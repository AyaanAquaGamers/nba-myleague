    // ==========================================================
    // 2K24-STYLE "DATA HUB" PANELS
    // Generic renderer that surfaces the 168 backend systems (GM Career,
    // Franchise, Media, Awards, Coaching, Contracts, Draft, Sim Controls,
    // Analytics, League Ops) that previously had zero UI. Uses the same
    // collapsible hub-menu / hub-kv-grid look already established elsewhere
    // in this app (Team Intel, League History drill-downs) so it fits in
    // visually rather than looking bolted on.
    // ==========================================================
    const HUB_CONFIG = {"gm": {"label": "GM Career", "items": [{"path": "/api/team_identity", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Team Identity"}, {"path": "/api/coach_hot_seat", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Coach Hot Seat"}, {"path": "/api/coach_confidence", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Coach Confidence"}, {"path": "/api/maybe_fire_coach", "method": "POST", "args": ["team"], "arg_labels": {"team": ""}, "label": "Check If Coach Gets Fired"}, {"path": "/api/toggle_coaching_career_mode", "method": "POST", "args": ["enabled"], "arg_labels": {"enabled": "true or false"}, "label": "Toggle Coaching Career Mode"}, {"path": "/api/ownership_confidence", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Ownership Confidence"}, {"path": "/api/owner_personality", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Owner Personality"}, {"path": "/api/board_of_governors_vote", "method": "POST", "args": [], "arg_labels": {}, "label": "Hold Board of Governors Vote"}, {"path": "/api/state_of_franchise_letter", "method": "POST", "args": ["team"], "arg_labels": {"team": ""}, "label": "Write State of the Franchise Letter"}, {"path": "/api/log_career_stop", "method": "POST", "args": ["team", "role"], "arg_labels": {"team": "", "role": "Role (default General Manager)"}, "label": "Log a Career Stop"}, {"path": "/api/add_coaching_tree", "method": "POST", "args": ["mentor_name", "hired_team", "new_role"], "arg_labels": {"mentor_name": "Mentor name", "hired_team": "Hired by team", "new_role": "New role (default Head Coach)"}, "label": "Add to Coaching Tree"}, {"path": "/api/add_fo_alumni", "method": "POST", "args": ["name", "previous_team", "role"], "arg_labels": {"name": "Name", "previous_team": "Previous team", "role": "Role"}, "label": "Add Front Office Alumni"}, {"path": "/api/resurface_fo_alumni", "method": "POST", "args": ["name", "new_team", "new_role"], "arg_labels": {"name": "Name", "new_team": "New team", "new_role": "New role"}, "label": "Resurface Alumni Elsewhere"}]}, "franchise": {"label": "Franchise & Business", "items": [{"path": "/api/set_ticket_price", "method": "POST", "args": ["team", "tier"], "arg_labels": {"team": "", "tier": "Budget / Standard / Premium / Luxury"}, "label": "Set Ticket Price Tier"}, {"path": "/api/merch_concessions_revenue", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Merch & Concessions Revenue"}, {"path": "/api/ticket_loyalty_tier", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Ticket Loyalty Tier"}, {"path": "/api/cap_sheet_projection", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Cap Sheet 5-Year Projection"}, {"path": "/api/assign_mascot", "method": "POST", "args": ["team"], "arg_labels": {"team": ""}, "label": "Assign Team Mascot"}, {"path": "/api/upgrade_practice_facility", "method": "POST", "args": ["team", "tier"], "arg_labels": {"team": "", "tier": "Standard / Upgraded / State-of-the-Art / World Class"}, "label": "Upgrade Practice Facility"}, {"path": "/api/set_custom_uniform", "method": "POST", "args": ["team", "primary", "secondary"], "arg_labels": {"team": "", "primary": "Primary color hex (e.g. #1d428a)", "secondary": "Secondary color hex"}, "label": "Set Custom Uniform Colors"}, {"path": "/api/relocate_team", "method": "POST", "args": ["new_name"], "arg_labels": {"new_name": "New team name/city"}, "label": "Relocate Your Franchise"}, {"path": "/api/run_expansion_draft", "method": "POST", "args": [], "arg_labels": {}, "label": "Run an Expansion Draft"}]}, "media": {"label": "Media & Fan Engagement", "items": [{"path": "/api/generate_social_event", "method": "POST", "args": ["player_name"], "arg_labels": {"player_name": "Player name (optional)"}, "label": "Generate a Social Media Moment"}, {"path": "/api/hype_video_script", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Team Hype Video Script"}, {"path": "/api/assign_nickname", "method": "POST", "args": ["player_name", "nickname"], "arg_labels": {"player_name": "Player name", "nickname": "Nickname (optional)"}, "label": "Assign a Player Nickname"}, {"path": "/api/assign_walk_up_motif", "method": "POST", "args": ["player_name"], "arg_labels": {"player_name": "Player name"}, "label": "Assign Walk-Up Sound Motif"}, {"path": "/api/retired_number_ceremony_script", "method": "GET", "args": ["player", "team", "number"], "arg_labels": {"player": "Player name", "team": "", "number": "Jersey number"}, "label": "Retired Number Ceremony Script"}, {"path": "/api/road_atmosphere", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Road Atmosphere Flavor"}, {"path": "/api/spark_rivalry", "method": "POST", "args": ["player_a", "player_b", "reason"], "arg_labels": {"player_a": "Player A", "player_b": "Player B", "reason": "Reason (optional)"}, "label": "Spark a Player Rivalry"}, {"path": "/api/campaign_for_award", "method": "POST", "args": ["player_name", "award"], "arg_labels": {"player_name": "Player name", "award": "Award name"}, "label": "Campaign for an Award"}, {"path": "/api/hometown_pride", "method": "GET", "args": ["player", "city"], "arg_labels": {"player": "Player name", "city": "Tonight's game city"}, "label": "Hometown Pride Check"}, {"path": "/api/player_documentary", "method": "POST", "args": ["player_name"], "arg_labels": {"player_name": "Player name"}, "label": "Generate a Player Documentary"}, {"path": "/api/jumbotron_highlight", "method": "GET", "args": ["player"], "arg_labels": {"player": "Player name"}, "label": "Jumbotron Highlight"}]}, "awards": {"label": "Awards & Legacy", "items": [{"path": "/api/league_history", "method": "GET", "args": [], "arg_labels": {}, "label": "League History (all seasons)"}, {"path": "/api/franchise_records", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Franchise Records"}, {"path": "/api/team_dynasty_rating", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Team Dynasty Rating"}, {"path": "/api/player_legacy_card", "method": "GET", "args": ["player"], "arg_labels": {"player": "Player name"}, "label": "Player Legacy Card"}, {"path": "/api/compare_players", "method": "GET", "args": ["a", "b"], "arg_labels": {"a": "Player A", "b": "Player B"}, "label": "Player Comparison"}, {"path": "/api/career_highs", "method": "GET", "args": ["name"], "arg_labels": {"name": "Player name"}, "label": "Career Highs for a Player"}, {"path": "/api/milestone_watch_list", "method": "GET", "args": [], "arg_labels": {}, "label": "Milestone Watch List"}, {"path": "/api/news_archive", "method": "GET", "args": [], "arg_labels": {}, "label": "League News Archive"}, {"path": "/api/power_rankings", "method": "GET", "args": [], "arg_labels": {}, "label": "Power Rankings"}, {"path": "/api/player_of_week", "method": "GET", "args": [], "arg_labels": {}, "label": "Player of the Week History"}, {"path": "/api/coach_of_month", "method": "GET", "args": [], "arg_labels": {}, "label": "Coach of the Month History"}, {"path": "/api/hustle_leaderboard", "method": "GET", "args": [], "arg_labels": {}, "label": "Hustle Stats Leaderboard"}, {"path": "/api/executive_of_the_year", "method": "POST", "args": [], "arg_labels": {}, "label": "Award Executive of the Year"}, {"path": "/api/clutch_player_of_the_year", "method": "POST", "args": [], "arg_labels": {}, "label": "Award Clutch Player of the Year"}, {"path": "/api/simulate_fan_vote", "method": "POST", "args": [], "arg_labels": {}, "label": "Simulate All-Star Fan Vote"}, {"path": "/api/all_star_captains_draft", "method": "POST", "args": [], "arg_labels": {}, "label": "Run All-Star Captains Draft"}, {"path": "/api/select_all_decade_team", "method": "POST", "args": [], "arg_labels": {}, "label": "Select the All-Decade Team"}, {"path": "/api/all_time_redraft", "method": "GET", "args": [], "arg_labels": {}, "label": "All-Time Redraft"}, {"path": "/api/generate_backstory", "method": "POST", "args": ["target_start_year"], "arg_labels": {"target_start_year": "Truncate history before this year"}, "label": "Regenerate League Backstory (1984 -> now)"}]}, "coaching": {"label": "Coaching & Strategy", "items": [{"path": "/api/set_coaching_gameplan", "method": "POST", "args": ["team", "slider", "value"], "arg_labels": {"team": "", "slider": "Slider name (e.g. Pace)", "value": "Value 0-100"}, "label": "Set a Gameplan Slider"}, {"path": "/api/lineup_synergy", "method": "POST", "args": ["players"], "arg_labels": {"players": "Name1, Name2, Name3, Name4, Name5"}, "label": "Lineup Synergy (5 names, comma-separated)"}, {"path": "/api/injury_history", "method": "GET", "args": ["player"], "arg_labels": {"player": "Player name"}, "label": "Injury History"}, {"path": "/api/morale_snapshot", "method": "GET", "args": ["player"], "arg_labels": {"player": "Player name"}, "label": "Player Morale & Fatigue"}, {"path": "/api/skills_challenge", "method": "POST", "args": [], "arg_labels": {}, "label": "Run Skills Challenge"}, {"path": "/api/set_load_management", "method": "POST", "args": ["team", "player_name", "minutes_cap"], "arg_labels": {"team": "", "player_name": "Player name", "minutes_cap": "Minutes cap (0-48)"}, "label": "Set Load Management Minutes Cap"}, {"path": "/api/choose_injury_treatment", "method": "POST", "args": ["player_name", "treatment"], "arg_labels": {"player_name": "Injured player name", "treatment": "surgery or rehab"}, "label": "Choose Injury Treatment"}, {"path": "/api/invest_skill_tree", "method": "POST", "args": ["player_name", "branch", "node"], "arg_labels": {"player_name": "Player name", "branch": "Sharpshooter / Slasher / Playmaker / Defender", "node": "Node name within that branch"}, "label": "Invest in a Skill Tree Node"}, {"path": "/api/position_battle", "method": "POST", "args": ["team", "position"], "arg_labels": {"team": "", "position": "PG / SG / SF / PF / C"}, "label": "Run a Position Battle"}, {"path": "/api/load_management_suggestions", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Load Management Suggestions"}, {"path": "/api/run_combine_minigame", "method": "POST", "args": ["prospect_name", "drill", "user_taps"], "arg_labels": {"prospect_name": "Prospect name", "drill": "Drill (Vertical, Sprint, Agility, ...)", "user_taps": "Your score (0-20)"}, "label": "Run Combine Mini-Game"}]}, "frontoffice2": {"label": "Trades & Contracts", "items": [{"path": "/api/buyout_market", "method": "GET", "args": [], "arg_labels": {}, "label": "View Buyout Market"}, {"path": "/api/enter_buyout_market", "method": "POST", "args": ["player_name", "remaining_salary"], "arg_labels": {"player_name": "Player name (must already be waived)", "remaining_salary": "Remaining salary owed ($M)"}, "label": "Put a Waived Player on the Buyout Market"}, {"path": "/api/trade_requests", "method": "GET", "args": [], "arg_labels": {}, "label": "View Active Trade Requests"}, {"path": "/api/submit_trade_request", "method": "POST", "args": ["player_name", "reason"], "arg_labels": {"player_name": "Player name", "reason": "Reason (optional)"}, "label": "Submit a Trade Request for a Player"}, {"path": "/api/negotiate_contract", "method": "POST", "args": ["team", "player_name", "years", "salary"], "arg_labels": {"team": "", "player_name": "Player name", "years": "Years", "salary": "Salary per year ($M)"}, "label": "Negotiate a Contract"}, {"path": "/api/grade_trade", "method": "POST", "args": ["team_a", "players_a_get", "team_b", "players_b_get"], "arg_labels": {"team_a": "Team A", "players_a_get": "Players Team A receives (comma-separated)", "team_b": "Team B", "players_b_get": "Players Team B receives (comma-separated)"}, "label": "Grade a Trade"}, {"path": "/api/create_custom_player", "method": "POST", "args": ["name", "position", "team"], "arg_labels": {"name": "Player name", "position": "PG / SG / SF / PF / C", "team": ""}, "label": "Create a Custom Player"}, {"path": "/api/fantasy_draft_scramble", "method": "POST", "args": [], "arg_labels": {}, "label": "Fantasy Draft Scramble (reshuffles EVERY roster!)"}, {"path": "/api/rfa/submit_offer_sheet", "method": "POST", "args": ["player_name", "offering_team", "years", "salary"], "arg_labels": {"player_name": "RFA player name", "offering_team": "", "years": "Years", "salary": "Salary/yr ($M)"}, "label": "Submit RFA Offer Sheet"}, {"path": "/api/rfa/match", "method": "POST", "args": ["player_name", "match"], "arg_labels": {"player_name": "Player name", "match": "true to match, false to decline"}, "label": "Match / Decline RFA Offer Sheet"}, {"path": "/api/extend_and_trade", "method": "POST", "args": ["player_name", "new_team", "years", "salary"], "arg_labels": {"player_name": "Player name", "new_team": "Destination team", "years": "Years", "salary": "Salary/yr ($M)"}, "label": "Extend-and-Trade a Player"}, {"path": "/api/check_designated_rookie", "method": "GET", "args": ["player"], "arg_labels": {"player": "Player name"}, "label": "Check Designated Rookie Eligibility"}, {"path": "/api/check_supermax", "method": "GET", "args": ["player"], "arg_labels": {"player": "Player name"}, "label": "Check Supermax Eligibility"}, {"path": "/api/attempt_unretirement", "method": "POST", "args": ["player_name", "team"], "arg_labels": {"player_name": "Retired player name", "team": ""}, "label": "Attempt Player Un-Retirement"}, {"path": "/api/what_would_it_take", "method": "GET", "args": ["player"], "arg_labels": {"player": "Target player name"}, "label": "\"What Would It Take\" for a Player"}, {"path": "/api/trade_finder_search", "method": "GET", "args": ["attribute", "attributes", "hide_untouchable", "max_age", "max_rating", "max_salary", "min_attribute", "min_rating", "position", "q", "team"], "arg_labels": {}, "label": "Trade Finder Search"}, {"path": "/api/find_trade_partners", "method": "GET", "args": ["players", "team"], "arg_labels": {}, "label": "Find Trade Partners"}, {"path": "/api/suggest_trade_package", "method": "GET", "args": [], "arg_labels": {}, "label": "Suggest Trade Package"}, {"path": "/api/team_intel", "method": "GET", "args": ["team"], "arg_labels": {}, "label": "Team Intel"}, {"path": "/api/shop_player", "method": "GET", "args": ["player", "team"], "arg_labels": {}, "label": "Shop Player"}]}, "draft": {"label": "Draft & Prospects", "items": [{"path": "/api/invest_scouting_region", "method": "POST", "args": ["team", "region", "points"], "arg_labels": {"team": "", "region": "Region (EuroLeague, G-League, NCAA, ...)", "points": "Points to invest"}, "label": "Invest Scouting Points in a Region"}, {"path": "/api/scouted_prospect_grade", "method": "GET", "args": ["team", "prospect"], "arg_labels": {"team": "", "prospect": "Prospect name"}, "label": "Scouted Prospect Grade"}, {"path": "/api/set_big_board_rank", "method": "POST", "args": ["prospect_name", "rank"], "arg_labels": {"prospect_name": "Prospect name", "rank": "Your rank"}, "label": "Set Custom Big Board Rank"}, {"path": "/api/simulate_dev_league_game", "method": "POST", "args": ["prospect_name"], "arg_labels": {"prospect_name": "Prospect name"}, "label": "Simulate a Dev/Summer League Game"}, {"path": "/api/grade_draft_pick", "method": "POST", "args": ["pick_no", "team", "prospect_name"], "arg_labels": {"pick_no": "Pick number", "team": "", "prospect_name": "Prospect name"}, "label": "Grade a Draft Pick"}, {"path": "/api/draft_lottery_ceremony", "method": "POST", "args": [], "arg_labels": {}, "label": "Run Draft Lottery Ceremony"}, {"path": "/api/redraft_simulator", "method": "GET", "args": ["year"], "arg_labels": {"year": "Draft year"}, "label": "Redraft a Past Draft Class"}, {"path": "/api/develop_academy_prospect", "method": "POST", "args": ["team"], "arg_labels": {"team": ""}, "label": "Develop an Academy Prospect"}]}, "sim": {"label": "Scheduling & Sim Controls", "items": [{"path": "/api/season_recap", "method": "GET", "args": [], "arg_labels": {}, "label": "Season Recap"}, {"path": "/api/simcast", "method": "GET", "args": [], "arg_labels": {}, "label": "Live SimCast (your last game)"}, {"path": "/api/call_timeout", "method": "POST", "args": ["team"], "arg_labels": {"team": ""}, "label": "Call a Timeout"}, {"path": "/api/legends_showcase", "method": "POST", "args": ["team"], "arg_labels": {"team": ""}, "label": "Simulate Legends Showcase Exhibition"}, {"path": "/api/championship_parade", "method": "POST", "args": ["team"], "arg_labels": {"team": ""}, "label": "Run Championship Parade"}, {"path": "/api/celebrity_legends_game", "method": "POST", "args": [], "arg_labels": {}, "label": "Run Celebrity/Legends Undercard Game"}, {"path": "/api/scouting_report", "method": "GET", "args": ["opponent"], "arg_labels": {"opponent": "Opponent team name"}, "label": "Scout an Upcoming Opponent"}, {"path": "/api/sim_week", "method": "POST", "args": [], "arg_labels": {}, "label": "Quick-Sim a Full Week"}, {"path": "/api/sim_season", "method": "POST", "args": [], "arg_labels": {}, "label": "Quick-Sim the Rest of the Season"}, {"path": "/api/sim_to_day", "method": "POST", "args": ["day"], "arg_labels": {"day": "Target day number"}, "label": "Quick-Sim to a Specific Day"}, {"path": "/api/quick_sim/next_game", "method": "POST", "args": [], "arg_labels": {}, "label": "Next Game"}, {"path": "/api/quick_sim/trade_deadline", "method": "POST", "args": [], "arg_labels": {}, "label": "Trade Deadline"}, {"path": "/api/advance_round", "method": "POST", "args": ["partner", "team"], "arg_labels": {}, "label": "Advance Round"}, {"path": "/api/start_playoffs", "method": "POST", "args": [], "arg_labels": {}, "label": "Start Playoffs"}]}, "analytics": {"label": "Analytics & Projections", "items": [{"path": "/api/advanced_analytics", "method": "GET", "args": ["player"], "arg_labels": {"player": "Player name"}, "label": "Advanced Analytics (TS%, PER, Clutch)"}, {"path": "/api/export_stats_csv", "method": "GET", "args": [], "arg_labels": {}, "label": "Export Season Stats (CSV download)"}, {"path": "/api/league_leaders", "method": "GET", "args": ["category"], "arg_labels": {"category": "PTS / AST / REB / FG% / 3P% / FT%"}, "label": "League Leaders (choose a stat)"}, {"path": "/api/clinch_tracker", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Clinch / Magic Number Tracker"}, {"path": "/api/win_total_vs_actual", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Win Total: Predicted vs Actual"}, {"path": "/api/home_away_splits", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Home/Away Net Rating Splits"}, {"path": "/api/referee_profile", "method": "GET", "args": ["name"], "arg_labels": {"name": "Referee name (optional)"}, "label": "Referee Tendency Profile"}, {"path": "/api/strength_of_schedule", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Strength of Schedule"}, {"path": "/api/predict_series_matchup", "method": "GET", "args": ["team_a", "team_b"], "arg_labels": {"team_a": "Team A", "team_b": "Team B"}, "label": "Predict a Playoff Series Matchup"}, {"path": "/api/two_way_roster_report", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Two-Way Roster Report"}, {"path": "/api/predict_win_totals", "method": "POST", "args": [], "arg_labels": {}, "label": "Predict Every Team's Win Total"}, {"path": "/api/clutch_win_probability", "method": "GET", "args": ["home_score", "away_score", "seconds_left", "has_ball_home"], "arg_labels": {"home_score": "Home score", "away_score": "Away score", "seconds_left": "Seconds left", "has_ball_home": "true or false"}, "label": "Clutch-Time Win Probability"}, {"path": "/api/standings_tiebreaker", "method": "GET", "args": ["team_a", "team_b"], "arg_labels": {"team_a": "Team A", "team_b": "Team B"}, "label": "Standings Tiebreaker Check"}]}, "leagueops": {"label": "League Operations", "items": [{"path": "/api/set_league_rule", "method": "POST", "args": ["rule", "value"], "arg_labels": {"rule": "Rule name (e.g. shot_clock_seconds)", "value": "New value"}, "label": "Set a League Rule"}, {"path": "/api/reset_league_rules", "method": "POST", "args": [], "arg_labels": {}, "label": "Reset League Rules to Default"}, {"path": "/api/set_difficulty", "method": "POST", "args": ["setting", "value"], "arg_labels": {"setting": "ai_trade_aggressiveness / injury_frequency / cap_strictness", "value": "Value 0-100"}, "label": "Set Difficulty Setting"}, {"path": "/api/set_theme", "method": "POST", "args": ["theme"], "arg_labels": {"theme": "dark / light / high_contrast / colorblind_friendly"}, "label": "Set UI Theme"}, {"path": "/api/set_score_bug_style", "method": "POST", "args": ["style"], "arg_labels": {"style": "Classic / Modern Minimal / Retro / Full Stats"}, "label": "Set Broadcast Score Bug Style"}, {"path": "/api/whatif/save", "method": "POST", "args": ["label", "from_year"], "arg_labels": {"label": "Branch name", "from_year": "Branch from year"}, "label": "Save a \"What-If\" History Branch"}, {"path": "/api/whatif/list", "method": "GET", "args": [], "arg_labels": {}, "label": "List \"What-If\" Branches"}, {"path": "/api/set_training_focus", "method": "POST", "args": ["team", "player_name", "focus"], "arg_labels": {"team": "", "player_name": "Player name", "focus": "Shooting / Finishing / Playmaking / Defense / Physical / Recovery / Film Study"}, "label": "Set In-Season Training Focus"}, {"path": "/api/training_focus", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "View Team's Training Focus Board"}, {"path": "/api/crowd_intensity", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Crowd Intensity Tonight"}, {"path": "/api/fan_approval", "method": "GET", "args": ["team"], "arg_labels": {"team": ""}, "label": "Fan Approval"}, {"path": "/api/league_rulebook", "method": "GET", "args": [], "arg_labels": {}, "label": "View League Rulebook"}, {"path": "/api/league_search", "method": "GET", "args": ["q"], "arg_labels": {}, "label": "League Search"}, {"path": "/api/rivalries", "method": "GET", "args": ["team"], "arg_labels": {}, "label": "Rivalries"}]}};
    const HUB_RENDERED = {};

    function hubTeamDefault() {
        return (typeof state !== 'undefined' && state && state.user_team) ? state.user_team : '';
    }

    // Every numeric-looking field gets a real, valid default -- these tools
    // used to default to a blank field, which crashed several backend
    // routes with a raw 500 debug page the moment someone hit Run without
    // typing a number first (or typed something non-numeric). The backend
    // is now defensive either way (safe_int/safe_float), but a sane default
    // means most people never even see a blank numeric box.
    const NUMERIC_ARG_DEFAULTS = {
        rank: '1', num_games: '4', day: '1', year: String(new Date().getFullYear()),
        points: '10', pick_no: '1', user_taps: '10', minutes_cap: '30', value: '50',
        n: '5', years: '3', from_year: String(new Date().getFullYear()),
        min_rating: '0', max_rating: '99', max_salary: '50', max_age: '40', min_attribute: '0',
        home_score: '0', away_score: '0', seconds_left: '24',
    };
    const NUMERIC_ARGS = new Set(Object.keys(NUMERIC_ARG_DEFAULTS));

    function hubArgDefault(argName) {
        const n = argName.toLowerCase();
        if (n === 'team' || n === 'team_a' || n === 'offering_team') return hubTeamDefault();
        if (n === 'category') return 'PTS';
        if (NUMERIC_ARG_DEFAULTS[n] !== undefined) return NUMERIC_ARG_DEFAULTS[n];
        if (n.includes('score')) return '0';
        if (n === 'has_ball_home') return 'true';
        if (HUB_ARG_CHOICES[n]) return HUB_ARG_CHOICES[n][0];
        return '';
    }
    function hubArgIsNumeric(argName) {
        return NUMERIC_ARGS.has(argName.toLowerCase()) || argName.toLowerCase().includes('score');
    }

    // A handful of args across the "More Tools" catalog are really a fixed
    // set of choices (validated server-side against an exact allow-list),
    // but were rendered as blank freeform text inputs -- so using them
    // meant guessing/remembering the exact valid string to type (checked
    // by actually calling every one of these 49 endpoints with a
    // placeholder value and reading back the server's "Choose from: ..."
    // validation errors). Render a real <select> for these instead so
    // they can't be mistyped.
    const HUB_ARG_CHOICES = {
        'tier': ['Budget', 'Standard', 'Premium', 'Luxury'],
        'theme': ['dark', 'light', 'high_contrast', 'colorblind_friendly'],
        'style': ['Classic', 'Modern Minimal', 'Retro', 'Full Stats'],
        'region': ['EuroLeague', 'G-League', 'NCAA', 'Australia/NBL', 'China/CBA', 'Africa/BAL'],
        'era': ['1984', '1992', '1998', '2003', '2011', '2016', 'Modern'],
        'setting': ['ai_trade_aggressiveness', 'injury_frequency', 'cap_strictness'],
        'focus': ['Shooting', 'Finishing', 'Playmaking', 'Defense', 'Physical', 'Recovery', 'Film Study'],
        'slider': ['Pace', 'Crash Glass', 'Defensive Pressure', 'Switch Everything', 'Double Team',
                   'Zone Frequency', 'Help Defense', 'Transition Focus', 'Bench Usage', 'Star Usage'],
        'rule': ['shot_clock_seconds', 'quarter_length_minutes', 'num_games', 'play_in_enabled',
                 'conferences_enabled', 'salary_cap', 'hard_cap_apron', 'luxury_tax_rate',
                 'max_roster_size', 'min_roster_size', 'trade_deadline_fraction', 'expansion_enabled'],
        'position': ['PG', 'SG', 'SF', 'PF', 'C'],
    };
    function hubArgChoices(argName) {
        return HUB_ARG_CHOICES[argName.toLowerCase()] || null;
    }

    function hubEscape(s) {
        return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    }

    // Reusable gauge ring (conic-gradient percentage dial) + info badge used
    // across the Franchise/Coaching/Trades/Draft/Sim/Analytics/League Ops
    // panels so they read with the same visual polish as GM Career / Awards
    // & Legacy / Media instead of being flatter stat-card-only screens.
    function gaugeCard(pct, title, sub) {
        const p = Math.max(0, Math.min(100, Number(pct) || 0));
        const color = p >= 66 ? '#2ee6a6' : p >= 40 ? '#ffb020' : '#ff5470';
        return `
        <div class="gauge-card">
            <div class="gauge-ring" style="background:conic-gradient(${color} ${p * 3.6}deg, #1d2c4d 0deg);">
                <div style="width:40px; height:40px; border-radius:50%; background:#0d1526; display:flex; align-items:center; justify-content:center;">${Math.round(p)}</div>
            </div>
            <div class="gauge-label-block">
                <div class="gl-title">${hubEscape(title)}</div>
                <div class="gl-sub">${hubEscape(sub || '')}</div>
            </div>
        </div>`;
    }

    function infoBadge(icon, title, value) {
        return `<div class="info-badge"><span>${icon}</span><span><b>${hubEscape(title)}:</b> ${hubEscape(value)}</span></div>`;
    }

    // Recursively render an arbitrary JSON value using the app's existing
    // hub-kv-grid / hub-table look.
    // UPGRADE PASS (generic result UI overhaul): this single renderer feeds
    // every "Advanced Tools" result across every tab, so fixing it here
    // fixes the "type text, click Run, get a raw JSON dump back" complaint
    // everywhere at once instead of one tool at a time. Specific bugs fixed:
    //   - tables silently capped at 6 columns with no way to see the rest
    //     (no horizontal scroll on this table type) -- now shows every
    //     column and scrolls horizontally instead of truncating data away
    //   - internal/plumbing fields (backstory_generated, a redundant
    //     `count` next to the array it's counting, a `success: true` flag)
    //     leaked into the display as raw snake_case -- now filtered out
    //   - every key showed as literal snake_case ("cap_space_est") instead
    //     of a readable label ("Cap Space Est")
    //   - numbers were printed as raw floats (16.699999999999) -- now
    //     rounded to something a person would actually read
    const HUB_HIDE_KEYS = new Set(['success', 'backstory_generated', 'status']);

    function hubPrettyLabel(key) {
        return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    function hubFormatScalar(v) {
        if (v === null || v === undefined || v === '') return '<span class="hub-result-empty">--</span>';
        if (typeof v === 'number') {
            return Number.isInteger(v) ? v.toLocaleString() : (Math.round(v * 100) / 100).toLocaleString();
        }
        if (typeof v === 'boolean') return v ? '✅ Yes' : '❌ No';
        // BUGFIX: a nested object/array landing in a table cell used to print
        // literally as "[object Object]" (e.g. League History's per-season
        // `standings` breakdown). Summarize instead of dumping raw JS.
        if (Array.isArray(v)) return v.length ? `${v.length} item${v.length === 1 ? '' : 's'}` : '--';
        if (typeof v === 'object') return Object.keys(v).length ? `${Object.keys(v).length} field${Object.keys(v).length === 1 ? '' : 's'}` : '--';
        return hubEscape(v);
    }

    function hubRenderValue(val) {
        if (val === null || val === undefined) return '<span class="hub-result-empty">--</span>';
        if (Array.isArray(val)) {
            if (val.length === 0) return '<span class="hub-result-empty">None</span>';
            if (typeof val[0] === 'object' && val[0] !== null) {
                // A few known noisy/low-signal columns get dropped from the
                // flat table view specifically (they're either internal
                // bookkeeping like is_backstory, or nested detail that's
                // more useful drilled into than crammed into a table cell).
                const HUB_TABLE_DROP_COLS = new Set(['is_backstory', 'highlight_reel']);
                const cols = Object.keys(val[0]).filter(c => !HUB_HIDE_KEYS.has(c) && !HUB_TABLE_DROP_COLS.has(c));
                let html = '<div class="hub-table-scroll"><table class="hub-table"><thead><tr>' +
                    cols.map(c => `<th>${hubEscape(hubPrettyLabel(c))}</th>`).join('') + '</tr></thead><tbody>';
                val.slice(0, 60).forEach(row => {
                    html += '<tr>' + cols.map(c => `<td>${hubFormatScalar(row[c])}</td>`).join('') + '</tr>';
                });
                html += '</tbody></table></div>';
                if (val.length > 60) html += `<div class="hub-result-empty mt-1">+ ${val.length - 60} more</div>`;
                return html;
            }
            return '<div>' + val.map(v => hubEscape(v)).join(', ') + '</div>';
        }
        if (typeof val === 'object') {
            let keys = Object.keys(val).filter(k => !HUB_HIDE_KEYS.has(k));
            // A `count` field is just the length of a sibling array/list --
            // redundant once that array is rendered as a table below it.
            const hasArraySibling = keys.some(k => Array.isArray(val[k]));
            if (hasArraySibling) keys = keys.filter(k => k !== 'count');
            if (keys.length === 0) return '<span class="hub-result-empty">Done.</span>';
            let html = '<div class="hub-kv-grid">';
            keys.forEach(k => {
                const v = val[k];
                if (v !== null && typeof v === 'object') {
                    html += `<div class="hub-kv-key">${hubEscape(hubPrettyLabel(k))}</div><div class="hub-kv-val">${hubRenderValue(v)}</div>`;
                } else {
                    html += `<div class="hub-kv-key">${hubEscape(hubPrettyLabel(k))}</div><div class="hub-kv-val">${hubFormatScalar(v)}</div>`;
                }
            });
            html += '</div>';
            return html;
        }
        return `<div>${hubEscape(val)}</div>`;
    }

    async function hubRunItem(groupKey, idx) {
        const item = HUB_CONFIG[groupKey].items[idx];
        const bodyId = `hubbody-${groupKey}-${idx}`;
        const body = document.getElementById(bodyId);
        if (!body) return;
        const argValues = {};
        (item.args || []).forEach(a => {
            const inp = document.getElementById(`hubarg-${groupKey}-${idx}-${a}`);
            argValues[a] = inp ? inp.value : '';
        });
        body.querySelector('.hub-result-box').innerHTML = '<span class="hub-spinner">Loading</span>';
        try {
            let res;
            if (item.method === 'POST') {
                res = await fetch(item.path, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(argValues) });
            } else {
                const qs = Object.keys(argValues).filter(k => argValues[k] !== '').map(k => `${encodeURIComponent(k)}=${encodeURIComponent(argValues[k])}`).join('&');
                res = await fetch(item.path + (qs ? ('?' + qs) : ''));
            }
            const data = await res.json();
            body.querySelector('.hub-result-box').innerHTML = hubRenderValue(data);
        } catch (e) {
            body.querySelector('.hub-result-box').innerHTML = '<span class="text-danger small">Request failed.</span>';
        }
    }
    window.hubRunItem = hubRunItem;

    function hubToggleRow(groupKey, idx) {
        const body = document.getElementById(`hubbody-${groupKey}-${idx}`);
        const chevron = document.getElementById(`hubchev-${groupKey}-${idx}`);
        const head = document.getElementById(`hubhead-${groupKey}-${idx}`);
        if (!body) return;
        const opening = body.style.display === 'none' || !body.style.display;
        body.style.display = opening ? 'block' : 'none';
        if (chevron) chevron.textContent = opening ? '▾' : '▸';
        if (head) head.classList.toggle('expanded', opening);
        if (opening) {
            const item = HUB_CONFIG[groupKey].items[idx];
            if (!item.args || item.args.length === 0) {
                hubRunItem(groupKey, idx);
            }
        }
    }
    window.hubToggleRow = hubToggleRow;

    function hubTeamOptions(selected) {
        const teams = (typeof state !== 'undefined' && state && Array.isArray(state.teams)) ? state.teams : [];
        const names = teams.map(t => (typeof t === 'string') ? t : t.name).filter(Boolean);
        if (names.length === 0) return `<option value="${hubEscape(selected || '')}">${hubEscape(selected || 'Loading teams...')}</option>`;
        return names.map(n => `<option value="${hubEscape(n)}" ${n === selected ? 'selected' : ''}>${hubEscape(n)}</option>`).join('');
    }

    function hubIsTeamArg(argName) {
        const n = argName.toLowerCase();
        return n === 'team' || n === 'team_a' || n === 'team_b' || n === 'offering_team' ||
               n === 'new_team' || n === 'hired_team' || n === 'previous_team' || n === 'opponent';
    }
    // UPGRADE PASS: player_name/player-style args were plain text boxes --
    // you had to know and type the exact full name with correct spelling.
    // A <datalist> gives real autocomplete against the actual league/team
    // roster (still a text input under the hood, so free entry still works
    // for retired/historical names not in the current player pool) without
    // needing a heavier picker component for 60+ different arg call sites.
    function hubIsPlayerArg(argName) {
        const n = argName.toLowerCase();
        return n.includes('player') || n === 'name' || n === 'a' || n === 'b' ||
               n === 'mentor_name' || n === 'prospect_name' || n === 'prospect' || n === 'player_a' || n === 'player_b';
    }
    let HUB_PLAYER_DATALIST_BUILT = false;
    function hubEnsurePlayerDatalist() {
        if (HUB_PLAYER_DATALIST_BUILT) return;
        HUB_PLAYER_DATALIST_BUILT = true;
        let dl = document.getElementById('hub-player-datalist');
        if (!dl) {
            dl = document.createElement('datalist');
            dl.id = 'hub-player-datalist';
            document.body.appendChild(dl);
        }
        fetch('/api/all_players_lite').then(r => r.json()).then(data => {
            const players = data.players || [];
            dl.innerHTML = players.map(p => `<option value="${hubEscape(p.name)}">${hubEscape(p.position || '')} · ${hubEscape(p.team || '')} · ${p.rating || ''} OVR</option>`).join('');
        }).catch(() => {});
    }

    function renderHubGroup(groupKey) {
        if (HUB_RENDERED[groupKey]) return;
        HUB_RENDERED[groupKey] = true;
        hubEnsurePlayerDatalist();
        const grid = document.getElementById(`hubgrid-${groupKey}`);
        if (!grid) return;
        const items = HUB_CONFIG[groupKey].items;
        let html = '';
        items.forEach((item, idx) => {
            const argsHtml = (item.args || []).map(a => {
                const choices = hubArgChoices(a);
                if (choices) {
                    return `<select class="hub-arg-input" id="hubarg-${groupKey}-${idx}-${a}" title="${hubEscape((item.arg_labels && item.arg_labels[a]) || a)}">
                        ${choices.map(c => `<option value="${hubEscape(c)}">${hubEscape(c)}</option>`).join('')}
                    </select>`;
                }
                if (hubIsTeamArg(a)) {
                    return `<select class="hub-arg-input" id="hubarg-${groupKey}-${idx}-${a}" title="${hubEscape((item.arg_labels && item.arg_labels[a]) || a)}">
                        ${hubTeamOptions(hubArgDefault(a))}
                    </select>`;
                }
                if (hubIsPlayerArg(a)) {
                    return `<input class="hub-arg-input" type="text" list="hub-player-datalist" id="hubarg-${groupKey}-${idx}-${a}" placeholder="${hubEscape((item.arg_labels && item.arg_labels[a]) || a)} -- start typing to search" value="">`;
                }
                return `<input class="hub-arg-input" type="${hubArgIsNumeric(a) ? 'number' : 'text'}" id="hubarg-${groupKey}-${idx}-${a}" placeholder="${hubEscape((item.arg_labels && item.arg_labels[a]) || a)}" value="${hubEscape(hubArgDefault(a))}">`;
            }).join('');
            html += `
            <div class="hub-menu-row">
                <div class="hub-menu-row-head" id="hubhead-${groupKey}-${idx}" onclick="hubToggleRow('${groupKey}', ${idx})">
                    <span>🔧 ${hubEscape(item.label)}</span>
                    <span class="hub-menu-chevron" id="hubchev-${groupKey}-${idx}">▸</span>
                </div>
                <div class="hub-menu-row-body" id="hubbody-${groupKey}-${idx}" style="display:none;">
                    ${argsHtml ? `<div class="mb-2">${argsHtml}<button class="hub-row-run-btn" onclick="hubRunItem('${groupKey}', ${idx})">▶ Run</button></div>` : ''}
                    <div class="hub-result-box">${argsHtml ? '<span class="hub-result-empty">Enter values above and tap Run.</span>' : '<span class="hub-spinner">Loading</span>'}</div>
                </div>
            </div>`;
        });
        grid.innerHTML = html;
    }
    window.renderHubGroup = renderHubGroup;

    // ==========================================================
    // BESPOKE PANELS -- GM Career, Awards & Legacy, Media & Fans
    // These are the three highest-traffic new hubs, so instead of the
    // generic expand-a-row list they get real 2K24-style menu layouts:
    // stat cards, ladders with rank/name/team/stat columns, press
    // conference option buttons, feed cards, etc.
    // ==========================================================
    // ----------------------------------------------------------------
    // Shared load-guard + error-safety wrapper for every "bespoke" hub
    // panel (GM Career, Media, Analytics, Franchise, etc).
    //
    // BUGFIX: each panel used to set its own "loaded" flag to true BEFORE
    // fetching data, then never clear it if something threw partway
    // through (a bad response, a network hiccup, a rapid double-open of
    // the tab racing two fetches against the same DOM). Once that flag was
    // stuck at true, the panel would refuse to ever render again -- which
    // is exactly what "this tab just says Loading forever" looked like
    // from the outside. This wrapper (a) skips a call if one is already
    // in-flight for that panel instead of letting two overlapping fetches
    // race each other, and (b) always clears the flag and shows a Retry
    // button on failure instead of leaving the panel stuck.
    // ----------------------------------------------------------------
    const BESPOKE_STATE = {};
    function bespokeGuardStart(key) {
        if (!BESPOKE_STATE[key]) BESPOKE_STATE[key] = { loaded: false, loading: false };
        const st = BESPOKE_STATE[key];
        if (st.loaded || st.loading) return false;
        st.loading = true;
        return true;
    }
    function bespokeGuardEnd(key, success) {
        const st = BESPOKE_STATE[key];
        if (!st) return;
        st.loading = false;
        st.loaded = !!success;
    }
    function bespokeReset(key) { if (BESPOKE_STATE[key]) BESPOKE_STATE[key].loaded = false; }
    window.bespokeReset = bespokeReset;
    function bespokeErrorHtml(e, retryFnName) {
        const msg = e && e.message ? hubEscape(String(e.message)) : 'unknown error';
        return `<p class="text-danger small">⚠ Couldn't load this panel (${msg}). <button class="btn btn-sm btn-outline-accent ms-2" onclick="${retryFnName}()">Retry</button></p>`;
    }
    window.bespokeErrorHtml = bespokeErrorHtml;

    async function jget(path) { const r = await fetch(path); return r.json(); }
    async function jpost(path, body) {
        const r = await fetch(path, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body || {}) });
        return r.json();
    }

    // ---------------- GM CAREER ----------------
    async function renderGmBespoke() {
        if (!bespokeGuardStart('gm')) return;
        try {
        const root = document.getElementById('gm-bespoke-root');
        const team = hubTeamDefault();
        const [report, dash, personality, resume] = await Promise.all([
            jget('/api/gm_report_card'), jget(`/api/gm_dashboard?team=${encodeURIComponent(team)}`),
            jget(`/api/gm_personality?team=${encodeURIComponent(team)}`), jget('/api/career_resume')
        ]);
        const d = dash.dashboard || {};
        const traits = personality.traits || {};
        // Reordered to read like an actual GM's homepage: who you are and
        // how you're doing first, your team's front office next, your
        // voice (press conferences) after that, and your career history /
        // outside interest last as a quieter footnote rather than a
        // headline action -- "check for job offers" as the first thing you
        // see reads like you're trying to leave your own team.
        let html = `
        <div class="stat-card-row">
            <div class="stat-card"><div class="sc-label">Overall Grade</div><div class="sc-value gold">${hubEscape(report.overall_grade || '--')}</div><div class="sc-sub">${hubEscape(report.record || '')}</div></div>
            <div class="stat-card"><div class="sc-label">Fan Approval</div><div class="sc-value">${hubEscape(report.fan_approval ?? '--')}%</div></div>
            <div class="stat-card"><div class="sc-label">Cap Space</div><div class="sc-value">$${hubEscape(d.cap_space ?? '--')}M</div><div class="sc-sub">${hubEscape(report.cap_health || '')}</div></div>
            <div class="stat-card"><div class="sc-label">Power Rank</div><div class="sc-value">#${hubEscape(d.power_rank ?? '--')}</div></div>
            <div class="stat-card"><div class="sc-label">Avg Roster Morale</div><div class="sc-value">${hubEscape(d.avg_morale ?? '--')}</div></div>
        </div>
        <div class="gm-archetype-badge mb-3">
            <span style="font-size:1.4rem;">${hubEscape(traits.emoji || '🧠')}</span>
            <div>
                <div style="font-weight:700; color:#eab308;">${hubEscape(personality.archetype || 'Unknown Archetype')} <span style="color:#7d93b8; font-weight:400; font-size:0.72rem;">— your GM style</span></div>
                <div style="color:#9db4d9; font-size:0.78rem;">${hubEscape(traits.desc || '')}</div>
            </div>
        </div>

        <div class="subsection-title mt-0">Front Office Staff</div>
        <div id="gm-fo-list"><span class="hub-spinner">Loading</span></div>

        <div class="subsection-title">Press Conference</div>
        <p class="text-white-50 small mb-2">What you say here shapes fan approval and locker room morale.</p>
        <div id="gm-presser-options"><span class="hub-spinner">Loading talking points</span></div>
        <div id="gm-presser-result" class="hub-result-box"></div>

        <div class="subsection-title">Career Timeline</div>
        <div id="gm-resume-list"></div>
        <div class="mt-2">
            <button class="hub-row-run-btn" style="background:#334155; color:#e2e8f0;" onclick="gmCheckJobOffers()">📞 Check External Interest</button>
            <span class="text-white-50 small ms-2">Other teams occasionally come calling if you're winning big — this doesn't commit you to anything.</span>
        </div>
        <div id="gm-offers-result" class="hub-result-box mt-2"></div>`;
        root.innerHTML = html;

        // press conference options
        const popts = await jget('/api/gm_press_conference_options');
        const optsEl = document.getElementById('gm-presser-options');
        optsEl.innerHTML = (popts.options || []).map(o =>
            `<button class="presser-opt-btn" onclick="gmHoldPresser('${o.id}')">${hubEscape(o.text)}</button>`
        ).join('') || '<span class="hub-result-empty">No talking points available.</span>';

        // career resume timeline -- render each stop as readable text
        // ("General Manager, Gotham Knights — since 2026") instead of
        // dumping the raw {team, role, year_started} object as JSON text.
        const hist = (resume.history || []);
        document.getElementById('gm-resume-list').innerHTML = hist.length
            ? hist.slice().reverse().map(h => {
                if (typeof h === 'string') return `<div class="resume-item">${hubEscape(h)}</div>`;
                const role = h.role || 'General Manager';
                const stopTeam = h.team || '';
                const yr = h.year_started !== undefined ? h.year_started : '';
                return `<div class="resume-item">${hubEscape(role)}${stopTeam ? `, ${hubEscape(stopTeam)}` : ''}${yr !== '' ? ` — since ${hubEscape(yr)}` : ''}</div>`;
            }).join('')
            : `<span class="hub-result-empty">This is your first logged stop — GM of ${hubEscape(team)}.</span>`;

        // front office roster
        const fo = await jget(`/api/front_office?team=${encodeURIComponent(team)}`);
        const staff = fo.staff || {};
        document.getElementById('gm-fo-list').innerHTML = Object.keys(staff).length
            ? Object.entries(staff).map(([role, name]) => `
                <div class="fo-role-row">
                    <span><b>${hubEscape(role)}:</b> ${hubEscape(name)}</span>
                    <button class="fo-hire-btn" onclick="gmHireStaff('${hubEscape(role)}')">Hire New</button>
                </div>`).join('')
            : '<span class="hub-result-empty">No staff on record.</span>';
            bespokeGuardEnd('gm', true);
        } catch (e) {
            bespokeGuardEnd('gm', false);
            const root = document.getElementById('gm-bespoke-root');
            if (root) root.innerHTML = bespokeErrorHtml(e, 'renderGmBespoke');
        }
    }
    window.renderGmBespoke = renderGmBespoke;

    async function gmHoldPresser(optionId) {
        const team = hubTeamDefault();
        const res = await jpost('/api/gm_press_conference', { team, option_id: optionId });
        document.getElementById('gm-presser-result').innerHTML = hubRenderValue(res);
    }
    window.gmHoldPresser = gmHoldPresser;

    async function gmCheckJobOffers() {
        const box = document.getElementById('gm-offers-result');
        box.innerHTML = '<span class="hub-result-empty">Checking...</span>';
        const res = await jget('/api/check_job_offers');
        box.innerHTML = hubRenderValue(res);
    }
    window.gmCheckJobOffers = gmCheckJobOffers;

    async function gmHireStaff(role) {
        const team = hubTeamDefault();
        await jpost('/api/hire_front_office_staff', { team, role });
        bespokeReset('gm');
        renderGmBespoke();
    }
    window.gmHireStaff = gmHireStaff;

    // ---------------- AWARDS & LEGACY ----------------
    function ladderRows(list, statKeys) {
        if (!list || !list.length) return '<span class="hub-result-empty">Not enough games played yet.</span>';
        return list.map(p => `
            <div class="ladder-row">
                <span class="ladder-rank">${p.rank}</span>
                <span class="ladder-name">${hubEscape(p.name)}</span>
                <span class="ladder-team">${hubEscape(p.team)}</span>
                <span class="ladder-stat">${statKeys.map(k => `${k.toUpperCase()} ${p[k]}`).join('  ·  ')}</span>
            </div>`).join('');
    }

    async function renderAwardsBespoke() {
        if (!bespokeGuardStart('awards')) return;
        try {
        const root = document.getElementById('awards-bespoke-root');
        const [mvp, roy, odds] = await Promise.all([jget('/api/mvp_ladder'), jget('/api/rookie_ladder'), jget('/api/award_odds_board')]);
        const mvpList = mvp.ladder || [];
        const royList = roy.ladder || [];
        const mvpOdds = odds.mvp_odds || {};
        root.innerHTML = `
        <div class="row">
            <div class="col-md-6">
                <div class="subsection-title mt-0">MVP Ladder</div>
                <div>${ladderRows(mvpList, ['ppg','apg','rpg'])}</div>
            </div>
            <div class="col-md-6">
                <div class="subsection-title mt-0">Rookie of the Year Ladder</div>
                <div>${ladderRows(royList, ['ppg','rpg','apg'])}</div>
            </div>
        </div>
        <div class="subsection-title">MVP Odds</div>
        <div>${Object.keys(mvpOdds).length ? Object.entries(mvpOdds).map(([name, pct]) => `
            <div class="odds-bar-wrap">
                <div class="odds-bar-label"><span>${hubEscape(name)}</span><span>${hubEscape(pct)}</span></div>
                <div class="odds-bar-track"><div class="odds-bar-fill" style="width:${parseFloat(pct) || 0}%;"></div></div>
            </div>`).join('') : '<span class="hub-result-empty">No odds yet.</span>'}</div>

        <div class="subsection-title">Hall of Fame Ballot</div>
        <div class="mb-2"><input class="hub-arg-input" id="hof-player-input" placeholder="Retired player name" style="width:220px;">
            <button class="hub-row-run-btn" onclick="awardsAddHof()">Add to Ballot</button>
            <button class="hub-row-run-btn" style="background:#334155; color:#e2e8f0; margin-left:6px;" onclick="awardsTallyHof()">Tally Vote</button></div>
        <div id="hof-result" class="hub-result-box"></div>

        <div class="subsection-title">Legacy Score Lookup</div>
        <div class="mb-2"><input class="hub-arg-input" id="legacy-player-input" placeholder="Player name" style="width:220px;">
            <button class="hub-row-run-btn" onclick="awardsLegacyLookup()">Look Up</button></div>
        <div id="legacy-result" class="hub-result-box"></div>`;
            bespokeGuardEnd('awards', true);
        } catch (e) {
            bespokeGuardEnd('awards', false);
            const root = document.getElementById('awards-bespoke-root');
            if (root) root.innerHTML = bespokeErrorHtml(e, 'renderAwardsBespoke');
        }
    }
    window.renderAwardsBespoke = renderAwardsBespoke;

    async function awardsAddHof() {
        const name = document.getElementById('hof-player-input').value;
        const res = await jpost('/api/hof_ballot/add', { player_name: name });
        document.getElementById('hof-result').innerHTML = hubRenderValue(res);
    }
    window.awardsAddHof = awardsAddHof;
    async function awardsTallyHof() {
        const res = await jpost('/api/hof_ballot/tally', {});
        document.getElementById('hof-result').innerHTML = hubRenderValue(res);
    }
    window.awardsTallyHof = awardsTallyHof;
    async function awardsLegacyLookup() {
        const name = document.getElementById('legacy-player-input').value;
        const res = await jget(`/api/legacy_score?player=${encodeURIComponent(name)}`);
        document.getElementById('legacy-result').innerHTML = hubRenderValue(res);
    }
    window.awardsLegacyLookup = awardsLegacyLookup;

    // ---------------- MEDIA & FAN ENGAGEMENT ----------------
    async function renderMediaBespoke() {
        if (!bespokeGuardStart('media')) return;
        try {
        const root = document.getElementById('media-bespoke-root');
        const team = hubTeamDefault();
        const [news, social, fan] = await Promise.all([
            jget('/api/news_archive'), jget('/api/social_media_feed'), jget('/api/fan_approval')
        ]);
        const newsList = (news.news || []).slice(0, 12);
        const socialList = (social.feed || []).slice(0, 12).reverse();
        root.innerHTML = `
        <div class="stat-card-row">
            <div class="stat-card"><div class="sc-label">Fan Approval</div><div class="sc-value gold">${hubEscape(fan.fan_approval ?? '--')}%</div></div>
            <div class="stat-card"><div class="sc-label">Market Size</div><div class="sc-value" style="font-size:1.1rem;">${hubEscape(fan.market_size ?? '--')}</div></div>
            <div class="stat-card"><div class="sc-label">Attendance Revenue</div><div class="sc-value" style="font-size:1.1rem;">$${hubEscape(fan.attendance_revenue ?? '--')}</div></div>
        </div>
        <div class="row">
            <div class="col-md-6">
                <div class="subsection-title mt-0">League News</div>
                <div>${newsList.length ? newsList.slice().reverse().map(n => `
                    <div class="feed-card">${hubEscape(n.icon || '📰')} ${hubEscape(n.text || n.headline || JSON.stringify(n))}
                        <div class="fc-meta">${hubEscape(n.kind || '')}</div></div>`).join('') : '<span class="hub-result-empty">No news yet.</span>'}</div>
            </div>
            <div class="col-md-6">
                <div class="subsection-title mt-0">Social Media</div>
                <div>${socialList.length ? socialList.map(s => `
                    <div class="feed-card">${hubEscape(typeof s === 'string' ? s : (s.text || JSON.stringify(s)))}</div>`).join('') : '<span class="hub-result-empty">Nothing trending yet.</span>'}</div>
            </div>
        </div>
        <div class="subsection-title">Press Roundtable</div>
        <button class="hub-row-run-btn mb-2" onclick="mediaGenPodcast()">Generate New Segment</button>
        <div id="media-podcast-result" class="hub-result-box mb-3"></div>
        <button class="hub-row-run-btn" onclick="mediaGenBeatWriter()">Get Beat Writer Report</button>
        <div id="media-beatwriter-result" class="hub-result-box"></div>`;
            bespokeGuardEnd('media', true);
        } catch (e) {
            bespokeGuardEnd('media', false);
            const root = document.getElementById('media-bespoke-root');
            if (root) root.innerHTML = bespokeErrorHtml(e, 'renderMediaBespoke');
        }
    }
    window.renderMediaBespoke = renderMediaBespoke;

    async function mediaGenPodcast() {
        const res = await jget('/api/podcast_roundtable');
        document.getElementById('media-podcast-result').innerHTML = hubRenderValue(res);
    }
    window.mediaGenPodcast = mediaGenPodcast;
    async function mediaGenBeatWriter() {
        const team = hubTeamDefault();
        const res = await jpost('/api/beat_writer_report', { team });
        document.getElementById('media-beatwriter-result').innerHTML = hubRenderValue(res);
    }
    window.mediaGenBeatWriter = mediaGenBeatWriter;

    // ---------------- FRANCHISE & BUSINESS (bespoke) ----------------
    async function renderFranchiseBespoke() {
        if (!bespokeGuardStart('franchise')) return;
        try {
        const team = hubTeamDefault();
        const root = document.getElementById('franchise-bespoke-root');
        const [biz, records, value, dynasty, ownerConf, ownerPersonality] = await Promise.all([
            jget(`/api/business_summary?team=${encodeURIComponent(team)}`),
            jget(`/api/franchise_records?team=${encodeURIComponent(team)}`),
            jget(`/api/franchise_value?team=${encodeURIComponent(team)}`),
            jget(`/api/team_dynasty_rating?team=${encodeURIComponent(team)}`),
            jget(`/api/ownership_confidence?team=${encodeURIComponent(team)}`),
            jget(`/api/owner_personality?team=${encodeURIComponent(team)}`)
        ]);
        const trophies = (records.trophy_room || []).length;
        const retiredJerseys = (records.retired_jerseys || []).length;
        const hof = (records.hall_of_fame || []).length;
        root.innerHTML = `
        <div class="gauge-row">
            ${gaugeCard(ownerConf.ownership_confidence, 'Owner Confidence', ownerPersonality.archetype || '')}
            ${gaugeCard(dynasty.dynasty_score, 'Dynasty Rating', `${dynasty.championships ?? 0} championship${dynasty.championships === 1 ? '' : 's'}`)}
        </div>
        <div class="stat-card-row">
            <div class="stat-card"><div class="sc-label">Franchise Value</div><div class="sc-value gold">$${hubEscape(value.estimated_value_millions ?? '--')}M</div></div>
            <div class="stat-card"><div class="sc-label">Est. Gate Revenue</div><div class="sc-value">$${hubEscape(biz.estimated_gate_revenue_millions ?? '--')}M</div></div>
            <div class="stat-card"><div class="sc-label">Sponsorship Revenue</div><div class="sc-value">$${hubEscape(biz.sponsorship_revenue_millions ?? '--')}M</div></div>
        </div>
        <div class="subsection-title mt-0">Trophy Case</div>
        <div class="d-flex flex-wrap gap-2 mb-2">
            ${infoBadge('🏆', 'Trophy Room Items', trophies)}
            ${infoBadge('👕', 'Retired Jerseys', retiredJerseys)}
            ${infoBadge('⭐', 'Hall of Famers', hof)}
        </div>
        <div class="subsection-title">Quick Actions</div>
        <div class="mini-select-row">
            <button class="hub-row-run-btn" onclick="franchiseQuickAction('sign_sponsorship')">🤝 Sign a Sponsorship</button>
            <button class="hub-row-run-btn" onclick="franchiseQuickAction('arena_naming_rights')">🏟️ Arena Naming Rights</button>
            <button class="hub-row-run-btn" onclick="franchiseQuickAction('jersey_patch_deal')">👕 Jersey Patch Deal</button>
            <span class="player-meta small ms-2">Ticket Tier:</span>
            <select id="franchise-ticket-tier" class="hub-arg-input" style="width:130px;" onchange="franchiseSetTicketTier(this.value)">
                <option value="Budget">Budget</option>
                <option value="Standard" selected>Standard</option>
                <option value="Premium">Premium</option>
                <option value="Luxury">Luxury</option>
            </select>
        </div>
        <div id="franchise-action-result" class="hub-result-box mt-2"></div>`;
        const tierSel = document.getElementById('franchise-ticket-tier');
        if (tierSel && biz.ticket_tier) tierSel.value = biz.ticket_tier;
            bespokeGuardEnd('franchise', true);
        } catch (e) {
            bespokeGuardEnd('franchise', false);
            const root = document.getElementById('franchise-bespoke-root');
            if (root) root.innerHTML = bespokeErrorHtml(e, 'renderFranchiseBespoke');
        }
    }
    window.renderFranchiseBespoke = renderFranchiseBespoke;

    async function franchiseSetTicketTier(tier) {
        const team = hubTeamDefault();
        const res = await jpost('/api/set_ticket_price', { team, tier });
        document.getElementById('franchise-action-result').innerHTML = hubRenderValue(res);
        if (res.success && typeof showToast === 'function') showToast(`Ticket tier set to ${tier}.`, 'success');
        bespokeReset('franchise');
        renderFranchiseBespoke();
    }
    window.franchiseSetTicketTier = franchiseSetTicketTier;

    async function franchiseQuickAction(endpoint) {
        const team = hubTeamDefault();
        const res = await jpost(`/api/${endpoint}`, { team });
        document.getElementById('franchise-action-result').innerHTML = hubRenderValue(res);
        bespokeReset('franchise');
        renderFranchiseBespoke();
    }
    window.franchiseQuickAction = franchiseQuickAction;

    // ---------------- COACHING & STRATEGY (bespoke) ----------------
    async function renderCoachingBespoke() {
        if (!bespokeGuardStart('coaching')) return;
        try {
        const team = hubTeamDefault();
        const root = document.getElementById('coaching-bespoke-root');
        const [conf, heat, plan, synergy, loadMgmt] = await Promise.all([
            jget(`/api/coach_confidence?team=${encodeURIComponent(team)}`),
            jget(`/api/coach_hot_seat?team=${encodeURIComponent(team)}`),
            jget(`/api/coaching_gameplan?team=${encodeURIComponent(team)}`),
            coachingFetchLineupSynergy(team),
            jget(`/api/load_management_suggestions?team=${encodeURIComponent(team)}`)
        ]);
        const gp = plan.gameplan || {};
        const sug = loadMgmt.suggestions || [];
        root.innerHTML = `
        <div class="gauge-row">
            ${gaugeCard(conf.confidence_pct, 'Coach Confidence', 'Front office trust level')}
            ${gaugeCard(heat.heat, 'Hot Seat Heat', (heat.heat ?? 0) > 60 ? 'On the hot seat' : 'Safe for now')}
        </div>
        <div class="subsection-title mt-0">Starting Lineup Synergy</div>
        ${synergy ? `
        <div class="info-badge mb-3">
            <span>🔗</span>
            <span><b>Net Rating Estimate:</b> ${synergy.net_rating_estimate > 0 ? '+' : ''}${hubEscape(synergy.net_rating_estimate)} &nbsp;·&nbsp; <b>Position Spread:</b> ${hubEscape(synergy.position_spread)}/5</span>
        </div>` : '<span class="hub-result-empty">Set a starting lineup in Team Management first.</span>'}

        <div class="subsection-title">Position Battle</div>
        <div class="mini-select-row">
            <select id="coaching-position-select" class="hub-arg-input" style="width:100px;">
                <option value="PG">PG</option><option value="SG">SG</option><option value="SF">SF</option><option value="PF">PF</option><option value="C">C</option>
            </select>
            <button class="hub-row-run-btn" onclick="coachingRunPositionBattle()">⚔️ Check Battle</button>
        </div>
        <div id="coaching-position-result" class="hub-result-box mb-3"></div>

        <div class="subsection-title">Load Management Suggestions</div>
        <div>${sug.length ? sug.map(s => `<div class="feed-card">🦵 ${hubEscape(typeof s === 'string' ? s : JSON.stringify(s))}</div>`).join('') : '<span class="hub-result-empty">No one needs a rest day right now.</span>'}</div>

        <div class="subsection-title">Gameplan Sliders</div>
        <div class="player-meta small mb-2">Drag any slider to adjust your team's game plan -- changes apply immediately and stack with your Offense/Defense scheme picks below.</div>
        ${(() => {
            // UPGRADE PASS: these 10 sliders used to render as one flat,
            // undifferentiated list -- no visual distinction between "this
            // affects how we score" and "this affects how we defend," which
            // made the panel harder to reason about than it needed to be.
            // Grouped to match how the offense/defense scheme dropdowns are
            // already organized elsewhere on this screen.
            const OFFENSE_SLIDER_KEYS = ["Pace", "Crash Glass", "Transition Focus", "Star Usage", "Bench Usage"];
            const DEFENSE_SLIDER_KEYS = ["Defensive Pressure", "Switch Everything", "Double Team", "Zone Frequency", "Help Defense"];
            const sliderRow = (k, v) => `
            <div class="odds-bar-wrap">
                <div class="odds-bar-label"><span>${hubEscape(k)}</span><span id="gp-val-${cssSafe(k)}">${hubEscape(v)}</span></div>
                <input type="range" min="0" max="100" value="${v}" class="form-range"
                    oninput="document.getElementById('gp-val-${cssSafe(k)}').innerText = this.value;"
                    onchange="coachingSetSlider('${k.replace(/'/g, "\\'")}', this.value)">
            </div>`;
            if (!Object.keys(gp).length) return '<span class="hub-result-empty">No gameplan set yet.</span>';
            return `
            <div class="subsection-title" style="font-size:0.85em; opacity:0.8;">🏀 Offense</div>
            <div id="coaching-gameplan-sliders-offense">${OFFENSE_SLIDER_KEYS.filter(k => k in gp).map(k => sliderRow(k, gp[k])).join('')}</div>
            <div class="subsection-title mt-2" style="font-size:0.85em; opacity:0.8;">🛡 Defense</div>
            <div id="coaching-gameplan-sliders-defense">${DEFENSE_SLIDER_KEYS.filter(k => k in gp).map(k => sliderRow(k, gp[k])).join('')}</div>
            `;
        })()}
        <div id="coaching-gameplan-result" class="hub-result-box mt-1"></div>`;
            bespokeGuardEnd('coaching', true);
        } catch (e) {
            bespokeGuardEnd('coaching', false);
            const root = document.getElementById('coaching-bespoke-root');
            if (root) root.innerHTML = bespokeErrorHtml(e, 'renderCoachingBespoke');
        }
    }
    window.renderCoachingBespoke = renderCoachingBespoke;

    async function coachingFetchLineupSynergy(team) {
        try {
            const starters = (state.teams && state.teams[team] && state.teams[team].starters) || {};
            const names = Object.values(starters).filter(Boolean);
            if (names.length < 2) return null;
            return await jpost('/api/lineup_synergy', { players: names });
        } catch (e) { return null; }
    }

    async function coachingRunPositionBattle() {
        const team = hubTeamDefault();
        const position = document.getElementById('coaching-position-select').value;
        const res = await jpost('/api/position_battle', { team, position });
        document.getElementById('coaching-position-result').innerHTML = hubRenderValue(res);
    }
    window.coachingRunPositionBattle = coachingRunPositionBattle;

    function cssSafe(s) { return s.replace(/[^a-zA-Z0-9]/g, '_'); }

    async function coachingSetSlider(sliderName, value) {
        const team = hubTeamDefault();
        const res = await jpost('/api/set_coaching_gameplan', { team, slider: sliderName, value: parseInt(value, 10) });
        const box = document.getElementById('coaching-gameplan-result');
        if (res.success) {
            if (typeof showToast === 'function') showToast(`${sliderName} set to ${value}.`, 'success');
        } else if (box) {
            box.innerHTML = `<span class="text-danger small">${hubEscape(res.reason || 'Could not update gameplan.')}</span>`;
        }
    }
    window.coachingSetSlider = coachingSetSlider;

    // ---------------- DRAFT & PROSPECTS (bespoke) ----------------
    async function renderDraftBespoke() {
        if (!bespokeGuardStart('draft')) return;
        try {
        const root = document.getElementById('draft-bespoke-root');
        const [cls, board] = await Promise.all([jget('/api/draft_class_strength'), jget('/api/big_board')]);
        const topProspects = (board.board || []).slice(0, 8);
        const clsHtml = cls.success === false
            ? `<span class="hub-result-empty">${hubEscape(cls.reason || 'No draft class generated yet.')}</span>`
            : `<div class="stat-card-row">
                <div class="stat-card"><div class="sc-label">Class Strength</div><div class="sc-value gold" style="font-size:1.2rem;">${hubEscape(cls.class_grade ?? '--')}</div></div>
                <div class="stat-card"><div class="sc-label">Avg Rating</div><div class="sc-value">${hubEscape(cls.avg_rating ?? '--')}</div></div>
                <div class="stat-card"><div class="sc-label">Elite Prospects</div><div class="sc-value">${hubEscape(cls.elite_prospects ?? '--')}</div></div>
               </div>`;
        root.innerHTML = `
        ${clsHtml}
        <div class="subsection-title">Big Board — Top Prospects</div>
        <div class="player-meta small mb-2">Set your own rank for any prospect -- it sticks and re-sorts the board. Tap a name to view their full profile, or hit Scout to spend scouting points on them.</div>
        <div id="draft-bigboard-rows">${topProspects.length ? topProspects.map((p, i) => `
            <div class="ladder-row">
                <input type="number" class="hub-arg-input" style="width:52px; margin-right:8px;" value="${p.custom_rank ?? (i + 1)}"
                    onchange="draftSetBigBoardRank('${p.name.replace(/'/g, "\\'")}', this.value)">
                <a class="ladder-name player-link" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')">${hubEscape(p.name)}</a>
                <span class="ladder-stat">${hubEscape(p.scouted_rating)} OVR (scouted)</span>
                <button class="btn btn-sm btn-outline-info py-0 px-1 ms-1" style="font-size:0.7rem;" title="Spend scouting points on this prospect" onclick="draftScoutProspect('${p.name.replace(/'/g, "\\'")}')">🔍 Scout</button>
            </div>`).join('') : '<span class="hub-result-empty">No prospects scouted yet.</span>'}</div>
        <div id="draft-scout-result" class="hub-result-box mt-2"></div>`;
            bespokeGuardEnd('draft', true);
        } catch (e) {
            bespokeGuardEnd('draft', false);
            const root = document.getElementById('draft-bespoke-root');
            if (root) root.innerHTML = bespokeErrorHtml(e, 'renderDraftBespoke');
        }
    }
    window.renderDraftBespoke = renderDraftBespoke;

    async function draftScoutProspect(prospectName) {
        const team = hubTeamDefault();
        const res = await jget(`/api/scouted_prospect_grade?team=${encodeURIComponent(team)}&prospect=${encodeURIComponent(prospectName)}`);
        document.getElementById('draft-scout-result').innerHTML = `<div class="feed-card"><b>${hubEscape(prospectName)}</b><br>${hubRenderValue(res)}</div>`;
    }
    window.draftScoutProspect = draftScoutProspect;

    async function draftSetBigBoardRank(prospectName, rank) {
        await jpost('/api/set_big_board_rank', { prospect_name: prospectName, rank: parseInt(rank, 10) });
        if (typeof showToast === 'function') showToast(`${prospectName} ranked #${rank} on your board.`, 'success');
        bespokeReset('draft');
        renderDraftBespoke();
    }
    window.draftSetBigBoardRank = draftSetBigBoardRank;

    // ---------------- SIM CONTROLS (bespoke) ----------------
    async function renderSimBespoke() {
        if (!bespokeGuardStart('sim')) return;
        try {
        const root = document.getElementById('sim-bespoke-root');
        const team = hubTeamDefault();
        const [countdown, sos] = await Promise.all([
            jget('/api/trade_deadline_countdown'),
            jget(`/api/strength_of_schedule?team=${encodeURIComponent(team)}`)
        ]);
        const seasonPct = state.current_day && state.schedule_days_total
            ? Math.round(100 * state.current_day / state.schedule_days_total) : 0;
        root.innerHTML = `
        <div class="gauge-row">
            ${gaugeCard(100 - (countdown.days_until_deadline ?? 100) * 100 / 200, 'Trade Deadline', `${countdown.days_until_deadline ?? '--'} days away${countdown.is_deadline_day ? ' — TODAY!' : ''}`)}
            ${gaugeCard(seasonPct, 'Season Progress', `Day ${state.current_day ?? '--'} of ${state.schedule_days_total ?? '--'}`)}
        </div>
        <div class="info-badge mb-3">📅 <b>Schedule Difficulty:</b> ${hubEscape(sos.difficulty ?? '--')} (avg opponent wins: ${hubEscape(sos.avg_opponent_wins ?? '--')})</div>

        <div class="subsection-title mt-0">Scout Next Opponent</div>
        <div class="mini-select-row">
            <input class="hub-arg-input" id="sim-scout-opponent" placeholder="Opponent team name" style="width:220px;">
            <button class="hub-row-run-btn" onclick="simScoutOpponent()">🔭 Scout</button>
        </div>
        <div id="sim-scout-result" class="hub-result-box mb-3"></div>

        <div class="subsection-title">Special Events</div>
        <div class="d-flex flex-wrap gap-2">
            <button class="hub-row-run-btn" onclick="simQuickAction('summer_league')">☀️ Simulate Summer League</button>
            <button class="hub-row-run-btn" onclick="simQuickAction('preseason_games')">🏀 Simulate Preseason</button>
            <button class="hub-row-run-btn" onclick="simQuickAction('global_game')">🌍 Simulate a Global Game</button>
            <button class="hub-row-run-btn" onclick="simQuickAction('media_day')">🎤 Hold Media Day</button>
        </div>
        <div id="sim-action-result" class="hub-result-box mt-2"></div>`;
            bespokeGuardEnd('sim', true);
        } catch (e) {
            bespokeGuardEnd('sim', false);
            const root = document.getElementById('sim-bespoke-root');
            if (root) root.innerHTML = bespokeErrorHtml(e, 'renderSimBespoke');
        }
    }
    window.renderSimBespoke = renderSimBespoke;

    async function simScoutOpponent() {
        const opp = document.getElementById('sim-scout-opponent').value;
        const res = await jget(`/api/scouting_report?opponent=${encodeURIComponent(opp)}`);
        document.getElementById('sim-scout-result').innerHTML = hubRenderValue(res);
    }
    window.simScoutOpponent = simScoutOpponent;

    async function simQuickAction(endpoint) {
        const team = hubTeamDefault();
        const res = await jpost(`/api/${endpoint}`, { team });
        document.getElementById('sim-action-result').innerHTML = hubRenderValue(res);
    }
    window.simQuickAction = simQuickAction;

    // ---------------- ANALYTICS & PROJECTIONS (bespoke) ----------------
    async function renderAnalyticsBespoke() {
        if (!bespokeGuardStart('analytics')) return;
        try {
        const root = document.getElementById('analytics-bespoke-root');
        const team = hubTeamDefault();
        const [odds, playoffs, splits] = await Promise.all([
            jget('/api/championship_odds'),
            jget('/api/playoff_picture_projector'),
            jget(`/api/home_away_splits?team=${encodeURIComponent(team)}`)
        ]);
        const oddsTop = (odds.odds || []).slice(0, 6);
        const proj = playoffs.projection || {};
        const confBlock = (name, rows) => `
            <div class="subsection-title mt-0">${hubEscape(name)}</div>
            <div>${(rows || []).slice(0, 8).map(r => `
                <div class="ladder-row">
                    <span class="ladder-rank">${r.seed}</span>
                    <span class="ladder-name">${hubEscape(r.team)}</span>
                    <span class="ladder-stat">${hubEscape(r.wins)}W · ${hubEscape(r.status)}</span>
                </div>`).join('') || '<span class="hub-result-empty">No standings yet.</span>'}</div>`;
        root.innerHTML = `
        <div class="gauge-row">
            ${gaugeCard((splits.home_win_pct_est ?? 0) * 100, 'Home Win % (est.)', '')}
            ${gaugeCard((splits.away_win_pct_est ?? 0) * 100, 'Away Win % (est.)', '')}
        </div>
        <div class="subsection-title mt-0">Championship Odds</div>
        <div>${oddsTop.length ? oddsTop.map((o, i) => `
            <div class="odds-bar-wrap">
                <div class="odds-bar-label"><span>${i === 0 ? '🏆 ' : ''}${hubEscape(o.team)}</span><span>${hubEscape(o.title_pct)}%</span></div>
                <div class="odds-bar-track"><div class="odds-bar-fill" style="width:${o.title_pct}%; ${i === 0 ? 'background:linear-gradient(90deg,#ffb020,#f59e0b);' : ''}"></div></div>
            </div>`).join('') : '<span class="hub-result-empty">No odds yet.</span>'}</div>
        <div class="row">
            <div class="col-md-6">${confBlock('East Playoff Picture', proj.East)}</div>
            <div class="col-md-6">${confBlock('West Playoff Picture', proj.West)}</div>
        </div>`;
            bespokeGuardEnd('analytics', true);
        } catch (e) {
            bespokeGuardEnd('analytics', false);
            const root = document.getElementById('analytics-bespoke-root');
            if (root) root.innerHTML = bespokeErrorHtml(e, 'renderAnalyticsBespoke');
        }
    }
    window.renderAnalyticsBespoke = renderAnalyticsBespoke;

    // ---------------- LEAGUE OPERATIONS (bespoke) ----------------
    async function renderLeagueopsBespoke() {
        if (!bespokeGuardStart('leagueops')) return;
        try {
        const root = document.getElementById('leagueops-bespoke-root');
        const team = hubTeamDefault();
        const [pr, rules, recap, riv] = await Promise.all([
            jget('/api/power_rankings'), jget('/api/league_rules'), jget('/api/season_recap'),
            jget(`/api/rivalries?team=${encodeURIComponent(team)}`)
        ]);
        const rows = (pr.rankings || pr.rows || []).slice(0, 6);
        // BUGFIX: this read rules.defaults first, showing the ORIGINAL
        // static defaults instead of the league's actual current rules --
        // so changing a rule here would never reflect what you'd actually set.
        const d = rules.rules || rules.defaults || {};
        const rivalries = riv.rivalries || [];
        root.innerHTML = `
        ${recap.headline ? `<div class="feed-card">🏆 ${hubEscape(recap.headline)}</div>` : ''}
        <div class="player-meta small mb-2">Tap any value below to edit it -- changes apply immediately.</div>
        <div class="stat-card-row">
            <div class="stat-card"><div class="sc-label">Games / Season</div>
                <input type="number" class="hub-arg-input mt-1" style="width:100%;" value="${d.num_games ?? ''}" onchange="leagueopsSetRule('num_games', this.value)"></div>
            <div class="stat-card"><div class="sc-label">Luxury Tax Rate</div>
                <input type="number" step="0.05" class="hub-arg-input mt-1" style="width:100%;" value="${d.luxury_tax_rate ?? ''}" onchange="leagueopsSetRule('luxury_tax_rate', this.value)"></div>
            <div class="stat-card"><div class="sc-label">Hard Cap Apron ($M)</div>
                <input type="number" step="0.5" class="hub-arg-input mt-1" style="width:100%;" value="${d.hard_cap_apron ?? ''}" onchange="leagueopsSetRule('hard_cap_apron', this.value)"></div>
            <div class="stat-card"><div class="sc-label">Min / Max Roster</div>
                <div class="d-flex gap-1 mt-1">
                    <input type="number" class="hub-arg-input" style="width:50%;" value="${d.min_roster_size ?? ''}" onchange="leagueopsSetRule('min_roster_size', this.value)">
                    <input type="number" class="hub-arg-input" style="width:50%;" value="${d.max_roster_size ?? ''}" onchange="leagueopsSetRule('max_roster_size', this.value)">
                </div></div>
        </div>
        <div id="leagueops-rule-result" class="hub-result-box mb-2"></div>

        <div class="subsection-title">Rivalries</div>
        <div class="mb-2">${rivalries.length ? rivalries.map(r => `<span class="jersey-badge d-inline-block me-1 mb-1" style="font-size:0.78rem;">🔥 ${hubEscape(typeof r === 'string' ? r : (r.team || JSON.stringify(r)))}</span>`).join('') : '<span class="hub-result-empty">No rivalries have developed yet.</span>'}</div>

        <div class="subsection-title">Power Rankings (Top 6)</div>
        <div>${rows.length ? rows.map((r, i) => `
            <div class="ladder-row">
                <span class="ladder-rank">${i + 1}</span>
                <span class="ladder-name">${hubEscape(r.team)}</span>
                <span class="ladder-stat">${hubEscape(r.wins)}-${hubEscape(r.losses)}${r.identity ? '  ·  ' + hubEscape(r.identity) : ''}</span>
            </div>`).join('') : '<span class="hub-result-empty">Not enough games played yet.</span>'}</div>`;
            bespokeGuardEnd('leagueops', true);
        } catch (e) {
            bespokeGuardEnd('leagueops', false);
            const root = document.getElementById('leagueops-bespoke-root');
            if (root) root.innerHTML = bespokeErrorHtml(e, 'renderLeagueopsBespoke');
        }
    }
    window.renderLeagueopsBespoke = renderLeagueopsBespoke;

    async function leagueopsSetRule(rule, value) {
        const res = await jpost('/api/set_league_rule', { rule, value });
        const box = document.getElementById('leagueops-rule-result');
        if (res.success) {
            if (typeof showToast === 'function') showToast(`${rule.replace(/_/g, ' ')} updated.`, 'success');
        } else if (box) {
            box.innerHTML = `<span class="text-danger small">${hubEscape(res.reason || 'Could not update that rule.')}</span>`;
        }
    }
    window.leagueopsSetRule = leagueopsSetRule;

    // ---------------- TRADES & CONTRACTS (bespoke) ----------------
    async function renderContractsBespoke() {
        if (!bespokeGuardStart('contracts')) return;
        try {
        const team = hubTeamDefault();
        const root = document.getElementById('contracts-bespoke-root');
        const [cap, needs, buyout] = await Promise.all([
            jget(`/api/cap_projection?team=${encodeURIComponent(team)}`),
            jget(`/api/team_needs?team=${encodeURIComponent(team)}`),
            jget('/api/buyout_market')
        ]);
        const proj = (cap.projection || []).slice(0, 4);
        const needsList = needs.needs || [];
        const market = buyout.market || [];
        root.innerHTML = `
        <div class="subsection-title mt-0">Cap Projection</div>
        <div class="stat-card-row">
            ${proj.length ? proj.map(p => `
                <div class="stat-card">
                    <div class="sc-label">${hubEscape(p.year)}</div>
                    <div class="sc-value gold" style="font-size:1.2rem;">$${hubEscape(p.committed !== undefined ? p.committed.toFixed(1) : '--')}M</div>
                    <div class="sc-sub">committed${p.contracts_expiring ? ` · ${p.contracts_expiring} expiring` : ''}</div>
                </div>`).join('') : '<span class="hub-result-empty">No projection available.</span>'}
        </div>
        <div class="subsection-title">Team Needs</div>
        <div class="mb-3">${needsList.length ? needsList.map(pos => `<span class="jersey-badge d-inline-block me-1 mb-1" style="font-size:0.78rem;">${hubEscape(pos)}</span>`).join('') : '<span class="hub-result-empty">Roster looks balanced right now.</span>'}</div>

        <div class="subsection-title">Buyout Market</div>
        <div class="mb-3">${market.length ? market.map(p => `<div class="feed-card">💵 ${hubEscape(typeof p === 'string' ? p : (p.name || JSON.stringify(p)))}</div>`).join('') : '<span class="hub-result-empty">No players have been bought out this season yet.</span>'}</div>

        <div class="subsection-title">Compare Two Players</div>
        <div class="mini-select-row">
            <input class="hub-arg-input" id="contracts-cmp-a" placeholder="Player A" style="width:170px;">
            <input class="hub-arg-input" id="contracts-cmp-b" placeholder="Player B" style="width:170px;">
            <button class="hub-row-run-btn" onclick="contractsComparePlayers()">⚖️ Compare</button>
        </div>
        <div id="contracts-cmp-result" class="hub-result-box mb-3"></div>

        <div class="subsection-title">What Would It Take?</div>
        <div class="mini-select-row">
            <input class="hub-arg-input" id="contracts-wwit-player" placeholder="Player name" style="width:220px;">
            <button class="hub-row-run-btn" onclick="contractsWhatWouldItTake()">🤔 Ask</button>
        </div>
        <div id="contracts-wwit-result" class="hub-result-box"></div>`;
            bespokeGuardEnd('contracts', true);
        } catch (e) {
            bespokeGuardEnd('contracts', false);
            const root = document.getElementById('contracts-bespoke-root');
            if (root) root.innerHTML = bespokeErrorHtml(e, 'renderContractsBespoke');
        }
    }
    window.renderContractsBespoke = renderContractsBespoke;

    async function contractsComparePlayers() {
        const a = document.getElementById('contracts-cmp-a').value;
        const b = document.getElementById('contracts-cmp-b').value;
        const res = await jget(`/api/compare_players?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
        document.getElementById('contracts-cmp-result').innerHTML = hubRenderValue(res);
    }
    window.contractsComparePlayers = contractsComparePlayers;

    async function contractsWhatWouldItTake() {
        const player = document.getElementById('contracts-wwit-player').value;
        const res = await jget(`/api/what_would_it_take?player=${encodeURIComponent(player)}`);
        document.getElementById('contracts-wwit-result').innerHTML = hubRenderValue(res);
    }
    window.contractsWhatWouldItTake = contractsWhatWouldItTake;

    // Wire the new sidebar hub buttons: lazily render their panel the first
    // time each one is opened, on top of the existing switchTab() behavior.
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.side-nav-btn').forEach(btn => {
            const onclick = btn.getAttribute('onclick') || '';
            const m = onclick.match(/switchTab\('hub-([a-z2]+)'/);
            if (m) {
                const map = { gm:'gm', franchise:'franchise', media:'media', awards:'awards',
                              coaching:'coaching', contracts:'frontoffice2', draft:'draft',
                              sim:'sim', analytics:'analytics', leagueops:'leagueops' };
                const key = map[m[1]];
                if (key) {
                    btn.addEventListener('click', () => renderHubGroup(key));
                    if (key === 'gm') btn.addEventListener('click', renderGmBespoke);
                    if (key === 'awards') btn.addEventListener('click', renderAwardsBespoke);
                    if (key === 'media') btn.addEventListener('click', renderMediaBespoke);
                    if (key === 'franchise') btn.addEventListener('click', renderFranchiseBespoke);
                    if (key === 'coaching') btn.addEventListener('click', renderCoachingBespoke);
                    if (key === 'draft') btn.addEventListener('click', renderDraftBespoke);
                    if (key === 'sim') btn.addEventListener('click', renderSimBespoke);
                    if (key === 'analytics') btn.addEventListener('click', renderAnalyticsBespoke);
                    if (key === 'leagueops') btn.addEventListener('click', renderLeagueopsBespoke);
                    if (key === 'frontoffice2') btn.addEventListener('click', renderContractsBespoke);
                }
            }
        });
    });