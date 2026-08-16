"""
In-process multi-season stress test.

Imports app.py directly and drives the simulation through N full season
cycles using the same internal functions the Flask routes call, so no
server/networking is involved. Catches and logs every exception with a
full traceback but keeps going (skipping only the current cycle step),
so one bug doesn't stop us from finding the next one.
"""
import sys
import traceback
import random

sys.path.insert(0, ".")
import app as A  # noqa: E402

random.seed(1234)

FAILURES = []


def safe(label, fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception:
        tb = traceback.format_exc()
        FAILURES.append({"step": label, "traceback": tb})
        print(f"\n[FAIL] {label}\n{tb}\n")
        return None


def run_regular_season():
    print("  -> regular season...")
    guard = 0
    consecutive_errors = 0
    while not A.SIM_STATE["season_simulated"]:
        guard += 1
        if guard > 500:
            FAILURES.append({"step": "regular_season", "traceback": "guard limit -- possible infinite loop"})
            break
        before = len(FAILURES)
        safe("run_schedule_day", A.run_schedule_day)
        if len(FAILURES) > before:
            consecutive_errors += 1
            if consecutive_errors > 5:
                FAILURES.append({"step": "regular_season", "traceback": "aborting after 5 consecutive day-sim errors"})
                break
        else:
            consecutive_errors = 0
        if A.SIM_STATE.get("pending_offer"):
            # auto-decline to unpause, mirroring /api/respond_offer accept=False
            A.SIM_STATE["pending_offer"] = None


def run_play_in():
    if A.SIM_STATE.get("play_in", {}).get("active"):
        print("  -> play-in tournament...")
        for _ in range(20):
            if not A.SIM_STATE.get("play_in", {}).get("active"):
                break
            safe("simulate_play_in_games", A.simulate_play_in_games)


def run_playoffs():
    print("  -> playoffs...")
    guard = 0
    while not A.SIM_STATE.get("playoffs_complete"):
        guard += 1
        if guard > 40:
            FAILURES.append({"step": "playoffs", "traceback": "guard limit -- bracket never completed"})
            break
        r = str(A.SIM_STATE["current_round"])
        matchups = A.SIM_STATE["playoff_bracket"].get(r, [])
        if not matchups:
            FAILURES.append({"step": "playoffs", "traceback": f"no matchups found for round {r}"})
            break

        def sim_round():
            for m in matchups:
                if m["winner"] is None:
                    game_num = m["series"][0] + m["series"][1] + 1
                    home = m["team1"] if game_num in [1, 2, 5, 7] else m["team2"]
                    away = m["team2"] if game_num in [1, 2, 5, 7] else m["team1"]
                    box = A.simulate_game(home, away, True)
                    m["games"].append(box)
                    if box["home_score"] > box["away_score"]:
                        if home == m["team1"]:
                            m["series"][0] += 1
                        else:
                            m["series"][1] += 1
                    else:
                        if away == m["team1"]:
                            m["series"][0] += 1
                        else:
                            m["series"][1] += 1
                    if m["series"][0] == 4:
                        m["winner"] = m["team1"]
                    elif m["series"][1] == 4:
                        m["winner"] = m["team2"]

        safe("simulate_playoff_round", sim_round)
        if all(m["winner"] is not None for m in matchups):
            A.SIM_STATE["round_completed"] = True
            safe("advance_playoff_round", A.advance_playoff_round)


def run_offseason_and_draft():
    print("  -> offseason...")
    safe("process_offseason", A.process_offseason)

    print("  -> draft...")
    safe("start_draft", A.start_draft)
    d = A.SIM_STATE.get("draft", {})
    guard = 0
    while d.get("active") and d["index"] < len(d["order"]):
        guard += 1
        if guard > 200:
            FAILURES.append({"step": "draft", "traceback": "guard limit -- draft never finished"})
            break
        pick_id = d["order"][d["index"]]
        pk = A.SIM_STATE["draft_picks"][pick_id]
        if pk["current_team"] == A.SIM_STATE["user_team"]:
            prospect = safe("draft_best_available(user_pick)", A.draft_best_available)
            if prospect:
                safe("execute_draft_pick(user)", A.execute_draft_pick, prospect)
            else:
                break
        safe("advance_draft", A.advance_draft)
        d = A.SIM_STATE.get("draft", {})

    print("  -> auto-waive over-limit rosters...")
    safe("auto_waive_ai_rosters", A.auto_waive_ai_rosters)

    print("  -> start new season...")
    user_roster_size = len(A.team_roster(A.SIM_STATE["user_team"]))
    if user_roster_size > A.MAX_ROSTER:
        # mirror what a real user would be forced to do: waive down to the limit
        roster = A.team_roster(A.SIM_STATE["user_team"])
        roster_sorted = sorted(roster, key=lambda p: p.get("rating", 0))
        for p in roster_sorted[: user_roster_size - A.MAX_ROSTER]:
            safe("waive_player(auto-fix)", A.waive_player, p["name"])
    safe("start_new_season", A.start_new_season)


def main(seasons=3):
    for season in range(1, seasons + 1):
        print(f"\n=== SEASON CYCLE {season}/{seasons} (year={A.SIM_STATE.get('year')}) ===")
        run_regular_season()
        run_play_in()
        run_playoffs()
        run_offseason_and_draft()

    print(f"\n=== DONE: {len(FAILURES)} failures across {seasons} season cycles ===")
    for f in FAILURES:
        print("-" * 70)
        print(f["step"])
        print(f["traceback"][-1500:])
    return len(FAILURES)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    nfail = main(n)
    sys.exit(1 if nfail else 0)
