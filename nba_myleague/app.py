import os
import sys
import re
import copy
import random
import json
import webbrowser
from flask import Flask, render_template_string, jsonify, request

# Some Android Python runners (e.g. Pydroid 3) execute this file in a way
# where Python's __file__ resolves to a fake path like "<string>", which
# breaks Flask's default auto-detection of the templates/static folders
# (it normally looks next to __file__) and causes a TemplateNotFound error
# even though templates/index.html is right there on disk. A first attempt
# fell back to sys.argv[0] -- but that turned out to ALSO not point at the
# real script location under Pydroid (it's presumably some launcher path),
# so that still 404'd with the same error.
#
# Rather than keep guessing at more magic variables that might not be
# trustworthy on every Android runner, this searches the filesystem
# directly for wherever templates/index.html actually landed, starting
# from every plausible candidate directory (not just one), and reads the
# file ourselves instead of asking Flask/Jinja's own loader to find it.
# render_template_string() is then used to serve it, which completely
# bypasses Flask's template-folder resolution -- the exact thing that kept
# failing -- for the one page that actually needs it.
def _find_file(target_relpath, search_roots, max_depth=5, require_sibling=None, sibling_must_contain=None):
    """Look for `target_relpath` (e.g. 'templates/index.html') by walking
    outward from each root in `search_roots`, bounded in depth so this
    can't hang scanning the whole device. If `require_sibling` is given
    (e.g. 'app.py'), a match only counts if that file also exists in the
    same parent directory -- otherwise a generic path like
    'templates/index.html' can match some unrelated package's files
    elsewhere on a real device. That alone isn't enough, though: a real
    collision was found during testing where an unrelated installed PyPI
    package (confusingly also named with a generic 'app.py' + a
    'templates/index.html') matched. So when `sibling_must_contain` is
    given, the sibling file's actual content is checked for that unique
    marker string too, not just its filename. Returns the first fully
    verified match's full path, or None."""
    seen = set()
    for root in search_roots:
        if not root or root in seen or not os.path.isdir(root):
            continue
        seen.add(root)
        root_depth = root.rstrip(os.sep).count(os.sep)
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                if dirpath.rstrip(os.sep).count(os.sep) - root_depth > max_depth:
                    dirnames[:] = []
                    continue
                candidate = os.path.join(dirpath, target_relpath)
                if not os.path.isfile(candidate):
                    continue
                if require_sibling:
                    sibling_path = os.path.join(os.path.dirname(os.path.dirname(candidate)), require_sibling)
                    if not os.path.isfile(sibling_path):
                        continue
                    if sibling_must_contain:
                        try:
                            with open(sibling_path, "r", encoding="utf-8", errors="ignore") as sf:
                                if sibling_must_contain not in sf.read():
                                    continue
                        except OSError:
                            continue
                return candidate
        except (PermissionError, OSError):
            continue
    return None


def _app_base_dir():
    candidates = []
    try:
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    if sys.argv and sys.argv[0]:
        candidates.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    candidates.append(os.getcwd())
    for c in candidates:
        if c and os.path.isdir(os.path.join(c, "templates")):
            return c

    # None of the "trustworthy" variables panned out -- actively search for
    # it instead of assuming. Covers the common places a zip gets extracted
    # to on Android (Downloads, internal/external storage roots, home dir)
    # plus everywhere already tried above, in case the file is a level or
    # two off from where we expected.
    search_roots = list(dict.fromkeys(candidates + [
        os.path.expanduser("~"),
        "/storage/emulated/0",
        "/storage/emulated/0/Download",
        "/storage/emulated/0/Documents",
        "/sdcard",
        "/sdcard/Download",
    ]))
    found = _find_file(os.path.join("templates", "index.html"), search_roots, require_sibling="app.py", sibling_must_contain="SIM_STATE = {")
    if found:
        return os.path.dirname(os.path.dirname(found))
    return candidates[0] if candidates else os.getcwd()

_BASE_DIR = _app_base_dir()
_INDEX_HTML_PATH = os.path.join(_BASE_DIR, "templates", "index.html")
_INDEX_HTML_CACHE = None

def _load_index_html():
    """Read templates/index.html ourselves (with a couple of read-time
    fallback locations) rather than trusting Flask's template loader, and
    cache it -- avoids re-hitting the filesystem on every request."""
    global _INDEX_HTML_CACHE
    if _INDEX_HTML_CACHE is not None:
        return _INDEX_HTML_CACHE
    paths_to_try = [_INDEX_HTML_PATH]
    if not os.path.isfile(_INDEX_HTML_PATH):
        found = _find_file(os.path.join("templates", "index.html"), [
            os.getcwd(), os.path.expanduser("~"),
            "/storage/emulated/0", "/storage/emulated/0/Download", "/sdcard",
        ], require_sibling="app.py", sibling_must_contain="SIM_STATE = {")
        if found:
            paths_to_try.insert(0, found)
    for p in paths_to_try:
        try:
            with open(p, "r", encoding="utf-8") as f:
                _INDEX_HTML_CACHE = f.read()
                return _INDEX_HTML_CACHE
        except OSError:
            continue
    return None  # index() route below turns this into a clear error message, not a Jinja crash

app = Flask(
    __name__,
    template_folder=os.path.join(_BASE_DIR, "templates"),
    static_folder=os.path.join(_BASE_DIR, "static"),
)

# ==========================================
# SAVE / LOAD PERSISTENCE (JSON save slots)
# ==========================================
# UPGRADE: Database Persistence & Save/Load States. All league data previously
# lived only in the in-memory SIM_STATE dict for the lifetime of the process --
# closing the server lost the whole franchise. This adds simple, dependency-free
# JSON save-slot persistence so a GM can maintain multiple franchise saves and
# pick a session back up later. (A full SQLite/SQLAlchemy backing store would be
# a natural next step for concurrent multi-user play; JSON slots keep this
# single-process app's architecture unchanged while still solving the "I lost
# my franchise" problem.)
SAVE_DIR = os.path.join(_BASE_DIR, "saves")


def _ensure_save_dir():
    os.makedirs(SAVE_DIR, exist_ok=True)


def _safe_slot_name(slot_name):
    cleaned = "".join(c for c in str(slot_name) if c.isalnum() or c in ("-", "_"))
    return cleaned[:60] or "save"


def list_save_slots():
    _ensure_save_dir()
    slots = []
    for fname in sorted(os.listdir(SAVE_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(SAVE_DIR, fname)
        try:
            with open(path) as f:
                data = json.load(f)
            # UPGRADE: Save slot metadata polish. Instead of just team/year/
            # stage, surface a quick thumbnail line -- the user's current
            # record and their best active player -- so a save list is
            # actually scannable at a glance instead of every slot looking
            # identical until you load it.
            user_team = data.get("user_team")
            team_cfg = (data.get("teams") or {}).get(user_team, {})
            record = f"{team_cfg.get('wins', 0)}-{team_cfg.get('losses', 0)}" if team_cfg else None
            star_player = None
            best_rating = -1
            for p in (data.get("players") or {}).values():
                if p.get("team") == user_team and not p.get("retired") and p.get("rating", 0) > best_rating:
                    best_rating = p["rating"]
                    star_player = p.get("name")
            slots.append({
                "slot": fname[:-5],
                "user_team": user_team,
                "year": data.get("year"),
                "stage": data.get("stage"),
                "saved_at": os.path.getmtime(path),
                "record": record,
                "star_player": star_player,
                "star_player_rating": best_rating if star_player else None,
            })
        except Exception:
            continue
    return slots


def save_game(slot_name):
    _ensure_save_dir()
    slot_name = _safe_slot_name(slot_name)
    path = os.path.join(SAVE_DIR, f"{slot_name}.json")
    with open(path, "w") as f:
        json.dump(SIM_STATE, f)
    return {"success": True, "slot": slot_name}


def load_game(slot_name):
    slot_name = _safe_slot_name(slot_name)
    path = os.path.join(SAVE_DIR, f"{slot_name}.json")
    if not os.path.exists(path):
        return {"success": False, "reason": f"No save found named '{slot_name}'."}
    with open(path) as f:
        data = json.load(f)
    SIM_STATE.clear()
    SIM_STATE.update(data)
    SIM_STATE["save_slot_meta"] = {"slot": slot_name}
    return {"success": True, "slot": slot_name}


def delete_save(slot_name):
    slot_name = _safe_slot_name(slot_name)
    path = os.path.join(SAVE_DIR, f"{slot_name}.json")
    if os.path.exists(path):
        os.remove(path)
        return {"success": True}
    return {"success": False, "reason": "Save not found."}


# ==========================================
# PROCEDURAL DATA SEEDING ENGINE
# ==========================================
# NOTE: This sim uses an entirely fictional universe of players and franchises.
# We deliberately avoid generating real, named public figures (real athletes) with
# invented ratings, injuries, trades, and stats -- so every name and team below is made up.
FIRST_NAMES = ["Marcus", "Jalen", "Tyrese", "Devin", "Anthony", "Jordan", "Malik", "Isaiah", "Cameron",
               "Xavier", "DeAndre", "Trey", "Elijah", "Darius", "Kevin", "Andre", "Julian", "Terrence",
               "Bryce", "Nate", "Deshawn", "Miles", "Quentin", "Rashad", "Tobias", "Omari", "Grant",
               "Leon", "Corey", "Zion", "Reggie", "Marcel", "Silas", "Amari", "Deion", "Kaden",
               "Jaylen", "Kobe", "Damian", "Aaron", "Brandon", "Chris", "Dwayne", "Elliot", "Frank",
               "Gerald", "Harold", "Ivan", "Jerome", "Kyrie", "Lamar", "Maurice", "Nathaniel", "Otis",
               "Paxton", "Quincy", "Roman", "Sterling", "Tremaine", "Ulysses", "Vaughn", "Walker",
               "Xander", "Yusuf", "Zaire", "Antoine", "Braylon", "Cedric", "Dallas", "Emmanuel",
               "Foster", "Gideon", "Hakeem", "Immanuel", "Jaxon", "Keandre", "Landon", "Mekhi"]
LAST_NAMES = ["Johnson", "Williams", "Brooks", "Carter", "Reed", "Bailey", "Hunter", "Coleman", "Foster",
              "Price", "Simmons", "Ward", "Sanders", "Griffin", "Morales", "Patterson", "Holloway", "Marsh",
              "Booker", "Lawson", "Ellison", "Vance", "Whitfield", "Osei", "Delgado", "Kowalski",
              "Abernathy", "Reyes", "Sloan", "Voss", "Castellan", "Nakamura", "Okafor", "Beaumont",
              "Anderson", "Bennett", "Chandler", "Dawson", "Estrada", "Farrell", "Gallagher", "Hastings",
              "Ibarra", "Jefferson", "Kingston", "Lindqvist", "Mercer", "Novak", "Ortega", "Pierce",
              "Quintero", "Rutherford", "Sinclair", "Thackeray", "Underwood", "Vasquez", "Winslow",
              "Yamamoto", "Zeigler", "Ashby", "Blackwood", "Cortez", "Dumont", "Ekwueme", "Fairbanks",
              "Grady", "Huxtable", "Ingram", "Jaworski", "Kellerman", "Larsen", "Mbeki", "Norwood"]
POSITIONS = ["PG", "SG", "SF", "PF", "C"]

# Hardcoded, permanent 30-team fictional league split into East/West conferences
EAST_TEAMS = [
    "Gotham Knights", "Steel Harbor Ironclads", "Kolkata Reapers", "Crescent Bay Storm",
    "Old Meridian Ravens", "Vantage City Voltage", "Chennai Comets", "Kowloon Marauders",
    "Rio Grande Outlaws", "Hyderabad Sentinels", "Nova Haven Blaze", "Delhi Titans",
    "Shanghai Wolves", "Bengaluru Ballers", "Mumbai Vipers",
]
WEST_TEAMS = [
    "Neon City Phantoms", "Atlas Ridge Grizzlies", "Frostpine Yetis", "Sundown Valley Coyotes",
    "Ember Falls Dragons", "Lakeshore Sirens", "Copperfield Miners", "Ironwood Bison",
    "Salt Flats Scorpions", "Cobalt City Sharks", "Redrock Canyon Hawks", "Starlight Meteors",
    "Highland Peaks Rams", "Driftwood Bay Herons", "Union Square Sentries",
]
NBA_TEAMS = EAST_TEAMS + WEST_TEAMS
TEAM_CONFERENCE = {name: "East" for name in EAST_TEAMS}
TEAM_CONFERENCE.update({name: "West" for name in WEST_TEAMS})

# --- 2K-style team strategy option sets ---
OFFENSE_STYLES = ["Balanced", "Pace & Space", "Post-Up Heavy", "Iso-Heavy", "Motion Offense", "Fast Break Heavy",
                   "Pick-and-Roll Heavy", "Small Ball", "Grit and Grind"]
DEFENSE_STYLES = ["Man-to-Man", "2-3 Zone Package", "Full-Court Press", "Switch Everything", "Box-and-1",
                   "Triangle-and-2", "Drop Coverage", "Blitz the Pick-and-Roll"]
PACE_OPTIONS = ["Slow", "Balanced", "Fast"]
SHOOTING_WILLINGNESS_OPTIONS = ["Conservative", "Balanced", "Aggressive"]
REBOUNDING_STYLES = ["Crash Offensive Glass", "Balanced", "Get Back on Defense"]
SCORING_OPTIONS = ["Featured Scorer", "Balanced Attack", "Everyone Shoots"]

SALARY_CAP = 165.0

# ──────────────────── CONTRACT TYPES ─────────────────────────────────────────
CONTRACT_TYPES = {
    "Rookie Scale": {"desc": "Controlled first 4 years after draft", "color": "#38bdf8"},
    "Max Contract": {"desc": "Maximum salary deal", "color": "#facc15"},
    "Supermax":     {"desc": "Designated Rookie Extension", "color": "#f97316"},
    "Standard":     {"desc": "Negotiated deal", "color": "#94a3b8"},
    "MLE":          {"desc": "Mid-Level Exception", "color": "#a78bfa"},
    "Veteran Min":  {"desc": "League minimum", "color": "#64748b"},
    "Two-Way":      {"desc": "G-League dual contract", "color": "#34d399"},
}

def classify_contract(salary, years, rating, draft_year=None, current_year=None):
    scale = era_salary_scale()
    if salary <= 2.5 * scale:
        return "Veteran Min"
    if salary >= 35.0 * scale:
        return "Supermax" if rating >= 90 else "Max Contract"
    if draft_year and current_year and current_year - draft_year <= 4:
        return "Rookie Scale"
    if 8.0 * scale <= salary <= 12.5 * scale:
        return "MLE"
    return "Standard"
LUXURY_TAX_LINE = SALARY_CAP           # tax starts to bite the instant a team crosses the cap
TAX_APRON_ROOM = 22.0                  # how far over the cap a team can spend before hitting a hard apron
LUXURY_TAX_RATE = 1.75                 # $ owed in tax per $ spent over the line
MIN_ROSTER = 8
MAX_ROSTER = 15
START_YEAR = 2026
TRADE_DEADLINE_FRACTION = 0.78         # trades lock once this fraction of the schedule has been played


def era_salary_scale():
    """BUGFIX: every dollar-figure salary/contract formula in this file
    (player generation, rookie scale, free-agent asking price, veteran
    minimum, contract-type thresholds) was tuned around the Modern era's
    $165M cap and hardcoded as an absolute number. Switching to an earlier
    era only ever changed SALARY_CAP itself -- contracts kept coming out at
    full Modern size, so a 1984 team ($3.6M cap) would sign its very first
    superstar to what was effectively 5x the whole team's cap and stay
    permanently, drastically over the cap. This scales those formulas
    proportionally to whichever cap is currently active."""
    return round(SALARY_CAP / 165.0, 4)


# ──────────────────── RIVAL GM PERSONALITIES ─────────────────────────────────
GM_ARCHETYPES = {
    "Dealmaker":       {"desc": "Always on the phone. Loves blockbusters.", "trade_eagerness": 1.40, "threshold_adj": -0.06, "fa_pref": "star",     "rebuild_patience": 0.30, "emoji": "📞"},
    "Analytics GM":    {"desc": "Values efficiency and draft capital.",       "trade_eagerness": 0.85, "threshold_adj": +0.04, "fa_pref": "value",    "rebuild_patience": 0.70, "emoji": "📊"},
    "Win-Now GM":      {"desc": "Mortgages the future for one more shot.",    "trade_eagerness": 1.25, "threshold_adj": -0.04, "fa_pref": "veteran",  "rebuild_patience": 0.15, "emoji": "🏆"},
    "Patient Builder": {"desc": "Trusts the process. Young core, slow build.","trade_eagerness": 0.65, "threshold_adj": +0.02, "fa_pref": "young",    "rebuild_patience": 0.95, "emoji": "🌱"},
    "Loyalist":        {"desc": "Keeps his guys. Rarely trades homegrown.",   "trade_eagerness": 0.75, "threshold_adj":  0.00, "fa_pref": "balanced", "rebuild_patience": 0.60, "emoji": "🤝"},
}

# ==========================================
# FIXED LEAGUE SEED
# ==========================================
# UPGRADE: previously every fresh league re-rolled all 30 teams' 15-man rosters
# (names, ages, attributes, contracts...) from scratch using whatever random
# state happened to be active -- so no two "New Game" runs ever produced the
# same league, and there was no stable roster to balance the sim around or for
# a GM to get to know across saves. Seeding the RNG with a fixed constant
# immediately before roster/coach/low-level-pool generation (and restoring true
# randomness immediately after, exactly like the existing scouting-fog trick
# used in scouted_prospect_view) makes the 30 teams, their 15-man rosters, and
# every player's attributes fully deterministic and identical across every new
# league -- while gameplay (game sims, injuries, progression, AI decisions,
# etc.) still plays out randomly as before.
FIXED_LEAGUE_SEED = 20260725

# UPGRADE: Low-level depth pool. A fresh league previously had exactly 450
# players (30 teams x 15-man rosters) and nothing else -- free agency didn't
# have real up-and-down/fringe depth to sign until players started getting
# waived mid-season. Each team now also seeds LOW_LEVEL_POOL_PER_TEAM
# low-rated (fringe/two-way/tryout caliber) free agents into the pool at
# league creation, so a new league starts with 30*15 + 30*LOW_LEVEL_POOL_PER_TEAM
# players in the player pool instead of just 450.
LOW_LEVEL_POOL_PER_TEAM = 30

# ==========================================
# CAP EXCEPTIONS: Bird Rights / MLE / Vet Minimum
# ==========================================
BIRD_YEARS_REQUIRED = 3                # consecutive seasons with a team to earn full Bird Rights
EARLY_BIRD_YEARS_REQUIRED = 2          # a lesser exception after just 2 years
BIRD_APRON_ROOM = TAX_APRON_ROOM * 2.4   # Bird-rights re-signings can blow well past the normal apron
NON_TAXPAYER_MLE = 12.8                # full non-taxpayer Mid-Level Exception ($M)
TAXPAYER_MLE = 5.2                     # smaller MLE for teams already deep in the tax
VETERAN_MINIMUM_BASE = 2.0             # $M -- floor salary for a min-salary veteran signing
VETERAN_MINIMUM_PER_YEAR_SERVICE = 0.12  # small bump per year of service, capped below

# ==========================================
# TEAM MARKET SIZE (drives free-agent demand & willingness to give hometown discounts)
# ==========================================
LARGE_MARKET_TEAMS = {
    "Gotham Knights", "Shanghai Wolves", "Mumbai Vipers", "Neon City Phantoms",
    "Rio Grande Outlaws", "Kolkata Reapers", "Delhi Titans", "Bengaluru Ballers",
}
SMALL_MARKET_TEAMS = {
    "Frostpine Yetis", "Salt Flats Scorpions", "Copperfield Miners", "Ironwood Bison",
    "Union Square Sentries", "Highland Peaks Rams", "Driftwood Bay Herons",
}


def market_size_tier(team_name):
    if team_name in LARGE_MARKET_TEAMS:
        return "Large"
    if team_name in SMALL_MARKET_TEAMS:
        return "Small"
    return "Mid"


# ==========================================
# COACHING STAFF SYSTEM
# ==========================================
# Each system has a light schematic identity (its own affinity for an offense/
# defense style) and grants a direct in-game boost to the box-score categories
# tied to that system when a team's own strategy dials match it -- rewarding
# GMs who build a roster/scheme combo that actually fits their coach.
COACH_SYSTEMS = {
    "7 Seconds or Less": {
        "desc": "Up-tempo, three-happy pace-and-space system.",
        "affinity_offense": "Pace & Space", "affinity_pace": "Fast",
        "fg_bonus": 0.0, "tp_bonus": 0.02, "pace_bonus": 0.05, "ast_bonus": 0.0, "tov_mod": 1.0,
    },
    "Grit and Grind": {
        "desc": "Bruising, defense-and-rebounding-first identity.",
        "affinity_defense": "Man-to-Man", "affinity_rebounding": "Crash Offensive Glass",
        "fg_bonus": -0.005, "tp_bonus": -0.01, "def_fg_bonus": -0.015, "reb_bonus": 0.08, "tov_mod": 1.0,
    },
    "Motion Read-and-React": {
        "desc": "Constant off-ball movement, extra passing reads.",
        "affinity_offense": "Motion Offense",
        "fg_bonus": 0.01, "tp_bonus": 0.005, "ast_bonus": 0.06, "tov_mod": 0.95,
    },
    "Point-Center Hub": {
        "desc": "Offense runs through a playmaking big at the elbow/post.",
        "affinity_offense": "Post-Up Heavy",
        "fg_bonus": 0.012, "tp_bonus": 0.0, "ast_bonus": 0.04, "tov_mod": 1.0,
    },
    "Switch-Everything Defense": {
        "desc": "Versatile, position-less perimeter defense.",
        "affinity_defense": "Switch Everything",
        "fg_bonus": 0.0, "tp_bonus": 0.0, "def_fg_bonus": -0.02, "def_tp_bonus": -0.015, "tov_mod": 1.0,
    },
    "Small-Ball Spacing": {
        "desc": "Shoots and spaces the floor from every position.",
        "affinity_offense": "Pace & Space", "affinity_shooting": "Aggressive",
        "fg_bonus": 0.0, "tp_bonus": 0.018, "reb_bonus": -0.04, "tov_mod": 1.0,
    },
    "Pound-the-Rock Post Offense": {
        "desc": "Deliberate, post-heavy, low-turnover half-court system.",
        "affinity_offense": "Post-Up Heavy", "affinity_pace": "Slow",
        "fg_bonus": 0.01, "tp_bonus": -0.01, "tov_mod": 0.90,
    },
    "Full-Court Chaos Press": {
        "desc": "Relentless full-court pressure, forces mistakes.",
        "affinity_defense": "Full-Court Press",
        "fg_bonus": 0.0, "tp_bonus": 0.0, "opp_tov_bonus": 0.10, "tov_mod": 1.05,
    },
}
COACH_FIRST_NAMES = ["Marv", "Doug", "Nate", "Erik", "Steve", "Monty", "Frank", "Tyronn", "Chauncey", "Ime", "Wes", "Darvin"]
COACH_LAST_NAMES = ["Alston", "Baxter", "Crandall", "Duffy", "Ellerbe", "Farrow", "Grimaldi", "Huxley", "Ivers", "Jencks"]


def generate_coach_name():
    return f"{random.choice(COACH_FIRST_NAMES)} {random.choice(COACH_LAST_NAMES)}"


COACH_DIAL_FIELD_MAP = {
    "affinity_offense": "offensive_priority", "affinity_defense": "defensive_priority",
    "affinity_pace": "pace", "affinity_rebounding": "rebounding_style", "affinity_shooting": "shooting_willingness",
}


def recommended_dials_for_coach(team_name):
    """
    UPGRADE: Coach system 'recommended dials' hint. Reads the team's current
    coach's scheme affinities (the same fields sim_team_stats checks to award
    the coach's fg/tp/ast/reb/tov bonus) and returns which strategy dial
    values would actually activate the bonus, so a GM doesn't have to reverse
    -engineer COACH_SYSTEMS by hand.
    """
    coach_cfg = SIM_STATE.get("coaches", {}).get(team_name)
    if not coach_cfg:
        return {}
    sysdef = COACH_SYSTEMS.get(coach_cfg.get("system"), {})
    recs = {}
    for affinity_key, dial_field in COACH_DIAL_FIELD_MAP.items():
        if sysdef.get(affinity_key):
            recs[dial_field] = sysdef[affinity_key]
    return recs


def generate_coach_candidate():
    return {
        "id": f"coach_{random.randint(100000, 999999)}",
        "name": generate_coach_name(),
        "system": random.choice(list(COACH_SYSTEMS.keys())),
    }


COACH_MARKET_SIZE = 6


def refill_coach_market():
    """UPGRADE: Coach hiring/firing market. Keeps a standing pool of
    unemployed candidate coaches available to hire, topped back up to
    COACH_MARKET_SIZE any time it drops (after a hire, or on league seed)."""
    market = SIM_STATE.setdefault("coach_market", [])
    while len(market) < COACH_MARKET_SIZE:
        market.append(generate_coach_candidate())


def fire_coach(team_name):
    """UPGRADE: Coach hiring/firing UI + market. Releases the team's current
    coach back into the open market (as a re-hirable candidate elsewhere) and
    leaves the team without a coach -- no scheme bonus applies -- until a new
    one is hired. A minor chemistry hit reflects the disruption."""
    current = SIM_STATE["coaches"].get(team_name)
    if not current:
        return {"success": False, "reason": f"{team_name} doesn't currently have a coach on staff."}
    SIM_STATE["coaches"].pop(team_name, None)
    SIM_STATE["coach_market"].append({"id": f"coach_{random.randint(100000, 999999)}",
                                       "name": current["name"], "system": current["system"]})
    disrupt_chemistry(team_name, amount=4.0)
    push_news("🧑‍💼", f"{team_name} have fired head coach {current['name']}.", "front_office")
    return {"success": True, "fired": current["name"]}


def hire_coach(team_name, candidate_id):
    """UPGRADE: Coach hiring/firing UI + market. Hires a candidate off the
    coach market into team_name's vacancy (firing whoever's currently there,
    if anyone, first)."""
    market = SIM_STATE.setdefault("coach_market", [])
    candidate = next((c for c in market if c["id"] == candidate_id), None)
    if not candidate:
        return {"success": False, "reason": "That candidate is no longer available."}
    if SIM_STATE["coaches"].get(team_name):
        fire_coach(team_name)
    SIM_STATE["coach_market"] = [c for c in market if c["id"] != candidate_id]
    SIM_STATE["coaches"][team_name] = {"name": candidate["name"], "system": candidate["system"], "years_with_team": 0}
    refill_coach_market()
    push_news("🧑‍💼", f"{team_name} have hired {candidate['name']} ({candidate['system']}) as head coach.", "front_office")
    return {"success": True, "hired": candidate["name"], "system": candidate["system"]}

# ==========================================
# ATTRIBUTE / TENDENCY ARCHITECTURE (35 attrs, 20 tendencies)
# ==========================================
CATEGORY_ATTRS = {
    # UPGRADE PASS: +10 attributes on top of the existing 35 (45 total),
    # one or two per category so no single category dominates the card.
    "Finishing": ["Close Shot", "Driving Layup", "Driving Dunk", "Post Control", "Standing Dunk", "Post Hook",
                  "Contact Finishing"],
    "Shooting": ["Mid-Range", "Three-Point", "Free Throw", "Shot IQ", "Off-the-Dribble",
                 "Corner Shooting"],
    "Playmaking": ["Passing Accuracy", "Ball Handling", "Speed With Ball", "Vision", "Ball Security",
                   "Pick & Roll Passing"],
    "Defense": ["Interior Defense", "Perimeter Defense", "Steal", "Block", "Lateral Quickness", "Help Defense IQ",
                "Pick & Roll Defense", "Post Defense", "On-Ball Defense IQ", "Weakside Rim Protection"],
    "Rebounding": ["Offensive Rebound", "Defensive Rebound", "Boxout", "Rebound Positioning"],
    "Physical": ["Speed", "Strength", "Vertical", "Stamina", "Hustle", "Durability",
                 "Agility", "Length"],
    "Intangibles": ["Clutch Factor", "Consistency", "Leadership", "Basketball IQ"],
}
ALL_ATTRIBUTES = [a for cat in CATEGORY_ATTRS.values() for a in cat]  # 45 total

TENDENCY_LIST = ["Shoot 3PT", "Shoot Mid-Range", "Drive to Rim", "Post Up",
                  "Pass", "Iso", "Crash Offensive Glass", "Draw Fouls",
                  "Catch & Shoot", "Spot Up", "Transition", "Post Fade",
                  "Pick & Roll Ball Handler", "Help Defense",
                  "Clutch Shooting", "Cut to Basket", "Screen Setting",
                  "Fast Break Finish", "Contest Shots", "Take Charges",
                  # UPGRADE PASS: +20 tendencies on top of the existing 20 (40 total)
                  "Attack Closeouts", "Step-Back Jumper", "Post Spin Move", "Dribble Hand-Off",
                  "Off-Ball Movement", "Kick Out Pass", "Isolation Post-Up", "And-1 Attempts",
                  "Deny Passing Lanes", "Zone Positioning", "Switch on Defense", "Backdoor Cuts",
                  "Putback Attempts", "Late Clock Shots", "Rim Protection Tendency", "Full-Court Press",
                  "Corner Three Attempts", "Double Team Trigger", "Fast Break Ball Handling", "Flashy Passing"]

POSITION_CATEGORY_OFFSET = {
    "PG": {"Finishing": -3, "Shooting": 2,  "Playmaking": 10, "Defense": -2, "Rebounding": -10, "Physical": 4,  "Intangibles": 0},
    "SG": {"Finishing": 0,  "Shooting": 8,  "Playmaking": 2,  "Defense": 0,  "Rebounding": -8,  "Physical": 2,  "Intangibles": 0},
    "SF": {"Finishing": 2,  "Shooting": 2,  "Playmaking": 0,  "Defense": 2,  "Rebounding": -2,  "Physical": 2,  "Intangibles": 0},
    "PF": {"Finishing": 4,  "Shooting": -4, "Playmaking": -6, "Defense": 4,  "Rebounding": 6,   "Physical": 0,  "Intangibles": 0},
    "C":  {"Finishing": 6,  "Shooting": -10,"Playmaking": -10,"Defense": 6,  "Rebounding": 12,  "Physical": -2, "Intangibles": 0},
}

_NAME_REGISTRY = set()


def clamp(v, lo=25, hi=99):
    return max(lo, min(hi, int(round(v))))


def safe_int(val, default=0):
    """Coerce a request arg to int without ever raising -- several UI tools
    let the user leave a numeric field blank or type something non-numeric,
    which used to blow up with a raw 500 debug page (ValueError/TypeError)
    instead of a normal JSON error. Blank string, None, and already-int
    values all resolve sensibly; anything else falls back to `default`."""
    if val is None or val == "":
        return default
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def safe_float(val, default=0.0):
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def unique_name(suffix=""):
    for _ in range(200):
        name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}{suffix}"
        if name not in _NAME_REGISTRY:
            _NAME_REGISTRY.add(name)
            return name
    # Fallback: the ~5,000-combo pool is exhausted (a very long-running
    # league). Disambiguate with a real-looking generational suffix
    # (Jr./II/III/...) instead of a bare number, which read as broken --
    # e.g. "Silas Coleman 182" -- to anyone scanning the draft board.
    ordinals = ["Jr.", "II", "III", "IV", "V", "VI"]
    for ordinal in ordinals:
        name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)} {ordinal}{suffix}"
        if name not in _NAME_REGISTRY:
            _NAME_REGISTRY.add(name)
            return name
    # Truly exhausted (thousands of players deep into one league's history):
    # last resort still reads as a name, not a debug artifact.
    name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)} {random.choice(ordinals)}-{random.randint(2, 9)}{suffix}"
    _NAME_REGISTRY.add(name)
    return name


def gen_attributes(base_rating, position):
    attrs = {}
    mods = POSITION_CATEGORY_OFFSET[position]
    for cat, alist in CATEGORY_ATTRS.items():
        off = mods[cat]
        for a in alist:
            val = random.gauss(base_rating + off, 7)
            attrs[a] = clamp(val)
    return attrs


def calc_rating(attrs):
    return round(sum(attrs.values()) / len(attrs))


def derive_categories(attrs):
    def m(keys):
        return sum(attrs[k] for k in keys) / len(keys)
    return {
        "Inside": m(CATEGORY_ATTRS["Finishing"]),
        "Outside": m(CATEGORY_ATTRS["Shooting"]),
        "Playmaking": m(CATEGORY_ATTRS["Playmaking"]),
        "Defense": m(CATEGORY_ATTRS["Defense"]),
        "Rebounding": m(CATEGORY_ATTRS["Rebounding"]),
        "Athleticism": m(CATEGORY_ATTRS["Physical"]),
        "Intangibles": m(CATEGORY_ATTRS["Intangibles"]),
    }


# ==========================================
# BADGES -- NBA 2K-style earned traits, computed from attribute clusters.
# Tiers scale with how far above the threshold the underlying attributes are.
# ==========================================
BADGE_DEFS = [
    {"key": "sharpshooter", "name": "Sharpshooter", "icon": "🎯", "attrs": ["Three-Point"],
     "desc": "Knocks down threes at an elite clip on catch-and-shoot and pull-up looks."},
    {"key": "slasher", "name": "Slasher", "icon": "⚡", "attrs": ["Driving Layup", "Driving Dunk"],
     "desc": "Explosive finisher who consistently converts at the rim in traffic."},
    {"key": "rim_protector", "name": "Rim Protector", "icon": "🛡️", "attrs": ["Block", "Interior Defense"],
     "desc": "Alters shots and swats attempts around the basket."},
    {"key": "lockdown", "name": "Lockdown Defender", "icon": "🔒", "attrs": ["Perimeter Defense", "Lateral Quickness"],
     "desc": "Shuts down opposing ball-handlers on the perimeter."},
    {"key": "glass_cleaner", "name": "Glass Cleaner", "icon": "🧹", "attrs": ["Offensive Rebound", "Defensive Rebound"],
     "desc": "Dominates the boards on both ends of the floor."},
    {"key": "dimer", "name": "Dimer", "icon": "🧠", "attrs": ["Passing Accuracy", "Vision"],
     "desc": "Elite table-setter who consistently creates good looks for teammates."},
    {"key": "post_menace", "name": "Post Menace", "icon": "💪", "attrs": ["Post Control"],
     "desc": "Bullies smaller defenders with back-to-the-basket scoring."},
    {"key": "pickpocket", "name": "Pick-Pocket", "icon": "🖐️", "attrs": ["Steal"],
     "desc": "Elite ball-hawk who consistently generates takeaways."},
    {"key": "iron_man", "name": "Iron Man", "icon": "🦾", "attrs": ["Durability"],
     "desc": "Rarely misses time -- a much lower baseline injury risk."},
    {"key": "high_motor", "name": "High Motor", "icon": "🔥", "attrs": ["Hustle"],
     "desc": "Non-stop energy that shows up in loose balls, closeouts, and effort plays."},
    {"key": "brick_wall", "name": "Brick Wall", "icon": "🧱", "attrs": ["Strength"],
     "desc": "Powerful frame that wins physical, bump-and-grind matchups."},
]

BADGE_TIER_ORDER = {"HOF": 4, "Gold": 3, "Silver": 2, "Bronze": 1}


def badge_tier_for(value):
    if value >= 95:
        return "HOF"
    if value >= 90:
        return "Gold"
    if value >= 85:
        return "Silver"
    if value >= 80:
        return "Bronze"
    return None


def compute_badges(p):
    """Derive a player's 2K-style badge list from his attribute clusters. Called
    at creation and refreshed whenever ratings change (progression/offseason)."""
    attrs = p["attributes"]
    badges = []
    for b in BADGE_DEFS:
        avg = sum(attrs[a] for a in b["attrs"]) / len(b["attrs"])
        tier = badge_tier_for(avg)
        if tier:
            badges.append({"key": b["key"], "name": b["name"], "icon": b["icon"],
                            "tier": tier, "desc": b["desc"], "rating": round(avg)})
    badges.sort(key=lambda x: BADGE_TIER_ORDER[x["tier"]], reverse=True)
    return badges


def gen_tendencies(position, attrs):
    t = {}
    t["Shoot 3PT"] = clamp(random.gauss(35 + (attrs["Three-Point"] - 70) * 0.6 +
                                         (10 if position in ["PG", "SG"] else -12 if position == "C" else 0), 10), 5, 99)
    t["Shoot Mid-Range"] = clamp(random.gauss(30 + (attrs["Mid-Range"] - 70) * 0.5, 10), 5, 99)
    t["Drive to Rim"] = clamp(random.gauss(40 + (attrs["Ball Handling"] - 70) * 0.4 +
                                            (10 if position in ["PG", "SG"] else 0), 10), 5, 99)
    t["Post Up"] = clamp(random.gauss(20 + (attrs["Post Control"] - 70) * 0.5 +
                                       (22 if position in ["C", "PF"] else -10), 10), 2, 99)
    t["Pass"] = clamp(random.gauss(35 + (attrs["Passing Accuracy"] - 70) * 0.5 +
                                    (18 if position == "PG" else 0), 10), 5, 99)
    t["Iso"] = clamp(random.gauss(25, 10), 5, 90)
    t["Crash Offensive Glass"] = clamp(random.gauss(30 + (attrs["Offensive Rebound"] - 70) * 0.5 +
                                                      (16 if position in ["C", "PF"] else -6), 10), 5, 99)
    t["Draw Fouls"] = clamp(random.gauss(30 + (attrs["Strength"] - 70) * 0.3, 10), 5, 90)
    t["Catch & Shoot"] = clamp(random.gauss(35 + (attrs["Three-Point"] - 70) * 0.5 +
                                             (attrs["Shot IQ"] - 70) * 0.3, 10), 5, 99)
    t["Spot Up"] = clamp(random.gauss(30 + (attrs["Shot IQ"] - 70) * 0.4 +
                                       (8 if position in ["SF", "SG"] else 0), 10), 5, 99)
    t["Transition"] = clamp(random.gauss(35 + (attrs["Speed"] - 70) * 0.4, 10), 5, 99)
    t["Post Fade"] = clamp(random.gauss(20 + (attrs["Post Control"] - 70) * 0.5 +
                                         (18 if position in ["C", "PF"] else -12), 10), 2, 99)
    t["Pick & Roll Ball Handler"] = clamp(random.gauss(30 + (attrs["Ball Handling"] - 70) * 0.4 +
                                                        (18 if position == "PG" else 0), 10), 5, 99)
    t["Help Defense"] = clamp(random.gauss(35 + (attrs["Help Defense IQ"] - 70) * 0.5, 10), 5, 99)
    t["Clutch Shooting"] = clamp(random.gauss(30 + (attrs["Clutch Factor"] - 70) * 0.6 +
                                               (attrs["Shot IQ"] - 70) * 0.2, 10), 5, 99)
    t["Cut to Basket"] = clamp(random.gauss(30 + (attrs["Speed"] - 70) * 0.3 +
                                             (attrs["Vision"] - 70) * 0.2, 10), 5, 99)
    t["Screen Setting"] = clamp(random.gauss(25 + (attrs["Strength"] - 70) * 0.4 +
                                              (18 if position in ["C", "PF"] else -8), 10), 5, 99)
    t["Fast Break Finish"] = clamp(random.gauss(30 + (attrs["Speed"] - 70) * 0.4 +
                                                 (attrs["Driving Dunk"] - 70) * 0.2, 10), 5, 99)
    t["Contest Shots"] = clamp(random.gauss(30 + (attrs["Perimeter Defense"] - 70) * 0.4 +
                                             (attrs["Hustle"] - 70) * 0.2, 10), 5, 99)
    t["Take Charges"] = clamp(random.gauss(25 + (attrs["Help Defense IQ"] - 70) * 0.3 +
                                            (attrs["Strength"] - 70) * 0.2, 10), 5, 90)

    # UPGRADE PASS: +20 tendencies, each tied to real attributes/position
    # the same way the original 20 are, instead of just filling in flat
    # random noise -- so they actually differentiate players like the rest
    # of the tendency set does.
    t["Attack Closeouts"] = clamp(random.gauss(30 + (attrs["Speed With Ball"] - 70) * 0.4 +
                                                (attrs["Driving Layup"] - 70) * 0.2, 10), 5, 99)
    t["Step-Back Jumper"] = clamp(random.gauss(20 + (attrs["Off-the-Dribble"] - 70) * 0.5 +
                                                (10 if position in ["SG", "SF"] else -8), 10), 5, 99)
    t["Post Spin Move"] = clamp(random.gauss(18 + (attrs["Post Control"] - 70) * 0.5 +
                                              (16 if position in ["C", "PF"] else -10), 10), 2, 99)
    t["Dribble Hand-Off"] = clamp(random.gauss(28 + (attrs["Pick & Roll Passing"] - 70) * 0.4, 10), 5, 99)
    t["Off-Ball Movement"] = clamp(random.gauss(30 + (attrs["Basketball IQ"] - 70) * 0.4 +
                                                 (attrs["Speed"] - 70) * 0.2, 10), 5, 99)
    t["Kick Out Pass"] = clamp(random.gauss(30 + (attrs["Vision"] - 70) * 0.4 +
                                             (attrs["Passing Accuracy"] - 70) * 0.3, 10), 5, 99)
    t["Isolation Post-Up"] = clamp(random.gauss(18 + (attrs["Post Control"] - 70) * 0.3 +
                                                 (attrs["Strength"] - 70) * 0.2, 10), 2, 95)
    t["And-1 Attempts"] = clamp(random.gauss(25 + (attrs["Contact Finishing"] - 70) * 0.5, 10), 5, 95)
    t["Deny Passing Lanes"] = clamp(random.gauss(30 + (attrs["Steal"] - 70) * 0.4 +
                                                  (attrs["On-Ball Defense IQ"] - 70) * 0.3, 10), 5, 99)
    t["Zone Positioning"] = clamp(random.gauss(30 + (attrs["Help Defense IQ"] - 70) * 0.4 +
                                                (attrs["Basketball IQ"] - 70) * 0.2, 10), 5, 99)
    t["Switch on Defense"] = clamp(random.gauss(30 + (attrs["Lateral Quickness"] - 70) * 0.4 +
                                                 (attrs["Agility"] - 70) * 0.2, 10), 5, 99)
    t["Backdoor Cuts"] = clamp(random.gauss(28 + (attrs["Vision"] - 70) * 0.3 +
                                             (attrs["Speed"] - 70) * 0.2, 10), 5, 99)
    t["Putback Attempts"] = clamp(random.gauss(28 + (attrs["Offensive Rebound"] - 70) * 0.5 +
                                                (14 if position in ["C", "PF"] else -6), 10), 5, 99)
    t["Late Clock Shots"] = clamp(random.gauss(25 + (attrs["Clutch Factor"] - 70) * 0.4 +
                                                (attrs["Shot IQ"] - 70) * 0.2, 10), 5, 95)
    t["Rim Protection Tendency"] = clamp(random.gauss(25 + (attrs["Weakside Rim Protection"] - 70) * 0.5 +
                                                       (16 if position in ["C", "PF"] else -10), 10), 2, 99)
    t["Full-Court Press"] = clamp(random.gauss(25 + (attrs["Stamina"] - 70) * 0.3 +
                                                (attrs["Lateral Quickness"] - 70) * 0.2, 10), 5, 95)
    t["Corner Three Attempts"] = clamp(random.gauss(28 + (attrs["Corner Shooting"] - 70) * 0.5, 10), 5, 99)
    t["Double Team Trigger"] = clamp(random.gauss(22 + (attrs["Help Defense IQ"] - 70) * 0.35 +
                                                   (attrs["Basketball IQ"] - 70) * 0.2, 10), 5, 90)
    t["Fast Break Ball Handling"] = clamp(random.gauss(28 + (attrs["Speed With Ball"] - 70) * 0.4 +
                                                        (14 if position == "PG" else 0), 10), 5, 99)
    t["Flashy Passing"] = clamp(random.gauss(20 + (attrs["Vision"] - 70) * 0.3 +
                                              (attrs["Leadership"] - 70) * 0.1, 10), 5, 95)

    return t


def potential_grade(pot):
    if pot >= 93: return "A+"
    if pot >= 88: return "A"
    if pot >= 83: return "A-"
    if pot >= 78: return "B+"
    if pot >= 72: return "B"
    if pot >= 65: return "C+"
    return "C"


def backfill_career_history(p, start_year):
    """Veteran players generated at league seed (or added to keep a roster at
    the minimum size) previously had at most a single fabricated season on
    record, so a 33-year-old vet's Career tab looked identical to a rookie's.
    Give them a plausible multi-season history -- and, for genuine stars, a
    scattering of past awards -- sized to their age.

    BUGFIX: seasons_to_backfill used to be an independent random 3-7 roll,
    completely decoupled from the player's actual years_pro / draft_year --
    which is what the Career Timeline's "Drafted <year>" entry is built
    from (see make_player()). A vet drafted 7 years ago could randomly only
    get 3 backfilled seasons, leaving a visible unexplained gap on their own
    player card between "Drafted 2019" and a Season-by-Season table that
    only went back to 2023. Backfill the player's FULL years_pro instead
    (capped at a sane 15 to avoid absurd data volume for very old vets) so
    the earliest season on record always lines up with their real draft
    year, not a random shorter window."""
    years_pro = max(0, p["age"] - 20)
    seasons_to_backfill = min(years_pro, 15)
    history = []
    base_rating = p["rating"]
    for i in range(seasons_to_backfill, 0, -1):
        yr = start_year - i
        # Ratings wobble year to year; early-career seasons trend a bit lower.
        drift = -6 if i > seasons_to_backfill - 2 else random.randint(-4, 3)
        season_rating = clamp(base_rating + drift + random.randint(-5, 5), 45, 99)
        ppg = round(max(1.0, (season_rating - 42) * 0.42 + random.uniform(-1.5, 1.5)), 1)
        rpg = round(max(0.5, (season_rating - 48) * 0.15 + random.uniform(-0.8, 0.8)), 1)
        apg = round(max(0.3, (season_rating - 48) * 0.11 + random.uniform(-0.8, 0.8)), 1)
        history.append({"year": yr, "PPG": ppg, "RPG": rpg, "APG": apg})
        if season_rating >= 92 and random.random() < 0.45:
            p["career_awards"].append({"year": yr, "award": random.choice(["MVP", "All-NBA First Team", "All-Star"])})
        elif season_rating >= 87 and random.random() < 0.30:
            p["career_awards"].append({"year": yr, "award": random.choice(["All-Star", "All-NBA Second Team", "All-NBA Third Team"])})
        elif season_rating >= 80 and random.random() < 0.12:
            p["career_awards"].append({"year": yr, "award": "All-Star"})
    p["history"] = history

    # BUGFIX: career_highs was left at its default all-zero dict here, even
    # for a 15-year vet with a full fabricated season history above. Since
    # record_game_stats() flags ANY stat that beats the stored high as a
    # new "career high", that meant literally every veteran in the league
    # got a career-high news blurb for their first game of a fresh league
    # (and often several more per stat over the first few games) --
    # trivially true since 0 loses to almost anything, but nonsense given
    # they've supposedly played 5-15 real seasons already. Seed plausible
    # single-game highs from the best fabricated season on record instead,
    # so only a genuinely standout game clears the bar going forward.
    if history:
        best_season = max(history, key=lambda s: s["PPG"])
        pts_high = round(best_season["PPG"] * random.uniform(1.9, 2.6) + 4)
        p["career_highs"] = {
            "PTS": pts_high,
            "REB": round(best_season["RPG"] * random.uniform(1.8, 2.5) + 3),
            "AST": round(best_season["APG"] * random.uniform(1.7, 2.4) + 2),
            "STL": random.randint(3, 6) + (2 if base_rating >= 85 else 0),
            "BLK": random.randint(2, 5) + (2 if base_rating >= 85 and p.get("position") in ("PF", "C") else 0),
            "TOV": random.randint(4, 9),
            "FGM": max(1, round(pts_high * random.uniform(0.32, 0.42))),
            "FGA": max(1, round(pts_high * random.uniform(0.62, 0.82))),
            "3PM": random.randint(3, 6) + (2 if base_rating >= 85 else 0),
            "3PA": 0,  # filled in just below, needs 3PM first
        }
        p["career_highs"]["3PA"] = p["career_highs"]["3PM"] + random.randint(2, 7)
    return p


# UPGRADE: Physical attributes (height/weight/wingspan). Purely cosmetic/
# flavor data -- doesn't feed into ratings or sim math -- but it's the kind
# of thing a real scouting report has and this sim was missing entirely.
# Rough real-NBA-shaped ranges per position, in inches/lbs.
PHYSICAL_RANGES = {
    "PG": {"height": (70, 77), "weight": (170, 205)},
    "SG": {"height": (73, 79), "weight": (185, 220)},
    "SF": {"height": (76, 81), "weight": (200, 235)},
    "PF": {"height": (78, 83), "weight": (215, 255)},
    "C":  {"height": (80, 87), "weight": (230, 290)},
}


def gen_physicals(position):
    lo, hi = PHYSICAL_RANGES.get(position, PHYSICAL_RANGES["SF"])["height"]
    height_in = round(clamp(random.gauss((lo + hi) / 2, (hi - lo) / 4), lo - 2, hi + 2))
    wlo, whi = PHYSICAL_RANGES.get(position, PHYSICAL_RANGES["SF"])["weight"]
    weight_lbs = round(clamp(random.gauss((wlo + whi) / 2, (whi - wlo) / 4), wlo - 10, whi + 10))
    # NBA wingspans typically run a few inches longer than height; centers
    # and forwards trend toward the long end more than guards do.
    wing_bonus = random.gauss(3.5 if position in ("C", "PF") else 2.0, 1.2)
    wingspan_in = round(height_in + max(0, wing_bonus))
    return height_in, weight_lbs, wingspan_in


def format_height(inches):
    feet, inch = divmod(int(round(inches)), 12)
    return f"{feet}'{inch}\""


# UPGRADE: Multiple eligible positions. Real players routinely slide up or
# down a slot (a combo guard playing the 1 or the 2, a stretch four who can
# man the 5 in small-ball lineups) -- previously every player was locked to
# exactly one position, which is also what caused rosters to accumulate
# lopsided depth (four point guards, one ancient center) since the AI/user
# had no visibility into flexible fits. ~45% of players get one adjacent
# secondary position; a small share of forwards/bigs get real positional
# versatility (PF/C dual-eligible, etc).
def gen_secondary_position(position, attrs):
    idx = POSITIONS.index(position)
    neighbors = [POSITIONS[i] for i in (idx - 1, idx + 1) if 0 <= i < len(POSITIONS)]
    if not neighbors:
        return None
    # Higher IQ/versatility-flavored attributes make a second position more likely.
    chance = 0.45 + (0.15 if attrs.get("Vision", 50) >= 75 else 0)
    if random.random() < chance:
        return random.choice(neighbors)
    return None


def make_player(position, age, base_rating, potential, team, year, draft_year, tier="vet"):
    attrs = gen_attributes(base_rating, position)
    rating = calc_rating(attrs)
    tendencies = gen_tendencies(position, attrs)
    height_in, weight_lbs, wingspan_in = gen_physicals(position)
    secondary_position = gen_secondary_position(position, attrs)
    # UPGRADE: Player agent personalities. Previously every player negotiated
    # off one universal formula (market size / win% / role) -- now each
    # player also has a distinct negotiating temperament that colors those
    # same numbers instead of replacing them: a Loyalty guy discounts hard
    # to stay put (and charges a premium to be lured away), a Business guy
    # just chases whoever pays most regardless of context, and a Ring
    # Chaser will take a real discount to join a winner and won't sign
    # cheap with a loser. See negotiate_salary() and handle_free_agency_offer().
    agent_personality = random.choices(
        ["Loyalty", "Business", "Ring Chaser", "Balanced"],
        weights=[0.25, 0.3, 0.2, 0.25], k=1)[0]
    salary = round(max(1.0, (rating - 55) * 0.5 + random.uniform(-1.0, 1.5)) * era_salary_scale(), 1)
    years_left = random.randint(1, 4)
    contract = {"years_left": years_left, "salary": salary,
                "contract_type": classify_contract(salary, years_left, rating, draft_year, year)} if team else None
    # UPGRADE: No-trade clauses. A real contract term (won by leverage at
    # signing time), distinct from the GM-settable "untradeable" flag --
    # this isn't something the user can toggle, it's earned by being an
    # elite, established veteran. Real NBA no-trade clauses are rare and
    # essentially only go to accomplished, long-tenured stars, so this only
    # rolls for rating 85+ players age 28+, and even then only ~20% of the
    # time.
    if contract and rating >= 85 and age >= 28 and random.random() < 0.20:
        contract["no_trade_clause"] = True
    suffix = " Jr." if tier == "rookie" and random.random() < 0.12 else ""
    player = {
        "name": unique_name(suffix),
        "team": team,
        "position": position,
        "secondary_position": secondary_position,
        "agent_personality": agent_personality,
        "height_in": height_in,
        "weight_lbs": weight_lbs,
        "wingspan_in": wingspan_in,
        "age": age,
        "jersey": random.randint(0, 55),
        "rating": rating,
        "potential": potential,
        "potential_grade": potential_grade(potential),
        "attributes": attrs,
        "tendencies": tendencies,
        "salary": salary,
        "contract": contract,
        "minutes": 0,
        "draft_year": draft_year,
        "retired": False,
        "injury": None,
        "stats": {"FGM": 0, "FGA": 0, "3PM": 0, "3PA": 0, "FTM": 0, "FTA": 0, "PTS": 0, "REB": 0, "AST": 0, "STL": 0, "BLK": 0, "TOV": 0, "GP": 0, "MIN": 0},
        "history": [],
        "fatigue": 0,          # 0 = fully fresh, 100 = exhausted. Driven by the Stamina attribute.
        "morale": 70,          # 0-100 happiness. Driven by playing time, winning, contract situation.
        "form": 0.0,           # -1.0 (ice cold) .. +1.0 (heating up). Rolling hot/cold streak modifier.
        "asking_price": None,
        "career_awards": [],
        "injury_history_count": 0,   # lifetime injury count -- feeds the "injury prone" escalation
        "injury_prone": False,
        "seasons_with_team": 0,       # continuity tracker for team chemistry
        "career_totals": {"FGM": 0, "FGA": 0, "3PM": 0, "3PA": 0, "FTM": 0, "FTA": 0, "PTS": 0, "REB": 0, "AST": 0,
                           "STL": 0, "BLK": 0, "TOV": 0, "GP": 0, "MIN": 0, "SEASONS": 0},
        "two_way": False,
        # UPGRADE: actual accrued NBA service time (see veteran_minimum_salary),
        # instead of only ever approximating it from age. Backfilled at
        # creation to roughly match a player's fabricated career history, then
        # incremented for real once per season in process_offseason.
        "seasons_played": max(0, age - 22),
        # UPGRADE: player morale/trade-request system -- None, or
        # {"since_day", "since_year", "reason"} once a player is unhappy
        # enough to formally ask out. Cleared on trade/waive/re-sign.
        "trade_request": None,
        "low_morale_streak": 0,
        # UPGRADE: injury system depth -- which body region was last hurt and
        # how many games remain in the elevated re-injury risk window after
        # returning from it (see maybe_injure_players / INJURY_TYPES).
        "injury_region": None,
        "reinjury_window": 0,
        "retired_number": False,
        # UPGRADE: Player personalities — affects locker room chemistry and on-court behaviour
        "personality_trait": _gen_personality_trait(attrs, age),
        # UPGRADE: Player timeline — career milestone events (Draft, All-Star, Champion, MVP, Retire)
        "timeline": [{"year": draft_year, "event": "Drafted", "icon": "🏀"}],
        # ===== UPGRADE BATCH 3 additions =====
        "accessories": _gen_accessories(),
        "shoe_brand": random.choice(SHOE_BRANDS),
        "portrait_seed": random.randint(1, 999999),
        "aging_curve": _gen_aging_curve(age),
        "season_goal": random.choice(PLAYER_GOAL_TYPES),
        "goal_progress": 0,
        "career_highs": {"PTS": 0, "REB": 0, "AST": 0, "STL": 0, "BLK": 0, "TOV": 0, "FGM": 0, "FGA": 0, "3PM": 0, "3PA": 0},
        "triple_doubles": 0,
    }
    player["badges"] = compute_badges(player)
    return player


# ==========================================================
# UPGRADE BATCH 3 -- new data pools (accessories/shoes/aging/goals)
# ==========================================================
SHOE_BRANDS = ["Nike", "Jordan Brand", "Adidas", "Puma", "Under Armour", "New Balance", "Li-Ning", "Anta"]
ACCESSORY_POOL = ["Shooting Sleeve", "Headband", "Leg Sleeves", "Compression Tights", "Wristband", "Knee Sleeve", "Mouthguard", "Goggles"]


def _gen_accessories():
    n = random.choices([0, 1, 2], weights=[0.35, 0.45, 0.20])[0]
    return random.sample(ACCESSORY_POOL, k=n) if n else []


AGING_CURVES = {
    "Early Bloomer":   {"peak_age": (23, 26), "decline_rate": 1.0, "desc": "Breaks out young, ages on the normal curve after."},
    "Late Bloomer":    {"peak_age": (28, 31), "decline_rate": 0.8, "desc": "Slow start, keeps improving into his late 20s."},
    "Superstar Peak":  {"peak_age": (26, 30), "decline_rate": 0.7, "desc": "Elite ceiling, ages gracefully."},
    "Injury Decline":  {"peak_age": (24, 27), "decline_rate": 1.6, "desc": "Wear and tear catches up fast once he tips over."},
    "Normal Aging":    {"peak_age": (25, 29), "decline_rate": 1.0, "desc": "Standard, unremarkable aging pattern."},
}


def _gen_aging_curve(age):
    weights = {"Early Bloomer": 0.2, "Late Bloomer": 0.15, "Superstar Peak": 0.12, "Injury Decline": 0.13, "Normal Aging": 0.4}
    return random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]


PLAYER_GOAL_TYPES = [
    "Earn a starting role", "Make the All-Star team", "Win MVP", "Sign a max contract",
    "Win a championship", "Average 20+ PPG", "Lead the league in assists", "Make an All-Defensive team",
]


# All personality traits and their effects on team chemistry/performance
PERSONALITY_TRAITS = {
    "Leader":          {"emoji": "👑", "chemistry_bonus": +6, "morale_spread": True,  "clutch_boost": +0.06},
    "Gym Rat":         {"emoji": "🏋", "chemistry_bonus": +3, "morale_spread": False, "clutch_boost": +0.02, "dev_bonus": 1.5},
    "Mentor":          {"emoji": "📚", "chemistry_bonus": +5, "morale_spread": True,  "young_dev_bonus": 2.0},
    "Clutch":          {"emoji": "🎯", "chemistry_bonus": +2, "morale_spread": False, "clutch_boost": +0.12},
    "Locker Room Cancer": {"emoji": "☠", "chemistry_bonus": -8, "morale_spread": True, "clutch_boost": 0},
    "Emotional":       {"emoji": "🌋", "chemistry_bonus": -3, "morale_spread": True,  "clutch_boost": -0.04},
    "Professional":    {"emoji": "💼", "chemistry_bonus": +2, "morale_spread": False, "clutch_boost": +0.01},
    "Lazy":            {"emoji": "😴", "chemistry_bonus": -2, "morale_spread": False, "clutch_boost": -0.03, "dev_bonus": 0.5},
}


def _gen_personality_trait(attrs, age):
    iq = attrs.get("Shot IQ", 60) + attrs.get("Vision", 60)
    athl = attrs.get("Athleticism", 60) + attrs.get("Speed", 60)
    # Weight the distribution by plausible attributes
    weights = {
        "Leader":             max(0, (iq - 100) / 4),
        "Gym Rat":            max(0, (athl - 120) / 5),
        "Mentor":             max(0, (age - 28) * 2),
        "Clutch":             12,
        "Locker Room Cancer": 6,
        "Emotional":          10,
        "Professional":       18,
        "Lazy":               7,
    }
    total = sum(weights.values()) or 1
    roll = random.random() * total
    running = 0
    for trait, w in weights.items():
        running += w
        if roll < running:
            return trait
    return "Professional"


def generate_roster(team_name, year):
    players = []
    for i in range(15):
        pos = POSITIONS[i % 5]
        if i < 5:
            base = random.randint(78, 94)
            minutes = [34, 32, 30, 28, 26][i]
        elif i < 10:
            base = random.randint(70, 79)
            minutes = [22, 20, 18, 16, 14][i - 5]
        else:
            # UPGRADE PASS (free agent quality): 55-71 read as replacement-
            # level scrubs even for a fresh signing -- bumped the floor
            # slightly (58-71 -> 60-74) so bottom-of-roster/eventual-waive
            # players aren't quite so uniformly bad once they hit the FA pool.
            base = random.randint(60, 74)
            minutes = 0

        age = random.randint(21, 36)
        if age <= 25:
            potential = clamp(base + random.randint(0, 18), 60, 99)
        else:
            potential = clamp(base + random.randint(-4, 6), 55, 99)

        p = make_player(pos, age, base, potential, team_name, year, year - (age - 20), tier="vet")
        p["minutes"] = minutes
        backfill_career_history(p, year)
        players.append(p)
    return players


def generate_draft_class(year):
    draft_pool = []
    for i in range(60):
        pos = random.choice(POSITIONS)
        age = random.randint(19, 22)
        if i < 5:
            base = random.randint(70, 82)
            potential = random.randint(85, 99)
        elif i < 15:
            base = random.randint(64, 76)
            potential = random.randint(75, 92)
        elif i < 30:
            base = random.randint(58, 70)
            potential = random.randint(65, 85)
        else:
            base = random.randint(50, 64)
            potential = random.randint(55, 78)
        p = make_player(pos, age, base, potential, None, year, year, tier="rookie")
        p["projected"] = f"Top {random.choice([3,5,10,14])}" if i < 14 else ("First Round" if i < 30 else "Second Round")
        draft_pool.append(p)
    draft_pool.sort(key=lambda x: x["potential"], reverse=True)
    tag_international_prospects(draft_pool)   # UPGRADE: international scouting stash flags
    return draft_pool


def generate_low_level_pool(team_name, year, count=LOW_LEVEL_POOL_PER_TEAM):
    """UPGRADE: Low-level depth pool (see LOW_LEVEL_POOL_PER_TEAM above).

    Generates `count` free agents "attached" to a team for flavor (its
    scouting department found them, its G-League affiliate stashed them,
    etc.) but who are NOT on that team's 15-man roster -- they enter the
    sim as unsigned free agents any team can pick up.

    UPGRADE PASS (FA quality, round 2): the previous 45-68 base range was
    still a hard ceiling well below a real rotation player (78+), so the
    free agent wire was *always* just replacement-level fodder -- there
    was never a genuinely useful signing available, which doesn't match
    real NBA free agency (there are always a handful of solid rotation
    guys and the occasional real name on a buyout). Now:
      - the bulk of the pool (80%) is 45-72 -- still mostly replacement
        level/depth signings, that part of the read stays intact
      - the rest (20%) is a "found value" tier at 68-84 -- a real
        difference-maker who fell out of a rotation, is coming off
        injury, or got bought out, so there's usually at least one or two
        free agents worth actually planning a signing around
    """
    pool = []
    for i in range(count):
        pos = POSITIONS[i % 5]
        age = random.randint(19, 34)
        if random.random() < 0.20:
            base = random.randint(68, 84)
        else:
            base = random.randint(45, 72)
        if age <= 23:
            potential = clamp(base + random.randint(0, 20), 45, 95)
        else:
            potential = clamp(base + random.randint(-6, 10), 40, 90)
        p = make_player(pos, age, base, potential, None, year, year - max(0, age - 20), tier="low")
        p["scouted_by"] = team_name  # flavor only -- doesn't grant any team exclusive rights
        pool.append(p)
    return pool


# ==========================================
# DRAFT SCOUTING ENGINE (attribute obfuscation)
# ==========================================
# Rather than showing a prospect's exact ratings the moment the draft class is
# generated, GMs see wide, uncertain projection ranges (e.g. "72-84" three-point
# shooting) that narrow toward the true number as scout points are invested.
SCOUT_POINTS_PER_SEASON = 30       # a team's scouting budget for the whole draft class each year
MAX_SCOUT_POINTS_PER_PROSPECT = 10  # points needed to fully clear the fog on one prospect
SCOUT_HEADLINE_CATEGORIES = ["Finishing", "Shooting", "Playmaking", "Defense", "Rebounding", "Physical"]


def _scout_uncertainty_width(points):
    """0 points invested = +/-18 wide fog; MAX points = fully revealed (+/-0)."""
    frac = min(1.0, points / MAX_SCOUT_POINTS_PER_PROSPECT)
    return round(18 * (1 - frac) ** 1.4)


def scouted_prospect_view(prospect, points_invested):
    """
    Returns a display-safe copy of a draft prospect: category ratings are
    replaced with (low, high) projection ranges around the true value, and the
    exact overall rating/potential are hidden behind grade bands until enough
    scout points are invested. Never mutates the underlying prospect dict.
    """
    cats = derive_categories(prospect["attributes"])
    width = _scout_uncertainty_width(points_invested)
    seed = hash(prospect["name"]) & 0xFFFF   # stable per-prospect noise so the
    random.seed(seed)                        # range doesn't jitter every request
    ranges = {}
    for cat in SCOUT_HEADLINE_CATEGORIES:
        true_val = cats.get(cat, 70)
        skew = random.uniform(-width * 0.4, width * 0.4)
        lo = clamp(true_val - width + skew, 25, 99)
        hi = clamp(true_val + width + skew, 25, 99)
        if lo > hi:
            lo, hi = hi, lo
        ranges[cat] = {"low": lo, "high": hi, "revealed": width <= 1}
    random.seed()  # restore true randomness for the rest of the sim

    fully_scouted = points_invested >= MAX_SCOUT_POINTS_PER_PROSPECT
    ovr_width = max(1, round(width * 0.6))
    view = {
        "name": prospect["name"], "position": prospect["position"], "age": prospect["age"],
        "projected": prospect["projected"], "draft_year": prospect["draft_year"],
        "scout_points_invested": points_invested,
        "scout_ranges": ranges,
        "overall_range": {"low": clamp(prospect["rating"] - ovr_width, 25, 99),
                           "high": clamp(prospect["rating"] + ovr_width, 25, 99)},
        "potential_grade": prospect["potential_grade"] if points_invested >= 4 else "Unknown",
        "rating": prospect["rating"] if fully_scouted else None,
        "potential": prospect["potential"] if fully_scouted else None,
        "fully_scouted": fully_scouted,
    }
    return view


def scout_prospect(team_name, prospect_name, points):
    """Invest `points` of a team's season scouting budget into one prospect."""
    points = max(0, int(points))
    budget = SIM_STATE["scouting"]["points"].get(team_name, 0)
    if points > budget:
        return {"success": False, "reason": f"{team_name} only has {budget} scout points left this season."}
    invested = SIM_STATE["scouting"]["invested"].setdefault(team_name, {})
    current = invested.get(prospect_name, 0)
    new_total = min(MAX_SCOUT_POINTS_PER_PROSPECT, current + points)
    actually_spent = new_total - current
    invested[prospect_name] = new_total
    SIM_STATE["scouting"]["points"][team_name] = budget - actually_spent
    return {"success": True, "prospect": prospect_name, "points_invested": new_total,
            "points_remaining": SIM_STATE["scouting"]["points"][team_name]}


# ─────────────────────── SCOUTING COMBINE DRILLS ─────────────────────────────

def run_combine_drill(team_name, prospect_name, drill_name):
    """Run one combine drill on a prospect. Returns a noisy measurement of
    the underlying attribute (±noise range defined in COMBINE_DRILLS), spends
    1 scout point, and tightens that attribute's scouting range by ~30%
    because physical test results anchor the uncertainty around that trait."""
    drill = COMBINE_DRILLS.get(drill_name)
    if not drill:
        return {"success": False, "reason": f"Unknown drill '{drill_name}'."}
    budget = SIM_STATE["scouting"]["points"].get(team_name, 0)
    if budget < drill["cost"]:
        return {"success": False, "reason": f"Not enough scout points (need {drill['cost']}, have {budget})."}
    prospect = next((p for p in SIM_STATE["draft_class"] if p["name"] == prospect_name), None)
    if not prospect:
        return {"success": False, "reason": "Prospect not found."}

    # Already run this drill? Only charge once, but allow re-checking result.
    results = SIM_STATE["combine_results"].setdefault(prospect_name, {})
    if drill_name not in results:
        true_val = prospect.get("attributes", {}).get(drill["attr"], 60)
        noise = drill["noise"]
        measured = round(clamp(true_val + random.uniform(-noise, noise), 25, 99), 1)
        results[drill_name] = {"measured": measured, "attr": drill["attr"],
                                "drill": drill_name, "desc": drill["desc"]}
        SIM_STATE["scouting"]["points"][team_name] = budget - drill["cost"]

        # Tighten the scouting range on that attribute category -- having a
        # real measured number narrows uncertainty more than film review alone.
        invested = SIM_STATE["scouting"]["invested"].setdefault(team_name, {})
        invested[prospect_name] = invested.get(prospect_name, 0) + drill["cost"]

    return {"success": True, "result": results[drill_name],
            "points_remaining": SIM_STATE["scouting"]["points"].get(team_name, 0)}


# ─────────────────────────── G-LEAGUE SIMULATION ─────────────────────────────

def g_league_tick():
    """Called every simulated day. Simulates a light G-League box score for
    each two-way player and banks development XP. No UI needed -- results are
    surfaced in the player card and a "Call Up" button on the roster tab."""
    year_day = SIM_STATE.get("current_day", 1)
    # Only sim G-League during the regular season window.
    if SIM_STATE.get("season_simulated") or SIM_STATE.get("playoffs_started"):
        return
    for p in SIM_STATE["players"].values():
        if not p.get("two_way"):
            continue
        gl = SIM_STATE["g_league_stats"].setdefault(p["name"], {
            "GP": 0, "PTS": 0.0, "REB": 0.0, "AST": 0.0, "xp_banked": 0.0
        })
        # ~75% chance of playing on any given day (mimics a 50-game schedule).
        if random.random() > 0.75:
            continue
        base = p.get("rating", 60)
        pts  = round(max(4, random.gauss(base * 0.38, 4)), 1)
        reb  = round(max(1, random.gauss(base * 0.12, 2)), 1)
        ast  = round(max(0, random.gauss(base * 0.09, 1.5)), 1)
        gl["GP"]  += 1
        gl["PTS"] += pts
        gl["REB"] += reb
        gl["AST"] += ast
        # UPGRADE: Training facility bonus multiplies development XP earned
        fac_level = SIM_STATE.get("facilities", {}).get(p.get("team",""), {}).get("Training", 1)
        dev_mult = FACILITY_BONUS["dev_mult"][min(fac_level - 1, 4)]
        gl["xp_banked"] = round(gl["xp_banked"] + G_LEAGUE_DEV_XP_PER_GAME * dev_mult, 2)
        # Apply banked XP to the player's rating once it crosses a threshold.
        if gl["xp_banked"] >= 5.0:
            xp_to_apply = int(gl["xp_banked"] // 5)
            bump = min(xp_to_apply, 3)    # cap at +3 per call-up cycle
            if p["rating"] < p.get("potential", 99):
                p["rating"] = min(p.get("potential", 99), p["rating"] + bump)
                _regen_attributes_for_rating(p)
            gl["xp_banked"] = round(gl["xp_banked"] % 5, 2)


def _regen_attributes_for_rating(p):
    """Nudge a player's attributes up proportionally when their G-League XP
    pushes their overall rating, so the attribute sheet stays in sync."""
    new_attrs = gen_attributes(p["rating"], p["position"])
    old_attrs = p.get("attributes", {})
    for k, v in new_attrs.items():
        old = old_attrs.get(k, v)
        p["attributes"][k] = round(old * 0.7 + v * 0.3, 1)   # smooth blend
    p["attributes"] = p.get("attributes", new_attrs)


def call_up_two_way(player_name):
    """Promote a two-way player to the standard 15-man roster, consuming their
    G-League XP as a final development burst and converting their contract."""
    return convert_two_way_to_standard(player_name)


def scout_top_prospects(team_name, n=5):
    """
    UPGRADE: Scouting 'assign all points' quick-action. Spends a team's
    remaining season scouting budget across its top `n` remaining-potential
    prospects (by current known/estimated rating), spreading points evenly
    and giving leftover points to the highest-rated prospect first, instead
    of requiring the user to invest one prospect at a time.
    """
    budget = SIM_STATE["scouting"]["points"].get(team_name, 0)
    if budget <= 0:
        return {"success": False, "reason": f"{team_name} has no scout points left this season."}
    invested = SIM_STATE["scouting"]["invested"].setdefault(team_name, {})
    prospects = sorted(SIM_STATE["draft_class"], key=lambda p: -p["potential"])[:max(1, n)]
    prospects = [p for p in prospects if invested.get(p["name"], 0) < MAX_SCOUT_POINTS_PER_PROSPECT]
    if not prospects:
        return {"success": False, "reason": "Every top prospect is already fully scouted."}

    results = []
    remaining = budget
    per_prospect = max(1, remaining // len(prospects))
    for p in prospects:
        if remaining <= 0:
            break
        current = invested.get(p["name"], 0)
        room = MAX_SCOUT_POINTS_PER_PROSPECT - current
        spend = min(per_prospect, room, remaining)
        if spend <= 0:
            continue
        new_total = current + spend
        invested[p["name"]] = new_total
        remaining -= spend
        results.append({"name": p["name"], "points_invested": new_total})
    # Dump any leftover (from rounding, or prospects that hit the cap early)
    # onto the single best remaining prospect that still has room.
    for p in prospects:
        if remaining <= 0:
            break
        current = invested.get(p["name"], 0)
        room = MAX_SCOUT_POINTS_PER_PROSPECT - current
        if room <= 0:
            continue
        spend = min(room, remaining)
        invested[p["name"]] = current + spend
        remaining -= spend
        for r in results:
            if r["name"] == p["name"]:
                r["points_invested"] = invested[p["name"]]
                break
        else:
            results.append({"name": p["name"], "points_invested": invested[p["name"]]})

    SIM_STATE["scouting"]["points"][team_name] = remaining
    return {"success": True, "spent": results, "points_remaining": remaining}


PICK_PROTECTION_TIERS = {
    "None": 0, "Top-4 Protected": 4, "Top-10 Protected": 10, "Lottery Protected": 14,
}


def make_pick(year, rnd, original_team, current_team=None):
    pid = f"{year}_R{rnd}_{original_team.replace(' ', '')}"
    return {"id": pid, "year": year, "round": rnd, "original_team": original_team,
            "current_team": current_team or original_team, "protection": "None"}


# ==========================================
# GLOBAL ENGINE STATE ARCHITECTURE
# ==========================================
SIM_STATE = {
    "current_tab": "roster",
    "user_team": "Gotham Knights",
    "team_chosen": False,  # UPGRADE: team selection -- False until the user picks who to GM instead of being auto-assigned
    "era_chosen": False,   # UPGRADE: era selection -- False until the user picks which era to start the league in
    "year": START_YEAR,
    "stage": "regular_season",  # regular_season -> playoffs -> offseason -> draft -> free_agency -> regular_season
    "season_simulated": False,
    "playoffs_started": False,
    "playoffs_complete": False,
    "current_round": 1,
    "round_completed": False,
    "current_day": 1,
    "teams": {},
    "players": {},
    "schedule": [],
    "schedule_days_total": 82,
    "regular_season_games": [],
    "playoff_bracket": {"1": [], "2": [], "3": [], "4": []},
    "draft_class": [],
    "draft_picks": {},
    "draft": {"active": False, "order": [], "index": 0, "results": [], "year": None},
    "awards": {"MVP": None, "DPOY": None, "ROY": None, "MIP": None, "Finals_MVP": None, "All_NBA": None, "All_Stars": None,
               "Sixth_Man": None, "All_Defensive": None, "All_Rookie": None},
    "trade_deadline_day": None,
    "last_lottery_order": [],
    "trades": [],
    "trade_log": [],
    "bidding_wars": [],
    "free_agents": [],
    "retired_players": [],
    "pending_offer": None,
    "pending_bid": None,
    "offseason_report": None,
    "history": [],
    "fa_day": 0,
    "fa_days_total": 10,
    "fa_daily_log": [],
    "sim_stopped_reason": None,
    "version": 0,
    "news": [],
    "live_prewatched": {},
    "team_display_names": {},
    "expansion_draft_used": False,
    "expansion_history": None,
    "all_star": {},
    "coaches": {},                          # team_name -> {name, system, years_with_team}
    "coach_market": [],                     # UPGRADE: pool of unemployed candidate coaches available to hire
    "scouting": {"points": {}, "invested": {}},   # draft scouting fog-of-war state
    "play_in": {"active": False, "complete": False, "games": {}},
    "save_slot_meta": None,                 # info about the slot this game was loaded from, if any
    "trade_requests": [],                   # UPGRADE: player morale/trade-request system -- active requests
    "franchise_records": {},                # UPGRADE: historical stats archive -- team_name -> best single-game/season marks
    "retired_numbers": {},                  # UPGRADE: team_name -> list of {number, player, reason}
    "team_colors": {},                      # UPGRADE: team logo/color customization -- team_name -> {primary}
    "trade_aggressiveness": 50.0,           # UPGRADE: league-wide AI trade willingness dial (0-100)
    "gm_trust": {},                         # UPGRADE: front-office reputation -- team_name -> trust score 0-100
    "gm_archetypes": {},                    # UPGRADE: rival GM personalities -- team_name -> archetype name
    "legacy_score": 0,                      # UPGRADE: GM legacy score -- accumulates across seasons
    "legacy_log": [],                       # UPGRADE: season-by-season legacy events for the history tab
    "assistant_coaches": {},                # UPGRADE: coaching staff depth -- team_name -> list of assistants
    "assistant_coach_market": [],           # UPGRADE: unemployed assistant coach candidate pool
    "practice_points": {},                  # UPGRADE: practice mini-game -- team_name -> offseason focus points left
    "rivalries": {},                        # UPGRADE: rivalries & narrative arcs -- "TeamA|TeamB" -> meeting/trade history
    "stashed_players": {},                  # UPGRADE: international scouting -- team_name -> stashed player names
    "ingame_strategy_bonus": {},             # UPGRADE: in-game coaching decisions -- team_name -> live overrides
    "coach_career": {},                      # UPGRADE: clickable coach profiles -- coach name -> {system, seasons[], championships, total_wins, total_losses, teams_coached, hires, fires, years_experience}
    "untradeable": {},                       # UPGRADE: "untradeable" flag -- team_name -> list of player names a GM has locked from trades
    "trade_targets": {},                     # 2K-style trade watchlist -- team_name -> list of player names (on other rosters) a GM is tracking
    "h2h_history": {},                       # UPGRADE: team-vs-team head-to-head series history -- "TeamA|TeamB" (sorted) -> {TeamA_wins, TeamB_wins, games:[...]}
    "trade_block": [],                       # UPGRADE: "trade block" -- player names the user has marked available, so AI teams proactively call about them
    "trade_exceptions": {},                  # UPGRADE: banked Trade Exceptions (TPE)
    "owner_mandate": None,                   # UPGRADE: owner mandates/hot seat
    "hot_seat": {"warnings": 0, "fired": False, "fired_from": None},  # UPGRADE: owner mandates/hot seat
    "fan_approval": {},                      # UPGRADE: fan approval 0-100 per team, fed by wins/stars/trades
    "attendance_revenue": {},               # UPGRADE: ticket revenue ($M) per team, based on fan approval + market
    "media_morale_bonus": 0,               # UPGRADE: morale/fan-approval modifier from press conference responses
    "combine_results": {},                  # UPGRADE: scouting combine drill results
    "g_league_stats": {},                   # UPGRADE: G-League box scores
    "retired_jerseys": [],                  # UPGRADE: jersey retirement ceremonies
    "hall_of_fame": [],                     # UPGRADE: Hall of Fame inductees
    "trophy_room": [],                      # UPGRADE: championship trophy archive
    "team_records": {},                     # UPGRADE: all-time team records (most wins, longest streak, etc.)
    "franchise_goat": {},                   # UPGRADE: greatest player/coach/season per franchise
    "facilities": {},                        # UPGRADE: team facility levels — dept -> level 1-5
    "arena": {},                             # UPGRADE: arena customization — court/jersey/colors/nickname
    "pending_arbitration": [],               # UPGRADE: salary arbitration demands from outperforming players
    # ===== UPGRADE BATCH 3 =====
    "team_identity": {},        # team_name -> identity label (Fast Paced, Defensive, Small Ball, ...)
    "coaching_gameplan": {},    # team_name -> {slider_name: 0-100}
    "player_of_week": [],       # history list of {week, year, player, team, line}
    "coach_of_month": [],       # history list of {month, year, coach, team}
    "weekly_watermark_day": 0,  # last day POTW was evaluated through
    # ===== UPGRADE BATCH 4 =====
    "league_rules": {},         # editable league rules -- see DEFAULT_LEAGUE_RULES
    "front_office": {},         # team_name -> {role: staffer_name}
    "simcast_log": {},          # game_id -> list of live play-by-play events already revealed
    # ===== UPGRADE BATCH 5 =====
    "era": "Modern",            # active era id -- see ERAS
    "training_focus": {},       # player_name -> {"focus": str, "set_year": int} in-season weekly training pick
    # ===== UPGRADE BATCH 6 =====
    "backstory_generated": False,   # whether pre-league history (1984 -> start) has been seeded
    "backstory_start_year": 1984,
    # ===== UPGRADE BATCH 7 =====
    "gm_personalities": {},     # team_name -> archetype (persists across seasons)
    "scouting_regions": {},     # team_name -> {region: points_invested}
    "ticket_prices": {},        # team_name -> price tier ("Budget".."Premium")
    "sponsorships": {},         # team_name -> [{sponsor, annual_value}]
    "no_trade_clauses": {},     # player_name -> bool
    "player_options": {},       # player_name -> bool (has a player option on final contract year)
    "dev_league_stats": {},     # player_name -> dev-league box totals pre-draft
    "social_media": [],         # feed of player social posts/incidents
    "travel_log": {},           # team_name -> {"miles_this_trip", "timezone_shift", "consecutive_road"}
    "coaching_career_mode": False,  # if True, user plays as a Head Coach instead of GM
    "lineup_synergy_cache": {}, # frozenset(5 names) -> net rating estimate
    "custom_big_board": {},     # prospect_name -> user's personal rank override
    "user_theme": "dark",       # UI theme preset
    "difficulty_settings": {"ai_trade_aggressiveness": 50, "injury_frequency": 50, "cap_strictness": 50},
    "press_conferences": [],    # log of press conference prompts + user's chosen response
    "player_nicknames": {},     # player_name -> nickname
    "what_if_branches": [],     # saved alternate-history branch snapshots
    # ===== UPGRADE BATCH 8 =====
    # NBA Cup state now lives in SIM_STATE["cup"], set up by setup_in_season_cup()
    "buyout_market": [],             # waived vets currently negotiating a buyout
    "trade_requests": [],            # active player trade requests
    "custom_players": [],            # user-created players (Create-a-Player)
    "fantasy_draft_mode": False,
    "summer_league": {},             # summer league standings/results
    "preseason_games": [],
    "global_games": [],              # international exhibition results
    "media_day_log": [],             # player interview quotes
    "hall_of_fame_ballot": {},       # candidate_name -> {"votes_pct": float, "year_on_ballot": int}
    "arena_names": {},               # team_name -> arena name + naming-rights sponsor
    "jersey_patches": {},            # team_name -> {sponsor, annual_value}
    "team_mascots": {},              # team_name -> mascot name
    "executive_of_the_year": [],     # history log
    "coach_hot_seat": {},            # team_name -> heat score 0-100
    "hustle_stats": {},              # player_name -> {"deflections", "charges_taken", "loose_balls"}
    "walk_up_motifs": {},            # player_name -> {"root_freq", "pattern"} for the sound engine
    "trade_grades": [],              # log of graded trades
    "draft_night_grades": {},        # year -> {pick_no: {team, grade}}
    "franchise_value": {},           # team_name -> estimated $ value
    "ticket_loyalty_tier": {},       # team_name -> tier label
    "fan_vote_totals": {},           # this season's All-Star fan-vote flavor totals
    # ===== UPGRADE BATCH 11 (next 50) =====
    "rfa_offer_sheets": [],
    "extend_trade_log": [],
    "designated_rookie": {},
    "academy_prospects": {},
    "realignment": {},
    "board_votes": [],
    "franchise_letters": [],
    "beat_writer_reports": [],
    "skill_tree_progress": {},
    "player_rivalries": [],
    "campaign_log": [],
    "position_battles": {},
    "documentaries": [],
    "win_total_predictions": {},
    "award_odds": {},
    "parade_log": [],
    "custom_uniforms": {},
    "referee_profiles": {},
    "job_offers": [],
    "coaching_tree": {},
    "fo_alumni": [],
    "gm_career_history": [],
    "notifications": [],
    "undo_stack": [],
    "ownership_confidence": {},
    "owner_personalities": {},
    "all_decade_teams": [],
    "redraft_results": {},
}

# ─────────────────────── TEAM FACILITIES ─────────────────────────────────────
FACILITY_DEPTS = {
    "Training":  {"emoji": "🏋", "desc": "Boosts player development XP and aging curve",  "cost": [0,3,6,10,15], "bonus_key": "dev_mult"},
    "Medical":   {"emoji": "🏥", "desc": "Reduces injury duration and reinjury risk",       "cost": [0,3,6,10,15], "bonus_key": "injury_mult"},
    "Scouting":  {"emoji": "🔭", "desc": "More scout points per season",                   "cost": [0,2,5,8,12],  "bonus_key": "scout_pts"},
    "Analytics": {"emoji": "📊", "desc": "Improves AI draft grades and trade values",      "cost": [0,2,5,8,12],  "bonus_key": "analytics"},
}
FACILITY_BONUS = {
    "dev_mult":    [1.0, 1.05, 1.12, 1.20, 1.30],  # G-League XP multiplier
    "injury_mult": [1.0, 0.90, 0.80, 0.68, 0.55],  # injury duration multiplier (lower = better)
    "scout_pts":   [0,   2,    5,    8,    12],      # bonus scout points per season
    "analytics":   [0,   5,    10,   16,   25],      # bonus scouting OVR reveal points
}

ARENA_DEFAULTS = {"court": "Classic Hardwood", "jersey_style": "Home/Away", "nickname": "", "vibe": "Neutral"}
ARENA_COURTS   = ["Classic Hardwood", "Dark Court", "City Edition", "Throwback", "Championship Edition"]
ARENA_VIBES    = ["Neutral", "Loud", "Electric", "Intimidating", "Homey"]


def seed_league():
    # UPGRADE: Fixed league seed. Pin the RNG before any team/player/coach
    # generation so the 30 teams' 15-man rosters (and the low-level depth
    # pool below) come out byte-for-byte identical on every new league,
    # instead of a fresh random cast of names/attributes each time. We reset
    # the name registry too, since it's a module-level dedup set that would
    # otherwise remember names from a previous league in this same process
    # (e.g. after "New Game" is used twice) and skew the deterministic draw.
    _NAME_REGISTRY.clear()
    random.seed(FIXED_LEAGUE_SEED)

    for team_name in NBA_TEAMS:
        SIM_STATE["teams"][team_name] = {
            "cap_space": SALARY_CAP, "wins": 0, "losses": 0, "streak": 0, "conference": TEAM_CONFERENCE[team_name],
            "points_for": 0, "points_against": 0,
            "offensive_priority": "Balanced", "defensive_priority": "Man-to-Man",
            "pace": "Balanced", "shooting_willingness": "Balanced", "rebounding_style": "Balanced",
            "scoring_option": "Balanced Attack",
            "chemistry": 65.0, "luxury_tax": 0.0, "over_tax": False,
            "starters": {}, "recent_results": [],
        }
        team_roster = generate_roster(team_name, START_YEAR)
        for p in team_roster:
            SIM_STATE["players"][p["name"]] = p
        for yr in [START_YEAR, START_YEAR + 1, START_YEAR + 2]:
            for rnd in [1, 2]:
                pk = make_pick(yr, rnd, team_name)
                SIM_STATE["draft_picks"][pk["id"]] = pk

        # UPGRADE: Low-level depth pool -- seed this team's share of fringe
        # free agents alongside its roster so the league launches with real
        # free-agency depth (30*15 rostered + 30*LOW_LEVEL_POOL_PER_TEAM
        # fringe players) rather than only ever having 450 players until
        # someone gets waived.
        for p in generate_low_level_pool(team_name, START_YEAR):
            SIM_STATE["players"][p["name"]] = p
            SIM_STATE["free_agents"].append(p)

    SIM_STATE["draft_class"] = generate_draft_class(START_YEAR)
    SIM_STATE["team_colors"] = default_team_colors()          # UPGRADE: team color customization defaults
    for team_name in NBA_TEAMS:
        recompute_cap(team_name)
        SIM_STATE["coaches"][team_name] = {
            "name": generate_coach_name(),
            "system": random.choice(list(COACH_SYSTEMS.keys())),
            "years_with_team": random.randint(1, 6),
        }
        SIM_STATE["scouting"]["points"][team_name] = SCOUT_POINTS_PER_SEASON
        if team_name != SIM_STATE["user_team"]:
            SIM_STATE["gm_trust"][team_name] = 50.0            # UPGRADE: front-office reputation baseline
            SIM_STATE["gm_archetypes"][team_name] = random.choice(list(GM_ARCHETYPES.keys()))
        SIM_STATE["facilities"].setdefault(team_name, {dept: 1 for dept in FACILITY_DEPTS})
        SIM_STATE["arena"].setdefault(team_name, dict(ARENA_DEFAULTS))
    SIM_STATE["scouting"]["invested"] = {}
    refill_coach_market()   # UPGRADE: coach hiring/firing market
    refill_assistant_market()   # UPGRADE: coaching staff depth
    refill_practice_points()    # UPGRADE: practice mini-game starting budget

    # UPGRADE: Fixed league seed (part 2). Restore true, unpredictable
    # randomness for everything downstream of league creation -- game sims,
    # injuries, progression, AI trade/FA behavior, the annual draft class
    # rolled during play, etc. Only the initial 30-team cast is deterministic.
    random.seed()


def build_schedule():
    """
    UPGRADE: previously every one of the 82 "rounds" was simply 1 calendar day
    where literally all 30 teams played -- there was no such thing as a rest day,
    and every team shared the exact same day-by-day calendar. Real NBA-style (and
    2K MyLeague-style) calendars are staggered: not everyone plays every night,
    and different teams end up with different gaps/back-to-backs.

    We keep the same fair round-robin pairing logic (every team still gets
    exactly 82 games against a balanced slate of opponents), but each round's 15
    matchups are now split into two "waves" scheduled on two different calendar
    days, and a league-wide breather day is inserted every few rounds. Because
    the wave split rotates as the pairing table rotates, which teams land in the
    early wave vs. the late wave keeps changing all season -- so no two teams end
    up with an identical calendar.
    """
    SIM_STATE["schedule"] = []
    teams_list = list(SIM_STATE["teams"].keys())

    def ensure_day(idx):
        while len(SIM_STATE["schedule"]) <= idx:
            SIM_STATE["schedule"].append([])

    day_cursor = 0
    for round_idx in range(82):
        round_matchups = []
        for i in range(15):
            home = teams_list[i]
            away = teams_list[29 - i]
            if round_idx % 2 == 0:
                round_matchups.append({"home": home, "away": away})
            else:
                round_matchups.append({"home": away, "away": home})

        # Split this round's 15 matchups (30 teams, no repeats within a round)
        # into two staggered waves so not everybody tips off the same night.
        wave_a = round_matchups[:8]
        wave_b = round_matchups[8:]

        ensure_day(day_cursor)
        SIM_STATE["schedule"][day_cursor].extend(wave_a)
        day_cursor += 1

        ensure_day(day_cursor)
        SIM_STATE["schedule"][day_cursor].extend(wave_b)
        day_cursor += 1

        # A league-wide breather every 4 rounds keeps the whole league from being
        # locked into back-to-backs for the entire season.
        if (round_idx + 1) % 4 == 0:
            ensure_day(day_cursor)  # leave this day empty -- a true off day
            day_cursor += 1

        teams_list = [teams_list[0]] + [teams_list[-1]] + teams_list[1:-1]

    SIM_STATE["schedule_days_total"] = len(SIM_STATE["schedule"])


# ==========================================================
# NBA CUP (In-Season Tournament) -- 2K-style calendar integration.
#
# Instead of a separate manual "run the group stage / run the knockout"
# action, the Cup now rides directly on the real schedule: 6 groups of 5
# teams are drawn each season, and the first already-scheduled meeting
# between every pair of group-mates (guaranteed to exist within the first
# ~29 rounds, since the round-robin pairing table cycles through every
# possible opponent exactly once per 29 rounds) is simply tagged as a Cup
# group game. Those games are ordinary regular-season games on the
# calendar -- they still count in the standings -- they just also feed
# the Cup table. Once every group game has been played, an 8-team single-
# elimination knockout bracket (6 group winners + 2 wildcards) is
# auto-seeded and its games are injected onto specific upcoming calendar
# days, exactly like NBA 2K's "Showcase"/semifinal/championship dates.
# ==========================================================
CUP_GROUP_COUNT = 6
CUP_GROUP_SIZE = 5
CUP_WILDCARD_SLOTS = 2


def setup_in_season_cup():
    """Draw this season's Cup groups and tag the real schedule with group games."""
    teams = list(NBA_TEAMS)
    random.shuffle(teams)
    groups = {f"Group {chr(65 + i)}": teams[i * CUP_GROUP_SIZE:(i + 1) * CUP_GROUP_SIZE]
              for i in range(CUP_GROUP_COUNT)}
    group_of = {t: g for g, members in groups.items() for t in members}

    needed_pairs = set()
    for members in groups.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                needed_pairs.add(frozenset((members[i], members[j])))

    tagged_pairs = set()
    last_tagged_day = 0
    # 29 rounds (58-ish calendar days with waves/breathers) is enough for the
    # round-robin table to have shown every team every opponent once; scan a
    # little past that as a safety margin in case of an unusual schedule.
    scan_limit = min(len(SIM_STATE["schedule"]), 80)
    for day_idx in range(scan_limit):
        if len(tagged_pairs) >= len(needed_pairs):
            break
        for m in SIM_STATE["schedule"][day_idx]:
            pair = frozenset((m["home"], m["away"]))
            if pair in needed_pairs and pair not in tagged_pairs:
                m["cup_group"] = group_of[m["home"]]
                tagged_pairs.add(pair)
                last_tagged_day = day_idx + 1  # 1-indexed calendar day

    standings = {t: {"group": group_of[t], "wins": 0, "losses": 0, "pt_diff": 0} for t in NBA_TEAMS}
    SIM_STATE["cup"] = {
        "year": SIM_STATE["year"],
        "groups": groups,
        "standings": standings,
        "stage": "group",              # group -> knockout -> complete
        "group_window_end_day": last_tagged_day,
        "bracket": {"QF": [], "SF": [], "F": []},
        "champion": None,
        "next_round_day": None,
    }


def _cup_record_group_result(matchup, box):
    cup = SIM_STATE.get("cup")
    if not cup or cup.get("stage") != "group":
        return
    home, away = matchup["home"], matchup["away"]
    st = cup["standings"]
    if home not in st or away not in st:
        return
    diff = box["home_score"] - box["away_score"]
    if diff > 0:
        st[home]["wins"] += 1
        st[away]["losses"] += 1
    else:
        st[away]["wins"] += 1
        st[home]["losses"] += 1
    st[home]["pt_diff"] += diff
    st[away]["pt_diff"] -= diff


def _cup_finalize_group_stage():
    cup = SIM_STATE["cup"]
    groups = cup["groups"]
    st = cup["standings"]

    def rank_key(t):
        s = st[t]
        return (s["wins"], s["pt_diff"])

    group_winners = []
    runner_ups = []
    for members in groups.values():
        ranked = sorted(members, key=rank_key, reverse=True)
        group_winners.append(ranked[0])
        runner_ups.extend(ranked[1:])
    wildcards = sorted(runner_ups, key=rank_key, reverse=True)[:CUP_WILDCARD_SLOTS]
    field = group_winners + wildcards
    rng = random.Random(f"cup-seed-{SIM_STATE['year']}")
    rng.shuffle(field)

    cup["stage"] = "knockout"
    cup["qualifiers"] = field
    qf_day = cup["group_window_end_day"] + 3
    cup["bracket"]["QF"] = [
        {"team1": field[0], "team2": field[1], "winner": None, "day": qf_day},
        {"team1": field[2], "team2": field[3], "winner": None, "day": qf_day},
        {"team1": field[4], "team2": field[5], "winner": None, "day": qf_day},
        {"team1": field[6], "team2": field[7], "winner": None, "day": qf_day},
    ]
    cup["next_round_day"] = qf_day
    for g in cup["bracket"]["QF"]:
        ensure_schedule_day(qf_day)
        SIM_STATE["schedule"][qf_day - 1].append(
            {"home": g["team1"], "away": g["team2"], "cup_knockout": True, "cup_round": "QF"})
    push_news("🏆", f"NBA Cup knockout bracket is set -- Quarterfinals tip off on Day {qf_day}.", kind="cup")


def ensure_schedule_day(day_1_indexed):
    while len(SIM_STATE["schedule"]) < day_1_indexed:
        SIM_STATE["schedule"].append([])


def _cup_record_knockout_result(matchup, box):
    cup = SIM_STATE.get("cup")
    if not cup or cup.get("stage") != "knockout":
        return
    round_name = matchup.get("cup_round")
    bracket = cup["bracket"].get(round_name, [])
    home, away = matchup["home"], matchup["away"]
    winner = home if box["home_score"] > box["away_score"] else away
    for g in bracket:
        if {g["team1"], g["team2"]} == {home, away} and g["winner"] is None:
            g["winner"] = winner
            break

    if round_name == "QF" and all(g["winner"] for g in bracket):
        winners = [g["winner"] for g in bracket]
        sf_day = matchup["day"] + 3 if isinstance(matchup.get("day"), int) else cup["next_round_day"] + 3
        cup["bracket"]["SF"] = [
            {"team1": winners[0], "team2": winners[1], "winner": None, "day": sf_day},
            {"team1": winners[2], "team2": winners[3], "winner": None, "day": sf_day},
        ]
        cup["next_round_day"] = sf_day
        for g in cup["bracket"]["SF"]:
            ensure_schedule_day(sf_day)
            SIM_STATE["schedule"][sf_day - 1].append(
                {"home": g["team1"], "away": g["team2"], "cup_knockout": True, "cup_round": "SF"})
        push_news("🏆", f"NBA Cup Semifinals are set for Day {sf_day}.", kind="cup")
    elif round_name == "SF" and all(g["winner"] for g in bracket):
        winners = [g["winner"] for g in bracket]
        f_day = matchup["day"] + 3 if isinstance(matchup.get("day"), int) else cup["next_round_day"] + 3
        cup["bracket"]["F"] = [{"team1": winners[0], "team2": winners[1], "winner": None, "day": f_day}]
        cup["next_round_day"] = f_day
        ensure_schedule_day(f_day)
        SIM_STATE["schedule"][f_day - 1].append(
            {"home": winners[0], "away": winners[1], "cup_knockout": True, "cup_round": "F"})
        push_news("🏆", f"NBA Cup Championship is set for Day {f_day}.", kind="cup")
    elif round_name == "F" and bracket and bracket[0]["winner"]:
        champion = bracket[0]["winner"]
        cup["champion"] = champion
        cup["stage"] = "complete"
        fa = SIM_STATE.setdefault("fan_approval", {})
        fa[champion] = clamp(fa.get(champion, 55) + 8, 0, 100)
        push_news("🏆", f"{champion} win the NBA Cup!", kind="cup")


def cup_process_matchup(matchup, box):
    """Called once per simulated game from run_schedule_day; routes the result
    into the Cup's group standings or knockout bracket if it's a Cup game."""
    if matchup.get("cup_group"):
        _cup_record_group_result(matchup, box)
    elif matchup.get("cup_knockout"):
        _cup_record_knockout_result(matchup, box)


def cup_maybe_finalize_group_stage(day_just_completed):
    cup = SIM_STATE.get("cup")
    if cup and cup.get("stage") == "group" and day_just_completed >= cup.get("group_window_end_day", 0) > 0:
        _cup_finalize_group_stage()


def assign_default_minutes(team_name):
    roster = [p for p in SIM_STATE["players"].values() if p["team"] == team_name and not p["retired"]]
    if team_name == SIM_STATE["user_team"]:
        # Don't overwrite the human coach's rotation choices - just give new
        # (0-minute) arrivals a bench role. BUGFIX: this used to blanket-bump
        # every 0-minute player to 6 with no regard for the team's total, which
        # is exactly how a fresh 15-man roster (already sitting at a clean 240
        # from generate_roster) ended up at 270 before a human ever touched a
        # slider. Now it only hands out minutes while real budget remains.
        for p in roster:
            if p["minutes"] == 0 and sum(pl["minutes"] for pl in roster) + 6 <= 240:
                p["minutes"] = 6
        for p in roster:
            if p.get("two_way"):
                p["minutes"] = min(p["minutes"], 10)  # two-way / G-League deal -- spot minutes only
        return
    ranked = sorted([p for p in roster if not p.get("two_way")], key=lambda p: -p["rating"])
    # Matches the corrected "standard" BENCH_DEPTH_PROFILES (240 total) so AI
    # teams' internal rotation weighting respects the same real 240-team-minute
    # budget the user is held to, instead of the old total of 260.
    starter_mins = [34, 32, 30, 28, 26]
    bench_mins = [16, 15, 13, 11, 10, 8, 7, 5, 3, 2]
    for i, p in enumerate(ranked):
        if i < 5:
            p["minutes"] = starter_mins[i]
        elif i < 15:
            p["minutes"] = bench_mins[i - 5] if (i - 5) < len(bench_mins) else 4
        else:
            p["minutes"] = 0
    for p in roster:
        if p.get("two_way"):
            p["minutes"] = 4


BENCH_DEPTH_PROFILES = {
    # UPGRADE: these used to sum to well over the real 240-team-minutes-per-game
    # budget (5 players x 48 min) -- e.g. "standard" totaled 260 and "deep" a
    # wild 291 -- which meant Auto-Build Lineup itself violated the same rule
    # the minutes screen now enforces on manual edits. Rebalanced so every
    # profile lands on exactly 240 while keeping each philosophy's shape.
    "shallow": {"starters": [36, 34, 32, 30, 28], "bench": [30, 23, 15, 8, 4]},
    "standard": {"starters": [34, 32, 30, 28, 26], "bench": [16, 15, 13, 11, 10, 8, 7, 5, 3, 2]},
    "deep": {"starters": [30, 29, 28, 27, 26], "bench": [14, 13, 13, 12, 11, 10, 9, 7, 6, 5]},
}
# UPGRADE PASS: rotation size used to be locked to whatever a bench-depth
# profile's hardcoded array happened to be (8/10/12 players) -- there was no
# way to say "I want a real tight 7-man playoff rotation" or "I want to play
# all 15 guys tonight." Each philosophy now maps to a default player count
# AND a shape exponent, and either can be overridden independently.
BENCH_DEPTH_DEFAULT_SIZE = {"shallow": 8, "standard": 10, "deep": 12}
BENCH_DEPTH_SHAPE = {"shallow": 2.3, "standard": 1.55, "deep": 1.05}


def auto_set_rotation(team_name, bench_depth="standard", rotation_size=None):
    """
    Rebuilds a team's entire minutes rotation from scratch based on player
    rating, a chosen bench-depth philosophy, and (now) exactly how many
    players should be in the rotation at all -- anywhere from a tight
    playoff-style 5-man rotation up to playing the full 15-man roster,
    instead of being locked to whatever a fixed 8/10/12-man array provided.
      - 'shallow' rides its top players heavily, minutes fall off fast.
      - 'standard' is the default balanced rotation.
      - 'deep' spreads minutes much more evenly, closer to full-roster parity.
    Total team minutes always sum to exactly 240 (5 players x 48 min)
    regardless of how many players are actually in the rotation.
    Injured/unavailable players still end up at 0 since minutes are
    reassigned fresh, in overall-rating order, every time this runs.
    """
    if rotation_size is None:
        rotation_size = BENCH_DEPTH_DEFAULT_SIZE.get(bench_depth, 10)
    roster = [p for p in SIM_STATE["players"].values() if p["team"] == team_name and not p["retired"]]
    ranked = sorted(roster, key=lambda p: -p["rating"])
    n = max(1, min(int(rotation_size), len(ranked)))
    shape_exp = BENCH_DEPTH_SHAPE.get(bench_depth, 1.55)

    # Weighted-descending curve: player i (0 = best) gets weight (n-i)^shape_exp,
    # normalized to sum to 240. Higher shape_exp = steeper drop-off (stars play
    # much more than the tail); lower = flatter (minutes spread closer to even).
    weights = [(n - i) ** shape_exp for i in range(n)]
    total_w = sum(weights)
    raw = [240.0 * w / total_w for w in weights]

    # Clamp to realistic per-player bounds, then rescale the remainder
    # across the still-flexible players so the team total stays exactly 240
    # even after clamping pulls some players to their floor/ceiling.
    # The ceiling itself has to flex with rotation size: 240 total minutes
    # split across only 5-6 players mathematically requires some of them
    # well past a normal 40-minute "heavy usage" night (a true 5-man
    # rotation only works at all if the top guys approach full 48-minute
    # games), so a fixed 40 cap made very tight rotations silently fall
    # short of the real 240-minute budget instead of erroring or adjusting.
    max_cap = 48.0 if n <= 6 else (42.0 if n <= 8 else 40.0)
    minutes = [0] * n
    locked = [False] * n
    remaining_budget = 240.0
    flexible_idx = list(range(n))
    for _ in range(n):  # at most n passes to converge
        if not flexible_idx:
            break
        flex_weight_total = sum(weights[i] for i in flexible_idx)
        if flex_weight_total <= 0:
            break
        changed = False
        for i in list(flexible_idx):
            share = remaining_budget * (weights[i] / flex_weight_total)
            capped = max(2.0, min(max_cap, share))
            if capped != share:
                minutes[i] = round(capped)
                locked[i] = True
                remaining_budget -= minutes[i]
                flexible_idx.remove(i)
                changed = True
        if not changed:
            for i in flexible_idx:
                minutes[i] = round(remaining_budget * (weights[i] / flex_weight_total))
            break
    # Rounding can leave the total off by a point or two -- true it up on the
    # best player in the rotation rather than leaving the team a phantom
    # possession short/over for the night.
    drift = 240 - sum(minutes)
    if minutes:
        minutes[0] = max(2, min(int(max_cap) + 2, minutes[0] + drift))

    for i, p in enumerate(ranked):
        p["minutes"] = minutes[i] if i < n else 0
    return [{"name": p["name"], "minutes": p["minutes"], "rating": p["rating"]} for p in ranked]


def recompute_cap(team_name):
    roster = [p for p in SIM_STATE["players"].values() if p["team"] == team_name and not p["retired"]]
    spent = sum((p["contract"]["salary"] if p["contract"] else 0) for p in roster)
    cap_space = round(SALARY_CAP - spent, 1)
    SIM_STATE["teams"][team_name]["cap_space"] = cap_space
    # --- Luxury tax: a soft cap. Teams may spend past SALARY_CAP up to a hard
    # apron (SALARY_CAP + TAX_APRON_ROOM), but every dollar past LUXURY_TAX_LINE
    # racks up a real tax bill at LUXURY_TAX_RATE, same spirit as the real NBA's
    # repeater tax -- informational for the user, and the AI factors it into how
    # eagerly a team takes on extra salary (see find_bidding_rival / trade offers).
    over_line = max(0.0, spent - LUXURY_TAX_LINE)
    SIM_STATE["teams"][team_name]["luxury_tax"] = round(over_line * LUXURY_TAX_RATE, 1)
    SIM_STATE["teams"][team_name]["over_tax"] = spent > LUXURY_TAX_LINE
    assign_default_minutes(team_name)
    recompute_starters(team_name)


POSITION_ORDER = {"PG": 0, "SG": 1, "SF": 2, "PF": 3, "C": 4}


def recompute_starters(team_name):
    """
    UPGRADE: 2K-style explicit Starting Five. Rather than just guessing 'top 5
    minutes' every time the UI needs a depth chart, the team now keeps a real
    starters-by-position-slot record (PG/SG/SF/PF/C), the same shape as a 2K
    MyLeague lineup screen. Recomputed any time the roster or minutes change,
    unless the human coach has already locked in a specific starter at that
    slot (tracked via 'starter_locked' on the player) -- an explicit call from
    the "Make Starter" button in the UI.
    """
    roster = [p for p in SIM_STATE["players"].values() if p["team"] == team_name and not p["retired"]]
    if not roster:
        SIM_STATE["teams"][team_name]["starters"] = {}
        return
    starters = SIM_STATE["teams"][team_name].get("starters", {}) or {}
    used_names = set()
    for pos in POSITIONS:
        locked_name = starters.get(pos)
        locked_player = SIM_STATE["players"].get(locked_name) if locked_name else None
        still_valid = (locked_player and locked_player["team"] == team_name and not locked_player["retired"]
                       and not (locked_player.get("injury") and locked_player["injury"].get("games_remaining", 0) > 0))
        if still_valid:
            starters[pos] = locked_name
            used_names.add(locked_name)
            continue
        pool = [p for p in roster if p["position"] == pos and p["name"] not in used_names
                and not (p.get("injury") and p["injury"].get("games_remaining", 0) > 0)]
        if not pool:
            pool = [p for p in roster if p["name"] not in used_names]
        if not pool:
            starters.pop(pos, None)
            continue
        best = max(pool, key=lambda p: (p["minutes"], p["rating"]))
        starters[pos] = best["name"]
        used_names.add(best["name"])
    SIM_STATE["teams"][team_name]["starters"] = starters


def depth_chart(team_name):
    """Returns the roster sorted 2K-lineup-style: Starting Five in PG->C slot
    order first, then the bench sorted by position group and minutes."""
    roster = [p for p in SIM_STATE["players"].values() if p["team"] == team_name and not p["retired"]]
    starters = SIM_STATE["teams"].get(team_name, {}).get("starters", {}) or {}
    starter_names = {name: pos for pos, name in starters.items()}
    starter_list = []
    for pos in POSITIONS:
        name = starters.get(pos)
        p = SIM_STATE["players"].get(name) if name else None
        if p:
            starter_list.append(p)
    bench = [p for p in roster if p["name"] not in starter_names]
    bench.sort(key=lambda p: (POSITION_ORDER.get(p["position"], 5), -p["minutes"], -p["rating"]))
    return starter_list, bench


def set_manual_starter(team_name, position, player_name):
    """2K-style 'Make Starter' swap: the chosen player takes over the slot
    (and inherits a starter-caliber minutes bump if he was buried on the bench),
    and whoever previously started there slides back into the rotation."""
    if position not in POSITIONS:
        return {"success": False, "reason": "Invalid position slot."}
    p = SIM_STATE["players"].get(player_name)
    if not p or p["team"] != team_name or p["retired"]:
        return {"success": False, "reason": "That player is not on this roster."}
    starters = SIM_STATE["teams"][team_name].setdefault("starters", {})
    prev_name = starters.get(position)
    prev = SIM_STATE["players"].get(prev_name) if prev_name else None
    if prev and prev["name"] != p["name"]:
        p["minutes"], prev["minutes"] = max(p["minutes"], prev["minutes"]), min(p["minutes"], prev["minutes"])
    elif p["minutes"] < 20:
        p["minutes"] = 26
    starters[position] = p["name"]
    # Clear this player out of any other slot he may have been occupying.
    for pos2, nm in list(starters.items()):
        if pos2 != position and nm == p["name"]:
            del starters[pos2]
    recompute_starters(team_name)
    return {"success": True}


def injury_severity_label(games_remaining):
    if games_remaining <= 3:
        return "Day-To-Day"
    if games_remaining <= 10:
        return "Week-To-Week"
    if games_remaining <= 20:
        return "Out Extended"
    return "Season-Ending"


MAX_NEWS_ITEMS = 500  # UPGRADE: News archive — keep more history for the archive tab


def push_news(icon, text, kind="general"):
    SIM_STATE.setdefault("news", [])
    SIM_STATE["news"].insert(0, {
        "year": SIM_STATE.get("year"), "day": SIM_STATE.get("current_day"),
        "icon": icon, "text": text, "kind": kind,
    })
    if len(SIM_STATE["news"]) > MAX_NEWS_ITEMS:
        SIM_STATE["news"] = SIM_STATE["news"][:MAX_NEWS_ITEMS]
    # UPGRADE BATCH 11: surface the notable subset of news in the
    # Notification Center too, instead of every routine item.
    if kind in {"milestone", "award", "transaction", "contract", "cup", "drama", "league_office"}:
        try:
            push_notification(f"{icon} {text}", kind)
        except NameError:
            pass  # push_notification not yet defined during early module load


def update_form(team_name, stats_dict):
    """
    UPGRADE: hot/cold streaks. A player's shooting performance relative to a
    neutral baseline nudges a rolling 'form' meter -- how much it swings is
    governed by his Consistency attribute (streaky guys run hotter and colder;
    ultra-consistent vets barely move). Form then feeds back into next game's
    shooting percentages in sim_team_stats, so a hot hand is a real, temporary
    in-game advantage, same as 2K's shot-meter momentum.
    """
    for p in team_roster(team_name):
        st = stats_dict.get(p["name"])
        form = p.get("form", 0.0)
        if st and st.get("FGA", 0) >= 3:
            actual_efg = (st["FGM"] + 0.5 * st["3PM"]) / max(1, st["FGA"])
            consistency = p["attributes"].get("Consistency", 70) / 100.0
            volatility = (1.0 - consistency) * 1.5 + 0.25
            delta = (actual_efg - 0.50) * volatility
            form = max(-1.0, min(1.0, form * 0.65 + delta))
        else:
            form *= 0.8
        p["form"] = round(form, 3)


def check_milestones(team_name, stats_dict, opponent, is_playoff, won):
    """Detects triple-doubles and big scoring nights and logs them to the
    league newswire -- the same kind of 'stat-of-the-night' flavor 2K surfaces."""
    for name, st in stats_dict.items():
        p = SIM_STATE["players"].get(name)
        if not p:
            continue
        double_digit_cats = sum(1 for k in ("PTS", "REB", "AST", "STL", "BLK") if st.get(k, 0) >= 10)
        tag = " (Playoffs)" if is_playoff else ""
        if double_digit_cats >= 3:
            push_news("🎯", f"{p['name']} ({team_name}) records a triple-double: "
                             f"{st['PTS']} PTS / {st['REB']} REB / {st['AST']} AST{tag}", "milestone")
        if st.get("PTS", 0) >= 50:
            push_news("🔥", f"{p['name']} ({team_name}) erupts for {st['PTS']} points vs {opponent}{tag}!", "milestone")
        elif st.get("PTS", 0) >= 40:
            push_news("🔥", f"{p['name']} ({team_name}) drops {st['PTS']} points vs {opponent}{tag}.", "milestone")


def pick_player_of_the_game(winner_stats, loser_stats):
    best_name, best_score = None, -999
    for st_dict in (winner_stats, loser_stats):
        for name, st in st_dict.items():
            score = (st.get("PTS", 0) + st.get("REB", 0) * 1.2 + st.get("AST", 0) * 1.5 +
                     st.get("STL", 0) * 2 + st.get("BLK", 0) * 2 - st.get("TOV", 0) * 0.5)
            if st_dict is loser_stats:
                score *= 0.85  # a standout on the losing side still counts, just discounted
            if score > best_score:
                best_score, best_name = score, name
    return best_name


def record_regular_result(m, box):
    """Standings/points-for-against/streak/last-10 bookkeeping for one regular
    season game. Factored out so both the normal day-sim loop and the
    'Jump Into Game' live viewer update the exact same records."""
    home, away = m["home"], m["away"]
    if box["home_score"] > box["away_score"]:
        winner, loser = home, away
    else:
        winner, loser = away, home
    SIM_STATE["teams"][home]["points_for"] = SIM_STATE["teams"][home].get("points_for", 0) + box["home_score"]
    SIM_STATE["teams"][home]["points_against"] = SIM_STATE["teams"][home].get("points_against", 0) + box["away_score"]
    SIM_STATE["teams"][away]["points_for"] = SIM_STATE["teams"][away].get("points_for", 0) + box["away_score"]
    SIM_STATE["teams"][away]["points_against"] = SIM_STATE["teams"][away].get("points_against", 0) + box["home_score"]
    SIM_STATE["teams"][winner]["wins"] += 1
    SIM_STATE["teams"][loser]["losses"] += 1
    w_streak = SIM_STATE["teams"][winner].get("streak", 0)
    SIM_STATE["teams"][winner]["streak"] = w_streak + 1 if w_streak >= 0 else 1
    l_streak = SIM_STATE["teams"][loser].get("streak", 0)
    SIM_STATE["teams"][loser]["streak"] = l_streak - 1 if l_streak <= 0 else -1
    for tname, result in ((winner, "W"), (loser, "L")):
        rl = SIM_STATE["teams"][tname].setdefault("recent_results", [])
        rl.append(result)
        if len(rl) > 10:
            del rl[0]

    # UPGRADE: Fan approval / attendance economics -- tick on every game result
    w_streak_new = SIM_STATE["teams"][winner].get("streak", 0)
    post_game_fan_approval_tick(winner, loser, w_streak_new)

    # UPGRADE: Media/press conference -- trigger after notable streaks
    user_team = SIM_STATE["user_team"]
    if not SIM_STATE.get("pending_press_conference"):
        if winner == user_team and w_streak_new == 5:
            trigger_press_conference("big_win")
        elif loser == user_team and SIM_STATE["teams"][loser].get("streak", 0) == -3:
            trigger_press_conference("big_loss")

    potg = box.get("potg")
    user_team = SIM_STATE["user_team"]
    if user_team in (home, away):
        opp = away if user_team == home else home
        my_score = box["home_score"] if user_team == home else box["away_score"]
        opp_score = box["away_score"] if user_team == home else box["home_score"]
        result_icon = "✅" if winner == user_team else "❌"
        potg_txt = f" · POTG: {potg}" if potg else ""
        push_news(result_icon, f"{user_team} {'defeat' if winner == user_team else 'fall to'} {opp}, "
                                f"{my_score}-{opp_score}{potg_txt}", "result")
    margin = abs(box["home_score"] - box["away_score"])
    if margin >= 30:
        push_news("💥", f"{winner} blow out {loser} {max(box['home_score'],box['away_score'])}-"
                        f"{min(box['home_score'],box['away_score'])}.", "result")




# ==========================================================
# UPGRADE BATCH 2 -- 10 major + 10 minor feature pass
# ==========================================================
# See the block comment above each sub-section for what it does and why.
# New SIM_STATE keys used here (team_colors, trade_aggressiveness, gm_trust,
# assistant_coaches, assistant_coach_market, practice_points, rivalries,
# extension_offers, stashed_players, ingame_strategy_bonus) are declared in
# the main SIM_STATE dict above and defaulted per-team in seed_league().

DEFAULT_TEAM_COLOR_PRESETS = [
    "#1d4ed8", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2", "#be185d",
    "#4338ca", "#65a30d", "#ea580c", "#0f766e", "#9333ea", "#b91c1c", "#0284c7", "#ca8a04",
]


def default_team_colors():
    colors = {}
    for i, t in enumerate(NBA_TEAMS):
        colors[t] = {"primary": DEFAULT_TEAM_COLOR_PRESETS[i % len(DEFAULT_TEAM_COLOR_PRESETS)]}
    return colors


# ----------------------------------------------------------
# MINOR 1: Jersey number picker (field already existed as
# `jersey`; this adds a real, validated way to change it).
# ----------------------------------------------------------
def set_jersey_number(name, number):
    p = SIM_STATE["players"].get(name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    try:
        number = int(number)
    except (TypeError, ValueError):
        return {"success": False, "reason": "Enter a number between 0 and 99."}
    if not (0 <= number <= 99):
        return {"success": False, "reason": "Jersey numbers must be between 0 and 99."}
    if p.get("team"):
        for other in team_roster(p["team"]):
            if other["name"] != name and other.get("jersey") == number:
                return {"success": False, "reason": f"#{number} is already worn by {other['name']} on this roster."}
    p["jersey"] = number
    return {"success": True, "jersey": number}


# UPGRADE: Player nicknames / custom cards. A cosmetic-only field the human
# GM can set on any of their own players -- shown alongside the real name
# wherever that player's card/link appears, the same way a jersey number
# customization already works. Doesn't touch ratings, stats, or trade logic
# at all, purely a personalization touch.
def set_player_nickname(name, nickname):
    p = SIM_STATE["players"].get(name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    nickname = (nickname or "").strip()
    if len(nickname) > 24:
        return {"success": False, "reason": "Nicknames must be 24 characters or fewer."}
    # Basic sanitization -- letters, numbers, spaces, and a handful of
    # common punctuation marks used in real nicknames (' " . -).
    if nickname and not re.match(r"^[A-Za-z0-9 '\".\-]+$", nickname):
        return {"success": False, "reason": "Nicknames can only contain letters, numbers, spaces, and basic punctuation."}
    p["nickname"] = nickname or None
    return {"success": True, "nickname": p["nickname"]}


# ----------------------------------------------------------
# MINOR 2: Team logo/color customization.
# ----------------------------------------------------------
def set_team_colors(team_name, primary):
    if team_name not in NBA_TEAMS:
        return {"success": False, "reason": "Unknown team."}
    if not isinstance(primary, str) or not re.match(r"^#[0-9a-fA-F]{6}$", primary or ""):
        return {"success": False, "reason": "Color must be a hex code like #38bdf8."}
    SIM_STATE["team_colors"].setdefault(team_name, {})
    SIM_STATE["team_colors"][team_name]["primary"] = primary
    return {"success": True, "team": team_name, "primary": primary}


# ----------------------------------------------------------
# MINOR 3: Injury report widget (league-wide, for the
# schedule/calendar view).
# ----------------------------------------------------------
def get_injury_report():
    report = []
    for p in SIM_STATE["players"].values():
        if p.get("retired") or not p.get("team") or not p.get("injury"):
            continue
        inj = p["injury"]
        grem = inj.get("games_remaining", 0)
        tier = inj.get("tier", "Minor")
        reinjury_risk = p.get("reinjury_window", 0) > 0
        # Status label: Day-to-Day, Out, Season-Ending
        if grem <= 3:
            status = "Day-to-Day"
            status_color = "#facc15"
        elif grem <= 12:
            status = "Out"
            status_color = "#f97316"
        else:
            status = "Extended Absence"
            status_color = "#ef4444"
        # Return probability: rough estimate
        return_prob = max(10, 100 - grem * 4)
        report.append({
            "name": p["name"], "team": p["team"], "position": p["position"],
            "description": inj.get("description"), "games_remaining": grem,
            "tier": tier, "region": p.get("injury_region"),
            "status": status, "status_color": status_color,
            "return_probability": return_prob,
            "reinjury_risk": reinjury_risk,
            "injury_prone": p.get("injury_prone", False),
        })
    report.sort(key=lambda r: (-r["games_remaining"], r["team"]))
    return report


# ----------------------------------------------------------
# MINOR 4: Quick "compare two players" tool.
# ----------------------------------------------------------
def compare_players(name_a, name_b):
    a = SIM_STATE["players"].get(name_a)
    b = SIM_STATE["players"].get(name_b)
    if not a or not b:
        return {"success": False, "reason": "Could not find one or both players."}

    # UPGRADE: Player comparison depth. This used to only send 8 basic
    # counting stats -- now it also carries physicals, the full attribute
    # sheet, badges, and career achievements so the comparison modal can
    # show a real side-by-side scouting report instead of a bare stat line.
    def snap(p):
        gp = max(1, p.get("stats", {}).get("GP", 0))
        st = p.get("stats", {})
        return {
            "name": p.get("name"), "team": p.get("team"), "position": p.get("position", "SF"),
            "secondary_position": p.get("secondary_position"), "age": p.get("age", 0),
            "height_in": p.get("height_in"), "weight_lbs": p.get("weight_lbs"), "wingspan_in": p.get("wingspan_in"),
            "rating": p.get("rating", 0), "potential": p.get("potential", 0), "potential_grade": p.get("potential_grade"),
            "salary": (p.get("contract") or {}).get("salary"),
            "ppg": round(st.get("PTS", 0) / gp, 1), "rpg": round(st.get("REB", 0) / gp, 1),
            "apg": round(st.get("AST", 0) / gp, 1), "spg": round(st.get("STL", 0) / gp, 1),
            "bpg": round(st.get("BLK", 0) / gp, 1),
            "attributes": p.get("attributes", {}), "badges": p.get("badges", []),
            "career_awards": p.get("career_awards", []),
            "career_totals": p.get("career_totals", {}),
            "injury_prone": p.get("injury_prone", False), "injury_history_count": p.get("injury_history_count", 0),
        }

    return {"success": True, "a": snap(a), "b": snap(b)}


# ----------------------------------------------------------
# MINOR 5: Configurable AI trade aggressiveness (league-wide
# dial). Feeds into evaluate_and_execute_trade's `threshold`
# and generate_ai_trade_offer's willingness to fire offers.
# ----------------------------------------------------------
def set_trade_aggressiveness(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return {"success": False, "reason": "Must be a number 0-100."}
    value = max(0.0, min(100.0, value))
    SIM_STATE["trade_aggressiveness"] = value
    return {"success": True, "trade_aggressiveness": value}


def trade_acceptance_threshold(team_b=None):
    """Base 0.88 acceptance bar, shaped by league aggressiveness dial, the
    specific AI team's trust score, AND their GM archetype personality."""
    agg = SIM_STATE.get("trade_aggressiveness", 50.0)
    threshold = 0.88 - (agg - 50.0) * 0.0016
    if team_b:
        trust = SIM_STATE.get("gm_trust", {}).get(team_b, 50.0)
        threshold -= (trust - 50.0) * 0.0012
        # UPGRADE: Rival GM archetype adjustment
        archetype_name = SIM_STATE.get("gm_archetypes", {}).get(team_b)
        if archetype_name:
            threshold += GM_ARCHETYPES[archetype_name]["threshold_adj"]
    return max(0.72, min(0.97, threshold))


def adjust_gm_trust(team_name, fairness_pct):
    """Called after a completed user<->AI trade. Fair/generous trades (from
    the AI's perspective) build trust; lopsided ones erode it."""
    if team_name not in NBA_TEAMS:
        return
    trust = SIM_STATE.setdefault("gm_trust", {}).setdefault(team_name, 50.0)
    delta = (100.0 - fairness_pct) * 0.15   # fairness_pct < 100 means team_b got the better end
    trust = max(0.0, min(100.0, trust + delta))
    SIM_STATE["gm_trust"][team_name] = round(trust, 1)


# ----------------------------------------------------------
# MINOR 6: Export season stats to CSV.
# ----------------------------------------------------------
def build_stats_csv():
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "Team", "Pos", "Age", "GP", "MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV",
                      "FG%", "3P%", "FT%", "Rating"])
    for p in sorted(SIM_STATE["players"].values(), key=lambda x: -x.get("stats", {}).get("PTS", 0)):
        if p.get("retired"):
            continue
        st = p.get("stats", {})
        gp = max(1, st.get("GP", 0))
        fga, fgm = st.get("FGA", 0), st.get("FGM", 0)
        pa3, pm3 = st.get("3PA", 0), st.get("3PM", 0)
        fta, ftm = st.get("FTA", 0), st.get("FTM", 0)
        writer.writerow([
            p["name"], p.get("team") or "FA", p["position"], p["age"], st.get("GP", 0),
            round(st.get("MIN", 0) / gp, 1), round(st.get("PTS", 0) / gp, 1), round(st.get("REB", 0) / gp, 1),
            round(st.get("AST", 0) / gp, 1), round(st.get("STL", 0) / gp, 1), round(st.get("BLK", 0) / gp, 1),
            round(st.get("TOV", 0) / gp, 1),
            round(100 * fgm / fga, 1) if fga else 0.0,
            round(100 * pm3 / pa3, 1) if pa3 else 0.0,
            round(100 * ftm / fta, 1) if fta else 0.0,
            p["rating"],
        ])
    return buf.getvalue()


# MINOR 7 (waive confirm) already exists client-side in waivePlayer().
# MINOR: Dark/light theme toggle is implemented purely client-side (CSS +
# a <body> class), see HTML_TEMPLATE.


# ----------------------------------------------------------
# MINOR 8: Playoff bracket "what has to happen" clinching math.
# ----------------------------------------------------------
def clinching_scenarios():
    if SIM_STATE["stage"] != "regular_season":
        return {"applicable": False}
    total_days = SIM_STATE.get("schedule_days_total") or 82
    games_left_league_wide = max(0, total_days - SIM_STATE["current_day"] + 1)
    out = {"applicable": True, "conferences": {}}
    for conf in ["East", "West"]:
        rows = []
        conf_teams = [t for t in NBA_TEAMS if TEAM_CONFERENCE.get(t) == conf]
        standings = sorted(conf_teams, key=lambda t: -(SIM_STATE["teams"][t]["wins"] /
                                                        max(1, SIM_STATE["teams"][t]["wins"] + SIM_STATE["teams"][t]["losses"])))
        for rank, t in enumerate(standings, start=1):
            cfg = SIM_STATE["teams"][t]
            wins, losses = cfg["wins"], cfg["losses"]
            games_left = max(0, total_days // 6 - (wins + losses))  # rough remaining-games estimate for this team
            if rank <= 6:
                # Magic number to clinch a guaranteed top-6 (no play-in) seed:
                # crude but honest estimate off the current 7-seed's max possible wins.
                seventh = standings[6] if len(standings) > 6 else None
                if seventh:
                    seventh_cfg = SIM_STATE["teams"][seventh]
                    seventh_max = seventh_cfg["wins"] + max(0, total_days // 6 - (seventh_cfg["wins"] + seventh_cfg["losses"]))
                    magic = max(0, seventh_max - wins + 1)
                else:
                    magic = None
                rows.append({"team": t, "seed": rank, "wins": wins, "losses": losses,
                             "status": "clinched" if magic == 0 else "in_the_hunt", "magic_number": magic})
            elif rank <= 10:
                rows.append({"team": t, "seed": rank, "wins": wins, "losses": losses,
                             "status": "play_in_range", "magic_number": None})
            else:
                tenth = standings[9] if len(standings) > 9 else None
                eliminated = False
                if tenth:
                    tenth_cfg = SIM_STATE["teams"][tenth]
                    my_max = wins + games_left
                    eliminated = my_max < tenth_cfg["wins"]
                rows.append({"team": t, "seed": rank, "wins": wins, "losses": losses,
                             "status": "eliminated" if eliminated else "long_shot", "magic_number": None})
        out["conferences"][conf] = rows
    return out


# ----------------------------------------------------------
# MAJOR 1: Contract extensions (mid-contract offers).
# ----------------------------------------------------------
def extension_eligible(p):
    if not p.get("team") or p.get("two_way") or not p.get("contract"):
        return False
    return 1 <= p["contract"]["years_left"] <= 2


def offer_extension(player_name, years, total_salary_per_year):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    if p.get("team") != SIM_STATE["user_team"]:
        return {"success": False, "reason": "You can only extend your own players."}
    if not extension_eligible(p):
        return {"success": False, "reason": "This player isn't extension-eligible (needs 1-2 contract years left, and no two-way deals)."}
    try:
        years = int(years)
        salary = round(float(total_salary_per_year), 1)
    except (TypeError, ValueError):
        return {"success": False, "reason": "Invalid years/salary."}
    if not (1 <= years <= 5) or salary <= 0:
        return {"success": False, "reason": "Years must be 1-5 and salary must be positive."}

    current_salary = p["contract"]["salary"]
    # A rough "what the player wants" line: age/potential-aware, similar spirit
    # to negotiate_salary's free-agent math but centered on a raise off his
    # current deal rather than an open-market bid.
    trajectory = 1.0
    if p["age"] <= 26:
        trajectory = 1.15
    elif p["age"] >= 32:
        trajectory = 0.85
    wants = round(current_salary * trajectory * (1.05 + p["rating"] / 400), 1)
    gap = (salary - wants) / max(1.0, wants)

    accept_prob = 0.5 + gap * 1.4
    accept_prob += (p.get("morale", 70) - 60) * 0.004
    accept_prob = max(0.03, min(0.97, accept_prob))
    accepted = random.random() < accept_prob

    result = {"success": True, "accepted": accepted, "player_wants": wants, "offer": salary}
    if accepted:
        # UPGRADE: No-trade clauses. Real stars on long-term deals frequently
        # demand NTCs as a condition of signing. Model: if the player is
        # rated 83+ and getting a 4+ year deal they can command one; their
        # agent personality also influences willingness. NTC is a contract
        # flag the GM can't override - it blocks that player from any trade
        # unless they consent (for simplicity, consent = trade_request flag set).
        ntc = False
        agent = p.get("agent_personality", "Balanced")
        ntc_threshold = {"Loyalty": 80, "Business": 87, "Ring Chaser": 84, "Balanced": 83}.get(agent, 83)
        if p["rating"] >= ntc_threshold and years >= 4:
            ntc = random.random() < 0.60  # 60% of eligible players demand it
        p["contract"] = {"years_left": years, "salary": salary,
                          "player_option": False, "team_option": False,
                          "no_trade_clause": ntc}
        p["trade_request"] = None
        p["low_morale_streak"] = 0
        recompute_cap(p["team"])
        ntc_note = " (includes No-Trade Clause)" if ntc else ""
        push_news("✍️", f"{p['team']} signs {p['name']} to a {years}-year, ${round(salary * years, 1)}M extension{ntc_note}.", "transaction")
        result["reason"] = "Extension accepted!"
        result["no_trade_clause"] = ntc
    else:
        result["reason"] = f"{p['name']}'s camp turned down the offer — he was looking for closer to ${wants}M/yr."
    return result


# ----------------------------------------------------------
# MAJOR 2: Draft-day trades (pick-for-pick / pick-for-player
# during the live draft). Reuses the existing legality/value
# machinery, just permits calling it mid-draft.
# ----------------------------------------------------------
def draft_trade(team_a, players_a, picks_a, team_b, players_b, picks_b):
    if not SIM_STATE["draft"]["active"]:
        return {"accepted": False, "reason": "The draft isn't currently active."}
    if team_a == team_b:
        return {"accepted": False, "reason": "A team can't trade with itself."}
    result = evaluate_and_execute_trade(team_a, players_a, picks_a, team_b, players_b, picks_b)
    if result.get("accepted"):
        # Draft order references draft_picks by id and is re-read live each
        # pick, so no separate order-list patch is needed -- current_team on
        # the traded pick already flips inside apply_trade.
        push_news("🔁", f"DRAFT-DAY TRADE: {team_a} and {team_b} swap assets mid-draft.", "transaction")
    return result


# ----------------------------------------------------------
# MAJOR 3: Coaching staff depth (assistant coaches).
# ----------------------------------------------------------
ASSISTANT_ROLES = ["Offensive Coordinator", "Defensive Coordinator", "Player Development"]


def generate_assistant_candidate():
    return {
        "name": generate_coach_name(),
        "role": random.choice(ASSISTANT_ROLES),
        "bonus": round(random.uniform(0.5, 3.0), 1),   # small flat bonus applied per role
    }


def refill_assistant_market(n=8):
    SIM_STATE["assistant_coach_market"] = [generate_assistant_candidate() for _ in range(n)]


def hire_assistant(team_name, candidate_name):
    market = SIM_STATE.get("assistant_coach_market", [])
    cand = next((c for c in market if c["name"] == candidate_name), None)
    if not cand:
        return {"success": False, "reason": "That candidate is no longer available."}
    staff = SIM_STATE["assistant_coaches"].setdefault(team_name, [])
    if any(c["role"] == cand["role"] for c in staff):
        return {"success": False, "reason": f"{team_name} already has a {cand['role']}. Fire them first."}
    if len(staff) >= 3:
        return {"success": False, "reason": "Coaching staff is already full (3 assistants)."}
    staff.append(cand)
    market.remove(cand)
    return {"success": True, "hired": cand}


def fire_assistant(team_name, candidate_name):
    staff = SIM_STATE["assistant_coaches"].setdefault(team_name, [])
    cand = next((c for c in staff if c["name"] == candidate_name), None)
    if not cand:
        return {"success": False, "reason": "That assistant isn't on your staff."}
    staff.remove(cand)
    SIM_STATE.setdefault("assistant_coach_market", []).append(cand)
    return {"success": True}


def assistant_bonus_total(team_name, role):
    staff = SIM_STATE.get("assistant_coaches", {}).get(team_name, [])
    return sum(c["bonus"] for c in staff if c["role"] == role)


# ----------------------------------------------------------
# MAJOR 4: Front-office reputation (GM trust score). See
# trade_acceptance_threshold/adjust_gm_trust above -- this
# just exposes a read helper for the UI.
# ----------------------------------------------------------
def gm_trust_snapshot():
    return {t: SIM_STATE.get("gm_trust", {}).get(t, 50.0) for t in NBA_TEAMS if t != SIM_STATE["user_team"]}


# ----------------------------------------------------------
# MAJOR 5: Salary cap history/projections UI (backend calc).
# ----------------------------------------------------------
def cap_projection(team_name, years=4):
    roster = team_roster(team_name)
    projections = []
    for offset in range(years):
        committed = 0.0
        expiring = 0
        for p in roster:
            c = p.get("contract")
            if not c:
                continue
            if c["years_left"] > offset:
                committed += c["salary"]
            elif c["years_left"] == offset:
                expiring += 1
        projections.append({
            "year": SIM_STATE["year"] + offset,
            "committed": round(committed, 1),
            "cap_space_est": round(SALARY_CAP - committed, 1),
            "contracts_expiring": expiring,
        })
    return projections


# ----------------------------------------------------------
# MAJOR 6: Rivalries & narrative arcs.
# ----------------------------------------------------------
def rivalry_key(team_a, team_b):
    return "|".join(sorted([team_a, team_b]))


def record_rivalry_meeting(team_a, team_b, is_playoff=False):
    key = rivalry_key(team_a, team_b)
    r = SIM_STATE["rivalries"].setdefault(key, {
        "teams": [team_a, team_b], "meetings": 0, "playoff_meetings": 0, "trades": 0,
        "heat": 0,           # 0-100 rivalry intensity score
        "moments": [],       # memorable game moments / story beats
        "series_wins": {team_a: 0, team_b: 0},  # all-time head-to-head dominance
    })
    r["meetings"] += 1
    r.setdefault("series_wins", {team_a: 0, team_b: 0})
    heat_gain = 3 if not is_playoff else 10   # playoff meetings spike intensity
    if is_playoff:
        r["playoff_meetings"] += 1
        r["heat"] = min(100, r.get("heat", 0) + heat_gain)
        if r["playoff_meetings"] >= 2:
            # Generate a rivalry moment narrative
            templates = [
                f"{team_a} and {team_b} clash again in the playoffs — bad blood is building.",
                f"Another postseason showdown: {team_a} vs {team_b}. These two can't stand each other.",
                f"The {team_a}–{team_b} rivalry rages on — fans have circled this playoff rematch all season.",
            ]
            moment = random.choice(templates)
            r.setdefault("moments", []).append({"year": SIM_STATE["year"], "text": moment, "type": "playoff"})
            if len(r["moments"]) > 10:
                r["moments"] = r["moments"][-10:]
            if r["playoff_meetings"] == 2:
                push_news("🔥", moment, "rivalry")
    else:
        r["heat"] = min(100, r.get("heat", 0) + 1)
    # Heat decays slightly each season so dead rivalries cool off
    # (this tick also runs on the first meeting of the season, minimal effect)


def record_rivalry_winner(home_team, home_score, away_team, away_score, is_playoff):
    """Called after each game to update series record."""
    key = rivalry_key(home_team, away_team)
    r = SIM_STATE["rivalries"].get(key)
    if not r:
        return
    winner = home_team if home_score > away_score else away_team
    r.setdefault("series_wins", {home_team: 0, away_team: 0})
    r["series_wins"][winner] = r["series_wins"].get(winner, 0) + 1


def decay_rivalries():
    """Called once per season — slightly cools all rivalry heat so
    inactive matchups don't stay at max intensity forever."""
    for r in SIM_STATE.get("rivalries", {}).values():
        r["heat"] = max(0, r.get("heat", 0) - 5)


def rivalry_intensity_label(heat):
    if heat >= 80: return ("🔥🔥🔥", "Legendary Rivalry")
    if heat >= 55: return ("🔥🔥", "Heated Rivalry")
    if heat >= 30: return ("🔥", "Developing Rivalry")
    if heat >= 10: return ("😤", "Budding Tension")
    return ("", "Familiar Foes")


def record_rivalry_trade(team_a, team_b):
    key = rivalry_key(team_a, team_b)
    r = SIM_STATE["rivalries"].setdefault(key, {"teams": [team_a, team_b], "meetings": 0, "playoff_meetings": 0, "trades": 0})
    r["trades"] += 1


def rivalry_note(team_a, team_b):
    r = SIM_STATE["rivalries"].get(rivalry_key(team_a, team_b))
    if not r or (r["meetings"] < 6 and r["playoff_meetings"] < 2 and r["trades"] == 0):
        return None
    bits = []
    if r["playoff_meetings"] >= 2:
        bits.append(f"{r['playoff_meetings']}x playoff rivals")
    if r["meetings"] >= 6:
        bits.append(f"{r['meetings']} all-time meetings")
    if r["trades"] > 0:
        bits.append(f"{r['trades']} trade{'s' if r['trades'] != 1 else ''} between them")
    return " • ".join(bits) if bits else None


def top_rivalries(team_name, n=5):
    rows = []
    for key, r in SIM_STATE.get("rivalries", {}).items():
        if team_name not in r.get("teams", []):
            continue
        other = r["teams"][0] if r["teams"][1] == team_name else r["teams"][1]
        heat = r.get("heat", r["meetings"] + r["playoff_meetings"] * 4 + r["trades"] * 2)
        rows.append({
            "team": other, "meetings": r["meetings"],
            "playoff_meetings": r["playoff_meetings"], "trades": r["trades"],
            "heat": heat,
            "moments": r.get("moments", []),
            "series_wins": r.get("series_wins", {}),
            "teams": r["teams"],
        })
    rows.sort(key=lambda x: -x["heat"])
    return rows[:n]


# ----------------------------------------------------------
# MAJOR 7: Practice/training-camp mini-game. Offseason-only
# "attribute focus" budget spent on specific players instead
# of pure random progression.
# ----------------------------------------------------------
PRACTICE_POINTS_PER_OFFSEASON = 5
PRACTICE_FOCUS_ATTRS = {
    "Shooting": ["Mid-Range", "Three-Point", "Free Throw"],
    "Finishing": ["Close Shot", "Driving Layup", "Driving Dunk"],
    "Playmaking": ["Passing Accuracy", "Ball Handling", "Vision"],
    "Defense": ["Interior Defense", "Perimeter Defense", "Steal", "Block"],
    "Physical": ["Speed", "Strength", "Vertical", "Stamina"],
}


def allocate_practice_points(team_name, player_name, focus, points):
    if SIM_STATE["stage"] != "offseason":
        return {"success": False, "reason": "Practice focus can only be set during the offseason."}
    if focus not in PRACTICE_FOCUS_ATTRS:
        return {"success": False, "reason": f"Unknown focus area. Choose from: {', '.join(PRACTICE_FOCUS_ATTRS)}."}
    p = SIM_STATE["players"].get(player_name)
    if not p or p.get("team") != team_name:
        return {"success": False, "reason": "That player isn't on this roster."}
    try:
        points = int(points)
    except (TypeError, ValueError):
        return {"success": False, "reason": "Points must be a whole number."}
    remaining = SIM_STATE["practice_points"].get(team_name, 0)
    if points <= 0 or points > remaining:
        return {"success": False, "reason": f"{team_name} only has {remaining} practice point(s) left this offseason."}

    for attr in PRACTICE_FOCUS_ATTRS[focus]:
        if attr in p["attributes"]:
            p["attributes"][attr] = clamp(p["attributes"][attr] + points * 0.8)
    p["rating"] = calc_rating(p["attributes"])
    p["badges"] = compute_badges(p)
    SIM_STATE["practice_points"][team_name] = remaining - points
    return {"success": True, "remaining": remaining - points, "new_rating": p["rating"]}


def refill_practice_points():
    for t in NBA_TEAMS:
        SIM_STATE["practice_points"][t] = PRACTICE_POINTS_PER_OFFSEASON


# ----------------------------------------------------------
# MAJOR 8: International scouting (stash-and-hold pipeline).
# Adds an "international" flag + stash timer onto a slice of
# each draft class; stashed picks sit off-roster (not counted
# against the 15-man limit) until their timer runs out.
# ----------------------------------------------------------
def tag_international_prospects(draft_pool):
    for i, p in enumerate(draft_pool):
        if random.random() < 0.18:
            p["international"] = True
            p["stash_years"] = random.choice([1, 1, 2])
            p["origin"] = random.choice(["Adriatic League", "EuroCup", "Australian NBL", "Liga ACB", "Chinese CBA"])
        else:
            p["international"] = False
            p["stash_years"] = 0
    return draft_pool


def stash_or_activate_drafted_player(p, team_name):
    """Called right after execute_draft_pick assigns a team. If the prospect
    was tagged international with stash years remaining, park him off the
    active roster (not cap/roster-counted) instead of activating him."""
    if p.get("international") and p.get("stash_years", 0) > 0:
        SIM_STATE.setdefault("stashed_players", {}).setdefault(team_name, []).append(p["name"])
        p["team"] = team_name
        p["stashed"] = True
        return True
    return False


def tick_stashed_players():
    """Run once per offseason: count down stash timers and promote anyone
    who's ready to actually join the active roster."""
    promoted = []
    for team_name, names in list(SIM_STATE.get("stashed_players", {}).items()):
        still = []
        for name in names:
            p = SIM_STATE["players"].get(name)
            if not p:
                continue
            p["stash_years"] = max(0, p.get("stash_years", 0) - 1)
            if p["stash_years"] <= 0:
                p["stashed"] = False
                promoted.append(name)
                recompute_cap(team_name)
            else:
                still.append(name)
        SIM_STATE["stashed_players"][team_name] = still
    return promoted


# ----------------------------------------------------------
# MAJOR 9: In-game coaching decisions (timeout usage,
# defensive scheme, late-game fouling) as live choices during
# "Jump Into Game", not just pre-game dials.
# ----------------------------------------------------------
def set_ingame_strategy(team_name, defensive_scheme=None, foul_when_trailing=None):
    if team_name not in NBA_TEAMS:
        return {"success": False, "reason": "Unknown team."}
    overrides = SIM_STATE.setdefault("ingame_strategy_bonus", {})
    entry = overrides.setdefault(team_name, {})
    if defensive_scheme is not None:
        entry["defensive_scheme"] = defensive_scheme
    if foul_when_trailing is not None:
        entry["foul_when_trailing"] = bool(foul_when_trailing)
    return {"success": True, "strategy": entry}


def apply_ingame_strategy_to_clutch(team_name, is_trailing, swing):
    """Consulted from apply_clutch_factor: a live 'foul when trailing' call
    adds extra late-game variance (more empty/extra possessions), same
    spirit as real end-game fouling strategy -- higher risk, higher reward."""
    entry = SIM_STATE.get("ingame_strategy_bonus", {}).get(team_name)
    if not entry:
        return swing
    if entry.get("foul_when_trailing") and is_trailing:
        swing += random.gauss(0, 2.2)
    return swing


def clear_ingame_strategy():
    SIM_STATE["ingame_strategy_bonus"] = {}


# ----------------------------------------------------------
# MAJOR 10: The four deep-architecture items flagged in the
# previous pass (SQLite/SQLAlchemy backend, modular REST +
# separate frontend, possession-level sim engine, multiplayer/
# session-keyed state) are deliberately NOT attempted here.
# Each is a full rewrite of a load-bearing part of this
# single-file app, not an additive feature, and bolting any of
# them on without a dedicated session/tests would risk the
# whole app's stability. See the chat response for a scoped
# proposal on any one of them.
# ----------------------------------------------------------




seed_league()
build_schedule()
setup_in_season_cup()
SIM_STATE["trade_deadline_day"] = int(SIM_STATE["schedule_days_total"] * TRADE_DEADLINE_FRACTION)
# UPGRADE BATCH 6: backfill league history since 1984 for the default boot league too.


def team_roster(team_name):
    return [p for p in SIM_STATE["players"].values() if p["team"] == team_name and not p["retired"]]


def team_picks(team_name):
    return [pk for pk in SIM_STATE["draft_picks"].values() if pk["current_team"] == team_name]


# ==========================================
# ENGINE SIMULATION LOGIC
# ==========================================
def effective_minutes(p):
    """UPGRADE: Smarter AI rotations — fatigue and personality now affect
    how many real minutes a player actually plays vs their allocation."""
    if p.get("injury") and p["injury"].get("games_remaining", 0) > 0:
        return 0
    base = p["minutes"]
    if base <= 0:
        return 0
    # Heavy fatigue pulls real minutes down (tired players sit more)
    fatigue = p.get("fatigue", 0)
    if fatigue > 75:
        base = max(0, base - round((fatigue - 75) / 10))
    # Personality modifiers: Lazy players sometimes ghost minutes, Gym Rats play through
    trait = p.get("personality_trait", "Professional")
    if trait == "Lazy" and random.random() < 0.15:
        base = max(0, base - random.randint(2, 5))
    elif trait == "Gym Rat" and fatigue > 60 and random.random() < 0.20:
        base = min(base + 2, 42)  # plays through fatigue
    return base


def sim_team_stats(team_name, opponent_name=None, is_home=False):
    """
    Simulates one team's box score for a game. If opponent_name is supplied, the
    opponent's live coaching strategy (defensive scheme, rebounding style) pushes
    back on this team's efficiency and volume -- a lightweight 2K-style team-style
    engine (pace, shooting willingness, offensive archetype, defensive scheme,
    rebounding style all move the numbers).
    """
    team_players = [p for p in SIM_STATE["players"].values() if p["team"] == team_name and not p["retired"]]
    team_stats = {}
    team_cfg = SIM_STATE["teams"].get(team_name, {})
    opp_cfg = SIM_STATE["teams"].get(opponent_name, {}) if opponent_name else {}

    # --- Team chemistry: a well-gelled roster shoots a bit better and turns the
    # ball over a bit less than a disjointed one. Centered at 65 (the league-average
    # starting value) so a fresh roster is neutral; a 90+ chemistry juggernaut and a
    # 20-chemistry fire drill both feel meaningfully different on the floor.
    chem = team_cfg.get("chemistry", 65.0)
    chem_fg_bonus = (chem - 65.0) * 0.0006
    chem_tov_mod = 1.0 - (chem - 65.0) * 0.003

    # --- Coaching system: only pays off when the team's own live strategy dials
    # actually match the coach's scheme identity -- otherwise the coach's system
    # sits dormant. This rewards building a roster/scheme combo around the coach
    # you hired instead of a flat, unconditional stat boost.
    coach_fg_bonus = coach_tp_bonus = coach_def_fg_bonus = coach_def_tp_bonus = 0.0
    coach_ast_bonus = coach_reb_bonus = 0.0
    coach_tov_mod = 1.0
    coach_cfg = SIM_STATE.get("coaches", {}).get(team_name)
    if coach_cfg:
        sysdef = COACH_SYSTEMS.get(coach_cfg.get("system"), {})
        matches = (
            (sysdef.get("affinity_offense") and sysdef["affinity_offense"] == team_cfg.get("offensive_priority")) or
            (sysdef.get("affinity_defense") and sysdef["affinity_defense"] == team_cfg.get("defensive_priority")) or
            (sysdef.get("affinity_pace") and sysdef["affinity_pace"] == team_cfg.get("pace")) or
            (sysdef.get("affinity_rebounding") and sysdef["affinity_rebounding"] == team_cfg.get("rebounding_style")) or
            (sysdef.get("affinity_shooting") and sysdef["affinity_shooting"] == team_cfg.get("shooting_willingness"))
        )
        if matches:
            # Fit improves further the longer a coach has been with the team
            # (staff continuity / player buy-in).
            tenure_mult = min(1.5, 1.0 + coach_cfg.get("years_with_team", 1) * 0.05)
            coach_fg_bonus = sysdef.get("fg_bonus", 0.0) * tenure_mult
            coach_tp_bonus = sysdef.get("tp_bonus", 0.0) * tenure_mult
            coach_ast_bonus = sysdef.get("ast_bonus", 0.0) * tenure_mult
            coach_reb_bonus = sysdef.get("reb_bonus", 0.0) * tenure_mult
            coach_tov_mod = 1.0 - (1.0 - sysdef.get("tov_mod", 1.0)) * tenure_mult
    # The opponent's coach can also press their scheme's defensive edge onto us.
    opp_coach_cfg = SIM_STATE.get("coaches", {}).get(opponent_name) if opponent_name else None
    if opp_coach_cfg:
        opp_sysdef = COACH_SYSTEMS.get(opp_coach_cfg.get("system"), {})
        opp_matches = (
            (opp_sysdef.get("affinity_defense") and opp_sysdef["affinity_defense"] == opp_cfg.get("defensive_priority"))
        )
        if opp_matches:
            coach_def_fg_bonus += opp_sysdef.get("def_fg_bonus", 0.0)
            coach_def_tp_bonus += opp_sysdef.get("def_tp_bonus", 0.0)

    total_weight = sum([effective_minutes(p) * (p["rating"] ** 2) for p in team_players if effective_minutes(p) > 0])
    if total_weight == 0:
        total_weight = 1

    # --- Pace: scales overall possessions (shots, FTs, boards, assists all move together) ---
    pace_mult = {"Slow": 0.90, "Balanced": 1.0, "Fast": 1.12}.get(team_cfg.get("pace", "Balanced"), 1.0)
    # Fast Break Heavy offense also genuinely pushes pace up (more possessions,
    # not just more 3s) -- applied here, before possession totals are rolled,
    # so it actually affects shot/rebound/assist volume rather than doing nothing.
    if team_cfg.get("offensive_priority") == "Fast Break Heavy":
        pace_mult *= 1.06

    team_fga = int(random.randint(84, 98) * pace_mult)
    team_fta = int(random.randint(18, 28) * pace_mult)
    # BUGFIX: rebound opportunities used to ignore pace entirely, so a "Fast" pace
    # team generated more shots/assists but not more boards. Rebounds should scale
    # with possessions (more shots = more misses = more rebound chances) too.
    team_reb = int(random.randint(38, 52) * (0.6 + 0.4 * pace_mult))
    team_ast = int(random.randint(22, 32) * pace_mult * (1 + coach_ast_bonus))
    team_tov = max(6, int(random.randint(11, 16) * (0.9 + 0.2 * pace_mult) * coach_tov_mod))
    team_score = 0

    # UPGRADE PASS (deeper coaching controls): the 10 Coaching Gameplan
    # sliders (Crash Glass, Help Defense, Zone Frequency, Double Team,
    # Defensive Pressure, Transition Focus, Star Usage, Bench Usage,
    # Switch Everything, Pace) previously only fed a cosmetic team-identity
    # label and one scouting-report sentence -- they never actually moved a
    # single stat in the box score. Wire them in for real, each centered at
    # 50 (neutral) so an untouched team plays exactly as it did before.
    my_plan = get_coaching_gameplan(team_name)
    opp_plan = get_coaching_gameplan(opponent_name) if opponent_name else {s: 50 for s in GAMEPLAN_SLIDERS}

    def slider_pull(plan, key):
        return (plan.get(key, 50) - 50) / 50.0  # -1.0 .. +1.0

    # Crash Glass: more guys attacking the offensive boards = more of my own
    # misses turn into extra shots, at the cost of transition defense (I
    # already have that trade-off from rebounding_style; this slider adds a
    # second, finer-grained lever on top of it).
    team_reb = int(team_reb * (1 + 0.16 * slider_pull(my_plan, "Crash Glass")))
    # Transition Focus: genuinely pushes pace, same mechanism as Fast Break
    # Heavy above but continuous instead of all-or-nothing.
    team_fga = int(team_fga * (1 + 0.08 * slider_pull(my_plan, "Transition Focus")))
    team_ast = int(team_ast * (1 + 0.05 * slider_pull(my_plan, "Transition Focus")))
    # Star Usage: shifts shot volume toward/away from the top option -- the
    # actual per-player usage split happens later where scoring_option is
    # applied; here it just banks the pull for that step to read.
    star_usage_pull = slider_pull(my_plan, "Star Usage")
    # Bench Usage: shifts minutes-weighted usage toward/away from the bench
    # rather than free stats -- actual effect applied in the per-player
    # scoring-option loop below, where each player's minutes are already
    # being weighed against the rotation.
    bench_usage_pull = slider_pull(my_plan, "Bench Usage")

    # --- Opponent-side sliders push back on THIS team, same spirit as the
    # opponent's categorical defensive scheme above but continuous. ---
    opp_help_pull = slider_pull(opp_plan, "Help Defense")      # tighter rim D, looser perimeter
    opp_zone_pull = slider_pull(opp_plan, "Zone Frequency")    # softer paint pressure, live passing lanes -> more TOV risk
    opp_double_pull = slider_pull(opp_plan, "Double Team")     # extra pressure on the primary ball-handler
    opp_pressure_pull = slider_pull(opp_plan, "Defensive Pressure")  # more contests + more fouls both ways

    # --- Home-court advantage: a real, modest boost instead of just breaking ties ---
    home_fg_bonus = 0.012 if is_home else -0.004
    home_reb_bonus = 0.03 if is_home else -0.02

    # --- Shooting willingness: shifts overall 3PT rate up/down league-wide for this team ---
    willingness_shift = {"Conservative": -0.05, "Balanced": 0.0, "Aggressive": 0.07}.get(
        team_cfg.get("shooting_willingness", "Balanced"), 0.0)
    # --- Offensive archetype nudges shot selection further ---
    # UPGRADE (more offense/defense options pass): Small Ball leans into
    # the modern spread-the-floor, no-true-center look -- max 3PT rate but
    # it costs you on the glass. Grit and Grind is the physical, grind-it-out
    # counter -- pounds the paint and draws fouls, at the expense of pace
    # and efficient outside shooting.
    archetype_shift = {"Pace & Space": 0.10, "Post-Up Heavy": -0.10, "Iso-Heavy": -0.03,
                        "Motion Offense": 0.02, "Fast Break Heavy": 0.06, "Pick-and-Roll Heavy": 0.03,
                        "Small Ball": 0.14, "Grit and Grind": -0.08,
                        "Balanced": 0.0}.get(team_cfg.get("offensive_priority", "Balanced"), 0.0)
    # Pick-and-Roll Heavy funnels extra usage through the primary ball-handler's
    # reads, so it bumps assist generation specifically rather than just 3PT rate.
    if team_cfg.get("offensive_priority") == "Pick-and-Roll Heavy":
        team_ast = int(team_ast * 1.08)
    # Small Ball trades size for shooting/pace -- more possessions and 3PA,
    # fewer offensive boards (nobody crashing the glass in a 5-out look).
    if team_cfg.get("offensive_priority") == "Small Ball":
        team_reb = int(team_reb * 0.92)
    # Grit and Grind grinds the game out in the paint -- more trips to the
    # line, since that style lives on drawing contact and second-chance points.
    grit_fta_bonus = 1.12 if team_cfg.get("offensive_priority") == "Grit and Grind" else 1.0

    # --- Opponent defensive scheme: pushes back on this team's shooting efficiency ---
    opp_def = opp_cfg.get("defensive_priority", "Man-to-Man")
    fg_pct_mod = 0.0
    tp_pct_mod = 0.0
    fta_mod = 1.0
    if opp_def == "2-3 Zone Package":
        tp_pct_mod = 0.025          # zones are looser on the perimeter
        fg_pct_mod = -0.015         # but clog the paint a little
    elif opp_def == "Full-Court Press":
        fta_mod = 1.10              # more scrambling fouls
        fg_pct_mod = -0.01
    elif opp_def == "Switch Everything":
        fg_pct_mod = -0.02
        tp_pct_mod = -0.01
    elif opp_def == "Box-and-1":
        fg_pct_mod = 0.015          # everyone else gets looser looks...
        tp_pct_mod = 0.02
    elif opp_def == "Triangle-and-2":
        fg_pct_mod = 0.02           # ...even more so, since two defenders are tied up
    elif opp_def == "Drop Coverage":
        # UPGRADE: Drop Coverage -- the big sits back near the paint against
        # ball-screens, conceding the mid-range but walling off the rim and
        # discouraging drives. Real modern-NBA scheme that wasn't
        # represented at all before.
        fg_pct_mod = -0.025         # tougher shots at the rim
        tp_pct_mod = 0.015          # but more open pull-up 3s off the screen
    elif opp_def == "Blitz the Pick-and-Roll":
        # Double-teams the ball-handler immediately off every screen --
        # high risk, high reward: forces empty possessions but the extra
        # defender has to come from somewhere, so shooters left open by the
        # rotation get real efficiency added back.
        fg_pct_mod = -0.03
        tp_pct_mod = 0.035
        fta_mod *= 1.05             # more scrambling contact fouls

    # Coaching system bonuses layer on top of the scheme adjustments above.
    fg_pct_mod += coach_fg_bonus + coach_def_fg_bonus
    tp_pct_mod += coach_tp_bonus + coach_def_tp_bonus

    # --- Opponent Coaching Gameplan sliders push back on this team too,
    # continuous on top of their categorical defensive scheme above. ---
    # Help Defense: crashing extra bodies to the paint = tougher shots at
    # the rim, but leaves shooters open on the weak side.
    fg_pct_mod -= 0.03 * opp_help_pull
    tp_pct_mod += 0.02 * opp_help_pull
    # Zone Frequency: a real zone possession-by-possession (not just the
    # binary "2-3 Zone Package" scheme) softens rim pressure and opens
    # passing/driving lanes -- but scrambled zone rotations cough up live-ball
    # turnovers when attacked with quick ball movement.
    fg_pct_mod += 0.015 * opp_zone_pull
    team_tov = max(4, int(team_tov * (1 + 0.08 * opp_zone_pull)))
    # Double Team: extra defensive attention on the primary scorer knocks
    # down efficiency league-wide for this team (the per-player star_usage
    # step below layers the more targeted hit on the actual top option).
    fg_pct_mod -= 0.02 * opp_double_pull
    team_tov = max(4, int(team_tov * (1 + 0.05 * opp_double_pull)))
    # Defensive Pressure: contests everything harder -- costs this team
    # efficiency and draws more scrambling fouls both ways.
    fg_pct_mod -= 0.02 * opp_pressure_pull
    fta_mod *= (1 + 0.06 * opp_pressure_pull)

    # --- Opponent rebounding style affects how many boards THIS team can grab ---
    opp_reb_style = opp_cfg.get("rebounding_style", "Balanced")
    opp_reb_pressure = {"Crash Offensive Glass": -0.05, "Balanced": 0.0, "Get Back on Defense": 0.08}.get(opp_reb_style, 0.0)
    # --- This team's own rebounding style trades boards for transition defense ---
    own_reb_style = team_cfg.get("rebounding_style", "Balanced")
    own_reb_mod = {"Crash Offensive Glass": 0.15, "Balanced": 0.0, "Get Back on Defense": -0.10}.get(own_reb_style, 0.0)
    team_reb = max(20, int(team_reb * (1 + own_reb_mod + opp_reb_pressure + home_reb_bonus + coach_reb_bonus)))

    # --- Scoring Options: who gets featured in the shot-usage pecking order ---
    scoring_option = team_cfg.get("scoring_option", "Balanced Attack")
    best_scorer_name = None
    second_scorer_name = None
    if team_players:
        eligible = [p for p in team_players if effective_minutes(p) > 0]
        if eligible:
            ranked = sorted(eligible, key=lambda pl: pl["rating"], reverse=True)
            # UPGRADE PASS: "Featured Scorer" used to always feed whichever
            # player the system decided was the rating leader -- there was
            # no way to say "no, actually run the offense through THIS
            # guy," even if he's not technically the highest-rated player
            # on the roster (a team's actual best offensive weapon isn't
            # always its best overall rated player). designated_star is a
            # per-team pick the user can set; if it's unset, hurt, or not
            # actually getting minutes tonight, this falls back to the old
            # auto-pick-the-best-available behavior exactly as before.
            designated_star = team_cfg.get("designated_star")
            star_player = next((pl for pl in eligible if pl["name"] == designated_star), None) if designated_star else None
            if star_player:
                best_scorer_name = star_player["name"]
                rest_ranked = [pl for pl in ranked if pl["name"] != best_scorer_name]
                second_scorer_name = rest_ranked[0]["name"] if rest_ranked else None
            else:
                best_scorer_name = ranked[0]["name"]
                if len(ranked) > 1:
                    second_scorer_name = ranked[1]["name"]

    # A Box-and-1 keys entirely on the opponent's #1 option; Triangle-and-2 spreads
    # that same defensive attention across their top two -- both trade tighter
    # coverage on the stars for looser coverage on everyone else (handled above
    # via fg_pct_mod/tp_pct_mod being *positive* league-wide for this team).
    shadowed_players = set()
    if opp_def == "Box-and-1" and best_scorer_name:
        shadowed_players = {best_scorer_name}
    elif opp_def == "Triangle-and-2":
        shadowed_players = {n for n in (best_scorer_name, second_scorer_name) if n}

    for p in team_players:
        emin = effective_minutes(p)
        if emin == 0:
            continue

        attrs = p["attributes"]
        cats = derive_categories(attrs)
        tend = p["tendencies"]
        weight = (emin * (p["rating"] ** 2)) / total_weight

        if scoring_option == "Featured Scorer" and p["name"] == best_scorer_name:
            weight *= 1.28
        elif scoring_option == "Featured Scorer":
            weight *= 0.94
        elif scoring_option == "Everyone Shoots":
            weight = (weight + (1.0 / max(1, len(team_players)))) / 2.0

        # Star Usage slider (continuous version of the Featured Scorer /
        # Everyone Shoots toggle): nudges shot volume toward or away from
        # the top-two options on a 0-100 dial instead of a 3-way switch,
        # so "a little more usage for my star" is an actual option, not
        # just full Featured Scorer or nothing.
        if p["name"] == best_scorer_name:
            weight *= (1 + 0.22 * star_usage_pull)
        elif p["name"] != second_scorer_name:
            weight *= (1 - 0.10 * star_usage_pull)
        # Bench Usage slider: shifts real shot volume toward or away from
        # the bench (players outside the top 5 by rating among the
        # rotation getting minutes), independent of the starter-focused
        # Star Usage dial above.
        bench_cutoff_rating = ranked[min(4, len(ranked) - 1)]["rating"] if ranked else 0
        is_bench = p["rating"] < bench_cutoff_rating
        if is_bench:
            weight *= (1 + 0.12 * bench_usage_pull)
        else:
            weight *= (1 - 0.05 * bench_usage_pull)

        # A shadowed star eats a real, separate efficiency hit on top of the
        # scheme's league-wide modifiers above. The Double Team slider adds
        # a continuous version of the same idea, targeted at whoever is
        # actually this team's #1 option, on top of any categorical scheme.
        shadow_fg_penalty = 0.06 if p["name"] in shadowed_players else 0.0
        shadow_tp_penalty = 0.05 if p["name"] in shadowed_players else 0.0
        if p["name"] == best_scorer_name and opp_double_pull > 0:
            shadow_fg_penalty += 0.04 * opp_double_pull
            weight *= (1 - 0.08 * opp_double_pull)  # doubled star gives the ball up more

        # --- Fatigue: heavy minutes on low-Stamina legs erode shooting efficiency
        # and rebounding effort. This was previously generated (attrs["Stamina"])
        # but never actually consumed anywhere in the sim -- now it matters.
        fatigue_pct = clamp(p.get("fatigue", 0), 0, 100) / 100.0
        fatigue_fg_penalty = fatigue_pct * 0.06
        fatigue_reb_penalty = fatigue_pct * 0.10

        # --- Hot/cold streak: a temporary shooting nudge carried over from
        # recent performance (see update_form()), same feel as 2K's momentum.
        form_bonus = p.get("form", 0.0) * 0.035

        fga = max(0, int(team_fga * weight) + random.randint(-1, 2))
        fg_pct = max(0.28, min(0.68, random.gauss(0.45 + (cats["Inside"] - 70) * 0.002 + fg_pct_mod + home_fg_bonus - fatigue_fg_penalty - shadow_fg_penalty + form_bonus, 0.05)))
        fgm = int(fga * fg_pct)

        tpa_fraction = max(0.05, min(0.80, 0.15 + (tend["Shoot 3PT"] - 35) * 0.01 + willingness_shift + archetype_shift))
        tpa = int(fga * tpa_fraction)
        tp_pct = max(0.18, min(0.55, random.gauss(0.35 + (cats["Outside"] - 70) * 0.002 + tp_pct_mod + home_fg_bonus - fatigue_fg_penalty * 0.7 - shadow_tp_penalty + form_bonus, 0.05)))
        tpm = int(tpa * tp_pct)
        if tpm > fgm:
            tpm = fgm

        fta = max(0, int(team_fta * weight * (1 + (tend["Draw Fouls"] - 30) * 0.01) * fta_mod * grit_fta_bonus) + random.randint(-1, 1))
        ftm = int(fta * random.gauss(0.65 + (cats["Outside"] - 70) * 0.002, 0.06))

        pts = (fgm - tpm) * 2 + (tpm * 3) + ftm
        team_score += pts

        reb = int(team_reb * weight * (1.8 if p["position"] in ["C", "PF"] else 0.5) *
                  (1 + (tend["Crash Offensive Glass"] - 30) * 0.003) * (1 - fatigue_reb_penalty))
        ast = int(team_ast * weight * (1.8 if p["position"] in ["PG", "SG"] else 0.4) *
                  (1 + (tend["Pass"] - 35) * 0.004))

        stl = max(0, int((team_fga * weight) * random.uniform(0.04, 0.12) * (cats["Defense"] / 75)))
        blk = max(0, int((team_fga * weight) * random.uniform(0.02, 0.1) * (2.0 if p["position"] in ["C", "PF"] else 0.3) * (cats["Defense"] / 75)))

        # --- Turnovers: a real box-score stat that was completely missing before.
        # Ball-handling/vision reduce turnover rate; high-usage guards who touch the
        # ball more (Pick & Roll / Pass tendencies) commit more of them; fatigue adds a few.
        handle_factor = max(0.5, 1.25 - (attrs["Ball Handling"] - 50) * 0.006 - (attrs["Vision"] - 50) * 0.003 -
                            (attrs["Ball Security"] - 50) * 0.005)
        usage_factor = 1.0 + (tend["Pick & Roll Ball Handler"] - 30) * 0.004 + (tend["Pass"] - 35) * 0.003
        tov = max(0, int(team_tov * weight * handle_factor * usage_factor * (1 + fatigue_pct * 0.2)) + random.randint(-1, 1))

        team_stats[p["name"]] = {"FGM": fgm, "FGA": fga, "3PM": tpm, "3PA": tpa, "FTM": ftm, "FTA": fta,
                                  "PTS": pts, "REB": reb, "AST": ast, "STL": stl, "BLK": blk, "TOV": tov}

    return team_stats, team_score


# UPGRADE: Injury system depth. Instead of one flat injury model (a single
# random duration off a generic description list), injuries now come from a
# real body region with a severity tier, and getting hurt again in the same
# region shortly after returning carries real elevated risk -- reflecting how
# re-aggravation actually works.
INJURY_REGIONS = {
    "Ankle": {"Minor": "Ankle Sprain", "Moderate": "Ankle Sprain (Grade 2)",
              "Major": "High Ankle Sprain", "Severe": "Ankle Fracture"},
    "Knee": {"Minor": "Knee Soreness", "Moderate": "Knee Sprain",
             "Major": "Knee Bone Bruise", "Severe": "Meniscus Tear"},
    "Back": {"Minor": "Back Spasms", "Moderate": "Lower Back Strain",
             "Major": "Disc Irritation", "Severe": "Herniated Disc"},
    "Hamstring": {"Minor": "Hamstring Tightness", "Moderate": "Hamstring Strain",
                  "Major": "Grade 2 Hamstring Strain", "Severe": "Hamstring Tear"},
    "Wrist/Hand": {"Minor": "Wrist Soreness", "Moderate": "Wrist Sprain",
                   "Major": "Finger Fracture", "Severe": "Wrist Fracture"},
    "Shoulder": {"Minor": "Shoulder Soreness", "Moderate": "AC Joint Sprain",
                 "Major": "Shoulder Strain", "Severe": "Labrum Tear"},
    "Illness": {"Minor": "Flu-Like Illness", "Moderate": "Viral Illness",
                "Major": "Extended Illness", "Severe": "Extended Illness"},
}
INJURY_TIER_GAMES = {"Minor": (1, 3), "Moderate": (4, 9), "Major": (10, 20), "Severe": (21, 40)}
REINJURY_WINDOW_GAMES = 10     # games after return during which risk stays elevated
REINJURY_RISK_MULT = 2.2       # risk multiplier while inside that window


def maybe_injure_players(team_stats_dict):
    """
    BUGFIX/UPGRADE: injury chance used to be a flat 0.5% for every player, which
    meant the "Durability" attribute (generated for every player) was completely
    decorative. Now fragile (low-Durability) and fatigued players are meaningfully
    more injury-prone, and their injuries tend to run longer.

    UPGRADE: injury history now escalates future risk. A player who's already
    racked up several injuries this era of his career is a real "injury prone"
    guy going forward -- not just a fresh independent coin flip every single
    game like before. This makes durability an actual long-term trait that
    shows up on a player's page, not just a hidden attribute.

    UPGRADE: injury system depth. Injuries now draw from a real body region
    with a severity tier (Minor/Moderate/Major/Severe) instead of one flat
    duration model, and a player who's still inside his re-injury window
    (see REINJURY_WINDOW_GAMES) is at meaningfully higher risk of re-hurting
    the *same* region -- and re-aggravations run more severe than a fresh
    injury would.
    """
    for name in team_stats_dict:
        p = SIM_STATE["players"].get(name)
        if not p or p.get("injury"):
            continue
        durability = p["attributes"].get("Durability", 70)
        fatigue_pct = clamp(p.get("fatigue", 0), 0, 100) / 100.0
        history_count = p.get("injury_history_count", 0)
        history_mult = 1.0 + min(history_count, 6) * 0.12
        reinjury_active = p.get("reinjury_window", 0) > 0
        reinjury_mult = REINJURY_RISK_MULT if reinjury_active else 1.0
        chance = (0.003 + ((99 - durability) / 99.0) * 0.014 + fatigue_pct * 0.008) * history_mult * reinjury_mult
        if random.random() < chance:
            severity_score = ((99 - durability) / 99.0) + fatigue_pct * 0.4 + (0.35 if reinjury_active else 0)
            roll = random.random() + severity_score * 0.55
            if roll < 0.45:
                tier = "Minor"
            elif roll < 0.75:
                tier = "Moderate"
            elif roll < 0.93:
                tier = "Major"
            else:
                tier = "Severe"

            # Re-aggravating the same region as a recent injury; otherwise draw fresh.
            region = p.get("injury_region") if (reinjury_active and p.get("injury_region")) else random.choice(list(INJURY_REGIONS.keys()))
            desc = INJURY_REGIONS[region][tier]
            lo, hi = INJURY_TIER_GAMES[tier]
            games = random.randint(lo, hi)
            # UPGRADE: Medical facility reduces injury duration
            med_level = SIM_STATE.get("facilities", {}).get(p.get("team",""), {}).get("Medical", 1)
            med_mult = FACILITY_BONUS["injury_mult"][min(med_level - 1, 4)]
            games = max(1, int(round(games * med_mult)))

            p["injury"] = {"games_remaining": games, "description": desc, "status": injury_severity_label(games),
                            "region": region, "tier": tier, "reaggravation": reinjury_active}
            p["injury_history_count"] = history_count + 1
            p["injury_prone"] = p["injury_history_count"] >= 3
            p["injury_region"] = region
            if p["rating"] >= 78 or p["team"] == SIM_STATE.get("user_team"):
                reagg_txt = " -- a re-aggravation of a recent injury" if reinjury_active else ""
                push_news("🩹", f"{p['name']} ({p['team']}) is {p['injury']['status'].lower()} with a {tier.lower()} "
                                f"{desc.lower()}{reagg_txt} -- expected to miss {games} game{'s' if games != 1 else ''}.", "injury")


FATIGUE_RECOVERY_PER_DAY = 14


def update_fatigue_and_morale(team_name, team_stats_dict):
    """
    UPGRADE: brand-new fatigue and morale systems.
    Fatigue: players who log heavy minutes build up fatigue based on their Stamina
    attribute; everyone recovers a bit each game day (more if they didn't play/were
    hurt). High fatigue then feeds back into sim_team_stats as a real efficiency
    penalty and a higher injury chance above.
    Morale: tracks whether a player is getting run relative to how good he is, and
    whether his team is winning -- used to lightly color trade value and give the
    front office a read on locker-room temperature.
    """
    team_cfg = SIM_STATE["teams"].get(team_name, {})
    streak = team_cfg.get("streak", 0)
    # UPGRADE: Back-to-back travel fatigue — check if this team also played yesterday
    current_day = SIM_STATE.get("current_day", 1)
    last_game_day = team_cfg.get("last_game_day", -2)
    is_back_to_back = (current_day - last_game_day) == 1
    if team_name in [matchup["home"] if isinstance(matchup, dict) else "" for matchup in (SIM_STATE["schedule"][current_day - 1] if current_day > 0 and current_day <= len(SIM_STATE["schedule"]) else [])]:
        team_cfg["last_game_day"] = current_day
    for p in team_roster(team_name):
        played = p["name"] in team_stats_dict
        minutes = p["minutes"] if played else 0
        stamina = p["attributes"].get("Stamina", 70)
        if played and minutes > 0:
            load = minutes / 40.0
            gain = load * (1.7 - stamina / 100.0) * 16
            # Extra fatigue penalty on back-to-backs (reduced by Stamina)
            b2b_penalty = max(0, 8 - stamina / 20) if is_back_to_back else 0
            p["fatigue"] = clamp(p.get("fatigue", 0) + gain + b2b_penalty - FATIGUE_RECOVERY_PER_DAY * 0.35, 0, 100)
        else:
            p["fatigue"] = clamp(p.get("fatigue", 0) - FATIGUE_RECOVERY_PER_DAY, 0, 100)

        # --- Morale ---
        target_minutes = clamp((p["rating"] - 40) * 0.62, 2, 36)
        diff = minutes - target_minutes
        delta = 0.0
        if diff < -6:
            delta -= 0.5
        elif diff > 4:
            delta += 0.2
        if streak >= 3:
            delta += 0.3
        elif streak <= -3:
            delta -= 0.3
        if p.get("injury"):
            delta -= 0.15
        if p["contract"] and p["contract"]["years_left"] <= 1 and p["rating"] >= 78 and team_win_pct(team_name) < 0.40:
            delta -= 0.25  # a frustrated star watching a lost season with an expiring deal
        p["morale"] = clamp(p.get("morale", 70) + delta, 0, 100)

        # UPGRADE: Player morale/trade-request system. A player who stays
        # miserable for a sustained stretch -- not just one bad night -- can
        # formally ask out, giving real teeth to morale and letting unhappy
        # stars generate a "wants out" storyline instead of just a quiet
        # hidden number nobody ever sees consequences from.
        if p["morale"] < 35:
            p["low_morale_streak"] = p.get("low_morale_streak", 0) + 1
        else:
            p["low_morale_streak"] = 0
        maybe_file_trade_request(p, team_name)

    nudge_team_chemistry(team_name)


TRADE_REQUEST_MORALE_STREAK = 12   # consecutive low-morale games before a player can request out


def maybe_file_trade_request(p, team_name):
    if p.get("trade_request") or p.get("low_morale_streak", 0) < TRADE_REQUEST_MORALE_STREAK:
        return
    # Bigger names are more newsworthy and more willing to actually go public;
    # everyone's morale still tanks, but not every disgruntled bench piece
    # generates a front-office storyline.
    if p["rating"] < 68 and random.random() > 0.25:
        return
    if random.random() > 0.35:
        return  # even once eligible, a request isn't guaranteed every single check
    if team_win_pct(team_name) < 0.40:
        reason = "a lost season with no path to contending"
    elif p.get("minutes", 0) < clamp((p["rating"] - 40) * 0.62, 2, 36) - 6:
        reason = "a diminished role he feels he's outgrown"
    else:
        reason = "persistent unhappiness with the direction of the franchise"
    p["trade_request"] = {"since_day": SIM_STATE.get("current_day"), "since_year": SIM_STATE.get("year"), "reason": reason}
    SIM_STATE.setdefault("trade_requests", []).append({"player": p["name"], "team": team_name, "reason": reason,
                                                         "rating": p["rating"], "year": SIM_STATE.get("year")})
    push_news("📢", f"{p['name']} has requested a trade from {team_name}, citing {reason}.", "trade_rumor")


TRADE_RUMOR_CHANCE_PER_DAY = 0.05


def maybe_generate_trade_rumor():
    """
    UPGRADE: In-season awards races & storylines -- "trade rumor" feed. A few
    times a week, floats a plausible rumor that a struggling team is shopping
    a notable veteran with an expiring-ish deal, the same kind of speculation
    real NBA trade season runs on, to make the regular season feel alive
    beyond just game results scrolling by.
    """
    if random.random() > TRADE_RUMOR_CHANCE_PER_DAY:
        return
    if not trade_window_open():
        return
    candidates = []
    for team_name, cfg in SIM_STATE["teams"].items():
        if team_win_pct(team_name) >= 0.42:
            continue  # only real sellers generate rumors
        for p in team_roster(team_name):
            if p["rating"] >= 74 and p.get("contract") and p["contract"]["years_left"] <= 2 and not p.get("trade_request"):
                candidates.append((p, team_name))
    if not candidates:
        return
    p, team_name = random.choice(candidates)
    suitor = random.choice([t for t in NBA_TEAMS if t != team_name])
    flavor = random.choice([
        f"are fielding calls on {p['name']}", f"could be open to moving {p['name']} before the deadline",
        f"have made {p['name']} available in trade talks", f"are listening on offers for {p['name']}",
    ])
    push_news("📰", f"League sources: {team_name} {flavor}. {suitor} are said to be among the teams interested.", "trade_rumor")


def clear_trade_request(name):
    """Called on trade/waive/re-sign so a resolved player drops off the active list."""
    p = SIM_STATE["players"].get(name)
    if p:
        p["trade_request"] = None
        p["low_morale_streak"] = 0
    SIM_STATE["trade_requests"] = [r for r in SIM_STATE.get("trade_requests", []) if r["player"] != name]


def nudge_team_chemistry(team_name):
    """
    UPGRADE: Team chemistry now also factors in player personality traits.
    Leaders and Mentors pull chemistry up; Locker Room Cancers and Emotional
    players drag it down — matching how real NBA locker rooms work.
    """
    roster = team_roster(team_name)
    if not roster:
        return
    avg_morale = sum(p.get("morale", 70) for p in roster) / len(roster)
    continuity_score = sum(min(p.get("seasons_with_team", 0), 4) / 4.0 for p in roster) / len(roster) * 100.0
    # UPGRADE: personality trait chemistry bonuses/penalties
    personality_delta = 0
    for p in roster:
        trait = p.get("personality_trait", "Professional")
        trait_cfg = PERSONALITY_TRAITS.get(trait, {})
        personality_delta += trait_cfg.get("chemistry_bonus", 0)
    personality_modifier = personality_delta / max(1, len(roster))
    target = avg_morale * 0.50 + continuity_score * 0.40 + personality_modifier * 0.10
    current = SIM_STATE["teams"][team_name].get("chemistry", 65.0)
    SIM_STATE["teams"][team_name]["chemistry"] = round(clamp(current + (target - current) * 0.06, 0, 100), 1)


def disrupt_chemistry(team_name, amount=6.0):
    """Trades, cuts, and free-agent additions rattle locker-room continuity --
    called any time a roster changes outside of normal game-to-game flow."""
    t = SIM_STATE["teams"].get(team_name)
    if t:
        t["chemistry"] = round(clamp(t.get("chemistry", 65.0) - amount, 0, 100), 1)


def morale_label(morale):
    if morale >= 80:
        return "Happy"
    if morale >= 55:
        return "Content"
    if morale >= 35:
        return "Unhappy"
    return "Discontent"


def split_into_quarters(total):
    """Break a final team score into 4 plausible quarter scores that sum to it."""
    if total <= 0:
        return [0, 0, 0, 0]
    weights = [max(0.12, random.gauss(0.25, 0.045)) for _ in range(4)]
    wsum = sum(weights)
    quarters = []
    remaining = total
    for i in range(3):
        q = int(round(total * weights[i] / wsum))
        q = max(0, min(q, remaining))
        quarters.append(q)
        remaining -= q
    quarters.append(max(0, remaining))
    return quarters


def resolve_final_score_with_quarters(home_score, away_score):
    """
    Splits each team's final score into real quarters, and -- instead of the old
    hack of just nudging the home score up by 1-3 points on a tie -- plays out
    genuine 5-minute-style overtime periods (appended as extra periods) until
    someone actually wins.
    """
    home_quarters = split_into_quarters(home_score)
    away_quarters = split_into_quarters(away_score)
    ot_home, ot_away = [], []
    safety = 0
    while home_score == away_score and safety < 6:
        oh = random.randint(7, 15)
        oa = random.randint(7, 15)
        home_score += oh
        away_score += oa
        ot_home.append(oh)
        ot_away.append(oa)
        safety += 1
    if home_score == away_score:
        home_score += 1  # astronomically rare fallback, never leave a true tie on the board
    return home_score, away_score, home_quarters + ot_home, away_quarters + ot_away


def team_clutch_composite(team_name):
    """Minutes-weighted average of Clutch Factor + Consistency for a team's
    rotation -- used to swing close games late, same idea as 2K's late-game
    attribute checks (a team of stone-cold killers should win more coin-flip
    finishes than a team of streaky guys)."""
    roster = [p for p in SIM_STATE["players"].values() if p["team"] == team_name and not p["retired"] and effective_minutes(p) > 0]
    if not roster:
        return 70.0
    total_min = sum(effective_minutes(p) for p in roster)
    if total_min <= 0:
        return 70.0
    return sum(effective_minutes(p) * ((p["attributes"].get("Clutch Factor", 70) * 0.65 +
               p["attributes"].get("Consistency", 70) * 0.35)) for p in roster) / total_min


def apply_clutch_factor(home_team, away_team, home_score, away_score):
    """
    UPGRADE: close games now actually care about clutch attributes. Previously
    every point of the final score came purely from the whole-game statistical
    model with no regard for who a team actually wants the ball in crunch time.
    Now, when a game projects to finish within one score (8 points), each
    team's minutes-weighted Clutch Factor/Consistency composite nudges the
    final margin -- a team of proven closers edges a team of streaky scorers
    in the games that are actually close, without swinging blowouts at all.
    """
    margin = abs(home_score - away_score)
    if margin > 8:
        return home_score, away_score
    home_clutch = team_clutch_composite(home_team)
    away_clutch = team_clutch_composite(away_team)
    edge = (home_clutch - away_clutch) * 0.06   # up to roughly +/-3 pts at max attribute gap
    edge += random.gauss(0, 1.5)                # crunch time is still not deterministic
    swing = max(-4.0, min(4.0, edge))
    # UPGRADE: in-game coaching decisions -- a live "foul when trailing" call
    # adds extra late-game variance for whichever side is behind right now.
    swing = apply_ingame_strategy_to_clutch(home_team, home_score < away_score, swing)
    swing = -apply_ingame_strategy_to_clutch(away_team, away_score < home_score, -swing)
    home_score = max(0, int(round(home_score + swing / 2)))
    away_score = max(0, int(round(away_score - swing / 2)))
    return home_score, away_score


# UPGRADE: Team-vs-team head-to-head series history. Previously the only way
# to see how two franchises had done against each other was to manually dig
# through box scores -- this keeps a lightweight running ledger per team pair
# (all-time series record + a capped recent-meetings log) so a GM can pull up
# "how have we done against them" at a glance.
def record_h2h(home_team, away_team, home_score, away_score, is_playoff):
    key = "|".join(sorted([home_team, away_team]))
    ledger = SIM_STATE["h2h_history"].setdefault(key, {home_team if home_team < away_team else away_team: 0,
                                                         away_team if home_team < away_team else home_team: 0,
                                                         "games": []})
    team_lo, team_hi = sorted([home_team, away_team])
    ledger.setdefault(team_lo, 0)
    ledger.setdefault(team_hi, 0)
    winner = home_team if home_score > away_score else away_team
    ledger[winner] = ledger.get(winner, 0) + 1
    ledger["games"].append({
        "year": SIM_STATE["year"], "home": home_team, "away": away_team,
        "home_score": home_score, "away_score": away_score, "is_playoff": is_playoff,
    })
    # Cap the recent-games log so long saves don't grow this ledger unbounded --
    # the win/loss totals above stay exact and cumulative regardless.
    if len(ledger["games"]) > 60:
        ledger["games"] = ledger["games"][-60:]


def simulate_game(home_team, away_team, is_playoff=False):
    home_stats, home_score = sim_team_stats(home_team, opponent_name=away_team, is_home=True)
    away_stats, away_score = sim_team_stats(away_team, opponent_name=home_team, is_home=False)
    record_rivalry_meeting(home_team, away_team, is_playoff=is_playoff)  # UPGRADE: rivalries & narrative arcs

    home_score, away_score = apply_clutch_factor(home_team, away_team, home_score, away_score)
    home_score, away_score, home_quarters, away_quarters = resolve_final_score_with_quarters(home_score, away_score)
    record_h2h(home_team, away_team, home_score, away_score, is_playoff)
    record_rivalry_winner(home_team, home_score, away_team, away_score, is_playoff)

    winner_stats, loser_stats = (home_stats, away_stats) if home_score > away_score else (away_stats, home_stats)
    potg = pick_player_of_the_game(winner_stats, loser_stats)

    game_box = {
        "home_team": home_team, "away_team": away_team,
        "home_score": home_score, "away_score": away_score,
        "home_stats": home_stats, "away_stats": away_stats,
        "home_quarters": home_quarters, "away_quarters": away_quarters,
        "overtimes": max(0, len(home_quarters) - 4),
        "is_playoff": is_playoff,
        "potg": potg,
    }

    # Fatigue and morale apply every game (regular season AND playoffs) since
    # they're about the players' bodies/heads, not season box-score totals.
    update_fatigue_and_morale(home_team, home_stats)
    update_fatigue_and_morale(away_team, away_stats)
    update_form(home_team, home_stats)
    update_form(away_team, away_stats)
    check_milestones(home_team, home_stats, away_team, is_playoff, home_score > away_score)
    check_milestones(away_team, away_stats, home_team, is_playoff, away_score > home_score)

    if not is_playoff:
        for st_dict in [home_stats, away_stats]:
            for p_name, st in st_dict.items():
                p = SIM_STATE["players"][p_name]
                for key in ["FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "PTS", "REB", "AST", "STL", "BLK", "TOV"]:
                    p["stats"][key] += st[key]
                p["stats"]["GP"] += 1
                p["stats"]["MIN"] += effective_minutes(p)
                # UPGRADE BATCH 3: career highs + triple-double tracker, fed
                # straight off this game's individual box line.
                record_game_box_for_trackers(p_name, st)
        maybe_injure_players(home_stats)
        maybe_injure_players(away_stats)

    return game_box


SHOT_FLAVOR_2PT = ["drives and finishes at the rim", "buries the mid-range jumper", "throws it down on the fast break",
                    "banks it in off the glass", "spins in the post and scores", "gets to the free throw line and converts"]
SHOT_FLAVOR_3PT = ["nails a three from the corner", "pulls up from downtown", "catches and fires from deep",
                    "buries a stepback three", "drills it off the pick and roll"]
FLAVOR_EVENTS = ["grabs the defensive rebound", "comes up with the steal", "rejects the shot at the rim",
                 "dishes a slick assist", "battles for the offensive board", "draws the charge"]


def _weighted_player(pool):
    if not pool:
        return None
    weights = [max(1.0, p["rating"]) * max(1, effective_minutes(p)) for p in pool]
    return random.choices(pool, weights=weights, k=1)[0]


def build_play_by_play(home_team, away_team, box):
    """
    UPGRADE: "Jump Into Game" live mode. Builds a readable, quarter-by-quarter
    play-by-play trace for a game whose final box score has already been
    simulated -- so the live viewer's running score always lands exactly on
    the real result, while still feeling like a broadcast instead of a
    silent box score. Each quarter's scoring plays are paced out against a
    countdown clock and weighted toward each team's best/most-used players.
    """
    home_players = [p for p in team_roster(home_team) if effective_minutes(p) > 0] or team_roster(home_team)
    away_players = [p for p in team_roster(away_team) if effective_minutes(p) > 0] or team_roster(away_team)
    home_q, away_q = box["home_quarters"], box["away_quarters"]
    events = []
    period_names = ["1st Quarter", "2nd Quarter", "3rd Quarter", "4th Quarter"] + \
        [f"Overtime {i+1}" for i in range(max(0, len(home_q) - 4))]

    run_home, run_away = 0, 0
    for qi in range(len(home_q)):
        period_len = 720 if qi < 4 else 300
        clock = period_len
        target_home, target_away = home_q[qi], away_q[qi]
        made_home = made_away = 0
        events.append({"period": period_names[qi], "clock": "12:00" if qi < 4 else "5:00",
                        "team": None, "text": f"— {period_names[qi]} tips off —",
                        "home_score": run_home, "away_score": run_away, "type": "period"})
        while made_home < target_home or made_away < target_away:
            remaining_h, remaining_a = target_home - made_home, target_away - made_away
            side = "home" if (remaining_h > 0 and (remaining_a <= 0 or random.random() < remaining_h / max(1, remaining_h + remaining_a))) else "away"
            pool = home_players if side == "home" else away_players
            remaining = remaining_h if side == "home" else remaining_a
            player = _weighted_player(pool)
            if player is None or remaining <= 0:
                break
            if remaining == 1:
                pts, flavor = 1, "sinks a free throw"
            elif remaining >= 3 and random.random() < 0.32:
                pts, flavor = 3, random.choice(SHOT_FLAVOR_3PT)
            else:
                pts, flavor = 2, random.choice(SHOT_FLAVOR_2PT)
            if side == "home":
                made_home += pts
                run_home += pts
            else:
                made_away += pts
                run_away += pts
            clock = max(0, clock - random.randint(9, 34))
            mins, secs = divmod(clock, 60)
            shot_clock = random.randint(1, 24)
            team_name = home_team if side == "home" else away_team
            beat_buzzer = " Beats the shot clock buzzer!" if shot_clock <= 2 else ""
            is_crunch = qi >= 3 and clock <= 120 and abs(run_home - run_away) <= 6
            events.append({"period": period_names[qi], "clock": f"{mins}:{secs:02d}", "team": side,
                            "shot_clock": shot_clock, "crunch": is_crunch,
                            "text": f"{player['name']} ({team_name}) {flavor} (+{pts}).{beat_buzzer}",
                            "home_score": run_home, "away_score": run_away, "type": "score"})
            if random.random() < 0.22:
                flavor_side = random.choice(["home", "away"])
                flavor_pool = home_players if flavor_side == "home" else away_players
                fplayer = _weighted_player(flavor_pool)
                if fplayer:
                    clock = max(0, clock - random.randint(3, 12))
                    mins2, secs2 = divmod(clock, 60)
                    events.append({"period": period_names[qi], "clock": f"{mins2}:{secs2:02d}", "team": flavor_side,
                                   "text": f"{fplayer['name']} {random.choice(FLAVOR_EVENTS)}.",
                                   "home_score": run_home, "away_score": run_away, "type": "flavor"})
        events.append({"period": period_names[qi], "clock": "0:00", "team": None,
                        "text": f"— End of {period_names[qi]}: {home_team} {run_home}, {away_team} {run_away} —",
                        "home_score": run_home, "away_score": run_away, "type": "period"})

    winner = home_team if box["home_score"] > box["away_score"] else away_team
    events.append({"period": "Final", "clock": "0:00", "team": None,
                    "text": f"🏁 FINAL: {home_team} {box['home_score']} — {away_team} {box['away_score']}. "
                            f"{winner} win it!" + (f" Player of the Game: {box['potg']}." if box.get("potg") else ""),
                    "home_score": box["home_score"], "away_score": box["away_score"], "type": "final"})
    return events


def tick_injuries():
    for p in SIM_STATE["players"].values():
        if p.get("injury"):
            p["injury"]["games_remaining"] -= 1
            if p["injury"]["games_remaining"] <= 0:
                p["injury"] = None
                # UPGRADE: re-injury risk window opens the moment a player
                # returns -- see maybe_injure_players / REINJURY_WINDOW_GAMES.
                p["reinjury_window"] = REINJURY_WINDOW_GAMES
        elif p.get("reinjury_window", 0) > 0:
            p["reinjury_window"] -= 1


AWARD_QUALIFY_GP = 41   # min games played to be eligible for MVP/DPOY/Scoring/MIP (half a season)
ROY_QUALIFY_GP = 20     # rookies see fewer minutes, so a lower bar applies


def generate_awards():
    if SIM_STATE.get("awards") and SIM_STATE["awards"].get("MVP") is not None:
        return
    all_active = [p for p in SIM_STATE["players"].values() if p["stats"]["GP"] > 0 and not p["retired"]]
    if not all_active:
        return

    # Award-eligible pool requires a real games-played qualifier so a 3-game hot
    # streak (or a single garbage-time appearance) can't accidentally win a title.
    qualified = [p for p in all_active if p["stats"]["GP"] >= AWARD_QUALIFY_GP]
    if not qualified:
        qualified = all_active  # fallback for a shortened/early sim

    qualified.sort(key=lambda x: (x["stats"]["PTS"] / x["stats"]["GP"]) + (SIM_STATE["teams"][x["team"]]["wins"] * 0.4), reverse=True)
    mvp = qualified[0]

    qualified.sort(key=lambda x: (x["stats"]["REB"] / x["stats"]["GP"]) + (x["stats"]["BLK"] / x["stats"]["GP"]), reverse=True)
    dpoy = qualified[0]

    qualified.sort(key=lambda x: (x["stats"]["PTS"] / x["stats"]["GP"]), reverse=True)
    scoring = qualified[0]

    # Guard against age <= 23 in addition to draft_year matching the current
    # year -- draft_year alone isn't a safe rookie signal for every player
    # source in this sim (e.g. undrafted free-agent pools can share a
    # draft_year with the current season by coincidence), and ROY should
    # never realistically go to anyone outside a normal rookie age band.
    rookies = [p for p in all_active
               if p["draft_year"] == SIM_STATE["year"] and p["stats"]["GP"] >= ROY_QUALIFY_GP
               and p.get("age", 22) <= 23]
    roy = None
    if rookies:
        rookies.sort(key=lambda x: (x["stats"]["PTS"] / x["stats"]["GP"]), reverse=True)
        roy = rookies[0]

    # Most Improved Player: only real, qualified improvement counts -- a player who
    # simply declined less than everyone else should NOT win with a negative delta.
    improved = []
    for p in qualified:
        if p["history"]:
            prev = p["history"][-1]["PPG"]
            cur = p["stats"]["PTS"] / p["stats"]["GP"]
            delta = cur - prev
            if delta > 0:
                improved.append((p, delta))
    mip, mip_delta = (None, None)
    if improved:
        improved.sort(key=lambda x: x[1], reverse=True)
        mip, mip_delta = improved[0]

    SIM_STATE["awards"].update({
        "MVP": {"name": mvp["name"], "team": mvp["team"], "stat": f"{round(mvp['stats']['PTS']/mvp['stats']['GP'], 1)} PPG"},
        "DPOY": {"name": dpoy["name"], "team": dpoy["team"], "stat": f"{round(dpoy['stats']['REB']/dpoy['stats']['GP'], 1)} RPG"},
        "Scoring_Champ": {"name": scoring["name"], "team": scoring["team"], "stat": f"{round(scoring['stats']['PTS']/scoring['stats']['GP'], 1)} PPG"},
    })
    if roy:
        SIM_STATE["awards"]["ROY"] = {"name": roy["name"], "team": roy["team"], "stat": f"{round(roy['stats']['PTS']/roy['stats']['GP'], 1)} PPG"}
    if mip:
        SIM_STATE["awards"]["MIP"] = {"name": mip["name"], "team": mip["team"], "stat": f"+{round(mip_delta, 1)} PPG"}
    # If nobody posted a genuine positive improvement, MIP simply stays None/unawarded that season.

    for p in all_active:
        ppg = round(p["stats"]["PTS"] / p["stats"]["GP"], 1)
        rpg = round(p["stats"]["REB"] / p["stats"]["GP"], 1)
        apg = round(p["stats"]["AST"] / p["stats"]["GP"], 1)
        p["history"].append({"year": SIM_STATE["year"], "PPG": ppg, "RPG": rpg, "APG": apg})

    # --- All-NBA Teams (positionless top 15) and All-Star rosters (12/conference) ---
    def composite_score(pl):
        gp = pl["stats"]["GP"]
        ppg = pl["stats"]["PTS"] / gp
        rpg = pl["stats"]["REB"] / gp
        apg = pl["stats"]["AST"] / gp
        spg = pl["stats"]["STL"] / gp
        bpg = pl["stats"]["BLK"] / gp
        wp = team_win_pct(pl["team"])
        return ppg + rpg * 0.8 + apg * 0.9 + spg * 2.0 + bpg * 2.0 + wp * 6.0

    ranked_all = sorted(qualified, key=composite_score, reverse=True)

    def as_award_entry(pl):
        return {"name": pl["name"], "team": pl["team"], "position": pl["position"],
                "stat": f"{round(pl['stats']['PTS']/pl['stats']['GP'],1)}/{round(pl['stats']['REB']/pl['stats']['GP'],1)}/{round(pl['stats']['AST']/pl['stats']['GP'],1)}"}

    top15 = ranked_all[:15]
    SIM_STATE["awards"]["All_NBA"] = {
        "First": [as_award_entry(p) for p in top15[0:5]],
        "Second": [as_award_entry(p) for p in top15[5:10]],
        "Third": [as_award_entry(p) for p in top15[10:15]],
    }

    east_pool = sorted([p for p in ranked_all if TEAM_CONFERENCE.get(p["team"]) == "East"], key=composite_score, reverse=True)[:12]
    west_pool = sorted([p for p in ranked_all if TEAM_CONFERENCE.get(p["team"]) == "West"], key=composite_score, reverse=True)[:12]
    SIM_STATE["awards"]["All_Stars"] = {
        "East": [as_award_entry(p) for p in east_pool],
        "West": [as_award_entry(p) for p in west_pool],
    }

    # --- UPGRADE: Sixth Man of the Year -- best real bench scorer, i.e. someone
    # who plays a genuine bench role (per-game minutes below a starter's workload)
    # rather than the outright leader in scoring who's obviously starting.
    sixth_man = None
    bench_pool = [p for p in qualified if p["stats"]["GP"] > 0 and (p["stats"]["MIN"] / p["stats"]["GP"]) <= 28]
    if bench_pool:
        bench_pool.sort(key=lambda x: x["stats"]["PTS"] / x["stats"]["GP"], reverse=True)
        sixth_man = bench_pool[0]
        SIM_STATE["awards"]["Sixth_Man"] = {"name": sixth_man["name"], "team": sixth_man["team"],
                                             "stat": f"{round(sixth_man['stats']['PTS']/sixth_man['stats']['GP'], 1)} PPG (Bench)"}

    # --- UPGRADE: All-Defensive First/Second Team -- a genuine defensive
    # composite (steals, blocks, defensive attributes, and winning) instead of
    # just reusing the offensive All-NBA ranking with a different label.
    def defensive_composite(pl):
        gp = pl["stats"]["GP"]
        spg = pl["stats"]["STL"] / gp
        bpg = pl["stats"]["BLK"] / gp
        rpg = pl["stats"]["REB"] / gp
        interior = pl["attributes"].get("Interior Defense", 70)
        perimeter = pl["attributes"].get("Perimeter Defense", 70)
        lateral = pl["attributes"].get("Lateral Quickness", 70)
        return spg * 2.2 + bpg * 2.2 + rpg * 0.3 + (interior + perimeter + lateral - 210) * 0.05 + team_win_pct(pl["team"]) * 2.5

    def_ranked = sorted(qualified, key=defensive_composite, reverse=True)[:10]
    SIM_STATE["awards"]["All_Defensive"] = {
        "First": [as_award_entry(p) for p in def_ranked[0:5]],
        "Second": [as_award_entry(p) for p in def_ranked[5:10]],
    }

    # --- UPGRADE: All-Rookie First/Second Team -- same composite-score idea as
    # All-NBA, but restricted to this year's draft class.
    rookie_pool = [p for p in all_active if p["draft_year"] == SIM_STATE["year"] and p["stats"]["GP"] > 0]
    rookie_ranked = sorted(rookie_pool, key=composite_score, reverse=True)[:10]
    if rookie_ranked:
        SIM_STATE["awards"]["All_Rookie"] = {
            "First": [as_award_entry(p) for p in rookie_ranked[0:5]],
            "Second": [as_award_entry(p) for p in rookie_ranked[5:10]],
        }

    # --- Stamp every real season award onto the winning player's own record so
    # it survives into their Career tab (previously awards only lived at the
    # league level in SIM_STATE["awards"], with no memory of who won what in
    # past seasons once a new MVP/DPOY/etc. was crowned the following year).
    def _log_award(pl, award_name):
        pl.setdefault("career_awards", []).append({"year": SIM_STATE["year"], "award": award_name})
        # UPGRADE: Player timeline — log milestone events for the career timeline card
        timeline_icons = {"MVP": "🏆", "All-Star": "⭐", "DPOY": "🛡", "ROY": "🌟",
                          "Scoring Champion": "🔥", "NBA Champion": "💍", "Finals MVP": "🏆"}
        icon = timeline_icons.get(award_name, "🎖")
        pl.setdefault("timeline", []).append({"year": SIM_STATE["year"], "event": award_name, "icon": icon})

    _log_award(mvp, "MVP")
    _log_award(dpoy, "DPOY")
    _log_award(scoring, "Scoring Champion")
    if roy:
        _log_award(roy, "Rookie of the Year")
    if mip:
        _log_award(mip, "Most Improved Player")
    for pl in top15[0:5]:
        _log_award(pl, "All-NBA First Team")
    for pl in top15[5:10]:
        _log_award(pl, "All-NBA Second Team")
    for pl in top15[10:15]:
        _log_award(pl, "All-NBA Third Team")
    for pl in east_pool + west_pool:
        _log_award(pl, "All-Star")
    if sixth_man:
        _log_award(sixth_man, "Sixth Man of the Year")
    for pl in def_ranked[0:5]:
        _log_award(pl, "All-Defensive First Team")
    for pl in def_ranked[5:10]:
        _log_award(pl, "All-Defensive Second Team")
    for pl in rookie_ranked[0:5]:
        _log_award(pl, "All-Rookie First Team")
    for pl in rookie_ranked[5:10]:
        _log_award(pl, "All-Rookie Second Team")


def compute_finals_mvp():
    finals = SIM_STATE["playoff_bracket"].get("4", [])
    if not finals or finals[0]["winner"] is None:
        return None
    series = finals[0]
    champion = series["winner"]
    scores = {}
    for g in series["games"]:
        for side_stats in [g["home_stats"], g["away_stats"]]:
            for name, st in side_stats.items():
                weighted = st["PTS"] + st["REB"] * 1.1 + st["AST"] * 1.4 + st["STL"] * 1.5 + st["BLK"] * 1.5
                scores[name] = scores.get(name, 0) + weighted
    if not scores:
        return None
    # Prefer someone on the championship roster when scores are close
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_name, best_score = ranked[0]
    for name, sc in ranked[:3]:
        p = SIM_STATE["players"].get(name)
        if p and p["team"] == champion:
            best_name, best_score = name, sc
            break
    games_played = len(series["games"])
    avg = round(best_score / max(1, games_played), 1)
    p = SIM_STATE["players"].get(best_name)
    return {"name": best_name, "team": p["team"] if p else champion, "stat": f"{avg} Finals Impact Score/gm"}


def record_league_history():
    finals = SIM_STATE["playoff_bracket"].get("4", [])
    champion = finals[0]["winner"] if finals and finals[0]["winner"] else None
    finals_mvp = compute_finals_mvp()
    if finals_mvp and SIM_STATE.get("awards") is not None:
        SIM_STATE["awards"]["Finals_MVP"] = finals_mvp
    roy = SIM_STATE["awards"].get("ROY") if SIM_STATE.get("awards") else None

    if finals_mvp:
        fmvp_player = SIM_STATE["players"].get(finals_mvp["name"])
        if fmvp_player:
            fmvp_player.setdefault("career_awards", []).append({"year": SIM_STATE["year"], "award": "Finals MVP"})
    if champion:
        for p in team_roster(champion):
            p.setdefault("career_awards", []).append({"year": SIM_STATE["year"], "award": "NBA Champion"})

    entry = {
        "year": SIM_STATE["year"],
        "champion": champion,
        "finals_mvp": finals_mvp["name"] if finals_mvp else None,
        "finals_mvp_stat": finals_mvp["stat"] if finals_mvp else None,
        "roy": roy["name"] if roy else None,
        "mvp": SIM_STATE["awards"]["MVP"]["name"] if SIM_STATE.get("awards") and SIM_STATE["awards"].get("MVP") else None,
        # Full-league standings snapshot so each franchise's Team Tracker page
        # can show its own season-by-season record across years, not just the
        # current live season.
        "standings": {
            t: {"wins": SIM_STATE["teams"][t]["wins"], "losses": SIM_STATE["teams"][t]["losses"]}
            for t in NBA_TEAMS
        },
    }
    SIM_STATE["history"].append(entry)
    record_coach_career_season(champion)
    entry["highlight_reel"] = generate_highlight_reel(champion, finals_mvp)
    # Fan approval boost for the winning city; slight dip for the runner-up
    if champion:
        update_fan_approval(champion, 15, "championship")
        trigger_press_conference("title")
    if finals and len(finals) > 0:
        runner_up = next((t for t in (finals[0].get("teams") or []) if t != champion), None)
        if runner_up:
            update_fan_approval(runner_up, -5, "finals loss")
    # Book attendance revenue for every team before the season resets
    for t in NBA_TEAMS:
        compute_attendance_revenue(t)
    # UPGRADE: GM legacy score
    # UPGRADE: Trophy room — archive every championship permanently
    if champion:
        _awards = SIM_STATE.get("awards") or {}
        mvp_name = _awards.get("MVP", {}).get("name")
        finals_mvp_data = compute_finals_mvp() if SIM_STATE.get("playoff_bracket") else None
        SIM_STATE.setdefault("trophy_room", []).append({
            "year": SIM_STATE["year"], "champion": champion,
            "coach": SIM_STATE.get("coaches", {}).get(champion, {}).get("name"),
            "finals_mvp": finals_mvp_data["name"] if finals_mvp_data else None,
            "mvp": mvp_name,
            "wins": SIM_STATE["teams"].get(champion, {}).get("wins", 0),
        })

    for t in NBA_TEAMS:
        wins = SIM_STATE["teams"][t]["wins"]
        streak = SIM_STATE["teams"][t].get("streak", 0)
        rec = SIM_STATE.setdefault("team_records", {}).setdefault(t, {
            "most_wins": 0, "longest_win_streak": 0, "championships": 0, "best_season_year": None
        })
        if wins > rec["most_wins"]:
            rec["most_wins"] = wins
            rec["best_season_year"] = SIM_STATE["year"]
        if abs(streak) > rec["longest_win_streak"]:
            rec["longest_win_streak"] = abs(streak)
        if t == champion:
            rec["championships"] = rec.get("championships", 0) + 1

    _update_franchise_goat(champion)

    compute_legacy_score(champion)


def _update_franchise_goat(champion):
    """Update each team's GOAT across seasons — highest peak-rated player
    who spent meaningful time there, plus the best coach and best season."""
    for team_name in NBA_TEAMS:
        roster = [p for p in SIM_STATE["players"].values()
                  if p.get("team") == team_name and not p.get("retired")]
        if not roster:
            continue
        best_player = max(roster, key=lambda p: p.get("career_totals", {}).get("PEAK_RATING", p["rating"]))
        goat = SIM_STATE.setdefault("franchise_goat", {}).setdefault(team_name, {})
        peak = best_player.get("career_totals", {}).get("PEAK_RATING", best_player["rating"])
        if peak > goat.get("player_rating", 0):
            goat["player"] = best_player["name"]
            goat["player_rating"] = peak
            goat["player_pos"] = best_player["position"]
        coach = SIM_STATE.get("coaches", {}).get(team_name, {})
        if coach:
            coach_career = SIM_STATE.get("coach_career", {}).get(coach["name"], {})
            coach_wins = coach_career.get("total_wins", 0)
            if coach_wins > goat.get("coach_wins", 0):
                goat["coach"] = coach["name"]
                goat["coach_wins"] = coach_wins
                goat["coach_system"] = coach.get("system")
        wins = SIM_STATE["teams"][team_name]["wins"]
        if wins > goat.get("best_season_wins", 0):
            goat["best_season_wins"] = wins
            goat["best_season_year"] = SIM_STATE["year"]
        if team_name == champion:
            goat["championships"] = goat.get("championships", 0) + 1


def compute_legacy_score(champion):
    """
    Accumulates a career legacy score for the human GM across seasons.
    Points awarded for: championships, win total, playoff appearances,
    draft hits (high-value players drafted and developed), and trades
    that improved the franchise. Logged per season so the history tab
    can show a season-by-season breakdown.
    """
    user_team = SIM_STATE["user_team"]
    year = SIM_STATE["year"]
    wins = SIM_STATE["teams"][user_team]["wins"]
    season_pts = 0
    events = []

    # Championship
    if champion == user_team:
        season_pts += 500
        events.append("🏆 Championship (+500)")

    # Playoff appearance (bracket exists and user team made it)
    bracket = SIM_STATE.get("playoff_bracket", {})
    all_playoff_teams = set()
    for rd_data in bracket.values():
        for series in rd_data:
            all_playoff_teams.update(series.get("teams", []))
    if user_team in all_playoff_teams:
        season_pts += 100
        events.append("🏅 Playoff appearance (+100)")

    # Win bonus: every win above .500 is worth 3 pts
    win_bonus = max(0, wins - 41) * 3
    if win_bonus:
        season_pts += win_bonus
        events.append(f"📈 {wins} wins (+{win_bonus})")

    # Fan approval tier bonus
    fa = SIM_STATE.get("fan_approval", {}).get(user_team, 55)
    if fa >= 80:
        season_pts += 50
        events.append(f"❤️ Fan approval {fa}% (+50)")
    elif fa >= 65:
        season_pts += 20
        events.append(f"❤️ Fan approval {fa}% (+20)")

    # Award-winning player developed by this team
    awards = SIM_STATE.get("awards") or {}
    for award_key in ("MVP", "ROY", "DPOY", "MIP"):
        aw = awards.get(award_key)
        if aw and SIM_STATE["players"].get(aw.get("name"), {}).get("team") == user_team:
            season_pts += 80
            events.append(f"🏅 {award_key}: {aw['name']} (+80)")

    SIM_STATE["legacy_score"] = SIM_STATE.get("legacy_score", 0) + season_pts
    SIM_STATE.setdefault("legacy_log", []).append({
        "year": year, "pts": season_pts, "total": SIM_STATE["legacy_score"], "events": events
    })


def generate_highlight_reel(champion, finals_mvp):
    """Build a compact top-5 text recap of the season's most memorable moments."""
    highlights = []
    awards = SIM_STATE.get("awards", {}) or {}
    year = SIM_STATE["year"]

    # MVP
    # BUGFIX: this read mvp['ppg']/['rpg']/['apg'], but SIM_STATE["awards"]
    # entries only ever have name/team/stat (a single combined string like
    # "23.2 PPG") -- those keys never existed, so this has always thrown a
    # hard KeyError and crashed the whole finals-conclusion flow with a 500
    # every single time a champion was crowned. Look up the real player's
    # actual season stat line instead of assuming fields that were never
    # there.
    mvp = awards.get("MVP")
    if mvp:
        mvp_player = SIM_STATE["players"].get(mvp["name"])
        mvp_gp = max(1, (mvp_player or {}).get("stats", {}).get("GP", 1))
        mvp_ppg = round((mvp_player or {}).get("stats", {}).get("PTS", 0) / mvp_gp, 1) if mvp_player else mvp.get("stat", "")
        mvp_rpg = round((mvp_player or {}).get("stats", {}).get("REB", 0) / mvp_gp, 1) if mvp_player else ""
        mvp_apg = round((mvp_player or {}).get("stats", {}).get("AST", 0) / mvp_gp, 1) if mvp_player else ""
        if mvp_player:
            highlights.append(f"🏅 {mvp['name']} wins MVP ({mvp_ppg} PPG / {mvp_rpg} RPG / {mvp_apg} APG)")
        else:
            highlights.append(f"🏅 {mvp['name']} wins MVP ({mvp.get('stat', '')})")

    # Scoring champion
    sc = awards.get("Scoring_Champ")
    if sc:
        highlights.append(f"🔥 Scoring title goes to {sc['name']} with {sc.get('stat', '')}")

    # ROY
    roy = awards.get("ROY")
    if roy:
        highlights.append(f"🌟 Rookie of the Year: {roy['name']}")

    # Finals MVP & champion
    if champion:
        if finals_mvp:
            highlights.append(f"🏆 {champion} win the championship! Finals MVP: {finals_mvp['name']}")
        else:
            highlights.append(f"🏆 {champion} are your {year} champions!")

    # Any player who hit a big personal milestone this season
    for p in SIM_STATE["players"].values():
        gp = p.get("stats", {}).get("GP", 0)
        if gp < 20:
            continue
        ppg = round(p["stats"].get("PTS", 0) / max(1, gp), 1)
        if ppg >= 35:
            highlights.append(f"💥 {p['name']} drops {ppg} PPG — historic scoring season")
            break

    # Trade block standout  — most expensive trade of the year
    tlog = SIM_STATE.get("trade_log", [])
    season_trades = [t for t in tlog if t.get("year") == year]
    if season_trades:
        highlights.append(f"🔁 {len(season_trades)} trades completed this season, reshaping the league")

    return highlights[:5]


# UPGRADE: Clickable coach profiles. Coaches previously had no persistent
# identity outside a single team's "years_with_team" counter -- firing or
# switching teams silently reset their whole track record. This rolls each
# coach's season (per team they're currently on staff for) into a
# league-wide career ledger keyed by coach name, so a GM can click any
# coach's name the same way they click a player's and see a real resume:
# career W-L, championships won, seasons coached, and every team they've
# been on staff for.
def record_coach_career_season(champion):
    for team_name, coach in SIM_STATE.get("coaches", {}).items():
        if not coach:
            continue
        team_cfg = SIM_STATE["teams"].get(team_name, {})
        wins = team_cfg.get("wins", 0)
        losses = team_cfg.get("losses", 0)
        career = SIM_STATE["coach_career"].setdefault(coach["name"], {
            "system": coach.get("system"),
            "seasons": [],
            "total_wins": 0,
            "total_losses": 0,
            "championships": 0,
            "teams_coached": [],
        })
        career["system"] = coach.get("system", career.get("system"))
        career["seasons"].append({
            "year": SIM_STATE["year"],
            "team": team_name,
            "wins": wins,
            "losses": losses,
            "champion": team_name == champion,
        })
        career["total_wins"] += wins
        career["total_losses"] += losses
        if team_name == champion:
            career["championships"] += 1
        if team_name not in career["teams_coached"]:
            career["teams_coached"].append(team_name)


# ==========================================
# TRADE SYSTEM (multi-player + future picks)
# ==========================================
def player_value(p):
    # UPGRADE PASS (trade realism fix): value used to scale linearly with
    # rating (base = p["rating"]), which meant an elite 89 OVR player and a
    # replacement-level 62 OVR player were only ~1.4x apart in trade value --
    # confirmed live: shopping an 89 OVR player returned 62 OVR players as
    # a "fair" offer. Real trade value is convex, not linear -- stars are
    # worth dramatically more than the raw rating gap suggests. Anchored at
    # rating 70 (an average rotation player) so calibration everywhere else
    # that assumes "value roughly equals rating" for a mid-tier player is
    # undisturbed; value pulls away exponentially above/below that anchor.
    rating_gap = p["rating"] - 70
    base_rating_value = 70 * (1.045 ** rating_gap)
    age_factor = 1.0
    if p["age"] <= 23:
        age_factor = 1.20
    elif p["age"] <= 27:
        age_factor = 1.05
    elif p["age"] >= 34:
        age_factor = 0.65
    elif p["age"] >= 31:
        age_factor = 0.85
    pot_factor = 1 + max(0, (p["potential"] - p["rating"])) / 200.0
    injury_pen = 0.85 if (p.get("injury") and p["injury"].get("games_remaining", 0) > 3) else 1.0
    morale = p.get("morale", 70)
    morale_factor = 0.90 + (morale / 100.0) * 0.20  # discontented stars are worth less on the trade market
    return round(base_rating_value * age_factor * pot_factor * injury_pen * morale_factor, 1)


def calculate_pick_value(years_out, team_win_loss_record):
    """
    Standalone pick-decay formula: value drops the further out the pick is (future
    uncertainty), and scales inversely with how good the originating team's live
    record currently is -- a pick owed by a bad team is worth more than one owed by
    a contender, since it's more likely to land early in the draft order.
    `team_win_loss_record` is that team's current win percentage (0.0 - 1.0).
    Returns a base 1st-round-equivalent value; multiply by round weight separately.
    """
    decay = max(0.55, 1 - years_out * 0.08)
    quality_mult = 1 + (0.5 - team_win_loss_record) * 0.6
    return round(decay * quality_mult, 4)


PROTECTION_VALUE_DISCOUNT = {"None": 1.0, "Top-4 Protected": 0.80, "Top-10 Protected": 0.65, "Lottery Protected": 0.50}


def pick_value(pick):
    years_out = max(0, pick["year"] - SIM_STATE["year"])
    base = 42 if pick["round"] == 1 else 14
    team_rec = SIM_STATE["teams"].get(pick["original_team"])
    win_pct = team_win_pct(pick["original_team"]) if team_rec else 0.5
    multiplier = calculate_pick_value(years_out, win_pct)
    protection = pick.get("protection", "None")
    discount = PROTECTION_VALUE_DISCOUNT.get(protection, 1.0)
    return round(base * multiplier * discount, 1)


def trade_window_open():
    """Trades lock at the deadline during the regular season, same as the real
    NBA -- but re-open again once the season ends (offseason/draft/free agency
    all allow wheeling and dealing right up until tip-off of the next year)."""
    if SIM_STATE["stage"] != "regular_season":
        return True
    deadline = SIM_STATE.get("trade_deadline_day")
    if deadline is None:
        return True
    return SIM_STATE["current_day"] <= deadline


def team_win_pct(team_name):
    t = SIM_STATE["teams"].get(team_name)
    if not t or (t["wins"] + t["losses"]) == 0:
        return 0.5
    return t["wins"] / (t["wins"] + t["losses"])


def team_context(team_name):
    """Classify a team's current team-building mindset based on record."""
    wp = team_win_pct(team_name)
    if wp > 0.600:
        return "Contender"
    if wp < 0.400:
        return "Rebuilder"
    return "Balanced"


# UPGRADE: Owner mandates / hot seat. A controlling owner sets a budget
# ceiling and a win expectation at the start of each season based on how
# good the roster actually is -- miss badly enough (on wins or budget) too
# many times and the GM (the user) gets fired, sent back to the team-picker
# to find a new job elsewhere while their old team keeps running under AI
# control. Mandate strength is judged off roster talent (average rating)
# rather than the win% that's about to reset to 0-0 for the new season.
def team_strength_tier(team_name):
    roster = team_roster(team_name)
    if not roster:
        return "Balanced"
    avg = sum(p["rating"] for p in roster) / len(roster)
    if avg >= 76:
        return "Contender"
    if avg <= 68:
        return "Rebuilder"
    return "Balanced"


def generate_owner_mandate(team_name):
    tier = team_strength_tier(team_name)
    if tier == "Contender":
        min_wins = random.randint(48, 54)
        budget_ceiling = round(SALARY_CAP + TAX_APRON_ROOM * random.uniform(0.8, 1.0), 1)
        label = "Win a championship" if random.random() < 0.4 else "Make a deep playoff run"
    elif tier == "Rebuilder":
        min_wins = random.randint(20, 30)
        budget_ceiling = round(SALARY_CAP * random.uniform(0.80, 0.92), 1)
        label = "Develop young talent -- wins are secondary"
    else:
        min_wins = random.randint(38, 44)
        budget_ceiling = round(SALARY_CAP * random.uniform(0.95, 1.05), 1)
        label = "Make the playoffs"
    return {"min_wins": min_wins, "budget_ceiling": budget_ceiling,
            "expectation_label": label, "season_year": SIM_STATE["year"]}


def evaluate_owner_mandate():
    """Grades the season just finished against the mandate set at its start
    (called from start_new_season, BEFORE wins/losses reset), then rolls a
    fresh mandate for the upcoming season."""
    user_team = SIM_STATE["user_team"]
    mandate = SIM_STATE.get("owner_mandate")
    hot_seat = SIM_STATE.setdefault("hot_seat", {"warnings": 0, "fired": False, "fired_from": None})
    if mandate and not hot_seat.get("fired"):
        actual_wins = SIM_STATE["teams"][user_team]["wins"]
        actual_losses = SIM_STATE["teams"][user_team]["losses"]
        season_salary = team_total_salary(user_team)
        missed_wins = actual_wins < mandate["min_wins"] - 4   # small grace window
        blew_budget = season_salary > mandate["budget_ceiling"] + 3.0
        if missed_wins or blew_budget:
            hot_seat["warnings"] = hot_seat.get("warnings", 0) + 1
            reasons = []
            if missed_wins:
                reasons.append(f"finished {actual_wins}-{actual_losses} against a {mandate['min_wins']}-win expectation")
            if blew_budget:
                reasons.append(f"payroll hit ${season_salary}M against a ${mandate['budget_ceiling']}M ceiling")
            push_news("🔥", f"Ownership is unhappy: {' and '.join(reasons)}. Hot seat warning {hot_seat['warnings']}/3.", "general")
            if hot_seat["warnings"] >= 3:
                hot_seat["fired"] = True
                hot_seat["fired_from"] = user_team
                push_news("🚪", f"{display_name(user_team)} have fired their General Manager after repeatedly missing ownership's expectations.", "general")
        elif hot_seat.get("warnings", 0) > 0:
            push_news("✅", "Ownership is pleased with the direction of the franchise — hot seat warnings cleared.", "general")
            hot_seat["warnings"] = 0

    if not hot_seat.get("fired"):
        SIM_STATE["owner_mandate"] = generate_owner_mandate(user_team)
    # Fan approval swings on mandate outcomes too
    if mandate:
        actual_wins = SIM_STATE["teams"][user_team]["wins"]
        swing = 8 if actual_wins >= mandate["min_wins"] else -10
        update_fan_approval(user_team, swing, reason="mandate result")


# ───────────────────── FAN APPROVAL / ATTENDANCE ECONOMICS ─────────────────────
MARKET_SIZE = {}   # populated lazily on first call


def get_market_size(team_name):
    global MARKET_SIZE
    if not MARKET_SIZE:
        large = NBA_TEAMS[:8]
        small = NBA_TEAMS[-8:]
        for t in NBA_TEAMS:
            MARKET_SIZE[t] = "large" if t in large else ("small" if t in small else "medium")
    return MARKET_SIZE.get(team_name, "medium")


def update_fan_approval(team_name, delta, reason=""):
    fa = SIM_STATE.setdefault("fan_approval", {})
    current = fa.get(team_name, 55)
    fa[team_name] = round(max(10, min(99, current + delta)), 1)


def compute_attendance_revenue(team_name):
    """Ticket revenue in $M for this team this season.
    Scales from ~$15M (10% fan approval, small market) to ~$80M
    (99% fan approval, large market) matching rough real-NBA gate ranges."""
    fa = SIM_STATE.get("fan_approval", {}).get(team_name, 55)
    market_mult = {"large": 1.4, "medium": 1.0, "small": 0.7}[get_market_size(team_name)]
    base = 15 + (fa / 100) * 65
    revenue = round(base * market_mult, 1)
    SIM_STATE.setdefault("attendance_revenue", {})[team_name] = revenue
    return revenue


def post_game_fan_approval_tick(winner, loser, streak):
    """Called after every game result to tick fan approval up/down.
    Win streaks compound faster; blowout losses hurt more."""
    streak_bonus = min(3, streak // 3) if streak > 0 else 0
    update_fan_approval(winner, 1 + streak_bonus, "win")
    update_fan_approval(loser, -1, "loss")


# ───────────────────── MEDIA / PRESS CONFERENCE MINI-GAME ──────────────────────
PRESS_CONF_EVENTS = [
    {"id": "big_win",  "trigger": "win_streak_5",  "prompt": "You just won 5 in a row. How do you address the media?"},
    {"id": "big_loss", "trigger": "loss_streak_3", "prompt": "3 straight losses. The press is asking tough questions."},
    {"id": "star_trade","trigger": "star_traded",  "prompt": "You just traded away a fan favourite. How do you spin it?"},
    {"id": "title",    "trigger": "champion",      "prompt": "You've won the championship! What do you say?"},
]

PRESS_RESPONSES = {
    "confident":   {"label": "😤 Confident",   "morale": +4, "fan": +3, "desc": "Bold statement fires up the locker room"},
    "humble":      {"label": "🙏 Humble",       "morale": +2, "fan": +5, "desc": "Fans love the humility"},
    "deflect":     {"label": "🤐 No Comment",   "morale": -1, "fan": -2, "desc": "Silence raises eyebrows"},
    "motivate":    {"label": "🔥 Call to Arms", "morale": +6, "fan": +2, "desc": "Squad gets fired up — short-term boost"},
    "honest":      {"label": "🎯 Brutally Honest","morale": +1,"fan": +4, "desc": "Respects the fans but might sting"},
}


def trigger_press_conference(event_id):
    event = next((e for e in PRESS_CONF_EVENTS if e["id"] == event_id), None)
    if not event:
        return
    SIM_STATE["pending_press_conference"] = {
        "event_id": event_id, "prompt": event["prompt"],
        "responses": PRESS_RESPONSES,
    }


def resolve_press_conference(response_key):
    resp = PRESS_RESPONSES.get(response_key)
    if not resp:
        return {"success": False, "reason": "Invalid response."}
    user_team = SIM_STATE["user_team"]
    # apply morale to user's roster
    for p in team_roster(user_team):
        p["morale"] = round(min(100, max(0, p.get("morale", 70) + resp["morale"])), 1)
    update_fan_approval(user_team, resp["fan"], reason=f"press conference: {response_key}")
    SIM_STATE["media_morale_bonus"] = resp["morale"]
    SIM_STATE.pop("pending_press_conference", None)
    news_msg = f'GM chose to {resp["label"]} after the press conference. {resp["desc"]}.'
    push_news("🎙", news_msg, "general")
    return {"success": True, "effect": resp}


def team_total_salary(team_name):
    roster = team_roster(team_name)
    return round(sum((p["contract"]["salary"] if p["contract"] else 0) for p in roster), 1)


def get_team_asset_valuation(team, asset):
    """
    Contextual trade-value multiplier for a single asset (a player dict OR a draft
    pick dict), seen through `team`'s current win% lens:
      - Win% > 60%  (Contender): future draft capital valued at 60%, but high-rated
        (80+) ready-now veterans (age 25+) get a 125% premium.
      - Win% < 40%  (Rebuilder): draft capital valued at 125%, expiring veteran
        contracts (age 30+, <=1 year left) discounted hard to 55%.
      - Otherwise (Balanced): no adjustment.
    Returns the asset's adjusted value in trade-value points.
    """
    is_pick = "round" in asset and "year" in asset
    base = pick_value(asset) if is_pick else player_value(asset)
    wp = team_win_pct(team)

    if wp > 0.60:
        if is_pick:
            base *= 0.60
        elif asset["rating"] >= 80 and asset["age"] >= 25:
            base *= 1.25
    elif wp < 0.40:
        if is_pick:
            base *= 1.25
        else:
            is_expiring_vet = (asset.get("contract") and asset["contract"]["years_left"] <= 1) and asset["age"] >= 30
            if is_expiring_vet:
                base *= 0.55

    return round(base, 1)


def contextual_player_value(p, evaluating_team):
    """Value a player from the perspective of the team currently evaluating them,
    factoring in whether that team is contending, rebuilding, or balanced."""
    return get_team_asset_valuation(evaluating_team, p)


def contextual_pick_value(pick, evaluating_team):
    return get_team_asset_valuation(evaluating_team, pick)


def package_value(player_names, pick_ids):
    total = 0.0
    for n in player_names:
        p = SIM_STATE["players"].get(n)
        if p:
            total += player_value(p)
    for pid in pick_ids:
        pk = SIM_STATE["draft_picks"].get(pid)
        if pk:
            total += pick_value(pk)
    return round(total, 1)


def contextual_package_value(player_names, pick_ids, evaluating_team, protections=None):
    protections = protections or {}
    total = 0.0
    for n in player_names:
        p = SIM_STATE["players"].get(n)
        if p:
            total += contextual_player_value(p, evaluating_team)
    for pid in pick_ids:
        pk = SIM_STATE["draft_picks"].get(pid)
        if pk:
            if pid in protections and protections[pid] in PROTECTION_VALUE_DISCOUNT:
                pk_copy = dict(pk)
                pk_copy["protection"] = protections[pid]
                total += get_team_asset_valuation(evaluating_team, pk_copy)
            else:
                total += contextual_pick_value(pk, evaluating_team)
    return round(total, 1)


def validate_trade_legality(team_name, players_out, picks_out, players_in, picks_in, final_size, tpe_id=None):
    if not (MIN_ROSTER <= final_size <= MAX_ROSTER):
        return False, f"{team_name} roster size would be illegal ({final_size})."

    # UPGRADE: "Untradeable" flag. A GM can lock franchise cornerstones from
    # ever leaving via trade -- checked here so it's enforced on every path
    # a trade can execute through (user-built offers AND AI-generated offers
    # the user might accept), not just the trade-builder UI.
    locked = set(SIM_STATE.get("untradeable", {}).get(team_name, []))
    locked_hit = locked.intersection(players_out)
    if locked_hit:
        who = ", ".join(sorted(locked_hit))
        return False, f"{who} is flagged untradeable by {team_name} and can't be included in a trade."

    # UPGRADE: No-trade clauses. Distinct from the untradeable flag above --
    # this is a real contract term the player themselves holds, not
    # something the GM can toggle on or off. A trade involving one of these
    # players is blocked outright unless/until that clause is gone (the
    # contract expires or is renegotiated).
    ntc_hit = [n for n in players_out
               if SIM_STATE["players"].get(n) and (SIM_STATE["players"][n].get("contract") or {}).get("no_trade_clause")]
    if ntc_hit:
        who = ", ".join(sorted(ntc_hit))
        return False, f"{who} has a no-trade clause in their contract and must approve any deal — they haven't."

    current_salary = team_total_salary(team_name)
    outgoing_salary = sum((SIM_STATE["players"][n]["contract"]["salary"]
                            if SIM_STATE["players"].get(n) and SIM_STATE["players"][n]["contract"] else 0)
                           for n in players_out)
    incoming_salary = sum((SIM_STATE["players"][n]["contract"]["salary"]
                            if SIM_STATE["players"].get(n) and SIM_STATE["players"][n]["contract"] else 0)
                           for n in players_in)
    projected_salary = round(current_salary - outgoing_salary + incoming_salary, 1)

    # UPGRADE: Trade Exceptions (TPE). If this team is spending a valid,
    # unexpired TPE of its own with enough room left, it can absorb the
    # incoming salary gap without matching outgoing salary for it -- this
    # is the whole point of banking one. Skips straight past both the hard
    # apron check and the 125%-matching rule below, exactly like the real
    # CBA rule it's modeling.
    tpe = find_tpe(team_name, tpe_id) if tpe_id else None
    if tpe:
        gap = incoming_salary - outgoing_salary
        if gap > tpe["remaining"] + 0.05:
            return False, (f"{team_name}'s trade exception only has ${tpe['remaining']}M left -- "
                            f"this trade needs ${round(gap, 1)}M of exception room to cover the salary gap.")
        return True, ""

    hard_apron = SALARY_CAP + TAX_APRON_ROOM
    if projected_salary > hard_apron and projected_salary >= current_salary:
        return False, (f"{team_name} would land at ${projected_salary}M against a ${hard_apron}M hard apron "
                        f"(${SALARY_CAP}M cap + luxury tax room) and this trade doesn't reduce their salary — rejected for cap reasons.")

    # UPGRADE: Trade Machine salary-matching & realism pass. Real CBA rules
    # require an over-the-cap team's outgoing salary to cover a real fraction
    # of what's coming back in (roughly incoming <= outgoing*1.25 + $100k for
    # most teams). A team already under the cap can absorb salary freely (that
    # IS their cap room), but a team already over the cap can't just take on
    # a much bigger contract than it's sending out.
    if current_salary > SALARY_CAP and incoming_salary > outgoing_salary:
        matching_limit = round(outgoing_salary * 1.25 + 0.1, 2)
        if incoming_salary > matching_limit:
            return False, (f"{team_name} is over the cap and can only take back up to ${matching_limit}M in salary "
                            f"for the ${outgoing_salary}M they're sending out (125% + $100k matching rule) — "
                            f"this trade brings back ${incoming_salary}M.")

    return True, ""


def _package_best_player_rating(players):
    ratings = [SIM_STATE["players"][n]["rating"] for n in players if SIM_STATE["players"].get(n)]
    return max(ratings) if ratings else 0


def trade_passes_sanity_check(players_a, players_b, picks_a=None):
    """
    UPGRADE: Trade Machine "as bad as it looks" logic. The value-formula
    threshold in evaluate_and_execute_trade can, in edge cases (a bunch of
    matching salary filler vs. one real player, or several mediocre rotation
    guys vs. one star), technically clear the bar while still being a deal no
    real front office takes -- giving up a clearly-better player for a
    clearly-worse one. This is a blunt final guardrail: if the best player
    team B is giving up rates 12+ points higher than the best player they'd
    receive, and the receiving side isn't at least getting real quantity
    back (3+ total assets) to compensate, it's rejected regardless of what
    the value formula said.

    BUGFIX: picks_a used to not be a parameter at all here -- "quantity"
    only ever counted len(players_a), so a real 91-OVR-for-70-OVR offer
    sweetened with two future first-round picks was rejected by this same
    guard as if the picks didn't exist, no matter how many were added. A
    star still isn't going to move for a bench guy and a second-rounder --
    but first-round-capital-heavy packages should actually be able to clear
    this bar the way they would in a real front office, so picks now count
    toward the asset-quantity side of the check (weighted below full value
    of a player, since picks are inherently less certain than an established
    NBA player, but they do count).
    """
    picks_a = picks_a or []
    best_out = _package_best_player_rating(players_b)
    best_in = _package_best_player_rating(players_a)
    # Each real pick counts as 0.6 of a player toward the quantity bar --
    # substantial capital, but a proven veteran is still worth more than a
    # pick that hasn't been drafted yet.
    asset_quantity = len(players_a) + 0.6 * len(picks_a)
    if best_out - best_in >= 12 and asset_quantity < 3:
        return False, (f"That deal is as bad as it looks — sending back a clearly worse best player "
                        f"({best_in or 'no one'} OVR vs. {best_out} OVR) without enough extra quantity to compensate. Rejected.")
    return True, ""


# UPGRADE: Trade Exceptions (TPE), real-NBA style. When a team sends out
# more outgoing salary than it takes back in a trade, the leftover salary
# room is banked as a Trade Exception it can use within a 1-year window to
# absorb an incoming player's salary in a LATER, separate trade without
# needing to send matching salary back for it. This is what actually
# enables realistic uneven trades (e.g., "take our vet's expiring deal,
# we'll take back less right now but you get vet-minimum flexibility
# later") instead of every trade needing to balance salary in the same
# transaction.
TPE_MIN_AMOUNT = 0.5  # ignore tiny/noise leftovers under $500k


def _tpe_expired(exc):
    if SIM_STATE["year"] > exc["expire_year"]:
        return True
    if SIM_STATE["year"] == exc["expire_year"] and SIM_STATE["current_day"] >= exc["expire_day"]:
        return True
    return False


def purge_expired_tpes():
    """Physically drops expired exceptions from state -- called once per
    simulated day so a stale TPE doesn't linger forever in the save file."""
    for team_name, excs in list(SIM_STATE.get("trade_exceptions", {}).items()):
        alive = [e for e in excs if not _tpe_expired(e)]
        if alive:
            SIM_STATE["trade_exceptions"][team_name] = alive
        else:
            SIM_STATE["trade_exceptions"].pop(team_name, None)


def active_tpes(team_name):
    return [e for e in SIM_STATE.get("trade_exceptions", {}).get(team_name, []) if not _tpe_expired(e)]


def maybe_create_trade_exception(team_name, players_sent, players_received):
    sent_salary = sum((SIM_STATE["players"][n]["contract"]["salary"]
                        if SIM_STATE["players"].get(n) and SIM_STATE["players"][n]["contract"] else 0)
                       for n in players_sent)
    received_salary = sum((SIM_STATE["players"][n]["contract"]["salary"]
                            if SIM_STATE["players"].get(n) and SIM_STATE["players"][n]["contract"] else 0)
                           for n in players_received)
    diff = round(sent_salary - received_salary, 1)
    if diff < TPE_MIN_AMOUNT:
        return
    exc = {
        "id": f"tpe_{len(SIM_STATE['trade_exceptions'].get(team_name, [])) + random.randint(1000,9999)}_{SIM_STATE['year']}",
        "amount": diff, "remaining": diff,
        "created_year": SIM_STATE["year"], "created_day": SIM_STATE["current_day"],
        "expire_year": SIM_STATE["year"] + 1, "expire_day": SIM_STATE["current_day"],
        "source": f"Trade sending out {', '.join(players_sent) if players_sent else 'assets'}",
    }
    SIM_STATE["trade_exceptions"].setdefault(team_name, []).append(exc)


def find_tpe(team_name, tpe_id):
    for e in active_tpes(team_name):
        if e["id"] == tpe_id:
            return e
    return None


def apply_trade(team_a, players_a, picks_a, team_b, players_b, picks_b, protections=None):
    protections = protections or {}
    snapshot_for_undo(f"Trade between {team_a} and {team_b}")
    maybe_create_trade_exception(team_a, players_a, players_b)
    maybe_create_trade_exception(team_b, players_b, players_a)
    for name in players_a:
        SIM_STATE["players"][name]["team"] = team_b
        SIM_STATE["players"][name]["seasons_with_team"] = 0
        clear_trade_request(name)   # UPGRADE: morale/trade-request system -- resolved by the trade itself
    for name in players_b:
        SIM_STATE["players"][name]["team"] = team_a
        SIM_STATE["players"][name]["seasons_with_team"] = 0
        clear_trade_request(name)
    disrupt_chemistry(team_a, amount=5.0 + len(players_b) * 2.0)
    disrupt_chemistry(team_b, amount=5.0 + len(players_a) * 2.0)
    for pid in picks_a:
        SIM_STATE["draft_picks"][pid]["current_team"] = team_b
        if pid in protections:
            SIM_STATE["draft_picks"][pid]["protection"] = protections[pid]
    for pid in picks_b:
        SIM_STATE["draft_picks"][pid]["current_team"] = team_a
        if pid in protections:
            SIM_STATE["draft_picks"][pid]["protection"] = protections[pid]

    recompute_cap(team_a)
    recompute_cap(team_b)

    entry = {
        "year": SIM_STATE["year"], "team_a": team_a, "team_b": team_b,
        "sent_by_a": players_a + [f"{SIM_STATE['draft_picks'][pid]['year']} R{SIM_STATE['draft_picks'][pid]['round']} Pick" for pid in picks_a],
        "sent_by_b": players_b + [f"{SIM_STATE['draft_picks'][pid]['year']} R{SIM_STATE['draft_picks'][pid]['round']} Pick" for pid in picks_b],
    }
    SIM_STATE["trade_log"].insert(0, entry)


def team_untouchables(team, count=2):
    """A team's best `count` players are considered untouchable -- 2K-style
    realism guard so the Trade Finder/Fair Deal engine never dangles a
    franchise cornerstone as an easy grab."""
    roster = sorted(team_roster(team), key=lambda p: -p.get("rating", 0))
    return {p["name"] for p in roster[:count]}


def trade_grade_letter(fairness_pct):
    """Convert the numeric fairness score into the letter grade 2K shows on
    its trade screen."""
    if fairness_pct >= 105: return "A+"
    if fairness_pct >= 95: return "A"
    if fairness_pct >= 88: return "B+"
    if fairness_pct >= 80: return "B"
    if fairness_pct >= 70: return "C"
    if fairness_pct >= 55: return "D"
    return "F"


def team_positional_needs(team):
    """Return the 1-2 positions where a team is thinnest relative to the
    league average starter rating at that spot -- the same 'Team Needs'
    readout NBA 2K shows on the trade screen."""
    roster = team_roster(team)
    league_avg_by_pos = {}
    for pos in POSITIONS:
        ratings = [p["rating"] for p in SIM_STATE["players"].values() if not p["retired"] and p["position"] == pos]
        league_avg_by_pos[pos] = sum(ratings) / len(ratings) if ratings else 70

    team_best_by_pos = {}
    for pos in POSITIONS:
        ratings = [p["rating"] for p in roster if p["position"] == pos]
        team_best_by_pos[pos] = max(ratings) if ratings else 0

    gaps = sorted(POSITIONS, key=lambda pos: team_best_by_pos[pos] - league_avg_by_pos[pos])
    return [pos for pos in gaps if team_best_by_pos[pos] < league_avg_by_pos[pos]][:2] or [gaps[0]]


def suggest_trade_counter(team_a, players_a, picks_a, gap):
    """
    UPGRADE: Trade Machine counter-offer. When an AI team rejects a trade
    that was reasonably close in value, suggest a concrete asset the human
    GM could add to flip it into an accepted deal, instead of just a flat
    'no' -- same spirit as a real front office countering back.
    """
    if gap <= 0:
        return None
    roster_a = [p for p in team_roster(team_a) if p["name"] not in players_a]
    if gap <= 12:
        cand_picks = [pid for pid, pk in SIM_STATE["draft_picks"].items()
                      if pk["current_team"] == team_a and pk["round"] == 2 and pid not in picks_a]
        if cand_picks:
            pk = SIM_STATE["draft_picks"][cand_picks[0]]
            return f"Add the {pk['year']} 2nd-round pick to close the gap."
    if gap <= 24:
        cand_picks = [pid for pid, pk in SIM_STATE["draft_picks"].items()
                      if pk["current_team"] == team_a and pk["round"] == 1 and pid not in picks_a]
        if cand_picks:
            pk = SIM_STATE["draft_picks"][cand_picks[0]]
            return f"Add the {pk['year']} 1st-round pick to close the gap."
    filler = sorted(roster_a, key=lambda p: abs(p["rating"] - (52 + gap)))[:1]
    if filler:
        return f"Add a role player like {filler[0]['name']} ({filler[0]['rating']} OVR) as extra value."
    return "Try sweetening the offer with an additional draft asset."


def evaluate_and_execute_trade(team_a, players_a, picks_a, team_b, players_b, picks_b, protections=None, tpe_id=None):
    protections = protections or {}
    roster_a = team_roster(team_a)
    roster_b = team_roster(team_b)
    size_a_after = len(roster_a) - len(players_a) + len(players_b)
    size_b_after = len(roster_b) - len(players_b) + len(players_a)

    ok, msg = validate_trade_legality(team_a, players_a, picks_a, players_b, picks_b, size_a_after, tpe_id=tpe_id)
    if not ok:
        return {"accepted": False, "reason": msg}
    ok, msg = validate_trade_legality(team_b, players_b, picks_b, players_a, picks_a, size_b_after)
    if not ok:
        return {"accepted": False, "reason": msg}

    # Team B (usually the AI side) values both packages through its own contender/rebuilder lens.
    # Protected picks are discounted since they carry a real chance of not conveying.
    value_a_sends = contextual_package_value(players_a, picks_a, team_b, protections)
    value_b_sends = contextual_package_value(players_b, picks_b, team_b, protections)
    fairness_pct = round(min(150.0, (value_a_sends / max(1.0, value_b_sends)) * 100), 1)

    threshold = trade_acceptance_threshold(team_b)   # UPGRADE: trade aggressiveness dial + GM trust
    # 2K-style realism: a team's top couple of players are "untouchable" --
    # not literally unmovable, but it takes a real overpay (not just a fair
    # deal) before the front office considers moving one.
    untouchables_hit = [n for n in players_b if n in team_untouchables(team_b)]
    if untouchables_hit:
        threshold *= 1.6
    accepted = value_a_sends >= value_b_sends * threshold
    # Small randomness so it's not perfectly predictable
    if abs(value_a_sends - value_b_sends * threshold) < 6:
        accepted = random.random() < 0.5 + (value_a_sends - value_b_sends * threshold) * 0.03

    sanity_reason = None
    if accepted:
        sane, sanity_reason = trade_passes_sanity_check(players_a, players_b, picks_a)
        if not sane:
            accepted = False

    if accepted:
        apply_trade(team_a, players_a, picks_a, team_b, players_b, picks_b, protections)
        if tpe_id:
            tpe = find_tpe(team_a, tpe_id)
            if tpe:
                # players_a is what team_a sent out, players_b is what it received.
                sent_salary = sum((SIM_STATE["players"][n]["contract"]["salary"]
                                    if SIM_STATE["players"].get(n) and SIM_STATE["players"][n]["contract"] else 0)
                                   for n in players_a)
                received_salary = sum((SIM_STATE["players"][n]["contract"]["salary"]
                                        if SIM_STATE["players"].get(n) and SIM_STATE["players"][n]["contract"] else 0)
                                       for n in players_b)
                gap = max(0.0, received_salary - sent_salary)
                tpe["remaining"] = round(max(0.0, tpe["remaining"] - gap), 2)
                if tpe["remaining"] <= 0.01:
                    SIM_STATE["trade_exceptions"][team_a] = [e for e in SIM_STATE["trade_exceptions"].get(team_a, []) if e["id"] != tpe["id"]]
        if team_a == SIM_STATE["user_team"] or team_b == SIM_STATE["user_team"]:
            ai_team = team_b if team_a == SIM_STATE["user_team"] else team_a
            adjust_gm_trust(ai_team, fairness_pct)   # UPGRADE: front-office reputation system
            record_rivalry_trade(team_a, team_b)     # UPGRADE: rivalries & narrative arcs

    result = {
        "accepted": accepted,
        "value_sent": value_a_sends,
        "value_received": value_b_sends,
        "fairness_pct": fairness_pct,
        "team_b_context": team_context(team_b),
        "reason": "Trade accepted!" if accepted else (sanity_reason or f"{team_b} ({team_context(team_b)}) rejected the offer — they value their side higher."),
    }
    if not accepted:
        gap = value_b_sends * threshold - value_a_sends
        if 0 < gap < 28:
            counter = suggest_trade_counter(team_a, players_a, picks_a, gap)
            if counter:
                result["counter_suggestion"] = counter
    return result


def team_position_needs(team_name):
    """
    Returns positions sorted from WEAKEST to strongest for a team, based on the
    average rating of rostered players at each spot (an empty position counts as
    the weakest possible need). This drives which player type a smart AI GM
    actually targets in a trade, instead of a pure random pick.
    """
    roster = team_roster(team_name)
    by_pos = {pos: [] for pos in POSITIONS}
    for p in roster:
        by_pos.setdefault(p["position"], []).append(p["rating"])
    avg_by_pos = {pos: (sum(vals) / len(vals) if vals else 0) for pos, vals in by_pos.items()}
    return sorted(avg_by_pos.keys(), key=lambda pos: avg_by_pos[pos])


def generate_ai_trade_offer():
    ai_teams = [t for t in NBA_TEAMS if t != SIM_STATE["user_team"]]
    random.shuffle(ai_teams)
    user_roster = team_roster(SIM_STATE["user_team"])
    if not user_roster:
        return None

    for ai_team in ai_teams[:12]:
        ai_roster = team_roster(ai_team)
        if len(ai_roster) < MIN_ROSTER + 1 or not ai_roster:
            continue

        ctx = team_context(ai_team)

        # UPGRADE: "Trade block" -- players the user has explicitly marked
        # available get first look, ahead of the normal positional-need
        # scan. This is what makes AI teams "proactively call" about them:
        # the existing daily random-offer roll (see run_schedule_day) now
        # has a much better chance of surfacing a deal for a block player
        # specifically, instead of whatever the AI's need-scan happens to
        # land on.
        block_names = set(SIM_STATE.get("trade_block", []))
        block_candidates = [p for p in user_roster if p["name"] in block_names]

        # Smarter targeting: scan the AI's weakest 3 positions (not just 2) and
        # prefer the user's best-fit player there. Try a couple of candidates in
        # order (best fit first) so one illegal/oversized deal doesn't kill the
        # whole attempt for that team.
        needs = team_position_needs(ai_team)[:3]
        candidates = [p for p in user_roster if p["position"] in needs]
        if block_candidates:
            candidate_pool = block_candidates[:4]
        elif candidates:
            candidates.sort(key=lambda pl: -contextual_player_value(pl, ai_team))
            candidate_pool = candidates[:4] if len(candidates) >= 4 else candidates
        else:
            candidate_pool = sorted(user_roster, key=lambda pl: -contextual_player_value(pl, ai_team))[:4]
        if not candidate_pool:
            continue

        for target in candidate_pool:
            target_val = contextual_player_value(target, ai_team)
            target_salary = target["contract"]["salary"] if target["contract"] else 0.0
            # Tighter, fairer budget band than before -- a smart GM doesn't wildly
            # overpay OR lowball; contenders stretch slightly further for a real need.
            stretch = 1.10 if ctx == "Contender" else 1.0
            budget = target_val * random.uniform(0.95, 1.08) * stretch

            # A smart AI protects its own core: young, high-rated building blocks
            # (85+ OVR, age <= 26) are off the table unless the team is actively
            # rebuilding and selling everything, or it's a true blockbuster where
            # nothing else covers the value.
            def is_untouchable(pl):
                return pl["rating"] >= 85 and pl["age"] <= 26 and ctx != "Rebuilder"

            tradeable = [p for p in ai_roster if not is_untouchable(p)]
            if not tradeable:
                continue

            # Real trades roughly match outgoing/incoming salary (teams sit close to
            # the cap). Prefer pieces whose combined salary tracks the target's
            # salary, tie-broken toward the AI's lower-value assets so it keeps its
            # best remaining players.
            ai_roster_sorted = sorted(
                tradeable,
                key=lambda pl: (abs((pl["contract"]["salary"] if pl["contract"] else 0.0) - target_salary),
                                 contextual_player_value(pl, ai_team))
            )
            offer_players = []
            offer_val = 0.0
            outgoing_salary = 0.0
            for p in ai_roster_sorted:
                if len(offer_players) >= 3:
                    break
                if len(ai_roster) - len(offer_players) - 1 < MIN_ROSTER:
                    break
                offer_players.append(p["name"])
                offer_val += contextual_player_value(p, ai_team)
                outgoing_salary += (p["contract"]["salary"] if p["contract"] else 0.0)
                if outgoing_salary >= target_salary * 0.85 and offer_val >= budget * 0.65:
                    break

            # Sweeten with picks if still short -- contenders and balanced teams do
            # this readily; rebuilders only part with a pick if the offer is
            # otherwise close (they'd rather hoard picks).
            picks = team_picks(ai_team)
            offer_picks = []
            if picks and (ctx != "Rebuilder" or offer_val >= budget * 0.65):
                random.shuffle(picks)
                for pk in picks:
                    if offer_val >= budget * 0.98 or len(offer_picks) >= 2:
                        break
                    offer_picks.append(pk["id"])
                    offer_val += contextual_pick_value(pk, ai_team)

            if not offer_players and not offer_picks:
                continue
            # Don't send a package that badly overshoots the target's value either --
            # a smart GM doesn't give away more than it has to.
            if offer_val > budget * 1.35:
                continue

            size_ai_after = len(ai_roster) - len(offer_players) + 1
            size_user_after = len(user_roster) - 1 + len(offer_players)
            ok_ai, _ = validate_trade_legality(ai_team, offer_players, offer_picks, [target["name"]], [], size_ai_after)
            ok_user, _ = validate_trade_legality(SIM_STATE["user_team"], [target["name"]], [], offer_players, offer_picks, size_user_after)
            if not (ok_ai and ok_user):
                continue  # a smart GM doesn't propose a deal that would break the cap for either side

            return {
                "from_team": ai_team,
                "to_team": SIM_STATE["user_team"],
                "offer_players": offer_players,
                "offer_picks": offer_picks,
                "wants_players": [target["name"]],
                "wants_picks": [],
                "offer_value": round(offer_val, 1),
                "want_value": round(target_val, 1),
                "context": ctx,
            }
    return None


# ==========================================
# DRAFT SYSTEM
# ==========================================
def resolve_pick_protections(draft_year):
    """
    Right before a draft, check every traded, protected first-round pick for this
    year: if the original team's own projected slot (worst record = pick 1) falls
    within the protection range, the pick does NOT convey. It reverts to the
    original team and the team that was supposed to receive it is compensated
    with an unprotected future 2nd-round pick instead.
    """
    teams_by_slot = sorted(NBA_TEAMS, key=lambda t: team_win_pct(t))  # worst record = slot 1
    for pk in list(SIM_STATE["draft_picks"].values()):
        if pk["year"] != draft_year or pk["round"] != 1:
            continue
        if pk.get("protection", "None") == "None":
            continue
        if pk["current_team"] == pk["original_team"]:
            continue  # never traded away, protection is moot
        threshold = PICK_PROTECTION_TIERS.get(pk["protection"], 0)
        slot = teams_by_slot.index(pk["original_team"]) + 1 if pk["original_team"] in teams_by_slot else 30
        if slot <= threshold:
            receiving_team = pk["current_team"]
            pk["current_team"] = pk["original_team"]
            pk["protection"] = "None"
            comp_year = SIM_STATE["year"] + 2
            comp_pick = make_pick(comp_year, 2, pk["original_team"], current_team=receiving_team)
            if comp_pick["id"] in SIM_STATE["draft_picks"]:
                comp_pick["id"] = comp_pick["id"] + f"_comp{random.randint(1000,9999)}"
            SIM_STATE["draft_picks"][comp_pick["id"]] = comp_pick


LOTTERY_SLOTS = 4     # how many picks at the top of round 1 are drawn by weighted odds
LOTTERY_TEAM_COUNT = 14  # how many non-playoff teams are in the lottery pool, NBA-style


def run_draft_lottery():
    """
    UPGRADE: real NBA-style weighted draft lottery. Previously round 1 draft order
    was a flat, deterministic worst-record-picks-first sort -- so tanking to the
    very bottom of the league guaranteed the #1 pick every single time. Now only
    the 14 teams that missed the playoffs are lottery-eligible, and their odds at
    the top 4 picks are weighted (the worse the record, the better the odds, but
    never a lock) via a real ping-pong-ball-style weighted draw without
    replacement. The remaining lottery teams and every playoff team still slot in
    by reverse standings, same as the real league.
    Returns {team_name: slot_index} for all 30 teams (slot 1 = first overall).
    """
    ranked_worst_first = sorted(NBA_TEAMS, key=lambda t: team_win_pct(t))

    bracket = SIM_STATE.get("playoff_bracket", {}).get("1", [])
    playoff_teams = {m["team1"] for m in bracket} | {m["team2"] for m in bracket}
    if len(playoff_teams) < 16:
        # Fallback (e.g. draft triggered without a completed playoff bracket):
        # just treat the 14 best records as "playoff teams" for lottery purposes.
        playoff_teams = set(ranked_worst_first[-16:])

    lottery_teams = [t for t in ranked_worst_first if t not in playoff_teams][:LOTTERY_TEAM_COUNT]
    non_lottery_playoff_teams = [t for t in ranked_worst_first if t not in lottery_teams]

    # Weighted odds: worst team gets the most ping-pong-ball combinations.
    weights = {t: (len(lottery_teams) - i) ** 2 for i, t in enumerate(lottery_teams)}
    pool = list(lottery_teams)
    drawn = []
    for _ in range(min(LOTTERY_SLOTS, len(pool))):
        total = sum(weights[t] for t in pool)
        r = random.uniform(0, total)
        upto = 0
        pick_team = pool[-1]
        for t in pool:
            upto += weights[t]
            if upto >= r:
                pick_team = t
                break
        drawn.append(pick_team)
        pool.remove(pick_team)

    remaining_lottery_worst_first = [t for t in lottery_teams if t not in drawn]
    final_order = drawn + remaining_lottery_worst_first + non_lottery_playoff_teams
    return {team: idx for idx, team in enumerate(final_order)}


def start_draft():
    draft_year = SIM_STATE["year"]
    resolve_pick_protections(draft_year)
    picks_this_draft = [pk for pk in SIM_STATE["draft_picks"].values() if pk["year"] == draft_year]

    lottery_slots = run_draft_lottery()
    SIM_STATE["last_lottery_order"] = [t for t, _ in sorted(lottery_slots.items(), key=lambda kv: kv[1])][:LOTTERY_SLOTS]

    def sort_key(pk):
        if pk["round"] == 1:
            return (pk["round"], lottery_slots.get(pk["original_team"], 99), 0.0)
        team_rec = SIM_STATE["teams"].get(pk["original_team"])
        win_pct = 0.5
        if team_rec and (team_rec["wins"] + team_rec["losses"]) > 0:
            win_pct = team_rec["wins"] / (team_rec["wins"] + team_rec["losses"])
        return (pk["round"], win_pct, random.random())

    picks_this_draft.sort(key=sort_key)

    SIM_STATE["draft"] = {"active": True, "order": [pk["id"] for pk in picks_this_draft],
                           "index": 0, "results": [], "year": draft_year}
    SIM_STATE["stage"] = "draft"
    advance_draft()


def draft_best_available():
    if not SIM_STATE["draft_class"]:
        return None
    return max(SIM_STATE["draft_class"], key=lambda p: p["rating"] + p["potential"] * 0.3)


def execute_draft_pick(prospect):
    pick_id = SIM_STATE["draft"]["order"][SIM_STATE["draft"]["index"]]
    pk = SIM_STATE["draft_picks"][pick_id]
    team_name = pk["current_team"]

    prospect["team"] = team_name
    rookie_salary = round(max(1.0, (prospect["rating"] - 50) * 0.35) * era_salary_scale(), 1)
    prospect["contract"] = {"years_left": 3, "salary": rookie_salary}
    prospect["salary"] = rookie_salary
    SIM_STATE["players"][prospect["name"]] = prospect
    SIM_STATE["draft_class"] = [p for p in SIM_STATE["draft_class"] if p["name"] != prospect["name"]]
    stash_or_activate_drafted_player(prospect, team_name)   # UPGRADE: international stash-and-hold

    SIM_STATE["draft"]["results"].append({
        "pick_number": SIM_STATE["draft"]["index"] + 1, "round": pk["round"],
        "team": team_name, "player": prospect["name"], "position": prospect["position"],
        "rating": prospect["rating"], "potential_grade": prospect["potential_grade"]
    })
    SIM_STATE["draft"]["index"] += 1
    recompute_cap(team_name)


def advance_draft():
    d = SIM_STATE["draft"]
    while d["active"] and d["index"] < len(d["order"]):
        pick_id = d["order"][d["index"]]
        pk = SIM_STATE["draft_picks"][pick_id]
        team_name = pk["current_team"]
        if team_name == SIM_STATE["user_team"]:
            break
        prospect = draft_best_available()
        if prospect is None:
            break
        execute_draft_pick(prospect)

    if d["index"] >= len(d["order"]):
        finish_draft()


def waive_player(player_name):
    """Release a player outright: he leaves his team's roster and re-enters the
    free agent pool immediately (any team, including his old one, can re-sign
    him later). This is the escape valve for rosters that end up over the
    MAX_ROSTER limit -- most commonly right after the draft, when rookies are
    added to a team's roster with no automatic corresponding cut."""
    p = SIM_STATE["players"].get(player_name)
    if not p or not p.get("team"):
        return {"success": False, "reason": "That player is not currently on a roster."}
    snapshot_for_undo(f"Waive {player_name}")
    old_team = p["team"]
    p["team"] = None
    p["contract"] = None
    p["injury"] = None
    p["salary"] = 0
    clear_trade_request(player_name)   # UPGRADE: morale/trade-request system
    if p not in SIM_STATE["free_agents"]:
        SIM_STATE["free_agents"].append(p)
    recompute_cap(old_team)
    return {"success": True, "team": old_team, "name": player_name}


def auto_waive_ai_rosters():
    """AI-controlled teams have no UI to manage cuts, so immediately after the
    draft trim any AI roster back down to MAX_ROSTER by releasing its
    lowest-rated players. The user's own team is left untouched here -- the
    user gets to choose who to waive themselves before the season is allowed
    to start (see api_start_new_season)."""
    cut = []
    for team_name in NBA_TEAMS:
        if team_name == SIM_STATE["user_team"]:
            continue
        roster = sorted(team_roster(team_name), key=lambda p: p["rating"])
        while len(roster) > MAX_ROSTER:
            worst = roster.pop(0)
            waive_player(worst["name"])
            cut.append({"name": worst["name"], "team": team_name})
    return cut


def finish_draft():
    SIM_STATE["draft"]["active"] = False
    for prospect in SIM_STATE["draft_class"]:
        prospect["team"] = None
        prospect["contract"] = None
        SIM_STATE["free_agents"].append(prospect)
    SIM_STATE["draft_class"] = []
    SIM_STATE["stage"] = "free_agency"
    SIM_STATE["fa_day"] = 0
    SIM_STATE["fa_daily_log"] = []
    auto_waive_ai_rosters()


# ==========================================
# FREE AGENCY SYSTEM (with bidding wars)
# ==========================================
BIDDING_WAR_CHANCE = 0.28


def check_salary_arbitration():
    """
    UPGRADE: Salary Arbitration. Run each season during the offseason.
    If a player is producing significantly above their contract value
    (based on PPG vs salary percentile), they demand a renegotiation.
    The GM can accept (raises their salary to market rate), decline (morale hit),
    or offer a compromise (split the difference).
    """
    user_team = SIM_STATE["user_team"]
    demands = []
    roster = team_roster(user_team)
    for p in roster:
        if not p.get("contract") or p.get("two_way") or p.get("no_trade_clause"):
            continue
        gp = max(1, p["stats"].get("GP", 0))
        ppg = p["stats"].get("PTS", 0) / gp
        salary = p["contract"]["salary"]
        years_left = p["contract"]["years_left"]
        # Market rate estimate: high-scoring, high-rated players on cheap deals
        market_rate = round(max(1.5, (p["rating"] - 55) * 0.55), 1)
        if salary < market_rate * 0.65 and ppg >= 15 and years_left >= 2:
            demands.append({
                "player": p["name"], "current_salary": salary,
                "market_rate": market_rate, "ppg": round(ppg, 1),
                "rating": p["rating"],
            })
    if demands:
        SIM_STATE["pending_arbitration"] = demands
        push_news("⚖️", f"{len(demands)} player(s) on your roster have filed for salary arbitration.", "contract")
    return demands


def resolve_arbitration(player_name, choice):
    """choice: 'accept' | 'decline' | 'compromise'"""
    demands = SIM_STATE.get("pending_arbitration", [])
    demand = next((d for d in demands if d["player"] == player_name), None)
    if not demand:
        return {"success": False, "reason": "No pending arbitration for that player."}
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    new_salary = demand["market_rate"]
    if choice == "accept":
        p["contract"]["salary"] = new_salary
        p["morale"] = min(100, p.get("morale", 70) + 15)
        msg = f"{player_name} got their market rate (${new_salary}M). Happy camper."
        p["contract"]["contract_type"] = "Standard"
    elif choice == "compromise":
        compromise = round((demand["current_salary"] + new_salary) / 2, 1)
        p["contract"]["salary"] = compromise
        p["morale"] = min(100, p.get("morale", 70) + 5)
        msg = f"{player_name} accepted a compromise at ${compromise}M/yr."
    else:  # decline
        p["morale"] = max(20, p.get("morale", 70) - 20)
        p.setdefault("low_morale_streak", 0)
        p["low_morale_streak"] += 3
        msg = f"{player_name} was denied — morale dropped sharply. Trade request likely."
    recompute_cap(p["team"])
    SIM_STATE["pending_arbitration"] = [d for d in demands if d["player"] != player_name]
    push_news("⚖️", msg, "contract")
    return {"success": True, "message": msg, "choice": choice}


def negotiate_salary(p, team_name=None):
    """
    Player's market-demanded salary. The base number is cached on the player
    dict as 'asking_price' (pure rating-based) so it doesn't flicker across
    repeated background polls with no team context.

    UPGRADE: Interactive Player Demand Engine. When a specific team_name is
    supplied, the number returned layers three real free-agency dynamics on
    top of that base demand instead of a single flat market rate:
      - Market size: players ask a premium to sign in a small market and will
        take a discount to play in a marquee city.
        - Winning percentage: a genuine contender gets a "wants to win" discount;
        a bad team has to overpay to get a player to sign on.
      - Projected role: a player who'd be a clear starter there commands full
        price; one projected to come off the bench discounts their ask.
    The cached base 'asking_price' itself is never mutated by team context, so
    the FA board's headline number always stays the neutral market rate.
    """
    if p.get("asking_price") is None:
        p["asking_price"] = round(max(1.0, (p["rating"] - 55) * 0.55 + random.uniform(-0.5, 1.0)) * era_salary_scale(), 1)
    base = p["asking_price"]
    if team_name is None:
        return base

    demand = base
    tier = market_size_tier(team_name)
    demand *= {"Large": 0.94, "Mid": 1.0, "Small": 1.12}.get(tier, 1.0)

    wp = team_win_pct(team_name)
    if wp >= 0.600:
        demand *= 0.92       # contenders get a "wants to win" discount
    elif wp <= 0.350:
        demand *= 1.10       # bad teams have to overpay to attract talent

    roster = team_roster(team_name)
    same_pos = [pl for pl in roster if pl["position"] == p["position"]]
    would_start = not same_pos or p["rating"] >= max((pl["rating"] for pl in same_pos), default=0)
    if not would_start and same_pos:
        demand *= 0.85       # projected bench role discounts the ask

    # UPGRADE: Player agent personalities layer on top of the market/win%/
    # role numbers above instead of replacing them.
    personality = p.get("agent_personality", "Balanced")
    if personality == "Loyalty":
        if p.get("team") == team_name:
            demand *= 0.90    # discounts hard to stay right where they are
        else:
            demand *= 1.06    # costs more to lure away from wherever they are
    elif personality == "Business":
        demand *= 1.08        # chases the money regardless of context
    elif personality == "Ring Chaser":
        if wp >= 0.600:
            demand *= 0.85    # will take a real discount to chase a ring
        elif wp <= 0.350:
            demand *= 1.15    # won't sign cheap with a loser

    return round(max(VETERAN_MINIMUM_BASE * era_salary_scale(), demand), 1)


TWO_WAY_SLOTS = 2
TWO_WAY_SALARY = 0.6

# UPGRADE: Scouting combine drills. Each prospect has hidden true athletic
# scores; when a GM runs them through a drill the result adds noise (±noise
# range) so results are informative but not perfect -- exactly like the real
# combine where a player's lane-agility time doesn't perfectly predict their
# NBA career. Running every drill tightens the confidence interval on the
# prospect's scouting range (widens if you skip it).
COMBINE_DRILLS = {
    "Vertical":    {"attr": "Athleticism", "noise": 6,  "cost": 1, "desc": "Max vertical leap"},
    "Sprint":      {"attr": "Speed",       "noise": 5,  "cost": 1, "desc": "3/4-court sprint time"},
    "Agility":     {"attr": "Defense",     "noise": 7,  "cost": 1, "desc": "Lane agility drill"},
    "Shooting":    {"attr": "Three-Point", "noise": 8,  "cost": 1, "desc": "Spot-up shooting workout"},
    "Strength":    {"attr": "Post-Up",     "noise": 6,  "cost": 1, "desc": "Bench press / body composition"},
}

# UPGRADE: G-League two-way simulation. Previously two-way players just sat
# invisible with locked minutes. Now they play G-League box scores every
# simulated day (light-weight, no UI needed) which lets them accumulate stats
# and development XP, and unlocks a GM "Call Up" action to bring them to the
# main roster (swapping to a standard slot) when the time is right.
G_LEAGUE_GAMES_PER_SEASON = 50
G_LEAGUE_DEV_XP_PER_GAME = 0.4   # rating points per G-League game played


def count_two_way(team_name):
    return sum(1 for p in team_roster(team_name) if p.get("two_way"))


def bird_rights_status(p, team_name):
    """
    Returns 'full' if the player has full Bird Rights with team_name (3+
    straight seasons there before hitting FA), 'early' for Early Bird (2
    years), or None. Only applies when re-signing with the SAME team the
    player was accrued with.
    """
    if p.get("bird_team") != team_name:
        return None
    years = p.get("bird_years", 0)
    if years >= BIRD_YEARS_REQUIRED:
        return "full"
    if years >= EARLY_BIRD_YEARS_REQUIRED:
        return "early"
    return None


def veteran_minimum_salary(p):
    """
    UPGRADE: Vet-minimum salary scaling by real years of service. This used to
    approximate a player's service time from (age - 20), which quietly broke
    down for anyone who entered the league later or earlier than exactly age
    20 (two-way conversions, older undrafted signings, etc.). Now it reads the
    player's actual accrued seasons_played, which is backfilled at creation
    and incremented for real once per season in process_offseason.
    """
    years_service = max(0, p.get("seasons_played", max(0, p.get("age", 22) - 20)))
    scale = era_salary_scale()
    return round(min(VETERAN_MINIMUM_BASE * scale + years_service * VETERAN_MINIMUM_PER_YEAR_SERVICE * scale, 4.5 * scale), 1)


def fa_eligibility_badges(p, team_name):
    """
    UPGRADE: Expose bird_rights_status / exception eligibility in the FA UI.
    Returns a list of short badge labels (e.g. ["Bird Rights", "MLE"])
    describing every cap exception team_name could use to sign this free
    agent right now, instead of the user having to already know exception
    types exist and try them blind. Purely informational -- doesn't reserve
    or spend anything.
    """
    badges = []
    status = bird_rights_status(p, team_name)
    if status == "full":
        badges.append("Full Bird Rights")
    elif status == "early":
        badges.append("Early Bird Rights")
    if not team_used_mle(team_name):
        cap = mle_amount_for(team_name)
        if negotiate_salary(p, team_name) <= cap + 0.5:
            badges.append("MLE" if cap == NON_TAXPAYER_MLE else "Taxpayer MLE")
    if negotiate_salary(p, team_name) <= veteran_minimum_salary(p) + 0.5:
        badges.append("Vet Min")
    cap_space = SIM_STATE["teams"].get(team_name, {}).get("cap_space", 0)
    if cap_space >= negotiate_salary(p, team_name):
        badges.append("Cap Space")
    return badges


def team_used_mle(team_name):
    return SIM_STATE["teams"].get(team_name, {}).get("used_mle_year") == SIM_STATE["year"]


def mle_amount_for(team_name):
    return TAXPAYER_MLE if SIM_STATE["teams"].get(team_name, {}).get("over_tax") else NON_TAXPAYER_MLE


def sign_free_agent(name, team_name, salary=None, two_way=False, exception=None):
    """
    exception: None (normal cap-room signing), 'bird' (Bird/Early-Bird Rights --
    re-signing your own outgoing free agent over the cap), 'mle' (Mid-Level
    Exception -- one signing per team per season, works even without cap room),
    or 'vet_min' (Veteran Minimum -- always available regardless of cap state).
    """
    pool = SIM_STATE["free_agents"]
    p = next((x for x in pool if x["name"] == name), None)
    if not p:
        return {"success": False, "reason": "Player not found in free agency pool."}
    snapshot_for_undo(f"Sign {name} to {team_name}")

    if two_way:
        # UPGRADE: G-League / two-way contracts. These sit outside the normal
        # 15-man cap-counted roster (a small extra pool for stashing young
        # talent), draw minimal cap hit, and are capped to spot minutes.
        if count_two_way(team_name) >= TWO_WAY_SLOTS:
            return {"success": False, "reason": f"{team_name} already has {TWO_WAY_SLOTS} two-way slots filled."}
        final_salary = TWO_WAY_SALARY
        p["team"] = team_name
        p["contract"] = {"years_left": 1, "salary": final_salary, "player_option": False, "team_option": False}
        p["salary"] = final_salary
        p["two_way"] = True
        p["minutes"] = 4
        p["asking_price"] = None
        p["seasons_with_team"] = 0
        SIM_STATE["players"][name] = p
        SIM_STATE["free_agents"] = [x for x in pool if x["name"] != name]
        return {"success": True, "player": name, "team": team_name, "salary": final_salary, "two_way": True}

    if len(team_roster(team_name)) >= MAX_ROSTER:
        return {"success": False, "reason": f"{team_name} roster is full ({MAX_ROSTER})."}

    # Auto-detect the best available exception if the caller didn't specify one
    # but a plain cap-room signing wouldn't fit.
    asking = negotiate_salary(p, team_name)
    proposed = salary if salary is not None else asking
    cap_space = SIM_STATE["teams"][team_name]["cap_space"]
    if exception is None and cap_space - proposed < -TAX_APRON_ROOM:
        if bird_rights_status(p, team_name):
            exception = "bird"
        elif not team_used_mle(team_name) and proposed <= mle_amount_for(team_name) + 0.5:
            exception = "mle"
        elif proposed <= veteran_minimum_salary(p) + 0.5:
            exception = "vet_min"

    final_salary = round(float(proposed), 1)
    apron_room = TAX_APRON_ROOM
    exception_label = None

    if exception == "bird":
        status = bird_rights_status(p, team_name)
        if not status:
            return {"success": False, "reason": f"{team_name} doesn't hold Bird Rights on {name}."}
        apron_room = BIRD_APRON_ROOM
        exception_label = "Full Bird Rights" if status == "full" else "Early Bird Rights"
    elif exception == "mle":
        if team_used_mle(team_name):
            return {"success": False, "reason": f"{team_name} has already used its Mid-Level Exception this season."}
        cap_mle = mle_amount_for(team_name)
        if final_salary > cap_mle:
            return {"success": False, "reason": f"The Mid-Level Exception caps out at ${cap_mle}M for {team_name}."}
        exception_label = "Mid-Level Exception"
    elif exception == "vet_min":
        vmin = veteran_minimum_salary(p)
        final_salary = min(final_salary, vmin) if final_salary > vmin else final_salary
        if final_salary > vmin + 0.05:
            return {"success": False, "reason": f"Veteran Minimum signings for {name} cap out around ${vmin}M."}
        exception_label = "Veteran Minimum"

    if exception_label is None and cap_space - final_salary < -TAX_APRON_ROOM:
        return {"success": False, "reason": f"{team_name} would blow through the ${TAX_APRON_ROOM}M luxury-tax apron "
                f"(${cap_space}M available, needs ${final_salary}M). Try a Bird Rights, MLE, or Veteran Minimum signing instead."}
    if exception_label and cap_space - final_salary < -apron_room:
        return {"success": False, "reason": f"Even with {exception_label}, {team_name} would exceed the hard cap "
                f"(${cap_space}M available, needs ${final_salary}M)."}

    p["team"] = team_name
    contract_years = random.randint(1, 3) if exception != "bird" else random.randint(2, 5)
    p["contract"] = {"years_left": contract_years, "salary": final_salary,
                      "player_option": random.random() < 0.15 and contract_years >= 3,
                      "team_option": random.random() < 0.12 and contract_years >= 3,
                      "exception_used": exception_label}
    p["salary"] = final_salary
    p["two_way"] = False
    p["minutes"] = 0
    p["asking_price"] = None
    p["seasons_with_team"] = 0
    if exception == "mle":
        SIM_STATE["teams"][team_name]["used_mle_year"] = SIM_STATE["year"]
    SIM_STATE["players"][name] = p
    SIM_STATE["free_agents"] = [x for x in pool if x["name"] != name]
    recompute_cap(team_name)
    disrupt_chemistry(team_name, amount=3.0)
    return {"success": True, "player": name, "team": team_name, "salary": final_salary, "exception": exception_label}


def convert_two_way_to_standard(name):
    """
    UPGRADE: Two-way contract conversion flow. Converts a signed two-way
    player onto a real standard contract once a 15-man roster spot is open,
    instead of the user having to waive and re-sign him through the normal FA
    flow. Charges him at (at least) the veteran-minimum rate, same as a real
    two-way-to-standard NBA conversion.
    """
    p = SIM_STATE["players"].get(name)
    if not p or not p.get("two_way"):
        return {"success": False, "reason": "That player isn't on a two-way contract."}
    team_name = p["team"]
    if not team_name:
        return {"success": False, "reason": "That player isn't currently on a roster."}
    standard_roster = [pl for pl in team_roster(team_name) if not pl.get("two_way")]
    if len(standard_roster) >= MAX_ROSTER:
        return {"success": False, "reason": f"{team_name}'s standard {MAX_ROSTER}-man roster is full -- waive someone first."}

    salary = veteran_minimum_salary(p)
    cap_space = SIM_STATE["teams"][team_name]["cap_space"]
    if cap_space - salary < -TAX_APRON_ROOM:
        return {"success": False, "reason": f"{team_name} doesn't have room under the apron for a standard-contract "
                f"conversion (${cap_space}M available, needs ${salary}M)."}

    p["two_way"] = False
    p["contract"] = {"years_left": random.randint(1, 2), "salary": salary,
                      "player_option": False, "team_option": False, "exception_used": "Two-Way Conversion"}
    p["salary"] = salary
    recompute_cap(team_name)
    push_news("📈", f"{p['name']} converted from a two-way deal to a standard NBA contract with {team_name}.", "roster")
    return {"success": True, "player": name, "team": team_name, "salary": salary}


def find_bidding_rival(p, base_salary, exclude_team):
    candidates = []
    for t in NBA_TEAMS:
        if t == exclude_team:
            continue
        if len(team_roster(t)) >= MAX_ROSTER - 1:
            continue
        # Tax-aware apron: contenders will dip further into the luxury tax to
        # chase a real upgrade; balanced/rebuilding teams stay much more cautious.
        apron_allowance = TAX_APRON_ROOM if team_context(t) == "Contender" else TAX_APRON_ROOM * 0.35
        if SIM_STATE["teams"][t]["cap_space"] - base_salary * 1.05 < -apron_allowance:
            continue
        # rivals more likely to jump in if the player upgrades their roster
        candidates.append(t)
    if not candidates:
        return None
    return random.choice(candidates)


def handle_free_agency_offer(player, user_offer, exception=None):
    """
    Dynamic bidding-war resolver. `player` is a free-agent dict, `user_offer` is the
    salary ($M) the user is putting on the table. Rolls BIDDING_WAR_CHANCE (28%) for
    a rival CPU team to jump in -- the CPU team must have an open roster spot and
    enough cap space to actually make the counter, and its counter-offer lands
    somewhere between 108% and 130% of the player's market demand (negotiate_salary).
    Every war (triggered or not) is logged to SIM_STATE["bidding_wars"].
    """
    user_team = SIM_STATE["user_team"]
    market_demand = negotiate_salary(player, user_team)
    rival = find_bidding_rival(player, user_offer, user_team)

    # Cap-exception signings (Bird Rights, MLE, Vet Min) are guaranteed money the
    # player already knows is a real anchor bid, so a rival war is less likely.
    war_chance = BIDDING_WAR_CHANCE * (0.4 if exception else 1.0)
    # UPGRADE: Player agent personalities feed into whether a bidding war
    # even happens, not just the number -- a Business-minded player invites
    # more rival interest (they're shopping it around by nature), while a
    # Loyalty player re-upping with the team they're already on is much
    # less likely to draw one (they're not really looking elsewhere).
    personality = player.get("agent_personality", "Balanced")
    if personality == "Business":
        war_chance *= 1.35
    elif personality == "Loyalty" and player.get("team") == user_team:
        war_chance *= 0.35
    triggered = bool(rival) and random.random() < war_chance
    entry = {
        "player": player["name"], "user_team": user_team, "user_offer": user_offer,
        "market_demand": market_demand, "triggered": triggered, "rival_team": rival if triggered else None,
    }

    if triggered:
        required_salary = round(market_demand * random.uniform(1.08, 1.30), 1)
        entry["required_salary"] = required_salary
        SIM_STATE["bidding_wars"].append(entry)
        SIM_STATE["pending_bid"] = {
            "player": player["name"], "user_team": user_team, "competing_team": rival,
            "base_salary": market_demand, "required_salary": required_salary,
        }
        return {"bidding_war": True, "player": player["name"], "competing_team": rival,
                "base_salary": market_demand, "required_salary": required_salary}

    SIM_STATE["bidding_wars"].append(entry)
    result = sign_free_agent(player["name"], user_team, salary=user_offer, exception=exception)
    result["bidding_war"] = False
    return result


def submit_user_fa_offer(name, offer_salary=None, exception=None):
    """
    User's opening offer on a free agent, either a structured custom offer (a
    salary the user proposes themselves, which can be above or below asking
    price) or -- if none supplied -- the player's straight market demand.
    A lowball offer well under asking price risks the player simply rejecting it
    outright (in addition to the normal rival bidding-war chance).
    """
    pool = SIM_STATE["free_agents"]
    p = next((x for x in pool if x["name"] == name), None)
    if not p:
        return {"success": False, "reason": "Player not found in free agency pool."}

    user_team = SIM_STATE["user_team"]
    if len(team_roster(user_team)) >= MAX_ROSTER:
        return {"success": False, "reason": f"{user_team} roster is full ({MAX_ROSTER})."}

    asking_price = negotiate_salary(p, user_team)
    base_salary = round(float(offer_salary), 1) if offer_salary is not None else asking_price

    if exception is None and SIM_STATE["teams"][user_team]["cap_space"] - base_salary < -TAX_APRON_ROOM:
        # Auto-suggest whichever cap exception would actually make this signing legal.
        if bird_rights_status(p, user_team):
            exception = "bird"
        elif not team_used_mle(user_team) and base_salary <= mle_amount_for(user_team) + 0.5:
            exception = "mle"
        elif base_salary <= veteran_minimum_salary(p) + 0.5:
            exception = "vet_min"
        else:
            return {"success": False, "reason": f"{user_team} would blow through the ${TAX_APRON_ROOM}M luxury-tax apron "
                    f"(${SIM_STATE['teams'][user_team]['cap_space']}M available, needs ${base_salary}M). "
                    f"No cap exception covers this offer."}

    # Lowball protection: offers well under market demand can just get turned down.
    if base_salary < asking_price * 0.80:
        if random.random() < 0.65:
            return {"success": False, "reason": f"{p['name']} turned down your ${base_salary}M offer — he's asking around ${asking_price}M."}

    return handle_free_agency_offer(p, base_salary, exception=exception)


def resolve_bidding_war(match):
    pending = SIM_STATE.get("pending_bid")
    if not pending:
        return {"status": "no_pending_bid"}

    SIM_STATE["pending_bid"] = None
    name = pending["player"]
    user_team = pending["user_team"]
    rival = pending["competing_team"]
    required_salary = pending["required_salary"]

    if not match:
        result = sign_free_agent(name, rival, salary=required_salary)
        outcome = {"status": "lost_to_rival", "team": rival, "salary": required_salary, "sign_result": result}
    elif SIM_STATE["teams"][user_team]["cap_space"] - required_salary < -TAX_APRON_ROOM:
        # Can't afford to match - player walks to the rival anyway
        result = sign_free_agent(name, rival, salary=required_salary)
        outcome = {"status": "could_not_afford", "team": rival, "salary": required_salary, "sign_result": result}
    else:
        result = sign_free_agent(name, user_team, salary=required_salary)
        outcome = {"status": "matched", "team": user_team, "salary": required_salary, "sign_result": result}

    for entry in reversed(SIM_STATE["bidding_wars"]):
        if entry["player"] == name and entry.get("triggered") and "resolution" not in entry:
            entry["resolution"] = outcome["status"]
            break
    return outcome


def simulate_fa_day():
    """Process ONE day of free agency, NBA2K MyLeague-style -- each AI team
    gets at most one signing attempt today instead of the whole period
    resolving instantly."""
    signed = []
    ai_teams = [t for t in NBA_TEAMS if t != SIM_STATE["user_team"]]
    random.shuffle(ai_teams)
    SIM_STATE["free_agents"].sort(key=lambda p: p["rating"], reverse=True)
    for team_name in ai_teams:
        if not SIM_STATE["free_agents"]:
            break
        if len(team_roster(team_name)) >= MAX_ROSTER - 1:
            continue
        apron_allowance = TAX_APRON_ROOM if team_context(team_name) == "Contender" else TAX_APRON_ROOM * 0.35
        for p in SIM_STATE["free_agents"]:
            salary = negotiate_salary(p)
            if SIM_STATE["teams"][team_name]["cap_space"] - salary >= -apron_allowance:
                result = sign_free_agent(p["name"], team_name)
                if result["success"]:
                    signed.append(result)
                break
    SIM_STATE["fa_day"] = min(SIM_STATE["fa_day"] + 1, SIM_STATE["fa_days_total"])
    SIM_STATE["fa_daily_log"] = signed
    return signed


def simulate_fa_period():
    """Fast-forward every remaining day of the free agency period at once."""
    signed = []
    safety = 0
    while safety < 400:
        safety += 1
        if SIM_STATE["fa_day"] >= SIM_STATE["fa_days_total"] and safety > 1:
            pass  # allow at least one more pass, but don't loop forever
        day_signed = simulate_fa_day()
        if not day_signed:
            break
        signed.extend(day_signed)
        if SIM_STATE["fa_day"] >= SIM_STATE["fa_days_total"]:
            break
    return signed


# ==========================================
# RETIREMENT & PROGRESSION / REGRESSION
# ==========================================
def maybe_retire(p):
    age = p["age"]
    if age < 30:
        return False
    base_chance = 0.0
    if age >= 38:
        base_chance = 0.85
    elif age >= 36:
        base_chance = 0.45
    elif age >= 34:
        base_chance = 0.22
    elif age >= 32:
        base_chance = 0.10
    elif age >= 30:
        base_chance = 0.03
    if p["rating"] < 65:
        base_chance += 0.15
    if random.random() < min(0.95, base_chance):
        trigger_retirement_ceremony(p)
        return True
    return False


def trigger_retirement_ceremony(p):
    """On retirement, check if the player earns a jersey number retirement
    ceremony (great career) and/or Hall of Fame induction, then log it."""
    awards = p.get("career_awards", [])
    championships = sum(1 for a in awards if "Champion" in a.get("award",""))
    mvps = sum(1 for a in awards if a.get("award") == "MVP")
    seasons = p.get("career_totals", {}).get("SEASONS", 0) or len(set(a["year"] for a in awards)) or 1
    peak_rating = p.get("career_totals", {}).get("PEAK_RATING", p["rating"])

    # Jersey retirement: elite career (8+ seasons AND (multiple championships OR MVP))
    retire_jersey = seasons >= 8 and (championships >= 2 or mvps >= 1 or peak_rating >= 90)
    if retire_jersey:
        jersey_no = p.get("jersey", random.randint(1, 55))
        team = p.get("team") or p.get("career_totals", {}).get("LAST_TEAM") or "Unknown"
        ceremony = {
            "player": p["name"], "team": team, "jersey": jersey_no,
            "seasons": seasons, "mvps": mvps, "championships": championships,
            "year": SIM_STATE["year"], "peak_rating": peak_rating,
        }
        SIM_STATE.setdefault("retired_jerseys", []).append(ceremony)
        push_news("🏟", f"{team} retire #{jersey_no} — {p['name']} ({seasons} seasons, {championships}x champion)", "ceremony")

    # Hall of Fame: legendary career
    hof = peak_rating >= 90 or championships >= 3 or mvps >= 2 or (seasons >= 12 and championships >= 1)
    if hof:
        SIM_STATE.setdefault("hall_of_fame", []).append({
            "player": p["name"], "year": SIM_STATE["year"] + 1,
            "seasons": seasons, "peak_rating": peak_rating,
            "championships": championships, "mvps": mvps,
            "position": p.get("position"), "team": p.get("team"),
        })
        push_news("🏛", f"{p['name']} elected to Hall of Fame — Class of {SIM_STATE['year']+1}", "ceremony")
    p["hall_of_fame"] = hof


PHYSICAL_ATTRS = set(CATEGORY_ATTRS["Physical"])
MENTAL_ATTRS = set(CATEGORY_ATTRS["Intangibles"]) | {"Shot IQ", "Vision", "Help Defense IQ", "Ball Security", "Passing Accuracy"}


def apply_progression(p):
    """
    UPGRADE: Position-aware aging curves. The previous model used the same
    base arc for every player regardless of position. Real NBA careers diverge
    sharply by role: guards depend on speed and quickness (erode early), bigs
    rely on size, strength and post craft (hold up longer), wings split the
    middle. Added position-specific attribute decay multipliers and peak-window
    offsets so a 33-year-old PG and a 33-year-old C decline along genuinely
    different curves.
    """
    age = p["age"]
    pos = p.get("position", "SF")
    pot = p["potential"]
    rating = p["rating"]
    gap = pot - rating

    # Position-specific peak window shifts and physical-decay multipliers.
    # Guards peak earlier and lose athleticism faster; bigs peak slightly
    # later and their skill attributes (Post-Up, Rebounding, IQ) hold longest.
    POS_CONFIG = {
        "PG": {"peak_start": 24, "peak_end": 29, "phys_mult": 1.4, "skill_mult": 0.9},
        "SG": {"peak_start": 24, "peak_end": 30, "phys_mult": 1.3, "skill_mult": 0.95},
        "SF": {"peak_start": 25, "peak_end": 30, "phys_mult": 1.1, "skill_mult": 1.0},
        "PF": {"peak_start": 25, "peak_end": 31, "phys_mult": 0.9, "skill_mult": 1.05},
        "C":  {"peak_start": 26, "peak_end": 32, "phys_mult": 0.7, "skill_mult": 1.1},
    }
    cfg = POS_CONFIG.get(pos, POS_CONFIG["SF"])
    peak_s, peak_e = cfg["peak_start"], cfg["peak_end"]
    phys_m, skill_m = cfg["phys_mult"], cfg["skill_mult"]

    # Base arc using position-aware peak window
    if age <= 20:
        base = random.uniform(2.0, 5.5) * (0.5 + gap / 55.0)
    elif age < peak_s:
        base = random.uniform(1.2, 4.0) * (0.5 + gap / 65.0)
    elif age <= peak_e:
        base = random.uniform(-0.4, 1.2) * (0.4 + gap / 90.0) if gap > 0 else random.uniform(-0.6, 0.4)
    elif age <= peak_e + 3:
        base = random.uniform(-1.8, 0.2)
    elif age <= peak_e + 6:
        base = random.uniform(-3.5, -0.8)
    else:
        base = random.uniform(-6.5, -2.5)

    # Rare breakout / bust variance
    breakout_roll = random.random()
    if age <= 25 and gap > 12 and breakout_roll < 0.05:
        base += random.uniform(4.0, 8.0)
    elif age <= 26 and breakout_roll > 0.985:
        base -= random.uniform(3.0, 6.0)

    for k in p["attributes"]:
        if k in PHYSICAL_ATTRS:
            if age > peak_e:
                delta = base * phys_m * 1.6 + random.uniform(-2, 1)
            elif age > peak_s:
                delta = min(base, 0.5) + random.uniform(-1.5, 1.5)
            else:
                delta = base + random.uniform(-2, 2)
        elif k in MENTAL_ATTRS:
            if age <= peak_e + 2:
                delta = max(base * skill_m, -0.3) + random.uniform(-1.0, 1.5)
            else:
                delta = base * skill_m * 0.5 + random.uniform(-1.0, 1.0)
        else:
            delta = base + random.uniform(-2, 2)
        p["attributes"][k] = clamp(p["attributes"][k] + delta)

    old_rating = p["rating"]
    p["rating"] = calc_rating(p["attributes"])
    if p["rating"] > p["potential"]:
        p["potential"] = p["rating"] + random.randint(0, 3)
    p["potential_grade"] = potential_grade(p["potential"])
    p["badges"] = compute_badges(p)
    return round(p["rating"] - old_rating, 1)


def process_offseason():
    retired = []
    progressed = []
    regressed = []
    now_free = []

    # UPGRADE: Rivalry heat decays slightly each offseason
    decay_rivalries()
    # UPGRADE: Salary arbitration — check for outperforming players
    check_salary_arbitration()

    # UPGRADE: Personality spread — Mentors slightly improve young teammates,
    # Locker Room Cancers drag down team morale proportional to their rating.
    for team_name in NBA_TEAMS:
        roster = team_roster(team_name)
        mentors = [p for p in roster if p.get("personality_trait") == "Mentor"]
        cancers = [p for p in roster if p.get("personality_trait") == "Locker Room Cancer"]
        for p in roster:
            # Mentor lifts young players' development ceiling slightly
            if mentors and p["age"] <= 24 and p.get("personality_trait") not in ("Locker Room Cancer", "Lazy"):
                bonus = len(mentors) * 0.4
                p["potential"] = min(99, p.get("potential", 80) + round(random.uniform(0, bonus), 1))
            # Cancer drags morale — they spread negativity
            if cancers and p.get("personality_trait") not in ("Leader", "Professional"):
                drag = len(cancers) * random.uniform(1.5, 3.5)
                p["morale"] = max(20, p.get("morale", 70) - drag)

    # UPGRADE: Real historical stats archive + franchise records. Captures
    # each team's best single-season win total and best single-season scorer
    # while this season's numbers are still live (before the reset below),
    # so long-running saves build up real "best team/player ever" history
    # instead of that data just being overwritten and lost every year.
    for team_name in NBA_TEAMS:
        cfg = SIM_STATE["teams"].get(team_name, {})
        wins = cfg.get("wins", 0)
        fr = SIM_STATE["franchise_records"].setdefault(team_name, {})
        if wins > fr.get("best_season_wins", {}).get("wins", -1):
            fr["best_season_wins"] = {"wins": wins, "year": SIM_STATE["year"]}
        best_scorer, best_ppg = None, -1
        for p in team_roster(team_name):
            gp = p.get("stats", {}).get("GP", 0)
            if gp >= 20:
                ppg = p["stats"]["PTS"] / gp
                if ppg > best_ppg:
                    best_ppg, best_scorer = ppg, p["name"]
        if best_scorer and best_ppg > fr.get("best_season_scorer", {}).get("ppg", -1):
            fr["best_season_scorer"] = {"player": best_scorer, "ppg": round(best_ppg, 1), "year": SIM_STATE["year"]}

    for p in list(SIM_STATE["players"].values()):
        if p["retired"] or p["team"] is None:
            continue
        p["age"] += 1
        # UPGRADE: real accrued service time for veteran-minimum scaling
        # (see veteran_minimum_salary) -- ticks once per season actually
        # played, rather than only ever being approximated from age.
        p["seasons_played"] = p.get("seasons_played", 0) + 1

        if maybe_retire(p):
            p["retired"] = True
            awards = p.get("career_awards", [])
            career = p.get("career_totals", {})
            career_pts = career.get("PTS", 0) + p.get("stats", {}).get("PTS", 0)
            # UPGRADE: Hall of Fame induction now also recognizes a real career
            # scoring resume, not just awards count -- a 18,000+ career point
            # compiler gets in even without a stacked trophy case, like in the
            # real NBA.
            hof = len(awards) >= 6 or sum(1 for a in awards if a["award"] == "MVP") >= 2 or career_pts >= 18000
            SIM_STATE["retired_players"].append({
                "name": p["name"], "team": p["team"], "final_rating": p["rating"], "age": p["age"],
                "career_awards": awards,
                "championships": sum(1 for a in awards if a["award"] == "NBA Champion"),
                "all_star_selections": sum(1 for a in awards if a["award"] == "All-Star"),
                "mvps": sum(1 for a in awards if a["award"] == "MVP"),
                "career_points": round(career_pts),
                "hall_of_fame": hof,
            })
            # UPGRADE: retired jersey numbers. A Hall of Famer's number gets
            # retired by the franchise he was with when he hung it up.
            if hof and p["team"]:
                retired_list = SIM_STATE["retired_numbers"].setdefault(p["team"], [])
                if not any(rn["number"] == p["jersey"] for rn in retired_list):
                    retired_list.append({"number": p["jersey"], "player": p["name"], "year": SIM_STATE["year"]})
                    p["retired_number"] = True
                    push_news("🎽", f"{p['team']} will retire {p['name']}'s #{p['jersey']} jersey.", "history")
            retired.append({"name": p["name"], "team": p["team"], "age": p["age"]})
            recompute_cap(p["team"])
            continue

        delta = apply_progression(p)
        if delta > 0.6:
            progressed.append({"name": p["name"], "team": p["team"], "delta": delta, "new_rating": p["rating"]})
        elif delta < -0.6:
            regressed.append({"name": p["name"], "team": p["team"], "delta": delta, "new_rating": p["rating"]})

        if p["contract"]:
            p["contract"]["years_left"] -= 1
            if p["contract"]["years_left"] <= 0:
                old_team = p["team"]
                # Bird Rights: remember which team the player is walking away
                # from and how many consecutive seasons they'd stacked up, so
                # that team (and only that team) can go over the cap to keep
                # them via Bird/Early-Bird rights during free agency.
                p["bird_team"] = old_team
                p["bird_years"] = p.get("seasons_with_team", 0)
                p["team"] = None
                p["contract"] = None
                p["injury"] = None
                SIM_STATE["free_agents"].append(p)
                now_free.append({"name": p["name"], "old_team": old_team})
                recompute_cap(old_team)

    for team_name in NBA_TEAMS:
        recompute_cap(team_name)

    # generate replenishment picks 3 years out for every team
    new_year_target = SIM_STATE["year"] + 3
    for team_name in NBA_TEAMS:
        for rnd in [1, 2]:
            pk = make_pick(new_year_target, rnd, team_name)
            if pk["id"] not in SIM_STATE["draft_picks"]:
                SIM_STATE["draft_picks"][pk["id"]] = pk

    refill_practice_points()                      # UPGRADE: practice mini-game -- fresh budget each offseason
    promoted = tick_stashed_players()              # UPGRADE: international scouting -- count down stash timers
    if not SIM_STATE.get("assistant_coach_market"):
        refill_assistant_market()                  # UPGRADE: coaching staff depth -- keep the market stocked

    # UPGRADE PASS (free agent quality): previously the ONLY source of free
    # agents was waived players -- and rosters are generated with bench
    # spots (11-15) capped at 60-71 base rating, so the free agent pool
    # skewed toward replacement-level talent with nothing resembling a
    # real "quality vet" free agency class. Seed a handful of genuinely
    # useful players (75-88 base, the "solid starter / good bench piece"
    # band real free agency actually has) into the pool each offseason --
    # not superstars (those should be earned via trade/draft), but players
    # worth actually checking Free Agency for.
    quality_fa_signings = []
    num_quality_fas = random.randint(4, 7)
    for _ in range(num_quality_fas):
        pos = random.choice(POSITIONS)
        age = random.randint(24, 33)
        base = random.randint(75, 88)
        potential = clamp(base + random.randint(-3, 5), 65, 95)
        p = make_player(pos, age, base, potential, None, SIM_STATE["year"], SIM_STATE["year"] - (age - 20), tier="vet")
        p["contract"] = None
        p["salary"] = 0
        backfill_career_history(p, SIM_STATE["year"])
        SIM_STATE["players"][p["name"]] = p
        SIM_STATE["free_agents"].append(p)
        quality_fa_signings.append({"name": p["name"], "position": pos, "rating": p["rating"]})
    if quality_fa_signings:
        push_news("🆓", f"{len(quality_fa_signings)} notable free agents have entered the market this offseason, "
                         f"led by {quality_fa_signings[0]['name']} ({quality_fa_signings[0]['position']}, "
                         f"{quality_fa_signings[0]['rating']} OVR).", "general")

    report = {"retired": retired, "progressed": sorted(progressed, key=lambda x: -x["delta"])[:15],
              "regressed": sorted(regressed, key=lambda x: x["delta"])[:15], "now_free_agents": now_free,
              "international_promoted": promoted, "quality_free_agents_added": quality_fa_signings}
    SIM_STATE["offseason_report"] = report
    return report


def display_name(team_name):
    """UPGRADE: Franchise relocation/rebranding. Team dict keys stay stable
    everywhere internally (schedule, standings, trades, history all key off
    the original name) -- this overlay is what the UI shows once the user
    rebrands their franchise, so nothing structural has to change underneath."""
    return SIM_STATE.get("team_display_names", {}).get(team_name, team_name)


# UPGRADE: Team selection. The franchise used to always auto-assign the
# user to Gotham Knights -- this lets a GM pick literally any of the 30
# teams (used for the first-launch picker, and reusable later if they ever
# want to switch jobs). Everything per-team (roster, coach, scouting
# points, cap sheet) already exists for all 30 franchises from seed_league,
# so switching is just repointing which one is "yours" plus keeping the
# AI-trust bookkeeping honest for whichever team you're leaving behind.
def choose_user_team(new_team):
    if new_team not in NBA_TEAMS:
        return {"success": False, "reason": "That's not a valid team."}
    old_team = SIM_STATE["user_team"]
    if new_team == old_team:
        SIM_STATE["team_chosen"] = True
        return {"success": True, "user_team": new_team}
    SIM_STATE["gm_trust"][old_team] = SIM_STATE.get("gm_trust", {}).get(old_team, 50.0)
    SIM_STATE.setdefault("gm_trust", {}).pop(new_team, None)
    SIM_STATE["user_team"] = new_team
    SIM_STATE["team_chosen"] = True
    push_news("🎙️", f"{display_name(new_team)} introduce their new General Manager, "
                     f"taking over the front office duties.", "general")
    return {"success": True, "user_team": new_team}


def relocate_team(new_name):
    user_team = SIM_STATE["user_team"]
    if SIM_STATE["stage"] not in ("free_agency", "draft"):
        return {"success": False, "reason": "You can only relocate/rebrand the franchise during the offseason."}
    if SIM_STATE["teams"][user_team].get("relocated_this_offseason"):
        return {"success": False, "reason": "You've already rebranded the franchise this offseason."}
    new_name = (new_name or "").strip()
    if not new_name or len(new_name) > 40:
        return {"success": False, "reason": "Enter a valid new franchise name."}
    old_display = display_name(user_team)
    SIM_STATE.setdefault("team_display_names", {})[user_team] = new_name
    SIM_STATE["teams"][user_team]["relocated_this_offseason"] = True
    push_news("🏙️", f"{old_display} announce a relocation and rebrand — the franchise will now play as the {new_name}.", "general")
    return {"success": True, "new_name": new_name}


def run_expansion_draft():
    """
    UPGRADE: Expansion Draft. Rather than growing the league past its fixed
    30-team schedule structure (which would require rebuilding the entire
    round-robin schedule engine and risks breaking standings/history that key
    off a stable 30-team list), this restocks the two worst-performing AI
    franchises from a league-wide unprotected-player pool -- the same core
    "build a roster from scratch via an expansion draft" gameplay, without
    destabilizing the schedule.
    """
    if SIM_STATE.get("expansion_draft_used"):
        return {"success": False, "reason": "An expansion draft has already been run this game."}
    if SIM_STATE["stage"] not in ("free_agency", "draft"):
        return {"success": False, "reason": "Expansion drafts can only be run during the offseason."}

    ai_teams = [t for t in NBA_TEAMS if t != SIM_STATE["user_team"]]
    ranked = sorted(ai_teams, key=lambda t: SIM_STATE["teams"][t]["wins"] /
                     max(1, SIM_STATE["teams"][t]["wins"] + SIM_STATE["teams"][t]["losses"]))
    expansion_teams = ranked[:2]

    # Release the expansion franchises' existing rosters back to free agency.
    for t in expansion_teams:
        for p in team_roster(t):
            p["team"] = None
            p["contract"] = None
            p["minutes"] = 0
            SIM_STATE["free_agents"].append(p)

    # Every other team exposes its two weakest rostered players to the pool.
    pool = []
    for t in ai_teams:
        if t in expansion_teams:
            continue
        exposed = sorted(team_roster(t), key=lambda p: p["rating"])[:2]
        pool.extend(exposed)

    random.shuffle(pool)
    picks_log = {t: [] for t in expansion_teams}
    turn = 0
    while pool and any(len(team_roster(t)) < 11 for t in expansion_teams):
        team = expansion_teams[turn % 2]
        turn += 1
        if len(team_roster(team)) >= 11:
            continue
        needs = team_position_needs(team)
        candidate = next((p for pos in needs for p in pool if p["position"] == pos), None) or pool[0]
        pool.remove(candidate)
        old_team = candidate["team"]
        candidate["team"] = team
        candidate["contract"] = {"years_left": random.randint(1, 2), "salary": round(max(1.0, (candidate["rating"] - 55) * 0.45) * era_salary_scale(), 1)}
        candidate["salary"] = candidate["contract"]["salary"]
        candidate["seasons_with_team"] = 0
        if old_team and candidate in SIM_STATE["free_agents"]:
            SIM_STATE["free_agents"].remove(candidate)
        picks_log[team].append(candidate["name"])

    for t in expansion_teams:
        recompute_cap(t)

    ensure_min_rosters()
    SIM_STATE["expansion_draft_used"] = True
    SIM_STATE["expansion_history"] = {"year": SIM_STATE["year"], "teams": expansion_teams, "picks": picks_log}
    push_news("🆕", f"Expansion Draft complete: {expansion_teams[0]} and {expansion_teams[1]} have rebuilt their "
                     f"rosters from a league-wide talent pool.", "general")
    return {"success": True, "expansion_teams": expansion_teams, "picks": picks_log}


def edit_draft_prospect(old_name, new_name=None, new_position=None):
    """UPGRADE: Custom draft class editor. Rename a prospect or swap his
    listed position before the draft begins (locked once the draft goes
    live) -- attributes/ratings stay untouched to keep the class balanced."""
    if SIM_STATE["draft"]["active"]:
        return {"success": False, "reason": "The draft is already underway — this year's class is locked in."}
    prospect = next((p for p in SIM_STATE["draft_class"] if p["name"] == old_name), None)
    if not prospect:
        return {"success": False, "reason": "Prospect not found in this year's draft class."}
    if new_name:
        new_name = new_name.strip()
        if not new_name or len(new_name) > 40:
            return {"success": False, "reason": "Enter a valid name."}
        taken = any(p["name"] == new_name for p in SIM_STATE["draft_class"] if p is not prospect) or new_name in SIM_STATE["players"]
        if taken:
            return {"success": False, "reason": "That name is already taken."}
        prospect["name"] = new_name
    if new_position and new_position in POSITIONS:
        prospect["position"] = new_position
        prospect["badges"] = compute_badges(prospect)
    return {"success": True, "prospect": prospect["name"]}


def ensure_min_rosters():
    for team_name in NBA_TEAMS:
        roster = team_roster(team_name)
        shortfall = MIN_ROSTER - len(roster)
        for _ in range(max(0, shortfall)):
            pos = random.choice(POSITIONS)
            age = random.randint(23, 33)
            base = random.randint(58, 68)
            potential = clamp(base + random.randint(-3, 8), 55, 85)
            p = make_player(pos, age, base, potential, team_name, SIM_STATE["year"], SIM_STATE["year"] - (age - 20), tier="vet")
            p["contract"] = {"years_left": 1, "salary": round(max(1.0, (p["rating"] - 55) * 0.5) * era_salary_scale(), 1)}
            p["salary"] = p["contract"]["salary"]
            backfill_career_history(p, SIM_STATE["year"])
            SIM_STATE["players"][p["name"]] = p
        if shortfall > 0:
            recompute_cap(team_name)


def start_new_season():
    evaluate_owner_mandate()  # UPGRADE: owner mandates/hot seat -- must run before wins/losses reset below
    SIM_STATE["year"] += 1
    for p in SIM_STATE["players"].values():
        ct = p.setdefault("career_totals", {"FGM": 0, "FGA": 0, "3PM": 0, "3PA": 0, "FTM": 0, "FTA": 0, "PTS": 0,
                                             "REB": 0, "AST": 0, "STL": 0, "BLK": 0, "TOV": 0, "GP": 0, "MIN": 0, "SEASONS": 0})
        if p["stats"].get("GP", 0) > 0:
            for k in ("FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "PTS", "REB", "AST", "STL", "BLK", "TOV", "GP", "MIN"):
                ct[k] = ct.get(k, 0) + p["stats"].get(k, 0)
            ct["SEASONS"] = ct.get("SEASONS", 0) + 1
        p["stats"] = {"FGM": 0, "FGA": 0, "3PM": 0, "3PA": 0, "FTM": 0, "FTA": 0, "PTS": 0, "REB": 0, "AST": 0, "STL": 0, "BLK": 0, "TOV": 0, "GP": 0, "MIN": 0}
        p["injury"] = None
        p["fatigue"] = 0
        p["injury_history_count"] = max(0, p.get("injury_history_count", 0) - 1)  # a clean season cools the risk down
        p["injury_prone"] = p["injury_history_count"] >= 3
        if p.get("team"):
            p["seasons_with_team"] = p.get("seasons_with_team", 0) + 1  # continuity for team chemistry
    for team_name in NBA_TEAMS:
        SIM_STATE["teams"][team_name]["wins"] = 0
        SIM_STATE["teams"][team_name]["losses"] = 0
        SIM_STATE["teams"][team_name]["streak"] = 0
        SIM_STATE["teams"][team_name]["points_for"] = 0
        SIM_STATE["teams"][team_name]["relocated_this_offseason"] = False
        SIM_STATE["teams"][team_name]["points_against"] = 0
        recompute_cap(team_name)

    SIM_STATE["regular_season_games"] = []
    SIM_STATE["playoff_bracket"] = {"1": [], "2": [], "3": [], "4": []}
    SIM_STATE["playoffs_started"] = False
    SIM_STATE["playoffs_complete"] = False
    SIM_STATE["current_round"] = 1
    SIM_STATE["round_completed"] = False
    SIM_STATE["current_day"] = 1
    SIM_STATE["season_simulated"] = False
    SIM_STATE["awards"] = {"MVP": None, "DPOY": None, "ROY": None, "MIP": None, "Finals_MVP": None, "All_NBA": None, "All_Stars": None,
                            "Sixth_Man": None, "All_Defensive": None, "All_Rookie": None}
    SIM_STATE["offseason_report"] = None
    SIM_STATE["draft"] = {"active": False, "order": [], "index": 0, "results": [], "year": None}
    SIM_STATE["fa_day"] = 0
    SIM_STATE["fa_daily_log"] = []

    if not SIM_STATE["draft_class"]:
        SIM_STATE["draft_class"] = generate_draft_class(SIM_STATE["year"])
        for team_name in NBA_TEAMS:
            base_pts = SCOUT_POINTS_PER_SEASON
            scout_level = SIM_STATE.get("facilities", {}).get(team_name, {}).get("Scouting", 1)
            bonus_pts = FACILITY_BONUS["scout_pts"][min(scout_level - 1, 4)]
            SIM_STATE["scouting"]["points"][team_name] = base_pts + bonus_pts
        SIM_STATE["scouting"]["invested"] = {}

    ensure_min_rosters()
    build_schedule()
    setup_in_season_cup()
    SIM_STATE["trade_deadline_day"] = int(SIM_STATE["schedule_days_total"] * TRADE_DEADLINE_FRACTION)
    SIM_STATE["stage"] = "regular_season"


TRADE_OFFER_CHANCE_PER_DAY = 0.06


def simulate_all_star_weekend():
    """
    UPGRADE: All-Star Weekend. Around the season's midpoint, the league pauses
    for a flavor showcase: an East vs West All-Star Game (high-pace, low-D
    exhibition), a 3-Point Contest, and a Slam Dunk Contest -- each picking
    real winners off real attributes, and logging the results to the
    newswire like an actual mid-season event instead of the sim just quietly
    marching through the calendar.
    """
    active = [p for p in SIM_STATE["players"].values() if not p["retired"] and p.get("team")]
    east_pool = sorted([p for p in active if TEAM_CONFERENCE.get(p["team"]) == "East"], key=lambda p: -p["rating"])[:12]
    west_pool = sorted([p for p in active if TEAM_CONFERENCE.get(p["team"]) == "West"], key=lambda p: -p["rating"])[:12]
    if len(east_pool) < 5 or len(west_pool) < 5:
        return None

    # --- 3-Point Contest: top shooters by the Three-Point attribute ---
    three_field = sorted(active, key=lambda p: -p["attributes"].get("Three-Point", 60))[:8]
    three_scores = {p["name"]: round(p["attributes"].get("Three-Point", 60) * 0.28 + random.uniform(0, 12), 1) for p in three_field}
    three_champ = max(three_scores, key=three_scores.get)

    # --- Slam Dunk Contest: athleticism + a little showmanship flair ---
    dunk_field = sorted(active, key=lambda p: -(p["attributes"].get("Vertical", 60) + p["attributes"].get("Standing Dunk", p["attributes"].get("Driving Dunk", 60))))[:6]
    dunk_scores = {}
    for p in dunk_field:
        athleticism = (p["attributes"].get("Vertical", 60) + p["attributes"].get("Standing Dunk", p["attributes"].get("Driving Dunk", 60))) / 2
        score = round(athleticism * 0.85 + random.uniform(0, 20), 1)
        dunk_scores[p["name"]] = min(100.0, score)
    dunk_champ = max(dunk_scores, key=dunk_scores.get)

    # --- All-Star Game: high pace, minimal defense exhibition ---
    def squad_score(pool):
        return sum(60 + p["attributes"].get("Inside", 60) * 0.3 + p["attributes"].get("Outside", 60) * 0.3 for p in pool) / len(pool)
    east_score = int(squad_score(east_pool) * random.uniform(1.7, 1.95))
    west_score = int(squad_score(west_pool) * random.uniform(1.7, 1.95))
    winners = east_pool if east_score >= west_score else west_pool
    game_mvp = max(winners, key=lambda p: p["rating"])["name"]

    result = {
        "year": SIM_STATE["year"], "east_score": east_score, "west_score": west_score,
        "game_mvp": game_mvp, "three_pt_champ": three_champ, "dunk_champ": dunk_champ,
        "east_roster": [p["name"] for p in east_pool], "west_roster": [p["name"] for p in west_pool],
    }
    SIM_STATE["all_star"] = result
    winner_conf = "East" if east_score >= west_score else "West"
    push_news("🌟", f"All-Star Weekend: {winner_conf} wins the All-Star Game {max(east_score,west_score)}-"
                     f"{min(east_score,west_score)}! Game MVP: {game_mvp}. 3PT Contest: {three_champ}. Dunk Contest: {dunk_champ}.", "milestone")
    return result


def run_schedule_day():
    """Simulate one day of the schedule. Returns True if the caller (a
    multi-day sim loop) should stop -- either the season just wrapped, or an
    AI team surfaced a trade offer that needs the user's attention before
    the sim continues."""
    purge_expired_tpes()  # UPGRADE: Trade Exceptions (TPE) -- drop any that just aged out of their 1-year window
    g_league_tick()       # UPGRADE: G-League simulation -- tick two-way players' development
    total_days = SIM_STATE.get("schedule_days_total") or len(SIM_STATE["schedule"])
    if SIM_STATE["current_day"] > total_days:
        if not SIM_STATE["season_simulated"]:
            SIM_STATE["season_simulated"] = True
            generate_awards()
            if not SIM_STATE["playoffs_started"] and not SIM_STATE.get("play_in", {}).get("active"):
                begin_play_in()
        return True

    all_star = SIM_STATE.setdefault("all_star", {})
    if all_star.get("year") != SIM_STATE["year"] and SIM_STATE["current_day"] >= int(total_days * 0.48):
        simulate_all_star_weekend()

    day_idx = SIM_STATE["current_day"] - 1
    matchups = SIM_STATE["schedule"][day_idx] if day_idx < len(SIM_STATE["schedule"]) else []

    playing_teams = set()
    live_cache = SIM_STATE.setdefault("live_prewatched", {})
    for m in matchups:
        cache_key = f"{SIM_STATE['current_day']}|{m['home']}|{m['away']}"
        if cache_key in live_cache:
            # This matchup was already played out through the "Jump Into Game"
            # live viewer -- bookkeeping was already applied at watch-time, so

            # just fold the cached box score into today's results in order.
            box = live_cache.pop(cache_key)
        else:
            box = simulate_game(m["home"], m["away"], m.get("cup_knockout", False))
            if not m.get("cup_knockout"):
                # Cup knockout games are extra neutral-site showcase games
                # injected onto the calendar -- they don't touch regular
                # season win/loss records, only the Cup bracket.
                record_regular_result(m, box)
        cup_process_matchup(m, box)
        SIM_STATE["regular_season_games"].append(box)
        playing_teams.add(m["home"])
        playing_teams.add(m["away"])

    # Teams with no game today (a real rest day on their personal calendar) get a
    # bigger fatigue recovery bump than the small between-game recovery baked
    # into update_fatigue_and_morale.
    for team_name in NBA_TEAMS:
        if team_name in playing_teams:
            continue
        for p in team_roster(team_name):
            p["fatigue"] = clamp(p.get("fatigue", 0) - FATIGUE_RECOVERY_PER_DAY, 0, 100)

    tick_injuries()
    maybe_generate_trade_rumor()   # UPGRADE: in-season "trade rumor" feed
    cup_maybe_finalize_group_stage(SIM_STATE["current_day"])
    SIM_STATE["current_day"] += 1

    # UPGRADE BATCH 3: crown Player of the Week every 7 sim-days, Coach of
    # the Month every 30, and refresh cached team identities weekly.
    if SIM_STATE["current_day"] - SIM_STATE.get("weekly_watermark_day", 0) >= 7:
        evaluate_player_of_week()
        apply_weekly_training()
        for _team in NBA_TEAMS:
            compute_team_identity(_team)
        SIM_STATE["weekly_watermark_day"] = SIM_STATE["current_day"]
    if SIM_STATE["current_day"] % 30 == 0:
        evaluate_coach_of_month()

    stop = False
    if SIM_STATE["current_day"] > total_days:
        SIM_STATE["season_simulated"] = True
        generate_awards()
        if not SIM_STATE["playoffs_started"] and not SIM_STATE.get("play_in", {}).get("active"):
            begin_play_in()
        stop = True

    # Give the user's front office something to react to mid-sim, NBA2K-style
    # -- an AI GM occasionally calls with an offer, which pauses the sim until
    # it's accepted or declined. Teams call more often when the user has
    # actually put someone on the trade block (see trade_block upgrade).
    # UPGRADE: archetype eagerness modulates the base probability per team.
    call_chance = TRADE_OFFER_CHANCE_PER_DAY
    if SIM_STATE.get("trade_block"):
        call_chance = min(0.35, TRADE_OFFER_CHANCE_PER_DAY * 4)
    # Pick a random AI team and apply their archetype multiplier to the roll
    if not stop and not SIM_STATE["pending_offer"] and trade_window_open():
        ai_teams = [t for t in NBA_TEAMS if t != SIM_STATE["user_team"]]
        chosen_ai = random.choice(ai_teams) if ai_teams else None
        archetype_name = SIM_STATE.get("gm_archetypes", {}).get(chosen_ai)
        eagerness = GM_ARCHETYPES[archetype_name]["trade_eagerness"] if archetype_name else 1.0
        if random.random() < call_chance * eagerness:
            offer = generate_ai_trade_offer()
            if offer:
                SIM_STATE["pending_offer"] = offer
                stop = True

    return stop
# ==========================================
# FLASK ROUTING ENDPOINTS
# ==========================================
@app.route('/')
def index():
    html = _load_index_html()
    if html is None:
        # Give an actually actionable message instead of a raw Jinja
        # traceback -- we already searched every plausible location and
        # genuinely could not find templates/index.html on disk.
        return (
            "<pre style='font-family:monospace; padding:24px; white-space:pre-wrap;'>"
            "Could not find templates/index.html anywhere near this app.\n\n"
            f"Looked in (and below, a few levels deep): {_BASE_DIR}\n\n"
            "Make sure the 'templates' folder (with index.html inside it) "
            "is extracted in the SAME parent folder as app.py, not moved "
            "or left inside a nested zip subfolder.</pre>",
            500,
        )
    return render_template_string(html)


@app.after_request
def _bump_version_on_mutation(response):
    # Any successful POST to a state-changing /api/ endpoint marks the state as
    # "dirty" so the lightweight heartbeat poll can tell the client a real
    # refetch is needed, instead of the client blindly re-fetching (and
    # re-rendering) the entire ~2MB league payload on a dumb fixed timer.
    try:
        if request.method == "POST" and request.path.startswith("/api/") and response.status_code < 400:
            SIM_STATE["version"] = SIM_STATE.get("version", 0) + 1
    except Exception:
        pass
    return response


@app.route('/api/heartbeat')
def heartbeat():
    # Tiny, cheap payload polled every couple seconds. The client only pays for
    # a full /api/state fetch (and full re-render) when this version actually
    # changes, which is what makes tab switching and general navigation feel
    # instant instead of janky.
    return jsonify({
        "version": SIM_STATE.get("version", 0),
        "stage": SIM_STATE.get("stage"),
        "year": SIM_STATE.get("year"),
        "has_pending_offer": bool(SIM_STATE.get("pending_offer")),
    })


@app.route('/api/career_leaders')
def api_career_leaders():
    combined = []
    for p in SIM_STATE["players"].values():
        ct = p.get("career_totals", {})
        cur = p.get("stats", {})
        total_pts = ct.get("PTS", 0) + cur.get("PTS", 0)
        total_reb = ct.get("REB", 0) + cur.get("REB", 0)
        total_ast = ct.get("AST", 0) + cur.get("AST", 0)
        total_gp = ct.get("GP", 0) + cur.get("GP", 0)
        if total_gp <= 0:
            continue
        combined.append({"name": p["name"], "team": p.get("team") or "Retired",
                          "position": p.get("position", ""), "rating": p.get("rating", 0),
                          "pts": total_pts, "reb": total_reb, "ast": total_ast, "gp": total_gp})
    return jsonify({
        "points": sorted(combined, key=lambda x: -x["pts"])[:10],
        "rebounds": sorted(combined, key=lambda x: -x["reb"])[:10],
        "assists": sorted(combined, key=lambda x: -x["ast"])[:10],
        "games_played_league_wide": sum(x["gp"] for x in combined),
    })


@app.route('/api/save_game', methods=['POST'])
def api_save_game():
    data = request.json or {}
    result = save_game(data.get("slot", "autosave"))
    return jsonify(result)


@app.route('/api/load_game', methods=['POST'])
def api_load_game():
    data = request.json or {}
    slot = data.get("slot")
    if not slot:
        return jsonify({"success": False, "reason": "No save slot specified."})
    result = load_game(slot)
    return jsonify(result)


@app.route('/api/list_saves')
def api_list_saves():
    return jsonify({"saves": list_save_slots()})


@app.route('/api/delete_save', methods=['POST'])
def api_delete_save():
    data = request.json or {}
    slot = data.get("slot")
    if not slot:
        return jsonify({"success": False, "reason": "No save slot specified."})
    return jsonify(delete_save(slot))


@app.route('/api/state')
def get_state():
    # Compute each pick's current trade value fresh on every fetch (it depends on
    # year-distance and the originating team's live record) without mutating the
    # canonical stored pick dicts.
    payload = dict(SIM_STATE)
    payload["draft_picks"] = {
        pid: {**pk, "value": pick_value(pk)} for pid, pk in SIM_STATE["draft_picks"].items()
    }
    # Make sure every free agent has a stable, visible asking price, and
    # (UPGRADE) surface which cap exceptions the user's team could use to
    # sign them right now -- see fa_eligibility_badges.
    user_team = SIM_STATE["user_team"]
    payload["free_agents"] = []
    for fa in SIM_STATE["free_agents"]:
        negotiate_salary(fa)
        fa_view = dict(fa)
        fa_view["fa_eligibility"] = fa_eligibility_badges(fa, user_team)
        payload["free_agents"].append(fa_view)

    # Draft Scouting: the user only ever sees fogged, ranged projections for
    # prospects (never the raw attributes), narrowing as scout points go in.
    if SIM_STATE["draft_class"]:
        user_team = SIM_STATE["user_team"]
        invested = SIM_STATE["scouting"]["invested"].get(user_team, {})
        payload["draft_class"] = [
            scouted_prospect_view(p, invested.get(p["name"], 0)) for p in SIM_STATE["draft_class"]
        ]
        payload["scout_points_remaining"] = SIM_STATE["scouting"]["points"].get(user_team, 0)

    # UPGRADE: Coach system "recommended dials" hint.
    payload["recommended_dials"] = recommended_dials_for_coach(user_team)
    # UPGRADE: Combine results and press conference surfaced to frontend
    payload["combine_results"] = SIM_STATE.get("combine_results", {})
    payload["pending_press_conference"] = SIM_STATE.get("pending_press_conference")
    payload["gm_archetypes"] = SIM_STATE.get("gm_archetypes", {})
    payload["legacy_score"] = SIM_STATE.get("legacy_score", 0)
    payload["legacy_log"] = SIM_STATE.get("legacy_log", [])
    payload["retired_jerseys"] = SIM_STATE.get("retired_jerseys", [])
    payload["hall_of_fame"] = SIM_STATE.get("hall_of_fame", [])
    payload["trophy_room"] = SIM_STATE.get("trophy_room", [])
    payload["team_records"] = SIM_STATE.get("team_records", {})
    payload["franchise_goat"] = SIM_STATE.get("franchise_goat", {})
    payload["facilities"] = SIM_STATE.get("facilities", {}).get(user_team, {dept: 1 for dept in FACILITY_DEPTS})
    payload["arena"] = SIM_STATE.get("arena", {}).get(user_team, dict(ARENA_DEFAULTS))
    payload["pending_arbitration"] = SIM_STATE.get("pending_arbitration", [])

    return jsonify(payload)


@app.route('/api/update_rotation', methods=['POST'])
def update_rotation():
    data = request.json
    team = SIM_STATE["user_team"]
    # Only count minutes for this team's own roster toward the 240 budget --
    # the minutes payload should only ever contain the user's players anyway,
    # but guard against anything stray.
    incoming = {name: int(mins) for name, mins in data["minutes"].items() if name in SIM_STATE["players"]}
    team_total = sum(mins for name, mins in incoming.items() if SIM_STATE["players"][name]["team"] == team)
    if team_total > 240:
        return jsonify({"status": "error", "reason": f"Total allocated minutes ({team_total}) exceed the 240-minute team budget (5 players x 48 min). Reduce someone else's minutes first."}), 400
    for name, mins in incoming.items():
        SIM_STATE["players"][name]["minutes"] = mins
    SIM_STATE["teams"][team]["offensive_priority"] = data["offensive_priority"]
    SIM_STATE["teams"][team]["defensive_priority"] = data["defensive_priority"]
    SIM_STATE["teams"][team]["pace"] = data.get("pace", SIM_STATE["teams"][team].get("pace", "Balanced"))
    SIM_STATE["teams"][team]["shooting_willingness"] = data.get(
        "shooting_willingness", SIM_STATE["teams"][team].get("shooting_willingness", "Balanced"))
    SIM_STATE["teams"][team]["rebounding_style"] = data.get(
        "rebounding_style", SIM_STATE["teams"][team].get("rebounding_style", "Balanced"))
    SIM_STATE["teams"][team]["scoring_option"] = data.get(
        "scoring_option", SIM_STATE["teams"][team].get("scoring_option", "Balanced Attack"))
    # UPGRADE PASS: lets the user explicitly pick which player Featured
    # Scorer actually feeds, instead of it always being whichever player
    # the system decided was the rating leader. Empty string means "let
    # the game auto-pick the best available" -- the old behavior, still
    # the default and still what happens if the chosen player gets hurt,
    # traded, or benched.
    designated_star = (data.get("designated_star") or "").strip()
    if designated_star and designated_star in SIM_STATE["players"] and SIM_STATE["players"][designated_star]["team"] == team:
        SIM_STATE["teams"][team]["designated_star"] = designated_star
    else:
        SIM_STATE["teams"][team]["designated_star"] = None
    recompute_starters(team)
    return jsonify({"status": "success"})


@app.route('/api/auto_set_rotation', methods=['POST'])
def api_auto_set_rotation():
    data = request.json or {}
    bench_depth = data.get("bench_depth", "standard")
    # UPGRADE PASS: rotation_size is now optional and, when given, overrides
    # the philosophy's default player count entirely -- lets the user pick
    # any rotation size (a tight 7-man playoff rotation, playing all 15
    # guys, anything in between) instead of being stuck with whatever
    # 8/10/12-man count the chosen philosophy used to hardcode.
    rotation_size = data.get("rotation_size")
    if rotation_size is not None:
        try:
            rotation_size = max(1, min(15, int(rotation_size)))
        except (TypeError, ValueError):
            rotation_size = None
    result = auto_set_rotation(SIM_STATE["user_team"], bench_depth, rotation_size)
    SIM_STATE["teams"][SIM_STATE["user_team"]]["starters"] = {}  # let auto-build re-pick starters fresh
    recompute_starters(SIM_STATE["user_team"])
    return jsonify({"status": "success", "rotation": result})


@app.route('/api/todays_games')
def todays_games():
    """Returns the current day's matchups that haven't been resolved yet
    (either via a normal Sim Day, or already watched live) -- powers the
    Jump Into Game tab's list of games available to watch."""
    if SIM_STATE["season_simulated"] or SIM_STATE["stage"] != "regular_season":
        return jsonify({"day": SIM_STATE["current_day"], "games": []})
    day_idx = SIM_STATE["current_day"] - 1
    matchups = SIM_STATE["schedule"][day_idx] if day_idx < len(SIM_STATE["schedule"]) else []
    live_cache = SIM_STATE.get("live_prewatched", {})
    games = []
    for m in matchups:
        cache_key = f"{SIM_STATE['current_day']}|{m['home']}|{m['away']}"
        watched = cache_key in live_cache
        h, a = SIM_STATE["teams"][m["home"]], SIM_STATE["teams"][m["away"]]
        games.append({
            "home": m["home"], "away": m["away"], "watched": watched,
            "home_record": f"{h['wins']}-{h['losses']}", "away_record": f"{a['wins']}-{a['losses']}",
            "is_user_game": SIM_STATE["user_team"] in (m["home"], m["away"]),
        })
    return jsonify({"day": SIM_STATE["current_day"], "games": games})


CRUNCH_PLAYS = {
    "iso_star": {"label": "🎯 Feed the Star (Iso)", "attr": "Clutch Factor", "shot": 2},
    "three_for_win": {"label": "🏹 Three for the Win", "attr": "Three-Point", "shot": 3},
    "pick_and_roll": {"label": "🔄 Pick & Roll", "attr": "Passing Accuracy", "shot": 2},
    "post_up": {"label": "💪 Post It Up", "attr": "Post Control", "shot": 2},
}
CRUNCH_PLAY_LABELS = [{"key": k, "label": v["label"]} for k, v in CRUNCH_PLAYS.items()]


def apply_crunch_playcall(user_team, opp_team, call, box, is_home):
    """
    UPGRADE: "Jump Into Game" crunch-time mode. When a watched game the user's
    team is playing in projects to finish within 6 points, the final
    possession is handed to the human coach -- pick the play, and the outcome
    actually swings the final score (weighted by the relevant attribute of
    the best-fit player for that call), same spirit as 2K letting you draw up
    the last shot instead of just watching the box score land wherever.
    """
    play = CRUNCH_PLAYS.get(call, CRUNCH_PLAYS["iso_star"])
    roster = [p for p in team_roster(user_team) if effective_minutes(p) > 0] or team_roster(user_team)
    if not roster:
        return box
    player = max(roster, key=lambda p: p["attributes"].get(play["attr"], 60) * 0.7 + p["attributes"].get("Clutch Factor", 60) * 0.3)
    attr_val = player["attributes"].get(play["attr"], 60)
    clutch = player["attributes"].get("Clutch Factor", 60)
    success_pct = max(0.18, min(0.82, 0.38 + (attr_val - 70) * 0.009 + (clutch - 70) * 0.006))
    made = random.random() < success_pct
    pts = play["shot"] if made else 0
    stats_key = "home_stats" if is_home else "away_stats"
    score_key = "home_score" if is_home else "away_score"
    quarters_key = "home_quarters" if is_home else "away_quarters"
    st = box[stats_key].setdefault(player["name"], {"FGM": 0, "FGA": 0, "3PM": 0, "3PA": 0, "FTM": 0, "FTA": 0,
                                                      "PTS": 0, "REB": 0, "AST": 0, "STL": 0, "BLK": 0, "TOV": 0})
    st["FGA"] += 1
    if play["shot"] == 3:
        st["3PA"] += 1
    if made:
        st["FGM"] += 1
        if play["shot"] == 3:
            st["3PM"] += 1
        st["PTS"] += pts
        box[score_key] += pts
        if box[quarters_key]:
            box[quarters_key][-1] += pts
    else:
        st["TOV"] += 1 if random.random() < 0.3 else 0
    box["crunch_result"] = {
        "player": player["name"], "team": user_team, "call": play["label"], "made": made, "points": pts,
        "text": (f"🔥 {player['name']} ({user_team}) delivers on the {play['label']} call for {pts} clutch points!" if made
                 else f"❄️ {player['name']} ({user_team})'s {play['label']} attempt is off the mark. Defense holds.")
    }
    return box


GAME_PLAN_FIELDS = ("pace", "offensive_priority", "defensive_priority", "shooting_willingness", "rebounding_style", "scoring_option")


@app.route('/api/watch_game', methods=['POST'])
def watch_game():
    """Simulates one specific game from today's slate right now (instead of
    waiting for a full Sim Day) and returns a full play-by-play trace for the
    'Jump Into Game' live viewer. The result is committed to standings
    immediately; run_schedule_day() will pick up the cached box score for
    this matchup (instead of re-simulating it) once the rest of the day plays out.

    Supports an optional one-game-only 'game_plan' strategy override, and --
    when the user's own team is in a game that projects to finish within 6
    points -- pauses before locking in the result to let the human coach call
    the final possession (see apply_crunch_playcall)."""
    data = request.json or {}
    home, away = data.get("home"), data.get("away")
    crunch_call = data.get("crunch_call")
    game_plan = data.get("game_plan") or {}
    day_idx = SIM_STATE["current_day"] - 1
    matchups = SIM_STATE["schedule"][day_idx] if day_idx < len(SIM_STATE["schedule"]) else []
    m = next((mm for mm in matchups if mm["home"] == home and mm["away"] == away), None)
    if not m:
        return jsonify({"status": "error", "reason": "That matchup isn't on today's schedule."})
    cache_key = f"{SIM_STATE['current_day']}|{home}|{away}"
    live_cache = SIM_STATE.setdefault("live_prewatched", {})
    pending = SIM_STATE.setdefault("pending_crunch", {})

    if cache_key in live_cache:
        box = live_cache[cache_key]
        return jsonify({"status": "success", "box": box, "events": build_play_by_play(home, away, box)})

    if cache_key in pending and crunch_call:
        info = pending.pop(cache_key)
        box = apply_crunch_playcall(info["user_team"], info["opp_team"], crunch_call, info["box"], info["is_home"])
        record_regular_result(m, box)
        live_cache[cache_key] = box
        events = build_play_by_play(home, away, box)
        return jsonify({"status": "success", "box": box, "events": events, "crunch_result": box.get("crunch_result")})

    user_team = SIM_STATE["user_team"]
    orig_cfg = None
    if game_plan and user_team in (home, away):
        cfg = SIM_STATE["teams"][user_team]
        orig_cfg = {k: cfg.get(k) for k in GAME_PLAN_FIELDS}
        for k, v in game_plan.items():
            if k in GAME_PLAN_FIELDS and v:
                cfg[k] = v
    box = simulate_game(home, away, False)
    if orig_cfg:
        SIM_STATE["teams"][user_team].update(orig_cfg)

    margin = abs(box["home_score"] - box["away_score"])
    if margin <= 6 and user_team in (home, away):
        pending[cache_key] = {"box": box, "user_team": user_team,
                               "opp_team": away if user_team == home else home, "is_home": user_team == home}
        return jsonify({"status": "crunch_choice_needed", "plays": CRUNCH_PLAY_LABELS, "preview": {
            "home_team": home, "away_team": away, "home_score": box["home_score"], "away_score": box["away_score"],
        }, "box": box, "events": build_play_by_play(home, away, box)})

    record_regular_result(m, box)
    live_cache[cache_key] = box
    events = build_play_by_play(home, away, box)
    return jsonify({"status": "success", "box": box, "events": events})


@app.route('/api/live_timeout', methods=['POST'])
def live_timeout():
    """
    UPGRADE: a called timeout used to just be a flavor line + a small fatigue
    tick. It now surfaces a real coach's-eye view of the team that called it --
    who's on the floor, how gassed they are, and what they're doing this
    season -- plus, if it's the user's own team, lets them make a substitution
    or a strategy change right from the timeout panel (applied through the
    same safe rotation/gameplan path as the Team Management screen, so it
    can't corrupt a game whose result is already locked in -- see the
    engineering note on watchLiveGame in the frontend for why).
    """
    data = request.json or {}
    home, away, side = data.get("home"), data.get("away"), data.get("side")
    cache_key = f"{SIM_STATE['current_day']}|{home}|{away}"
    timeouts = SIM_STATE.setdefault("live_timeouts", {})
    used = timeouts.get(cache_key, {"home": 0, "away": 0})
    if used.get(side, 0) >= 2:
        return jsonify({"status": "error", "reason": "No timeouts remaining for that team."})
    used[side] = used.get(side, 0) + 1
    timeouts[cache_key] = used
    team_name = home if side == "home" else away
    for p in team_roster(team_name):
        if effective_minutes(p) > 0:
            p["fatigue"] = clamp(p.get("fatigue", 0) - 6, 0, 100)

    team_cfg = SIM_STATE["teams"].get(team_name, {})
    starters = team_cfg.get("starters", {})
    starter_names = set(starters.values())
    roster = [p for p in team_roster(team_name) if not p.get("retired")]

    def player_card(p):
        gp = (p.get("stats") or {}).get("GP", 0) or 1
        s = p.get("stats") or {}
        return {
            "name": p["name"], "position": p["position"], "rating": p["rating"],
            "fatigue": round(clamp(p.get("fatigue", 0), 0, 100), 1),
            "ppg": round(s.get("PTS", 0) / gp, 1), "rpg": round(s.get("REB", 0) / gp, 1),
            "apg": round(s.get("AST", 0) / gp, 1), "injury": bool(p.get("injury")),
        }

    on_court = [player_card(p) for p in roster if p["name"] in starter_names]
    bench = [player_card(p) for p in roster if p["name"] not in starter_names]

    return jsonify({
        "status": "success", "timeouts_left": 2 - used[side],
        "text": f"⏱ {team_name} calls a timeout -- the bench gets a breather.",
        "team": team_name, "is_user_team": team_name == SIM_STATE["user_team"],
        "on_court": on_court, "bench": bench,
        "gameplan": {
            "offensive_priority": team_cfg.get("offensive_priority", "Balanced"),
            "defensive_priority": team_cfg.get("defensive_priority", "Man-to-Man"),
            "pace": team_cfg.get("pace", "Balanced"),
            "scoring_option": team_cfg.get("scoring_option", "Balanced Attack"),
        },
    })


@app.route('/api/edit_draft_prospect', methods=['POST'])
def api_edit_draft_prospect():
    data = request.json or {}
    result = edit_draft_prospect(data.get("old_name"), data.get("new_name"), data.get("new_position"))
    return jsonify(result)


@app.route('/api/scout_top_prospects', methods=['POST'])
def api_scout_top_prospects():
    data = request.json or {}
    n = safe_int(data.get("n"), 5)
    result = scout_top_prospects(SIM_STATE["user_team"], n)
    return jsonify(result)


@app.route('/api/scout_prospect', methods=['POST'])
def api_scout_prospect():
    data = request.json or {}
    name = data.get("name")
    points = data.get("points", 2)
    if not name:
        return jsonify({"success": False, "reason": "No prospect specified."})
    result = scout_prospect(SIM_STATE["user_team"], name, points)
    return jsonify(result)


@app.route('/api/fire_coach', methods=['POST'])
def api_fire_coach():
    result = fire_coach(SIM_STATE["user_team"])
    return jsonify(result)


@app.route('/api/hire_coach', methods=['POST'])
def api_hire_coach():
    data = request.json or {}
    result = hire_coach(SIM_STATE["user_team"], data.get("candidate_id"))
    return jsonify(result)


# UPGRADE: "Untradeable" flag -- lets a GM lock franchise cornerstones so a
# fat-fingered trade builder click can't accidentally send them away. Only
# the human GM's own roster can be flagged (AI teams manage their own
# rosters and don't need this UI), and the flag is enforced server-side in
# validate_trade_legality for every trade path, not just this toggle.
@app.route('/api/toggle_untradeable', methods=['POST'])
def api_toggle_untradeable():
    data = request.json or {}
    player_name = data.get("player_name")
    user_team = SIM_STATE["user_team"]
    p = SIM_STATE["players"].get(player_name)
    if not p or p.get("team") != user_team:
        return jsonify({"success": False, "reason": "That player isn't on your roster."})
    locked = SIM_STATE["untradeable"].setdefault(user_team, [])
    if player_name in locked:
        locked.remove(player_name)
        flagged = False
    else:
        if player_name in SIM_STATE.get("trade_block", []):
            return jsonify({"success": False, "reason": f"{player_name} is on the trade block -- take them off the block first."})
        locked.append(player_name)
        flagged = True
    return jsonify({"success": True, "player_name": player_name, "untradeable": flagged})


def compute_rumored_trade_block(team_name, starter_names, untouchable_names):
    """AI teams don't maintain an explicit trade block the way the user's
    team does, but that shouldn't mean opposing rosters are a total black
    box -- this reads the same signals a real front office scout would use
    (buried on the bench, unhappy, or on an expiring deal) to surface a
    'rumored' interest list. Deliberately excludes anything on that team's
    real untouchables list or their starters, and is capped at 3 names so
    it reads as a scouting hint, not a guaranteed offer."""
    roster = team_roster(team_name)
    candidates = []
    for p in roster:
        if p["name"] in starter_names or p["name"] in untouchable_names:
            continue
        morale = p.get("morale", 70)
        years_left = (p.get("contract") or {}).get("years_left") or 0
        expiring = years_left <= 1
        if morale >= 55 and not expiring:
            continue
        score = (100 - morale) + (25 if expiring else 0) - p.get("minutes", 0) * 0.1
        candidates.append((score, p["name"]))
    candidates.sort(key=lambda x: -x[0])
    return [name for _, name in candidates[:3]]


@app.route('/api/team_intel')
def api_team_intel():
    """Everything for the 2K-style Team Intel screen in one call: starting
    lineup, 6th man, untouchables (server's real trade-value read, not a
    client-side guess), injuries, and expiring contracts. Trade block and
    target list are only meaningful for the user's own team -- AI teams
    don't publish either."""
    team = request.args.get("team", "")
    if team not in SIM_STATE["teams"]:
        return jsonify({"success": False, "reason": "Unknown team."})
    roster = team_roster(team)
    starters_map = SIM_STATE["teams"][team].get("starters", {}) or {}
    starter_names = set(starters_map.values()) if isinstance(starters_map, dict) else set(starters_map)
    starters = [{"slot": slot, "name": name} for slot, name in starters_map.items()] if isinstance(starters_map, dict) else []
    non_starters = sorted([p for p in roster if p["name"] not in starter_names], key=lambda p: -p.get("minutes", 0))
    sixth_man = non_starters[0]["name"] if non_starters else None
    # BUGFIX: this used to sort by SIM_STATE["players"][n]["rating"] directly,
    # which threw a 500 (and crashed the Team Intel/Compare screens with a
    # non-JSON error page) if an untouchable name was ever briefly stale
    # relative to the roster. .get()-based lookups make this resilient
    # instead of crashing the whole endpoint over one bad name.
    untouchables = sorted(
        [n for n in team_untouchables(team) if n in SIM_STATE["players"]],
        key=lambda n: -SIM_STATE["players"][n].get("rating", 0)
    )
    injuries = [p["name"] for p in roster if p.get("injury")]
    expiring = [p["name"] for p in roster
                if p.get("contract") and (p["contract"].get("years_left") or 0) <= 1]
    is_user_team = team == SIM_STATE["user_team"]
    t = SIM_STATE["teams"][team]

    # UPGRADE: head-to-head season series vs the user's team -- this data
    # (regular_season_games) already existed but nothing ever surfaced the
    # matchup history between two specific teams.
    h2h = {"wins": 0, "losses": 0}
    if not is_user_team:
        for g in SIM_STATE.get("regular_season_games", []):
            teams_in_game = {g.get("home_team"), g.get("away_team")}
            if teams_in_game == {team, SIM_STATE["user_team"]}:
                user_is_home = g.get("home_team") == SIM_STATE["user_team"]
                user_score = g["home_score"] if user_is_home else g["away_score"]
                opp_score = g["away_score"] if user_is_home else g["home_score"]
                if user_score > opp_score:
                    h2h["wins"] += 1
                else:
                    h2h["losses"] += 1

    return jsonify({
        "success": True, "team": team, "conference": t.get("conference"),
        "wins": t.get("wins", 0), "losses": t.get("losses", 0),
        "streak": t.get("streak", 0),
        "chemistry": t.get("chemistry", 65.0),
        "starters": starters, "sixth_man": sixth_man,
        "untouchables": untouchables, "injuries": injuries, "expiring_contracts": expiring,
        "trade_block": SIM_STATE.get("trade_block", []) if is_user_team else compute_rumored_trade_block(team, starter_names, set(untouchables)),
        "trade_block_is_rumored": not is_user_team,
        "target_list": SIM_STATE["trade_targets"].get(team, []) if is_user_team else [],
        "is_user_team": is_user_team,
        "head_to_head": h2h,
    })


@app.route('/api/toggle_trade_target', methods=['POST'])
def api_toggle_trade_target():
    """2K-style trade watchlist -- flag a player on another roster as
    someone you're tracking, independent of actually building an offer."""
    data = request.json or {}
    player_name = data.get("player_name")
    user_team = SIM_STATE["user_team"]
    p = SIM_STATE["players"].get(player_name)
    if not p or not p.get("team") or p.get("team") == user_team:
        return jsonify({"success": False, "reason": "That player isn't on another team's roster."})
    targets = SIM_STATE["trade_targets"].setdefault(user_team, [])
    if player_name in targets:
        targets.remove(player_name)
        watching = False
    else:
        targets.append(player_name)
        watching = True
    return jsonify({"success": True, "player_name": player_name, "watching": watching})


# UPGRADE: "Trade block" -- the flip side of untradeable. Marks a player as
# available so AI teams proactively call about them (see the boosted
# call_chance and block_candidates targeting bias in run_schedule_day /
# generate_ai_trade_offer above).
@app.route('/api/toggle_trade_block', methods=['POST'])
def api_toggle_trade_block():
    data = request.json or {}
    player_name = data.get("player_name")
    user_team = SIM_STATE["user_team"]
    p = SIM_STATE["players"].get(player_name)
    if not p or p.get("team") != user_team:
        return jsonify({"success": False, "reason": "That player isn't on your roster."})
    block = SIM_STATE.setdefault("trade_block", [])
    if player_name in block:
        block.remove(player_name)
        on_block = False
    else:
        # A player can't be both untradeable and on the block at the same time.
        locked = SIM_STATE["untradeable"].get(user_team, [])
        if player_name in locked:
            return jsonify({"success": False, "reason": f"{player_name} is flagged untradeable -- unlock them first."})
        block.append(player_name)
        on_block = True
    return jsonify({"success": True, "player_name": player_name, "on_trade_block": on_block})


@app.route('/api/choose_team', methods=['POST'])
def api_choose_team():
    data = request.json or {}
    result = choose_user_team(data.get("team"))
    return jsonify(result)


@app.route('/api/relocate_team', methods=['POST'])
def api_relocate_team():
    data = request.json or {}
    result = relocate_team(data.get("new_name"))
    return jsonify(result)


@app.route('/api/run_expansion_draft', methods=['POST'])
def api_run_expansion_draft():
    result = run_expansion_draft()
    return jsonify(result)


@app.route('/api/set_starter', methods=['POST'])
def api_set_starter():
    data = request.json or {}
    position = data.get("position")
    name = data.get("name")
    result = set_manual_starter(SIM_STATE["user_team"], position, name)
    return jsonify(result)


@app.route('/api/sim_day', methods=['POST'])
def sim_day():
    run_schedule_day()
    paused = bool(SIM_STATE["pending_offer"])
    return jsonify({"status": "success", "paused_for_offer": paused})


@app.route('/api/sim_week', methods=['POST'])
def sim_week():
    for _ in range(7):
        if SIM_STATE["season_simulated"] or SIM_STATE["pending_offer"]:
            break
        if run_schedule_day():
            break
    paused = bool(SIM_STATE["pending_offer"])
    return jsonify({"status": "success", "paused_for_offer": paused})


@app.route('/api/sim_season', methods=['POST'])
def sim_season():
    while not SIM_STATE["season_simulated"] and not SIM_STATE["pending_offer"]:
        if run_schedule_day():
            break
    paused = bool(SIM_STATE["pending_offer"])
    return jsonify({"status": "success", "paused_for_offer": paused})


@app.route('/api/sim_to_day', methods=['POST'])
def sim_to_day():
    """Simulate forward through a target day -- powers the 2K-style calendar
    where you click any future box and say "sim to here"."""
    data = request.json or {}
    target_day = safe_int(data.get("day"), SIM_STATE["current_day"])
    while (SIM_STATE["current_day"] <= target_day and not SIM_STATE["season_simulated"]
           and not SIM_STATE["pending_offer"]):
        if run_schedule_day():
            break
    paused = bool(SIM_STATE["pending_offer"])
    return jsonify({"status": "success", "paused_for_offer": paused})


def conference_seed_order(conference_name):
    """Full win-pct/point-diff/wins ranked order of every team in a conference,
    best record first. Factored out so both the play-in tournament (needs
    seeds 7-10) and the final bracket (needs 1-8) share one ranking."""
    conf_teams = [(name, d) for name, d in SIM_STATE["teams"].items() if d["conference"] == conference_name]

    def seed_key(item):
        _, d = item
        gp = d["wins"] + d["losses"]
        win_pct = d["wins"] / gp if gp > 0 else 0.0
        point_diff = d.get("points_for", 0) - d.get("points_against", 0)
        return (win_pct, point_diff, d["wins"])

    ranked = sorted(conf_teams, key=seed_key, reverse=True)
    return [t[0] for t in ranked]


def seed_conference_bracket_from_list(seeds, conference_name):
    """Standard 8-team static bracket (1v8, 4v5, 2v7, 3v6) built from an
    explicit, already-resolved list of 8 seeded teams (seeds[0] = #1 seed)."""
    pairs = [(0, 7), (3, 4), (1, 6), (2, 5)]
    return [{"team1": seeds[a], "team2": seeds[b], "games": [], "winner": None, "series": [0, 0],
             "conference": conference_name} for a, b in pairs]


def seed_conference_bracket(conference_name):
    """Legacy direct top-8-by-record seeding, kept for any code path that still
    wants a bracket without running the play-in tournament first."""
    seeds = conference_seed_order(conference_name)[:8]
    return seed_conference_bracket_from_list(seeds, conference_name)


# ==========================================
# PLAY-IN TOURNAMENT (7th-10th seeds per conference)
# ==========================================
def begin_play_in():
    """
    UPGRADE: NBA-style Play-In Tournament. Instead of the 7th-8th seeds locking
    in straight from the regular-season table, the 7th-10th place teams in each
    conference now play it out: (7) vs (8) with the winner claiming the 7 seed
    outright; (9) vs (10) with the loser eliminated; then the (7)v(8) loser
    hosts the (9)v(10) winner for the final 8 seed. Seeds 1-6 lock in directly,
    same as the real league.
    """
    pi = {"active": True, "complete": False}
    for conf in ("East", "West"):
        order = conference_seed_order(conf)
        top6 = order[:6]
        seed7, seed8, seed9, seed10 = order[6], order[7], order[8], order[9]
        pi[conf] = {
            "locked_top6": top6,
            "seed7": seed7, "seed8": seed8, "seed9": seed9, "seed10": seed10,
            "game1": {"team1": seed7, "team2": seed8, "winner": None, "box": None,
                      "label": "7-8 Game (winner = #7 seed)"},
            "game2": {"team1": seed9, "team2": seed10, "winner": None, "box": None,
                      "label": "9-10 Game (loser eliminated)"},
            "game3": {"team1": None, "team2": None, "winner": None, "box": None,
                      "label": "Final Play-In Game (winner = #8 seed)"},
            "final_7_seed": None, "final_8_seed": None, "complete": False,
        }
    SIM_STATE["play_in"] = pi
    SIM_STATE["playoffs_started"] = False
    SIM_STATE["stage"] = "play_in"


def _play_in_winner(box, team1, team2):
    return team1 if box["home_score"] > box["away_score"] else team2


def simulate_play_in_games():
    """Advances the play-in tournament as far as it can go in one call: plays
    the independent 7v8 and 9v10 games, then -- once both are known -- the
    final 7v8-loser-vs-9v10-winner game, for both conferences. Once both
    conferences have resolved their 7/8 seeds, the real playoff bracket
    auto-seeds itself, exactly like the regular-season-to-playoffs handoff."""
    pi = SIM_STATE["play_in"]
    for conf in ("East", "West"):
        c = pi.get(conf)
        if not c or c["complete"]:
            continue
        if c["game1"]["winner"] is None:
            box = simulate_game(c["game1"]["team1"], c["game1"]["team2"], True)
            c["game1"]["box"] = box
            c["game1"]["winner"] = _play_in_winner(box, c["game1"]["team1"], c["game1"]["team2"])
        if c["game2"]["winner"] is None:
            box = simulate_game(c["game2"]["team1"], c["game2"]["team2"], True)
            c["game2"]["box"] = box
            c["game2"]["winner"] = _play_in_winner(box, c["game2"]["team1"], c["game2"]["team2"])
        if c["game1"]["winner"] and c["game2"]["winner"] and c["game3"]["winner"] is None:
            g1_loser = c["game1"]["team2"] if c["game1"]["winner"] == c["game1"]["team1"] else c["game1"]["team1"]
            c["game3"]["team1"] = g1_loser
            c["game3"]["team2"] = c["game2"]["winner"]
            box = simulate_game(c["game3"]["team1"], c["game3"]["team2"], True)
            c["game3"]["box"] = box
            c["game3"]["winner"] = _play_in_winner(box, c["game3"]["team1"], c["game3"]["team2"])
        if c["game1"]["winner"] and c["game3"]["winner"]:
            c["final_7_seed"] = c["game1"]["winner"]
            c["final_8_seed"] = c["game3"]["winner"]
            c["complete"] = True

    if pi.get("East", {}).get("complete") and pi.get("West", {}).get("complete"):
        pi["complete"] = True
        pi["active"] = False
        begin_playoffs()
    return pi


def begin_playoffs():
    # East and West brackets grouped together in round 1 -- because advance_round()
    # pairs adjacent winners, this keeps each conference separate through the
    # conference finals, meeting only in the Finals (round 4), like the real NBA.
    #
    # If the play-in tournament has resolved seeds 7/8, use those; otherwise
    # (e.g. this is called directly without a play-in stage) fall back to a
    # plain top-8-by-record seeding.
    pi = SIM_STATE.get("play_in") or {}
    matchups = []
    for conf in ("East", "West"):
        c = pi.get(conf)
        if c and c.get("complete"):
            full_seeds = c["locked_top6"] + [c["final_7_seed"], c["final_8_seed"]]
            matchups += seed_conference_bracket_from_list(full_seeds, conf)
        else:
            matchups += seed_conference_bracket(conf)
    SIM_STATE["playoff_bracket"]["1"] = matchups
    SIM_STATE["playoffs_started"] = True
    SIM_STATE["current_round"] = 1
    SIM_STATE["round_completed"] = False
    SIM_STATE["stage"] = "playoffs"


@app.route('/api/start_playoffs', methods=['POST'])
def start_playoffs():
    # Kept for backward compatibility; the postseason now auto-seeds itself the
    # moment the 82-game regular season finishes (see run_schedule_day) by
    # kicking off the play-in tournament first, so this only matters if
    # something calls it again -- it's a harmless no-op / manual fallback.
    if not SIM_STATE["playoffs_started"] and not SIM_STATE.get("play_in", {}).get("active"):
        begin_play_in()
    return jsonify({"status": "success"})


@app.route('/api/watch_play_in_game', methods=['POST'])
def api_watch_play_in_game():
    """
    UPGRADE: Play-in tournament game speed/replay. Previously simulate_play_in_games()
    resolved every play-in matchup instantly with no presentation at all. This lets
    the user "Jump Into" one specific play-in game (game1/game2/game3, one conference)
    through the exact same simulate_game() + build_play_by_play() pipeline -- and the
    same live-viewer UI -- used for every regular-season game, instead of a separate,
    inconsistent presentation just for the play-in round.
    """
    data = request.json or {}
    conf = data.get("conference")
    game_key = data.get("game_key")
    pi = SIM_STATE.get("play_in") or {}
    c = pi.get(conf)
    if not c or game_key not in ("game1", "game2", "game3"):
        return jsonify({"status": "error", "reason": "That play-in game isn't available."})
    g = c[game_key]
    if g["winner"] is not None:
        box = g["box"]
        return jsonify({"status": "success", "box": box, "events": build_play_by_play(g["team1"], g["team2"], box)})
    if game_key == "game3" and not (c["game1"]["winner"] and c["game2"]["winner"]):
        return jsonify({"status": "error", "reason": "The 7-8 and 9-10 games must finish before the final play-in game."})
    if game_key == "game3" and not g["team1"]:
        g1_loser = c["game1"]["team2"] if c["game1"]["winner"] == c["game1"]["team1"] else c["game1"]["team1"]
        g["team1"] = g1_loser
        g["team2"] = c["game2"]["winner"]
    if not g["team1"] or not g["team2"]:
        return jsonify({"status": "error", "reason": "That play-in game isn't set up yet."})

    box = simulate_game(g["team1"], g["team2"], True)
    g["box"] = box
    g["winner"] = _play_in_winner(box, g["team1"], g["team2"])

    if c["game1"]["winner"] and c["game3"]["winner"] and not c["complete"]:
        c["final_7_seed"] = c["game1"]["winner"]
        c["final_8_seed"] = c["game3"]["winner"]
        c["complete"] = True
    if pi.get("East", {}).get("complete") and pi.get("West", {}).get("complete"):
        pi["complete"] = True
        pi["active"] = False
        begin_playoffs()

    events = build_play_by_play(g["team1"], g["team2"], box)
    return jsonify({"status": "success", "box": box, "events": events})


@app.route('/api/simulate_play_in', methods=['POST'])
def api_simulate_play_in():
    if not SIM_STATE.get("play_in", {}).get("active"):
        return jsonify({"status": "error", "reason": "No play-in tournament is currently active."})
    simulate_play_in_games()
    return jsonify({"status": "success", "play_in": SIM_STATE["play_in"]})


def advance_playoff_round():
    """Push the bracket to the next round (or close out the Finals). Called
    automatically the instant a round finishes so the bracket never sits
    stuck waiting on a manual click."""
    r = str(SIM_STATE["current_round"])
    matchups = SIM_STATE["playoff_bracket"][r]
    winners = [m["winner"] for m in matchups]

    if SIM_STATE["current_round"] < 4:
        next_r = str(SIM_STATE["current_round"] + 1)
        new_matchups = []
        for i in range(0, len(winners), 2):
            new_matchups.append({"team1": winners[i], "team2": winners[i+1], "games": [], "winner": None, "series": [0, 0]})
        SIM_STATE["playoff_bracket"][next_r] = new_matchups
        SIM_STATE["current_round"] += 1
        SIM_STATE["round_completed"] = False
    else:
        SIM_STATE["playoffs_complete"] = True
        SIM_STATE["stage"] = "offseason"
        record_league_history()


@app.route('/api/simulate_playoff_games', methods=['POST'])
def simulate_playoff_games():
    r = str(SIM_STATE["current_round"])
    matchups = SIM_STATE["playoff_bracket"][r]

    for m in matchups:
        if m["winner"] is None:
            game_num = m["series"][0] + m["series"][1] + 1
            home = m["team1"] if game_num in [1, 2, 5, 7] else m["team2"]
            away = m["team2"] if game_num in [1, 2, 5, 7] else m["team1"]

            box = simulate_game(home, away, True)
            m["games"].append(box)

            if box["home_score"] > box["away_score"]:
                if home == m["team1"]: m["series"][0] += 1
                else: m["series"][1] += 1
            else:
                if away == m["team1"]: m["series"][0] += 1
                else: m["series"][1] += 1

            if m["series"][0] == 4: m["winner"] = m["team1"]
            elif m["series"][1] == 4: m["winner"] = m["team2"]

    round_complete = all(m["winner"] is not None for m in matchups)
    SIM_STATE["round_completed"] = round_complete
    if round_complete:
        # Auto-advance immediately -- no more waiting on a stale/hidden tab to
        # notice and offer a button. The bracket just keeps moving.
        advance_playoff_round()
    return jsonify({"status": "success"})


@app.route('/api/advance_round', methods=['POST'])
def advance_round():
    # Kept for compatibility; rounds now auto-advance on their own inside
    # simulate_playoff_games(), so this is only needed as a manual fallback.
    if SIM_STATE["round_completed"]:
        advance_playoff_round()
    return jsonify({"status": "success"})


# --- Trade endpoints ---
@app.route('/api/suggest_trade_package')
def api_suggest_trade_package():
    """2K-style 'Find a Fair Deal' -- picks a partner player at one of the
    user's needy positions, then greedily assembles an outgoing package
    (cheapest players/picks first) until the offer clears fairness."""
    team = request.args.get("team")
    partner = request.args.get("partner")
    if not team or not partner or team == partner:
        return jsonify({"success": False, "reason": "Pick a trade partner first."})

    needs = team_positional_needs(team)
    partner_roster = team_roster(partner)
    candidates = [p for p in partner_roster if p["position"] in needs]
    if not candidates:
        candidates = partner_roster
    if not candidates:
        return jsonify({"success": False, "reason": f"{partner} has nothing to offer right now."})
    target = max(candidates, key=lambda p: p["rating"])

    target_value = contextual_package_value([target["name"]], [], partner)
    user_roster = sorted((p for p in team_roster(team) if p["name"] != target["name"]),
                          key=lambda p: p["rating"])
    package_players = []
    running_value = 0.0
    for p in user_roster:
        if running_value >= target_value * 0.9:
            break
        package_players.append(p["name"])
        running_value = contextual_package_value(package_players, [], partner)
    package_picks = []
    if running_value < target_value * 0.9:
        my_picks = [pid for pid, pk in SIM_STATE["draft_picks"].items() if pk["current_team"] == team]
        for pid in sorted(my_picks, key=lambda pid: SIM_STATE["draft_picks"][pid]["round"]):
            if running_value >= target_value * 0.9:
                break
            package_picks.append(pid)
            running_value = contextual_package_value(package_players, package_picks, partner)
    if not package_players and not package_picks:
        return jsonify({"success": False, "reason": "Couldn't find a fair package -- try a different partner."})
    return jsonify({"success": True, "target_player": target["name"], "players_a": package_players,
                     "picks_a": package_picks, "need_filled": target["position"]})


@app.route('/api/team_needs')
def api_team_needs():
    team = request.args.get("team")
    if not team:
        return jsonify({"needs": []})
    return jsonify({"needs": team_positional_needs(team)})


@app.route('/api/trade_preview', methods=['POST'])
def api_trade_preview():
    """Read-only fairness meter for the trade builder -- lets the UI show a
    live 'how fair is this?' bar as the user drags assets in, before they
    commit to a formal offer."""
    data = request.json or {}
    team_b = data.get("team_b")
    players_a = data.get("players_a", [])
    picks_a = data.get("picks_a", [])
    players_b = data.get("players_b", [])
    picks_b = data.get("picks_b", [])
    protections = data.get("protections", {})
    if not team_b:
        return jsonify({"fairness_pct": 0})
    team_a = data.get("team_a") or SIM_STATE.get("user_team")
    value_a_sends = contextual_package_value(players_a, picks_a, team_b, protections)
    value_b_sends = contextual_package_value(players_b, picks_b, team_b, protections)
    fairness_pct = round(min(150.0, (value_a_sends / max(1.0, value_b_sends)) * 100), 1)

    def _salary_out(names):
        total = 0.0
        for n in names:
            p = SIM_STATE["players"].get(n)
            if p and p.get("contract"):
                total += p["contract"].get("salary", 0) or 0
        return round(total, 1)

    salary_out_a = _salary_out(players_a)
    salary_out_b = _salary_out(players_b)
    untouchables_hit = [n for n in players_b if n in team_untouchables(team_b)]
    return jsonify({
        "fairness_pct": fairness_pct, "value_sent": value_a_sends, "value_received": value_b_sends,
        "salary_out_a": salary_out_a, "salary_out_b": salary_out_b,
        "needs_a": team_positional_needs(team_a) if team_a else [],
        "needs_b": team_positional_needs(team_b),
        "grade": trade_grade_letter(fairness_pct),
        "untouchables_hit": untouchables_hit,
    })


@app.route('/api/propose_trade', methods=['POST'])
def propose_trade():
    data = request.json
    team_a = data.get("team_a")
    team_b = data.get("team_b")
    players_a = data.get("players_a", [])
    picks_a = data.get("picks_a", [])
    players_b = data.get("players_b", [])
    picks_b = data.get("picks_b", [])
    protections = data.get("protections", {})  # {pick_id: "Top-4 Protected", ...}
    tpe_id = data.get("tpe_id")  # UPGRADE: spend a banked Trade Exception instead of matching salary

    if not trade_window_open():
        return jsonify({"accepted": False, "reason": f"The trade deadline (Day {SIM_STATE.get('trade_deadline_day')}) has passed. "
                        f"Trading reopens in the offseason."})
    if not players_a and not picks_a:
        return jsonify({"accepted": False, "reason": "You must offer at least one asset."})
    if not players_b and not picks_b:
        return jsonify({"accepted": False, "reason": "You must request at least one asset."})

    result = evaluate_and_execute_trade(team_a, players_a, picks_a, team_b, players_b, picks_b, protections, tpe_id=tpe_id)
    return jsonify(result)


@app.route('/api/propose_3team_trade', methods=['POST'])
def propose_3team_trade():
    """3-and-4-team blockbuster trades. Each team in the deal sends a bundle
    of players and picks to one or more of the other teams. We validate all
    three pairings independently (each team's salary legality and roster size)
    then apply all legs atomically -- either every leg goes through or none do."""
    data = request.json or {}
    if not trade_window_open():
        return jsonify({"accepted": False, "reason": "Trade deadline has passed."})

    teams = data.get("teams", [])          # ["TeamA", "TeamB", "TeamC"]
    sends = data.get("sends", {})          # {team: {dest_team: {players:[], picks:[]}}}

    if len(teams) < 3:
        return jsonify({"accepted": False, "reason": "Need at least 3 teams."})

    # Collect every team's net incoming/outgoing
    net_players_out = {t: [] for t in teams}
    net_players_in  = {t: [] for t in teams}
    net_picks_out   = {t: [] for t in teams}
    net_picks_in    = {t: [] for t in teams}

    for sender, dests in sends.items():
        for dest, bundle in dests.items():
            for p in bundle.get("players", []):
                net_players_out[sender].append(p)
                net_players_in[dest].append(p)
            for pk in bundle.get("picks", []):
                net_picks_out[sender].append(pk)
                net_picks_in[dest].append(pk)

    # Validate each team independently
    for t in teams:
        final_size = len(team_roster(t)) - len(net_players_out[t]) + len(net_players_in[t])
        ok, msg = validate_trade_legality(t, net_players_out[t], net_picks_out[t],
                                           net_players_in[t], net_picks_in[t], final_size)
        if not ok:
            return jsonify({"accepted": False, "reason": f"[{t}] {msg}"})

    # Check at least the user's team is involved and sent something
    user_team = SIM_STATE["user_team"]
    if user_team not in teams:
        return jsonify({"accepted": False, "reason": "Your team must be in the trade."})
    if not net_players_out[user_team] and not net_picks_out[user_team]:
        return jsonify({"accepted": False, "reason": "Your team must send at least one asset."})

    # All good — apply every leg
    for sender, dests in sends.items():
        for dest, bundle in dests.items():
            if bundle.get("players") or bundle.get("picks"):
                apply_trade(sender, bundle.get("players", []), bundle.get("picks", []),
                             dest, [], [])

    log_entry = f"3-team deal: {' + '.join(teams)}"
    SIM_STATE.setdefault("trade_log", []).append({"year": SIM_STATE["year"], "day": SIM_STATE["current_day"],
                                                    "description": log_entry})
    push_news("🔁", log_entry, "trade")
    return jsonify({"accepted": True, "reason": "3-team trade completed!", "teams": teams})


@app.route('/api/scout_trade_offer', methods=['POST'])
def scout_trade_offer():
    if not trade_window_open():
        return jsonify({"offer": None, "reason": "The trade deadline has passed."})
    offer = generate_ai_trade_offer()
    SIM_STATE["pending_offer"] = offer
    return jsonify({"offer": offer})


@app.route('/api/respond_offer', methods=['POST'])
def respond_offer():
    data = request.json
    accept = data.get("accept", False)
    offer = SIM_STATE.get("pending_offer")
    if not offer:
        return jsonify({"status": "no_offer"})

    if not accept:
        SIM_STATE["pending_offer"] = None
        return jsonify({"status": "declined"})

    # "Pass the sim": re-validate cap/roster legality for both teams at the moment
    # of acceptance (rosters may have shifted since the offer was scouted) before
    # actually executing it.
    from_team, to_team = offer["from_team"], offer["to_team"]
    offer_players, offer_picks = offer["offer_players"], offer["offer_picks"]
    wants_players, wants_picks = offer["wants_players"], offer["wants_picks"]

    roster_from = team_roster(from_team)
    roster_to = team_roster(to_team)
    size_from_after = len(roster_from) - len(offer_players) + len(wants_players)
    size_to_after = len(roster_to) - len(wants_players) + len(offer_players)

    ok_from, msg_from = validate_trade_legality(from_team, offer_players, offer_picks, wants_players, wants_picks, size_from_after)
    ok_to, msg_to = validate_trade_legality(to_team, wants_players, wants_picks, offer_players, offer_picks, size_to_after)
    if not (ok_from and ok_to):
        SIM_STATE["pending_offer"] = None
        return jsonify({"status": "rejected", "reason": msg_from or msg_to})

    apply_trade(from_team, offer_players, offer_picks, to_team, wants_players, wants_picks)
    SIM_STATE["pending_offer"] = None
    return jsonify({"status": "accepted"})


@app.route('/api/counter_offer', methods=['POST'])
def api_counter_offer():
    """Negotiate: ask the AI team to sweeten their current offer.
    They'll add their cheapest available pick if they have one, or drop
    one of the players they're asking for if the request is too steep."""
    offer = SIM_STATE.get("pending_offer")
    if not offer:
        return jsonify({"success": False, "reason": "No pending offer to counter."})

    from_team = offer["from_team"]
    ai_roster = team_roster(from_team)
    ai_picks = [pk for pk in SIM_STATE.get("draft_picks", {}).values()
                if pk.get("current_team") == from_team and pk.get("year", 9999) >= SIM_STATE["year"]]

    sweetened = False
    msg_parts = []

    # Option A: AI throws in their cheapest available pick
    if ai_picks:
        cheapest_pick = sorted(ai_picks, key=lambda p: p.get("value", 0))[0]
        if cheapest_pick["id"] not in offer["offer_picks"]:
            offer["offer_picks"].append(cheapest_pick["id"])
            label = f"{cheapest_pick.get('year','?')} {cheapest_pick.get('round','?')}R pick"
            msg_parts.append(f"added their {label}")
            sweetened = True

    # Option B: If the ask is steep (>1 player wanted), drop the cheapest wanted player
    if not sweetened and len(offer["wants_players"]) > 1:
        wanted_vals = [(n, contextual_player_value(SIM_STATE["players"][n], from_team))
                       for n in offer["wants_players"] if n in SIM_STATE["players"]]
        if wanted_vals:
            drop_name = min(wanted_vals, key=lambda x: x[1])[0]
            offer["wants_players"].remove(drop_name)
            msg_parts.append(f"dropped {drop_name} from their request")
            sweetened = True

    if sweetened:
        archetype = SIM_STATE.get("gm_archetypes", {}).get(from_team, "")
        return jsonify({
            "success": True,
            "message": f"📞 {from_team}{(' (' + archetype + ')') if archetype else ''} counter-offered: {' and '.join(msg_parts)}. Review the updated offer below."
        })
    return jsonify({"success": False, "reason": f"{from_team} won't budge — this is their final offer."})


# --- Draft endpoints ---
@app.route('/api/start_draft', methods=['POST'])
def api_start_draft():
    start_draft()
    return jsonify({"status": "success"})


@app.route('/api/draft_pick', methods=['POST'])
def api_draft_pick():
    data = request.json
    prospect_name = data.get("prospect_name")
    d = SIM_STATE["draft"]
    if not d["active"] or d["index"] >= len(d["order"]):
        return jsonify({"status": "error", "reason": "Draft is not active."})

    pick_id = d["order"][d["index"]]
    pk = SIM_STATE["draft_picks"][pick_id]
    if pk["current_team"] != SIM_STATE["user_team"]:
        return jsonify({"status": "error", "reason": "It is not your turn to pick."})

    prospect = next((p for p in SIM_STATE["draft_class"] if p["name"] == prospect_name), None)
    if not prospect:
        return jsonify({"status": "error", "reason": "Prospect not available."})

    # UPGRADE: Draft-day scouting lock warning. Drafting a prospect with (near)
    # zero scout points invested is a pure fog gamble -- his true rating/
    # potential are still hidden behind wide projection ranges. Warn once and
    # require an explicit confirm before locking the pick in, instead of
    # silently letting a GM blind-pick a total unknown.
    invested = SIM_STATE["scouting"]["invested"].get(SIM_STATE["user_team"], {}).get(prospect_name, 0)
    if invested < 1 and not data.get("confirm"):
        return jsonify({"status": "warning", "reason": f"{prospect_name} has barely been scouted (0 pts invested) -- "
                        f"his true rating and potential are still almost entirely hidden. Draft him anyway?",
                        "requires_confirm": True})

    execute_draft_pick(prospect)
    advance_draft()
    return jsonify({"status": "success"})


# --- Free agency endpoints ---
@app.route('/api/sign_free_agent', methods=['POST'])
def api_sign_free_agent():
    data = request.json
    name = data.get("name")
    offer_salary = data.get("offer_salary")
    result = submit_user_fa_offer(name, offer_salary=offer_salary)
    return jsonify(result)


@app.route('/api/sign_two_way', methods=['POST'])
def api_sign_two_way():
    data = request.json or {}
    name = data.get("name")
    result = sign_free_agent(name, SIM_STATE["user_team"], two_way=True)
    if result.get("success"):
        recompute_starters(SIM_STATE["user_team"])
    return jsonify(result)


@app.route('/api/convert_two_way', methods=['POST'])
def api_convert_two_way():
    data = request.json or {}
    result = convert_two_way_to_standard(data.get("name"))
    if result.get("success"):
        recompute_starters(SIM_STATE["user_team"])
    return jsonify(result)


@app.route('/api/run_combine_drill', methods=['POST'])
def api_run_combine_drill():
    data = request.json or {}
    result = run_combine_drill(
        SIM_STATE["user_team"],
        data.get("prospect_name"),
        data.get("drill_name"),
    )
    return jsonify(result)


@app.route('/api/g_league_stats')
def api_g_league_stats():
    user_team = SIM_STATE["user_team"]
    two_ways = [p for p in SIM_STATE["players"].values()
                if p.get("two_way") and p.get("team") == user_team]
    result = []
    for p in two_ways:
        gl = SIM_STATE["g_league_stats"].get(p["name"], {})
        gp = gl.get("GP", 0)
        result.append({
            "name": p["name"], "position": p["position"], "rating": p["rating"],
            "GP": gp,
            "PPG": round(gl.get("PTS", 0) / max(1, gp), 1),
            "RPG": round(gl.get("REB", 0) / max(1, gp), 1),
            "APG": round(gl.get("AST", 0) / max(1, gp), 1),
            "xp_banked": gl.get("xp_banked", 0),
        })
    return jsonify({"success": True, "players": result})


@app.route('/api/call_up', methods=['POST'])
def api_call_up():
    data = request.json or {}
    result = call_up_two_way(data.get("name"))
    if result.get("success"):
        recompute_starters(SIM_STATE["user_team"])
    return jsonify(result)


@app.route('/api/upgrade_facility', methods=['POST'])
def api_upgrade_facility():
    data = request.json or {}
    dept = data.get("dept")
    user_team = SIM_STATE["user_team"]
    if dept not in FACILITY_DEPTS:
        return jsonify({"success": False, "reason": "Unknown department."})
    fac = SIM_STATE["facilities"].setdefault(user_team, {dept: 1 for dept in FACILITY_DEPTS})
    current_level = fac.get(dept, 1)
    if current_level >= 5:
        return jsonify({"success": False, "reason": f"{dept} is already at max level (5)."})
    cost = FACILITY_DEPTS[dept]["cost"][current_level]  # cost to go from current_level -> current_level+1
    cap_space = SIM_STATE["teams"][user_team].get("cap_space", 0)
    if cap_space < cost:
        return jsonify({"success": False, "reason": f"Need ${cost}M cap space to upgrade {dept} (have ${cap_space}M)."})
    SIM_STATE["teams"][user_team]["cap_space"] = round(cap_space - cost, 1)
    fac[dept] = current_level + 1
    bonus_key = FACILITY_DEPTS[dept]["bonus_key"]
    new_bonus = FACILITY_BONUS[bonus_key][current_level + 1]
    push_news("🏗", f"{user_team} upgrades their {dept} facility to Level {current_level + 1}.", "general")
    return jsonify({"success": True, "dept": dept, "new_level": current_level + 1, "bonus": new_bonus})


@app.route('/api/set_arena', methods=['POST'])
def api_set_arena():
    data = request.json or {}
    user_team = SIM_STATE["user_team"]
    arena = SIM_STATE["arena"].setdefault(user_team, dict(ARENA_DEFAULTS))
    for key in ("court", "jersey_style", "nickname", "vibe"):
        if key in data:
            arena[key] = str(data[key])[:40]
    return jsonify({"success": True, "arena": arena})


@app.route('/api/resolve_bid', methods=['POST'])
def api_resolve_bid():
    data = request.json
    match = bool(data.get("match", False))
    result = resolve_bidding_war(match)
    return jsonify(result)


@app.route('/api/simulate_fa_period', methods=['POST'])
def api_simulate_fa_period():
    signed = simulate_fa_period()
    return jsonify({"status": "success", "signed_count": len(signed)})


@app.route('/api/simulate_fa_day', methods=['POST'])
def api_simulate_fa_day():
    signed = simulate_fa_day()
    return jsonify({"status": "success", "signed_count": len(signed), "signed": signed,
                     "fa_day": SIM_STATE["fa_day"], "fa_days_total": SIM_STATE["fa_days_total"]})


# --- Offseason endpoints ---
@app.route('/api/process_offseason', methods=['POST'])
def api_process_offseason():
    report = process_offseason()
    return jsonify({"status": "success", "report": report})


@app.route('/api/start_new_season', methods=['POST'])
def api_start_new_season():
    user_roster_size = len(team_roster(SIM_STATE["user_team"]))
    if user_roster_size > MAX_ROSTER:
        return jsonify({
            "status": "blocked",
            "reason": f"Your roster has {user_roster_size} players, but the league limit is {MAX_ROSTER}. "
                      f"Waive {user_roster_size - MAX_ROSTER} player(s) in Team Management before the regular season can begin."
        })
    start_new_season()
    return jsonify({"status": "success"})


@app.route('/api/waive_player', methods=['POST'])
def api_waive_player():
    data = request.json or {}
    name = data.get("name")
    p = SIM_STATE["players"].get(name)
    if not p or p.get("team") != SIM_STATE["user_team"]:
        return jsonify({"success": False, "reason": "You can only waive a player on your own roster."})
    result = waive_player(name)
    return jsonify(result)


# ==========================================================
# UPGRADE BATCH 2 -- API routes
# ==========================================================

@app.route('/api/set_jersey_number', methods=['POST'])
def api_set_jersey_number():
    data = request.json or {}
    result = set_jersey_number(data.get("name"), data.get("number"))
    return jsonify(result)


@app.route('/api/set_player_nickname', methods=['POST'])
def api_set_player_nickname():
    data = request.json or {}
    name = data.get("name")
    p = SIM_STATE["players"].get(name)
    if not p or p.get("team") != SIM_STATE["user_team"]:
        return jsonify({"success": False, "reason": "You can only set nicknames for players on your own roster."})
    result = set_player_nickname(name, data.get("nickname"))
    return jsonify(result)


@app.route('/api/set_team_colors', methods=['POST'])
def api_set_team_colors():
    data = request.json or {}
    result = set_team_colors(data.get("team"), data.get("primary"))
    return jsonify(result)


@app.route('/api/injury_report')
def api_injury_report():
    return jsonify({"success": True, "report": get_injury_report()})


@app.route('/api/press_conference', methods=['POST'])
def api_press_conference():
    data = request.json or {}
    result = resolve_press_conference(data.get("response_key"))
    return jsonify(result)


@app.route('/api/fan_approval')
def api_fan_approval():
    user_team = SIM_STATE["user_team"]
    return jsonify({
        "fan_approval": SIM_STATE.get("fan_approval", {}).get(user_team, 55),
        "attendance_revenue": compute_attendance_revenue(user_team),
        "market_size": get_market_size(user_team),
    })


@app.route('/api/resolve_arbitration', methods=['POST'])
def api_resolve_arbitration():
    data = request.json or {}
    result = resolve_arbitration(data.get("player_name"), data.get("choice"))
    return jsonify(result)


@app.route('/api/news_archive')
def api_news_archive():
    """Full persistent news archive — last 500 items."""
    category = request.args.get("category")
    news = SIM_STATE.get("news", [])
    if category:
        news = [n for n in news if n.get("category") == category]
    return jsonify({"success": True, "news": news[:200], "total": len(news)})


@app.route('/api/compare_players')
def api_compare_players():
    a = request.args.get("a")
    b = request.args.get("b")
    return jsonify(compare_players(a, b))


@app.route('/api/set_trade_aggressiveness', methods=['POST'])
def api_set_trade_aggressiveness():
    data = request.json or {}
    result = set_trade_aggressiveness(data.get("value"))
    return jsonify(result)


@app.route('/api/export_stats_csv')
def api_export_stats_csv():
    from flask import Response
    csv_text = build_stats_csv()
    return Response(csv_text, mimetype="text/csv",
                     headers={"Content-Disposition": f"attachment; filename=season_stats_{SIM_STATE['year']}.csv"})


@app.route('/api/clinching_scenarios')
def api_clinching_scenarios():
    return jsonify(clinching_scenarios())


@app.route('/api/offer_extension', methods=['POST'])
def api_offer_extension():
    data = request.json or {}
    result = offer_extension(data.get("name"), data.get("years"), data.get("salary"))
    return jsonify(result)


@app.route('/api/draft_trade', methods=['POST'])
def api_draft_trade():
    data = request.json or {}
    result = draft_trade(
        data.get("team_a"), data.get("players_a", []), data.get("picks_a", []),
        data.get("team_b"), data.get("players_b", []), data.get("picks_b", []),
    )
    return jsonify(result)


@app.route('/api/hire_assistant', methods=['POST'])
def api_hire_assistant():
    data = request.json or {}
    result = hire_assistant(SIM_STATE["user_team"], data.get("name"))
    return jsonify(result)


@app.route('/api/fire_assistant', methods=['POST'])
def api_fire_assistant():
    data = request.json or {}
    result = fire_assistant(SIM_STATE["user_team"], data.get("name"))
    return jsonify(result)


@app.route('/api/gm_trust')
def api_gm_trust():
    return jsonify({"success": True, "trust": gm_trust_snapshot()})


@app.route('/api/cap_projection')
def api_cap_projection():
    team = request.args.get("team", SIM_STATE["user_team"])
    return jsonify({"success": True, "team": team, "projection": cap_projection(team)})


@app.route('/api/rivalries')
def api_rivalries():
    team = request.args.get("team", SIM_STATE["user_team"])
    return jsonify({"success": True, "team": team, "rivalries": top_rivalries(team)})


@app.route('/api/allocate_practice_points', methods=['POST'])
def api_allocate_practice_points():
    data = request.json or {}
    result = allocate_practice_points(SIM_STATE["user_team"], data.get("player_name"), data.get("focus"), data.get("points"))
    return jsonify(result)


@app.route('/api/set_ingame_strategy', methods=['POST'])
def api_set_ingame_strategy():
    data = request.json or {}
    team = data.get("team", SIM_STATE["user_team"])
    result = set_ingame_strategy(team, data.get("defensive_scheme"), data.get("foul_when_trailing"))
    return jsonify(result)



# ==========================================================
# UPGRADE BATCH 3 -- Coaching Gameplan, Team Identity, Ladders,
# Power Rankings, POTW/COTM, Career/Triple-Double trackers, GM Dashboard
# ==========================================================

GAMEPLAN_SLIDERS = ["Pace", "Crash Glass", "Defensive Pressure", "Switch Everything",
                     "Double Team", "Zone Frequency", "Help Defense", "Transition Focus",
                     "Bench Usage", "Star Usage"]

TEAM_IDENTITIES = ["Fast Paced", "Defensive", "Small Ball", "Three Point", "Rebounding",
                    "Dynasty", "Rebuilding", "Balanced"]


def get_coaching_gameplan(team_name):
    plans = SIM_STATE.setdefault("coaching_gameplan", {})
    if team_name not in plans:
        plans[team_name] = {slider: 50 for slider in GAMEPLAN_SLIDERS}
    return plans[team_name]


def set_coaching_gameplan(team_name, slider_name, value):
    if slider_name not in GAMEPLAN_SLIDERS:
        return {"success": False, "reason": f"Unknown slider '{slider_name}'."}
    try:
        value = max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return {"success": False, "reason": "Value must be a number 0-100."}
    plan = get_coaching_gameplan(team_name)
    plan[slider_name] = value
    return {"success": True, "team": team_name, "gameplan": plan}


def compute_team_identity(team_name):
    """Derive a team's playing identity from its roster + record, cache it."""
    roster = [p for p in SIM_STATE["players"].values() if p.get("team") == team_name and not p.get("retired")]
    if not roster:
        return "Balanced"
    avg_age = sum(p["age"] for p in roster) / len(roster)
    three_rate = sum(p["tendencies"].get("3PT Rate", 0.3) for p in roster if p.get("tendencies")) / max(1, len(roster))
    reb_focus = sum(p["attributes"].get("Rebounding", 60) for p in roster) / len(roster)
    def_focus = sum(p["attributes"].get("Perimeter D", 60) + p["attributes"].get("Interior D", 60) for p in roster) / (2 * len(roster))
    team_cfg = SIM_STATE["teams"].get(team_name, {})
    wins, losses = team_cfg.get("wins", 0), team_cfg.get("losses", 0)
    win_pct = wins / max(1, wins + losses)

    scores = {
        "Three Point": three_rate * 100,
        "Defensive": def_focus,
        "Rebounding": reb_focus,
        "Fast Paced": get_coaching_gameplan(team_name).get("Pace", 50) + get_coaching_gameplan(team_name).get("Transition Focus", 50),
        "Small Ball": max(0, 100 - reb_focus),
        "Dynasty": win_pct * 130 if avg_age >= 26 else win_pct * 90,
        "Rebuilding": (100 - win_pct * 100) if avg_age <= 25 else 0,
    }
    identity = max(scores, key=scores.get)
    SIM_STATE.setdefault("team_identity", {})[team_name] = identity
    return identity


def power_rankings():
    """League-wide power rankings, blending record, point diff, and streak."""
    rows = []
    for team, cfg in SIM_STATE["teams"].items():
        wins, losses = cfg.get("wins", 0), cfg.get("losses", 0)
        gp = max(1, wins + losses)
        streak = cfg.get("streak", 0)
        score = (wins / gp) * 100 + streak * 1.5
        rows.append({"team": team, "wins": wins, "losses": losses, "streak": streak,
                      "identity": SIM_STATE.get("team_identity", {}).get(team) or compute_team_identity(team),
                      "score": round(score, 2)})
    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def _active_players():
    return [p for p in SIM_STATE["players"].values() if not p.get("retired")]


def mvp_ladder(top_n=10):
    def mvp_score(p):
        s = p["stats"]
        gp = max(1, s.get("GP", 0))
        team_wins = SIM_STATE["teams"].get(p["team"], {}).get("wins", 0)
        return (s.get("PTS", 0) + s.get("AST", 0) * 1.5 + s.get("REB", 0) * 1.2) / gp + team_wins * 0.4
    ranked = sorted([p for p in _active_players() if p["stats"].get("GP", 0) >= 3], key=mvp_score, reverse=True)[:top_n]
    return [{"rank": i + 1, "name": p["name"], "team": p["team"],
              "ppg": round(p["stats"]["PTS"] / max(1, p["stats"]["GP"]), 1),
              "apg": round(p["stats"]["AST"] / max(1, p["stats"]["GP"]), 1),
              "rpg": round(p["stats"]["REB"] / max(1, p["stats"]["GP"]), 1)} for i, p in enumerate(ranked)]


def rookie_ladder(top_n=10):
    year = SIM_STATE["year"]
    rookies = [p for p in _active_players() if p.get("draft_year") == year and p["stats"].get("GP", 0) >= 1]
    ranked = sorted(rookies, key=lambda p: p["stats"].get("PTS", 0) / max(1, p["stats"].get("GP", 1)), reverse=True)[:top_n]
    return [{"rank": i + 1, "name": p["name"], "team": p["team"],
              "ppg": round(p["stats"]["PTS"] / max(1, p["stats"]["GP"]), 1),
              "rpg": round(p["stats"]["REB"] / max(1, p["stats"]["GP"]), 1),
              "apg": round(p["stats"]["AST"] / max(1, p["stats"]["GP"]), 1)} for i, p in enumerate(ranked)]


def record_game_box_for_trackers(player_name, box):
    """Called after each simulated game with a player's box score line to
    update career highs and triple-double count. box: dict with PTS/REB/AST/STL/BLK/3PM."""
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return
    highs = p.setdefault("career_highs", {"PTS": 0, "REB": 0, "AST": 0, "STL": 0, "BLK": 0, "3PM": 0})
    new_highs = []
    for stat in highs:
        val = box.get(stat, 0)
        if val > highs[stat]:
            highs[stat] = val
            new_highs.append((stat, val))
    double_digit_cats = sum(1 for stat in ("PTS", "REB", "AST", "STL", "BLK") if box.get(stat, 0) >= 10)
    if double_digit_cats >= 3:
        p["triple_doubles"] = p.get("triple_doubles", 0) + 1
        push_news("🎯", f"{player_name} recorded a triple-double ({box.get('PTS',0)} PTS / {box.get('REB',0)} REB / {box.get('AST',0)} AST).", kind="milestone")
    if new_highs:
        best = max(new_highs, key=lambda t: t[1])
        push_news("📈", f"{player_name} set a new career high: {best[1]} {best[0]}.", kind="milestone")
    return new_highs


def evaluate_player_of_week():
    """Scans the last ~7 in-game days of team results to crown a POTW.
    Lightweight: ranks by combined per-game production this stretch using
    current cumulative stats as a proxy (good enough for a weekly headline)."""
    ranked = sorted([p for p in _active_players() if p["stats"].get("GP", 0) >= 1],
                     key=lambda p: p["stats"].get("PTS", 0) / max(1, p["stats"]["GP"])
                     + p["stats"].get("AST", 0) / max(1, p["stats"]["GP"])
                     + p["stats"].get("REB", 0) / max(1, p["stats"]["GP"]), reverse=True)
    if not ranked:
        return None
    winner = ranked[0]
    entry = {
        "week": len(SIM_STATE.get("player_of_week", [])) + 1,
        "year": SIM_STATE["year"],
        "player": winner["name"],
        "team": winner["team"],
        "line": f"{round(winner['stats']['PTS']/max(1,winner['stats']['GP']),1)} PPG / "
                f"{round(winner['stats']['REB']/max(1,winner['stats']['GP']),1)} RPG / "
                f"{round(winner['stats']['AST']/max(1,winner['stats']['GP']),1)} APG",
    }
    SIM_STATE.setdefault("player_of_week", []).append(entry)
    push_news("🌟", f"{winner['name']} named Player of the Week ({entry['line']}).", kind="award")
    return entry


def evaluate_coach_of_month():
    best_team, best_score = None, -999
    for team, cfg in SIM_STATE["teams"].items():
        wins, losses = cfg.get("wins", 0), cfg.get("losses", 0)
        score = wins - losses + cfg.get("streak", 0) * 0.5
        if score > best_score:
            best_score, best_team = score, team
    if not best_team:
        return None
    coach = SIM_STATE["teams"][best_team].get("coach", "Unknown Coach")
    entry = {"month": len(SIM_STATE.get("coach_of_month", [])) + 1, "year": SIM_STATE["year"],
              "coach": coach, "team": best_team}
    SIM_STATE.setdefault("coach_of_month", []).append(entry)
    push_news("🏅", f"{coach} ({best_team}) named Coach of the Month.", kind="award")
    return entry


def gm_dashboard(team_name):
    """One-screen summary: cap, injuries, trade offers, morale, chemistry, schedule, staff, power rank."""
    team_cfg = SIM_STATE["teams"].get(team_name, {})
    roster = [p for p in SIM_STATE["players"].values() if p.get("team") == team_name and not p.get("retired")]
    injuries = [{"name": p["name"], "injury": p["injury"]} for p in roster if p.get("injury")]
    trade_offers = [t for t in SIM_STATE.get("bidding_wars", []) if isinstance(t, dict) and t.get("team") == team_name]
    pending = SIM_STATE.get("pending_offer")
    avg_morale = round(sum(p.get("morale", 70) for p in roster) / max(1, len(roster)), 1)
    rank_row = next((r for r in power_rankings() if r["team"] == team_name), None)
    next_games = [g for g in SIM_STATE.get("regular_season_games", [])
                  if (g.get("home") == team_name or g.get("away") == team_name) and not g.get("played")][:5]
    free_agents_pending = [fa for fa in SIM_STATE.get("free_agents", []) if isinstance(fa, dict) and fa.get("interested_team") == team_name]
    return {
        "team": team_name,
        "cap_space": team_cfg.get("cap_space"),
        "wins": team_cfg.get("wins", 0),
        "losses": team_cfg.get("losses", 0),
        "power_rank": rank_row["rank"] if rank_row else None,
        "identity": SIM_STATE.get("team_identity", {}).get(team_name) or compute_team_identity(team_name),
        "injuries": injuries,
        "trade_offers_count": len(trade_offers),
        "pending_offer": bool(pending),
        "owner_mandate": SIM_STATE.get("owner_mandates", {}).get(team_name) if isinstance(SIM_STATE.get("owner_mandates"), dict) else team_cfg.get("owner_mandate"),
        "avg_morale": avg_morale,
        "fan_approval": SIM_STATE.get("fan_approval", {}).get(team_name, 55),
        "upcoming_games": next_games,
        "coach": team_cfg.get("coach"),
        "assistants": team_cfg.get("assistants", []),
        "pending_free_agents": len(free_agents_pending),
        "roster_size": len(roster),
    }


def league_leaders(category="PTS", top_n=15):
    """Redesigned league leaders board -- supports per-game categories plus
    shooting percentages, sorted correctly for each."""
    pct_cats = {"FG%": ("FGM", "FGA"), "3P%": ("3PM", "3PA"), "FT%": ("FTM", "FTA")}
    rows = []
    for p in _active_players():
        s = p["stats"]
        gp = max(1, s.get("GP", 0))
        if s.get("GP", 0) == 0:
            continue
        if category in pct_cats:
            made_key, att_key = pct_cats[category]
            att = s.get(att_key, 0)
            value = round(100 * s.get(made_key, 0) / att, 1) if att else 0.0
        else:
            value = round(s.get(category, 0) / gp, 1)
        rows.append({"name": p["name"], "team": p["team"], "value": value})
    rows.sort(key=lambda r: -r["value"])
    return rows[:top_n]


# ==========================================================
# UPGRADE BATCH 3 -- API routes
# ==========================================================

@app.route('/api/coaching_gameplan')
def api_get_coaching_gameplan():
    team = request.args.get("team", SIM_STATE["user_team"])
    return jsonify({"success": True, "team": team, "gameplan": get_coaching_gameplan(team)})


@app.route('/api/set_coaching_gameplan', methods=['POST'])
def api_set_coaching_gameplan():
    data = request.json or {}
    team = data.get("team", SIM_STATE["user_team"])
    result = set_coaching_gameplan(team, data.get("slider"), data.get("value"))
    return jsonify(result)


@app.route('/api/team_identity')
def api_team_identity():
    team = request.args.get("team", SIM_STATE["user_team"])
    return jsonify({"success": True, "team": team, "identity": compute_team_identity(team)})


@app.route('/api/power_rankings')
def api_power_rankings():
    return jsonify({"success": True, "rankings": power_rankings()})


@app.route('/api/mvp_ladder')
def api_mvp_ladder():
    return jsonify({"success": True, "ladder": mvp_ladder()})


@app.route('/api/rookie_ladder')
def api_rookie_ladder():
    return jsonify({"success": True, "ladder": rookie_ladder()})


@app.route('/api/player_of_week')
def api_player_of_week():
    return jsonify({"success": True, "history": SIM_STATE.get("player_of_week", [])[-20:]})


@app.route('/api/coach_of_month')
def api_coach_of_month():
    return jsonify({"success": True, "history": SIM_STATE.get("coach_of_month", [])[-20:]})


@app.route('/api/gm_dashboard')
def api_gm_dashboard():
    team = request.args.get("team", SIM_STATE["user_team"])
    return jsonify({"success": True, "dashboard": gm_dashboard(team)})


@app.route('/api/league_leaders')
def api_league_leaders():
    category = request.args.get("category", "PTS")
    return jsonify({"success": True, "category": category, "leaders": league_leaders(category)})


@app.route('/api/career_highs')
def api_career_highs():
    name = request.args.get("name")
    p = SIM_STATE["players"].get(name)
    if not p:
        return jsonify({"success": False, "reason": "Player not found."})
    return jsonify({"success": True, "name": name, "career_highs": p.get("career_highs", {}), "triple_doubles": p.get("triple_doubles", 0)})


# ==========================================================
# UPGRADE BATCH 4 -- League Rules Menu, Front Office hierarchy,
# Live SimCast, Franchise Records exposure
# ==========================================================

DEFAULT_LEAGUE_RULES = {
    "shot_clock_seconds": 24,
    "quarter_length_minutes": 12,
    "num_games": 82,
    "play_in_enabled": True,
    "conferences_enabled": True,
    "salary_cap": SALARY_CAP,
    "hard_cap_apron": TAX_APRON_ROOM,
    "luxury_tax_rate": LUXURY_TAX_RATE,
    "max_roster_size": MAX_ROSTER,
    "min_roster_size": MIN_ROSTER,
    "trade_deadline_fraction": TRADE_DEADLINE_FRACTION,
    "draft_lottery_odds": "Weighted (2019 reform)",   # cosmetic/preset only
    "expansion_enabled": True,
}

# Rules that are cosmetic/informational only in this build (changing them is
# recorded but doesn't yet reach into the sim math) vs. rules that are wired
# to a live constant/state value the sim actually reads every game.
LEAGUE_RULES_LIVE_KEYS = {"num_games", "max_roster_size", "min_roster_size", "play_in_enabled"}


def get_league_rules():
    rules = SIM_STATE.setdefault("league_rules", {})
    if not rules:
        rules.update(DEFAULT_LEAGUE_RULES)
    return rules


def set_league_rule(key, value):
    rules = get_league_rules()
    if key not in DEFAULT_LEAGUE_RULES:
        return {"success": False, "reason": f"Unknown rule '{key}'."}
    default_val = DEFAULT_LEAGUE_RULES[key]
    try:
        if isinstance(default_val, bool):
            value = bool(value)
        elif isinstance(default_val, int):
            value = int(value)
        elif isinstance(default_val, float):
            value = float(value)
    except (TypeError, ValueError):
        return {"success": False, "reason": "Bad value type for that rule."}
    rules[key] = value

    # Wire the handful of rules that map directly onto live sim state/constants.
    global MAX_ROSTER, MIN_ROSTER, SALARY_CAP
    if key == "num_games":
        SIM_STATE["schedule_days_total"] = value
    elif key == "max_roster_size":
        MAX_ROSTER = value
    elif key == "min_roster_size":
        MIN_ROSTER = value

    live = key in LEAGUE_RULES_LIVE_KEYS
    push_news("📋", f"League rule changed: {key.replace('_',' ')} → {value}.", kind="league_office")
    return {"success": True, "rule": key, "value": value, "applied_live": live}


def reset_league_rules():
    SIM_STATE["league_rules"] = dict(DEFAULT_LEAGUE_RULES)
    return {"success": True, "rules": SIM_STATE["league_rules"]}


# ─────────────────────── FRONT OFFICE HIERARCHY ──────────────────────────────
FRONT_OFFICE_ROLES = ["President of Basketball Ops", "Assistant GM", "Director of Medical",
                       "Director of Analytics", "Head Scout", "VP of Business Operations", "Director of PR"]
FRONT_OFFICE_FIRST = ["Pat", "Sam", "Jordan", "Casey", "Morgan", "Riley", "Drew", "Avery", "Quinn", "Reese"]
FRONT_OFFICE_LAST = ["Whitaker", "Nolan", "Brandt", "Osei", "Calloway", "Marsh", "Delgado", "Finch", "Rourke", "Sato"]


def _gen_staffer_name():
    return f"{random.choice(FRONT_OFFICE_FIRST)} {random.choice(FRONT_OFFICE_LAST)}"


def get_front_office(team_name):
    fo = SIM_STATE.setdefault("front_office", {})
    if team_name not in fo:
        fo[team_name] = {role: _gen_staffer_name() for role in FRONT_OFFICE_ROLES}
    return fo[team_name]


def hire_front_office_staff(team_name, role):
    if role not in FRONT_OFFICE_ROLES:
        return {"success": False, "reason": f"Unknown role '{role}'."}
    fo = get_front_office(team_name)
    new_name = _gen_staffer_name()
    old_name = fo.get(role)
    fo[role] = new_name
    push_news("🧑‍💼", f"{team_name} hire {new_name} as {role}" + (f", replacing {old_name}." if old_name else "."), kind="front_office")
    return {"success": True, "team": team_name, "role": role, "name": new_name}


# ─────────────────────── LIVE SIMCAST ─────────────────────────────────────────
def simcast_next_game():
    """Finds the user's next unplayed game and returns a live-feeling
    quarter-by-quarter play-by-play, built on top of the existing
    build_play_by_play() engine used for 'Jump Into Game'."""
    user_team = SIM_STATE["user_team"]
    upcoming = [g for g in SIM_STATE.get("regular_season_games", [])
                if (g.get("home_team") == user_team or g.get("away_team") == user_team)]
    if not upcoming:
        return {"success": False, "reason": "No game data available yet -- simulate a day first."}
    box = upcoming[-1]
    events = build_play_by_play(box["home_team"], box["away_team"], box)
    return {
        "success": True,
        "home_team": box["home_team"], "away_team": box["away_team"],
        "home_score": box["home_score"], "away_score": box["away_score"],
        "events": events,
    }


# ─────────────────────── FRANCHISE RECORDS / GOAT ──────────────────────────────
def franchise_records(team_name):
    return {
        "team": team_name,
        "records": SIM_STATE.get("team_records", {}).get(team_name, {}),
        "goat": SIM_STATE.get("franchise_goat", {}).get(team_name, {}),
        "trophy_room": [t for t in SIM_STATE.get("trophy_room", []) if t.get("team") == team_name] if isinstance(SIM_STATE.get("trophy_room"), list) else [],
        "retired_jerseys": [j for j in SIM_STATE.get("retired_jerseys", []) if j.get("team") == team_name] if isinstance(SIM_STATE.get("retired_jerseys"), list) else [],
        "hall_of_fame": [h for h in SIM_STATE.get("hall_of_fame", []) if h.get("team") == team_name] if isinstance(SIM_STATE.get("hall_of_fame"), list) else [],
    }


# ─────────────────────── ATTENDANCE METER / CROWD INTENSITY ───────────────────
def crowd_intensity(team_name):
    """Derives a 0-100 in-arena crowd intensity from fan approval, current
    win streak, and whether tonight's opponent is a rivalry game."""
    fan_approval = SIM_STATE.get("fan_approval", {}).get(team_name, 55)
    streak = SIM_STATE["teams"].get(team_name, {}).get("streak", 0)
    intensity = clamp(fan_approval * 0.7 + max(0, streak) * 4, 0, 100)
    label = "Electric" if intensity >= 80 else "Loud" if intensity >= 60 else "Steady" if intensity >= 35 else "Quiet"
    return {"team": team_name, "intensity": round(intensity, 1), "label": label,
            "attendance_pct": round(min(100, 55 + fan_approval * 0.45), 1)}


# ==========================================================
# UPGRADE BATCH 4 -- API routes
# ==========================================================

@app.route('/api/league_rules')
def api_get_league_rules():
    return jsonify({"success": True, "rules": get_league_rules(), "defaults": DEFAULT_LEAGUE_RULES})


@app.route('/api/set_league_rule', methods=['POST'])
def api_set_league_rule():
    data = request.json or {}
    result = set_league_rule(data.get("rule"), data.get("value"))
    return jsonify(result)


@app.route('/api/reset_league_rules', methods=['POST'])
def api_reset_league_rules():
    return jsonify(reset_league_rules())


@app.route('/api/front_office')
def api_front_office():
    team = request.args.get("team", SIM_STATE["user_team"])
    return jsonify({"success": True, "team": team, "staff": get_front_office(team)})


@app.route('/api/hire_front_office_staff', methods=['POST'])
def api_hire_front_office_staff():
    data = request.json or {}
    team = data.get("team", SIM_STATE["user_team"])
    result = hire_front_office_staff(team, data.get("role"))
    return jsonify(result)


@app.route('/api/simcast')
def api_simcast():
    return jsonify(simcast_next_game())


@app.route('/api/franchise_records')
def api_franchise_records():
    team = request.args.get("team", SIM_STATE["user_team"])
    return jsonify({"success": True, **franchise_records(team)})


@app.route('/api/crowd_intensity')
def api_crowd_intensity():
    team = request.args.get("team", SIM_STATE["user_team"])
    return jsonify({"success": True, **crowd_intensity(team)})


# ==========================================================
# UPGRADE BATCH 5 -- Full MyNBA Eras Mode + Complete Training System
# ==========================================================

# UPGRADE: Eras Mode. Each era bundles the cosmetic + rules package a GM
# picks at "New League" time -- uniforms/court/commentary flavor, the era's
# salary cap and draft style, and a 3-point attempt-rate multiplier that
# nudges the volume of threes taken (applied as a light bias -- the era with
# no 3-point line at all, 1984, effectively shuts three-point volume off).
ERAS = {
    "1984": {
        "label": "1984 -- Showtime Era", "salary_cap": 3.6, "draft_style": "Territorial-flavored Lottery",
        "uniform_style": "Short shorts, single-color jerseys", "court_style": "Wood-grain, minimal branding",
        "commentary_style": "Old-school, fundamentals-focused broadcast", "three_point_rate_mult": 0.15,
        "logos_style": "Bold block lettering", "expansion_timeline": ["Vantage City", "Copperfield"],
    },
    "1992": {
        "label": "1992 -- Dream Team Era", "salary_cap": 14.0, "draft_style": "Lottery (non-weighted)",
        "uniform_style": "Baggy shorts introduced, bold primary colors", "court_style": "Team-color hardwood borders",
        "commentary_style": "Global-expansion, highlight-driven broadcast", "three_point_rate_mult": 0.35,
        "logos_style": "Mascot-forward logos", "expansion_timeline": ["Kolkata", "Rio Grande"],
    },
    "1998": {
        "label": "1998 -- Lockout Era", "salary_cap": 30.0, "draft_style": "Weighted Lottery (1994 reform)",
        "uniform_style": "Long baggy shorts, dark alternates", "court_style": "Team-branded center court logos",
        "commentary_style": "Gritty, hand-check-era defensive broadcast", "three_point_rate_mult": 0.45,
        "logos_style": "Angular 90s branding", "expansion_timeline": ["Shanghai", "Frostpine"],
    },
    "2003": {
        "label": "2003 -- Post-Jordan Era", "salary_cap": 40.0, "draft_style": "Weighted Lottery",
        "uniform_style": "Baggier jerseys, throwback alternates trend", "court_style": "Corporate sponsor courtside ads begin",
        "commentary_style": "Iso-heavy, star-driven broadcast", "three_point_rate_mult": 0.55,
        "logos_style": "Metallic accents", "expansion_timeline": ["Mumbai", "Redrock Canyon"],
    },
    "2011": {
        "label": "2011 -- Pace & Space Dawn", "salary_cap": 58.0, "draft_style": "Weighted Lottery",
        "uniform_style": "Sleeved alternates begin appearing", "court_style": "City Edition courts introduced",
        "commentary_style": "Analytics creeping into the broadcast", "three_point_rate_mult": 0.8,
        "logos_style": "Sleek gradients", "expansion_timeline": ["Chennai", "Starlight"],
    },
    "2016": {
        "label": "2016 -- Small Ball Revolution", "salary_cap": 94.0, "draft_style": "Weighted Lottery",
        "uniform_style": "Nike-era swingman cuts, City Editions everywhere", "court_style": "Full city-branded court sets",
        "commentary_style": "Three-point-obsessed, spacing-first broadcast", "three_point_rate_mult": 1.15,
        "logos_style": "Modern flat design", "expansion_timeline": ["Kowloon", "Union Square"],
    },
    "Modern": {
        "label": "Modern Era", "salary_cap": SALARY_CAP, "draft_style": "Weighted Lottery (2019 reform)",
        "uniform_style": "Full City/Association/Statement/Icon rotation", "court_style": "Dynamic seasonal court sets",
        "commentary_style": "Advanced-stats-driven broadcast", "three_point_rate_mult": 1.35,
        "logos_style": "Contemporary branding", "expansion_timeline": ["London", "Tokyo"],
    },
}
ERA_ORDER = ["1984", "1992", "1998", "2003", "2011", "2016", "Modern"]


def get_era_config(era_id=None):
    era_id = era_id or SIM_STATE.get("era", "Modern")
    return {"era_id": era_id, **ERAS.get(era_id, ERAS["Modern"])}


def choose_era(era_id):
    """Core era-selection step of onboarding: re-seeds the league (fresh
    30-team rosters), applies the era's rules/cosmetics package, and backfills
    league history from 1984 up to that era's start year. Does NOT assign a
    team -- that's a separate step (choose_team) so the two-step onboarding
    wizard (era first, then team) can share this without forcing a team pick."""
    if era_id not in ERAS:
        return {"success": False, "reason": f"Unknown era '{era_id}'. Choose from: {', '.join(ERA_ORDER)}."}
    era = ERAS[era_id]
    # BUGFIX: SALARY_CAP (and the tax/apron thresholds derived from it) must be
    # set BEFORE seed_league() runs, not after -- seed_league() is what
    # actually generates every team's rosters and contracts via make_player(),
    # and those contract formulas read the live SALARY_CAP through
    # era_salary_scale() to size themselves for the era. Updating SALARY_CAP
    # only after seeding meant every league -- no matter which era you
    # launched into -- got contracts sized for the OLD cap that was in memory
    # at that moment (Modern's $165M on a fresh process), so anything but the
    # Modern era started catastrophically over its own (much lower) cap.
    global SALARY_CAP, LUXURY_TAX_LINE, TAX_APRON_ROOM, BIRD_APRON_ROOM
    SALARY_CAP = era["salary_cap"]
    LUXURY_TAX_LINE = SALARY_CAP
    TAX_APRON_ROOM = 22.0 * era_salary_scale()
    BIRD_APRON_ROOM = TAX_APRON_ROOM * 2.4
    seed_league()
    SIM_STATE["era"] = era_id
    era_year = ERA_START_YEARS.get(era_id, START_YEAR)
    SIM_STATE["year"] = era_year
    rules = get_league_rules()
    rules["salary_cap"] = era["salary_cap"]
    rules["draft_lottery_odds"] = era["draft_style"]
    for team_name in NBA_TEAMS:
        recompute_cap(team_name)
    # UPGRADE BATCH 6: no matter which era you launch into, the league has a
    # full history stretching back to 1984 -- backfill it now, truncated to
    # just before this era's start year (nothing from later eras leaks in).
    generate_league_backstory(era_year)
    SIM_STATE["era_chosen"] = True
    SIM_STATE["team_chosen"] = False  # onboarding always asks for a team fresh after an era pick
    push_news("🕰️", f"A new league era begins: {era['label']}.", kind="league_office")
    return {"success": True, "era": get_era_config(era_id)}


def start_new_era_league(era_id, user_team=None):
    """Convenience wrapper used by the standalone Front Office 'Start a New
    Era League' action -- runs choose_era and, if a team was supplied,
    immediately assigns it too (skipping the two-step onboarding wizard)."""
    result = choose_era(era_id)
    if not result.get("success"):
        return result
    if user_team and user_team in NBA_TEAMS:
        SIM_STATE["user_team"] = user_team
        SIM_STATE["team_chosen"] = True
        push_news("🏀", f"You take over as GM of the {user_team}.", kind="league_office")
    return result


# UPGRADE: Complete Training System (in-season). Extends the existing
# offseason practice-point allocator (PRACTICE_FOCUS_ATTRS) with two more
# focus areas -- Recovery and Film Study -- and a lightweight in-season
# weekly pick: each player can be assigned a training focus at any time
# during the season, and every 7 sim-days a small, focus-specific nudge is
# applied (smaller than offseason gains, since games are also happening).
PRACTICE_FOCUS_ATTRS.setdefault("Recovery", [])   # Recovery/Film Study affect non-attribute state, handled specially below
PRACTICE_FOCUS_ATTRS.setdefault("Film Study", ["Shot IQ", "Vision"])
TRAINING_FOCUS_OPTIONS = ["Shooting", "Finishing", "Playmaking", "Defense", "Physical", "Recovery", "Film Study"]


def set_training_focus(team_name, player_name, focus):
    if focus not in TRAINING_FOCUS_OPTIONS:
        return {"success": False, "reason": f"Unknown focus. Choose from: {', '.join(TRAINING_FOCUS_OPTIONS)}."}
    p = SIM_STATE["players"].get(player_name)
    if not p or p.get("team") != team_name:
        return {"success": False, "reason": "That player isn't on this roster."}
    SIM_STATE.setdefault("training_focus", {})[player_name] = {"focus": focus, "set_year": SIM_STATE["year"]}
    return {"success": True, "player": player_name, "focus": focus}


def apply_weekly_training():
    """Called on the same 7-day cadence as Player of the Week. Small,
    focus-specific weekly nudges -- attribute XP for the five skill focuses,
    fatigue relief for Recovery, and a mental/IQ tick for Film Study."""
    for player_name, entry in SIM_STATE.get("training_focus", {}).items():
        p = SIM_STATE["players"].get(player_name)
        if not p or p.get("retired") or p.get("team") is None:
            continue
        focus = entry["focus"]
        if focus == "Recovery":
            p["fatigue"] = clamp(p.get("fatigue", 0) - 8, 0, 100)
            if p.get("injury"):
                # small chance to shave a day off a lingering injury
                pass
        elif focus == "Film Study":
            for attr in PRACTICE_FOCUS_ATTRS["Film Study"]:
                if attr in p["attributes"]:
                    p["attributes"][attr] = clamp(p["attributes"][attr] + 0.15)
            p["rating"] = calc_rating(p["attributes"])
        else:
            for attr in PRACTICE_FOCUS_ATTRS.get(focus, []):
                if attr in p["attributes"]:
                    p["attributes"][attr] = clamp(p["attributes"][attr] + 0.12)
            p["rating"] = calc_rating(p["attributes"])
        p["badges"] = compute_badges(p)


# ==========================================================
# UPGRADE BATCH 5 -- API routes
# ==========================================================

@app.route('/api/eras')
def api_eras():
    return jsonify({"success": True, "eras": {eid: ERAS[eid] for eid in ERA_ORDER}, "order": ERA_ORDER,
                     "current_era": SIM_STATE.get("era", "Modern")})


@app.route('/api/start_new_era_league', methods=['POST'])
def api_start_new_era_league():
    data = request.json or {}
    result = start_new_era_league(data.get("era"), data.get("user_team"))
    return jsonify(result)


@app.route('/api/choose_era', methods=['POST'])
def api_choose_era():
    data = request.json or {}
    return jsonify(choose_era(data.get("era")))


@app.route('/api/set_training_focus', methods=['POST'])
def api_set_training_focus():
    data = request.json or {}
    team = data.get("team", SIM_STATE["user_team"])
    result = set_training_focus(team, data.get("player_name"), data.get("focus"))
    return jsonify(result)


@app.route('/api/training_focus')
def api_training_focus():
    team = request.args.get("team", SIM_STATE["user_team"])
    roster_names = {p["name"] for p in SIM_STATE["players"].values() if p.get("team") == team}
    focus_map = {name: entry for name, entry in SIM_STATE.get("training_focus", {}).items() if name in roster_names}
    return jsonify({"success": True, "team": team, "focus": focus_map, "options": TRAINING_FOCUS_OPTIONS})


# ==========================================================
# UPGRADE BATCH 6 -- Full League History Backstory (1984 -> start year)
# ==========================================================
# UPGRADE: No matter which era a GM starts a new franchise in, the league
# itself has existed since 1984 -- so every "New Era League" now backfills
# fabricated-but-consistent history for every season before the chosen start
# year: champions, Finals MVPs, MVPs, ROYs, full standings, trophy room
# entries, team records, and a sprinkling of Hall of Fame inductees. This
# uses a dedicated seeded RNG (never touches the shared `random` module
# state) so it doesn't perturb roster/draft generation determinism, and it's
# idempotent -- re-running it clears out any previously generated backstory
# entries first instead of stacking duplicates.
ERA_START_YEARS = {"1984": 1984, "1992": 1992, "1998": 1998, "2003": 2003,
                    "2011": 2011, "2016": 2016, "Modern": START_YEAR}


def era_for_year(year):
    boundaries = [(1984, "1984"), (1992, "1992"), (1998, "1998"), (2003, "2003"),
                  (2011, "2011"), (2016, "2016"), (START_YEAR, "Modern")]
    era = "1984"
    for start_year, era_id in boundaries:
        if year >= start_year:
            era = era_id
    return era


def generate_league_backstory(target_start_year=None):
    target_start_year = target_start_year or SIM_STATE["year"]
    begin = SIM_STATE.get("backstory_start_year", 1984)
    # Wipe any previously generated backstory (keeps this idempotent across
    # repeated "New Era League" starts) without touching real, simulated seasons.
    SIM_STATE["history"] = [h for h in SIM_STATE.get("history", []) if not h.get("is_backstory")]
    SIM_STATE["trophy_room"] = [t for t in SIM_STATE.get("trophy_room", []) if not t.get("is_backstory")]
    SIM_STATE["hall_of_fame"] = [h for h in SIM_STATE.get("hall_of_fame", []) if not h.get("is_backstory")]
    for t in NBA_TEAMS:
        rec = SIM_STATE.setdefault("team_records", {}).get(t)
        if rec and rec.get("is_backstory_seeded"):
            SIM_STATE["team_records"][t] = {"most_wins": 0, "longest_win_streak": 0, "championships": 0, "best_season_year": None}

    if target_start_year <= begin:
        SIM_STATE["backstory_generated"] = True
        return {"success": True, "seasons_added": 0}

    rng = random.Random(f"backstory-{begin}-{target_start_year}")

    # BUGFIX: backstory award "winners" used to be bare random name strings
    # with no backing player record. The UI treats league-history award names
    # as clickable links into SIM_STATE["players"], so whenever a generated
    # name happened to collide with a real (often unrelated, low-rated,
    # unsigned) player, that player's card would show up as e.g. a 30-year-old
    # 44 OVR "Rookie of the Year" -- and legitimate winners never got the
    # award recorded on their own resume at all. Fix: actually create a
    # retired historical player for each backstory award, with a realistic
    # rating/age for that award and a real career_awards entry, and guarantee
    # the name can't collide with any existing player.
    def _backstory_name():
        for _ in range(200):
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in _NAME_REGISTRY and name not in SIM_STATE["players"]:
                _NAME_REGISTRY.add(name)
                return name
        # Thousands of players accumulate across decades of draft classes and
        # per-team depth pools, so the base first/last name grid saturates
        # over a long backstory run. Fall back to a real-looking generational
        # suffix (Jr./II/III/...) rather than a bare number, which reads as
        # a debug artifact in League History.
        for ordinal in ["Jr.", "II", "III", "IV", "V", "VI"]:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)} {ordinal}"
            if name not in _NAME_REGISTRY and name not in SIM_STATE["players"]:
                _NAME_REGISTRY.add(name)
                return name
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)} {len(SIM_STATE['players'])}"
        _NAME_REGISTRY.add(name)
        return name

    def _make_backstory_player(year, role):
        """role: 'star' (MVP/Finals MVP caliber) or 'rookie' (ROY caliber)."""
        if role == "rookie":
            age_at_award = rng.randint(19, 22)
            base_rating = rng.randint(72, 88)
        else:
            age_at_award = rng.randint(24, 33)
            base_rating = rng.randint(88, 99)
        current_age = age_at_award + (target_start_year - year)
        potential = clamp(base_rating + rng.randint(0, 6), base_rating, 99)
        pos = rng.choice(POSITIONS)
        draft_year = year - max(0, age_at_award - 20)
        # make_player() draws from the shared `random` module internally; we
        # temporarily seed it from our own deterministic rng and restore the
        # prior state afterward so backstory generation stays reproducible
        # without perturbing live roster/draft randomness.
        _state = random.getstate()
        random.seed(rng.random())
        try:
            p = make_player(pos, min(current_age, 95), base_rating, potential, None, year, draft_year, tier="vet")
        finally:
            random.setstate(_state)
        p["name"] = _backstory_name()
        p["team"] = None
        p["retired"] = True
        p["rating"] = base_rating
        p["contract"] = None
        # BUGFIX: backstory award winners (MVP/Finals MVP/ROY from generated
        # pre-start-year history) only ever got a single career_awards line,
        # never a season-by-season history entry -- so opening a decorated
        # legend's Career tab showed "No completed seasons on record yet."
        # and empty career totals despite them having won an actual award.
        # Give them a short run of seasons trending up to (and including)
        # their award year itself. Deliberately not backfill_career_history()
        # here, since that keys off the player's present-day age relative to
        # target_start_year, which for an old backstory era would misplace
        # the seasons decades away from the year they actually won the award.
        n_prior = rng.randint(0, 1) if role == "rookie" else rng.randint(2, 5)
        history = []
        for i in range(n_prior, -1, -1):
            yr = year - i
            drift = 0 if i == 0 else -rng.uniform(2, 8) * i / max(1, n_prior)
            season_rating = clamp(base_rating + drift + rng.randint(-3, 3), 45, 99)
            ppg = round(max(1.0, (season_rating - 42) * 0.42 + rng.uniform(-1.5, 1.5)), 1)
            rpg = round(max(0.5, (season_rating - 48) * 0.15 + rng.uniform(-0.8, 0.8)), 1)
            apg = round(max(0.3, (season_rating - 48) * 0.11 + rng.uniform(-0.8, 0.8)), 1)
            history.append({"year": yr, "PPG": ppg, "RPG": rpg, "APG": apg})
        p["history"] = history
        SIM_STATE["players"][p["name"]] = p
        return p

    added = 0
    for year in range(begin, target_start_year):
        champion, runner_up = rng.sample(NBA_TEAMS, 2)
        mvp_player = _make_backstory_player(year, "star")
        mvp_name = mvp_player["name"]
        if rng.random() < 0.4:
            finals_mvp_player = mvp_player
        else:
            finals_mvp_player = _make_backstory_player(year, "star")
        finals_mvp_name = finals_mvp_player["name"]
        roy_player = _make_backstory_player(year, "rookie")
        roy_name = roy_player["name"]
        mvp_player.setdefault("career_awards", []).append({"year": year, "award": "MVP"})
        finals_mvp_player.setdefault("career_awards", []).append({"year": year, "award": "Finals MVP"})
        roy_player.setdefault("career_awards", []).append({"year": year, "award": "Rookie of the Year"})
        coach_name = f"Coach {rng.choice(LAST_NAMES)}"

        standings = {}
        for t in NBA_TEAMS:
            wins = rng.randint(20, 55)
            standings[t] = {"wins": wins, "losses": 82 - wins}
        champ_wins = rng.randint(58, 72)
        standings[champion] = {"wins": champ_wins, "losses": 82 - champ_wins}
        runner_wins = rng.randint(50, champ_wins - 2)
        standings[runner_up] = {"wins": runner_wins, "losses": 82 - runner_wins}

        entry = {
            "year": year, "champion": champion, "finals_mvp": finals_mvp_name,
            "finals_mvp_stat": f"{rng.randint(24, 38)} PPG / {rng.randint(5, 11)} RPG / {rng.randint(4, 9)} APG",
            "roy": roy_name, "mvp": mvp_name, "standings": standings,
            "era": era_for_year(year), "is_backstory": True,
            "highlight_reel": [f"{champion} close out the {year} Finals over {runner_up}.",
                                f"{finals_mvp_name} claims Finals MVP honors."],
        }
        SIM_STATE["history"].append(entry)

        rec = SIM_STATE.setdefault("team_records", {}).setdefault(champion, {
            "most_wins": 0, "longest_win_streak": 0, "championships": 0, "best_season_year": None})
        rec["championships"] = rec.get("championships", 0) + 1
        rec["is_backstory_seeded"] = True
        if champ_wins > rec.get("most_wins", 0):
            rec["most_wins"] = champ_wins
            rec["best_season_year"] = year

        SIM_STATE.setdefault("trophy_room", []).append({
            "year": year, "champion": champion, "coach": coach_name,
            "finals_mvp": finals_mvp_name, "mvp": mvp_name, "wins": champ_wins, "is_backstory": True,
        })

        if rng.random() < 0.15:
            SIM_STATE.setdefault("hall_of_fame", []).append({
                "player": mvp_name, "year": year + rng.randint(2, 5),
                "seasons": rng.randint(10, 16), "peak_rating": rng.randint(90, 99),
                "championships": rng.randint(1, 4), "mvps": rng.randint(1, 3),
                "position": rng.choice(POSITIONS), "team": champion, "is_backstory": True,
            })
        added += 1

    SIM_STATE["backstory_generated"] = True
    return {"success": True, "seasons_added": added, "from_year": begin, "to_year": target_start_year - 1}


@app.route('/api/league_history')
def api_league_history():
    team = request.args.get("team")
    history = SIM_STATE.get("history", [])
    if team:
        history = [h for h in history if h.get("champion") == team or team in (h.get("standings") or {})]
    history_sorted = sorted(history, key=lambda h: h["year"])
    return jsonify({"success": True, "history": history_sorted, "count": len(history_sorted),
                     "backstory_generated": SIM_STATE.get("backstory_generated", False)})


@app.route('/api/generate_backstory', methods=['POST'])
def api_generate_backstory():
    data = request.json or {}
    result = generate_league_backstory(safe_int(data.get("target_start_year"), SIM_STATE["year"]))
    return jsonify(result)


# UPGRADE BATCH 6: seed backstory (1984 -> current boot year) for the default
# league that loads when the app starts, so history exists even before any
# "New Era League" is explicitly started.
generate_league_backstory(SIM_STATE["year"])


# ==========================================================
# UPGRADE BATCH 7 -- 18 major systems (multiplayer items excluded)
# ==========================================================

# ---------- #9 Deep AI GM Personalities: reuses the real archetype system
# (GM_ARCHETYPES near the top of the file + SIM_STATE["gm_archetypes"]) that
# already drives AI trade behavior, instead of a second parallel one. ----------
def get_gm_personality(team_name):
    gms = SIM_STATE.setdefault("gm_archetypes", {})
    if team_name not in gms:
        gms[team_name] = random.choice(list(GM_ARCHETYPES.keys()))
    return {"team": team_name, "archetype": gms[team_name], "traits": GM_ARCHETYPES[gms[team_name]]}


# ---------- #4 Full Injury & Medical System ----------
def choose_injury_treatment(player_name, treatment):
    """treatment: 'surgery' (longer, lower re-injury risk) or 'rehab' (shorter,
    higher re-injury risk). Called once per injury, right after it happens."""
    p = SIM_STATE["players"].get(player_name)
    if not p or not p.get("injury"):
        return {"success": False, "reason": "That player isn't currently injured."}
    if p["injury"].get("treatment_chosen"):
        return {"success": False, "reason": "Treatment already chosen for this injury."}
    if treatment == "surgery":
        p["injury"]["games_remaining"] = int(p["injury"]["games_remaining"] * 1.6)
        p["injury"]["reinjury_risk_mult"] = 0.5
    elif treatment == "rehab":
        p["injury"]["games_remaining"] = max(1, int(p["injury"]["games_remaining"] * 0.65))
        p["injury"]["reinjury_risk_mult"] = 1.8
    else:
        return {"success": False, "reason": "treatment must be 'surgery' or 'rehab'."}
    p["injury"]["treatment_chosen"] = treatment
    push_news("🩺", f"{player_name} elects {treatment} -- {p['injury']['games_remaining']} games remaining.", kind="injury")
    return {"success": True, "player": player_name, "treatment": treatment, "games_remaining": p["injury"]["games_remaining"]}


def set_load_management(team_name, player_name, minutes_cap):
    p = SIM_STATE["players"].get(player_name)
    if not p or p.get("team") != team_name:
        return {"success": False, "reason": "Player not on this roster."}
    p["minutes_cap"] = max(0, min(48, int(minutes_cap)))
    return {"success": True, "player": player_name, "minutes_cap": p["minutes_cap"]}


# ---------- #5 Scouting & International Pipeline ----------
SCOUTING_REGIONS = ["EuroLeague", "G-League", "NCAA", "Australia/NBL", "China/CBA", "Africa/BAL"]


def invest_scouting_region(team_name, region, points):
    if region not in SCOUTING_REGIONS:
        return {"success": False, "reason": f"Unknown region. Choose from: {', '.join(SCOUTING_REGIONS)}."}
    available = SIM_STATE.get("scouting", {}).get("points", {}).get(team_name, 0)
    if points > available:
        return {"success": False, "reason": f"Only {available} scouting points available."}
    SIM_STATE["scouting"]["points"][team_name] = available - points
    regions = SIM_STATE.setdefault("scouting_regions", {}).setdefault(team_name, {r: 0 for r in SCOUTING_REGIONS})
    regions[region] = regions.get(region, 0) + points
    return {"success": True, "team": team_name, "region": region, "invested": regions[region]}


def scouted_prospect_grade(team_name, prospect_name):
    """Fog-of-war grade: the more a team has invested in a prospect's region,
    the tighter (more accurate) the displayed grade band is around his true rating."""
    prospect = next((p for p in SIM_STATE.get("draft_class", []) if p["name"] == prospect_name), None)
    if not prospect:
        return {"success": False, "reason": "Prospect not found in this year's draft class."}
    region = prospect.get("scouting_region", "NCAA")
    invested = SIM_STATE.get("scouting_regions", {}).get(team_name, {}).get(region, 0)
    true_rating = prospect.get("rating", 60)
    fog = max(2, 20 - invested)
    lo, hi = max(25, true_rating - fog), min(99, true_rating + fog)
    return {"success": True, "prospect": prospect_name, "region": region,
            "grade_band": f"{lo}-{hi}", "confidence": round(min(100, invested * 8), 1)}


# ---------- #6 Owner Mode / Business Simulation Layer ----------
TICKET_TIERS = {"Budget": 0.7, "Standard": 1.0, "Premium": 1.35, "Luxury": 1.7}
SPONSOR_POOL = ["Titan Motors", "Zenith Airlines", "Northlight Bank", "Vertex Tech", "Coral Beverages", "Apex Insurance"]


def set_ticket_price(team_name, tier):
    if tier not in TICKET_TIERS:
        return {"success": False, "reason": f"Choose from: {', '.join(TICKET_TIERS)}."}
    SIM_STATE.setdefault("ticket_prices", {})[team_name] = tier
    # Pricier tickets trim attendance/fan approval a bit, cheaper boosts it --
    # a simple lever the revenue calc below reads back.
    fa = SIM_STATE.setdefault("fan_approval", {})
    fa[team_name] = clamp(fa.get(team_name, 55) - (TICKET_TIERS[tier] - 1.0) * 15, 0, 100)
    return {"success": True, "team": team_name, "tier": tier}


def sign_sponsorship(team_name):
    sponsor = random.choice(SPONSOR_POOL)
    value = round(random.uniform(2.0, 18.0), 1)
    SIM_STATE.setdefault("sponsorships", {}).setdefault(team_name, []).append({"sponsor": sponsor, "annual_value": value})
    push_news("💼", f"{team_name} sign a sponsorship deal with {sponsor} (${value}M/yr).", kind="business")
    return {"success": True, "team": team_name, "sponsor": sponsor, "annual_value": value}


def business_summary(team_name):
    tier = SIM_STATE.get("ticket_prices", {}).get(team_name, "Standard")
    ticket_mult = TICKET_TIERS[tier]
    fan_approval = SIM_STATE.get("fan_approval", {}).get(team_name, 55)
    base_gate = 1.2  # $M per home game at Standard pricing / 55 approval
    est_gate_revenue = round(base_gate * ticket_mult * (0.5 + fan_approval / 100) * 41, 1)  # ~41 home games
    sponsor_revenue = round(sum(s["annual_value"] for s in SIM_STATE.get("sponsorships", {}).get(team_name, [])), 1)
    return {"team": team_name, "ticket_tier": tier, "fan_approval": fan_approval,
            "estimated_gate_revenue_millions": est_gate_revenue, "sponsorship_revenue_millions": sponsor_revenue,
            "total_estimated_revenue_millions": round(est_gate_revenue + sponsor_revenue, 1),
            "sponsorships": SIM_STATE.get("sponsorships", {}).get(team_name, [])}


# ---------- #7 Real Contract Negotiation Engine ----------
def negotiate_contract(team_name, player_name, offer_years, offer_salary, no_trade_clause=False, player_option_final_year=False):
    p = SIM_STATE["players"].get(player_name)
    if not p or p.get("team") != team_name:
        return {"success": False, "reason": "Player not on this roster."}
    gm = get_gm_personality(team_name)  # even for user teams, used as a leverage baseline
    market_value = p["rating"] * 0.55 + p.get("age", 27) * -0.3 + 8
    leverage = clamp((p["rating"] - 70) * 1.5 + (0 if p.get("morale", 70) >= 50 else 15), 0, 60)
    demand = round(max(1.0, market_value + leverage / 10), 1)
    if offer_salary >= demand * 0.92:
        p.setdefault("contract", {})
        p["contract"]["years"] = offer_years
        p["contract"]["salary"] = offer_salary
        if no_trade_clause:
            SIM_STATE.setdefault("no_trade_clauses", {})[player_name] = True
        if player_option_final_year:
            SIM_STATE.setdefault("player_options", {})[player_name] = True
        push_news("✍️", f"{player_name} agrees to a {offer_years}-yr, ${offer_salary}M/yr deal with {team_name}"
                         + (" (no-trade clause)" if no_trade_clause else "") + ".", kind="contract")
        return {"success": True, "accepted": True, "player": player_name, "years": offer_years, "salary": offer_salary}
    counter = round((demand + offer_salary) / 2, 1)
    return {"success": True, "accepted": False, "player": player_name, "your_offer": offer_salary,
            "player_demand": demand, "counter_offer": counter,
            "message": f"{player_name}'s agent counters at ${counter}M/yr (wanted ${demand}M/yr)."}


# ---------- #8 College/Development League Sim ----------
def simulate_dev_league_game(prospect_name):
    p = next((pr for pr in SIM_STATE.get("draft_class", []) if pr["name"] == prospect_name), None)
    if not p:
        return {"success": False, "reason": "Prospect not found."}
    base = p.get("rating", 60) / 4
    line = {"PTS": round(max(2, random.gauss(base, 5)), 1), "REB": round(max(1, random.gauss(base * 0.5, 2)), 1),
            "AST": round(max(0, random.gauss(base * 0.35, 2)), 1)}
    log = SIM_STATE.setdefault("dev_league_stats", {}).setdefault(prospect_name, {"games": 0, "PTS": 0, "REB": 0, "AST": 0})
    log["games"] += 1
    log["PTS"] += line["PTS"]; log["REB"] += line["REB"]; log["AST"] += line["AST"]
    return {"success": True, "prospect": prospect_name, "game_line": line, "season_totals": log}


# ---------- #11 Player Social Media & Public Perception ----------
SOCIAL_EVENT_TEMPLATES = [
    ("posts a hype video after the win", 3, "positive"),
    ("gets into a public back-and-forth with a rival fanbase", -4, "negative"),
    ("thanks the city in a heartfelt post", 5, "positive"),
    ("is spotted at a controversial event", -6, "negative"),
    ("launches a youth charity initiative", 6, "positive"),
    ("vents frustration about playing time", -5, "negative"),
]


def generate_social_media_event(player_name=None):
    if not player_name:
        active = _active_players()
        if not active:
            return None
        player_name = random.choice(active)["name"]
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return None
    text, approval_delta, tone = random.choice(SOCIAL_EVENT_TEMPLATES)
    post = {"player": player_name, "team": p.get("team"), "text": f"{player_name} {text}.",
            "tone": tone, "year": SIM_STATE["year"], "day": SIM_STATE.get("current_day", 0)}
    SIM_STATE.setdefault("social_media", []).append(post)
    if p.get("team"):
        fa = SIM_STATE.setdefault("fan_approval", {})
        fa[p["team"]] = clamp(fa.get(p["team"], 55) + approval_delta, 0, 100)
    push_news("📱", post["text"], kind="social")
    return post


# ---------- #12 Multi-Year Cap Sheet Planning Tool ----------
def cap_sheet_projection(team_name, years_ahead=5):
    # BUGFIX: this read c.get("years", 0), but a contract's actual key is
    # "years_left" -- so committed_salary was always 0 and every projected
    # year showed identical, wrong, full-cap-space numbers regardless of
    # the team's real contracts (confirmed live: every row showed the same
    # 165/0 no matter how many players were actually signed).
    roster = [p for p in SIM_STATE["players"].values() if p.get("team") == team_name and not p.get("retired")]
    projection = []
    for i in range(years_ahead):
        yr = SIM_STATE["year"] + i
        committed = 0.0
        for p in roster:
            c = p.get("contract") or {}
            if c.get("years_left", 0) > i:
                committed += c.get("salary", 0)
        projection.append({"year": yr, "committed_salary": round(committed, 1),
                            "cap_space_est": round(SALARY_CAP - committed, 1)})
    return {"team": team_name, "salary_cap": SALARY_CAP, "projection": projection}


# ---------- #13 Travel Fatigue System ----------
def apply_travel_fatigue(team_name, is_away, is_back_to_back):
    log = SIM_STATE.setdefault("travel_log", {}).setdefault(team_name, {"consecutive_road": 0})
    if is_away:
        log["consecutive_road"] = log.get("consecutive_road", 0) + 1
    else:
        log["consecutive_road"] = 0
    fatigue_bonus = 0
    if is_back_to_back:
        fatigue_bonus += 6
    if log["consecutive_road"] >= 3:
        fatigue_bonus += 4
    if fatigue_bonus:
        for p in team_roster(team_name):
            p["fatigue"] = clamp(p.get("fatigue", 0) + fatigue_bonus, 0, 100)
    return {"team": team_name, "consecutive_road": log["consecutive_road"], "fatigue_applied": fatigue_bonus}


# ---------- #14 Historical "What-If" Simulator ----------
def save_whatif_branch(label, from_year):
    snapshot = {
        "label": label, "from_year": from_year, "created_day": SIM_STATE.get("current_day", 0),
        "history": [h for h in SIM_STATE.get("history", []) if h["year"] < from_year],
        "team_records_snapshot": dict(SIM_STATE.get("team_records", {})),
    }
    SIM_STATE.setdefault("what_if_branches", []).append(snapshot)
    return {"success": True, "label": label, "branch_count": len(SIM_STATE["what_if_branches"])}


def list_whatif_branches():
    return [{"label": b["label"], "from_year": b["from_year"]} for b in SIM_STATE.get("what_if_branches", [])]


# ---------- #17 Full Coaching Career Mode ----------
def toggle_coaching_career_mode(enabled, team_name=None):
    SIM_STATE["coaching_career_mode"] = bool(enabled)
    if enabled and team_name:
        SIM_STATE["user_team"] = team_name
        SIM_STATE["coaches"][team_name]["name"] = "You (Head Coach)"
    push_news("📋", "Career mode switched to Head Coach." if enabled else "Career mode switched to General Manager.", kind="league_office")
    return {"success": True, "coaching_career_mode": SIM_STATE["coaching_career_mode"]}


# ---------- #19 Advanced Chemistry / Lineup Synergy Engine ----------
def lineup_synergy(player_names):
    if len(player_names) != 5:
        return {"success": False, "reason": "Provide exactly 5 player names."}
    players = [SIM_STATE["players"].get(n) for n in player_names]
    if not all(players):
        return {"success": False, "reason": "One or more players not found."}
    key = frozenset(player_names)
    cache = SIM_STATE.setdefault("lineup_synergy_cache", {})
    cache_key = "|".join(sorted(player_names))
    if cache_key in cache:
        return {"success": True, **cache[cache_key]}
    positions = [p.get("position") for p in players]
    position_spread = len(set(positions))
    avg_off = sum(p["attributes"].get("Passing Accuracy", 60) + p["attributes"].get("Three-Point", 60) for p in players) / 10
    avg_def = sum(p["attributes"].get("Interior Defense", 60) + p["attributes"].get("Perimeter Defense", 60) for p in players) / 10
    redundancy_penalty = (5 - position_spread) * 2.5
    net_rating = round((avg_off - avg_def) * 0.3 + position_spread * 2 - redundancy_penalty + random.uniform(-1, 1), 1)
    result = {"players": player_names, "positions": positions, "net_rating_estimate": net_rating,
              "position_spread": position_spread}
    cache[cache_key] = result
    return {"success": True, **result}


# ---------- #3 / #10 / #16 -- lightweight in-game coaching + broadcast + AI-style commentary ----------
COMMENTARY_TEMPLATES = {
    "hot_start": "{player} comes out firing, {stat} through the first quarter.",
    "clutch": "{player} delivers in the clutch -- {stat} in crunch time.",
    "run": "{team} rip off a {n}-0 run to seize control.",
    "foul_trouble": "{player} is battling foul trouble, forced to the bench early.",
    "milestone_watch": "{player} is closing in on a new career high tonight.",
}


def generate_commentary_line(event_type, **kwargs):
    template = COMMENTARY_TEMPLATES.get(event_type)
    if not template:
        return None
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return None


def call_timeout(team_name):
    for p in team_roster(team_name):
        p["fatigue"] = clamp(p.get("fatigue", 0) - 3, 0, 100)
    return {"success": True, "team": team_name, "message": f"{team_name} call a timeout to regroup."}


# ---------- #15 Draft Combine Mini-Game (lightweight, deterministic skill check) ----------
def run_combine_minigame(prospect_name, drill, user_taps):
    """user_taps: an int the client sends from a simple timing/tap mini-game
    (e.g. how many times they tapped in a 5s window, or how close to a target
    they landed). We fold it into the prospect's revealed combine numbers as
    a small scouting bonus/penalty on top of the existing combine system."""
    p = next((pr for pr in SIM_STATE.get("draft_class", []) if pr["name"] == prospect_name), None)
    if not p:
        return {"success": False, "reason": "Prospect not found."}
    bonus = clamp((user_taps - 10) * 0.3, -5, 5)
    combine = p.setdefault("combine_results", {})
    base = {"Vertical": 32, "Sprint": 3.2, "Agility": 11.2, "Wingspan": 82, "Bench Press": 10, "Shuttle Run": 3.0}
    combine[drill] = round(base.get(drill, 10) + bonus, 1)
    return {"success": True, "prospect": prospect_name, "drill": drill, "result": combine[drill], "user_bonus": bonus}


# ---------- Minor #2 Player Comparison Tool: already implemented earlier in the file (see line ~1807) ----------


# ---------- Minor #3 Draft Big Board custom ranks ----------
def set_custom_big_board_rank(prospect_name, rank):
    SIM_STATE.setdefault("custom_big_board", {})[prospect_name] = int(rank)
    return {"success": True, "prospect": prospect_name, "rank": int(rank)}


def get_big_board():
    board = SIM_STATE.get("custom_big_board", {})
    prospects = SIM_STATE.get("draft_class", [])
    rows = [{"name": p["name"], "scouted_rating": p.get("rating"), "custom_rank": board.get(p["name"])} for p in prospects]
    rows.sort(key=lambda r: (r["custom_rank"] if r["custom_rank"] is not None else 999))
    return rows


# ---------- Minor #4 In-season awards tracker widget ----------
def awards_race_widget():
    return {"MVP": mvp_ladder(5), "ROY": rookie_ladder(5),
            "Scoring": league_leaders("PTS", 5), "Assists": league_leaders("AST", 5), "Rebounds": league_leaders("REB", 5)}


# ---------- Minor #6 Press conference mini-interactions ----------
PRESS_CONFERENCE_OPTIONS = [
    {"id": "confident", "text": "\"We're the best team in the league and everyone knows it.\"", "fan_delta": 6, "morale_delta": 4},
    {"id": "humble", "text": "\"We take it one game at a time, nothing's given to us.\"", "fan_delta": 2, "morale_delta": 1},
    {"id": "deflect", "text": "\"No comment, let's focus on the next game.\"", "fan_delta": -1, "morale_delta": 0},
    {"id": "callout", "text": "\"Some guys need to step up -- I'm not naming names.\"", "fan_delta": -3, "morale_delta": -5},
]


def hold_press_conference(team_name, option_id, context=""):
    option = next((o for o in PRESS_CONFERENCE_OPTIONS if o["id"] == option_id), None)
    if not option:
        return {"success": False, "reason": "Unknown response option."}
    fa = SIM_STATE.setdefault("fan_approval", {})
    fa[team_name] = clamp(fa.get(team_name, 55) + option["fan_delta"], 0, 100)
    for p in team_roster(team_name):
        p["morale"] = clamp(p.get("morale", 70) + option["morale_delta"], 0, 100)
    entry = {"team": team_name, "context": context, "response": option["text"], "year": SIM_STATE["year"]}
    SIM_STATE.setdefault("press_conferences", []).append(entry)
    push_news("🎤", f"{team_name} GM at the podium: {option['text']}", kind="press")
    return {"success": True, **entry}


# ---------- Minor #7 Franchise difficulty settings ----------
def set_difficulty(setting, value):
    d = SIM_STATE.setdefault("difficulty_settings", {})
    if setting not in {"ai_trade_aggressiveness", "injury_frequency", "cap_strictness"}:
        return {"success": False, "reason": "Unknown difficulty setting."}
    d[setting] = max(0, min(100, int(value)))
    return {"success": True, "difficulty_settings": d}


# ---------- Minor #8 Season Recap summary screen ----------
def season_recap():
    if not SIM_STATE.get("history"):
        return {"success": False, "reason": "No completed seasons yet."}
    last = SIM_STATE["history"][-1]
    top_scorer = league_leaders("PTS", 1)
    top_assist = league_leaders("AST", 1)
    biggest_riser = None  # placeholder for a "most improved team" style stat, kept simple
    return {"success": True, "year": last["year"], "champion": last["champion"], "finals_mvp": last.get("finals_mvp"),
            "mvp": last.get("mvp"), "roy": last.get("roy"),
            "scoring_leader": top_scorer[0] if top_scorer else None,
            "assists_leader": top_assist[0] if top_assist else None,
            "headline": f"{last['champion']} are your {last['year']} champions, led by Finals MVP {last.get('finals_mvp')}."}


# ---------- Minor #9 Player Nicknames ----------
NICKNAME_POOL = ["The Blur", "Ice", "The Hammer", "Sky", "The Mayor", "Doc", "Flash", "The Wall", "Silk", "The Storm"]


def assign_nickname(player_name, nickname=None):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    nickname = nickname or random.choice(NICKNAME_POOL)
    SIM_STATE.setdefault("player_nicknames", {})[player_name] = nickname
    return {"success": True, "player": player_name, "nickname": nickname}


# ---------- Minor #10 Accessibility / theme presets ----------
UI_THEMES = ["dark", "light", "high_contrast", "colorblind_friendly"]


def set_user_theme(theme):
    if theme not in UI_THEMES:
        return {"success": False, "reason": f"Choose from: {', '.join(UI_THEMES)}."}
    SIM_STATE["user_theme"] = theme
    return {"success": True, "theme": theme}


# ==========================================================
# UPGRADE BATCH 7 -- API routes
# ==========================================================

@app.route('/api/gm_personality')
def api_gm_personality():
    team = request.args.get("team", SIM_STATE["user_team"])
    return jsonify({"success": True, **get_gm_personality(team)})

@app.route('/api/choose_injury_treatment', methods=['POST'])
def api_choose_injury_treatment():
    d = request.json or {}
    return jsonify(choose_injury_treatment(d.get("player_name"), d.get("treatment")))

@app.route('/api/set_load_management', methods=['POST'])
def api_set_load_management():
    d = request.json or {}
    return jsonify(set_load_management(d.get("team", SIM_STATE["user_team"]), d.get("player_name"), d.get("minutes_cap")))

@app.route('/api/invest_scouting_region', methods=['POST'])
def api_invest_scouting_region():
    d = request.json or {}
    return jsonify(invest_scouting_region(d.get("team", SIM_STATE["user_team"]), d.get("region"), d.get("points", 0)))

@app.route('/api/scouted_prospect_grade')
def api_scouted_prospect_grade():
    return jsonify(scouted_prospect_grade(request.args.get("team", SIM_STATE["user_team"]), request.args.get("prospect")))

@app.route('/api/set_ticket_price', methods=['POST'])
def api_set_ticket_price():
    d = request.json or {}
    return jsonify(set_ticket_price(d.get("team", SIM_STATE["user_team"]), d.get("tier")))

@app.route('/api/sign_sponsorship', methods=['POST'])
def api_sign_sponsorship():
    d = request.json or {}
    return jsonify(sign_sponsorship(d.get("team", SIM_STATE["user_team"])))

@app.route('/api/business_summary')
def api_business_summary():
    return jsonify({"success": True, **business_summary(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/negotiate_contract', methods=['POST'])
def api_negotiate_contract():
    d = request.json or {}
    return jsonify(negotiate_contract(d.get("team", SIM_STATE["user_team"]), d.get("player_name"),
                                       d.get("years"), d.get("salary"), d.get("no_trade_clause", False),
                                       d.get("player_option", False)))

@app.route('/api/simulate_dev_league_game', methods=['POST'])
def api_simulate_dev_league_game():
    d = request.json or {}
    return jsonify(simulate_dev_league_game(d.get("prospect_name")))

@app.route('/api/social_media_feed')
def api_social_media_feed():
    return jsonify({"success": True, "feed": SIM_STATE.get("social_media", [])[-30:]})

@app.route('/api/generate_social_event', methods=['POST'])
def api_generate_social_event():
    d = request.json or {}
    return jsonify({"success": True, "post": generate_social_media_event(d.get("player_name"))})

@app.route('/api/cap_sheet_projection')
def api_cap_sheet_projection():
    return jsonify({"success": True, **cap_sheet_projection(request.args.get("team", SIM_STATE["user_team"]),
                                                              safe_int(request.args.get("years"), 5))})

@app.route('/api/whatif/save', methods=['POST'])
def api_whatif_save():
    d = request.json or {}
    return jsonify(save_whatif_branch(d.get("label", "Untitled Branch"), safe_int(d.get("from_year"), SIM_STATE["year"])))

@app.route('/api/whatif/list')
def api_whatif_list():
    return jsonify({"success": True, "branches": list_whatif_branches()})

@app.route('/api/toggle_coaching_career_mode', methods=['POST'])
def api_toggle_coaching_career_mode():
    d = request.json or {}
    return jsonify(toggle_coaching_career_mode(d.get("enabled", False), d.get("team")))

@app.route('/api/lineup_synergy', methods=['POST'])
def api_lineup_synergy():
    d = request.json or {}
    return jsonify(lineup_synergy(d.get("players", [])))

@app.route('/api/call_timeout', methods=['POST'])
def api_call_timeout():
    d = request.json or {}
    return jsonify(call_timeout(d.get("team", SIM_STATE["user_team"])))

@app.route('/api/run_combine_minigame', methods=['POST'])
def api_run_combine_minigame():
    d = request.json or {}
    return jsonify(run_combine_minigame(d.get("prospect_name"), d.get("drill"), d.get("user_taps", 10)))

@app.route('/api/set_big_board_rank', methods=['POST'])
def api_set_big_board_rank():
    d = request.json or {}
    return jsonify(set_custom_big_board_rank(d.get("prospect_name"), safe_int(d.get("rank"), 0)))

@app.route('/api/big_board')
def api_big_board():
    return jsonify({"success": True, "board": get_big_board()})

@app.route('/api/awards_race')
def api_awards_race():
    return jsonify({"success": True, **awards_race_widget()})

@app.route('/api/gm_press_conference', methods=['POST'])
def api_gm_press_conference():
    d = request.json or {}
    return jsonify(hold_press_conference(d.get("team", SIM_STATE["user_team"]), d.get("option_id"), d.get("context", "")))

@app.route('/api/gm_press_conference_options')
def api_gm_press_conference_options():
    return jsonify({"success": True, "options": PRESS_CONFERENCE_OPTIONS})

@app.route('/api/set_difficulty', methods=['POST'])
def api_set_difficulty():
    d = request.json or {}
    return jsonify(set_difficulty(d.get("setting"), d.get("value", 50)))

@app.route('/api/season_recap')
def api_season_recap():
    return jsonify(season_recap())

@app.route('/api/assign_nickname', methods=['POST'])
def api_assign_nickname():
    d = request.json or {}
    return jsonify(assign_nickname(d.get("player_name"), d.get("nickname")))

@app.route('/api/set_theme', methods=['POST'])
def api_set_theme():
    d = request.json or {}
    return jsonify(set_user_theme(d.get("theme")))


# ==========================================================
# UPGRADE BATCH 8 -- next 20 major + 20 minor systems
# ==========================================================

# ---------- Major #1: In-Season Cup Tournament ----------
# NOTE: the Cup now runs automatically, integrated into the real calendar --
# see setup_in_season_cup() / cup_process_matchup() / cup_maybe_finalize_group_stage()
# near build_schedule(). No manual "run group stage / run knockout" triggers.


# ---------- Major #2: All-Star Draft Captains ----------
def run_all_star_captains_draft():
    if not SIM_STATE.get("all_star"):
        return {"success": False, "reason": "Run All-Star Weekend first."}
    pool = SIM_STATE["all_star"]["east_roster"] + SIM_STATE["all_star"]["west_roster"]
    pool_sorted = sorted(pool, key=lambda n: -SIM_STATE["players"][n]["rating"])
    captain_a, captain_b = pool_sorted[0], pool_sorted[1]
    remaining = [p for p in pool_sorted[2:]]
    team_a, team_b = [captain_a], [captain_b]
    turn = 0
    for p in remaining:
        (team_a if turn % 2 == 0 else team_b).append(p)
        turn += 1
    return {"success": True, "captain_a": captain_a, "team_a": team_a, "captain_b": captain_b, "team_b": team_b}


# ---------- Major #20 (Skills Challenge, grouped with All-Star content) ----------
def run_skills_challenge():
    active = [p for p in SIM_STATE["players"].values() if not p["retired"] and p.get("team")]
    field = sorted(active, key=lambda p: -(p["attributes"].get("Ball Handling", 60) + p["attributes"].get("Passing Accuracy", 60) + p["attributes"].get("Speed", 60)))[:6]
    scores = {p["name"]: round((p["attributes"].get("Ball Handling", 60) + p["attributes"].get("Passing Accuracy", 60) + p["attributes"].get("Speed", 60)) / 3 * 0.9 + random.uniform(0, 15), 1) for p in field}
    champ = max(scores, key=scores.get)
    push_news("🎯", f"{champ} wins the Skills Challenge.", kind="milestone")
    return {"success": True, "field": scores, "champion": champ}


# ---------- Major #3: Buyout Market ----------
def enter_buyout_market(player_name, remaining_salary):
    p = SIM_STATE["players"].get(player_name)
    if not p or p.get("team"):
        return {"success": False, "reason": "Player must already be waived to negotiate a buyout."}
    buyout_pct = clamp(50 + (99 - p["rating"]) * 0.3, 40, 90)
    buyout_amount = round(remaining_salary * buyout_pct / 100, 1)
    entry = {"player": player_name, "remaining_salary": remaining_salary, "buyout_amount": buyout_amount, "year": SIM_STATE["year"]}
    SIM_STATE.setdefault("buyout_market", []).append(entry)
    push_news("💸", f"{player_name} agrees to a buyout, becomes an unrestricted free agent.", kind="transaction")
    return {"success": True, **entry}


# ---------- Major #4: Player Trade Request / Empowerment ----------
def submit_trade_request(player_name, reason="wants a bigger role"):
    p = SIM_STATE["players"].get(player_name)
    if not p or not p.get("team"):
        return {"success": False, "reason": "Player not found or not on a roster."}
    entry = {"player": player_name, "team": p["team"], "reason": reason, "year": SIM_STATE["year"], "resolved": False}
    SIM_STATE.setdefault("trade_requests", []).append(entry)
    fa = SIM_STATE.setdefault("fan_approval", {})
    fa[p["team"]] = clamp(fa.get(p["team"], 55) - 4, 0, 100)
    push_news("📰", f"{player_name} has requested a trade from {p['team']} ({reason}).", kind="drama")
    return {"success": True, **entry}


def active_trade_requests():
    return [r for r in SIM_STATE.get("trade_requests", []) if not r["resolved"]]


# ---------- Major #5: Create-a-Player ----------
def create_custom_player(name, position, attributes_overrides=None, team_name=None):
    if position not in POSITIONS:
        return {"success": False, "reason": f"Position must be one of {POSITIONS}."}
    base_rating = 68
    potential = random.randint(70, 90)
    p = make_player(position, 22, base_rating, potential, team_name if team_name in NBA_TEAMS else None,
                     SIM_STATE["year"], SIM_STATE["year"], tier="vet")
    p["name"] = name
    p["is_custom"] = True
    if attributes_overrides:
        for k, v in attributes_overrides.items():
            if k in p["attributes"]:
                p["attributes"][k] = clamp(v)
        p["rating"] = calc_rating(p["attributes"])
    SIM_STATE["players"][name] = p
    SIM_STATE.setdefault("custom_players", []).append(name)
    push_news("🆕", f"Custom player {name} ({position}) has entered the league.", kind="league_office")
    return {"success": True, "player": name, "rating": p["rating"]}


# ---------- Major #6: Fantasy Draft League Mode ----------
def run_fantasy_draft_scramble():
    """Pulls every active, non-retired player into one pool and redeals them
    across all 30 teams in a snake draft order -- an instant reshuffled league."""
    pool = [p["name"] for p in SIM_STATE["players"].values() if not p.get("retired")]
    random.shuffle(pool)
    for p_name in pool:
        SIM_STATE["players"][p_name]["team"] = None
    teams = list(NBA_TEAMS)
    idx = 0
    direction = 1
    rosters = {t: [] for t in teams}
    order = teams[:]
    while pool:
        if idx >= len(order):
            order.reverse()
            idx = 0
        team = order[idx]
        if len(rosters[team]) < 15 and pool:
            player_name = pool.pop()
            SIM_STATE["players"][player_name]["team"] = team
            rosters[team].append(player_name)
        idx += 1
        if all(len(r) >= 15 for r in rosters.values()) or not pool:
            break
    SIM_STATE["fantasy_draft_mode"] = True
    push_news("🔀", "Fantasy Draft complete -- every roster in the league has been reshuffled.", kind="league_office")
    return {"success": True, "rosters_filled": {t: len(rosters[t]) for t in teams}}


# ---------- Major #7: Summer League ----------
def simulate_summer_league():
    prospects = SIM_STATE.get("draft_class", []) + [p for p in SIM_STATE["players"].values() if p.get("age", 30) <= 23 and not p.get("retired")]
    standings = {}
    for t in NBA_TEAMS:
        wins = random.randint(0, 5)
        standings[t] = {"wins": wins, "losses": 5 - wins}
    breakout = random.choice(prospects)["name"] if prospects else None
    SIM_STATE["summer_league"] = {"year": SIM_STATE["year"], "standings": standings, "breakout_performer": breakout}
    if breakout:
        push_news("☀️", f"Summer League standout: {breakout} turns heads in Vegas.", kind="milestone")
    return SIM_STATE["summer_league"]


# ---------- Major #8: Preseason ----------
def simulate_preseason_games(num_games=4):
    results = []
    for _ in range(num_games):
        home, away = random.sample(NBA_TEAMS, 2)
        home_score, away_score = random.randint(95, 125), random.randint(95, 125)
        results.append({"home": home, "away": away, "home_score": home_score, "away_score": away_score})
    SIM_STATE.setdefault("preseason_games", []).extend(results)
    return {"success": True, "games": results}


# ---------- Major #9: Global Games ----------
GLOBAL_GAME_CITIES = ["London", "Paris", "Mexico City", "Tokyo", "Manila", "Abu Dhabi", "Sao Paulo"]


def simulate_global_game():
    city = random.choice(GLOBAL_GAME_CITIES)
    home, away = random.sample(NBA_TEAMS, 2)
    home_score, away_score = random.randint(98, 122), random.randint(98, 122)
    entry = {"city": city, "home": home, "away": away, "home_score": home_score, "away_score": away_score, "year": SIM_STATE["year"]}
    SIM_STATE.setdefault("global_games", []).append(entry)
    push_news("🌍", f"NBA Global Games {city}: {home} {home_score} - {away_score} {away}.", kind="league_office")
    return entry


# ---------- Major #10: Media Day ----------
MEDIA_DAY_QUOTE_TEMPLATES = [
    "\"This is the year, no more excuses.\"", "\"I just want to stay healthy and let the results speak.\"",
    "\"We added exactly what we needed this summer.\"", "\"I'm in the best shape of my career.\"",
    "\"The expectations are high, and I like it that way.\"",
]


def hold_media_day(team_name):
    roster = team_roster(team_name)
    quotes = []
    for p in random.sample(roster, k=min(3, len(roster))):
        quotes.append({"player": p["name"], "quote": random.choice(MEDIA_DAY_QUOTE_TEMPLATES)})
    entry = {"team": team_name, "year": SIM_STATE["year"], "quotes": quotes}
    SIM_STATE.setdefault("media_day_log", []).append(entry)
    return {"success": True, **entry}


# ---------- Major #11: Legacy Score / Dynasty Rating ----------
def legacy_score(player_name):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    awards = len(p.get("career_awards", []))
    championships = sum(1 for a in p.get("career_awards", []) if "Champion" in a.get("award", ""))
    score = p.get("rating", 60) * 0.4 + awards * 4 + championships * 12 + p.get("all_star_selections", 0) * 3
    tier = "All-Time Great" if score > 120 else "Franchise Legend" if score > 90 else "Solid Vet" if score > 60 else "Rotation Player"
    return {"success": True, "player": player_name, "legacy_score": round(score, 1), "tier": tier}


def team_dynasty_rating(team_name):
    rec = SIM_STATE.get("team_records", {}).get(team_name, {})
    championships = rec.get("championships", 0)
    wins, losses = SIM_STATE["teams"].get(team_name, {}).get("wins", 0), SIM_STATE["teams"].get(team_name, {}).get("losses", 0)
    win_pct = wins / max(1, wins + losses)
    score = championships * 20 + win_pct * 50
    return {"team": team_name, "dynasty_score": round(score, 1), "championships": championships}


# ---------- Major #12: Hall of Fame Ballot Voting ----------
def add_to_hof_ballot(player_name):
    p = SIM_STATE["players"].get(player_name)
    if not p or not p.get("retired"):
        return {"success": False, "reason": "Only retired players can be added to the ballot."}
    ballot = SIM_STATE.setdefault("hall_of_fame_ballot", {})
    ballot[player_name] = {"votes_pct": 0.0, "year_on_ballot": 1}
    return {"success": True, "player": player_name}


def tally_hof_vote():
    ballot = SIM_STATE.setdefault("hall_of_fame_ballot", {})
    inducted = []
    for name, entry in list(ballot.items()):
        p = SIM_STATE["players"].get(name, {})
        base = p.get("rating", 60) + len(p.get("career_awards", [])) * 3
        entry["votes_pct"] = round(min(100, base * 0.6 + random.uniform(-5, 5)), 1)
        entry["year_on_ballot"] += 1
        if entry["votes_pct"] >= 75:
            inducted.append(name)
            SIM_STATE.setdefault("hall_of_fame", []).append({
                "player": name, "year": SIM_STATE["year"], "votes_pct": entry["votes_pct"],
                "seasons": p.get("age", 35) - 22, "position": p.get("position"), "team": p.get("last_team", p.get("team")),
            })
            ballot.pop(name, None)
            push_news("🏛️", f"{name} is inducted into the Hall of Fame with {entry['votes_pct']}% of the vote!", kind="milestone")
    return {"success": True, "inducted": inducted, "ballot": ballot}


# ---------- Major #13/#14/#15/#17: Arena naming, concessions, jersey patches, mascots ----------
NAMING_RIGHTS_SPONSORS = ["Zenith Financial", "Northstar Insurance", "Vertex Energy", "Coral Wireless", "Titan Bank"]
MASCOT_POOL = ["Thunderpaw", "Blaze", "Ridgeback", "Sky Talon", "Ironjaw", "Vortex", "Comet", "Grizz"]


def set_arena_naming_rights(team_name):
    sponsor = random.choice(NAMING_RIGHTS_SPONSORS)
    value = round(random.uniform(4.0, 25.0), 1)
    arena_name = f"{sponsor.split()[0]} Center"
    SIM_STATE.setdefault("arena_names", {})[team_name] = {"arena_name": arena_name, "sponsor": sponsor, "annual_value": value}
    push_news("🏟️", f"{team_name}'s arena is now {arena_name} in a naming-rights deal worth ${value}M/yr.", kind="business")
    return {"success": True, "team": team_name, "arena_name": arena_name, "sponsor": sponsor, "annual_value": value}


def sign_jersey_patch_deal(team_name):
    sponsor = random.choice(SPONSOR_POOL)
    value = round(random.uniform(3.0, 12.0), 1)
    SIM_STATE.setdefault("jersey_patches", {})[team_name] = {"sponsor": sponsor, "annual_value": value}
    return {"success": True, "team": team_name, "sponsor": sponsor, "annual_value": value}


def merch_and_concessions_revenue(team_name):
    fan_approval = SIM_STATE.get("fan_approval", {}).get(team_name, 55)
    merch = round(fan_approval * 0.08 + random.uniform(0, 2), 1)
    concessions = round(fan_approval * 0.05 + random.uniform(0, 1.5), 1)
    return {"team": team_name, "merchandise_revenue_millions": merch, "concessions_revenue_millions": concessions}


def assign_team_mascot(team_name, name=None):
    SIM_STATE.setdefault("team_mascots", {})[team_name] = name or random.choice(MASCOT_POOL)
    return {"success": True, "team": team_name, "mascot": SIM_STATE["team_mascots"][team_name]}


# ---------- Major #16: Advanced Analytics Dashboard ----------
def advanced_analytics(player_name):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    s = p["stats"]
    gp = max(1, s.get("GP", 0))
    ts_pct = round(100 * s.get("PTS", 0) / max(1, 2 * (s.get("FGA", 1) + 0.44 * s.get("FTA", 0))), 1)
    per_proxy = round((s.get("PTS", 0) + s.get("REB", 0) + s.get("AST", 0) * 1.5 + s.get("STL", 0) * 2 + s.get("BLK", 0) * 2 - s.get("TOV", 0)) / gp, 1)
    clutch_rating = round(p.get("attributes", {}).get("Clutch Factor", 60) * 0.6 + per_proxy * 0.4, 1)
    return {"success": True, "player": player_name, "true_shooting_pct": ts_pct, "per_estimate": per_proxy,
            "clutch_net_rating_estimate": clutch_rating}


# ---------- Major #18: Executive of the Year ----------
def award_executive_of_the_year():
    best_team, best_score = None, -999
    for team, cfg in SIM_STATE["teams"].items():
        wins, losses = cfg.get("wins", 0), cfg.get("losses", 0)
        cap_efficiency = wins / max(1, cfg.get("cap_space", 1) if cfg.get("cap_space", 0) > 0 else 1)
        score = wins - losses + cap_efficiency
        if score > best_score:
            best_score, best_team = score, team
    if not best_team:
        return {"success": False, "reason": "No season data yet."}
    entry = {"year": SIM_STATE["year"], "team": best_team}
    SIM_STATE.setdefault("executive_of_the_year", []).append(entry)
    push_news("🏅", f"{best_team}'s front office named Executive of the Year.", kind="award")
    return {"success": True, **entry}


# ---------- Major #19: Coach Hot Seat / Firing System ----------
def update_coach_hot_seat(team_name):
    cfg = SIM_STATE["teams"].get(team_name, {})
    wins, losses = cfg.get("wins", 0), cfg.get("losses", 0)
    win_pct = wins / max(1, wins + losses)
    heat = SIM_STATE.setdefault("coach_hot_seat", {})
    current = heat.get(team_name, 20)
    target = clamp((1 - win_pct) * 100, 0, 100)
    heat[team_name] = round(current + (target - current) * 0.15, 1)
    return {"team": team_name, "heat": heat[team_name]}


def maybe_fire_coach(team_name):
    heat = SIM_STATE.get("coach_hot_seat", {}).get(team_name, 0)
    if heat >= 85 and random.random() < 0.25:
        old_coach = SIM_STATE["teams"][team_name].get("coach", "the head coach")
        new_coach = f"Coach {random.choice(LAST_NAMES)}"
        SIM_STATE["teams"][team_name]["coach"] = new_coach
        SIM_STATE["coach_hot_seat"][team_name] = 15
        push_news("🔥", f"{team_name} fire {old_coach} and promote {new_coach} to head coach.", kind="league_office")
        return {"fired": True, "old_coach": old_coach, "new_coach": new_coach}
    return {"fired": False, "heat": heat}


# ---------- Minor #1: Hustle stats ----------
def record_hustle_stats(player_name, deflections=0, charges_taken=0, loose_balls=0):
    log = SIM_STATE.setdefault("hustle_stats", {}).setdefault(player_name, {"deflections": 0, "charges_taken": 0, "loose_balls": 0})
    log["deflections"] += deflections
    log["charges_taken"] += charges_taken
    log["loose_balls"] += loose_balls
    return log


def hustle_leaderboard(top_n=10):
    rows = [{"player": name, **stats, "total": sum(stats.values())} for name, stats in SIM_STATE.get("hustle_stats", {}).items()]
    rows.sort(key=lambda r: -r["total"])
    return rows[:top_n]


# ---------- Minor #2: Walk-up / entrance sound motifs ----------
def assign_walk_up_motif(player_name):
    rng = random.Random(player_name)
    motif = {"root_freq": rng.choice([220, 262, 294, 330, 349, 392]), "pattern": rng.choice(["ascending", "descending", "bounce"])}
    SIM_STATE.setdefault("walk_up_motifs", {})[player_name] = motif
    return {"success": True, "player": player_name, "motif": motif}


# ---------- Minor #3: Clutch Player of the Year ----------
def award_clutch_player_of_the_year():
    ranked = sorted(_active_players(), key=lambda p: -p["attributes"].get("Clutch Factor", 60))[:1]
    if not ranked:
        return {"success": False}
    winner = ranked[0]["name"]
    push_news("🥶", f"{winner} named Clutch Player of the Year.", kind="award")
    return {"success": True, "player": winner}


# ---------- Minor #4 / #5: Trade & Draft Night Grades ----------
def grade_trade(team_a, players_a_get, team_b, players_b_get):
    def side_value(names):
        return sum(SIM_STATE["players"].get(n, {}).get("rating", 60) for n in names)
    val_a, val_b = side_value(players_a_get), side_value(players_b_get)
    diff = val_a - val_b
    if abs(diff) <= 3:
        grades = {team_a: "B", team_b: "B"}
    else:
        winner, loser = (team_a, team_b) if diff > 0 else (team_b, team_a)
        winner_grade = "A" if abs(diff) > 15 else "B"
        loser_grade = "D" if abs(diff) > 15 else "C"
        grades = {winner: winner_grade, loser: loser_grade}
    entry = {"team_a": team_a, "team_b": team_b, "grades": grades, "year": SIM_STATE["year"]}
    SIM_STATE.setdefault("trade_grades", []).append(entry)
    return {"success": True, **entry}


def grade_draft_pick(pick_no, team_name, prospect_name):
    p = next((pr for pr in SIM_STATE.get("draft_class", []) if pr["name"] == prospect_name), None)
    projected_slot = p.get("projected_pick", pick_no) if p else pick_no
    value_gap = projected_slot - pick_no
    letter = "A" if value_gap >= 5 else "B" if value_gap >= 0 else "C" if value_gap >= -5 else "D"
    year_grades = SIM_STATE.setdefault("draft_night_grades", {}).setdefault(SIM_STATE["year"], {})
    year_grades[pick_no] = {"team": team_name, "prospect": prospect_name, "grade": letter}
    return {"success": True, "pick_no": pick_no, "team": team_name, "prospect": prospect_name, "grade": letter}


# ---------- Minor #6: Injury history page ----------
def injury_history(player_name):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    return {"success": True, "player": player_name, "current_injury": p.get("injury"),
            "durability": p.get("attributes", {}).get("Durability"), "reinjury_window": p.get("reinjury_window", 0)}


# ---------- Minor #7: Morale history (exposes existing per-week data if tracked, else current snapshot) ----------
def morale_snapshot(player_name):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    return {"success": True, "player": player_name, "morale": p.get("morale", 70), "fatigue": p.get("fatigue", 0)}


# ---------- Minor #8: Franchise value estimator ----------
def estimate_franchise_value(team_name):
    rec = SIM_STATE.get("team_records", {}).get(team_name, {})
    fan_approval = SIM_STATE.get("fan_approval", {}).get(team_name, 55)
    championships = rec.get("championships", 0)
    base_value = 1800  # $M baseline modern-era franchise value
    value = base_value + championships * 120 + (fan_approval - 55) * 8
    return {"team": team_name, "estimated_value_millions": round(max(400, value), 1)}


# ---------- Minor #9: Season ticket loyalty tier ----------
def update_ticket_loyalty_tier(team_name):
    fan_approval = SIM_STATE.get("fan_approval", {}).get(team_name, 55)
    tier = "Platinum" if fan_approval >= 85 else "Gold" if fan_approval >= 65 else "Silver" if fan_approval >= 45 else "Bronze"
    SIM_STATE.setdefault("ticket_loyalty_tier", {})[team_name] = tier
    return {"team": team_name, "tier": tier}


# ---------- Minor #10: Standings tiebreaker display ----------
def standings_tiebreaker(team_a, team_b):
    a, b = SIM_STATE["teams"].get(team_a, {}), SIM_STATE["teams"].get(team_b, {})
    a_pct = a.get("wins", 0) / max(1, a.get("wins", 0) + a.get("losses", 0))
    b_pct = b.get("wins", 0) / max(1, b.get("wins", 0) + b.get("losses", 0))
    if a_pct != b_pct:
        leader = team_a if a_pct > b_pct else team_b
        reason = "Better winning percentage"
    else:
        leader = random.choice([team_a, team_b])
        reason = "Coin flip (head-to-head data not tracked in this build)"
    return {"team_a": team_a, "team_b": team_b, "leader": leader, "reason": reason}


# ---------- Minor #11: Podcast-style GM roundtable flavor text ----------
ROUNDTABLE_TAKES = [
    "\"{team} are the biggest surprise of the season so far.\"",
    "\"I don't think {team} have done enough at the deadline.\"",
    "\"Watch out for {team} in the second half -- their young core is peaking.\"",
    "\"{team} need to make a move before it's too late.\"",
]


def generate_podcast_roundtable():
    team = random.choice(NBA_TEAMS)
    take = random.choice(ROUNDTABLE_TAKES).format(team=team)
    return {"segment": "GM Roundtable", "take": take}


# ---------- Minor #12: Team hype video flavor text ----------
def generate_hype_video_script(team_name):
    identity = SIM_STATE.get("team_identity", {}).get(team_name) or compute_team_identity(team_name)
    return {"team": team_name, "script": f"[Arena lights dim] ... a {identity.lower()} identity forged all season long ... "
                                          f"THIS is {team_name} basketball!"}


# ---------- Minor #13: Broadcast score-bug style toggle ----------
SCORE_BUG_STYLES = ["Classic", "Modern Minimal", "Retro", "Full Stats"]


def set_score_bug_style(style):
    if style not in SCORE_BUG_STYLES:
        return {"success": False, "reason": f"Choose from {SCORE_BUG_STYLES}."}
    SIM_STATE["score_bug_style"] = style
    return {"success": True, "style": style}


# ---------- Minor #14: Two-way roster spot indicator ----------
def two_way_roster_report(team_name):
    roster = team_roster(team_name)
    return {"team": team_name, "two_way_players": [p["name"] for p in roster if p.get("two_way")],
            "standard_count": len([p for p in roster if not p.get("two_way")])}


# ---------- Minor #15: All-Star fan vote totals (flavor) ----------
def simulate_fan_vote():
    active = [p for p in SIM_STATE["players"].values() if not p["retired"] and p.get("team")]
    top = sorted(active, key=lambda p: -p["rating"])[:10]
    totals = {p["name"]: random.randint(800000, 4500000) for p in top}
    SIM_STATE["fan_vote_totals"] = totals
    return {"success": True, "totals": totals}


# ---------- Minor #16: Retired number ceremony script ----------
def retired_number_ceremony_script(player_name, team_name, jersey_number):
    return {"script": f"The lights dim at center court. \"{player_name}'s number {jersey_number} will hang "
                       f"from these rafters forever\" -- the PA announcer's voice echoes as the banner rises for {team_name}."}


# ---------- Minor #17: Player legacy card (combines legacy score + HOF chance) ----------
def player_legacy_card(player_name):
    legacy = legacy_score(player_name)
    if not legacy.get("success"):
        return legacy
    hof_chance = clamp(legacy["legacy_score"] * 0.6, 0, 99)
    return {**legacy, "hall_of_fame_chance_pct": round(hof_chance, 1)}


# ---------- Minor #18: Road-trip atmosphere flavor ----------
ATMOSPHERE_FLAVOR = ["a hostile road environment", "a lifeless, half-empty road building", "a raucous road crowd smelling an upset"]


def road_atmosphere_flavor(team_name):
    log = SIM_STATE.get("travel_log", {}).get(team_name, {})
    flavor = random.choice(ATMOSPHERE_FLAVOR)
    return {"team": team_name, "consecutive_road": log.get("consecutive_road", 0), "flavor": flavor}


# ---------- Minor #19: Coach confidence meter (inverse of hot seat) ----------
def coach_confidence(team_name):
    heat = SIM_STATE.get("coach_hot_seat", {}).get(team_name, 20)
    return {"team": team_name, "confidence_pct": round(100 - heat, 1)}


# ---------- Minor #20: League-wide milestone watch list ----------
MILESTONE_TARGETS = [1000, 5000, 10000, 15000, 20000, 25000, 30000]


def milestone_watch_list():
    watch = []
    for p in _active_players():
        career_pts = sum(h.get("PPG", 0) * 30 for h in p.get("history", [])) if p.get("history") else 0  # rough proxy
        career_pts += p["stats"].get("PTS", 0)
        for target in MILESTONE_TARGETS:
            if 0 < target - career_pts <= 400:
                watch.append({"player": p["name"], "team": p["team"], "milestone": f"{target} career points",
                               "points_away": round(target - career_pts)})
                break
    return watch


# ==========================================================
# UPGRADE BATCH 8 -- API routes
# ==========================================================

@app.route('/api/trade_finder_search')
def api_trade_finder_search():
    """2K-style Trade Finder -- search every other team's roster by position,
    rating, salary, and age instead of digging through 29 rosters by hand."""
    team = request.args.get("team", SIM_STATE.get("user_team"))
    position = request.args.get("position", "")
    min_rating = safe_int(request.args.get("min_rating"), 0)
    max_rating = safe_int(request.args.get("max_rating"), 99)
    max_salary = safe_float(request.args.get("max_salary"), 999)
    max_age = safe_int(request.args.get("max_age"), 99)
    query = (request.args.get("q") or "").strip().lower()
    attributes_csv = request.args.get("attributes", "") or request.args.get("attribute", "")
    attributes = [a.strip() for a in attributes_csv.split(",") if a.strip()]
    min_attribute = safe_int(request.args.get("min_attribute"), 0)
    hide_untouchable = request.args.get("hide_untouchable", "1") != "0"
    my_needs = set(team_positional_needs(team)) if team else set()

    results = []
    for p in SIM_STATE["players"].values():
        if p["retired"] or not p["team"] or p["team"] == team:
            continue
        if position and p["position"] != position:
            continue
        if not (min_rating <= p["rating"] <= max_rating):
            continue
        if p.get("age", 0) > max_age:
            continue
        salary = (p.get("contract") or {}).get("salary", 0) or 0
        if salary > max_salary:
            continue
        if query and query not in p["name"].lower():
            continue
        attr_values = []
        if attributes:
            player_attrs = p.get("attributes") or {}
            meets_all = True
            for a in attributes:
                v = player_attrs.get(a)
                if v is None or v < min_attribute:
                    meets_all = False
                    break
                attr_values.append({"name": a, "value": v})
            if not meets_all:
                continue
        is_untouchable = p["name"] in team_untouchables(p["team"])
        if hide_untouchable and is_untouchable:
            continue
        results.append({
            "name": p["name"], "team": p["team"], "position": p["position"], "rating": p["rating"],
            "age": p.get("age"), "salary": salary, "years_left": (p.get("contract") or {}).get("years_left"),
            "on_trade_block": p["name"] in SIM_STATE.get("trade_block", []),
            "untouchable": is_untouchable,
            "fills_need": p["position"] in my_needs,
            "attribute_values": attr_values,
            "is_watched": p["name"] in SIM_STATE["trade_targets"].get(team, []),
        })
    if attributes:
        results.sort(key=lambda r: (-r["fills_need"], -(sum(av["value"] for av in r["attribute_values"]) / len(r["attribute_values"]))))
    else:
        results.sort(key=lambda r: (-r["fills_need"], -r["rating"]))
    return jsonify({"success": True, "count": len(results), "results": results[:60]})


@app.route('/api/attribute_options')
def api_attribute_options():
    """Attribute names for the Trade Finder's attribute-search dropdown."""
    sample = next((p for p in SIM_STATE["players"].values() if p.get("attributes")), None)
    return jsonify({"success": True, "attributes": sorted((sample or {}).get("attributes", {}).keys())})


@app.route('/api/find_trade_partners')
def api_find_trade_partners():
    """2K-style Trade Finder: given a package of YOUR players, rank every
    other team by how much they'd want that package, and suggest what each
    would realistically send back.

    BUGFIX (major): this used to build candidate return packages against a
    hand-rolled 0.85-of-my-own-valuation threshold that didn't match the
    real acceptance formula in evaluate_and_execute_trade at all (which
    values BOTH sides through the AI team's own lens against a genuine
    0.72-0.97 threshold, plus a separate sanity-check guardrail on top) --
    so Trade Finder would routinely surface offers that then got rejected
    the moment you actually tried to negotiate them. Every offer returned
    here is now validated with the exact same value formula, threshold, and
    sanity check evaluate_and_execute_trade uses, so if it's shown here,
    proposing it as-is in Trade Center will go through.
    """
    team = request.args.get("team", SIM_STATE.get("user_team"))
    players_csv = request.args.get("players", "")
    picks_csv = request.args.get("picks", "")
    my_players = [p.strip() for p in players_csv.split(",") if p.strip()]
    my_players = [n for n in my_players if n in SIM_STATE["players"]]
    my_picks = [p.strip() for p in picks_csv.split(",") if p.strip()]
    my_picks = [pid for pid in my_picks if pid in SIM_STATE["draft_picks"]]
    if not my_players and not my_picks:
        return jsonify({"success": False, "reason": "Select at least one of your players or picks first."})

    offers = []
    for other in NBA_TEAMS:
        if other == team:
            continue
        needs = team_positional_needs(other)
        fills_need = any(SIM_STATE["players"][n]["position"] in needs for n in my_players)

        # Both sides of the trade, valued through the AI team's own lens --
        # exactly how evaluate_and_execute_trade grades a real proposal.
        value_a_sends = contextual_package_value(my_players, my_picks, other)
        interest_score = value_a_sends * (1.15 if fills_need else 1.0)

        threshold = trade_acceptance_threshold(other)
        untouchables = team_untouchables(other)
        target = value_a_sends * threshold

        # UPGRADE (major, based on direct feedback): this used to greedily
        # grab the AI's WEAKEST players first and pile picks on top to
        # cover the gap -- technically clears the value-formula threshold,
        # but produces absurd-looking offers like "two 78 OVR players for a
        # 61 and a 58 plus three firsts" that no real front office would
        # ever propose, even if the raw numbers "worked." Real trade
        # returns are proportionate: a star comes back for another good
        # player (or two), not a stack of bench scrubs plus draft capital
        # doing all the work.
        #
        # Now: build several realistic candidate packages (their single
        # best trade chip, their best pair, and a pair that holds back
        # their #1 asset in case a team wouldn't move its best player) from
        # their top 8 movable players, top off with picks only if still
        # short, and keep whichever valid candidate is CLOSEST to a fair
        # value match (least overshoot) instead of whichever used the
        # fewest/weakest pieces.
        candidates_pool = sorted(
            [p for p in team_roster(other) if p["name"] not in untouchables and p["name"] not in my_players],
            key=lambda p: -p["rating"])[:8]

        def value_with_picks(names, max_picks):
            """Greedily add this team's best future picks until `names`
            clears `target`, capped at max_picks. Returns (value, pick_list)."""
            val = contextual_package_value(names, [], other) if names else 0.0
            picks_added = []
            if val < target and max_picks > 0:
                partner_picks = [(pid, pk) for pid, pk in SIM_STATE["draft_picks"].items()
                                  if pk["current_team"] == other and pk["year"] > SIM_STATE["year"]]
                partner_picks.sort(key=lambda item: (item[1]["round"], -pick_value(item[1])))
                for pid, pk in partner_picks:
                    if val >= target or len(picks_added) >= max_picks:
                        break
                    pv = pick_value(pk)
                    if pv <= 0:
                        continue
                    picks_added.append({"id": pid, "year": pk["year"], "round": pk["round"],
                                         "original_team": pk["original_team"], "protection": pk.get("protection", "None")})
                    val = contextual_package_value(names, [p["id"] for p in picks_added], other)
            return val, picks_added

        candidate_name_sets = []
        if len(candidates_pool) >= 1:
            candidate_name_sets.append([candidates_pool[0]["name"]])                       # their best chip alone
        if len(candidates_pool) >= 2:
            candidate_name_sets.append([candidates_pool[0]["name"], candidates_pool[1]["name"]])  # best pair
            candidate_name_sets.append([candidates_pool[1]["name"], candidates_pool[2]["name"]] if len(candidates_pool) >= 3 else [])  # holds back their #1 asset
        candidate_name_sets = [c for c in candidate_name_sets if c]

        best_candidate = None  # (overshoot, names, picks, value)
        for names in candidate_name_sets:
            val, picks_added = value_with_picks(names, max_picks=2)
            if val < target:
                continue  # doesn't clear the bar even with picks -- not viable
            overshoot = val - target
            if best_candidate is None or overshoot < best_candidate[0]:
                best_candidate = (overshoot, names, picks_added, val)

        if best_candidate is None:
            continue  # nothing on this roster can realistically match the ask
        _, package, pick_package, package_value = best_candidate

        if not package and not pick_package:
            continue
        # Final gate: run the EXACT same acceptance + legality checks
        # evaluate_and_execute_trade will run -- value/sanity AND roster
        # size, salary cap, no-trade clauses, and untradeable flags on both
        # sides -- so nothing gets suggested here that Negotiate would
        # reject for any reason. (Previously this endpoint didn't check
        # legality at all, so a value-fair offer could still blow the
        # user's roster past 15 players or violate the cap and get
        # rejected the moment it was actually proposed.)
        pick_ids = [p["id"] for p in pick_package]
        would_accept = value_a_sends >= package_value * threshold
        if untouchables and any(n in untouchables for n in package):
            would_accept = value_a_sends >= package_value * threshold * 1.6
        if would_accept:
            sane, _ = trade_passes_sanity_check(package, my_players, pick_ids)
            would_accept = sane
        if would_accept:
            my_roster_size = len(team_roster(team)) - len(my_players) + len(package)
            other_roster_size = len(team_roster(other)) - len(package) + len(my_players)
            ok1, _ = validate_trade_legality(team, my_players, my_picks, package, pick_ids, my_roster_size)
            ok2, _ = validate_trade_legality(other, package, pick_ids, my_players, my_picks, other_roster_size)
            would_accept = ok1 and ok2
        if not would_accept:
            continue

        offers.append({
            "team": other, "interest_score": round(interest_score, 1),
            "fills_need": fills_need, "suggested_return": package,
            "suggested_return_detail": [
                {"name": n, "position": SIM_STATE["players"][n]["position"], "rating": SIM_STATE["players"][n]["rating"]}
                for n in package
            ],
            "suggested_return_picks": pick_package,
            "return_value": round(package_value, 1),
        })
    offers.sort(key=lambda o: -o["interest_score"])
    return jsonify({"success": True, "players": my_players, "offers": offers[:8]})


@app.route('/api/shop_player')
def api_shop_player():
    """2K-style 'Shop This Player' -- reverse Trade Finder. Ranks every other
    team by how much they'd realistically value one of your players, using
    the same needs/contextual valuation the AI uses to judge real offers."""
    team = request.args.get("team", SIM_STATE.get("user_team"))
    player_name = request.args.get("player")
    player = SIM_STATE["players"].get(player_name)
    if not player:
        return jsonify({"success": False, "reason": "Player not found."})
    offers = []
    for other in NBA_TEAMS:
        if other == team:
            continue
        base_value = contextual_package_value([player_name], [], other)
        needs = team_positional_needs(other)
        interest = base_value * (1.15 if player["position"] in needs else 1.0)
        offers.append({"team": other, "interest_value": round(interest, 1), "fills_need": player["position"] in needs})
    offers.sort(key=lambda o: -o["interest_value"])
    return jsonify({"success": True, "player": player_name, "offers": offers[:10]})


@app.route('/api/cup_status')
def api_cup_status():
    cup = SIM_STATE.get("cup")
    if not cup:
        return jsonify({"success": False, "reason": "No Cup running yet."})
    return jsonify({"success": True, **cup})

@app.route('/api/all_star_captains_draft', methods=['POST'])
def api_all_star_captains_draft():
    return jsonify(run_all_star_captains_draft())

@app.route('/api/skills_challenge', methods=['POST'])
def api_skills_challenge():
    return jsonify(run_skills_challenge())

@app.route('/api/buyout_market')
def api_buyout_market():
    return jsonify({"success": True, "market": SIM_STATE.get("buyout_market", [])})

@app.route('/api/enter_buyout_market', methods=['POST'])
def api_enter_buyout_market():
    d = request.json or {}
    return jsonify(enter_buyout_market(d.get("player_name"), d.get("remaining_salary", 0)))

@app.route('/api/submit_trade_request', methods=['POST'])
def api_submit_trade_request():
    d = request.json or {}
    return jsonify(submit_trade_request(d.get("player_name"), d.get("reason", "wants a bigger role")))

@app.route('/api/trade_requests')
def api_trade_requests():
    return jsonify({"success": True, "requests": active_trade_requests()})

@app.route('/api/create_custom_player', methods=['POST'])
def api_create_custom_player():
    d = request.json or {}
    return jsonify(create_custom_player(d.get("name"), d.get("position"), d.get("attributes"), d.get("team")))

@app.route('/api/fantasy_draft_scramble', methods=['POST'])
def api_fantasy_draft_scramble():
    return jsonify(run_fantasy_draft_scramble())

@app.route('/api/summer_league', methods=['POST'])
def api_summer_league():
    return jsonify({"success": True, **simulate_summer_league()})

@app.route('/api/preseason_games', methods=['POST'])
def api_preseason_games():
    d = request.json or {}
    return jsonify(simulate_preseason_games(safe_int(d.get("num_games"), 4)))

@app.route('/api/global_game', methods=['POST'])
def api_global_game():
    return jsonify({"success": True, **simulate_global_game()})

@app.route('/api/media_day', methods=['POST'])
def api_media_day():
    d = request.json or {}
    return jsonify(hold_media_day(d.get("team", SIM_STATE["user_team"])))

@app.route('/api/legacy_score')
def api_legacy_score():
    return jsonify(legacy_score(request.args.get("player")))

@app.route('/api/team_dynasty_rating')
def api_team_dynasty_rating():
    return jsonify({"success": True, **team_dynasty_rating(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/hof_ballot/add', methods=['POST'])
def api_hof_ballot_add():
    d = request.json or {}
    return jsonify(add_to_hof_ballot(d.get("player_name")))

@app.route('/api/hof_ballot/tally', methods=['POST'])
def api_hof_ballot_tally():
    return jsonify(tally_hof_vote())

@app.route('/api/arena_naming_rights', methods=['POST'])
def api_arena_naming_rights():
    d = request.json or {}
    return jsonify(set_arena_naming_rights(d.get("team", SIM_STATE["user_team"])))

@app.route('/api/jersey_patch_deal', methods=['POST'])
def api_jersey_patch_deal():
    d = request.json or {}
    return jsonify(sign_jersey_patch_deal(d.get("team", SIM_STATE["user_team"])))

@app.route('/api/merch_concessions_revenue')
def api_merch_concessions_revenue():
    return jsonify({"success": True, **merch_and_concessions_revenue(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/assign_mascot', methods=['POST'])
def api_assign_mascot():
    d = request.json or {}
    return jsonify(assign_team_mascot(d.get("team", SIM_STATE["user_team"]), d.get("name")))

@app.route('/api/advanced_analytics')
def api_advanced_analytics():
    return jsonify(advanced_analytics(request.args.get("player")))

@app.route('/api/executive_of_the_year', methods=['POST'])
def api_executive_of_the_year():
    return jsonify(award_executive_of_the_year())

@app.route('/api/coach_hot_seat')
def api_coach_hot_seat():
    return jsonify({"success": True, **update_coach_hot_seat(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/maybe_fire_coach', methods=['POST'])
def api_maybe_fire_coach():
    d = request.json or {}
    return jsonify(maybe_fire_coach(d.get("team", SIM_STATE["user_team"])))

@app.route('/api/hustle_leaderboard')
def api_hustle_leaderboard():
    return jsonify({"success": True, "leaderboard": hustle_leaderboard()})

@app.route('/api/assign_walk_up_motif', methods=['POST'])
def api_assign_walk_up_motif():
    d = request.json or {}
    return jsonify(assign_walk_up_motif(d.get("player_name")))

@app.route('/api/clutch_player_of_the_year', methods=['POST'])
def api_clutch_player_of_the_year():
    return jsonify(award_clutch_player_of_the_year())

@app.route('/api/grade_trade', methods=['POST'])
def api_grade_trade():
    d = request.json or {}
    return jsonify(grade_trade(d.get("team_a"), d.get("players_a_get", []), d.get("team_b"), d.get("players_b_get", [])))

@app.route('/api/grade_draft_pick', methods=['POST'])
def api_grade_draft_pick():
    d = request.json or {}
    return jsonify(grade_draft_pick(safe_int(d.get("pick_no"), 1), d.get("team"), d.get("prospect_name")))

@app.route('/api/injury_history')
def api_injury_history():
    return jsonify(injury_history(request.args.get("player")))

@app.route('/api/morale_snapshot')
def api_morale_snapshot():
    return jsonify(morale_snapshot(request.args.get("player")))

@app.route('/api/franchise_value')
def api_franchise_value():
    return jsonify({"success": True, **estimate_franchise_value(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/ticket_loyalty_tier')
def api_ticket_loyalty_tier():
    return jsonify({"success": True, **update_ticket_loyalty_tier(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/standings_tiebreaker')
def api_standings_tiebreaker():
    return jsonify({"success": True, **standings_tiebreaker(request.args.get("team_a"), request.args.get("team_b"))})

@app.route('/api/podcast_roundtable')
def api_podcast_roundtable():
    return jsonify({"success": True, **generate_podcast_roundtable()})

@app.route('/api/hype_video_script')
def api_hype_video_script():
    return jsonify({"success": True, **generate_hype_video_script(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/set_score_bug_style', methods=['POST'])
def api_set_score_bug_style():
    d = request.json or {}
    return jsonify(set_score_bug_style(d.get("style")))

@app.route('/api/two_way_roster_report')
def api_two_way_roster_report():
    return jsonify({"success": True, **two_way_roster_report(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/simulate_fan_vote', methods=['POST'])
def api_simulate_fan_vote():
    return jsonify(simulate_fan_vote())

@app.route('/api/retired_number_ceremony_script')
def api_retired_number_ceremony_script():
    return jsonify({"success": True, **retired_number_ceremony_script(
        request.args.get("player"), request.args.get("team"), request.args.get("number", "00"))})

@app.route('/api/player_legacy_card')
def api_player_legacy_card():
    return jsonify(player_legacy_card(request.args.get("player")))

@app.route('/api/road_atmosphere')
def api_road_atmosphere():
    return jsonify({"success": True, **road_atmosphere_flavor(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/coach_confidence')
def api_coach_confidence():
    return jsonify({"success": True, **coach_confidence(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/milestone_watch_list')
def api_milestone_watch_list():
    return jsonify({"success": True, "watch_list": milestone_watch_list()})


# ==========================================================
# UPGRADE BATCH 11 -- next 50 systems
# ==========================================================

# ---------- 1: Restricted FA offer-sheet matching ----------
def submit_rfa_offer_sheet(player_name, offering_team, years, salary):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    original_team = p.get("last_team") or p.get("team")
    sheet = {"player": player_name, "offering_team": offering_team, "original_team": original_team,
              "years": years, "salary": salary, "year": SIM_STATE["year"], "resolved": False}
    SIM_STATE.setdefault("rfa_offer_sheets", []).append(sheet)
    push_news("📝", f"{offering_team} submit an offer sheet for RFA {player_name} ({years}yr/${salary}M).", kind="transaction")
    return {"success": True, **sheet}


def match_rfa_offer_sheet(player_name, match):
    sheet = next((s for s in SIM_STATE.get("rfa_offer_sheets", []) if s["player"] == player_name and not s["resolved"]), None)
    if not sheet:
        return {"success": False, "reason": "No pending offer sheet for that player."}
    sheet["resolved"] = True
    p = SIM_STATE["players"][player_name]
    if match:
        p["team"] = sheet["original_team"]
        p["contract"] = {"years": sheet["years"], "salary": sheet["salary"]}
        push_news("✅", f"{sheet['original_team']} match the offer sheet, retaining {player_name}.", kind="transaction")
    else:
        p["team"] = sheet["offering_team"]
        p["contract"] = {"years": sheet["years"], "salary": sheet["salary"]}
        push_news("➡️", f"{sheet['original_team']} decline to match -- {player_name} joins {sheet['offering_team']}.", kind="transaction")
    return {"success": True, "matched": match, "player": player_name}


# ---------- 2: Extend-and-trade ----------
def extend_and_trade(player_name, new_team, years, salary):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    old_team = p.get("team")
    p["team"] = new_team
    p["contract"] = {"years": years, "salary": salary}
    push_news("🔄", f"{player_name} is extended and traded from {old_team} to {new_team} ({years}yr/${salary}M).", kind="transaction")
    return {"success": True, "player": player_name, "from_team": old_team, "to_team": new_team}


# ---------- 3: Designated Rookie / Rose Rule eligibility ----------
def check_designated_rookie_eligibility(player_name):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    seasons_pro = max(0, p.get("age", 22) - 22)
    made_all_star = p.get("all_star_selections", 0) > 0
    eligible = seasons_pro <= 4 and (made_all_star or p.get("rating", 60) >= 88)
    if eligible:
        SIM_STATE.setdefault("designated_rookie", {})[player_name] = True
    return {"success": True, "player": player_name, "eligible": eligible, "seasons_pro": seasons_pro}


# ---------- 4: Supermax eligibility ----------
def check_supermax_eligibility(player_name):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    awards = p.get("career_awards", [])
    mvp_count = sum(1 for a in awards if "MVP" in a.get("award", "") and "Finals" not in a.get("award", ""))
    dpoy_count = sum(1 for a in awards if "Defensive Player" in a.get("award", ""))
    all_nba_count = sum(1 for a in awards if "All-NBA" in a.get("award", ""))
    eligible = mvp_count >= 1 or dpoy_count >= 1 or all_nba_count >= 2
    return {"success": True, "player": player_name, "eligible": eligible,
            "mvps": mvp_count, "dpoys": dpoy_count, "all_nba_teams": all_nba_count}


# ---------- 5: Two-way -> standard conversion: already implemented earlier in the file (see line ~4941) ----------


# ---------- 6: Player un-retirement ----------
def attempt_unretirement(player_name, team_name):
    p = SIM_STATE["players"].get(player_name)
    if not p or not p.get("retired"):
        return {"success": False, "reason": "Player is not retired."}
    if p.get("age", 40) > 42 or random.random() < 0.4:
        return {"success": False, "reason": f"{player_name} declines to come out of retirement."}
    p["retired"] = False
    p["team"] = team_name
    p["contract"] = {"years": 1, "salary": round(max(1.0, p.get("rating", 60) * 0.15) * era_salary_scale(), 1)}
    push_news("🔁", f"{player_name} comes out of retirement to sign with {team_name}!", kind="transaction")
    return {"success": True, "player": player_name, "team": team_name}


# ---------- 7: Practice facility tiers ----------
FACILITY_TIERS = {"Standard": 1.0, "Upgraded": 1.15, "State-of-the-Art": 1.3, "World Class": 1.5}


def upgrade_practice_facility(team_name, tier):
    if tier not in FACILITY_TIERS:
        return {"success": False, "reason": f"Choose from {list(FACILITY_TIERS)}."}
    cost = {"Standard": 0, "Upgraded": 15, "State-of-the-Art": 35, "World Class": 65}[tier]
    SIM_STATE.setdefault("team_facilities", {})[team_name] = tier
    push_news("🏋️", f"{team_name} upgrade their practice facility to {tier} tier (${cost}M).", kind="business")
    return {"success": True, "team": team_name, "tier": tier, "training_speed_bonus_pct": round((FACILITY_TIERS[tier] - 1) * 100, 1)}


# ---------- 8: Trade deadline countdown ----------
def trade_deadline_countdown():
    deadline_day = SIM_STATE.get("trade_deadline_day", 0)
    current_day = SIM_STATE.get("current_day", 0)
    days_left = max(0, deadline_day - current_day)
    return {"success": True, "days_until_deadline": days_left, "deadline_day": deadline_day,
            "is_deadline_day": days_left == 0}


# ---------- 9: Draft lottery ceremony ----------
def run_draft_lottery_ceremony():
    lottery_teams = sorted(NBA_TEAMS, key=lambda t: SIM_STATE["teams"].get(t, {}).get("wins", 41))[:14]
    weights = list(range(14, 0, -1))
    order = []
    pool = lottery_teams[:]
    pool_weights = weights[:]
    for _ in range(4):
        if not pool:
            break
        pick = random.choices(pool, weights=pool_weights, k=1)[0]
        idx = pool.index(pick)
        pool.pop(idx); pool_weights.pop(idx)
        order.append(pick)
    order += [t for t in lottery_teams if t not in order]
    push_news("🎱", f"Draft Lottery: {order[0]} win the No. 1 overall pick!", kind="league_office")
    return {"success": True, "lottery_order": order}


# ---------- 10: Draft class strength rating ----------
def draft_class_strength():
    prospects = SIM_STATE.get("draft_class", [])
    if not prospects:
        return {"success": False, "reason": "No draft class generated yet."}
    avg_rating = sum(p.get("rating", 60) for p in prospects) / len(prospects)
    elite_count = sum(1 for p in prospects if p.get("rating", 60) >= 82)
    label = "Historic" if avg_rating > 72 else "Strong" if avg_rating > 66 else "Average" if avg_rating > 60 else "Weak"
    return {"success": True, "year": SIM_STATE["year"], "avg_rating": round(avg_rating, 1),
            "elite_prospects": elite_count, "class_grade": label}


# ---------- 11: Redraft Simulator ----------
def redraft_simulator(year):
    picks = [p for p in SIM_STATE["players"].values() if p.get("draft_year") == year]
    if not picks:
        return {"success": False, "reason": f"No draft data found for {year}."}
    redrafted = sorted(picks, key=lambda p: -p.get("rating", 60))
    result = [{"redraft_pick": i + 1, "player": p["name"], "actual_rating_now": p.get("rating", 60)} for i, p in enumerate(redrafted[:30])]
    SIM_STATE.setdefault("redraft_results", {})[year] = result
    return {"success": True, "year": year, "redraft": result}


# ---------- 12: NBA Academy / youth pipeline ----------
def develop_academy_prospect(team_name):
    name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
    rating = random.randint(45, 70)
    entry = {"name": name, "rating": rating, "years_in_academy": random.randint(1, 3), "position": random.choice(POSITIONS)}
    SIM_STATE.setdefault("academy_prospects", {}).setdefault(team_name, []).append(entry)
    return {"success": True, "team": team_name, "prospect": entry}


# ---------- 13: "What Would It Take" reverse trade calculator ----------
def what_would_it_take(target_player_name):
    p = SIM_STATE["players"].get(target_player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    target_value = p.get("rating", 60)
    ask = []
    remaining = target_value
    roster_candidates = [pl for pl in SIM_STATE["players"].values() if not pl.get("retired") and pl["name"] != target_player_name]
    roster_candidates.sort(key=lambda pl: -pl.get("rating", 60))
    for cand in roster_candidates:
        if remaining <= 5:
            break
        if cand.get("rating", 60) <= remaining + 15:
            ask.append(cand["name"])
            remaining -= cand.get("rating", 60) * 0.5
            if len(ask) >= 3:
                break
    return {"success": True, "target": target_player_name, "estimated_ask": ask,
            "note": "Rough asset valuation -- actual asking price depends on team needs and GM personality."}


# ---------- 14: League realignment ----------
def realign_league(new_conferences):
    """new_conferences: {'Conference Name': [team1, team2, ...], ...}"""
    all_teams = [t for conf in new_conferences.values() for t in conf]
    if set(all_teams) != set(NBA_TEAMS):
        return {"success": False, "reason": "Realignment must include every team exactly once."}
    SIM_STATE["realignment"] = new_conferences
    push_news("🗺️", "The league has been realigned into new conferences.", kind="league_office")
    return {"success": True, "realignment": new_conferences}


# ---------- 15: Playoff Picture Projector ----------
def playoff_picture_projector():
    result = {}
    for conf_label in ["East", "West"]:
        conf_teams = [t for t in NBA_TEAMS if TEAM_CONFERENCE.get(t) == conf_label]
        ranked = sorted(conf_teams, key=lambda t: -SIM_STATE["teams"].get(t, {}).get("wins", 0))
        result[conf_label] = [{"seed": i + 1, "team": t, "wins": SIM_STATE["teams"].get(t, {}).get("wins", 0),
                                "status": "In" if i < 6 else "Play-In" if i < 10 else "Out"} for i, t in enumerate(ranked)]
    return {"success": True, "projection": result}


# ---------- 16: Standings clinch tracker ----------
def clinch_tracker(team_name):
    cfg = SIM_STATE["teams"].get(team_name, {})
    wins, losses = cfg.get("wins", 0), cfg.get("losses", 0)
    games_played = wins + losses
    games_left = max(0, SIM_STATE.get("schedule_days_total", 82) - games_played)
    magic_number = max(0, 42 - wins)  # rough proxy: 42 wins ~ borderline playoff line
    elimination_number = max(0, games_left - (42 - wins) + 1) if wins < 42 else None
    return {"team": team_name, "games_left": games_left, "magic_number_est": magic_number}


# ---------- 17: All-Decade Team ----------
def select_all_decade_team():
    decade_start = (SIM_STATE["year"] // 10) * 10 - 10
    candidates = [p for p in SIM_STATE["players"].values() if decade_start <= p.get("draft_year", 0) < decade_start + 10]
    top5 = sorted(candidates, key=lambda p: -(p.get("rating", 60) + len(p.get("career_awards", [])) * 3))[:5]
    entry = {"decade": f"{decade_start}s", "team": [p["name"] for p in top5]}
    SIM_STATE.setdefault("all_decade_teams", []).append(entry)
    push_news("🏆", f"The All-{decade_start}s Team has been announced.", kind="milestone")
    return {"success": True, **entry}


# ---------- 18: All-Time Redraft ----------
def all_time_redraft(num_picks=14):
    all_players = list(SIM_STATE["players"].values())
    ranked = sorted(all_players, key=lambda p: -(p.get("rating", 60) + len(p.get("career_awards", [])) * 2))[:num_picks]
    return {"success": True, "all_time_draft": [{"pick": i + 1, "player": p["name"], "rating": p.get("rating", 60)} for i, p in enumerate(ranked)]}


# ---------- 19: Legends Showcase exhibition ----------
def simulate_legends_showcase(team_name):
    legends = sorted([p for p in SIM_STATE["players"].values() if p.get("retired")], key=lambda p: -p.get("rating", 60))[:12]
    if not legends:
        return {"success": False, "reason": "No retired legends available yet."}
    legends_score = round(sum(p.get("rating", 60) for p in legends[:5]) / 5 * 1.1)
    current_score = round(sum(p.get("rating", 60) for p in team_roster(team_name)[:5]) / max(1, len(team_roster(team_name)[:5])))
    winner = "Legends" if legends_score + random.randint(-8, 8) > current_score else team_name
    push_news("⭐", f"Legends Showcase: {winner} win an exhibition thriller.", kind="milestone")
    return {"success": True, "winner": winner, "legends_score": legends_score, "current_team_score": current_score}


# ---------- 20: Ownership Confidence (distinct from coach hot seat) ----------
def update_ownership_confidence(team_name):
    cfg = SIM_STATE["teams"].get(team_name, {})
    wins, losses = cfg.get("wins", 0), cfg.get("losses", 0)
    win_pct = wins / max(1, wins + losses)
    conf = SIM_STATE.setdefault("ownership_confidence", {})
    conf[team_name] = round(clamp(50 + (win_pct - 0.5) * 100, 0, 100), 1)
    return {"team": team_name, "ownership_confidence": conf[team_name]}


# ---------- 21: Owner personality archetypes ----------
OWNER_ARCHETYPES = ["Meddling & Impatient", "Hands-Off & Trusting", "Big Spender", "Budget-Conscious", "Media-Obsessed"]


def get_owner_personality(team_name):
    owners = SIM_STATE.setdefault("owner_personalities", {})
    if team_name not in owners:
        owners[team_name] = random.choice(OWNER_ARCHETYPES)
    return {"team": team_name, "archetype": owners[team_name]}


# ---------- 22: Board of Governors votes ----------
BOG_PROPOSALS = ["Expand playoff field to 20 teams", "Shorten the regular season to 78 games",
                 "Introduce a hard salary cap", "Add a mid-season international tournament",
                 "Change draft lottery odds again"]


def hold_board_of_governors_vote():
    proposal = random.choice(BOG_PROPOSALS)
    votes_for = random.randint(10, 25)
    passed = votes_for >= 23
    entry = {"proposal": proposal, "votes_for": votes_for, "votes_total": 30, "passed": passed, "year": SIM_STATE["year"]}
    SIM_STATE.setdefault("board_votes", []).append(entry)
    push_news("🗳️", f"Board of Governors {'PASS' if passed else 'reject'}: \"{proposal}\" ({votes_for}/30).", kind="league_office")
    return {"success": True, **entry}


# ---------- 23: State of the Franchise letter ----------
def generate_state_of_franchise_letter(team_name):
    cfg = SIM_STATE["teams"].get(team_name, {})
    wins, losses = cfg.get("wins", 0), cfg.get("losses", 0)
    tone = "excited about our direction" if wins > losses else "committed to turning this around"
    letter = (f"To our fans -- this season we finished {wins}-{losses}. We remain {tone}. "
              f"Thank you for your continued support as we build toward our next championship.")
    entry = {"team": team_name, "year": SIM_STATE["year"], "letter": letter}
    SIM_STATE.setdefault("franchise_letters", []).append(entry)
    return {"success": True, **entry}


# ---------- 24: Beat writer practice reports ----------
BEAT_WRITER_TEMPLATES = ["{player} looked sharp in shooting drills today.", "{player} was held out of contact work as a precaution.",
                          "Coaches praised {player}'s energy in today's session.", "{player} worked extensively on his handle after practice."]


def generate_beat_writer_report(team_name):
    roster = team_roster(team_name)
    if not roster:
        return {"success": False, "reason": "No roster found."}
    player = random.choice(roster)["name"]
    text = random.choice(BEAT_WRITER_TEMPLATES).format(player=player)
    entry = {"team": team_name, "text": text, "day": SIM_STATE.get("current_day", 0)}
    SIM_STATE.setdefault("beat_writer_reports", []).append(entry)
    return {"success": True, **entry}


# ---------- 25: Skill Tree / branching badge upgrades ----------
SKILL_TREE_BRANCHES = {"Sharpshooter": ["Catch & Shoot", "Deep Range", "Off-Dribble Marksman"],
                        "Slasher": ["Contact Finisher", "Acrobat", "Downhill"],
                        "Playmaker": ["Dimer", "Break Starter", "Pick & Roll Maestro"],
                        "Defender": ["Lockdown", "Interior Fortress", "Chase-Down Artist"]}


def invest_skill_tree(player_name, branch, node):
    if branch not in SKILL_TREE_BRANCHES or node not in SKILL_TREE_BRANCHES[branch]:
        return {"success": False, "reason": "Unknown branch/node."}
    progress = SIM_STATE.setdefault("skill_tree_progress", {}).setdefault(player_name, {})
    progress[node] = progress.get(node, 0) + 1
    p = SIM_STATE["players"].get(player_name)
    if p and progress[node] >= 3:
        p.setdefault("badges", [])
        if node not in p["badges"]:
            p["badges"].append(node)
    return {"success": True, "player": player_name, "node": node, "progress": progress[node]}


# ---------- 26: Player Rivalry System ----------
def spark_player_rivalry(player_a, player_b, reason="a heated on-court exchange"):
    if not SIM_STATE["players"].get(player_a) or not SIM_STATE["players"].get(player_b):
        return {"success": False, "reason": "One or both players not found."}
    entry = {"player_a": player_a, "player_b": player_b, "reason": reason, "year": SIM_STATE["year"], "intensity": random.randint(30, 90)}
    SIM_STATE.setdefault("player_rivalries", []).append(entry)
    push_news("🔥", f"A rivalry is brewing between {player_a} and {player_b} after {reason}.", kind="drama")
    return {"success": True, **entry}


# ---------- 27: Awards Campaigning ----------
def campaign_for_award(player_name, award):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    swing = round(random.uniform(-2, 4), 1)  # can backfire slightly
    entry = {"player": player_name, "award": award, "perception_swing": swing, "year": SIM_STATE["year"]}
    SIM_STATE.setdefault("campaign_log", []).append(entry)
    push_news("📣", f"{player_name}'s camp is publicly campaigning for {award} consideration.", kind="drama")
    return {"success": True, **entry}


# ---------- 28: Hometown Pride ----------
def hometown_pride_boost(player_name, game_city):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    hometown = p.get("hometown", "Unknown")
    boost = hometown.split(",")[0].strip().lower() == game_city.strip().lower() if hometown != "Unknown" else False
    return {"player": player_name, "hometown": hometown, "playing_near_home": boost,
            "energy_boost_pct": 8 if boost else 0}


# ---------- 29: Position Battle mini-competitions ----------
def run_position_battle(team_name, position):
    roster = [p for p in team_roster(team_name) if p.get("position") == position]
    if len(roster) < 2:
        return {"success": False, "reason": "Need at least 2 players at that position."}
    scores = {p["name"]: round(p.get("rating", 60) + random.uniform(-6, 6), 1) for p in roster}
    winner = max(scores, key=scores.get)
    SIM_STATE.setdefault("position_battles", {})[f"{team_name}-{position}"] = {"winner": winner, "scores": scores}
    push_news("⚔️", f"{winner} wins the {position} battle at {team_name} camp.", kind="league_office")
    return {"success": True, "winner": winner, "scores": scores}


# ---------- 30: Player documentary ----------
def generate_player_documentary(player_name):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    championships = sum(1 for a in p.get("career_awards", []) if "Champion" in a.get("award", ""))
    script = (f"\"The Prime Years: {player_name}\" -- from draft night jitters to {championships} championship run(s), "
              f"a look back at a career defined by {p.get('position', 'his')} dominance and {p.get('rating', 60)}-rated peak play.")
    entry = {"player": player_name, "script": script}
    SIM_STATE.setdefault("documentaries", []).append(entry)
    return {"success": True, **entry}


# ---------- 31: Jumbotron replay highlight text ----------
def generate_jumbotron_highlight(player_name):
    p = SIM_STATE["players"].get(player_name)
    if not p:
        return {"success": False, "reason": "Player not found."}
    plays = [f"{player_name} throws it down with authority!", f"{player_name} splashes a deep three!",
             f"{player_name} with the ankle-breaking crossover!", f"{player_name} swats it into the third row!"]
    return {"success": True, "highlight": random.choice(plays)}


# ---------- 32: Season win total predictor ----------
def predict_season_win_totals():
    predictions = {}
    for t in NBA_TEAMS:
        roster = team_roster(t)
        avg_rating = sum(p.get("rating", 60) for p in roster) / max(1, len(roster))
        predicted_wins = round(clamp((avg_rating - 60) * 2.2 + 41, 10, 72))
        predictions[t] = predicted_wins
    SIM_STATE["win_total_predictions"] = predictions
    return {"success": True, "predictions": predictions}


def win_total_vs_actual(team_name):
    predicted = SIM_STATE.get("win_total_predictions", {}).get(team_name)
    actual = SIM_STATE["teams"].get(team_name, {}).get("wins", 0)
    return {"team": team_name, "predicted": predicted, "actual_so_far": actual}


# ---------- 33: Mid-season award odds tracker ----------
def award_odds_board():
    mvp = mvp_ladder(5)
    odds = {}
    total_score = sum(max(1, 5 - i) for i in range(len(mvp)))
    for i, row in enumerate(mvp):
        pct = round((5 - i) / total_score * 100, 1) if total_score else 0
        odds[row["name"]] = f"{pct}%"
    SIM_STATE["award_odds"] = odds
    return {"success": True, "mvp_odds": odds}


# ---------- 34: Championship parade ----------
def run_championship_parade(team_name):
    entry = {"team": team_name, "year": SIM_STATE["year"],
              "script": f"Confetti rains down on {team_name}'s parade route as thousands line the streets to celebrate the {SIM_STATE['year']} champions."}
    SIM_STATE.setdefault("parade_log", []).append(entry)
    push_news("🎉", entry["script"], kind="milestone")
    return {"success": True, **entry}


# ---------- 35: Custom uniform/jersey color editor ----------
def set_custom_uniform(team_name, primary_color, secondary_color):
    SIM_STATE.setdefault("custom_uniforms", {})[team_name] = {"primary": primary_color, "secondary": secondary_color}
    return {"success": True, "team": team_name, "primary": primary_color, "secondary": secondary_color}


# ---------- 36: All-Star Celebrity/Legends undercard ----------
def run_celebrity_legends_game():
    legends = sorted([p for p in SIM_STATE["players"].values() if p.get("retired")], key=lambda p: -p.get("rating", 60))[:10]
    score_a, score_b = random.randint(45, 65), random.randint(45, 65)
    winner = "Team Legends" if score_a > score_b else "Team Celebrity"
    push_news("🎬", f"Celebrity/Legends Game: {winner} win {max(score_a,score_b)}-{min(score_a,score_b)}.", kind="milestone")
    return {"success": True, "winner": winner, "score": f"{score_a}-{score_b}",
            "legends_in_game": [p["name"] for p in legends]}


# ---------- 37: Home/Away net rating splits ----------
def home_away_splits(team_name):
    cfg = SIM_STATE["teams"].get(team_name, {})
    wins, losses = cfg.get("wins", 0), cfg.get("losses", 0)
    # approximate split since we don't track home/away separately league-wide
    home_win_pct = clamp((wins / max(1, wins + losses)) * 1.15, 0, 1)
    away_win_pct = clamp((wins / max(1, wins + losses)) * 0.85, 0, 1)
    return {"team": team_name, "home_win_pct_est": round(home_win_pct * 100, 1), "away_win_pct_est": round(away_win_pct * 100, 1)}


# ---------- 38: Referee tendency profiles ----------
REFEREE_POOL = ["Referee Marsh", "Referee Okafor", "Referee Delgado", "Referee Chen", "Referee Novak"]


def get_referee_profile(name=None):
    profiles = SIM_STATE.setdefault("referee_profiles", {})
    name = name or random.choice(REFEREE_POOL)
    if name not in profiles:
        profiles[name] = {"foul_frequency": random.choice(["Tight Whistle", "Balanced", "Let Them Play"]),
                           "tech_quick_trigger": random.random() < 0.3}
    return {"referee": name, **profiles[name]}


# ---------- 39: Clutch-time win probability (flavor) ----------
def clutch_win_probability(home_score, away_score, seconds_left, has_ball_home):
    diff = home_score - away_score
    base = 50 + diff * 3 + (5 if has_ball_home else -5)
    time_factor = max(0.3, min(1.5, 60 / max(1, seconds_left)))
    prob = clamp(base + (0 if diff == 0 else (10 if diff > 0 else -10)) * time_factor, 1, 99)
    return {"home_win_probability_pct": round(prob, 1), "away_win_probability_pct": round(100 - prob, 1)}


# ---------- 40: Strength of schedule calculator ----------
def strength_of_schedule(team_name):
    remaining = [g for g in SIM_STATE.get("regular_season_games", []) if False]  # placeholder, real remaining sched below
    opponents = [t for t in NBA_TEAMS if t != team_name]
    avg_opp_wins = sum(SIM_STATE["teams"].get(t, {}).get("wins", 0) for t in opponents) / max(1, len(opponents))
    rating = "Brutal" if avg_opp_wins > 45 else "Tough" if avg_opp_wins > 41 else "Manageable" if avg_opp_wins > 37 else "Soft"
    return {"team": team_name, "avg_opponent_wins": round(avg_opp_wins, 1), "difficulty": rating}


# ---------- 41: Playoff series matchup predictor ----------
def predict_series_matchup(team_a, team_b):
    a_roster, b_roster = team_roster(team_a), team_roster(team_b)
    a_rating = sum(p.get("rating", 60) for p in a_roster) / max(1, len(a_roster))
    b_rating = sum(p.get("rating", 60) for p in b_roster) / max(1, len(b_roster))
    diff = a_rating - b_rating
    a_win_pct = clamp(50 + diff * 4, 5, 95)
    favorite = team_a if a_win_pct >= 50 else team_b
    return {"team_a": team_a, "team_b": team_b, "team_a_win_pct": round(a_win_pct, 1),
            "team_b_win_pct": round(100 - a_win_pct, 1), "favorite": favorite}


# ---------- 42: Multi-Franchise Career Tracker ----------
def log_career_stop(team_name, role="General Manager"):
    entry = {"team": team_name, "role": role, "year_started": SIM_STATE["year"]}
    SIM_STATE.setdefault("gm_career_history", []).append(entry)
    return {"success": True, **entry}


def career_resume():
    return {"success": True, "history": SIM_STATE.get("gm_career_history", [])}


# ---------- 43: Job Offers system ----------
def maybe_generate_job_offer():
    user_team = SIM_STATE["user_team"]
    cfg = SIM_STATE["teams"].get(user_team, {})
    win_pct = cfg.get("wins", 0) / max(1, cfg.get("wins", 0) + cfg.get("losses", 0))
    if win_pct < 0.6 or random.random() > 0.15:
        return {"success": False, "reason": "No offers right now -- keep winning."}
    other_teams = [t for t in NBA_TEAMS if t != user_team]
    offering_team = random.choice(other_teams)
    offer = {"team": offering_team, "role": "General Manager", "pitch": f"{offering_team} want you to run their front office.", "year": SIM_STATE["year"]}
    SIM_STATE.setdefault("job_offers", []).append(offer)
    push_news("📞", f"{offering_team} have reached out with a front-office job offer for you.", kind="league_office")
    return {"success": True, **offer}


# ---------- 44: Coaching Tree ----------
def add_to_coaching_tree(mentor_name, hired_team, new_role="Head Coach"):
    tree = SIM_STATE.setdefault("coaching_tree", {}).setdefault(mentor_name, [])
    entry = {"hired_team": hired_team, "role": new_role, "year": SIM_STATE["year"]}
    tree.append(entry)
    push_news("🌳", f"A former {mentor_name} assistant is hired as {new_role} of {hired_team}.", kind="league_office")
    return {"success": True, "mentor": mentor_name, **entry}


# ---------- 45: Front Office Alumni Network ----------
def add_fo_alumni(name, previous_team, role):
    entry = {"name": name, "previous_team": previous_team, "role": role, "year_departed": SIM_STATE["year"], "current_team": None}
    SIM_STATE.setdefault("fo_alumni", []).append(entry)
    return {"success": True, **entry}


def resurface_fo_alumni(name, new_team, new_role):
    alum = next((a for a in SIM_STATE.get("fo_alumni", []) if a["name"] == name), None)
    if not alum:
        return {"success": False, "reason": "Not found in alumni network."}
    alum["current_team"] = new_team
    push_news("🔄", f"{name}, formerly of {alum['previous_team']}, resurfaces as {new_role} of {new_team}.", kind="league_office")
    return {"success": True, **alum}


# ---------- 46: In-app tutorial ----------
TUTORIAL_STEPS = [
    {"title": "Welcome to Hoops Sim", "text": "You're the GM of your franchise. Use the Season Calendar to advance days and sim games."},
    {"title": "Roster & Lineups", "text": "Team Management lets you set your rotation, offense/defense strategy, and see a snapshot of your team."},
    {"title": "Trades & Free Agency", "text": "Trade Center and Free Agency Wire let you build your roster year-round."},
    {"title": "Front Office", "text": "Manage your GM personality, staff, scouting, business operations, and league rules here."},
    {"title": "History & Records", "text": "Every season is tracked -- champions, records, and Hall of Fame all live in League History."},
]


def get_tutorial():
    return {"success": True, "steps": TUTORIAL_STEPS}


# ---------- 47: Notification Center ----------
def push_notification(text, kind="general"):
    SIM_STATE.setdefault("notifications", []).append({"text": text, "kind": kind, "day": SIM_STATE.get("current_day", 0),
                                                        "year": SIM_STATE["year"], "read": False})


def get_notifications(unread_only=False):
    notes = SIM_STATE.get("notifications", [])
    if unread_only:
        notes = [n for n in notes if not n["read"]]
    return {"success": True, "notifications": notes[-30:], "unread_count": sum(1 for n in SIM_STATE.get("notifications", []) if not n["read"])}


def mark_notifications_read():
    for n in SIM_STATE.get("notifications", []):
        n["read"] = True
    return {"success": True}


# ---------- 48: Quick-Sim Presets ----------
def quick_sim_to_trade_deadline():
    days_left = SIM_STATE.get("trade_deadline_day", 0) - SIM_STATE.get("current_day", 0)
    simmed = 0
    for _ in range(max(0, days_left)):
        if SIM_STATE.get("season_simulated"):
            break
        sim_day()
        simmed += 1
    return {"success": True, "days_simmed": simmed}


def quick_sim_to_next_game():
    user_team = SIM_STATE["user_team"]
    simmed = 0
    for _ in range(30):
        if SIM_STATE.get("season_simulated"):
            break
        sim_day()
        simmed += 1
        day_idx = SIM_STATE["current_day"] - 1
        matchups = SIM_STATE["schedule"][day_idx] if 0 <= day_idx < len(SIM_STATE["schedule"]) else []
        if any(m.get("home") == user_team or m.get("away") == user_team for m in matchups):
            break
    return {"success": True, "days_simmed": simmed}


# ---------- 49: League-wide search ----------
def league_search(query):
    query = query.lower().strip()
    if not query:
        return {"success": True, "players": [], "teams": [], "prospects": []}
    players = [p["name"] for p in SIM_STATE["players"].values() if query in p["name"].lower()][:10]
    teams = [t for t in NBA_TEAMS if query in t.lower()][:10]
    prospects = [p["name"] for p in SIM_STATE.get("draft_class", []) if query in p["name"].lower()][:10]
    return {"success": True, "players": players, "teams": teams, "prospects": prospects}


# ---------- 50: Undo last action ----------
def snapshot_for_undo(action_label):
    SIM_STATE.setdefault("undo_stack", []).append({"label": action_label, "snapshot": copy.deepcopy(
        {"players": SIM_STATE["players"], "teams": SIM_STATE["teams"]})})
    if len(SIM_STATE["undo_stack"]) > 1:
        SIM_STATE["undo_stack"] = SIM_STATE["undo_stack"][-1:]  # keep only the single most recent for memory reasons


def undo_last_action():
    stack = SIM_STATE.get("undo_stack", [])
    if not stack:
        return {"success": False, "reason": "Nothing to undo."}
    last = stack.pop()
    SIM_STATE["players"] = last["snapshot"]["players"]
    SIM_STATE["teams"] = last["snapshot"]["teams"]
    push_news("↩️", f"Undid: {last['label']}.", kind="league_office")
    return {"success": True, "undone": last["label"]}


# ==========================================================
# UPGRADE BATCH 11 -- API routes
# ==========================================================

@app.route('/api/rfa/submit_offer_sheet', methods=['POST'])
def api_rfa_submit_offer_sheet():
    d = request.json or {}
    return jsonify(submit_rfa_offer_sheet(d.get("player_name"), d.get("offering_team"), d.get("years"), d.get("salary")))

@app.route('/api/rfa/match', methods=['POST'])
def api_rfa_match():
    d = request.json or {}
    return jsonify(match_rfa_offer_sheet(d.get("player_name"), d.get("match", True)))

@app.route('/api/extend_and_trade', methods=['POST'])
def api_extend_and_trade():
    d = request.json or {}
    return jsonify(extend_and_trade(d.get("player_name"), d.get("new_team"), d.get("years"), d.get("salary")))

@app.route('/api/check_designated_rookie')
def api_check_designated_rookie():
    return jsonify(check_designated_rookie_eligibility(request.args.get("player")))

@app.route('/api/check_supermax')
def api_check_supermax():
    return jsonify(check_supermax_eligibility(request.args.get("player")))

@app.route('/api/attempt_unretirement', methods=['POST'])
def api_attempt_unretirement():
    d = request.json or {}
    return jsonify(attempt_unretirement(d.get("player_name"), d.get("team", SIM_STATE["user_team"])))

@app.route('/api/upgrade_practice_facility', methods=['POST'])
def api_upgrade_practice_facility():
    d = request.json or {}
    return jsonify(upgrade_practice_facility(d.get("team", SIM_STATE["user_team"]), d.get("tier")))

@app.route('/api/trade_deadline_countdown')
def api_trade_deadline_countdown():
    return jsonify(trade_deadline_countdown())

@app.route('/api/draft_lottery_ceremony', methods=['POST'])
def api_draft_lottery_ceremony():
    return jsonify(run_draft_lottery_ceremony())

@app.route('/api/draft_class_strength')
def api_draft_class_strength():
    return jsonify(draft_class_strength())

@app.route('/api/redraft_simulator')
def api_redraft_simulator():
    return jsonify(redraft_simulator(safe_int(request.args.get("year"), SIM_STATE["year"])))

@app.route('/api/develop_academy_prospect', methods=['POST'])
def api_develop_academy_prospect():
    d = request.json or {}
    return jsonify(develop_academy_prospect(d.get("team", SIM_STATE["user_team"])))

@app.route('/api/what_would_it_take')
def api_what_would_it_take():
    return jsonify(what_would_it_take(request.args.get("player")))

@app.route('/api/realign_league', methods=['POST'])
def api_realign_league():
    d = request.json or {}
    conferences = d.get("conferences", {})
    if not isinstance(conferences, dict):
        return jsonify({"success": False, "reason": "Realignment needs a full conference map (every team assigned once) -- not available as a quick single-field tool. Use the League Operations realignment screen instead."})
    return jsonify(realign_league(conferences))

@app.route('/api/playoff_picture_projector')
def api_playoff_picture_projector():
    return jsonify(playoff_picture_projector())

@app.route('/api/clinch_tracker')
def api_clinch_tracker():
    return jsonify({"success": True, **clinch_tracker(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/select_all_decade_team', methods=['POST'])
def api_select_all_decade_team():
    return jsonify(select_all_decade_team())

@app.route('/api/all_time_redraft')
def api_all_time_redraft():
    return jsonify(all_time_redraft())

@app.route('/api/legends_showcase', methods=['POST'])
def api_legends_showcase():
    d = request.json or {}
    return jsonify(simulate_legends_showcase(d.get("team", SIM_STATE["user_team"])))

@app.route('/api/ownership_confidence')
def api_ownership_confidence():
    return jsonify({"success": True, **update_ownership_confidence(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/owner_personality')
def api_owner_personality():
    return jsonify({"success": True, **get_owner_personality(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/board_of_governors_vote', methods=['POST'])
def api_board_of_governors_vote():
    return jsonify(hold_board_of_governors_vote())

@app.route('/api/state_of_franchise_letter', methods=['POST'])
def api_state_of_franchise_letter():
    d = request.json or {}
    return jsonify(generate_state_of_franchise_letter(d.get("team", SIM_STATE["user_team"])))

@app.route('/api/beat_writer_report', methods=['POST'])
def api_beat_writer_report():
    d = request.json or {}
    return jsonify(generate_beat_writer_report(d.get("team", SIM_STATE["user_team"])))

@app.route('/api/invest_skill_tree', methods=['POST'])
def api_invest_skill_tree():
    d = request.json or {}
    return jsonify(invest_skill_tree(d.get("player_name"), d.get("branch"), d.get("node")))

@app.route('/api/spark_rivalry', methods=['POST'])
def api_spark_rivalry():
    d = request.json or {}
    return jsonify(spark_player_rivalry(d.get("player_a"), d.get("player_b"), d.get("reason", "a heated on-court exchange")))

@app.route('/api/campaign_for_award', methods=['POST'])
def api_campaign_for_award():
    d = request.json or {}
    return jsonify(campaign_for_award(d.get("player_name"), d.get("award")))

@app.route('/api/hometown_pride')
def api_hometown_pride():
    return jsonify({"success": True, **hometown_pride_boost(request.args.get("player"), request.args.get("city", ""))})

@app.route('/api/position_battle', methods=['POST'])
def api_position_battle():
    d = request.json or {}
    return jsonify(run_position_battle(d.get("team", SIM_STATE["user_team"]), d.get("position")))

@app.route('/api/player_documentary', methods=['POST'])
def api_player_documentary():
    d = request.json or {}
    return jsonify(generate_player_documentary(d.get("player_name")))

@app.route('/api/jumbotron_highlight')
def api_jumbotron_highlight():
    return jsonify(generate_jumbotron_highlight(request.args.get("player")))

@app.route('/api/predict_win_totals', methods=['POST'])
def api_predict_win_totals():
    return jsonify(predict_season_win_totals())

@app.route('/api/win_total_vs_actual')
def api_win_total_vs_actual():
    return jsonify({"success": True, **win_total_vs_actual(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/award_odds_board')
def api_award_odds_board():
    return jsonify(award_odds_board())

@app.route('/api/championship_parade', methods=['POST'])
def api_championship_parade():
    d = request.json or {}
    return jsonify(run_championship_parade(d.get("team", SIM_STATE["user_team"])))

@app.route('/api/set_custom_uniform', methods=['POST'])
def api_set_custom_uniform():
    d = request.json or {}
    return jsonify(set_custom_uniform(d.get("team", SIM_STATE["user_team"]), d.get("primary", "#1d428a"), d.get("secondary", "#c8102e")))

@app.route('/api/celebrity_legends_game', methods=['POST'])
def api_celebrity_legends_game():
    return jsonify(run_celebrity_legends_game())

@app.route('/api/home_away_splits')
def api_home_away_splits():
    return jsonify({"success": True, **home_away_splits(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/referee_profile')
def api_referee_profile():
    return jsonify({"success": True, **get_referee_profile(request.args.get("name"))})

@app.route('/api/clutch_win_probability')
def api_clutch_win_probability():
    return jsonify({"success": True, **clutch_win_probability(
        safe_int(request.args.get("home_score"), 0), safe_int(request.args.get("away_score"), 0),
        safe_int(request.args.get("seconds_left"), 24), request.args.get("has_ball_home", "true") == "true")})

@app.route('/api/strength_of_schedule')
def api_strength_of_schedule():
    return jsonify({"success": True, **strength_of_schedule(request.args.get("team", SIM_STATE["user_team"]))})

@app.route('/api/predict_series_matchup')
def api_predict_series_matchup():
    return jsonify({"success": True, **predict_series_matchup(request.args.get("team_a"), request.args.get("team_b"))})

@app.route('/api/log_career_stop', methods=['POST'])
def api_log_career_stop():
    d = request.json or {}
    return jsonify(log_career_stop(d.get("team", SIM_STATE["user_team"]), d.get("role", "General Manager")))

@app.route('/api/career_resume')
def api_career_resume():
    return jsonify(career_resume())

@app.route('/api/check_job_offers', methods=['POST'])
def api_check_job_offers():
    return jsonify(maybe_generate_job_offer())

@app.route('/api/add_coaching_tree', methods=['POST'])
def api_add_coaching_tree():
    d = request.json or {}
    return jsonify(add_to_coaching_tree(d.get("mentor_name"), d.get("hired_team"), d.get("new_role", "Head Coach")))

@app.route('/api/add_fo_alumni', methods=['POST'])
def api_add_fo_alumni():
    d = request.json or {}
    return jsonify(add_fo_alumni(d.get("name"), d.get("previous_team"), d.get("role")))

@app.route('/api/resurface_fo_alumni', methods=['POST'])
def api_resurface_fo_alumni():
    d = request.json or {}
    return jsonify(resurface_fo_alumni(d.get("name"), d.get("new_team"), d.get("new_role")))

@app.route('/api/tutorial')
def api_tutorial():
    return jsonify(get_tutorial())

@app.route('/api/notifications')
def api_notifications():
    return jsonify(get_notifications(request.args.get("unread_only", "false") == "true"))

@app.route('/api/notifications/mark_read', methods=['POST'])
def api_notifications_mark_read():
    return jsonify(mark_notifications_read())

@app.route('/api/quick_sim/trade_deadline', methods=['POST'])
def api_quick_sim_trade_deadline():
    return jsonify(quick_sim_to_trade_deadline())

@app.route('/api/quick_sim/next_game', methods=['POST'])
def api_quick_sim_next_game():
    return jsonify(quick_sim_to_next_game())

@app.route('/api/all_players_lite')
def api_all_players_lite():
    # UPGRADE PASS: powers the datalist autocomplete on every "player name"
    # box in the Advanced Tools catalog (previously plain free-text --
    # you had to know and type the exact full name). Kept intentionally
    # small (name/team/position/rating only) since it's fetched once and
    # cached client-side.
    out = []
    for p in SIM_STATE["players"].values():
        out.append({"name": p["name"], "team": p.get("team") or "Retired/FA",
                     "position": p.get("position", ""), "rating": p.get("rating", 0)})
    out.sort(key=lambda x: -x["rating"])
    return jsonify({"players": out})


@app.route('/api/league_search')
def api_league_search():
    return jsonify(league_search(request.args.get("q", "")))

@app.route('/api/undo_last_action', methods=['POST'])
def api_undo_last_action():
    return jsonify(undo_last_action())


# ==========================================================
# UPGRADE BATCH 13 -- next 5 major systems
# ==========================================================

# ---------- 1: Live Championship Odds Board ----------
def championship_odds_board():
    scores = {}
    for t in NBA_TEAMS:
        roster = team_roster(t)
        avg_rating = sum(p.get("rating", 60) for p in roster) / max(1, len(roster))
        cfg = SIM_STATE["teams"].get(t, {})
        win_pct = cfg.get("wins", 0) / max(1, cfg.get("wins", 0) + cfg.get("losses", 0))
        scores[t] = avg_rating * 0.6 + win_pct * 100 * 0.4
    total = sum(scores.values()) or 1
    odds = {t: round(s / total * 100, 1) for t, s in scores.items()}
    ranked = sorted(odds.items(), key=lambda kv: -kv[1])
    return {"success": True, "odds": [{"team": t, "title_pct": pct} for t, pct in ranked]}


# ---------- 2: Load Management Auto-Suggestions ----------
def load_management_suggestions(team_name):
    suggestions = []
    for p in team_roster(team_name):
        fatigue = p.get("fatigue", 0)
        age = p.get("age", 25)
        durability = p.get("attributes", {}).get("Durability", 75)
        risk = fatigue * 0.5 + max(0, age - 30) * 3 + max(0, 75 - durability) * 0.6
        if risk >= 45:
            suggestions.append({"player": p["name"], "risk_score": round(risk, 1),
                                 "recommendation": "Sit tonight / cap minutes" if risk >= 65 else "Reduce minutes"})
    suggestions.sort(key=lambda s: -s["risk_score"])
    return {"success": True, "team": team_name, "suggestions": suggestions}


# ---------- 3: GM Report Card ----------
def generate_gm_report_card():
    user_team = SIM_STATE["user_team"]
    cfg = SIM_STATE["teams"].get(user_team, {})
    wins, losses = cfg.get("wins", 0), cfg.get("losses", 0)
    win_pct = wins / max(1, wins + losses)
    trade_count = len([t for t in SIM_STATE.get("trade_grades", []) if t.get("team_a") == user_team or t.get("team_b") == user_team])
    cap_health = "Healthy" if cfg.get("cap_space", 0) >= 0 else "Over Cap"
    fan_approval = SIM_STATE.get("fan_approval", {}).get(user_team, 55)
    score = win_pct * 50 + fan_approval * 0.3 + min(trade_count, 5) * 4
    grade = "A" if score >= 65 else "B" if score >= 50 else "C" if score >= 35 else "D"
    return {"success": True, "team": user_team, "record": f"{wins}-{losses}", "fan_approval": fan_approval,
            "cap_health": cap_health, "trades_made": trade_count, "overall_grade": grade, "score": round(score, 1)}


# ---------- 4: Rival Scouting Report ----------
def generate_scouting_report(opponent_team):
    roster = team_roster(opponent_team)
    if not roster:
        return {"success": False, "reason": "Team not found or has no active roster."}
    top_scorer = max(roster, key=lambda p: p["stats"].get("PTS", 0) / max(1, p["stats"].get("GP", 1)))
    identity = SIM_STATE.get("team_identity", {}).get(opponent_team) or compute_team_identity(opponent_team)
    gameplan = get_coaching_gameplan(opponent_team)
    key_matchup = f"Watch out for {top_scorer['name']} ({round(top_scorer['stats'].get('PTS',0)/max(1,top_scorer['stats'].get('GP',1)),1)} PPG)."
    weaknesses = []
    avg_def = sum(p["attributes"].get("Perimeter Defense", 60) + p["attributes"].get("Interior Defense", 60) for p in roster) / (2 * max(1, len(roster)))
    if avg_def < 65:
        weaknesses.append("Vulnerable defensively -- attack the paint and push pace.")
    if gameplan.get("Three-Point", 50) if False else gameplan.get("Zone Frequency", 50) > 65:
        weaknesses.append("Plays a lot of zone -- ball movement and corner shooters can crack it.")
    if not weaknesses:
        weaknesses.append("No glaring weaknesses -- a disciplined, balanced opponent.")
    return {"success": True, "opponent": opponent_team, "identity": identity, "key_matchup": key_matchup,
            "weaknesses": weaknesses, "top_scorer": top_scorer["name"]}


# ---------- 5: League Constitution / Rulebook Viewer ----------
def league_rulebook():
    rules = get_league_rules()
    era = get_era_config()
    return {"success": True, "era": era["label"], "rules": {
        "Shot Clock": f"{rules['shot_clock_seconds']} seconds",
        "Quarter Length": f"{rules['quarter_length_minutes']} minutes",
        "Regular Season Games": rules["num_games"],
        "Play-In Tournament": "Enabled" if rules["play_in_enabled"] else "Disabled",
        "Conferences": "Enabled" if rules["conferences_enabled"] else "Disabled",
        "Salary Cap": f"${rules['salary_cap']}M",
        "Hard Cap Apron": f"${rules['hard_cap_apron']}M",
        "Luxury Tax Rate": f"{rules['luxury_tax_rate']}",
        "Roster Size": f"{rules['min_roster_size']}-{rules['max_roster_size']} players",
        "Trade Deadline": f"{round(rules['trade_deadline_fraction']*100)}% through the season",
        "Draft Lottery": rules["draft_lottery_odds"],
        "Expansion": "Enabled" if rules["expansion_enabled"] else "Disabled",
    }}


# ==========================================================
# UPGRADE BATCH 13 -- API routes
# ==========================================================

@app.route('/api/championship_odds')
def api_championship_odds():
    return jsonify(championship_odds_board())

@app.route('/api/load_management_suggestions')
def api_load_management_suggestions():
    return jsonify(load_management_suggestions(request.args.get("team", SIM_STATE["user_team"])))

@app.route('/api/gm_report_card')
def api_gm_report_card():
    return jsonify(generate_gm_report_card())

@app.route('/api/scouting_report')
def api_scouting_report():
    return jsonify(generate_scouting_report(request.args.get("opponent")))

@app.route('/api/league_rulebook')
def api_league_rulebook():
    return jsonify(league_rulebook())


if __name__ == '__main__':
    pass
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=debug_mode, host="0.0.0.0", port=port, use_reloader=False)
