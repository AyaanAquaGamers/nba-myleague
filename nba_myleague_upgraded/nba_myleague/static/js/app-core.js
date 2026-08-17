    // ==========================================================
    // UPGRADE BATCH 6 -- Sound Effects & Background Ambience
    // ==========================================================
    // Fully self-contained Web Audio API sound engine -- no external audio
    // files, so it works offline / in this single-file app with no asset
    // hosting. Generates crowd murmur, buzzers, swishes, whistles, and UI
    // clicks procedurally. Settings (on/off + volume) persist in
    // localStorage so they survive a page reload.
    const SoundEngine = (() => {
        let ctx = null;
        let ambienceNodes = null;
        let enabled = localStorage.getItem('hoopsim_sound_enabled') !== 'false';
        let sfxVolume = parseFloat(localStorage.getItem('hoopsim_sfx_volume') ?? '0.5');
        let ambienceVolume = parseFloat(localStorage.getItem('hoopsim_ambience_volume') ?? '0.18');
        let ambienceOn = localStorage.getItem('hoopsim_ambience_on') === 'true';

        function getCtx() {
            if (!ctx) {
                ctx = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (ctx.state === 'suspended') ctx.resume();
            return ctx;
        }

        function noiseBuffer(c, seconds) {
            const buf = c.createBuffer(1, c.sampleRate * seconds, c.sampleRate);
            const data = buf.getChannelData(0);
            for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
            return buf;
        }

        function tone(freq, duration, type, vol, delay) {
            if (!enabled) return;
            const c = getCtx();
            const osc = c.createOscillator();
            const gain = c.createGain();
            osc.type = type || 'sine';
            osc.frequency.value = freq;
            const t0 = c.currentTime + (delay || 0);
            gain.gain.setValueAtTime(0.0001, t0);
            gain.gain.exponentialRampToValueAtTime(Math.max(0.0001, vol * sfxVolume), t0 + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
            osc.connect(gain).connect(c.destination);
            osc.start(t0);
            osc.stop(t0 + duration + 0.05);
        }

        function noiseBurst(seconds, vol, filterFreq) {
            if (!enabled) return;
            const c = getCtx();
            const src = c.createBufferSource();
            src.buffer = noiseBuffer(c, seconds);
            const filter = c.createBiquadFilter();
            filter.type = 'bandpass';
            filter.frequency.value = filterFreq || 1200;
            const gain = c.createGain();
            const t0 = c.currentTime;
            gain.gain.setValueAtTime(0.0001, t0);
            gain.gain.exponentialRampToValueAtTime(Math.max(0.0001, vol * sfxVolume), t0 + 0.05);
            gain.gain.exponentialRampToValueAtTime(0.0001, t0 + seconds);
            src.connect(filter).connect(gain).connect(c.destination);
            src.start(t0);
        }

        const sfx = {
            click: () => tone(700, 0.05, 'sine', 0.1),
            swish: () => { tone(1200, 0.1, 'sine', 0.15); tone(1600, 0.07, 'sine', 0.08, 0.05); },
            buzzer: () => tone(180, 0.7, 'triangle', 0.22),
            whistle: () => { tone(2300, 0.2, 'sine', 0.18); tone(2500, 0.16, 'sine', 0.12, 0.08); },
            crowdCheer: () => { noiseBurst(1.2, 0.22, 700); noiseBurst(0.9, 0.14, 1400); },
            cash: () => { tone(880, 0.07, 'sine', 0.12); tone(1046, 0.07, 'sine', 0.12, 0.06); tone(1318, 0.1, 'sine', 0.12, 0.12); },
            error: () => { tone(220, 0.12, 'sine', 0.12); tone(180, 0.16, 'sine', 0.12, 0.1); },
            // UPGRADE (item 7 pass): a short rising fanfare for a locked-in
            // draft pick -- previously the draft had zero distinct audio,
            // just the generic UI click, despite being one of the most
            // watched moments in the whole app.
            draftPick: () => { tone(660, 0.09, 'triangle', 0.14); tone(880, 0.09, 'triangle', 0.16, 0.09); tone(1100, 0.14, 'triangle', 0.18, 0.18); },
        };

        // ---- Low-beat basketball ambience ----
        // A mellow lo-fi loop instead of a raw noise-floor hum: a soft kick
        // on the downbeats, a gentle brushed hi-hat on the off-beats, and an
        // occasional basketball dribble-bounce accent -- all synthesized,
        // no samples. Uses standard Web-Audio lookahead scheduling so the
        // rhythm stays tight instead of drifting like a plain setInterval loop.
        let ambienceTimer = null;
        let nextNoteTime = 0;
        let beatIndex = 0;
        const BPM = 78;
        const SECONDS_PER_BEAT = 60 / BPM;
        const STEPS_PER_BEAT = 2; // eighth notes

        function scheduleKick(t) {
            const c = getCtx();
            const osc = c.createOscillator();
            const gain = c.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(110, t);
            osc.frequency.exponentialRampToValueAtTime(45, t + 0.18);
            gain.gain.setValueAtTime(ambienceVolume * 0.9, t);
            gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.32);
            osc.connect(gain).connect(c.destination);
            osc.start(t); osc.stop(t + 0.35);
        }

        function scheduleHat(t, soft) {
            const c = getCtx();
            const src = c.createBufferSource();
            src.buffer = noiseBuffer(c, 0.06);
            const filter = c.createBiquadFilter();
            filter.type = 'highpass';
            filter.frequency.value = 6000;
            const gain = c.createGain();
            gain.gain.setValueAtTime(ambienceVolume * (soft ? 0.12 : 0.2), t);
            gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.05);
            src.connect(filter).connect(gain).connect(c.destination);
            src.start(t);
        }

        function scheduleDribble(t) {
            // A short, pitch-dropping thump -- evokes a ball bounce, sits
            // low in the mix so it reads as texture, not a sample.
            const c = getCtx();
            const osc = c.createOscillator();
            const gain = c.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(180, t);
            osc.frequency.exponentialRampToValueAtTime(70, t + 0.09);
            gain.gain.setValueAtTime(ambienceVolume * 0.55, t);
            gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.12);
            osc.connect(gain).connect(c.destination);
            osc.start(t); osc.stop(t + 0.14);
        }

        function ambienceScheduler() {
            const c = getCtx();
            while (nextNoteTime < c.currentTime + 0.12) {
                const step = beatIndex % (STEPS_PER_BEAT * 4); // 4-beat bar, 8 steps
                if (step === 0 || step === 4) scheduleKick(nextNoteTime);
                if (step % 2 === 1) scheduleHat(nextNoteTime, true);
                if (step === 6) scheduleDribble(nextNoteTime); // one soft dribble accent per bar
                nextNoteTime += SECONDS_PER_BEAT / STEPS_PER_BEAT;
                beatIndex++;
            }
        }

        function startAmbience() {
            if (!enabled || ambienceTimer) return;
            const c = getCtx();
            nextNoteTime = c.currentTime + 0.05;
            beatIndex = 0;
            ambienceTimer = setInterval(ambienceScheduler, 50);
            ambienceNodes = true; // just a flag now; the scheduler owns the actual nodes per-note
        }

        function stopAmbience() {
            if (ambienceTimer) {
                clearInterval(ambienceTimer);
                ambienceTimer = null;
            }
            ambienceNodes = null;
        }

        function setEnabled(v) {
            enabled = v;
            localStorage.setItem('hoopsim_sound_enabled', v ? 'true' : 'false');
            if (!v) stopAmbience(); else if (ambienceOn) startAmbience();
        }

        function setAmbienceOn(v) {
            ambienceOn = v;
            localStorage.setItem('hoopsim_ambience_on', v ? 'true' : 'false');
            if (v && enabled) startAmbience(); else stopAmbience();
        }

        function setSfxVolume(v) { sfxVolume = v; localStorage.setItem('hoopsim_sfx_volume', v); }
        function setAmbienceVolume(v) {
            ambienceVolume = v;
            localStorage.setItem('hoopsim_ambience_volume', v);
            // Volume is read live by the scheduler on each note, so no
            // stale gain-node reference to update here.
        }

        return {
            sfx, setEnabled, setAmbienceOn, setSfxVolume, setAmbienceVolume,
            isEnabled: () => enabled, isAmbienceOn: () => ambienceOn,
            getSfxVolume: () => sfxVolume, getAmbienceVolume: () => ambienceVolume,
        };
    })();

    // Play a UI click on any button press in the app, and infer game-flavor
    // sound effects from which API endpoint just got hit -- one hook point
    // instead of touching every simulate/trade/waive call site individually.
    document.addEventListener('click', (e) => {
        if (e.target.closest('button')) SoundEngine.sfx.click();
    });
    (function () {
        const origFetch = window.fetch;
        window.fetch = function (url, opts) {
            const p = origFetch.apply(this, arguments);
            try {
                const u = (typeof url === 'string') ? url : (url && url.url) || '';
                if (u.includes('/api/sim_day') || u.includes('/api/simulate_playoff_games') || u.includes('/api/simulate_play_in')) {
                    p.then(r => r.clone().json()).then(data => {
                        if (data && data.status !== 'blocked') {
                            SoundEngine.sfx.buzzer();
                            setTimeout(() => SoundEngine.sfx.crowdCheer(), 250);
                        } else if (data && data.status === 'blocked') {
                            SoundEngine.sfx.error();
                        }
                    }).catch(() => {});
                } else if (u.includes('/api/propose_trade') || u.includes('/api/counter_offer') || u.includes('/api/evaluate_trade') || u.includes('/api/draft_trade')) {
                    p.then(r => r.clone().json()).then(data => {
                        SoundEngine.sfx[data && (data.success || data.status === 'success') ? 'cash' : 'error']();
                    }).catch(() => {});
                } else if (u.includes('/api/waive_player') || u.includes('/api/offer_extension') || u.includes('/api/sign_free_agent')) {
                    p.then(r => r.clone().json()).then(data => {
                        SoundEngine.sfx[data && (data.success !== false) ? 'swish' : 'error']();
                    }).catch(() => {});
                } else if (u.includes('/api/draft_pick')) {
                    // UPGRADE (item 7 pass): draft picks previously had no
                    // distinct sound at all -- just the generic button click
                    // shared by every other button in the app. Skip the
                    // "warning" status (the low-scouting confirmation
                    // prompt) -- that's not an error, just a question, so it
                    // shouldn't play the error buzz.
                    p.then(r => r.clone().json()).then(data => {
                        if (!data) return;
                        if (data.status === 'success') SoundEngine.sfx.draftPick();
                        else if (data.status === 'error') SoundEngine.sfx.error();
                    }).catch(() => {});
                }
            } catch (e) { /* never let sound wiring break the real request */ }
            return p;
        };
    })();


    let state = {};
    const OFFENSE_STYLES_JS = ["Balanced", "Pace & Space", "Post-Up Heavy", "Iso-Heavy", "Motion Offense", "Fast Break Heavy", "Pick-and-Roll Heavy", "Small Ball", "Grit and Grind"];
    const DEFENSE_STYLES_JS = ["Man-to-Man", "2-3 Zone Package", "Full-Court Press", "Switch Everything", "Box-and-1", "Triangle-and-2", "Drop Coverage", "Blitz the Pick-and-Roll"];
    let activeTeamFilter = null;
    // UPGRADE: Sortable season stats table -- was hardcoded to always sort by
    // PPG descending. Now any column header is clickable; clicking the same
    // column again flips ascending/descending, matching a normal spreadsheet.
    let statsSortKey = 'PPG';
    let statsSortDir = -1; // -1 = descending, 1 = ascending
    let tradeSelection = { your_players: [], your_picks: [], their_players: [], their_picks: [] };
    let pickProtections = {}; // pick_id -> protection tier, for picks YOU are sending away
    let currentTradePartner = null; // BUGFIX: tracks who the builder is currently set up for, so
                                     // periodic background refreshes don't wipe the user's picks
    const PROTECTION_TIERS = ["None", "Top-4 Protected", "Top-10 Protected", "Lottery Protected"];

    const ATTRIBUTE_CATEGORIES = {
        "Finishing": ["Close Shot", "Driving Layup", "Driving Dunk", "Post Control", "Standing Dunk", "Post Hook", "Contact Finishing"],
        "Shooting": ["Mid-Range", "Three-Point", "Free Throw", "Shot IQ", "Off-the-Dribble", "Corner Shooting"],
        "Playmaking": ["Passing Accuracy", "Ball Handling", "Speed With Ball", "Vision", "Ball Security", "Pick & Roll Passing"],
        "Defense": ["Interior Defense", "Perimeter Defense", "Steal", "Block", "Lateral Quickness", "Help Defense IQ", "Pick & Roll Defense", "Post Defense", "On-Ball Defense IQ", "Weakside Rim Protection"],
        "Rebounding": ["Offensive Rebound", "Defensive Rebound", "Boxout", "Rebound Positioning"],
        "Physical": ["Speed", "Strength", "Vertical", "Stamina", "Hustle", "Durability", "Agility", "Length"],
        "Intangibles": ["Clutch Factor", "Consistency", "Leadership", "Basketball IQ"]
    };
    const TENDENCY_LIST = ["Shoot 3PT", "Shoot Mid-Range", "Drive to Rim", "Post Up", "Pass", "Iso",
        "Crash Offensive Glass", "Draw Fouls", "Catch & Shoot", "Spot Up", "Transition", "Post Fade",
        "Pick & Roll Ball Handler", "Help Defense", "Clutch Shooting", "Cut to Basket", "Screen Setting",
        "Fast Break Finish", "Contest Shots", "Take Charges",
        "Attack Closeouts", "Step-Back Jumper", "Post Spin Move", "Dribble Hand-Off", "Off-Ball Movement",
        "Kick Out Pass", "Isolation Post-Up", "And-1 Attempts", "Deny Passing Lanes", "Zone Positioning",
        "Switch on Defense", "Backdoor Cuts", "Putback Attempts", "Late Clock Shots", "Rim Protection Tendency",
        "Full-Court Press", "Corner Three Attempts", "Double Team Trigger", "Fast Break Ball Handling", "Flashy Passing"];

    // =========================================================
    // BADGE SYSTEM (NBA 2K-style) — a player earns a badge once his
    // relevant attributes cross a threshold, and the badge is graded
    // Bronze -> Silver -> Gold -> Hall of Fame the higher those attributes
    // go. Badges are a readable summary of the exact attributes the sim
    // engine already uses to generate box scores (shooting %, rebounding,
    // steals, turnovers, fatigue/injury resistance, etc) — a Gold badge
    // means that part of the sim is meaningfully boosted for that player,
    // an HOF badge means it's elite.
    // =========================================================
    const BADGE_TIERS = [
        {min: 96, name: "Hall of Fame", color: "#fbbf24", cls: "hof"},
        {min: 88, name: "Gold", color: "#facc15", cls: "gold"},
        {min: 78, name: "Silver", color: "#cbd5e1", cls: "silver"},
        {min: 68, name: "Bronze", color: "#d97706", cls: "bronze"},
    ];
    function badgeTierFor(value) {
        for (const t of BADGE_TIERS) if (value >= t.min) return t;
        return null;
    }
    const BADGE_DEFS = [
        {name: "Sharpshooter", icon: "🎯", attrs: (a) => (a["Three-Point"]),
         desc: "Knocks down open catch-and-shoot threes at an elite clip. Higher tier = better open 3PT%."},
        {name: "Deadeye", icon: "🧊", attrs: (a) => (a["Three-Point"] * 0.5 + a["Shot IQ"] * 0.5),
         desc: "Stays money even with a hand in his face. Higher tier = less accuracy lost on contested jumpers."},
        {name: "Slasher", icon: "⚡", attrs: (a) => (a["Driving Layup"] * 0.5 + a["Driving Dunk"] * 0.5),
         desc: "Gets to the rim and finishes through contact. Higher tier = better finishing % at the basket."},
        {name: "Posterizer", icon: "💥", attrs: (a) => (a["Standing Dunk"] * 0.5 + a["Vertical"] * 0.5),
         desc: "Throws down highlight dunks over defenders. Higher tier = more emphatic, higher-value finishes."},
        {name: "Post Menace", icon: "🐘", attrs: (a) => (a["Post Control"] * 0.5 + a["Strength"] * 0.5),
         desc: "Bullies smaller defenders on the block. Higher tier = better post scoring efficiency."},
        {name: "Dimer", icon: "🎯", attrs: (a) => (a["Passing Accuracy"] * 0.5 + a["Vision"] * 0.5),
         desc: "Elite table-setter who finds the open man. Higher tier = more assists generated per game."},
        {name: "Handles", icon: "🕹️", attrs: (a) => (a["Ball Handling"] * 0.5 + a["Speed With Ball"] * 0.5),
         desc: "Breaks defenders down off the dribble. Higher tier = fewer turnovers and better shot creation."},
        {name: "Lockdown Defender", icon: "🔒", attrs: (a) => (a["Perimeter Defense"] * 0.5 + a["Lateral Quickness"] * 0.5),
         desc: "Shuts down the opposing team's primary scorer. Higher tier = bigger dent in opponent efficiency."},
        {name: "Rim Protector", icon: "🧱", attrs: (a) => (a["Interior Defense"] * 0.5 + a["Block"] * 0.5),
         desc: "Alters and swats shots at the basket. Higher tier = more blocks and lower opponent FG% inside."},
        {name: "Pickpocket", icon: "🧤", attrs: (a) => (a["Steal"]),
         desc: "Jumps passing lanes and strips ball-handlers. Higher tier = more steals generated per game."},
        {name: "Glass Cleaner", icon: "🧹", attrs: (a) => (a["Offensive Rebound"] * 0.33 + a["Defensive Rebound"] * 0.33 + a["Boxout"] * 0.34),
         desc: "Dominates the boards on both ends. Higher tier = more rebounds pulled down per game."},
        {name: "Iron Man", icon: "🛡️", attrs: (a) => (a["Durability"]),
         desc: "Rarely misses time. Higher tier = a much lower chance of getting hurt over the season."},
        {name: "Motor", icon: "🔋", attrs: (a) => (a["Stamina"] * 0.5 + a["Hustle"] * 0.5),
         desc: "Plays hard for all 48 minutes. Higher tier = fatigue builds up slower and recovers faster."},
        {name: "Free Throw Ace", icon: "🎟️", attrs: (a) => (a["Free Throw"]),
         desc: "Automatic from the charity stripe. Higher tier = higher free-throw percentage."},
        {name: "Clutch Gene", icon: "🥶", attrs: (a) => (a["Clutch Factor"]),
         desc: "Elevates in crunch time. Higher tier = better performance in the final minutes of close games."},
        {name: "Mr. Consistent", icon: "📈", attrs: (a) => (a["Consistency"]),
         desc: "Brings the same level every night. Higher tier = fewer off-nights and cold streaks."},
        {name: "Off-the-Dribble Sniper", icon: "🎯", attrs: (a) => (a["Off-the-Dribble"] * 0.6 + a["Ball Handling"] * 0.4),
         desc: "Pulls up in rhythm off the dribble. Higher tier = better pull-up jumper efficiency."},
        {name: "Hook Specialist", icon: "🪝", attrs: (a) => (a["Post Hook"]),
         desc: "Automatic with the running hook in the paint. Higher tier = higher hook-shot accuracy."},
        {name: "Pick Dodger", icon: "🚧", attrs: (a) => (a["Pick & Roll Defense"]),
         desc: "Navigates screens without losing his man. Higher tier = fewer easy looks allowed off ball screens."},
        {name: "Post Lockdown", icon: "🚫", attrs: (a) => (a["Post Defense"]),
         desc: "Makes post touches a fight. Higher tier = tougher post defense, lower opponent post efficiency."},
        {name: "Ball Security", icon: "🔐", attrs: (a) => (a["Ball Security"]),
         desc: "Rarely turns it over under pressure. Higher tier = fewer live-ball turnovers."},
    ];
    function computePlayerBadges(p) {
        if (!p || !p.attributes) return [];
        const a = p.attributes;
        const out = [];
        BADGE_DEFS.forEach(b => {
            const val = b.attrs(a);
            const tier = badgeTierFor(val);
            if (tier) out.push({name: b.name, icon: b.icon, tier: tier.name, color: tier.color, cls: tier.cls, desc: b.desc, val: Math.round(val)});
        });
        out.sort((x, y) => y.val - x.val);
        return out;
    }
    function agentEmoji(personality) {
        const map = {'Loyalty':'🤝','Business':'💰','Ring Chaser':'💍','Balanced':'⚖️'};
        return map[personality] || '';
    }

    function badgeChipsHtml(p, max) {
        const badges = computePlayerBadges(p);
        if (badges.length === 0) return '<span class="text-white-50" style="font-size:0.72rem;">—</span>';
        const shown = max ? badges.slice(0, max) : badges;
        let html = shown.map(b => `<span title="${b.tier} ${b.name}: ${b.desc}" style="border:1px solid ${b.color};color:${b.color};border-radius:8px;padding:0 5px;font-size:0.68rem;margin-right:2px;white-space:nowrap;display:inline-block;margin-bottom:2px;">${b.icon} ${b.name}</span>`).join('');
        if (max && badges.length > max) html += `<span class="text-white-50" style="font-size:0.68rem;">+${badges.length - max}</span>`;
        return html;
    }

    let lastKnownStage = null;
    let finalsAdvanceRequested = false;
    let openModal = null;  // {type: 'series'|'box'|'player', ...} or null
    // IMPORTANT: which tab is showing is tracked ONLY client-side. The server's
    // current_tab field is never updated by any endpoint, so trusting it here
    // (as the old code did) meant every 2-second poll silently reset rendering
    // back to whatever the server's default was -- that's what caused tabs to
    // "freeze" or coaching prefs to "reset on their own". activeTab is the
    // single source of truth for what to (re)render.
    let activeTab = 'dashboard';
    let pendingOfferModalOpen = false;

    async function refreshState() {
        const response = await fetch('/api/state');
        state = await response.json();

        // UPGRADE: Era selection comes first -- a brand new league doesn't
        // even have real rosters/history until an era is picked, so this
        // gate blocks everything else, including the team picker.
        if (!state.era_chosen) {
            renderEraPicker();
            return;
        }
        const eraOverlay = document.getElementById('era-picker-overlay');
        if (eraOverlay) eraOverlay.style.display = 'none';

        // UPGRADE: Team selection. Previously the GM job was silently
        // auto-assigned (always Gotham Knights) -- now the app shows a
        // blocking picker on first launch and holds off on normal
        // rendering until the user actually picks a franchise.
        if (!state.team_chosen) {
            renderTeamPicker();
            return;
        }
        const pickerOverlay = document.getElementById('team-picker-overlay');
        if (pickerOverlay) pickerOverlay.style.display = 'none';

        renderActiveTab();
        renderSidebarStatus();
        renderTicker();
        checkPendingOffer();
        refreshNotifBadge();

        // Auto-advance the user to the Front Office once the offseason opens, so
        // finishing the playoffs never leaves the user stuck looking at a stale screen.
        if (lastKnownStage && lastKnownStage !== 'offseason' && state.stage === 'offseason' &&
            (activeTab === 'playoffs' || activeTab === 'stats' || activeTab === 'calendar')) {
            switchTab('frontoffice', document.querySelector("button[onclick*='frontoffice']"));
        }
        // UPGRADE: Confetti on championship clinch — fires once when the
        // simulation crosses from playoffs into offseason and the most recent
        // history entry shows the user's team as champion.
        if (lastKnownStage && lastKnownStage !== 'offseason' && state.stage === 'offseason') {
            const lastEntry = (state.history || []).slice(-1)[0];
            if (lastEntry && lastEntry.champion === state.user_team) {
                launchConfetti();
            }
        }
        lastKnownStage = state.stage;
        checkPressConference();
        renderFanApprovalWidget();

        // Keep whichever modal is currently open live -- re-paint it with the
        // freshly fetched state instead of leaving it frozen on stale data.
        if (openModal && openModal.type === 'series') {
            showSeriesModal(openModal.r, openModal.mIdx, true);
        } else if (openModal && openModal.type === 'box') {
            showBoxScore(openModal.boxType, openModal.identity, true);
        } else if (openModal && openModal.type === 'player') {
            showPlayerModal(openModal.name, true);
        } else if (openModal && openModal.type === 'coach') {
            showCoachModal(openModal.name, true);
        }
    }

    // Background refresh every 2 seconds so long-running simulations (playoff
    // rounds, season sims) never leave the visible screen stale, no matter which
    // tab is currently open.
    let lastSeenVersion = 0;

    // UPGRADE: Team selection screen. Renders once (rosters/ratings don't
    // change before the season starts) and lets the user pick any of the
    // 30 franchises to GM instead of being auto-assigned one.
    // UPGRADE: Era selection -- step 1 of onboarding, before the team picker.
    const ERA_ICONS = {"1984": "🕺", "1992": "🌟", "1998": "🔒", "2003": "👑", "2011": "🚀", "2016": "🎯", "Modern": "📊"};
    let eraCatalog = null;
    async function renderEraPicker() {
        const overlay = document.getElementById('era-picker-overlay');
        const grid = document.getElementById('era-picker-grid');
        if (!overlay || !grid) return;
        overlay.style.display = 'block';
        const teamOverlay = document.getElementById('team-picker-overlay');
        if (teamOverlay) teamOverlay.style.display = 'none';
        if (grid.dataset.built) return;

        if (!eraCatalog) {
            const res = await fetch('/api/eras');
            eraCatalog = await res.json();
        }
        grid.innerHTML = eraCatalog.order.map(eraId => {
            const era = eraCatalog.eras[eraId];
            const safeId = eraId.replace(/'/g, "\\'");
            return `<div class="col-md-6 col-lg-4">
                <div class="p-3 bg-dark rounded border border-secondary h-100 d-flex flex-column justify-content-between" style="cursor:pointer;" onclick="chooseEra('${safeId}')">
                    <div>
                        <div class="fw-bold text-white mb-1">${ERA_ICONS[eraId] || '🏀'} ${era.label}</div>
                        <div class="small text-white-50 mb-2">Salary Cap: <span class="text-warning">$${era.salary_cap}M</span> · Draft: ${era.draft_style}</div>
                        <div class="small text-white-50">${era.uniform_style}</div>
                        <div class="small text-white-50">${era.court_style}</div>
                        <div class="small text-info mt-2">"${era.commentary_style}"</div>
                    </div>
                    <button class="btn btn-outline-accent btn-sm mt-3 w-100">Start This Era</button>
                </div>
            </div>`;
        }).join('');
        grid.dataset.built = '1';
    }
    window.renderEraPicker = renderEraPicker;

    async function chooseEra(eraId) {
        const era = eraCatalog.eras[eraId];
        if (!confirm(`Start a new league in the ${era.label}? This generates a fresh 30-team league and full history back to 1984 -- this can't be undone.`)) return;
        const res = await fetch('/api/choose_era', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({era: eraId})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        const grid = document.getElementById('team-picker-grid');
        if (grid) grid.dataset.built = ''; // rosters are brand new for this era -- force the team picker to rebuild
        document.getElementById('era-picker-overlay').style.display = 'none';
        await refreshState();
    }
    window.chooseEra = chooseEra;

    function renderTeamPicker() {
        const overlay = document.getElementById('team-picker-overlay');
        const grid = document.getElementById('team-picker-grid');
        if (!overlay || !grid) return;
        overlay.style.display = 'block';
        if (grid.dataset.built) return;

        const playersByTeam = {};
        Object.values(state.players).forEach(p => {
            if (!p.team) return;
            (playersByTeam[p.team] = playersByTeam[p.team] || []).push(p);
        });
        const teams = Object.keys(state.teams).sort();
        grid.innerHTML = teams.map(t => {
            const roster = playersByTeam[t] || [];
            const avgRating = roster.length ? (roster.reduce((s, p) => s + p.rating, 0) / roster.length).toFixed(1) : '—';
            const star = roster.slice().sort((a, b) => b.rating - a.rating)[0];
            const conf = (state.teams[t] || {}).conference || '';
            const safeName = t.replace(/'/g, "\\'");
            return `<div class="col-md-4 col-lg-3">
                <div class="p-3 bg-dark rounded border border-secondary h-100 d-flex flex-column justify-content-between" style="cursor:pointer; border-top:4px solid ${teamColor(t)};" onclick="chooseTeam('${safeName}')">
                    <div>
                        <div class="fw-bold text-white">${t}</div>
                        <div class="small text-white-50 mb-2">${conf} Conference</div>
                        <div class="small">Avg Rating: <span class="text-warning">${avgRating}</span></div>
                        ${star ? `<div class="small">Best Player: ${star.name} (${star.rating} OVR)</div>` : ''}
                    </div>
                    <button class="btn btn-outline-accent btn-sm mt-3 w-100">Become GM</button>
                </div>
            </div>`;
        }).join('');
        grid.dataset.built = '1';
    }
    window.renderTeamPicker = renderTeamPicker;

    async function chooseTeam(team) {
        if (!confirm(`Become the GM of the ${team}? You can change this later from Front Office, but it's meant to be a real choice.`)) return;
        const res = await fetch('/api/choose_team', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({team})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
    }
    window.chooseTeam = chooseTeam;

    // Lets a GM switch franchises later from Front Office -- rebuilds the
    // picker grid fresh (ratings/rosters may have changed since launch) and
    // reuses the same chooseTeam() flow.
    function reopenTeamPicker() {
        const grid = document.getElementById('team-picker-grid');
        if (grid) grid.dataset.built = '';
        renderTeamPicker();
    }
    window.reopenTeamPicker = reopenTeamPicker;

    async function pollHeartbeat() {
        try {
            const res = await fetch('/api/heartbeat');
            const hb = await res.json();
            if (hb.version !== lastSeenVersion || hb.has_pending_offer) {
                lastSeenVersion = hb.version;
                await refreshState();
            }
        } catch (e) { /* transient network hiccup -- just try again next tick */ }
    }
    // BUGFIX (critical): the only thing that ever fetched game state was
    // this heartbeat poller, and it only called refreshState() when the
    // server's version counter DIFFERED from lastSeenVersion (which starts
    // at 0 on every fresh page load). Right when a league is brand new --
    // exactly the moment someone is sitting on the Era or Team selection
    // screen -- the server's version genuinely IS still 0, since nothing
    // has happened yet to increment it. 0 !== 0 is false, so refreshState()
    // never fired at all: no era picker, no team picker, nothing, on any
    // fresh load or refresh before the first real action. Do one
    // unconditional state fetch immediately on startup, THEN start the
    // heartbeat loop for ongoing updates.
    //
    // UPGRADE: the game previously auto-persisted in memory with no
    // concept of "unsaved progress" -- sim a few days, refresh the tab,
    // and you'd silently resume exactly where you left off. That's now
    // intentional-save-only: every real page load first resets the server
    // to a fresh, unstarted league before doing anything else, so a
    // refresh always restarts the onboarding flow unless you explicitly
    // use Load Game afterward to restore a save slot. This only runs once
    // here at true page load -- switching tabs within the app (which
    // never reloads the page) never touches this at all.
    (async () => {
        try { await fetch('/api/reset_new_session', { method: 'POST' }); } catch (e) { /* fall through to refreshState either way */ }
        refreshState();
        setInterval(pollHeartbeat, 2000);
    })();

    // A trade offer can surface mid-simulation (see auto-sim / sim-to-date).
    // Whenever one is pending, show it as a blocking popup -- regardless of
    // which tab is open -- and pause any auto-sim loop until it's resolved.
    function checkPendingOffer() {
        const overlay = document.getElementById('offer-popup-overlay');
        const modalBox = document.getElementById('offer-popup-modal');
        if (!overlay || !modalBox) return;
        if (state.pending_offer) {
            stopAutoSim();
            stopPlayoffAutoSim();
            if (!pendingOfferModalOpen) {
                pendingOfferModalOpen = true;
                overlay.style.display = 'block';
                modalBox.style.display = 'block';
            }
            renderOfferPopup();
        } else if (pendingOfferModalOpen) {
            pendingOfferModalOpen = false;
            overlay.style.display = 'none';
            modalBox.style.display = 'none';
        }
    }

    function renderOfferPopup() {
        const offer = state.pending_offer;
        if (!offer) return;
        // UPGRADE: clickable player pills (not plain text) so you can check
        // stats/attributes before deciding, and a Negotiate option -- this
        // popup used to only offer Accept/Decline.
        const playerPill = (name) => {
            const p = state.players[name];
            const ovrTxt = p ? ` <small style="color:${attrColor(p.rating)}; font-weight:700;">(${p.rating} OVR)</small>` : '';
            const safeName = name.replace(/'/g, "\\'");
            return `<span class="player-link" onclick="showPlayerModal('${safeName}')">${name}</span>${ovrTxt}`;
        };
        const sendPlayers = offer.offer_players.map(playerPill).join(', ') || '—';
        const sendPicks = offer.offer_picks.map(pid => (state.draft_picks[pid] ? `${pickLabel(state.draft_picks[pid])} (${state.draft_picks[pid].value ?? '—'} val)` : pid)).join(', ');
        const wantPlayers = offer.wants_players.map(playerPill).join(', ') || '—';
        document.getElementById('offer-popup-body').innerHTML = `
            <h5 class="mb-2">📨 Incoming Trade Offer from ${offer.from_team} <small class="text-muted">(${offer.context || ''})</small></h5>
            <p class="mb-1"><b>They send:</b> ${sendPlayers}${sendPicks ? ' + ' + sendPicks : ''} <span class="text-success small">(value ${offer.offer_value ?? '—'})</span></p>
            <p class="mb-3"><b>They want:</b> ${wantPlayers} <span class="text-warning small">(value ${offer.want_value ?? '—'})</span></p>
            <div class="d-flex gap-2 flex-wrap">
                <button class="btn btn-success flex-fill" onclick="respondOfferPopup(true)">✅ Accept</button>
                <button class="btn btn-outline-danger flex-fill" onclick="respondOfferPopup(false)">❌ Decline</button>
                <button class="btn btn-outline-warning flex-fill" onclick="openNegotiateBuilder()">🤝 Negotiate</button>
            </div>
            <div id="offer-popup-negotiate-panel" class="mt-3" style="display:none;"></div>
        `;
    }

    async function respondOfferPopup(accept) {
        await fetch('/api/respond_offer', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({accept})});
        await refreshState();
        if (activeTab === 'trade') renderTradeTab();
    }

    function renderSidebarStatus() {
        const el = document.getElementById('sidebar-status');
        if (!el) return;
        const stageLabels = {
            "regular_season": "🏀 Regular Season", "play_in": "🎟️ Play-In Tournament", "playoffs": "🏆 Playoffs",
            "offseason": "🌴 Offseason", "draft": "🎓 Draft Night", "free_agency": "💰 Free Agency"
        };
        el.innerHTML = `Season ${state.year}<br>${stageLabels[state.stage] || state.stage}`;
    }

    // UPGRADE BATCH 6: sound settings panel wiring

    async function toggleNotificationPanel() {
        const panel = document.getElementById('notif-panel');
        const willShow = panel.style.display === 'none';
        panel.style.display = willShow ? 'block' : 'none';
        if (willShow) {
            const res = await fetch('/api/notifications');
            const data = await res.json();
            panel.innerHTML = data.notifications.length
                ? data.notifications.slice().reverse().map(n => `<div class="small text-white-50 border-bottom border-secondary pb-1 mb-1">${n.text}</div>`).join('')
                : '<div class="small text-white-50">No notifications yet.</div>';
            await fetch('/api/notifications/mark_read', {method: 'POST'});
            document.getElementById('notif-badge').style.display = 'none';
        }
    }
    window.toggleNotificationPanel = toggleNotificationPanel;

    async function refreshNotifBadge() {
        const res = await fetch('/api/notifications');
        const data = await res.json();
        const badge = document.getElementById('notif-badge');
        if (data.unread_count > 0) { badge.style.display = 'inline'; badge.textContent = data.unread_count; }
        else { badge.style.display = 'none'; }
    }
    window.refreshNotifBadge = refreshNotifBadge;

    async function runUndoLastAction() {
        if (!confirm('Undo the most recent roster-changing action? This cannot be redone.')) return;
        const res = await fetch('/api/undo_last_action', {method: 'POST'});
        const data = await res.json();
        if (data.success) showToast(`Undid: ${data.undone}`, 'success');
        else showToast(data.reason || 'Nothing to undo.', 'error');
        await refreshState();
    }
    window.runUndoLastAction = runUndoLastAction;

    function openTutorialModal() {
        fetch('/api/tutorial').then(r => r.json()).then(data => {
            const body = data.steps.map((s, i) => `<h6 class="text-info">${i + 1}. ${s.title}</h6><p class="small text-white-50">${s.text}</p>`).join('');
            document.getElementById('modal-overlay').style.display = 'block';
            document.getElementById('player-modal').style.display = 'block';
            document.getElementById('pm-name').innerText = '❓ How to Play';
            document.getElementById('player-stats-render').innerHTML = `${body}<button class="btn btn-accent w-100 mt-2" onclick="closeModals()">Got it</button>`;
        });
    }
    window.openTutorialModal = openTutorialModal;

    function toggleSoundPanel() {
        const panel = document.getElementById('sound-panel');
        const willShow = panel.style.display === 'none';
        panel.style.display = willShow ? 'block' : 'none';
        if (willShow) {
            document.getElementById('sfx-enabled-check').checked = SoundEngine.isEnabled();
            document.getElementById('sfx-volume-slider').value = SoundEngine.getSfxVolume();
            document.getElementById('ambience-enabled-check').checked = SoundEngine.isAmbienceOn();
            document.getElementById('ambience-volume-slider').value = SoundEngine.getAmbienceVolume();
        }
    }
    function refreshSoundIcon() {
        const btn = document.getElementById('sound-toggle-btn');
        if (btn) btn.textContent = SoundEngine.isEnabled() ? '🔊 Sound' : '🔇 Sound';
    }
    document.addEventListener('DOMContentLoaded', () => {
        refreshSoundIcon();
        if (SoundEngine.isAmbienceOn()) {
            const resumeOnce = () => { SoundEngine.setAmbienceOn(true); document.removeEventListener('click', resumeOnce); };
            document.addEventListener('click', resumeOnce, { once: true });
        }
    });


    // BUGFIX (mobile sidebar close): three independent ways to close the
    // sidebar now stay in sync through these two functions -- the topbar
    // toggle button, the sidebar's own ✕ button, and tapping the backdrop.
    // Toggling both the sidebar's .open class AND body's .sidebar-open
    // class (rather than relying on fragile CSS sibling selectors) keeps
    // the backdrop's visibility correctly in sync with the sidebar no
    // matter which of the three controls triggered the change.
    function openSidebar() {
        const sb = document.getElementById('mlg-sidebar');
        if (sb) sb.classList.add('open');
        document.body.classList.add('sidebar-open');
    }
    window.openSidebar = openSidebar;

    function closeSidebar() {
        const sb = document.getElementById('mlg-sidebar');
        if (sb) sb.classList.remove('open');
        document.body.classList.remove('sidebar-open');
    }
    window.closeSidebar = closeSidebar;

    function toggleSidebar() {
        const sb = document.getElementById('mlg-sidebar');
        if (sb && sb.classList.contains('open')) closeSidebar();
        else openSidebar();
    }
    window.toggleSidebar = toggleSidebar;

    function switchTab(tabId, btnElement) {
        // On mobile, navigating should close the sidebar automatically --
        // this is a no-op on desktop since .open/.sidebar-open only affect
        // layout under the mobile media query anyway.
        closeSidebar();
        if (activeTab === 'livegame' && tabId !== 'livegame' && typeof lgTimer !== 'undefined') {
            clearTimeout(lgTimer);
            lgPlaying = false;
        }
        activeTab = tabId;
        document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
        document.querySelectorAll('.nav-btn, .side-nav-btn').forEach(btn => btn.classList.remove('active'));

        document.getElementById(`tab-${tabId}`).style.display = 'block';
        if (btnElement) btnElement.classList.add('active');
        // Leaving the Team Tracker always resets it back to the conference list
        // next time it's opened, so a stale team detail view doesn't linger.
        if (tabId !== 'teamtracker') showTeamTrackerList(true);
        renderActiveTab(true);
    }

    function switchTMTab(tab) {
        document.querySelectorAll('.tm-panel').forEach(el => el.style.display = (el.id === `tm-panel-${tab}` ? 'block' : 'none'));
        document.querySelectorAll('#tm-mini-tabs .pm-tab-btn').forEach(btn => btn.classList.toggle('active', btn.getAttribute('data-tm') === tab));
        if (tab === 'playbook' && typeof renderPlaybookTab === 'function') renderPlaybookTab();
    }
    window.switchTMTab = switchTMTab;

    // UPGRADE: dedicated Team Playbook tab (Lineup Management) -- surfaces
    // the same 10 Coaching Gameplan sliders the Coaching & Strategy Advanced
    // Tools panel already exposes (and reuses its coachingSetSlider handler
    // directly, so there's exactly one source of truth for saving a
    // change), just in the place a coach actually expects to manage it.
    function cssSafePlaybook(s) { return s.replace(/[^a-zA-Z0-9]/g, '_'); }
    function pbEscape(s) {
        if (s === null || s === undefined) return '';
        return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    async function renderPlaybookTab() {
        const root = document.getElementById('playbook-sliders-root');
        if (!root) return;
        const team = state.user_team;
        let plan;
        try {
            const res = await fetch(`/api/coaching_gameplan?team=${encodeURIComponent(team)}`);
            plan = (await res.json()).gameplan || {};
        } catch (e) {
            root.innerHTML = '<div class="text-danger small">Could not load your playbook -- try again.</div>';
            return;
        }
        const OFFENSE_SLIDER_KEYS = ["Pace", "Crash Glass", "Transition Focus", "Star Usage", "Bench Usage"];
        const DEFENSE_SLIDER_KEYS = ["Defensive Pressure", "Switch Everything", "Double Team", "Zone Frequency", "Help Defense"];
        const SLIDER_HINTS = {
            "Pace": "Faster pace = more possessions for everyone (more shots, boards, assists -- both ways).",
            "Crash Glass": "More offensive rebounding, at some cost to transition defense.",
            "Transition Focus": "Push the ball up the floor more -- more shot volume and quick-hit assists.",
            "Star Usage": "Run more of the offense through your #1 option (see Designated Star in Offense Strategy).",
            "Bench Usage": "Shift real shot volume toward your bench rotation instead of the starters.",
            "Defensive Pressure": "Contest harder everywhere -- costs the opponent efficiency, but draws more fouls both ways.",
            "Switch Everything": "Live-action version of the Switch Everything scheme -- less blown coverage, more mismatches to hunt.",
            "Double Team": "Send extra defenders at the opponent's best scorer -- hurts their efficiency, but risks turnovers of your own if they pass out of it.",
            "Zone Frequency": "Play more zone possessions -- softer at the rim, but scrambled rotations are more foul- and turnover-prone when attacked.",
            "Help Defense": "More bodies collapsing to protect the rim -- tougher interior shots, but leaves shooters open on the weak side.",
        };
        const sliderRow = (k, v) => `
            <div class="odds-bar-wrap" title="${pbEscape(SLIDER_HINTS[k] || '')}">
                <div class="odds-bar-label"><span>${pbEscape(k)}</span><span id="pb-val-${cssSafePlaybook(k)}">${pbEscape(v)}</span></div>
                <input type="range" min="0" max="100" value="${v}" class="form-range"
                    oninput="document.getElementById('pb-val-${cssSafePlaybook(k)}').innerText = this.value;"
                    onchange="playbookSetSlider('${k.replace(/'/g, "\\'")}', this.value)">
                <div class="small text-white-50" style="font-size:0.75em;">${pbEscape(SLIDER_HINTS[k] || '')}</div>
            </div>`;
        if (!Object.keys(plan).length) {
            root.innerHTML = '<span class="text-white-50 small">No playbook set yet -- this fills in automatically once your league is up and running.</span>';
            return;
        }
        root.innerHTML = `
            <div class="subsection-title" style="font-size:0.9em;">🏀 Offense</div>
            ${OFFENSE_SLIDER_KEYS.filter(k => k in plan).map(k => sliderRow(k, plan[k])).join('')}
            <div class="subsection-title mt-3" style="font-size:0.9em;">🛡 Defense</div>
            ${DEFENSE_SLIDER_KEYS.filter(k => k in plan).map(k => sliderRow(k, plan[k])).join('')}
        `;
    }
    window.renderPlaybookTab = renderPlaybookTab;

    async function playbookSetSlider(sliderName, value) {
        const team = state.user_team;
        await fetch('/api/set_coaching_gameplan', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({team, slider: sliderName, value: parseInt(value, 10)})
        });
        if (typeof showToast === 'function') showToast(`${sliderName} updated.`, 'success');
    }
    window.playbookSetSlider = playbookSetSlider;

    // UI OVERHAUL: Front Office used to be 9 full-width cards stacked
    // vertically (GM, staff, business, eras, settings, awards all at once).
    // Same click-through sub-tab pattern as Team Management, so you land on
    // Overview and drill into the section you actually want.
    function switchFOTab(tab) {
        document.querySelectorAll('.fo-panel').forEach(el => el.style.display = (el.id === `fo-panel-${tab}` ? 'block' : 'none'));
        document.querySelectorAll('#fo-mini-tabs .pm-tab-btn').forEach(btn => btn.classList.toggle('active', btn.getAttribute('data-fo') === tab));
    }
    window.switchFOTab = switchFOTab;

    function switchHistTab(tab) {
        document.querySelectorAll('.hist-panel').forEach(el => el.style.display = (el.id === `hist-panel-${tab}` ? 'block' : 'none'));
        document.querySelectorAll('#hist-mini-tabs .pm-tab-btn').forEach(btn => btn.classList.toggle('active', btn.getAttribute('data-hist') === tab));
        // BUGFIX: All-Time Leaders previously only refreshed once, whenever
        // the outer League History tab was first opened -- so if you sim'd
        // more games and came back to check leaders later without leaving
        // the History tab, you'd see stale (or blank, on a fresh league)
        // data forever. Refresh every time this specific sub-tab is opened.
        if (tab === 'leaders' && typeof renderCareerLeaders === 'function') renderCareerLeaders();
    }
    window.switchHistTab = switchHistTab;

    function switchTradeSubTab(tab) {
        document.querySelectorAll('.trade-sub-panel').forEach(el => el.style.display = (el.id === `trade-panel-${tab}` ? 'block' : 'none'));
        document.querySelectorAll('#trade-mini-tabs .pm-tab-btn').forEach(btn => btn.classList.toggle('active', btn.getAttribute('data-trade') === tab));
    }
    window.switchTradeSubTab = switchTradeSubTab;

    // UPGRADE: Keyboard shortcuts for common actions (sim day, next/prev tab,
    // close modal, help). Only the nav bar's own tab ids are in scope here --
    // Save/Load isn't a real tab-content panel so it's excluded from cycling.
    const KEYBOARD_TAB_ORDER = ['roster', 'calendar', 'stats', 'teamtracker', 'trade', 'frontoffice', 'freeagency', 'playoffs', 'history'];

    let simDayBusy = false;
    async function simOneDay() {
        if (simDayBusy || state.season_simulated || state.pending_offer) return;
        simDayBusy = true;
        stopAutoSim();
        try {
            const res = await fetch('/api/sim_day', {method: 'POST'});
            await res.json();
            await refreshState();
        } finally {
            simDayBusy = false;
        }
    }
    window.simOneDay = simOneDay;

    function cycleTab(direction) {
        const idx = KEYBOARD_TAB_ORDER.indexOf(activeTab);
        const nextIdx = ((idx === -1 ? 0 : idx) + direction + KEYBOARD_TAB_ORDER.length) % KEYBOARD_TAB_ORDER.length;
        const nextId = KEYBOARD_TAB_ORDER[nextIdx];
        const btn = document.querySelector(`.nav-btn[onclick*="switchTab('${nextId}'"]`);
        switchTab(nextId, btn);
    }

    function toggleShortcutsHelp() {
        const modal = document.getElementById('shortcuts-modal');
        const isOpen = modal.style.display === 'block';
        closeModals();
        if (!isOpen) {
            document.getElementById('modal-overlay').style.display = 'block';
            modal.style.display = 'block';
        }
    }
    window.toggleShortcutsHelp = toggleShortcutsHelp;

    // UPGRADE: Media / press conference mini-game
    function checkPressConference() {
        const pc = state.pending_press_conference;
        if (!pc || document.getElementById('press-conf-modal').style.display === 'block') return;
        document.getElementById('press-conf-prompt').innerText = pc.prompt;
        const btns = Object.entries(pc.responses || {}).map(([key, r]) =>
            `<button class="btn btn-outline-accent" onclick="submitPressResponse('${key}')">${r.label}<div class="small text-white-50">${r.desc}</div></button>`
        ).join('');
        document.getElementById('press-conf-responses').innerHTML = btns;
        document.getElementById('modal-overlay').style.display = 'block';
        document.getElementById('press-conf-modal').style.display = 'block';
        openModal = { type: 'press_conf' };
    }

    async function submitPressResponse(key) {
        closeModals();
        const res = await fetch('/api/press_conference', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({response_key: key}) });
        const data = await res.json();
        if (data.success) {
            const e = data.effect;
            pushLocalNotification(`Press Conference: ${e.label} — ${e.desc}. Morale ${e.morale >= 0 ? '+' : ''}${e.morale}, Fan Approval ${e.fan >= 0 ? '+' : ''}${e.fan}.`);
        }
        await refreshState();
    }
    window.submitPressResponse = submitPressResponse;

    function pushLocalNotification(msg) {
        const area = document.getElementById('news-ticker');
        if (!area) return;
        const el = document.createElement('div');
        el.className = 'alert alert-info py-1 px-2 mb-1 small';
        el.innerText = msg;
        area.prepend(el);
        setTimeout(() => el.remove(), 8000);
    }

    // UPGRADE: Fan approval widget rendered inside the Team Management tab
    function renderFanApprovalWidget() {
        const el = document.getElementById('fan-approval-widget');
        if (!el) return;
        const fa = (state.fan_approval || {})[state.user_team] ?? 55;
        const rev = (state.attendance_revenue || {})[state.user_team] ?? 0;
        const bar_color = fa >= 70 ? '#22c55e' : fa >= 45 ? '#facc15' : '#ef4444';
        el.innerHTML = `<div class="p-2 bg-dark rounded border border-secondary">
            <div class="d-flex justify-content-between small mb-1">
                <span class="text-white-50">Fan Approval</span>
                <span class="fw-bold" style="color:${bar_color};">${fa}%</span>
            </div>
            <div class="progress mb-2" style="height:8px; background:#1f2937;">
                <div class="progress-bar" style="width:${fa}%; background:${bar_color};"></div>
            </div>
            <div class="small text-white-50">Estimated gate revenue this season: <b class="text-white">$${rev}M</b></div>
        </div>`;
    }

    // UPGRADE: Confetti on clinching a title. Pure canvas animation —
    // no external libraries, tasteful 4-second burst then auto-cleans up.
    function launchConfetti() {
        const canvas = document.getElementById('confetti-canvas');
        if (!canvas) return;
        canvas.style.display = 'block';
        const ctx = canvas.getContext('2d');
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        const COLORS = ['#facc15','#38bdf8','#34d399','#f472b6','#a78bfa','#fb923c'];
        const particles = Array.from({length: 160}, () => ({
            x: Math.random() * canvas.width,
            y: Math.random() * -canvas.height,
            r: 4 + Math.random() * 6,
            d: 1.5 + Math.random() * 3,
            color: COLORS[Math.floor(Math.random() * COLORS.length)],
            tilt: Math.random() * 10 - 5,
            tiltAngle: 0,
            tiltSpeed: 0.07 + Math.random() * 0.05,
        }));
        let frame = 0;
        const MAX_FRAMES = 220;
        function draw() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            particles.forEach(p => {
                p.tiltAngle += p.tiltSpeed;
                p.y += p.d;
                p.tilt = 15 * Math.sin(p.tiltAngle);
                if (p.y > canvas.height) { p.y = -10; p.x = Math.random() * canvas.width; }
                ctx.beginPath();
                ctx.lineWidth = p.r;
                ctx.strokeStyle = p.color;
                ctx.moveTo(p.x + p.tilt + p.r / 2, p.y);
                ctx.lineTo(p.x + p.tilt, p.y + p.tilt + p.r / 2);
                ctx.stroke();
            });
            frame++;
            if (frame < MAX_FRAMES) requestAnimationFrame(draw);
            else { canvas.style.display = 'none'; ctx.clearRect(0, 0, canvas.width, canvas.height); }
        }
        requestAnimationFrame(draw);
    }

    document.addEventListener('keydown', (e) => {
        const tag = (e.target.tagName || '').toUpperCase();
        const isTyping = tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || e.target.isContentEditable;
        if (e.key === 'Escape') { closeModals(); return; }
        if (isTyping) return;
        if (e.key === 'd' || e.key === 'D') { simOneDay(); }
        else if (e.key === 'ArrowRight' || e.key === ']') { cycleTab(1); }
        else if (e.key === 'ArrowLeft' || e.key === '[') { cycleTab(-1); }
        else if (e.key === '?') { toggleShortcutsHelp(); }
    });

    // ── MOBILE SWIPE NAVIGATION ───────────────────────────────────────────────
    // Swipe left/right on the main content area to cycle tabs, same as the
    // arrow-key shortcuts. Threshold of 60px avoids accidental fires on scrolls.
    let _touchStartX = 0, _touchStartY = 0;
    const mainContent = document.getElementById('main-content') || document.body;
    mainContent.addEventListener('touchstart', e => {
        _touchStartX = e.changedTouches[0].screenX;
        _touchStartY = e.changedTouches[0].screenY;
    }, {passive: true});
    mainContent.addEventListener('touchend', e => {
        const dx = e.changedTouches[0].screenX - _touchStartX;
        const dy = e.changedTouches[0].screenY - _touchStartY;
        // Only treat as a horizontal swipe if horizontal movement dominates
        if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) {
            // Don't hijack swipes inside horizontally-scrolling containers
            const target = e.target.closest('.topnav-links, .table-dark-custom, [style*="overflow-x"]');
            if (target) return;
            cycleTab(dx < 0 ? 1 : -1);
        }
    }, {passive: true});

    function renderActiveTab(isTabSwitch) {
        if (!state.teams) return;
        const userTeam = state.user_team;
        const teamData = state.teams[userTeam];
        const capDisplay = document.getElementById('roster-cap-display');
        const capBanner = document.getElementById('roster-cap-banner');
        if (capDisplay && teamData) {
            const userCap = teamData.cap_space;
            const rules = state.league_rules || {};
            const CAP = rules.salary_cap ?? 165;
            const APRON = CAP + (rules.hard_cap_apron ?? 22);
            const spent = CAP - userCap;
            const pctUsed = Math.min(100, Math.max(0, (spent / APRON) * 100));
            const pctCap  = (CAP / APRON) * 100;
            const pctApron = 100;
            const taxBill = teamData.luxury_tax || 0;
            const barColor = spent > APRON ? '#ef4444' : spent > CAP ? '#f97316' : '#10b981';
            capDisplay.innerHTML = `
                <div class="d-flex justify-content-between align-items-end mb-1">
                    <span style="font-size:1.1rem;font-weight:700;">${userCap >= 0 ? '$'+userCap+'M Available' : '$'+Math.abs(userCap)+'M Over Cap'}${taxBill > 0 ? ` <span class="text-warning small">· $${taxBill}M Tax</span>` : ''}</span>
                    <span class="small text-white-50">$${spent}M / $${CAP}M cap · Hard apron $${APRON}M</span>
                </div>
                <div class="position-relative" style="height:14px;background:#1f2937;border-radius:7px;overflow:hidden;">
                    <div style="position:absolute;left:0;top:0;height:100%;width:${pctUsed}%;background:${barColor};border-radius:7px;transition:width 0.4s;"></div>
                    <div style="position:absolute;left:${pctCap}%;top:0;height:100%;width:2px;background:#facc15;" title="Salary cap ($${CAP}M)"></div>
                </div>
                <div class="d-flex justify-content-between mt-1 small text-white-50">
                    <span>$0</span><span style="margin-left:${pctCap}%;">💰 Cap</span><span>Apron</span>
                </div>`;
            capBanner.classList.toggle('negative', userCap < 0);
        }

        if (activeTab === 'dashboard') renderDashboardTab();
        else if (activeTab === 'roster') renderRosterTab(isTabSwitch);
        else if (activeTab === 'calendar') renderCalendarTab();
        else if (activeTab === 'livegame') renderLiveGameTab();
        else if (activeTab === 'stats') renderStatsTab();
        else if (activeTab === 'teamtracker') renderTeamTrackerTab();
        else if (activeTab === 'teamintel') renderTeamIntelTab();
        else if (activeTab === 'trade') renderTradeTab();
        else if (activeTab === 'frontoffice') renderFrontOfficeTab();
        else if (activeTab === 'freeagency') renderFreeAgencyTab();
        else if (activeTab === 'playoffs') renderPlayoffsTab();
        else if (activeTab === 'history') renderHistoryTab();
    }

    function getPlayerByName(name) {
        if (state.players && state.players[name]) return state.players[name];
        if (state.free_agents) {
            const fa = state.free_agents.find(p => p.name === name);
            if (fa) return fa;
        }
        if (state.draft_class) {
            const dp = state.draft_class.find(p => p.name === name);
            if (dp) return dp;
        }
        return null;
    }

    // ===================== ROSTER TAB =====================
    const POSITION_ORDER_JS = {"PG":0, "SG":1, "SF":2, "PF":3, "C":4};

    // 2K-style tiered OVR badge -- color communicates quality at a glance instead
    // of every rating rendering as the same flat, low-contrast grey text.
    function ovrTierClass(rating) {
        if (rating >= 95) return 'ovr-hof';
        if (rating >= 90) return 'ovr-elite';
        if (rating >= 80) return 'ovr-great';
        if (rating >= 70) return 'ovr-good';
        if (rating >= 60) return 'ovr-avg';
        return 'ovr-low';
    }
    function ovrBadgeHtml(rating) {
        return `<span class="ovr-badge ${ovrTierClass(rating)}" title="Overall Rating">${rating} OVR</span>`;
    }

    function playerRowHtml(p, isStarter, slotPos) {
        const injBadge = p.injury ? `<span class="badge-injury ms-2">🩹 ${p.injury.status || ''} · ${p.injury.description} (${p.injury.games_remaining}g)</span>` : (p.reinjury_window > 0 ? `<span class="badge bg-warning text-dark ms-2" style="font-size:0.65rem;" title="Elevated re-injury risk for ${p.reinjury_window} more games">⚠️ Re-injury risk</span>` : '');
        // UPGRADE: Injury-prone tags. The server has tracked this as a real
        // persistent trait for a while (3+ injuries this career = flagged,
        // and it already raises future injury odds) but never actually
        // showed it anywhere -- so it looked like every injury was an
        // independent coin flip. Now it's a visible badge.
        const proneBadge = p.injury_prone ? `<span class="badge bg-danger ms-2" style="font-size:0.65rem;" title="${p.injury_history_count || 0} injuries this career -- elevated long-term injury risk">🩹 Injury Prone</span>` : '';
        const ntcBadge = (p.contract && p.contract.no_trade_clause) ? `<span class="badge bg-warning text-dark ms-2" style="font-size:0.65rem;" title="Contractual no-trade clause -- can't be traded without their approval">📜 No-Trade Clause</span>` : '';
        const fatVal = p.fatigue || 0;
        const energyPct = Math.max(0, Math.min(100, 100 - fatVal));
        const energyColor = fatVal >= 60 ? '#ff5470' : fatVal >= 35 ? '#ffb020' : '#2ee6a6';
        const energyBarHtml = `<div class="energy-bar-track" title="Energy: ${Math.round(energyPct)}%">
            <div class="energy-bar-fill" style="width:${energyPct}%; background:${energyColor};"></div>
        </div>`;
        const fatBadge = fatVal >= 60 ? `<span class="badge-injury ms-2" style="background:#78350f;color:#fed7aa;">🥵 Fatigued ${Math.round(fatVal)}%</span>` : '';
        const form = p.form || 0;
        const formBadge = form >= 0.6
            ? `<span class="ms-2 animate__animated animate__pulse" title="On fire!" style="font-size:1rem;">🔥🔥 <small class="text-warning">HOT</small></span>`
            : form >= 0.35
            ? `<span class="ms-2" title="Heating up" style="font-size:0.9rem;">🔥</span>`
            : form <= -0.6
            ? `<span class="ms-2" title="Ice cold!" style="font-size:1rem;">❄️❄️ <small class="text-info">COLD</small></span>`
            : form <= -0.35
            ? `<span class="ms-2" title="Struggling" style="font-size:0.9rem;">🧊</span>`
            : '';
        const safeName = p.name.replace(/'/g, "\\'");
        // UPGRADE: Flexible starting slots. "Start" used to always insert a
        // player at their own natural position -- now it's a slot picker,
        // since the backend (set_manual_starter) already allows any player
        // in any of the 5 slots. This is what lets a GM run, say, two point
        // guards together (one at PG, one at SG) instead of being locked
        // into exactly one slot per natural position.
        const startBtn = isStarter
            ? `<span class="jersey-badge" style="background:#facc15;color:#1e293b;">⭐ STARTER</span>`
            : `<select class="form-select form-select-sm bg-dark text-white border-secondary d-inline-block" style="width:auto;padding:2px 6px;font-size:0.72rem;" onchange="if(this.value){makeStarter(this.value,'${safeName}'); this.value='';}" title="Insert into the starting lineup at a chosen slot">
                <option value="">🔁 Start at…</option>
                ${['PG','SG','SF','PF','C'].map(pos => `<option value="${pos}">${pos}${pos===p.position ? ' (natural)' : (pos===p.secondary_position ? ' (secondary)' : '')}</option>`).join('')}
            </select>`;
        // UPGRADE: Two-way contract conversion flow.
        const twoWayBadge = p.two_way ? `<span class="badge bg-info ms-2" style="font-size:0.65rem;">TWO-WAY</span>` : '';
        const convertBtn = p.two_way
            ? `<button class="btn btn-outline-accent" style="padding:2px 10px;font-size:0.72rem;" onclick="convertTwoWay('${safeName}')" title="Convert to a standard NBA contract">📈 Convert</button>`
            : '';
        // UPGRADE: "Untradeable" flag -- a GM-settable lock on franchise
        // cornerstones so a trade builder click can't accidentally send
        // them away. Server-side enforced too (see validate_trade_legality).
        const isLocked = ((state.untradeable || {})[state.user_team] || []).includes(p.name);
        const lockBadge = isLocked ? `<span class="badge bg-warning text-dark ms-2" style="font-size:0.65rem;" title="Locked from trades">🔒 UNTRADEABLE</span>` : '';
        const lockBtn = `<button class="btn btn-outline-accent" style="padding:2px 10px;font-size:0.72rem;" onclick="toggleUntradeable('${safeName}')" title="${isLocked ? 'Allow this player to be traded again' : 'Lock this player from ever being traded'}">${isLocked ? '🔓' : '🔒'}</button>`;
        // UPGRADE: Trade block -- mark a player available so AI teams call
        // proactively about them (see toggle_trade_block + the boosted
        // daily call chance server-side).
        const onBlock = (state.trade_block || []).includes(p.name);
        const blockBadge = onBlock ? `<span class="badge bg-info ms-2" style="font-size:0.65rem;" title="On the trade block">📢 ON BLOCK</span>` : '';
        const blockBtn = isLocked ? '' : `<button class="btn btn-outline-accent" style="padding:2px 10px;font-size:0.72rem;" onclick="toggleTradeBlock('${safeName}')" title="${onBlock ? 'Take off the trade block' : 'Mark available on the trade block'}">${onBlock ? '📢✓' : '📢'}</button>`;
        const rowId = `prow-${p.name.replace(/[^a-zA-Z0-9]/g, '_')}`;
        return `
            <div class="roster-row-card ${isStarter ? 'starter' : ''}" style="padding:8px 10px;">
                <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
                    <span class="d-flex align-items-center gap-2">
                        <span style="width:30px;height:30px;flex-shrink:0;">${playerSilhouetteSvg(p.name, p.position, teamColor(state.user_team), 30)}</span>
                        ${isStarter
                            ? `<select class="pos-slot-select" style="background:#1e293b;color:#facc15;border:1px solid #facc15;border-radius:4px;font-size:0.72rem;font-weight:700;padding:1px 4px;" onchange="makeStarter(this.value, '${safeName}')" title="Move this starter to a different slot">
                                ${['PG','SG','SF','PF','C'].map(pos => `<option value="${pos}" ${pos===(slotPos||p.position) ? 'selected' : ''}>${pos}</option>`).join('')}
                              </select>`
                            : `<span class="pos-slot-tag">${p.position}${p.secondary_position ? '/' + p.secondary_position : ''}</span>`}
                        <a class="player-link" onclick="showPlayerModal('${p.name}')">${p.name}</a>
                        <span class="text-warning fw-bold small" id="val-${p.name.replace(/ /g, '_')}" style="min-width:44px;display:inline-block;">${p.minutes} Min</span>
                        <input type="range" class="form-range slider-minutes-input" style="width:125px;height:20px;" min="0" max="48" value="${p.minutes}" data-player="${p.name}" oninput="onMinutesSliderInput(this)" title="Minutes per game">
                        <span class="d-flex align-items-center gap-1" style="min-width:70px;">${energyBarHtml}</span>
                        ${ovrBadgeHtml(p.rating)}${injBadge}${proneBadge}${fatBadge}${formBadge}${twoWayBadge}${lockBadge}${blockBadge}
                    </span>
                    <span class="d-flex align-items-center gap-2">
                        <span class="hub-menu-chevron" style="cursor:pointer;" onclick="document.getElementById('${rowId}').style.display = document.getElementById('${rowId}').style.display === 'none' ? 'block' : 'none';" title="More actions">⋯</span>
                    </span>
                </div>
                <div id="${rowId}" style="display:none;" class="mt-2 pt-2 border-top border-secondary">
                    <div class="d-flex align-items-center flex-wrap gap-2 mb-2">
                        <span class="small text-white-50">Age ${p.age}</span>
                        ${startBtn}${convertBtn}${lockBtn}${blockBtn}
                        <button class="btn btn-danger-custom" style="padding:2px 10px;font-size:0.72rem;" onclick="waivePlayer('${safeName}')" title="Release this player to free agency">✂ Waive</button>
                    </div>
                </div>
            </div>
        `;
    }

    async function toggleUntradeable(name) {
        const res = await fetch('/api/toggle_untradeable', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({player_name: name})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        renderRosterTab(true);
        renderTradeAssetGrid();
    }
    window.toggleUntradeable = toggleUntradeable;

    async function toggleTradeBlock(name) {
        const res = await fetch('/api/toggle_trade_block', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({player_name: name})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        renderRosterTab(true);
        renderTradeAssetGrid();
    }
    window.toggleTradeBlock = toggleTradeBlock;

    async function convertTwoWay(name) {
        const res = await fetch('/api/convert_two_way', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        renderRosterTab(true);
    }
    window.convertTwoWay = convertTwoWay;

    function totalAllocatedMinutes() {
        let total = 0;
        document.querySelectorAll('.slider-minutes-input').forEach(input => { total += parseInt(input.value, 10) || 0; });
        return total;
    }

    // UPGRADE: G-League two-way simulation panel. Shows each two-way player's
    // running G-League stats (updated every simulated day by g_league_tick on
    // the server), their banked development XP toward a rating bump, and a
    // "Call Up" button that promotes them to the 15-man roster (converting
    // their contract to a standard deal, same path as the existing Convert
    // button, but labelled and surfaced more prominently so it reads as the
    // GM making an active front-office decision rather than an admin chore).
    async function renderGLeaguePanel() {
        const el = document.getElementById('g-league-panel');
        if (!el) return;
        const twoWays = Object.values(state.players).filter(p => p.team === state.user_team && p.two_way);
        if (!twoWays.length) { el.innerHTML = ''; return; }

        const res = await fetch('/api/g_league_stats');
        const data = await res.json();
        const stats = {};
        (data.players || []).forEach(p => { stats[p.name] = p; });

        let html = `<div class="p-2 bg-dark rounded border border-info">
            <h6 class="text-info mb-2">🏀 G-League Affiliates</h6>
            <div class="row g-2">`;
        twoWays.forEach(p => {
            const gl = stats[p.name] || {};
            const xp = gl.xp_banked || 0;
            const xpPct = Math.min(100, (xp / 5) * 100).toFixed(0);
            const safeName = p.name.replace(/'/g, "\\'");
            html += `<div class="col-md-6">
                <div class="p-2 bg-dark border border-secondary rounded">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <a class="player-link" onclick="showPlayerModal('${safeName}')">${p.name}</a>
                        <button class="btn btn-outline-accent btn-sm" onclick="callUp('${safeName}')">⬆ Call Up</button>
                    </div>
                    <div class="small text-white-50">${p.position} · ${p.rating} OVR · G-League: ${gl.GP || 0} GP · ${gl.PPG || 0} PPG / ${gl.RPG || 0} RPG / ${gl.APG || 0} APG</div>
                    <div class="small text-white-50 mt-1">Dev XP: ${xp}/5 — next rating tick at 5</div>
                    <div class="progress mt-1" style="height:5px; background:#1f2937;">
                        <div class="progress-bar bg-info" style="width:${xpPct}%;"></div>
                    </div>
                </div>
            </div>`;
        });
        html += `</div></div>`;
        el.innerHTML = html;
    }

    async function callUp(name) {
        if (!confirm(`Call up ${name} to the 15-man roster? This converts their two-way contract to a standard deal.`)) return;
        const res = await fetch('/api/call_up', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason || 'Call-up failed.', 'error'); return; }
        await refreshState();
        renderRosterTab(true);
    }
    window.callUp = callUp;
    // UPGRADE: Roster balance indicator. Directly answers "why do I have 4
    // can actually cover each of the 5 slots (primary position, plus
    // secondary-position eligibility), and flags anything dangerously thin
    // or needlessly stacked so it's visible before it bites you in a
    // playoff injury.
    function renderRosterBalancePanel(allRoster) {
        const el = document.getElementById('roster-balance-panel');
        if (!el) return;
        const counts = {PG:0, SG:0, SF:0, PF:0, C:0};
        const primaryOnly = {PG:0, SG:0, SF:0, PF:0, C:0};
        allRoster.forEach(p => {
            if (counts.hasOwnProperty(p.position)) { counts[p.position]++; primaryOnly[p.position]++; }
            if (p.secondary_position && counts.hasOwnProperty(p.secondary_position)) counts[p.secondary_position]++;
        });
        const chips = ['PG','SG','SF','PF','C'].map(pos => {
            const c = counts[pos];
            const cls = c <= 1 ? 'bg-danger' : c >= 5 ? 'bg-warning text-dark' : 'bg-secondary';
            const label = c <= 1 ? ' ⚠ thin' : c >= 5 ? ' stacked' : '';
            return `<span class="badge ${cls} me-2 mb-1" title="${primaryOnly[pos]} natural + ${c - primaryOnly[pos]} secondary-eligible">${pos}: ${c}${label}</span>`;
        }).join('');
        el.innerHTML = `<div class="p-2 bg-dark rounded border border-secondary">
            <div class="small text-white-50 mb-1">Roster Balance (natural + secondary-eligible per slot)</div>
            ${chips}
        </div>`;
    }

    function refreshMinutesTotalBanner() {
        const disp = document.getElementById('minutes-total-display');
        if (!disp) return;
        const total = totalAllocatedMinutes();
        disp.innerText = `${total} / 240`;
        disp.className = 'font-monospace fw-bold ' + (total > 240 ? 'text-danger' : total === 240 ? 'text-success' : 'text-warning');

        const byPos = {PG:0, SG:0, SF:0, PF:0, C:0};
        document.querySelectorAll('.slider-minutes-input').forEach(input => {
            const p = state.players[input.getAttribute('data-player')];
            if (p && byPos.hasOwnProperty(p.position)) byPos[p.position] += parseInt(input.value, 10) || 0;
        });
        const posEl = document.getElementById('minutes-by-position');
        if (posEl) {
            posEl.innerHTML = Object.entries(byPos).map(([pos, mins]) =>
                `<span class="${mins > 48 ? 'text-danger' : mins === 48 ? 'text-success' : 'text-white-50'}">${pos}: ${mins}/48</span>`
            ).join('');
        }
    }

    function onMinutesSliderInput(el) {
        // UPGRADE: enforce a real 240-team-minutes-per-game budget (5 positions x 48
        // min, same constraint a real NBA rotation is built under) -- you can't just
        // stack everyone's minutes up; giving one guy more means taking it from
        // someone else. If a slider push would blow the budget, clamp it back to
        // exactly what's left instead of silently letting the team run over.
        const total = totalAllocatedMinutes();
        if (total > 240) {
            const overBy = total - 240;
            el.value = Math.max(0, parseInt(el.value, 10) - overBy);
        }
        const label = document.getElementById(`val-${el.getAttribute('data-player').replace(/ /g, '_')}`);
        if (label) label.innerText = el.value + ' Min';
        refreshMinutesTotalBanner();
    }
    window.onMinutesSliderInput = onMinutesSliderInput;

    async function makeStarter(position, name) {
        await fetch('/api/set_starter', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({position, name})});
        await refreshState();
        renderRosterTab(true);
    }
    window.makeStarter = makeStarter;

    function renderRosterTab(forceRebuild) {
        renderFanApprovalWidget();
        checkPressConference();
        renderGLeaguePanel();
        const container = document.getElementById('minutes-sliders-container');
        if (!container) return;
        const allRoster = Object.values(state.players).filter(p => p.team === state.user_team && !p.retired);
        const starters = (state.teams[state.user_team] && state.teams[state.user_team].starters) || {};
        const starterNames = new Set(Object.values(starters));

        // 2K-style depth chart: Starting Five in true lineup-slot order
        // (PG -> SG -> SF -> PF -> C), then the bench grouped by position.
        const startingFive = ['PG','SG','SF','PF','C'].map(pos => {
            const nm = starters[pos];
            return nm ? {pos, player: allRoster.find(p => p.name === nm)} : {pos, player: null};
        }).filter(row => row.player);
        const bench = allRoster.filter(p => !starterNames.has(p.name))
            .sort((a,b) => b.minutes - a.minutes || b.rating - a.rating);

        const roster = [...startingFive.map(r => r.player), ...bench];
        const rosterKey = roster.map(p => p.name + p.minutes).join('|') + '|' + JSON.stringify(starters);
        const overLimit = allRoster.length > 15;
        const limitBanner = document.getElementById('roster-limit-banner');
        if (limitBanner) {
            limitBanner.style.display = overLimit ? 'block' : 'none';
            if (overLimit) {
                limitBanner.innerHTML = `<div class="alert alert-danger mb-3">⚠ Your roster has <b>${allRoster.length}</b> players — the league limit is <b>15</b>. Waive ${allRoster.length - 15} player(s) below before the regular season can start.</div>`;
            }
        }
        renderRosterBalancePanel(allRoster);
        if (forceRebuild || container.dataset.rosterKey !== rosterKey) {
            let html = `<div class="text-uppercase small text-white-50 fw-bold mb-2" style="letter-spacing:1px;">⭐ Starting Five</div>`;
            startingFive.forEach(row => { html += playerRowHtml(row.player, true, row.pos); });
            if (!startingFive.length) html += `<div class="text-white-50 small mb-3">No starters set yet — click 🤖 Auto-Build Lineup below.</div>`;
            html += `<div class="text-uppercase small text-white-50 fw-bold mt-4 mb-2" style="letter-spacing:1px;">🪑 Bench (by position)</div>`;
            bench.forEach(p => { html += playerRowHtml(p, false, null); });
            container.innerHTML = html;
            container.dataset.rosterKey = rosterKey;
            refreshMinutesTotalBanner();
        }

        const snap = document.getElementById('team-snapshot');
        if (snap) {
            const t = state.teams[state.user_team];
            const picks = Object.values(state.draft_picks || {}).filter(pk => pk.current_team === state.user_team);
            const totalPickValue = picks.reduce((sum, pk) => sum + (pk.value || 0), 0);

            // Client-side derived team rating: minutes-weighted Defensive Rebound attribute
            let dRebWeighted = 0, minWeightTotal = 0;
            roster.forEach(p => {
                const dreb = p.attributes ? p.attributes['Defensive Rebound'] : null;
                if (dreb == null) return;
                dRebWeighted += dreb * Math.max(1, p.minutes);
                minWeightTotal += Math.max(1, p.minutes);
            });
            const dRebRating = minWeightTotal > 0 ? (dRebWeighted / minWeightTotal).toFixed(1) : '—';

            snap.innerHTML = `
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Conference</span><span>${t.conference}</span></div>
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Record</span><span>${t.wins}-${t.losses}</span></div>
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Streak</span><span class="${(t.streak||0) > 0 ? 'text-success' : (t.streak||0) < 0 ? 'text-danger' : 'text-white-50'}">${(t.streak||0) > 0 ? 'W' + t.streak : (t.streak||0) < 0 ? 'L' + Math.abs(t.streak) : '—'}</span></div>
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Roster Size</span><span>${roster.length} / 15</span></div>
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Offense</span><span>${t.offensive_priority}</span></div>
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Defense</span><span>${t.defensive_priority}</span></div>
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Pace</span><span>${t.pace}</span></div>
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Shooting Willingness</span><span>${t.shooting_willingness}</span></div>
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Rebounding</span><span>${t.rebounding_style}</span></div>
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Scoring Options</span><span>${t.scoring_option || 'Balanced Attack'}</span></div>
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Def. Rebounding Rating</span><span class="text-info">${dRebRating}</span></div>
                <div class="d-flex justify-content-between mb-2"><span class="text-white-50">Owned Picks Total Value</span><span class="text-success">${totalPickValue.toFixed(1)}</span></div>
                <div class="text-white-50 mt-3 mb-1">Owned Draft Picks (${picks.length})</div>
                <div>${picks.map(pk => `<span class="pick-tag">${pk.year} R${pk.round}${pk.original_team!==state.user_team ? ' (via '+pk.original_team.split(' ').pop()+')' : ''} <b class="text-success">· ${pk.value ?? '—'} val</b>${pk.protection && pk.protection !== 'None' ? ' <span class=\"text-warning\">🛡'+pk.protection+'</span>' : ''}</span>`).join('') || '<span class="text-muted small">None</span>'}</div>
            `;
            if (forceRebuild) {
                document.getElementById('strat-offense').value = t.offensive_priority;
                document.getElementById('strat-defense').value = t.defensive_priority;
                document.getElementById('strat-pace').value = t.pace;
                document.getElementById('strat-shooting').value = t.shooting_willingness;
                document.getElementById('strat-rebounding').value = t.rebounding_style;
                document.getElementById('strat-scoring').value = t.scoring_option || 'Balanced Attack';
                // UPGRADE: populate the Designated Star picker with the
                // user's own roster (sorted best-to-worst so the likely
                // pick is near the top), then restore whichever player is
                // currently saved as the star -- or leave it on Auto.
                const starSel = document.getElementById('strat-designated-star');
                if (starSel) {
                    const roster = Object.values(state.players || {}).filter(p => p.team === state.user_team && !p.retired).sort((a, b) => b.rating - a.rating);
                    starSel.innerHTML = '<option value="">Auto (highest-rated player)</option>' +
                        roster.map(p => `<option value="${p.name.replace(/"/g, '&quot;')}">${p.name} (${p.rating} OVR, ${p.position})</option>`).join('');
                    starSel.value = t.designated_star || '';
                }
                if (typeof initStrategyDials === 'function') initStrategyDials();
                if (typeof syncStrategyDials === 'function') syncStrategyDials();
            }
        }
    }

    async function waivePlayer(name) {
        if (!confirm(`Waive ${name}? He will be released to free agency and can be re-signed by any team, including yours.`)) return;
        const res = await fetch('/api/waive_player', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name})
        });
        const data = await res.json();
        if (!data.success) { showToast(data.reason || 'Could not waive that player.', 'error'); return; }
        await refreshState();
        renderRosterTab(true);
    }
    window.waivePlayer = waivePlayer;

    async function saveRotation() {
        const minsData = {};
        document.querySelectorAll('.slider-minutes-input').forEach(input => {
            minsData[input.getAttribute('data-player')] = input.value;
        });
        const res = await fetch('/api/update_rotation', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                minutes: minsData,
                offensive_priority: document.getElementById('strat-offense').value,
                defensive_priority: document.getElementById('strat-defense').value,
                pace: document.getElementById('strat-pace').value,
                shooting_willingness: document.getElementById('strat-shooting').value,
                rebounding_style: document.getElementById('strat-rebounding').value,
                scoring_option: document.getElementById('strat-scoring').value,
                designated_star: document.getElementById('strat-designated-star') ? document.getElementById('strat-designated-star').value : ''
            })
        });
        const data = await res.json();
        if (data.status === 'error') { showToast(data.reason, 'error'); return; }
        refreshState();
    }

    async function autoSetRotation() {
        const benchDepth = document.getElementById('bench-depth-select').value;
        // UPGRADE PASS: rotation size used to be locked to whatever the
        // chosen philosophy's fixed 8/10/12-man array happened to be --
        // this reads the new rotation-size input (any player count you
        // actually want in the rotation) if the user set one, and falls
        // back to that philosophy's sensible default otherwise.
        const sizeInput = document.getElementById('rotation-size-input');
        const rotationSize = sizeInput && sizeInput.value ? parseInt(sizeInput.value, 10) : null;
        await fetch('/api/auto_set_rotation', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({bench_depth: benchDepth, rotation_size: rotationSize})
        });
        await refreshState();
        renderRosterTab();
    }

    // ===================== STATS TAB (League Leaders) =====================
    function filterByTeam(teamName) {
        activeTeamFilter = teamName || null;
        renderStatsTab();
    }

    // UPGRADE: Attribute-based player finder. Answers "who's actually good
    // at X" -- filter the whole league by position and/or team, ranked by
    // any single attribute, instead of opening 400 player cards by hand.
    // UI OVERHAUL: 2K's stat leaders screen leads with a compact strip of
    // category leaders before the full sortable table -- gives an
    // at-a-glance answer to "who's leading the league in X" without
    // scrolling/sorting a giant table first.
    function renderStatLeaderStrip() {
        const el = document.getElementById('stat-leaders-strip');
        if (!el) return;
        const pool = Object.values(state.players).filter(p => !p.retired && p.stats && p.stats.GP > 0);
        if (!pool.length) { el.innerHTML = ''; return; }
        const cats = [
            {key: 'PPG', label: 'PTS', icon: '🏀', calc: p => p.stats.PTS / p.stats.GP},
            {key: 'RPG', label: 'REB', icon: '🧲', calc: p => p.stats.REB / p.stats.GP},
            {key: 'APG', label: 'AST', icon: '🎯', calc: p => p.stats.AST / p.stats.GP},
            {key: 'SPG', label: 'STL', icon: '🖐', calc: p => p.stats.STL / p.stats.GP},
            {key: 'BPG', label: 'BLK', icon: '🚫', calc: p => p.stats.BLK / p.stats.GP},
        ];
        el.className = 'lb-strip';
        el.innerHTML = cats.map(c => {
            const leader = pool.reduce((best, p) => c.calc(p) > c.calc(best) ? p : best, pool[0]);
            const safeName = leader.name.replace(/'/g, "\\'");
            return `<div class="lb-leader-card">
                <div class="lb-leader-label">${c.icon} ${c.label}/G Leader</div>
                <a class="player-link lb-leader-name d-block" onclick="showPlayerModal('${safeName}')">${leader.name}</a>
                <div class="lb-leader-team">${leader.team || 'FA'}</div>
                <div class="lb-leader-value">${c.calc(leader).toFixed(1)}</div>
            </div>`;
        }).join('');
    }

    function renderStatsTab() {
        renderMvpLadder();
        renderStatLeaderStrip();
        const awardsBanner = document.getElementById('awards-banner');
        if (state.season_simulated && state.awards) {
            awardsBanner.style.display = 'block';
            let html = '';
            const entries = [
                ['MVP', 'Most Valuable Player'], ['DPOY', 'Defensive Player of the Year'],
                ['Scoring_Champ', 'Scoring Champion'], ['ROY', 'Rookie of the Year'], ['MIP', 'Most Improved Player'],
                ['Sixth_Man', 'Sixth Man of the Year']
            ];
            entries.forEach(([key, label]) => {
                const a = state.awards[key];
                if (!a) return;
                html += `<div class="col-md-4 text-center border-end border-secondary mb-3">
                    <div class="text-white-50">${label}</div>
                    <h4 class="text-white mt-1"><a class="player-link" onclick="showPlayerModal('${a.name}')">${a.name}</a></h4>
                    <small class="text-info">${a.stat} — ${a.team}</small>
                </div>`;
            });
            document.getElementById('awards-content').innerHTML = html;
        } else {
            awardsBanner.style.display = 'none';
        }

        const filterSel = document.getElementById('stats-team-filter');
        if (filterSel && filterSel.options.length <= 1) {
            let opts = '<option value="">All Teams</option>';
            Object.keys(state.teams).sort().forEach(t => { opts += `<option value="${t}">${t}</option>`; });
            filterSel.innerHTML = opts;
        }
        if (filterSel && filterSel.value !== (activeTeamFilter || '')) filterSel.value = activeTeamFilter || '';

        const pBody = document.querySelector('#season-player-stats-table tbody');
        pBody.innerHTML = '';

        let all_players = Object.values(state.players).filter(p => p.stats.GP > 0 && !p.retired);
        if (activeTeamFilter) all_players = all_players.filter(p => p.team === activeTeamFilter);

        // Precompute every sortable derived stat once per player so sorting
        // doesn't recompute per-comparison, and so header clicks are cheap.
        const rows = all_players.map(p => {
            const s = p.stats;
            return {
                p,
                NAME: p.name,
                TEAM: p.team || '',
                GP: s.GP,
                MPG: s.MIN != null ? (s.MIN / s.GP) : 0,
                PPG: s.PTS / s.GP,
                RPG: s.REB / s.GP,
                APG: s.AST / s.GP,
                SPG: s.STL / s.GP,
                BPG: s.BLK / s.GP,
                FGPCT: s.FGA > 0 ? (s.FGM / s.FGA) * 100 : 0,
                TPPCT: s['3PA'] > 0 ? (s['3PM'] / s['3PA']) * 100 : 0,
            };
        });

        rows.sort((a, b) => {
            const av = a[statsSortKey], bv = b[statsSortKey];
            if (typeof av === 'string') return statsSortDir * av.localeCompare(bv);
            return statsSortDir * (av - bv);
        });

        // Update the sort-direction arrow on whichever header is active.
        ['NAME','TEAM','GP','MPG','PPG','RPG','APG','SPG','BPG','FGPCT','TPPCT'].forEach(k => {
            const el = document.getElementById(`sort-arrow-${k}`);
            if (el) el.innerText = (k === statsSortKey) ? (statsSortDir === -1 ? ' ▼' : ' ▲') : '';
        });

        rows.forEach(r => {
            const p = r.p;
            pBody.innerHTML += `<tr>
                <td><a class="player-link" onclick="showPlayerModal('${p.name}')">${p.name}</a> <small class="text-muted">(${p.position})</small></td>
                <td>${p.team}</td>
                <td>${r.GP}</td>
                <td>${r.MPG.toFixed(1)}</td>
                <td class="text-warning">${r.PPG.toFixed(1)}</td>
                <td>${r.RPG.toFixed(1)}</td>
                <td>${r.APG.toFixed(1)}</td>
                <td>${r.SPG.toFixed(1)}</td>
                <td>${r.BPG.toFixed(1)}</td>
                <td class="text-info">${r.FGPCT.toFixed(1)}%</td>
                <td class="text-info">${r.TPPCT.toFixed(1)}%</td>
                <td>${badgeChipsHtml(p, 3)}</td>
            </tr>`;
        });
    }

    function setStatsSort(key) {
        if (statsSortKey === key) {
            statsSortDir *= -1; // clicked the same column again -> flip direction
        } else {
            statsSortKey = key;
            // Default to descending for numeric stat columns (biggest first
            // is almost always what you want), ascending for name/team.
            statsSortDir = (key === 'NAME' || key === 'TEAM') ? 1 : -1;
        }
        renderStatsTab();
    }

    function teamColorHue(name) {
        let hash = 0;
        for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
        return Math.abs(hash) % 360;
    }
    function teamColor(name) {
        const custom = state.team_colors && state.team_colors[name] && state.team_colors[name].primary;
        if (custom) return custom;
        return `hsl(${teamColorHue(name)}, 65%, 45%)`;
    }
    function teamInitials(name) {
        return name.split(' ').filter(w => w[0] === w[0].toUpperCase()).map(w => w[0]).join('').slice(0, 3) || name.slice(0,2).toUpperCase();
    }
    function teamLogoHtml(name, size) {
        size = size || 22;
        return `<span class="team-logo-mini" style="width:${size}px;height:${size}px;background:${teamColor(name)};font-size:${size*0.42}px;">${teamInitials(name)}</span>`;
    }

    // ===================== CALENDAR TAB =====================
    const AUTOSIM_SPEEDS = [0.5, 1, 2, 3, 5, 8]; // days simulated per second, indexed by slider value 1-6

    let autoSimTimer = null;
    let autoSimBusy = false;

    function updateAutoSimSpeedLabel() {
        const v = parseInt(document.getElementById('autosim-speed').value, 10);
        const dps = AUTOSIM_SPEEDS[v - 1];
        document.getElementById('autosim-speed-label').innerText = `${dps} days/sec`;
        if (autoSimTimer) { stopAutoSim(true); toggleAutoSim(); } // live-restart at new speed
    }

    function toggleAutoSim() {
        if (autoSimTimer) { stopAutoSim(); return; }
        if (state.season_simulated) return;
        const v = parseInt(document.getElementById('autosim-speed').value, 10);
        const dps = AUTOSIM_SPEEDS[v - 1];
        const intervalMs = Math.max(60, Math.round(1000 / dps));
        const btn = document.getElementById('btn-autosim-toggle');
        btn.innerText = '⏸ Pause';
        btn.classList.remove('btn-accent'); btn.classList.add('btn-warning');
        autoSimTimer = setInterval(async () => {
            if (autoSimBusy) return;
            if (state.season_simulated || state.pending_offer) { stopAutoSim(); return; }
            autoSimBusy = true;
            const res = await fetch('/api/sim_day', {method: 'POST'});
            const data = await res.json();
            await refreshState();
            autoSimBusy = false;
            if (data.paused_for_offer || state.season_simulated) stopAutoSim();
        }, intervalMs);
    }

    function stopAutoSim(keepQuiet) {
        if (autoSimTimer) { clearInterval(autoSimTimer); autoSimTimer = null; }
        if (!keepQuiet) {
            const btn = document.getElementById('btn-autosim-toggle');
            if (btn) {
                btn.innerText = '▶ Auto-Sim';
                btn.classList.remove('btn-warning'); btn.classList.add('btn-accent');
            }
        }
    }

    let simToDayBusy = false;
    async function simToDay(day) {
        stopAutoSim();
        if (simToDayBusy) return;
        simToDayBusy = true;
        const v = parseInt(document.getElementById('autosim-speed')?.value || '4', 10);
        const dps = AUTOSIM_SPEEDS[v - 1] || 3;
        const intervalMs = Math.max(40, Math.round(1000 / dps));
        try {
            // Step forward one real day at a time so the UI (calendar, standings,
            // ticker, box scores) visibly updates in real time instead of the whole
            // multi-day jump happening silently on the server and only appearing
            // once it's all done.
            while (state.current_day <= day && !state.season_simulated) {
                if (state.pending_offer) break;  // let the user resolve the trade offer first
                const res = await fetch('/api/sim_day', {method: 'POST'});
                const data = await res.json();
                await refreshState();
                if (data.paused_for_offer || state.season_simulated) break;
                await new Promise(r => setTimeout(r, intervalMs));
            }
        } finally {
            simToDayBusy = false;
        }
    }

    async function simEntireSeason() {
        stopAutoSim();
        await simToDay(state.schedule_days_total || 82);
    }

    // 2K MyLeague-style "click the calendar icon on a game" popup: Jump In Game
    // (only unlocks once it's actually your next scheduled game -- that's the
    // only day the live viewer has matchup data for), Sim to This Date, or Sim
    // the whole Regular Season from here.
    function openGameOptionsModal(dayNum, homeTeam, awayTeam, isToday) {
        document.getElementById('boxscore-modal').style.display = 'none';
        document.getElementById('player-modal').style.display = 'none';
        document.getElementById('series-modal').style.display = 'none';
        const userTeam = state.user_team;
        const opp = homeTeam === userTeam ? awayTeam : homeTeam;
        const isHome = homeTeam === userTeam;
        const safeHome = homeTeam.replace(/'/g, "\\'");
        const safeAway = awayTeam.replace(/'/g, "\\'");
        const body = document.getElementById('game-options-body');
        // UPGRADE: "Jump In Game" on a future date used to just be disabled
        // with a "sim forward yourself first" note. Real 2K MyLEAGUE lets you
        // click a future game and it sims everything up to that point for
        // you, then drops you straight into it -- so this now does the same:
        // sim day-by-day (still visibly, same as Sim to This Date) up to but
        // NOT including the target day, then jump straight into the live
        // viewer once it's the current matchup.
        const jumpLabel = isToday ? '🎮 Jump In Game' : `🎮 Sim to Day ${dayNum} &amp; Jump In`;
        body.innerHTML = `
            <div class="player-meta mb-3">Day ${dayNum} — ${isHome ? 'vs' : '@'} ${teamLogoHtml(opp)} <b class="text-white">${opp}</b></div>
            <div class="d-flex flex-column gap-2">
                <button class="btn btn-accent w-100 text-start"
                        onclick="closeModals(); jumpIntoGame(${dayNum}, '${safeHome}', '${safeAway}', ${isToday ? 'true' : 'false'});">
                    ${jumpLabel}
                </button>
                <button class="btn btn-outline-accent w-100 text-start" onclick="closeModals(); simToDay(${dayNum});">⏩ Sim to This Date</button>
                <button class="btn btn-outline-info w-100 text-start" onclick="closeModals(); simEntireSeason();">⏭ Sim Regular Season</button>
            </div>
            ${isToday ? '' : '<div class="player-meta mt-3" style="font-size:0.72rem;">This will sim every game between now and this one, then drop you straight into it.</div>'}
        `;
        document.getElementById('modal-overlay').style.display = 'block';
        document.getElementById('game-options-modal').style.display = 'block';
    }
    window.openGameOptionsModal = openGameOptionsModal;

    // Sim up to (but not including) the target day so that day's game is
    // still live/unplayed, then jump straight into the live viewer -- shared
    // by the "Jump In Game" button above for both today's game (isToday,
    // no simming needed) and a future one.
    async function jumpIntoGame(dayNum, homeTeam, awayTeam, isToday) {
        if (!isToday) {
            await simToDay(dayNum - 1);
            // The matchup on `dayNum` might have shifted teams if a trade or
            // schedule quirk occurred while simming forward -- re-check the
            // actual scheduled game for that day before jumping in rather
            // than trusting the stale homeTeam/awayTeam captured when the
            // modal was first opened.
            const day = state.schedule && state.schedule[dayNum];
            const stillScheduled = Array.isArray(day) && day.some(g =>
                (g.home === homeTeam && g.away === awayTeam) || (g.home === awayTeam && g.away === homeTeam));
            if (!stillScheduled) {
                showToast("That matchup changed while simming forward -- check the calendar for what's next.", 'error');
                return;
            }
        }
        switchTab('livegame', document.querySelector('.nav-btn[onclick*=livegame]'));
        watchLiveGame(homeTeam, awayTeam);
    }
    window.jumpIntoGame = jumpIntoGame;

    function renderCalendarTab() {
        const tracker = document.getElementById('schedule-day-tracker');
        const totalDays = state.schedule_days_total || 82;
        if (tracker) tracker.innerText = `Schedule Matrix Progress: Day ${state.current_day <= totalDays ? state.current_day : totalDays} / ${totalDays}`;

        const alertBlock = document.getElementById('playoff-ready-alert');
        const controls = document.getElementById('autosim-controls');
        if (state.season_simulated) {
            if (controls) controls.style.display = 'none';
            if (alertBlock) alertBlock.style.display = 'block';
            stopAutoSim();
        } else {
            if (controls) controls.style.display = 'flex';
            if (alertBlock) alertBlock.style.display = 'none';
        }
        renderCalendar();
        renderNewsFeed();
        renderAllStarCard();
        renderCalendarInjuryReport();
        renderCupCard();
    }

    async function renderCupCard() {
        const el = document.getElementById('cup-content');
        if (!el) return;
        try {
            const res = await fetch('/api/cup_status');
            const cup = await res.json();
            if (!cup.success) { el.innerHTML = '<div class="text-white-50">Cup groups will be drawn once the season begins.</div>'; return; }
            if (cup.stage === 'group') {
                const rows = Object.entries(cup.groups).map(([g, members]) => {
                    const ranked = members.slice().sort((a, b) => {
                        const sa = cup.standings[a], sb = cup.standings[b];
                        return (sb.wins - sa.wins) || (sb.pt_diff - sa.pt_diff);
                    });
                    const lines = ranked.map(t => `<div class="d-flex justify-content-between"><span>${t}</span><span class="text-white-50">${cup.standings[t].wins}-${cup.standings[t].losses}</span></div>`).join('');
                    return `<div class="col-md-4 mb-3"><div class="fw-bold text-info small mb-1">${g}</div>${lines}</div>`;
                }).join('');
                el.innerHTML = `<div class="small text-white-50 mb-2">Group stage in progress -- group games are regular-season games on your calendar. Standings finalize by Day ${cup.group_window_end_day}.</div><div class="row">${rows}</div>`;
            } else {
                const roundBlock = (label, games) => !games || !games.length ? '' : `
                    <div class="mb-2"><div class="fw-bold text-info small">${label}</div>
                    ${games.map(g => `<div class="d-flex justify-content-between"><span>${g.team1} vs ${g.team2}</span><span class="text-white-50">${g.winner ? '✅ ' + g.winner : 'Day ' + g.day}</span></div>`).join('')}</div>`;
                el.innerHTML = (cup.stage === 'complete'
                    ? `<div class="alert alert-success py-2 mb-3">🏆 ${cup.champion} are your NBA Cup Champions!</div>`
                    : '') + roundBlock('Quarterfinals', cup.bracket.QF) + roundBlock('Semifinals', cup.bracket.SF) + roundBlock('Championship', cup.bracket.F);
            }
        } catch (e) { el.innerHTML = '<div class="text-white-50">Cup status unavailable.</div>'; }
    }

    async function renderCalendarInjuryReport() {
        const el = document.getElementById('calendar-injury-report');
        if (!el) return;
        const res = await fetch('/api/injury_report');
        const data = await res.json();
        const rows = (data.report || []);
        if (rows.length === 0) { el.innerHTML = '<p class="text-white-50">Nobody league-wide is currently out.</p>'; return; }
        el.innerHTML = rows.map(p => `
            <div class="d-flex justify-content-between mb-1 border-bottom border-secondary pb-1">
                <span><a class="player-link" onclick="showPlayerModal('${p.name}')">${p.name}</a> <span class="text-white-50">(${p.team}, ${p.position})</span></span>
                <span class="text-danger">${p.description} — ${p.games_remaining}g left</span>
            </div>`).join('');
    }

    function newsIconClass(kind) {
        return kind === 'injury' ? 'text-danger' : kind === 'milestone' ? 'text-warning' : kind === 'result' ? 'text-info' : 'text-white-50';
    }

    function renderNewsFeed() {
        const el = document.getElementById('league-news-feed');
        if (!el) return;
        const items = state.news || [];
        if (!items.length) { el.innerHTML = '<div class="text-white-50 small">No news yet -- sim some games to get the newswire rolling.</div>'; return; }
        el.innerHTML = items.slice(0, 60).map(n => `
            <div class="d-flex gap-2 py-1 border-bottom border-secondary small">
                <span>${n.icon}</span>
                <span class="text-white-50" style="min-width:70px;">Day ${n.day}</span>
                <span class="${newsIconClass(n.kind)}">${n.text}</span>
            </div>
        `).join('');
    }

    function renderAllStarCard() {
        const card = document.getElementById('all-star-card-col');
        const el = document.getElementById('all-star-content');
        if (!card || !el) return;
        const as = state.all_star;
        if (!as || as.year !== state.year) { card.style.display = 'none'; return; }
        card.style.display = 'block';
        const winner = as.east_score >= as.west_score ? 'East' : 'West';
        el.innerHTML = `
            <div class="mb-2">🏀 <b>${winner} wins the All-Star Game</b>: East ${as.east_score} — West ${as.west_score}</div>
            <div class="small text-white-50 mb-1">Game MVP: <a class="player-link" onclick="showPlayerModal('${as.game_mvp.replace(/'/g,"\\'")}')">${as.game_mvp}</a></div>
            <div class="small text-white-50 mb-1">3-Point Contest Champion: <a class="player-link" onclick="showPlayerModal('${as.three_pt_champ.replace(/'/g,"\\'")}')">${as.three_pt_champ}</a></div>
            <div class="small text-white-50">Slam Dunk Contest Champion: <a class="player-link" onclick="showPlayerModal('${as.dunk_champ.replace(/'/g,"\\'")}')">${as.dunk_champ}</a></div>
        `;
    }

    // ===================== JUMP INTO GAME (live viewer) =====================
    let lgEvents = [], lgCursor = 0, lgTimer = null, lgSpeed = 1, lgPlaying = true, lgBox = null;
    let lgUserSide = 'home';
    let lgMiniTab = 'pbp';
    let lgHomeTimeoutsLeft = 2, lgAwayTimeoutsLeft = 2, lgLastHomeScore = 0, lgLastAwayScore = 0;

    // ==========================================================
    // 2K24-STYLE IN-GAME HUD SCORE BUG
    // Sits on top of the existing text play-by-play feed. Reads the same
    // event stream (lgEvents/lgBox) the feed already uses -- no new backend
    // endpoints needed, just a proper on-screen presentation of the data
    // that was previously only shown as a line of plain text.
    // ==========================================================
    function hudInit() {
        if (!lgBox) return;
        lgHomeTimeoutsLeft = 2; lgAwayTimeoutsLeft = 2; lgLastHomeScore = 0; lgLastAwayScore = 0;
        lgQuartersSoFar = [];
        lgMiniTab = 'pbp';
        const homeAbbr = teamInitials(lgBox.home_team), awayAbbr = teamInitials(lgBox.away_team);
        document.getElementById('hud-home-abbrev').innerText = homeAbbr;
        document.getElementById('hud-away-abbrev').innerText = awayAbbr;
        document.getElementById('hud-home-logo').innerHTML = homeAbbr;
        document.getElementById('hud-home-logo').style.background = teamColor(lgBox.home_team);
        document.getElementById('hud-away-logo').innerHTML = awayAbbr;
        document.getElementById('hud-away-logo').style.background = teamColor(lgBox.away_team);
        document.getElementById('hud-home-score').innerText = '0';
        document.getElementById('hud-away-score').innerText = '0';
        document.getElementById('hud-period').innerText = 'Q1';
        document.getElementById('hud-gameclock').innerText = '12:00';
        document.getElementById('hud-shotclock').innerText = '24';
        hudRenderTimeoutPips();
        // BUGFIX: both "Home Timeout" and "Away Timeout" used to always be
        // clickable regardless of which side the user's team was actually
        // on -- meaning you could call the opponent's timeout for them.
        // There's now a single "Call Timeout" button that always targets
        // whichever side is actually the user's team for this matchup.
        lgUserSide = (lgBox.home_team === state.user_team) ? 'home' : 'away';
        const btn = document.getElementById('lg-timeout-user-btn');
        if (btn) btn.innerText = `⏱ ${lgUserSide === 'home' ? lgBox.home_team : lgBox.away_team} Timeout`;
        lgSwitchMiniTab('pbp');
    }

    function hudRenderTimeoutPips() {
        const mk = n => Array.from({length: 2}, (_, i) => `<span class="pip ${i < n ? 'on' : ''}"></span>`).join('');
        const home = document.getElementById('hud-home-timeouts');
        const away = document.getElementById('hud-away-timeouts');
        if (home) home.innerHTML = mk(lgHomeTimeoutsLeft);
        if (away) away.innerHTML = mk(lgAwayTimeoutsLeft);
    }

    // ---------------- LIVE GAME MINI-TABS: Play-by-Play / Score So Far ----------------
    // First pass at this tracked individual scorers' points by parsing the
    // play-by-play text (every scoring play ends in "(+2)/(+3)" with the
    // scorer's name up front). Turns out that text is generated independently
    // from the actual simulated box score -- validated the parsed totals
    // against the real final per-player PTS after a full game and they did
    // not match at all (several players off by double digits, one missing
    // entirely). Showing that would be confidently wrong, not just rough, so
    // it's gone. What IS reliable: the period-boundary events
    // ("End of 2nd Quarter: X 43, Y 46") carry the real cumulative score at
    // that exact moment, and those numbers are verified to match
    // lgBox.home_quarters/away_quarters exactly. So this tracks a real,
    // accurate team-level score-by-quarter table instead of a fabricated
    // player stat line.
    let lgQuartersSoFar = []; // [{label, home, away}]

    function lgTrackScoringEvent(ev) {
        if (ev.type !== 'period' || !ev.text.startsWith('— End of')) return;
        const label = ev.period;
        lgQuartersSoFar.push({ label, home: ev.home_score, away: ev.away_score });
    }

    function lgSwitchMiniTab(tab) {
        lgMiniTab = tab;
        document.getElementById('lg-minitab-pbp-btn').className = tab === 'pbp' ? 'btn btn-sm btn-accent' : 'btn btn-sm btn-outline-accent';
        document.getElementById('lg-minitab-box-btn').className = tab === 'box' ? 'btn btn-sm btn-accent' : 'btn btn-sm btn-outline-accent';
        document.getElementById('lg-feed').style.display = tab === 'pbp' ? 'block' : 'none';
        document.getElementById('lg-boxscore-sofar').style.display = tab === 'box' ? 'block' : 'none';
        if (tab === 'box') renderLgBoxScoreSoFar();
    }
    window.lgSwitchMiniTab = lgSwitchMiniTab;

    function renderLgBoxScoreSoFar() {
        const el = document.getElementById('lg-boxscore-sofar');
        if (!el || !lgBox) return;
        if (!lgQuartersSoFar.length) {
            el.innerHTML = `<div class="player-meta small">No completed quarters yet -- check back once the 1st ends. (A full player-by-player box score becomes available once the game is final.)</div>`;
            return;
        }
        const rows = lgQuartersSoFar.map(q => `<tr><td>${q.label.replace('1st Quarter','Q1').replace('2nd Quarter','Q2').replace('3rd Quarter','Q3').replace('4th Quarter','Q4')}</td><td class="text-end">${q.away}</td><td class="text-end">${q.home}</td></tr>`).join('');
        el.innerHTML = `
            <div class="player-meta small mb-2">Running team score by quarter. A full player-by-player box score becomes available once the game is final -- use Skip to Final or check it afterward in League Leaders / Team Tracker.</div>
            <table class="table-dark-custom" style="font-size:0.86rem; max-width:360px;">
                <thead><tr><th>Through</th><th class="text-end">${lgBox.away_team}</th><th class="text-end">${lgBox.home_team}</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
    }

    function hudFlashScore(el) {
        el.classList.add('flash');
        setTimeout(() => el.classList.remove('flash'), 300);
    }

    // Parses period text like "1st Quarter" / "4th Quarter" / "Overtime" into
    // a compact "Q1"-style label, and pulls a clock string out of ev.clock
    // when present so the HUD clock reads like a real broadcast bug.
    function hudPeriodShort(periodText) {
        if (!periodText) return 'Q1';
        if (/overtime/i.test(periodText)) return 'OT';
        if (/final/i.test(periodText)) return 'FINAL';
        const m = periodText.match(/(\d)/);
        return m ? `Q${m[1]}` : periodText.slice(0, 4).toUpperCase();
    }

    function hudUpdate(ev) {
        if (!ev || !lgBox) return;
        if (ev.home_score !== undefined) {
            const hEl = document.getElementById('hud-home-score'), aEl = document.getElementById('hud-away-score');
            if (hEl) {
                hEl.innerText = ev.home_score;
                if (ev.home_score !== lgLastHomeScore) { hudFlashScore(hEl); lgLastHomeScore = ev.home_score; }
            }
            if (aEl) {
                aEl.innerText = ev.away_score;
                if (ev.away_score !== lgLastAwayScore) { hudFlashScore(aEl); lgLastAwayScore = ev.away_score; }
            }
        }
        const periodEl = document.getElementById('hud-period');
        if (periodEl && ev.period) periodEl.innerText = hudPeriodShort(ev.period);
        const clockEl = document.getElementById('hud-gameclock');
        if (clockEl && ev.clock) clockEl.innerText = ev.clock;
        const shotEl = document.getElementById('hud-shotclock');
        if (shotEl) shotEl.innerText = ev.shot_clock !== undefined ? ev.shot_clock : '--';
        // Possession glow: the event stream tells us directly which side
        // the play belongs to (ev.team: 'home' | 'away' | null for
        // period markers), so use that instead of guessing from text.
        const homeArrow = document.getElementById('hud-home-poss'), awayArrow = document.getElementById('hud-away-poss');
        if (homeArrow && awayArrow && ev.team) {
            const isHomePoss = ev.team === 'home';
            homeArrow.classList.toggle('active', isHomePoss);
            awayArrow.classList.toggle('active', !isHomePoss);
        }
    }
    window.hudUpdate = hudUpdate;


    async function renderLiveGameTab() {
        // BUGFIX: this function used to run unconditionally on every refreshState()
        // call -- including the 2-second heartbeat poll -- which meant it would
        // hide an in-progress live viewer and rebuild the picker out from under
        // the user a couple seconds after they hit "Watch Live". Skip the rebuild
        // while a game is actively being watched.
        const viewer = document.getElementById('livegame-viewer');
        if (viewer && viewer.style.display === 'block') return;
        viewer.style.display = 'none';
        const picker = document.getElementById('livegame-picker');
        picker.innerHTML = '<div class="text-white-50 small">Loading today\'s games...</div>';
        const res = await fetch('/api/todays_games');
        const data = await res.json();
        // UPGRADE: this viewer is now reached only via the Season Calendar
        // (2K MyLeague-style), and only ever shows the user's own game --
        // no browsing/watching other teams' games.
        const userGames = data.games.filter(g => g.is_user_game);
        if (!userGames.length) {
            picker.innerHTML = `<div class="alert alert-secondary">No game for your team today (Day ${data.day}). Head to the Season Calendar to sim forward to your next game.</div>`;
            return;
        }
        picker.innerHTML = `<div class="text-white-50 small mb-2">Day ${data.day} -- Your Game</div>` + userGames.map(g => `
            <div class="p-2 mb-2 bg-dark border border-secondary rounded ${g.is_user_game ? 'border-warning' : ''}">
                <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
                    <div>${g.is_user_game ? '⭐ ' : ''}${teamLogoHtml(g.away)} ${g.away} (${g.away_record}) @ ${teamLogoHtml(g.home)} ${g.home} (${g.home_record})</div>
                    <button class="btn btn-sm ${g.watched ? 'btn-outline-accent' : 'btn-accent'}" onclick="watchLiveGame('${g.home.replace(/'/g,"\\\\'")}', '${g.away.replace(/'/g,"\\\\'")}')">
                        ${g.watched ? '🔁 Replay' : '▶ Watch Live'}
                    </button>
                </div>
                ${g.is_user_game && !g.watched ? `
                <div class="mt-2 small text-white-50">
                    Game Plan for this matchup:
                    <select id="gp-pace-${g.home.replace(/ /g,'_')}" class="form-select form-select-sm d-inline-block w-auto bg-dark text-white border-secondary">
                        <option value="">Pace: default</option>
                        <option value="Push the Pace">Push the Pace</option>
                        <option value="Balanced">Balanced</option>
                        <option value="Slow it Down">Slow it Down</option>
                    </select>
                    <select id="gp-scoring-${g.home.replace(/ /g,'_')}" class="form-select form-select-sm d-inline-block w-auto bg-dark text-white border-secondary">
                        <option value="">Offense: default</option>
                        <option value="Balanced Attack">Balanced Attack</option>
                        <option value="Feed the Star">Feed the Star</option>
                        <option value="Three-Point Heavy">Three-Point Heavy</option>
                        <option value="Inside-Out">Inside-Out</option>
                    </select>
                </div>` : ''}
            </div>
        `).join('');
    }
    window.renderLiveGameTab = renderLiveGameTab;

    let lgPendingCrunch = null;
    async function watchLiveGame(home, away, crunchCall) {
        const gpKey = home.replace(/ /g,'_');
        const paceSel = document.getElementById(`gp-pace-${gpKey}`);
        const scoringSel = document.getElementById(`gp-scoring-${gpKey}`);
        const game_plan = {};
        if (paceSel && paceSel.value) game_plan.pace = paceSel.value;
        if (scoringSel && scoringSel.value) game_plan.scoring_option = scoringSel.value;
        const body = {home, away, game_plan};
        if (crunchCall) body.crunch_call = crunchCall;
        const res = await fetch('/api/watch_game', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
        const data = await res.json();
        if (data.status === 'crunch_choice_needed') {
            // UI OVERHAUL: this used to skip straight to a decision screen with
            // zero playback -- if your team's game was ever close (which is
            // often!) "Jump Into Game" looked like it ONLY ever showed crunch
            // time. Now it plays the entire game like a real broadcast, and
            // only pauses for the human coach's final-possession call once
            // playback naturally reaches the end -- same as 2K.
            lgPendingCrunch = {home, away, plays: data.plays};
            document.getElementById('lg-crunch-panel').style.display = 'none';
            lgBox = data.box;
            lgEvents = data.events;
            lgCursor = 0;
            lgPlaying = true;
            lgSpeed = 1;
            document.getElementById('livegame-viewer').style.display = 'block';
            document.getElementById('livegame-picker').style.display = 'none';
            document.getElementById('lg-feed').innerHTML = '';
            document.getElementById('lg-play-btn').innerText = '⏸ Pause';
            await refreshState();
            hudInit();
            lgTick();
            return;
        }
        if (data.status !== 'success') { showToast(data.reason || 'Could not start that game.', 'error'); return; }
        document.getElementById('lg-crunch-panel').style.display = 'none';
        lgBox = data.box;
        lgEvents = data.events;
        // BUGFIX: after a crunch-time playcall, the server rebuilds play-by-play
        // for the *entire* completed game, and playback used to always restart
        // at event 0 -- so choosing the final play looked like it re-simmed the
        // whole game from tip-off. If this response came from a crunch call,
        // jump straight to the final stretch instead of replaying everything
        // we already just watched.
        lgCursor = data.crunch_result ? Math.max(0, lgEvents.length - 4) : 0;
        lgPlaying = true;
        lgSpeed = 1;
        document.getElementById('livegame-viewer').style.display = 'block';
        document.getElementById('livegame-picker').style.display = 'none';
        document.getElementById('lg-feed').innerHTML = data.crunch_result ? `<div class="text-warning fw-bold">🚨 ${data.crunch_result.text}</div><div class="text-white-50 small mb-2">— final result locked in —</div>` : '';
        document.getElementById('lg-play-btn').innerText = '⏸ Pause';
        await refreshState();
        hudInit();
        lgTick();
    }
    window.watchLiveGame = watchLiveGame;

    // UPGRADE: Play-in tournament game speed/replay -- reuses the exact same
    // live-viewer playback pipeline (lgBox/lgEvents/lgTick) as a regular-season
    // "Jump Into Game", instead of a separate, inconsistent presentation.
    async function watchPlayInGame(conference, gameKey) {
        const res = await fetch('/api/watch_play_in_game', {method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({conference, game_key: gameKey})});
        const data = await res.json();
        if (data.status !== 'success') { showToast(data.reason || 'Could not start that game.', 'error'); return; }
        lgBox = data.box;
        lgEvents = data.events;
        lgCursor = 0;
        lgPlaying = true;
        lgSpeed = 1;
        switchTab('livegame');
        document.getElementById('livegame-viewer').style.display = 'block';
        document.getElementById('livegame-picker').style.display = 'none';
        document.getElementById('lg-crunch-panel').style.display = 'none';
        document.getElementById('lg-feed').innerHTML = '';
        document.getElementById('lg-play-btn').innerText = '⏸ Pause';
        await refreshState();
        hudInit();
        lgTick();
    }
    window.watchPlayInGame = watchPlayInGame;

    async function lgCallTimeout(side) {
        if (!lgBox) return;
        const res = await fetch('/api/live_timeout', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({home: lgBox.home_team, away: lgBox.away_team, side})});
        const data = await res.json();
        const feed = document.getElementById('lg-feed');
        if (data.status !== 'success') {
            feed.insertAdjacentHTML('beforeend', `<div class="text-danger">${data.reason}</div>`);
            feed.scrollTop = feed.scrollHeight;
            return;
        }
        feed.insertAdjacentHTML('beforeend', `<div class="text-info">⏱ ${data.text} (${data.timeouts_left} left)</div>`);
        feed.scrollTop = feed.scrollHeight;
        if (side === 'home') lgHomeTimeoutsLeft = data.timeouts_left; else lgAwayTimeoutsLeft = data.timeouts_left;
        hudRenderTimeoutPips();
        renderTimeoutPanel(data, side);
    }
    window.lgCallTimeout = lgCallTimeout;

    let lgFoulStrategyOn = false;
    async function lgToggleFoulStrategy() {
        if (!lgBox) return;
        lgFoulStrategyOn = !lgFoulStrategyOn;
        const myTeam = (lgBox.home_team === state.user_team) ? lgBox.home_team : (lgBox.away_team === state.user_team ? lgBox.away_team : state.user_team);
        await fetch('/api/set_ingame_strategy', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({team: myTeam, foul_when_trailing: lgFoulStrategyOn})});
        const btn = document.getElementById('lg-foul-strategy-btn');
        if (btn) btn.innerText = `🦶 Foul When Trailing: ${lgFoulStrategyOn ? 'On' : 'Off'}`;
        const feed = document.getElementById('lg-feed');
        if (feed) {
            feed.insertAdjacentHTML('beforeend', `<div class="text-warning">🦶 ${myTeam} coaching staff will ${lgFoulStrategyOn ? 'now' : 'no longer'} foul aggressively when trailing late.</div>`);
            feed.scrollTop = feed.scrollHeight;
        }
    }
    window.lgToggleFoulStrategy = lgToggleFoulStrategy;

    function stamBarColor(fatigue) {
        if (fatigue >= 70) return '#ef4444';
        if (fatigue >= 40) return '#f59e0b';
        return '#10b981';
    }

    function renderTimeoutPanel(data, side) {
        const panel = document.getElementById('lg-timeout-panel');
        const playerRow = (p, isBench) => `
            <div class="d-flex justify-content-between align-items-center mb-1 small">
                <span><span class="pos-slot-tag">${p.position}</span><b class="text-white">${p.name}</b> ${ovrBadgeHtml(p.rating)}${p.injury ? ' <span class="text-danger">🩹</span>' : ''}</span>
                <span class="text-white-50">${p.ppg} PPG / ${p.rpg} RPG / ${p.apg} APG</span>
            </div>
            <div class="d-flex align-items-center gap-2 mb-2">
                <div style="flex:1; height:6px; background:#1f2937; border-radius:3px; overflow:hidden;">
                    <div style="width:${p.fatigue}%; height:100%; background:${stamBarColor(p.fatigue)};"></div>
                </div>
                <span class="text-white-50" style="font-size:0.7rem;">${Math.round(100 - p.fatigue)}% stamina</span>
                ${isBench && data.is_user_team ? `<button class="btn btn-outline-info" style="padding:1px 8px;font-size:0.7rem;" onclick="lgQuickSub('${p.name.replace(/'/g,"\\'")}')">🔁 Sub In</button>` : ''}
            </div>`;
        panel.innerHTML = `
            <div class="fw-bold text-info mb-2">⏱ ${data.team} Timeout${data.is_user_team ? '' : ' (opponent)'}</div>
            <div class="text-uppercase small text-white-50 mb-1" style="letter-spacing:1px;">On the Floor</div>
            ${data.on_court.map(p => playerRow(p, false)).join('') || '<div class="text-white-50 small">No lineup data.</div>'}
            <div class="text-uppercase small text-white-50 mt-3 mb-1" style="letter-spacing:1px;">Bench</div>
            ${data.bench.map(p => playerRow(p, true)).join('') || '<div class="text-white-50 small">Empty bench.</div>'}
            ${data.is_user_team ? `
            <div class="text-uppercase small text-white-50 mt-3 mb-2" style="letter-spacing:1px;">Draw Up a New Gameplan</div>
            <div class="d-flex gap-2 flex-wrap mb-2">
                <select id="lg-to-offense" class="form-select form-select-sm bg-dark text-white border-secondary w-auto">
                    ${OFFENSE_STYLES_JS.map(o => `<option value="${o}" ${o===data.gameplan.offensive_priority?'selected':''}>${o}</option>`).join('')}
                </select>
                <select id="lg-to-defense" class="form-select form-select-sm bg-dark text-white border-secondary w-auto">
                    ${DEFENSE_STYLES_JS.map(o => `<option value="${o}" ${o===data.gameplan.defensive_priority?'selected':''}>${o}</option>`).join('')}
                </select>
                <select id="lg-to-pace" class="form-select form-select-sm bg-dark text-white border-secondary w-auto">
                    <option value="Slow" ${data.gameplan.pace==='Slow'?'selected':''}>Slow It Down</option>
                    <option value="Balanced" ${data.gameplan.pace==='Balanced'?'selected':''}>Balanced Pace</option>
                    <option value="Fast" ${data.gameplan.pace==='Fast'?'selected':''}>Push The Pace</option>
                </select>
                <button class="btn btn-outline-accent btn-sm" onclick="lgApplyTimeoutGameplan()">Apply for Rest of Season</button>
            </div>
            <div class="small text-white-50">Gameplan/substitution changes here go through your normal coaching staff, same as Team Management -- they take hold starting with your next possession-by-possession game, not by rewriting tonight's result after the fact.</div>
            ` : ''}
            <button class="btn btn-outline-danger btn-sm mt-2" onclick="document.getElementById('lg-timeout-panel').style.display='none';">✕ Close Timeout</button>
        `;
        panel.style.display = 'block';
    }

    async function lgQuickSub(benchName) {
        const t = state.teams[state.user_team];
        const p = state.players[benchName];
        if (!t || !p) return;
        await fetch('/api/set_starter', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({position: p.position, name: benchName})});
        await refreshState();
        const feed = document.getElementById('lg-feed');
        feed.insertAdjacentHTML('beforeend', `<div class="text-info">🔁 ${benchName} checks in at ${p.position} going forward.</div>`);
        feed.scrollTop = feed.scrollHeight;
        document.getElementById('lg-timeout-panel').style.display = 'none';
    }
    window.lgQuickSub = lgQuickSub;

    async function lgApplyTimeoutGameplan() {
        const minsData = {};
        Object.values(state.players).filter(p => p.team === state.user_team && !p.retired).forEach(p => { minsData[p.name] = p.minutes; });
        const t = state.teams[state.user_team];
        await fetch('/api/update_rotation', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                minutes: minsData,
                offensive_priority: document.getElementById('lg-to-offense').value,
                defensive_priority: document.getElementById('lg-to-defense').value,
                pace: document.getElementById('lg-to-pace').value,
                shooting_willingness: t.shooting_willingness, rebounding_style: t.rebounding_style,
                scoring_option: t.scoring_option,
            })
        });
        await refreshState();
        const feed = document.getElementById('lg-feed');
        feed.insertAdjacentHTML('beforeend', `<div class="text-info">📋 New gameplan drawn up on the whiteboard.</div>`);
        feed.scrollTop = feed.scrollHeight;
        document.getElementById('lg-timeout-panel').style.display = 'none';
    }
    window.lgApplyTimeoutGameplan = lgApplyTimeoutGameplan;

    function lgTick() {
        clearTimeout(lgTimer);
        if (!lgPlaying || lgCursor >= lgEvents.length) return;
        const ev = lgEvents[lgCursor];
        const feed = document.getElementById('lg-feed');
        const cls = ev.type === 'final' ? 'text-warning fw-bold' : ev.type === 'period' ? 'text-info' : ev.type === 'flavor' ? 'text-white-50' : 'text-white';
        feed.insertAdjacentHTML('beforeend', `<div class="${cls}">[${ev.clock}] ${ev.text}</div>`);
        // BUGFIX: lgCursor was never advanced here, so the same event re-rendered
        // every tick forever, growing the DOM without bound until the tab froze.
        lgCursor++;
        // Keep the feed from growing unbounded even over a full 48-min game.
        while (feed.childElementCount > 250) feed.removeChild(feed.firstChild);
        feed.scrollTop = feed.scrollHeight;
        hudUpdate(ev);
        lgTrackScoringEvent(ev);
        if (lgMiniTab === 'box') renderLgBoxScoreSoFar();
        if (lgCursor < lgEvents.length) {
            lgTimer = setTimeout(lgTick, 550 / lgSpeed);
        } else if (lgPendingCrunch) {
            lgPlaying = false;
            const {home, away, plays} = lgPendingCrunch;
            lgPendingCrunch = null;
            feed.insertAdjacentHTML('beforeend', `<div class="text-warning fw-bold">🚨 It's anyone's game -- you're drawing up the final possession.</div>`);
            feed.scrollTop = feed.scrollHeight;
            document.getElementById('hud-period').innerText = 'FINAL POSS.';
            const panel = document.getElementById('lg-crunch-panel');
            panel.style.display = 'block';
            document.getElementById('lg-crunch-options').innerHTML = plays.map(pl =>
                `<button class="btn btn-warning btn-sm" onclick="watchLiveGame('${home.replace(/'/g,"\\'")}', '${away.replace(/'/g,"\\'")}', '${pl.key}')">${pl.label}</button>`
            ).join('');
        } else {
            lgPlaying = false;
            const btn = document.getElementById('lg-play-btn');
            if (btn) btn.innerText = '▶ Play';
        }
    }

    function lgTogglePlay() {
        lgPlaying = !lgPlaying;
        document.getElementById('lg-play-btn').innerText = lgPlaying ? '⏸ Pause' : '▶ Play';
        if (lgPlaying) lgTick();
        else clearTimeout(lgTimer);
    }
    window.lgTogglePlay = lgTogglePlay;

    function lgSetSpeed() {
        lgSpeed = lgSpeed >= 4 ? 1 : lgSpeed * 2;
        document.getElementById('lg-speed-btn').innerText = `Speed: ${lgSpeed}x`;
    }
    window.lgSetSpeed = lgSetSpeed;

    function lgSkipToEnd() {
        clearTimeout(lgTimer);
        const feed = document.getElementById('lg-feed');
        for (; lgCursor < lgEvents.length; lgCursor++) {
            const ev = lgEvents[lgCursor];
            const cls = ev.type === 'final' ? 'text-warning fw-bold' : ev.type === 'period' ? 'text-info' : ev.type === 'flavor' ? 'text-white-50' : 'text-white';
            feed.innerHTML += `<div class="${cls}">[${ev.clock}] ${ev.text}</div>`;
            hudUpdate(ev);
            lgTrackScoringEvent(ev);
        }
        if (lgMiniTab === 'box') renderLgBoxScoreSoFar();
        feed.scrollTop = feed.scrollHeight;
        lgPlaying = false;
        document.getElementById('lg-play-btn').innerText = '▶ Play';
        if (lgPendingCrunch) {
            const {home, away, plays} = lgPendingCrunch;
            lgPendingCrunch = null;
            feed.insertAdjacentHTML('beforeend', `<div class="text-warning fw-bold">🚨 It's anyone's game -- you're drawing up the final possession.</div>`);
            document.getElementById('hud-period').innerText = 'FINAL POSS.';
            const panel = document.getElementById('lg-crunch-panel');
            panel.style.display = 'block';
            document.getElementById('lg-crunch-options').innerHTML = plays.map(pl =>
                `<button class="btn btn-warning btn-sm" onclick="watchLiveGame('${home.replace(/'/g,"\\'")}', '${away.replace(/'/g,"\\'")}', '${pl.key}')">${pl.label}</button>`
            ).join('');
        }
    }
    window.lgSkipToEnd = lgSkipToEnd;

    function lgCloseViewer() {
        clearTimeout(lgTimer);
        lgPendingCrunch = null;
        document.getElementById('lg-crunch-panel').style.display = 'none';
        document.getElementById('livegame-viewer').style.display = 'none';
        document.getElementById('livegame-picker').style.display = 'block';
        renderLiveGameTab();
    }
    window.lgCloseViewer = lgCloseViewer;

    function renderCalendar() {
        const cal = document.getElementById('season-calendar');
        if (!cal || !state.schedule) return;
        const userTeam = state.user_team;
        const nextDay = state.current_day; // 1-indexed, next day to be simulated
        let html = '';

        // BUGFIX: games are no longer a uniform N-per-day (rest days can have 0,
        // wave days have ~7-8), so the old `dayIdx * dayMatchups.length` index math
        // into the flat regular_season_games list was wrong as soon as days had
        // different sizes. Build a real cumulative offset per day instead.
        let cumulativeStart = 0;
        const dayStartIdx = state.schedule.map(dayMatchups => {
            const start = cumulativeStart;
            cumulativeStart += dayMatchups.length;
            return start;
        });

        state.schedule.forEach((dayMatchups, dayIdx) => {
            const dayNum = dayIdx + 1;
            const myMatch = dayMatchups.find(m => m.home === userTeam || m.away === userTeam);
            const played = dayNum < nextDay;
            const isNextUp = dayNum === nextDay;

            if (!myMatch) {
                if (played) {
                    html += `<div class="calendar-tile no-game"><div class="cal-day-num">DAY ${dayNum}</div><div class="cal-opp">💤 Rest Day</div></div>`;
                } else {
                    html += `<div class="calendar-tile no-game sim-target" onclick="simToDay(${dayNum})" title="Jump to this day (no game for your team, but sims the league forward)">
                        <div class="cal-day-num">DAY ${dayNum}</div>
                        <div class="cal-opp">💤 Rest Day</div>
                        <div class="cal-wl text-white-50">Jump here</div>
                    </div>`;
                }
                return;
            }

            const opp = myMatch.home === userTeam ? myMatch.away : myMatch.home;
            const isHome = myMatch.home === userTeam;
            const cupBadge = myMatch.cup_knockout ? `<span class="cal-cup-badge" title="NBA Cup ${myMatch.cup_round}">🏆${myMatch.cup_round}</span>`
                : (myMatch.cup_group ? `<span class="cal-cup-badge" title="NBA Cup group game">🏆</span>` : '');

            if (played) {
                const sliceStart = dayStartIdx[dayIdx];
                let realIdx = -1;
                let box = null;
                for (let off = 0; off < dayMatchups.length; off++) {
                    const g = state.regular_season_games[sliceStart + off];
                    if (g && (g.home_team === userTeam || g.away_team === userTeam)) { realIdx = sliceStart + off; box = g; break; }
                }
                if (!box) {
                    html += `<div class="calendar-tile no-game"><div class="cal-day-num">DAY ${dayNum}</div><div class="cal-opp">${teamLogoHtml(opp)} vs</div></div>`;
                    return;
                }
                const myScore = isHome ? box.home_score : box.away_score;
                const oppScore = isHome ? box.away_score : box.home_score;
                const won = myScore > oppScore;
                const otTag = box.overtimes ? ` <span class="text-warning">${box.overtimes}OT</span>` : '';
                html += `<div class="calendar-tile played ${won ? 'win' : 'loss'}" onclick="showBoxScore('regular', ${realIdx})">
                    <div class="cal-day-num">DAY ${dayNum}${cupBadge}</div>
                    <div class="cal-opp">${isHome ? 'vs' : '@'} ${teamLogoHtml(opp)} ${opp.split(' ').pop()}</div>
                    <div class="cal-wl" style="color:${won ? '#10b981' : '#ef4444'}">${won ? 'W' : 'L'} <span class="cal-score">${myScore}-${oppScore}</span>${otTag}</div>
                </div>`;
            } else if (isNextUp) {
                const home = isHome ? userTeam : opp, away = isHome ? opp : userTeam;
                html += `<div class="calendar-tile next-up" onclick="simToDay(${dayNum})" title="Sim to this day">
                    <button class="cal-icon-btn" title="Game day options" onclick="event.stopPropagation(); openGameOptionsModal(${dayNum}, '${home.replace(/'/g,"\\'")}', '${away.replace(/'/g,"\\'")}', true);">📅</button>
                    <div class="cal-day-num">DAY ${dayNum}${cupBadge}</div>
                    <div class="cal-opp">${isHome ? 'vs' : '@'} ${teamLogoHtml(opp)} ${opp.split(' ').pop()}</div>
                    <div class="cal-wl text-info">▶ SIM TO HERE</div>
                </div>`;
            } else {
                const home = isHome ? userTeam : opp, away = isHome ? opp : userTeam;
                html += `<div class="calendar-tile no-game sim-target" onclick="simToDay(${dayNum})" title="Sim to this day">
                    <button class="cal-icon-btn" title="Game day options" onclick="event.stopPropagation(); openGameOptionsModal(${dayNum}, '${home.replace(/'/g,"\\'")}', '${away.replace(/'/g,"\\'")}', false);">📅</button>
                    <div class="cal-day-num">DAY ${dayNum}${cupBadge}</div>
                    <div class="cal-opp">${isHome ? 'vs' : '@'} ${teamLogoHtml(opp)} ${opp.split(' ').pop()}</div>
                    <div class="cal-wl text-white-50">Sim to here</div>
                </div>`;
            }
        });

        cal.innerHTML = html;
    }

    // Composite "power score" -- win pct weighted heavily, point differential as a
    // tiebreaker/form indicator, small bonus for a live win streak. Not an official
    // stat, just a fun 2K-style ranking widget.
    function renderPowerRankings() {
        const el = document.getElementById('power-rankings');
        if (!el || !state.teams) return;
        const rows = Object.entries(state.teams).map(([name, t]) => {
            const gp = t.wins + t.losses;
            const winPct = gp > 0 ? t.wins / gp : 0;
            const diff = (t.points_for || 0) - (t.points_against || 0);
            const score = winPct * 100 + diff * 0.15 + (t.streak || 0) * 0.5;
            return {name, t, score, diff};
        }).sort((a, b) => b.score - a.score);

        let html = '';
        rows.forEach((r, idx) => {
            const ctxTag = r.t.wins + r.t.losses >= 5
                ? (r.t.wins / (r.t.wins + r.t.losses) > 0.6 ? '<span class="badge bg-success">Contender</span>'
                   : r.t.wins / (r.t.wins + r.t.losses) < 0.4 ? '<span class="badge bg-danger">Rebuilder</span>'
                   : '<span class="badge bg-secondary">Balanced</span>')
                : '<span class="badge bg-secondary">—</span>';
            const rankCls = idx === 0 ? 'rank-1' : idx === 1 ? 'rank-2' : idx === 2 ? 'rank-3' : '';
            html += `<div class="col-md-6 col-lg-4 mb-2">
                <div class="power-rank-card ${rankCls}" onclick="showTeamDetail('${r.name}')">
                    <span class="team-chip"><b class="power-rank-num">#${idx+1}</b> ${teamLogoHtml(r.name)} ${r.name}${r.name===state.user_team ? ' ⭐' : ''}</span>
                    <span class="small">${r.t.wins}-${r.t.losses} ${ctxTag}</span>
                </div>
            </div>`;
        });
        el.innerHTML = html;
    }

    // ===================== TEAM TRACKER TAB =====================
    let teamTrackerActiveTeam = null;

    async function renderTeamTrackerTab() {
        const listView = document.getElementById('teamtracker-list-view');
        const detailView = document.getElementById('teamtracker-detail-view');
        if (teamTrackerActiveTeam) {
            listView.style.display = 'none';
            detailView.style.display = 'block';
            renderTeamDetail(teamTrackerActiveTeam);
        } else {
            listView.style.display = 'block';
            detailView.style.display = 'none';
            let clinchData = {applicable: false};
            if (state.stage === 'regular_season') {
                try { clinchData = await (await fetch('/api/clinching_scenarios')).json(); } catch (e) { clinchData = {applicable: false}; }
            }
            ['East', 'West'].forEach(conf => {
                const el = document.getElementById(`tt-standings-${conf.toLowerCase()}`);
                if (!el) return;
                const clinchRows = (clinchData.applicable && clinchData.conferences[conf]) || [];
                const clinchByTeam = {};
                clinchRows.forEach(r => clinchByTeam[r.team] = r);
                const confTeams = Object.entries(state.teams).filter(([, d]) => d.conference === conf)
                    .sort((a, b) => (b[1].wins/(Math.max(1,b[1].wins+b[1].losses))) - (a[1].wins/(Math.max(1,a[1].wins+a[1].losses))) || b[1].wins - a[1].wins);
                const leaderWins = confTeams.length ? confTeams[0][1].wins : 0;
                const leaderLosses = confTeams.length ? confTeams[0][1].losses : 0;
                let html = `<table class="table-dark-custom"><thead><tr><th>#</th><th>Team</th><th>W</th><th>L</th><th>PCT</th><th>GB</th><th>STRK</th><th>L10</th></tr></thead><tbody>`;
                confTeams.forEach(([name, d], idx) => {
                    const playoffTag = idx < 8 ? ' 🏆' : '';
                    const gp = Math.max(1, d.wins + d.losses);
                    const pct = (d.wins / gp).toFixed(3).replace(/^0/, '');
                    const gb = idx === 0 ? '—' : (((leaderWins - d.wins) + (d.losses - leaderLosses)) / 2).toFixed(1);
                    const strk = (d.streak||0) > 0 ? `W${d.streak}` : (d.streak||0) < 0 ? `L${Math.abs(d.streak)}` : '—';
                    const strkCls = (d.streak||0) > 0 ? 'text-success' : (d.streak||0) < 0 ? 'text-danger' : 'text-white-50';
                    const recent = d.recent_results || [];
                    const l10w = recent.filter(r => r === 'W').length, l10l = recent.length - l10w;
                    const clinch = clinchByTeam[name];
                    let clinchBadge = '';
                    let clinchTitle = '';
                    if (clinch) {
                        if (clinch.status === 'clinched') { clinchBadge = ' <span class="badge bg-success" style="font-size:0.6rem;">X</span>'; clinchTitle = 'Clinched a top-6 seed'; }
                        else if (clinch.status === 'eliminated') { clinchBadge = ' <span class="badge bg-secondary" style="font-size:0.6rem;">E</span>'; clinchTitle = 'Eliminated from playoff contention'; }
                        else if (clinch.magic_number !== null && clinch.magic_number !== undefined) { clinchTitle = `Magic number to clinch top-6: ${clinch.magic_number}`; }
                    }
                    html += `<tr style="cursor:pointer;" onclick="showTeamDetail('${name}')" title="${clinchTitle}">
                        <td>${idx + 1}</td>
                        <td>${teamLogoHtml(name)} ${name}${name===state.user_team ? ' ⭐' : ''}${playoffTag}${clinchBadge}</td>
                        <td>${d.wins}</td><td>${d.losses}</td><td>${pct}</td><td>${gb}</td>
                        <td class="${strkCls}">${strk}</td><td>${recent.length ? l10w+'-'+l10l : '—'}</td>
                    </tr>`;
                });
                html += `</tbody></table>`;
                el.innerHTML = html;
            });
            renderPowerRankings();
        }
    }

    function showTeamDetail(teamName) {
        teamTrackerActiveTeam = teamName;
        switchTab('teamtracker', document.querySelector("button[onclick*='teamtracker']"));
    }

    function showTeamTrackerList(silent) {
        teamTrackerActiveTeam = null;
        if (!silent) renderTeamTrackerTab();
    }

    // Small SVG donut used to visualize team chemistry (0-100) wherever a
    // team header is shown -- real backend-tracked value (state.teams[t].chemistry),
    // not a cosmetic fake stat.
    function chemistryRingSvg(value, size) {
        size = size || 54;
        const v = Math.max(0, Math.min(100, value == null ? 65 : value));
        const r = (size / 2) - 5;
        const c = 2 * Math.PI * r;
        const offset = c * (1 - v / 100);
        const color = v >= 75 ? '#2ee6a6' : v >= 45 ? '#ffb020' : '#ff5470';
        return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" title="Team Chemistry: ${Math.round(v)}">
            <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="#1d2c4d" stroke-width="5"/>
            <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="5"
                stroke-dasharray="${c}" stroke-dashoffset="${offset}" stroke-linecap="round"
                transform="rotate(-90 ${size/2} ${size/2})" style="transition:stroke-dashoffset .4s ease;"/>
            <text x="50%" y="53%" text-anchor="middle" dominant-baseline="middle" fill="#f4f7fb"
                font-size="${size*0.26}" font-family="Rajdhani,sans-serif" font-weight="700">${Math.round(v)}</text>
        </svg>`;
    }

    function renderTeamDetail(teamName) {
        const el = document.getElementById('tt-detail-content');
        const t = state.teams[teamName];
        if (!t || !el) { showTeamTrackerList(); return; }
        const roster = Object.values(state.players).filter(p => p.team === teamName && !p.retired)
            .sort((a,b) => (b.stats.PTS/(b.stats.GP||1)) - (a.stats.PTS/(a.stats.GP||1)));

        let html = `
            <div class="d-flex align-items-center gap-3 mb-3 pb-3 border-bottom border-secondary">
                <span class="player-avatar" style="background:${teamColor(teamName)};">${teamInitials(teamName)}</span>
                <div class="flex-fill">
                    <h3 class="text-white m-0">${teamName}${teamName===state.user_team ? ' ⭐' : ''}</h3>
                    <div class="small text-white-50">${t.conference}ern Conference · Record ${t.wins}-${t.losses} · ${(t.streak||0) > 0 ? 'W'+t.streak : (t.streak||0) < 0 ? 'L'+Math.abs(t.streak) : 'No streak'}</div>
                </div>
                <div class="text-center" style="line-height:1;">
                    ${chemistryRingSvg(t.chemistry, 54)}
                    <div class="small text-white-50 mt-1" style="letter-spacing:0.5px;">CHEMISTRY</div>
                </div>
                <div class="text-end small text-white-50">
                    <div>Offense: <b class="text-white">${t.offensive_priority}</b></div>
                    <div>Defense: <b class="text-white">${t.defensive_priority}</b></div>
                    <div>Pace: <b class="text-white">${t.pace}</b></div>
                </div>
            </div>
        `;

        const pastSeasons = (state.history || []).filter(h => h.standings && h.standings[teamName]);
        const champYears = pastSeasons.filter(h => h.champion === teamName).map(h => h.year);
        if (pastSeasons.length > 0) {
            html += `<h5 class="text-white-50 font-monospace mb-2">🏛 Franchise History</h5>`;
            html += `<div class="mb-3 small">
                <span class="jersey-badge">🏆 ${champYears.length} Championship${champYears.length === 1 ? '' : 's'}</span>
                ${champYears.length ? `<span class="text-white-50 ms-2">(${champYears.join(', ')})</span>` : ''}
            </div>`;
            html += `<div style="max-height:220px; overflow-y:auto;" class="mb-4"><table class="table-dark-custom">
                <thead><tr><th>Season</th><th>Record</th><th>League MVP</th><th>Champion</th></tr></thead><tbody>`;
            pastSeasons.slice().reverse().forEach(h => {
                const rec = h.standings[teamName];
                const wonIt = h.champion === teamName;
                html += `<tr${wonIt ? ' style="background:rgba(250,204,21,0.08);"' : ''}>
                    <td>${h.year}</td><td>${rec.wins}-${rec.losses}</td>
                    <td>${h.mvp === undefined || h.mvp === null ? '—' : (state.players[h.mvp] ? `<a class="player-link" onclick="showPlayerModal('${h.mvp}')">${h.mvp}</a>` : h.mvp)}</td>
                    <td>${wonIt ? '🏆 ' + h.champion : (h.champion || '—')}</td>
                </tr>`;
            });
            html += `</tbody></table></div>`;
        }

        // UPGRADE: Team-vs-team head-to-head series history. Pulls from the
        // server-side h2h_history ledger (built incrementally in
        // record_h2h every time these two teams play) and lets the GM pick
        // any opponent to see the all-time series record + recent meetings.
        const opponents = Object.keys(state.teams).filter(t => t !== teamName).sort();
        if (!h2hOpponent || h2hOpponent === teamName) h2hOpponent = opponents[0];
        const oppOpts = opponents.map(t => `<option value="${t}" ${t === h2hOpponent ? 'selected' : ''}>${t}</option>`).join('');
        html += `<h5 class="text-white-50 font-monospace mb-2">⚔️ Head-to-Head</h5>
            <div class="d-flex align-items-center gap-2 mb-2">
                <label class="small text-white-50 mb-0">vs.</label>
                <select class="form-select form-select-sm bg-dark text-white border-secondary" style="width:auto;" onchange="setH2hOpponent(this.value)">${oppOpts}</select>
            </div>
            <div id="h2h-render" class="mb-4"></div>`;

        html += `<h5 class="text-white-50 font-monospace mb-2">Current Roster & ${state.year || ''} Season Stats</h5>`;
        html += `<div style="max-height:600px; overflow-y:auto;"><table class="table-dark-custom">
            <thead><tr><th>Player</th><th>Pos</th><th>Age</th><th>OVR</th><th>GP</th><th>MPG</th><th>PPG</th><th>RPG</th><th>APG</th><th>FG%</th><th>3PT%</th><th>Badges</th></tr></thead><tbody>`;
        roster.forEach(p => {
            const s = p.stats || {GP:0,PTS:0,REB:0,AST:0,FGM:0,FGA:0,'3PM':0,'3PA':0,MIN:0};
            const gp = s.GP || 0;
            const ppg = gp > 0 ? (s.PTS/gp).toFixed(1) : '0.0';
            const rpg = gp > 0 ? (s.REB/gp).toFixed(1) : '0.0';
            const apg = gp > 0 ? (s.AST/gp).toFixed(1) : '0.0';
            const mpg = gp > 0 ? ((s.MIN||0)/gp).toFixed(1) : '0.0';
            const fgPct = s.FGA > 0 ? ((s.FGM/s.FGA)*100).toFixed(1) : '0.0';
            const tpPct = s['3PA'] > 0 ? ((s['3PM']/s['3PA'])*100).toFixed(1) : '0.0';
            const injBadge = p.injury ? ` <span class="badge-injury">🩹</span>` : '';
            html += `<tr>
                <td><a class="player-link" onclick="showPlayerModal('${p.name}')">${p.name}</a>${injBadge}</td>
                <td>${p.position}</td><td>${p.age}</td><td class="text-warning">${p.rating}</td>
                <td>${gp}</td><td>${mpg}</td><td class="text-warning">${ppg}</td><td>${rpg}</td><td>${apg}</td>
                <td class="text-info">${fgPct}%</td><td class="text-info">${tpPct}%</td>
                <td>${badgeChipsHtml(p, 3)}</td>
            </tr>`;
        });
        html += `</tbody></table></div>`;
        el.innerHTML = html;
        renderH2hPanel(teamName);
    }

    let h2hOpponent = null;
    function setH2hOpponent(team) {
        h2hOpponent = team;
        renderH2hPanel(teamTrackerActiveTeam);
    }
    window.setH2hOpponent = setH2hOpponent;

    function renderH2hPanel(teamName) {
        const el = document.getElementById('h2h-render');
        if (!el || !h2hOpponent) return;
        const key = [teamName, h2hOpponent].sort().join('|');
        const ledger = (state.h2h_history || {})[key];
        if (!ledger) {
            el.innerHTML = `<p class="text-white-50 small">${teamName} and ${h2hOpponent} haven't played yet.</p>`;
            return;
        }
        const myWins = ledger[teamName] || 0;
        const theirWins = ledger[h2hOpponent] || 0;
        const games = (ledger.games || []).slice().reverse();
        let html = `<div class="mb-2">
            <span class="text-white fw-bold" style="font-size:1.1rem;">${teamName} ${myWins} — ${theirWins} ${h2hOpponent}</span>
            <span class="text-white-50 small ms-2">(all-time series)</span>
        </div>`;
        if (games.length) {
            html += `<div style="max-height:220px; overflow-y:auto;"><table class="table-dark-custom">
                <thead><tr><th>Year</th><th>Matchup</th><th>Score</th><th>Type</th></tr></thead><tbody>`;
            games.forEach(g => {
                const homeWon = g.home_score > g.away_score;
                html += `<tr>
                    <td>${g.year}</td>
                    <td>${g.away} @ ${g.home}</td>
                    <td>${homeWon ? `<b>${g.home_score}</b>-${g.away_score}` : `${g.away_score}-<b>${g.home_score}</b>`}</td>
                    <td>${g.is_playoff ? '🏆 Playoffs' : 'Regular'}</td>
                </tr>`;
            });
            html += `</tbody></table></div>`;
        }
        el.innerHTML = html;
    }

    // ===================== PLAYOFFS TAB =====================
    function renderPlayoffsTab() {
        const initPanel = document.getElementById('playoff-init-panel');
        const layout = document.getElementById('playoff-bracket-layout');
        if (!initPanel || !layout) return;
        initPanel.innerHTML = ''; layout.innerHTML = ''; layout.style.display = 'none';

        if (state.stage === 'play_in') {
            const pi = state.play_in;
            const renderGame = (g, conf, gameKey) => {
                if (!g.team1 || !g.team2) return `<div class="text-white-50 small">${g.label} — TBD</div>`;
                const done = g.winner != null;
                return `<div class="mb-2">
                    <div class="small text-muted">${g.label}</div>
                    <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
                        <div>${teamLogoHtml(g.team1, 20)} ${g.team1.split(' ').pop()} vs ${teamLogoHtml(g.team2, 20)} ${g.team2.split(' ').pop()}
                        ${done ? `<b class="text-success ms-2">→ ${g.winner}</b>` : ''}</div>
                        ${!done ? `<button class="btn btn-sm btn-accent" onclick="watchPlayInGame('${conf}', '${gameKey}')">🎮 Jump Into Game</button>` : ''}
                    </div>
                </div>`;
            };
            let piHtml = `<h4>🎟️ Play-In Tournament</h4><div class="row">`;
            ['East', 'West'].forEach(conf => {
                const c = pi[conf];
                if (!c) return;
                piHtml += `<div class="col-md-6">
                    <h5 class="text-warning">${conf}ern Conference</h5>
                    <div class="small text-muted mb-2">Seeds 1-6 locked: ${c.locked_top6.map(t => t.split(' ').pop()).join(', ')}</div>
                    ${renderGame(c.game1, conf, 'game1')}
                    ${renderGame(c.game2, conf, 'game2')}
                    ${renderGame(c.game3, conf, 'game3')}
                    ${c.complete ? `<div class="text-success small mt-2">Final: #7 ${c.final_7_seed}, #8 ${c.final_8_seed}</div>` : ''}
                </div>`;
            });
            piHtml += `</div><button class="btn btn-danger btn-lg mt-3" onclick="simulatePlayIn()">⚡ Simulate All Remaining Play-In Games Instantly</button>`;
            initPanel.innerHTML = piHtml;
            return;
        }

        if (!state.playoffs_started) {
            initPanel.innerHTML = `<p class="text-white-50">Post-season brackets require regular season matrix complete parameters. The bracket seeds itself automatically the moment the full regular-season schedule wraps up.</p>`;
            return;
        }

        const r = state.current_round;
        initPanel.innerHTML = `<h4>Running Post-Season Bracket: <span class="text-warning">ROUND ${r}</span></h4>`;

        // Rounds now auto-advance the instant every series in them finishes
        // (handled server-side), so there's no "stuck, waiting on a button"
        // state anymore -- the bracket just keeps moving on its own.
        if (state.stage === 'playoffs') {
            // BUGFIX: this button's label/class used to be hardcoded here and
            // only patched to "Pause" by togglePlayoffAutoSim() afterward --
            // but this whole panel gets rebuilt from scratch on every
            // refreshState() tick while auto-sim is running (every ~700ms),
            // which wiped that patch back to "▶ Auto-Sim Series" almost
            // immediately. It technically still worked if you clicked it
            // (the timer variable itself was still tracked correctly), but
            // visually it never looked like it was running or pausable.
            // Render the correct state directly instead of relying on a
            // DOM mutation that kept getting overwritten.
            const autoSimRunning = !!playoffAutoSimTimer;
            initPanel.innerHTML += `
                <div class="d-flex align-items-center gap-3 flex-wrap my-2">
                    <button class="btn btn-danger btn-lg" onclick="simulatePlayoffGames()">⚡ Simulate Next Game</button>
                    <button class="btn ${autoSimRunning ? 'btn-warning' : 'btn-accent'}" id="btn-playoff-autosim-toggle" onclick="togglePlayoffAutoSim()">${autoSimRunning ? '⏸ Pause' : '▶ Auto-Sim Series'}</button>
                </div>`;
        } else if (r === 4) {
            const champ = state.playoff_bracket["4"][0].winner;
            initPanel.innerHTML += `<h2 class="text-success font-monospace fw-bold my-3">🏆 TOURNAMENT CONCLUDED <br/> CHAMPIONS: ${teamLogoHtml(champ, 32)} ${champ}</h2>`;
            initPanel.innerHTML += `<div class="alert alert-info">Head to the <b>Front Office</b> tab to process retirements, run progression, and begin the offseason.</div>`;
            stopPlayoffAutoSim();
        }

        layout.style.display = 'grid';
        layout.innerHTML = buildBracketTreeHtml();
    }

    // Round 1 is seeded [East x4, West x4]; advance_round() pairs adjacent
    // winners each round, which naturally keeps East and West separated all
    // the way to the Finals -- so we know exactly which array slice is which
    // conference at every round without any extra bookkeeping.
    function seedCard(r, mIdx, sideTeam, seedNum) {
        const m = state.playoff_bracket[r] ? state.playoff_bracket[r][mIdx] : null;
        if (!m) return `<div class="bracket-seed-card text-white-50">TBD</div>`;
        const isTeam1 = sideTeam === 'team1';
        const teamName = isTeam1 ? m.team1 : m.team2;
        const wins = isTeam1 ? m.series[0] : m.series[1];
        const isWinner = m.winner === teamName;
        return `<div class="bracket-seed-card" onclick="showSeriesModal('${r}', ${mIdx})">
            <div class="bracket-seed-row ${isWinner ? 'winner' : ''}">
                <span class="team-chip">${seedNum ? `<small class="text-muted">(${seedNum})</small>` : ''} ${teamLogoHtml(teamName)} ${teamName.split(' ').pop()}</span>
                <span class="bracket-series-score">${wins}</span>
            </div>
        </div>`;
    }

    function seedPairHtml(r, mIdx, seed1, seed2) {
        return `<div class="mb-2">${seedCard(r, mIdx, 'team1', seed1)}${seedCard(r, mIdx, 'team2', seed2)}</div>`;
    }

    function buildBracketTreeHtml() {
        const b = state.playoff_bracket;
        // Round 1: East = indices 0-3, West = indices 4-7 (see seed_conference_bracket/start_playoffs)
        const westR1 = [4, 5, 6, 7], eastR1 = [0, 1, 2, 3];
        const westSeeds = [[1,8],[4,5],[2,7],[3,6]]; // matches the (0,7),(3,4),(1,6),(2,5) static seeding
        const eastSeeds = [[1,8],[4,5],[2,7],[3,6]];

        let westR1Html = westR1.map((idx, i) => seedPairHtml('1', idx, westSeeds[i][0], westSeeds[i][1])).join('');
        let eastR1Html = eastR1.map((idx, i) => seedPairHtml('1', idx, eastSeeds[i][0], eastSeeds[i][1])).join('');

        // Round 2: East = indices 0-1, West = indices 2-3
        let westR2Html = [2, 3].map(idx => seedPairHtml('2', idx)).join('');
        let eastR2Html = [0, 1].map(idx => seedPairHtml('2', idx)).join('');

        // Round 3 (conference finals): East = index 0, West = index 1
        let westR3Html = seedPairHtml('3', 1);
        let eastR3Html = seedPairHtml('3', 0);

        // Round 4: League Finals (center)
        const finals = b['4'] ? b['4'][0] : null;
        let finalsHtml;
        if (finals) {
            finalsHtml = `<div class="bracket-finals-card" onclick="showSeriesModal('4', 0)">
                <div class="bracket-finals-title">🏆 League Finals</div>
                <div class="bracket-seed-row ${finals.winner === finals.team1 ? 'winner' : ''}">${teamLogoHtml(finals.team1, 26)} ${finals.team1.split(' ').pop()} <b class="bracket-series-score">${finals.series[0]}</b></div>
                <div class="bracket-seed-row ${finals.winner === finals.team2 ? 'winner' : ''}">${teamLogoHtml(finals.team2, 26)} ${finals.team2.split(' ').pop()} <b class="bracket-series-score">${finals.series[1]}</b></div>
                ${finals.winner ? `<div class="mt-2" style="color:#2ee6a6; font-weight:700;">🏆 ${finals.winner}</div>` : ''}
            </div>`;
        } else {
            finalsHtml = `<div class="bracket-finals-card text-white-50">Awaiting<br>Conference Champions</div>`;
        }

        const col = (label, html) => `<div class="bracket-tree-col"><div class="bracket-tree-col-label">${label}</div>${html}</div>`;

        return col('WEST R1', westR1Html) + col('WEST SEMIS', westR2Html) + col('WEST FINALS', westR3Html) +
               `<div class="d-flex align-items-center justify-content-center">${finalsHtml}</div>` +
               col('EAST FINALS', eastR3Html) + col('EAST SEMIS', eastR2Html) + col('EAST R1', eastR1Html);
    }


    async function simulatePlayoffGames() { await fetch('/api/simulate_playoff_games', {method: 'POST'}); refreshState(); }
    async function simulatePlayIn() { await fetch('/api/simulate_play_in', {method: 'POST'}); refreshState(); }
    window.simulatePlayIn = simulatePlayIn;

    async function openSaveLoadMenu() {
        document.getElementById('player-modal').style.display = 'none';
        document.getElementById('boxscore-modal').style.display = 'none';
        await renderSaveLoadList();
        document.getElementById('modal-overlay').style.display = 'block';
        document.getElementById('save-load-modal').style.display = 'block';
        openModal = {type: 'save-load'};
    }
    window.openSaveLoadMenu = openSaveLoadMenu;

    async function renderSaveLoadList() {
        const el = document.getElementById('save-load-list');
        if (!el) return;
        el.innerHTML = '<div class="text-white-50 small">Loading saves...</div>';
        const res = await fetch('/api/list_saves');
        const data = await res.json();
        const saves = data.saves || [];
        if (!saves.length) {
            el.innerHTML = '<div class="text-white-50 small">No saves yet -- name a slot above and hit Save New.</div>';
            return;
        }
        el.innerHTML = saves.map(s => `
            <div class="stat-subpanel mb-2 d-flex justify-content-between align-items-center flex-wrap gap-2">
                <div>
                    <div class="fw-bold text-info">${s.slot}</div>
                    <div class="small text-white-50">${s.user_team} · ${s.year} · ${s.stage}${s.record ? ` · ${s.record}` : ''}${s.star_player ? ` · ⭐ ${s.star_player} (${s.star_player_rating} OVR)` : ''}</div>
                </div>
                <div class="d-flex gap-2">
                    <button class="btn btn-sm btn-accent" onclick="loadSaveSlot('${s.slot.replace(/'/g, "\\'")}')">▶ Load</button>
                    <button class="btn btn-sm btn-outline-warning" onclick="overwriteSaveSlot('${s.slot.replace(/'/g, "\\'")}')" title="Overwrite this slot with your current game">💾 Overwrite</button>
                    <button class="btn btn-sm btn-danger-custom" onclick="deleteSaveSlot('${s.slot.replace(/'/g, "\\'")}')">🗑</button>
                </div>
            </div>`).join('');
    }
    window.renderSaveLoadList = renderSaveLoadList;

    async function reloadDataFiles() {
        if (!confirm('This replaces your current league with a fresh read of the data/division_*.json files. Any unsaved progress in your current game will be lost. Continue?')) return;
        const res = await fetch('/api/reload_data_files', { method: 'POST' });
        const result = await res.json();
        if (!result.success) {
            showToast(result.reason || 'Reload failed -- your current league was left untouched.', 'error');
            return;
        }
        closeModals();
        await refreshState();
        showToast(`Reloaded ${result.teams} teams, ${result.players} players from data files.`, 'success');
    }
    window.reloadDataFiles = reloadDataFiles;

    async function saveToNewSlot() {
        const input = document.getElementById('save-new-slot-name');
        const slot = (input.value || '').trim();
        if (!slot) { showToast('Give the save slot a name first.', 'error'); return; }
        const res = await fetch('/api/save_game', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({slot})});
        const result = await res.json();
        if (!result.success) { showToast(result.reason || 'Save failed.', 'error'); return; }
        input.value = '';
        SoundEngine.sfx.swish();
        showToast(`Saved to "${slot}".`, 'success');
        await renderSaveLoadList();
    }
    window.saveToNewSlot = saveToNewSlot;

    async function overwriteSaveSlot(slot) {
        if (!confirm(`Overwrite "${slot}" with your current game? This can't be undone.`)) return;
        const res = await fetch('/api/save_game', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({slot})});
        const result = await res.json();
        if (!result.success) { showToast(result.reason || 'Save failed.', 'error'); return; }
        SoundEngine.sfx.swish();
        showToast(`Saved to "${slot}".`, 'success');
        await renderSaveLoadList();
    }
    window.overwriteSaveSlot = overwriteSaveSlot;

    async function loadSaveSlot(slot) {
        if (!confirm(`Load "${slot}"? Any unsaved progress in your current game will be lost.`)) return;
        const res = await fetch('/api/load_game', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({slot})});
        const result = await res.json();
        if (!result.success) { showToast(result.reason || 'Load failed.', 'error'); return; }
        closeModals();
        await refreshState();
        SoundEngine.sfx.swish();
        showToast(`Loaded "${slot}".`, 'success');
    }
    window.loadSaveSlot = loadSaveSlot;

    async function deleteSaveSlot(slot) {
        if (!confirm(`Delete save "${slot}"? This can't be undone.`)) return;
        const res = await fetch('/api/delete_save', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({slot})});
        const result = await res.json();
        if (!result.success) { showToast(result.reason || 'Delete failed.', 'error'); return; }
        showToast(`Deleted "${slot}".`, 'success');
        await renderSaveLoadList();
    }
    window.deleteSaveSlot = deleteSaveSlot;

    let playoffAutoSimTimer = null;
    function togglePlayoffAutoSim() {
        if (playoffAutoSimTimer) { stopPlayoffAutoSim(); return; }
        const btn = document.getElementById('btn-playoff-autosim-toggle');
        if (btn) { btn.innerText = '⏸ Pause'; btn.classList.remove('btn-accent'); btn.classList.add('btn-warning'); }
        playoffAutoSimTimer = setInterval(async () => {
            if (state.stage !== 'playoffs' || state.pending_offer) { stopPlayoffAutoSim(); return; }
            await fetch('/api/simulate_playoff_games', {method: 'POST'});
            await refreshState();
        }, 700);
    }
    function stopPlayoffAutoSim() {
        if (playoffAutoSimTimer) { clearInterval(playoffAutoSimTimer); playoffAutoSimTimer = null; }
        const btn = document.getElementById('btn-playoff-autosim-toggle');
        if (btn) { btn.innerText = '▶ Auto-Sim Series'; btn.classList.remove('btn-warning'); btn.classList.add('btn-accent'); }
    }

    async function simGameFromModal(r, mIdx) {
        await fetch('/api/simulate_playoff_games', {method: 'POST'});
        await refreshState();  // openModal is already set, so this repaints the modal live
    }

    function showSeriesModal(r, mIdx, isRefresh) {
        if (!isRefresh) {
            document.getElementById('player-modal').style.display = 'none';
            document.getElementById('boxscore-modal').style.display = 'none';
            openModal = {type: 'series', r, mIdx};
        }

        const m = state.playoff_bracket[r][mIdx];
        if (!m) { closeModals(); return; }
        document.getElementById('series-header-title').innerText = `${m.team1} vs ${m.team2} (Series: ${m.series[0]}-${m.series[1]})`;

        let html = '<div class="list-group list-group-flush bg-dark border border-secondary rounded">';
        for(let i=0; i<7; i++) {
            if (i < m.games.length) {
                const g = m.games[i];
                html += `<div class="list-group-item bg-dark text-white d-flex justify-content-between align-items-center border-secondary py-3">
                    <span><strong>Game ${i+1}:</strong> ${g.away_team} <span class="text-warning">${g.away_score}</span> @ ${g.home_team} <span class="text-warning">${g.home_score}</span></span>
                    <button class="btn btn-sm btn-info" onclick="showBoxScore('playoff', '${r}_${mIdx}_${i}')">Boxscore</button>
                </div>`;
            } else if (m.winner) {
                break;
            } else {
                html += `<div class="list-group-item bg-dark text-white-50 border-secondary py-3">Game ${i+1}: TBD</div>`;
            }
        }
        html += '</div>';

        if (!m.winner) {
            html += `<button class="btn btn-danger btn-lg w-100 mt-3" onclick="simGameFromModal('${r}', ${mIdx})">⚡ Simulate Next Game (live)</button>`;
        } else {
            html += `<div class="alert alert-success mt-3 mb-0 text-center">Series winner: <b>${m.winner}</b></div>`;
        }

        document.getElementById('series-games-render').innerHTML = html;
        document.getElementById('modal-overlay').style.display = 'block';
        document.getElementById('series-modal').style.display = 'block';
    }

    function showBoxScore(type, identity, isRefresh) {
        if (!isRefresh) {
            document.getElementById('series-modal').style.display = 'none';
            document.getElementById('player-modal').style.display = 'none';
            openModal = {type: 'box', boxType: type, identity};
        }

        let gameObj;
        if(type === 'regular') {
            gameObj = state.regular_season_games[identity];
        } else {
            const parts = identity.split('_');
            gameObj = state.playoff_bracket[parts[0]][parts[1]].games[parts[2]];
        }

        document.getElementById('box-header-title').innerText = `${gameObj.away_team} (${gameObj.away_score}) @ ${gameObj.home_team} (${gameObj.home_score})`;

        let html = `<div class="row">`;

        // --- Quarter-by-quarter score breakdown ---
        if (gameObj.away_quarters && gameObj.home_quarters) {
            const numPeriods = gameObj.away_quarters.length;
            let periodHeaders = '';
            for (let i = 0; i < numPeriods; i++) {
                periodHeaders += `<th>${i < 4 ? 'Q' + (i + 1) : 'OT' + (i - 3)}</th>`;
            }
            html += `<div class="col-12 mb-3">
                <table class="table-dark-custom" style="font-size: 0.8rem; max-width: 480px;">
                    <thead><tr><th>Team</th>${periodHeaders}<th>Final</th></tr></thead>
                    <tbody>
                        <tr><td>${gameObj.away_team}</td>${gameObj.away_quarters.map(q => `<td>${q}</td>`).join('')}<td class="text-warning fw-bold">${gameObj.away_score}</td></tr>
                        <tr><td>${gameObj.home_team}</td>${gameObj.home_quarters.map(q => `<td>${q}</td>`).join('')}<td class="text-warning fw-bold">${gameObj.home_score}</td></tr>
                    </tbody>
                </table>
            </div>`;
        }

        // Sort each team's box score by points scored, highest first (matches how
        // real box scores and every other stats table in the app are ordered).
        const awayRows = Object.entries(gameObj.away_stats).sort((a, b) => b[1].PTS - a[1].PTS);
        const homeRows = Object.entries(gameObj.home_stats).sort((a, b) => b[1].PTS - a[1].PTS);

        html += `<div class="col-12 col-xl-6 mb-3">
            <h5 class="text-info">${gameObj.away_team} (Away)</h5>
            <table class="table-dark-custom" style="font-size: 0.8rem;">
                <thead><tr><th>Player</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>TOV</th><th>FGM</th><th>FGA</th><th>3PM</th><th>3PA</th></tr></thead><tbody>`;
        awayRows.forEach(([name, st]) => {
            html += `<tr><td><a class="player-link" onclick="showPlayerModal('${name}')">${name}</a></td><td>${st.PTS}</td><td>${st.REB}</td><td>${st.AST}</td><td>${st.STL}</td><td>${st.BLK}</td><td>${st.TOV||0}</td><td>${st.FGM}</td><td>${st.FGA}</td><td>${st['3PM']}</td><td>${st['3PA']}</td></tr>`;
        });
        html += `</tbody></table></div>`;

        html += `<div class="col-12 col-xl-6 mb-3">
            <h5 class="text-warning">${gameObj.home_team} (Home)</h5>
            <table class="table-dark-custom" style="font-size: 0.8rem;">
                <thead><tr><th>Player</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>TOV</th><th>FGM</th><th>FGA</th><th>3PM</th><th>3PA</th></tr></thead><tbody>`;
        homeRows.forEach(([name, st]) => {
            html += `<tr><td><a class="player-link" onclick="showPlayerModal('${name}')">${name}</a></td><td>${st.PTS}</td><td>${st.REB}</td><td>${st.AST}</td><td>${st.STL}</td><td>${st.BLK}</td><td>${st.TOV||0}</td><td>${st.FGM}</td><td>${st.FGA}</td><td>${st['3PM']}</td><td>${st['3PA']}</td></tr>`;
        });
        html += `</tbody></table></div></div>`;

        document.getElementById('boxscore-stats-render').innerHTML = html;
        document.getElementById('modal-overlay').style.display = 'block';
        document.getElementById('boxscore-modal').style.display = 'block';
    }
    window.showBoxScore = showBoxScore;

    function attrColor(v) {
        if (v >= 90) return '#10b981';
        if (v >= 80) return '#38bdf8';
        if (v >= 70) return '#fbbf24';
        if (v >= 60) return '#fb923c';
        return '#f87171';
    }

    let pmActiveTab = 'overview';

    async function editJerseyNumber(name, current) {
        const val = prompt(`New jersey number for ${name} (0-99):`, current);
        if (val === null) return;
        const res = await fetch('/api/set_jersey_number', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name, number: val})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        showPlayerModal(name, true);
    }
    window.editJerseyNumber = editJerseyNumber;

    async function editNickname(name, current) {
        const val = prompt(`Nickname for ${name} (leave blank to remove):`, current || '');
        if (val === null) return;
        const res = await fetch('/api/set_player_nickname', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name, nickname: val})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        showPlayerModal(name, true);
    }
    window.editNickname = editNickname;

    async function openExtensionPrompt(name, currentSalary) {
        const years = prompt(`Extension length in years (1-5) for ${name}:`, "3");
        if (years === null) return;
        const salary = prompt(`Salary per year ($M) to offer ${name} (current: $${currentSalary}M):`, currentSalary);
        if (salary === null) return;
        const res = await fetch('/api/offer_extension', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name, years, salary})});
        const data = await res.json();
        showToast(data.reason || (data.accepted ? 'Extension accepted!' : 'Extension rejected.'), data.accepted ? 'success' : 'error');
        if (data.success) { await refreshState(); showPlayerModal(name, true); }
    }
    window.openExtensionPrompt = openExtensionPrompt;

    // UPGRADE: fixed player comparison. Opens a real modal with two
    // searchable dropdowns (every rostered player, sorted by team then
    // name) instead of a prompt() that demanded an exact name match and a
    // window.open() popup that most browsers silently blocked.
    function openComparePrompt(name) {
        document.getElementById('player-modal').style.display = 'none';
        const allPlayers = Object.values(state.players)
            .sort((a, b) => (a.retired === b.retired ? 0 : a.retired ? 1 : -1) || (a.team || '').localeCompare(b.team || '') || a.name.localeCompare(b.name));
        const optsHtml = allPlayers.map(p => `<option value="${p.name}">${p.name} — ${p.retired ? 'Retired' : (p.team || 'FA')} (${p.rating} OVR)</option>`).join('');
        const selA = document.getElementById('compare-select-a');
        const selB = document.getElementById('compare-select-b');
        selA.innerHTML = optsHtml;
        selB.innerHTML = optsHtml;
        if (name) selA.value = name;
        // Default Player B to a sensible different player so the modal
        // isn't blank on first open.
        const other = allPlayers.find(p => p.name !== name);
        if (other) selB.value = other.name;
        document.getElementById('modal-overlay').style.display = 'block';
        document.getElementById('compare-modal').style.display = 'block';
        openModal = {type: 'compare'};
        runPlayerCompare();
    }
    window.openComparePrompt = openComparePrompt;

    // ─── RADAR CHART ──────────────────────────────────────────────────────────
    function buildRadarChart(labels, valsA, valsB, colorA, colorB, nameA, nameB) {
        const cx = 130, cy = 130, R = 100, n = labels.length;
        const angle = i => (Math.PI * 2 * i / n) - Math.PI / 2;
        const pt = (val, i) => {
            const r = (val / 99) * R;
            return [cx + r * Math.cos(angle(i)), cy + r * Math.sin(angle(i))];
        };
        // Grid rings
        let svg = `<svg viewBox="0 0 260 260" width="100%" style="max-width:260px;display:block;margin:0 auto;">`;
        [25, 50, 75, 99].forEach(pct => {
            const pts = labels.map((_, i) => pt(pct, i).join(',')).join(' ');
            svg += `<polygon points="${pts}" fill="none" stroke="#334155" stroke-width="0.8"/>`;
        });
        // Axis lines
        labels.forEach((_, i) => {
            const [x, y] = pt(99, i);
            svg += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#334155" stroke-width="0.8"/>`;
        });
        // Polygon A
        const ptsA = valsA.map((v, i) => pt(v, i).join(',')).join(' ');
        svg += `<polygon points="${ptsA}" fill="${colorA}" fill-opacity="0.25" stroke="${colorA}" stroke-width="2"/>`;
        // Polygon B
        const ptsB = valsB.map((v, i) => pt(v, i).join(',')).join(' ');
        svg += `<polygon points="${ptsB}" fill="${colorB}" fill-opacity="0.20" stroke="${colorB}" stroke-width="2" stroke-dasharray="4,2"/>`;
        // Labels
        labels.forEach((lbl, i) => {
            const [x, y] = pt(115, i);
            svg += `<text x="${x}" y="${y}" fill="#9db4d9" font-size="9" text-anchor="middle" dominant-baseline="middle">${lbl}</text>`;
        });
        svg += `</svg>`;
        return svg;
    }

    let comparePlayerSeq = 0;
    async function runPlayerCompare() {
        const a = document.getElementById('compare-select-a').value;
        const b = document.getElementById('compare-select-b').value;
        const render = document.getElementById('compare-render');
        if (!a || !b) { render.innerHTML = ''; return; }
        if (a === b) { render.innerHTML = `<p class="text-warning small">Pick two different players.</p>`; return; }
        // Same overlap guard as Team Intel: if the dropdowns get changed again
        // before this fetch lands, don't let a stale response overwrite a
        // fresher one (or throw trying to write into elements a newer call
        // already replaced).
        const mySeq = ++comparePlayerSeq;
        let data;
        try {
            const res = await fetch(`/api/compare_players?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
            data = await res.json();
        } catch (e) {
            if (mySeq !== comparePlayerSeq) return;
            render.innerHTML = `<p class="text-danger small">Couldn't load that comparison (${e.message}). <button class="btn btn-sm btn-outline-accent ms-2" onclick="runPlayerCompare()">Retry</button></p>`;
            return;
        }
        if (mySeq !== comparePlayerSeq) return;
        if (!data.success) { render.innerHTML = `<p class="text-danger small">${data.reason}</p>`; return; }

        // Wrap the actual HTML-building step too -- a malformed/partial
        // player record (e.g. a legend missing some attribute keys) used to
        // throw here and leave the panel on its last state with no
        // indication anything went wrong. Now it fails visibly with a retry
        // instead of silently.
        try {
        const A = data.a, B = data.b;
        const fmtH = in_ => in_ ? `${Math.floor(in_/12)}'${in_%12}"` : '—';
        const better = (av, bv, hi=true) => {
            if (av === bv || av === '—' || bv === '—') return ['',''];
            const aw = hi ? parseFloat(av) > parseFloat(bv) : parseFloat(av) < parseFloat(bv);
            return aw ? ['text-success fw-bold','text-white-50'] : ['text-white-50','text-success fw-bold'];
        };
        const row = (label, av, bv, hi=true) => {
            const [ac,bc] = better(av, bv, hi);
            return `<tr><td class="${ac}">${av}</td><td class="text-white-50 small text-center">${label}</td><td class="${bc} text-end">${bv}</td></tr>`;
        };

        // Header with silhouettes
        const colorA = teamColor(A.team || 'Free Agent'), colorB = teamColor(B.team || 'Free Agent');
        let html = `
        <div class="row text-center mb-3">
            <div class="col-5">
                <div class="d-flex justify-content-center mb-1">${playerSilhouetteSvg(A.name, A.position, colorA, 56)}</div>
                <a class="player-link fw-bold" onclick="showPlayerModal('${A.name.replace(/'/g,"\\'")}')">${A.name}</a>
                <div class="small text-white-50">${A.team||'FA'} · ${A.position}${A.secondary_position?'/'+A.secondary_position:''}</div>
                <div class="small text-info">${getPlayerArchetype(A)}</div>
                <div class="small" style="color:${getPeakColor(A.age,A.position)}">${getPeakLabel(A.age,A.position)}</div>
            </div>
            <div class="col-2 d-flex align-items-center justify-content-center text-white-50 fw-bold">VS</div>
            <div class="col-5">
                <div class="d-flex justify-content-center mb-1">${playerSilhouetteSvg(B.name, B.position, colorB, 56)}</div>
                <a class="player-link fw-bold" onclick="showPlayerModal('${B.name.replace(/'/g,"\\'")}')">${B.name}</a>
                <div class="small text-white-50">${B.team||'FA'} · ${B.position}${B.secondary_position?'/'+B.secondary_position:''}</div>
                <div class="small text-info">${getPlayerArchetype(B)}</div>
                <div class="small" style="color:${getPeakColor(B.age,B.position)}">${getPeakLabel(B.age,B.position)}</div>
            </div>
        </div>

        <!-- Physicals prominently at top -->
        <div class="row text-center stat-subpanel mb-3">
            <div class="col-2 text-end"><div class="fw-bold text-white">${fmtH(A.height_in)}</div><div class="fw-bold text-white">${A.weight_lbs?A.weight_lbs+' lbs':'—'}</div><div class="fw-bold text-white">${fmtH(A.wingspan_in)}</div></div>
            <div class="col-8 text-center"><div class="small text-white-50">HEIGHT</div><div class="small text-white-50">WEIGHT</div><div class="small text-white-50">WINGSPAN</div></div>
            <div class="col-2 text-start"><div class="fw-bold text-white">${fmtH(B.height_in)}</div><div class="fw-bold text-white">${B.weight_lbs?B.weight_lbs+' lbs':'—'}</div><div class="fw-bold text-white">${fmtH(B.wingspan_in)}</div></div>
        </div>

        <table class="table-dark-custom mb-3"><tbody>
            ${row('OVR', A.rating, B.rating)}
            ${row('Potential', A.potential_grade, B.potential_grade)}
            ${row('Age', A.age, B.age, false)}
            ${row('PPG', A.ppg, B.ppg)}
            ${row('RPG', A.rpg, B.rpg)}
            ${row('APG', A.apg, B.apg)}
            ${row('SPG', A.spg, B.spg)}
            ${row('BPG', A.bpg, B.bpg)}
            ${row('Salary $M', A.salary??'—', B.salary??'—', false)}
        </tbody></table>`;

        // Radar chart for key attributes
        const radarAttrs = ['Athleticism','Defense','Three-Point','Finishing','Vision','Rebounding'];
        const radarAvals = radarAttrs.map(k => (A.attributes||{})[k] || 50);
        const radarBvals = radarAttrs.map(k => (B.attributes||{})[k] || 50);
        html += `<h6 class="text-white-50 mb-2">📊 Attribute Radar</h6>`;
        html += buildRadarChart(radarAttrs, radarAvals, radarBvals, colorA, colorB, A.name, B.name);
        html += `<div class="d-flex gap-3 small mb-3"><span style="color:${colorA};">■ ${A.name}</span><span style="color:${colorB};">■ ${B.name}</span></div>`;

        // Attributes table
        const attrKeys = Object.keys(A.attributes||{}).filter(k => k in (B.attributes||{})).sort();
        if (attrKeys.length) {
            html += `<h6 class="text-white-50 mb-2">⚙ Attributes</h6><table class="table-dark-custom mb-3"><tbody>`;
            attrKeys.forEach(k => { html += row(k, Math.round(A.attributes[k]), Math.round(B.attributes[k])); });
            html += `</tbody></table>`;
        }

        // Badges side by side
        // BUGFIX: this read the stored `player.badges` field, which is only
        // ever written by a handful of backend code paths (roster creation,
        // post-training, etc.) and stays empty/stale for players who never
        // pass through one of those -- e.g. every Hall of Fame / league
        // history legend, and any player whose attributes changed some other
        // way. The player detail modal already computes badges live from
        // attributes via computePlayerBadges()/badgeChipsHtml(), so reuse
        // that here instead of trusting the stored field.
        const badgeBlock = (player) => badgeChipsHtml(player);
        html += `<h6 class="text-white-50 mb-2">🏅 Badges</h6>
        <div class="row mb-3">
            <div class="col-6">${badgeBlock(A)}</div>
            <div class="col-6">${badgeBlock(B)}</div>
        </div>`;

        // Awards
        const awardsBlock = (player) => (player.career_awards||[]).length
            ? player.career_awards.slice(-5).map(aw=>`<div class="small text-white-50">${aw.year}: ${aw.award}</div>`).join('')
            : '<span class="text-white-50 small">None yet</span>';
        html += `<h6 class="text-white-50 mb-2">🏆 Career Awards</h6>
        <div class="row"><div class="col-6">${awardsBlock(A)}</div><div class="col-6">${awardsBlock(B)}</div></div>`;

        render.innerHTML = html;
        } catch (e) {
            if (mySeq !== comparePlayerSeq) return;
            render.innerHTML = `<p class="text-danger small">Something went wrong rendering that comparison (${e.message}). <button class="btn btn-sm btn-outline-accent ms-2" onclick="runPlayerCompare()">Retry</button></p>`;
        }
    }
    window.runPlayerCompare = runPlayerCompare;

    // ─── PLAYER ARCHETYPES ─────────────────────────────────────────────────────
    // Computed from attribute sheet — gives every player a meaningful role label
    // beyond just "87 OVR". Mirrors NBA 2K's build system.
    function getPlayerArchetype(p) {
        const a = p.attributes || {};
        const pos = p.position || 'SF';
        const threeP = a['Three-Point'] || 0;
        const athl   = a['Athleticism'] || 0;
        const vis    = a['Vision'] || 0;
        const post   = a['Post-Up'] || 0;
        const def    = a['Defense'] || 0;
        const reb    = a['Rebounding'] || 0;
        const drib   = a['Ball Handling'] || a['Dribbling'] || 0;
        const spd    = a['Speed'] || 0;
        const iq     = a['Shot IQ'] || a['IQ'] || 0;
        const fin    = a['Finishing'] || a['Layup'] || 0;

        if (pos === 'C' || pos === 'PF') {
            if (reb >= 80 && def >= 75) return 'Glass-Cleaning Center';
            if (threeP >= 72) return 'Stretch Four';
            if (post >= 78) return 'Paint Beast';
            return 'Traditional Big';
        }
        if (pos === 'PG') {
            if (vis >= 78 && drib >= 78) return 'Floor General';
            if (threeP >= 74 && drib >= 74) return 'Playmaking Shot Creator';
            if (spd >= 80 && fin >= 75) return 'Athletic Finisher';
            return 'Pure Point Guard';
        }
        // SG / SF
        if (threeP >= 78 && def >= 72) return '3&D Wing';
        if (athl >= 78 && fin >= 75) return 'Slasher';
        if (def >= 80 && athl >= 75) return '2-Way Defender';
        if (iq >= 78 && threeP >= 72) return 'Microwave Scorer';
        if (drib >= 76 && threeP >= 74) return 'Playmaking Shot Creator';
        if (fin >= 78 && athl >= 78) return '2-Way Slasher';
        return 'Combo Wing';
    }
    window.getPlayerArchetype = getPlayerArchetype;

    // ─── PEAK AGE SYSTEM ──────────────────────────────────────────────────────
    const PEAK_WINDOWS = { PG:[24,29], SG:[24,30], SF:[25,30], PF:[25,31], C:[26,32] };
    function getPeakLabel(age, pos) {
        const [ps, pe] = PEAK_WINDOWS[pos] || [25, 30];
        if (age <= 20)         return 'Young';
        if (age < ps)          return 'Entering Prime';
        if (age <= pe)         return 'Prime';
        if (age <= pe + 3)     return 'Late Prime';
        if (age <= pe + 6)     return 'Declining';
        return 'Veteran';
    }
    function getPeakColor(age, pos) {
        const lbl = getPeakLabel(age, pos);
        return {Young:'#38bdf8', 'Entering Prime':'#34d399', Prime:'#facc15',
                'Late Prime':'#fb923c', Declining:'#f87171', Veteran:'#9db4d9'}[lbl] || '#e2e8f0';
    }

    // ─── PLAYER APPEARANCE (face/look) ─────────────────────────────────────────
    const HAIR_STYLES  = ['Buzz Cut','Fade','High Top','Dreads','Cornrows','Bald','Afro','Caesar'];
    const BEARD_STYLES = ['Clean Shaven','Stubble','Goatee','Full Beard','Chinstrap','Mustache'];
    const BODY_TYPES   = ['Slim','Athletic','Muscular','Stocky'];
    const SKIN_TONES   = ['Fair','Light','Medium','Brown','Dark','Deep'];

    function seedRand(str) {
        // Deterministic hash so the same player always gets the same look
        let h = 5381;
        for (let i = 0; i < str.length; i++) h = ((h << 5) + h) ^ str.charCodeAt(i);
        return Math.abs(h);
    }
    function getPlayerAppearance(name, position) {
        const h = seedRand(name + position);
        return {
            hair:      HAIR_STYLES[h % HAIR_STYLES.length],
            beard:     BEARD_STYLES[(h >> 3) % BEARD_STYLES.length],
            body:      BODY_TYPES[(h >> 6) % BODY_TYPES.length],
            skin_tone: SKIN_TONES[(h >> 9) % SKIN_TONES.length],
        };
    }

    // Silhouette SVG based on position + body type (renders in the player avatar slot)
    function playerSilhouetteSvg(name, position, color, size) {
        const app = getPlayerAppearance(name, position);
        const bodySizes = { Slim:'M18,62 Q16,58 18,48 Q20,38 24,34 Q28,30 32,34 Q36,38 38,48 Q40,58 38,62 Z',
                            Athletic:'M16,62 Q14,57 16,47 Q18,37 24,32 Q28,28 32,32 Q36,28 40,32 Q46,37 48,47 Q50,57 48,62 Z',
                            Muscular:'M14,62 Q12,56 14,46 Q16,36 22,31 Q27,27 32,31 Q37,27 42,31 Q48,36 50,46 Q52,56 50,62 Z',
                            Stocky:'M13,62 Q11,55 13,45 Q15,35 22,30 Q27,26 32,30 Q37,26 42,30 Q49,35 51,45 Q53,55 51,62 Z' };
        const body = bodySizes[app.body] || bodySizes.Athletic;
        const skinColors = { Fair:'#fde3ca', Light:'#f1c27d', Medium:'#c68642', Brown:'#8d5524', Dark:'#4a2912', Deep:'#2c1503' };
        const skin = skinColors[app.skin_tone] || '#c68642';
        const hairColors = ['#1a1a1a','#3b2314','#4a3728','#2c1a0e','#d4a853','#e8c97e','#7b2d00'];
        const hc = hairColors[seedRand(name) % hairColors.length];
        return `<svg viewBox="0 0 64 72" width="${size}" height="${size}" style="border-radius:50%;background:${color}20;">
            <ellipse cx="32" cy="24" rx="11" ry="13" fill="${skin}"/>
            <path d="${body}" fill="${skin}"/>
            <ellipse cx="32" cy="14" rx="11" ry="5" fill="${hc}" opacity="0.9"/>
            <circle cx="32" cy="7" r="4" fill="${hc}"/>
        </svg>`;
    }

    // UPGRADE: Player Development bar -- current OVR vs their real potential
    // ceiling, so you can see at a glance how much room a young player has
    // left to grow (or that a vet is already there).
    function devProgressHtml(p) {
        if (p.potential == null || p.retired) return '';
        const cur = p.rating, pot = Math.max(p.potential, p.rating);
        const pct = pot > 0 ? Math.round((cur / pot) * 100) : 100;
        const remaining = pot - cur;
        return `<div class="stat-subpanel mb-3">
            <div class="d-flex justify-content-between small text-white-50 mb-1">
                <span>📈 Development</span>
                <span>${cur} OVR → <span class="text-success">${pot} Potential</span>${remaining > 0 ? ` <span class="text-white-50">(+${remaining} left)</span>` : ' <span class="text-warning">(maxed out)</span>'}</span>
            </div>
            <div class="progress" style="height:8px; background:#1f2937;">
                <div class="progress-bar" role="progressbar" style="width:${pct}%; background:${pct >= 95 ? '#10b981' : '#38bdf8'};"></div>
            </div>
        </div>`;
    }

    // UPGRADE: League Average comparison -- a small up/down tag next to a
    // player's per-game stat showing how it stacks up against the league
    // average at a glance, instead of having to go check League Leaders.
    let leagueAvgCache = null;
    function computeLeagueAverages() {
        if (leagueAvgCache && leagueAvgCache.year === state.year) return leagueAvgCache;
        const pool = Object.values(state.players).filter(pl => !pl.retired && pl.stats && pl.stats.GP > 0);
        if (!pool.length) { leagueAvgCache = {year: state.year, PPG: 0, RPG: 0, APG: 0}; return leagueAvgCache; }
        const sum = (key) => pool.reduce((a, pl) => a + (pl.stats[key] / pl.stats.GP), 0);
        leagueAvgCache = {
            year: state.year,
            PPG: sum('PTS') / pool.length,
            RPG: sum('REB') / pool.length,
            APG: sum('AST') / pool.length,
        };
        return leagueAvgCache;
    }
    function leagueAvgTag(stat, value) {
        const avg = computeLeagueAverages()[stat];
        if (!avg || isNaN(value)) return '';
        const diff = value - avg;
        const pct = Math.abs(diff / avg * 100);
        if (pct < 5) return `<div class="small text-white-50">≈ league avg</div>`;
        const up = diff > 0;
        return `<div class="small" style="color:${up ? '#4ade80' : '#f87171'};">${up ? '▲' : '▼'} ${pct.toFixed(0)}% vs avg (${avg.toFixed(1)})</div>`;
    }

    function showPlayerModal(playerName, isRefresh) {
        if (!isRefresh) {
            document.getElementById('boxscore-modal').style.display = 'none';
            document.getElementById('series-modal').style.display = 'none';
            openModal = {type: 'player', name: playerName};
            pmActiveTab = 'overview'; // fresh player -> start on Overview
        }

        const p = getPlayerByName(playerName);
        if (!p) return;
        document.getElementById('pm-name').innerText = '';

        const s = p.stats || {GP:0,PTS:0,REB:0,AST:0,STL:0,BLK:0,FGM:0,FGA:0,'3PM':0,'3PA':0,MIN:0};
        let ppg = '0.0', rpg = '0.0', apg = '0.0', spg = '0.0', bpg = '0.0', fgPct = '0.0', tpPct = '0.0', mpg = '0.0';
        if (s.GP > 0) {
            ppg = (s.PTS / s.GP).toFixed(1);
            rpg = (s.REB / s.GP).toFixed(1);
            apg = (s.AST / s.GP).toFixed(1);
            spg = (s.STL / s.GP).toFixed(1);
            bpg = (s.BLK / s.GP).toFixed(1);
            mpg = ((s.MIN||0) / s.GP).toFixed(1);
            fgPct = s.FGA > 0 ? ((s.FGM / s.FGA) * 100).toFixed(1) : '0.0';
            tpPct = s['3PA'] > 0 ? ((s['3PM'] / s['3PA']) * 100).toFixed(1) : '0.0';
        }

        let attrHtml = '';
        Object.entries(ATTRIBUTE_CATEGORIES).forEach(([cat, attrs]) => {
            attrHtml += `<div class="col-md-6 mb-3"><div class="text-white-50 text-uppercase small fw-bold mb-2" style="letter-spacing:1px;">${cat}</div>`;
            attrs.forEach(a => {
                const v = p.attributes[a];
                attrHtml += `<div class="attr-row"><span class="attr-name">${a}</span><span class="attr-track"><div class="attr-bar-wrap"><div class="attr-bar-fill" style="width:${v}%; background:${attrColor(v)};"></div></div></span><span class="attr-val">${v}</span></div>`;
            });
            attrHtml += `</div>`;
        });

        let tendHtml = '';
        TENDENCY_LIST.forEach(t => {
            const v = p.tendencies[t];
            tendHtml += `<div class="attr-row"><span class="attr-name">${t}</span><span class="attr-track"><div class="attr-bar-wrap"><div class="attr-bar-fill" style="width:${v}%; background:#a78bfa;"></div></div></span><span class="attr-val">${v}</span></div>`;
        });

        const CONTRACT_TYPE_COLORS = {'Rookie Scale':'#38bdf8','Max Contract':'#facc15','Supermax':'#f97316','Standard':'#9db4d9','MLE':'#a78bfa','Veteran Min':'#7d93b8','Two-Way':'#34d399'};
        const ctypeLabel = p.contract && p.contract.contract_type ? p.contract.contract_type : '';
        const ctypeColor = CONTRACT_TYPE_COLORS[ctypeLabel] || '#9db4d9';
        const contractHtml = p.contract
            ? `${p.contract.years_left} yr(s) @ $${p.contract.salary}M${ctypeLabel ? ` <span class="badge" style="background:${ctypeColor}20;color:${ctypeColor};border:1px solid ${ctypeColor}40;font-size:0.6rem;">${ctypeLabel}</span>` : ''}`
            : (p.team ? 'N/A' : 'Unsigned');
        const injHtml = p.injury ? `<span class="badge-injury">🩹 ${p.injury.description} — ${p.injury.games_remaining} games remaining</span>` : `<span class="text-success small">Healthy</span>`;
        const proneHtml = p.injury_prone ? ` <span class="badge bg-danger" style="font-size:0.65rem;" title="${p.injury_history_count || 0} injuries this career">🩹 Injury Prone</span>` : '';
        const ntcHtml = (p.contract && p.contract.no_trade_clause) ? ` <span class="badge bg-warning text-dark" style="font-size:0.65rem;" title="Won't approve a trade">📜 No-Trade Clause</span>` : '';
        const moraleVal = (p.morale !== undefined && p.morale !== null) ? p.morale : 70;
        const moraleTxt = moraleVal >= 80 ? '😀 Happy' : moraleVal >= 55 ? '🙂 Content' : moraleVal >= 35 ? '😕 Unhappy' : '😠 Discontent';
        const moraleColor = moraleVal >= 55 ? 'text-success small' : moraleVal >= 35 ? 'text-warning small' : 'text-danger small';
        const fatigueTxt = Math.round((p.fatigue !== undefined && p.fatigue !== null) ? p.fatigue : 0);
        const ovrColor = attrColor(p.rating);
        const jersey = (p.jersey !== undefined && p.jersey !== null) ? p.jersey : '--';

        let careerHtml = '';
        const seasons = (p.history || []).slice().reverse();
        if (seasons.length === 0) {
            careerHtml = `<p class="text-white-50">No completed seasons on record yet.</p>`;
        } else {
            careerHtml = `<table class="table-dark-custom"><thead><tr><th>Season</th><th>PPG</th><th>RPG</th><th>APG</th></tr></thead><tbody>`;
            seasons.forEach(h => {
                careerHtml += `<tr><td>${h.year}</td><td class="text-warning">${h.PPG}</td><td>${h.RPG}</td><td>${h.APG}</td></tr>`;
            });
            careerHtml += `</tbody></table>`;
        }

        const isMine = p.team === state.user_team;
        const extEligible = isMine && p.contract && !p.two_way && p.contract.years_left >= 1 && p.contract.years_left <= 2;
        const extBtn = extEligible ? `<button class="btn btn-outline-accent" style="padding:2px 10px;font-size:0.72rem;" onclick="openExtensionPrompt('${p.name.replace(/'/g,"\\'")}', ${p.contract.salary})">✍️ Offer Extension</button>` : '';
        const compareBtn = `<button class="btn btn-outline-accent" style="padding:2px 10px;font-size:0.72rem;" onclick="openComparePrompt('${p.name.replace(/'/g,"\\'")}')">⚖ Compare</button>`;
        const isWatched = (state.trade_targets && state.trade_targets[state.user_team] || []).includes(p.name);
        const watchBtn = (!isMine && p.team) ? `<button class="btn ${isWatched ? 'btn-accent' : 'btn-outline-accent'}" style="padding:2px 10px;font-size:0.72rem;" onclick="toggleTradeTargetWatch('${p.name.replace(/'/g,"\\'")}'); showPlayerModal('${p.name.replace(/'/g,"\\'")}');" title="${isWatched ? 'Remove from trade target list' : 'Add to trade target list'}">${isWatched ? '★ Watching' : '☆ Watch'}</button>` : '';

        // UPGRADE: Player nicknames / custom cards. Cosmetic-only, editable
        // by the human GM for their own players, shown under the real name
        // on the card the same way real broadcasts caption a nickname.
        const nicknameHtml = p.nickname
            ? `<div class="small ${isMine ? 'text-info' : 'text-white-50'}" style="${isMine ? 'cursor:pointer;' : ''} font-style:italic;" ${isMine ? `onclick="editNickname('${p.name.replace(/'/g,"\\'")}', '${p.nickname.replace(/'/g,"\\'")}')" title="Click to edit nickname"` : ''}>"${p.nickname}"${isMine ? ' ✎' : ''}</div>`
            : (isMine ? `<div class="small text-white-50" style="cursor:pointer;" onclick="editNickname('${p.name.replace(/'/g,"\\'")}', '')" title="Click to add a nickname">+ Add nickname ✎</div>` : '');

        const headerHtml = `
            <div class="d-flex align-items-center gap-3 mb-3 pb-3 border-bottom border-secondary">
                <div class="player-avatar" style="background:${teamColor(p.team || 'Free Agent')};overflow:hidden;padding:0;">${playerSilhouetteSvg(p.name||'', p.position||'SF', teamColor(p.team||'Free Agent'), 60)}</div>
                <div class="flex-fill">
                    <h4 class="text-white m-0">${p.name}</h4>
                    ${nicknameHtml}
                    <div class="d-flex align-items-center gap-2 mt-1 flex-wrap">
                        <span class="jersey-badge" style="${isMine ? 'cursor:pointer;' : ''}" ${isMine ? `onclick="editJerseyNumber('${p.name.replace(/'/g,"\\'")}', ${p.jersey !== undefined && p.jersey !== null ? p.jersey : 0})" title="Click to change jersey number"` : ''}>#${jersey}${isMine ? ' ✎' : ''}</span>
                        <span class="jersey-badge">${p.position}</span>
                        <span class="jersey-badge">${p.team || 'Free Agent'}</span>
                        <span class="jersey-badge">Age ${p.age}</span>
                        ${p.agent_personality ? `<span class="jersey-badge" title="Negotiating style">${agentEmoji(p.agent_personality)} ${p.agent_personality}</span>` : ''}
                    </div>
                </div>
                <div class="d-flex flex-column gap-1 align-items-end">
                    <div class="ovr-badge" style="border-color:${ovrColor}; color:${ovrColor};">${p.rating}</div>
                    <div class="d-flex gap-1">${extBtn}${compareBtn}${watchBtn}</div>
                </div>
            </div>
            <div class="mb-3 text-center">${injHtml}${proneHtml}${ntcHtml} &nbsp; <span class="text-white-50 small">Contract: ${contractHtml}</span> &nbsp; <span class="text-success small">Potential: ${p.potential_grade}</span> &nbsp; <span class="${moraleColor}">${moraleTxt}</span> &nbsp; <span class="text-white-50 small">Fatigue: ${fatigueTxt}%</span></div>
            <div class="d-flex border-bottom border-secondary mb-3">
                <button class="pm-tab-btn active" id="pmtab-overview-btn" onclick="switchPlayerModalTab('overview')">Overview</button>
                <button class="pm-tab-btn" id="pmtab-attributes-btn" onclick="switchPlayerModalTab('attributes')">Attributes</button>
                <button class="pm-tab-btn" id="pmtab-career-btn" onclick="switchPlayerModalTab('career')">Career Stats</button>
            </div>
        `;

        const playerBadges = computePlayerBadges(p);
        const badgesFullHtml = playerBadges.length === 0
            ? `<p class="text-white-50 small">No badges earned yet — attributes need to hit at least Bronze level (68+) in a badge's core skills.</p>`
            : `<div class="row g-2">` + playerBadges.map(b => `
                <div class="col-12 col-md-6">
                    <div class="p-2 rounded" style="border:1px solid ${b.color}; background:rgba(255,255,255,0.03);">
                        <div class="d-flex justify-content-between align-items-center">
                            <span style="color:${b.color}; font-weight:600;">${b.icon} ${b.name}</span>
                            <span class="badge" style="background:${b.color}; color:#111;">${b.tier}</span>
                        </div>
                        <div class="text-white-50" style="font-size:0.75rem; margin-top:2px;">${b.desc}</div>
                    </div>
                </div>`).join('') + `</div>`;

        const fmtH = in_ => in_ ? `${Math.floor(in_/12)}'${in_%12}"` : '—';
        const physHtml = `
            <div class="row text-center mb-3 pb-3 border-bottom border-secondary">
                <div class="col-4">
                    <div class="text-white fw-bold" style="font-size:1.15rem;">${fmtH(p.height_in)}</div>
                    <div class="small text-white-50">HEIGHT</div>
                </div>
                <div class="col-4">
                    <div class="text-white fw-bold" style="font-size:1.15rem;">${p.weight_lbs ? p.weight_lbs + ' lbs' : '—'}</div>
                    <div class="small text-white-50">WEIGHT</div>
                </div>
                <div class="col-4">
                    <div class="text-white fw-bold" style="font-size:1.15rem;">${fmtH(p.wingspan_in)}</div>
                    <div class="small text-white-50">WINGSPAN</div>
                </div>
            </div>
            <div class="row text-center mb-3 pb-3 border-bottom border-secondary">
                <div class="col-3"><div class="small text-white-50">AGE</div><div class="fw-bold text-white">${p.age}</div></div>
                <div class="col-3"><div class="small text-white-50">POSITION</div><div class="fw-bold text-white">${p.position}${p.secondary_position ? '/' + p.secondary_position : ''}</div></div>
                <div class="col-3"><div class="small text-white-50">ARCHETYPE</div><div class="fw-bold text-info" style="font-size:0.8rem;">${getPlayerArchetype(p)}</div></div>
                <div class="col-3"><div class="small text-white-50">STAGE</div><div class="fw-bold" style="font-size:0.8rem;color:${getPeakColor(p.age, p.position)};">${getPeakLabel(p.age, p.position)}</div></div>
            </div>`;

        const app = getPlayerAppearance(p.name, p.position);
        const appearanceHtml = `
            <div class="row text-center stat-subpanel mb-3">
                <div class="col-3"><div class="small text-white-50">HAIR</div><div class="small text-white fw-bold">${app.hair}</div></div>
                <div class="col-3"><div class="small text-white-50">BEARD</div><div class="small text-white fw-bold">${app.beard}</div></div>
                <div class="col-3"><div class="small text-white-50">BODY</div><div class="small text-white fw-bold">${app.body}</div></div>
                <div class="col-3"><div class="small text-white-50">SKIN</div><div class="small text-white fw-bold">${app.skin_tone}</div></div>
            </div>`;

        const overviewHtml = physHtml + appearanceHtml + devProgressHtml(p) + `
            <h5 class="border-bottom border-secondary pb-2 mb-3 text-white-50">${state.year} Season Averages</h5>
            <div class="row text-center">
                <div class="col-3"><h3 class="text-warning">${ppg}</h3><small>PPG</small>${leagueAvgTag('PPG', parseFloat(ppg))}</div>
                <div class="col-3"><h3 class="text-warning">${rpg}</h3><small>RPG</small>${leagueAvgTag('RPG', parseFloat(rpg))}</div>
                <div class="col-3"><h3 class="text-warning">${apg}</h3><small>APG</small>${leagueAvgTag('APG', parseFloat(apg))}</div>
                <div class="col-3"><h3 class="text-white">${mpg}</h3><small>MPG</small></div>
            </div>
            <div class="row text-center mt-3">
                <div class="col-3"><h4 class="text-white">${spg}</h4><small>STL</small></div>
                <div class="col-3"><h4 class="text-white">${bpg}</h4><small>BLK</small></div>
                <div class="col-3"><h4 class="text-success">${fgPct}%</h4><small>FG%</small></div>
                <div class="col-3"><h4 class="text-success">${tpPct}%</h4><small>3PT%</small></div>
            </div>
            <h5 class="border-bottom border-secondary pb-2 mb-3 mt-4 text-white-50">🏅 Badges <small class="text-white-50">(Bronze → Silver → Gold → Hall of Fame)</small></h5>
            ${badgesFullHtml}
        `;
        const attributesHtml = `
            <h5 class="border-bottom border-secondary pb-2 mb-3 text-white-50">Attributes</h5>
            <div class="row">${attrHtml}</div>
            <h5 class="border-bottom border-secondary pb-2 mb-3 mt-4 text-white-50">Tendencies</h5>
            <div class="mb-2">${tendHtml}</div>
        `;
        // Career totals are an estimate for backfilled/past seasons (only
        // per-game averages are stored historically, not exact games played),
        // using a reasonable ~70-game season assumption; the current season's
        // totals are exact from live box scores.
        let careerPTS = p.stats.PTS, careerREB = p.stats.REB, careerAST = p.stats.AST, careerGP = p.stats.GP;
        seasons.forEach(h => {
            careerPTS += Math.round(h.PPG * 70);
            careerREB += Math.round(h.RPG * 70);
            careerAST += Math.round(h.APG * 70);
            careerGP += 70;
        });
        const careerTotalsHtml = seasons.length === 0 ? '' : `
            <div class="row text-center mb-4">
                <div class="col-3"><h4 class="text-white">${careerGP}</h4><small class="text-white-50">Career GP</small></div>
                <div class="col-3"><h4 class="text-warning">${careerPTS.toLocaleString()}</h4><small class="text-white-50">Career PTS</small></div>
                <div class="col-3"><h4 class="text-white">${careerREB.toLocaleString()}</h4><small class="text-white-50">Career REB</small></div>
                <div class="col-3"><h4 class="text-white">${careerAST.toLocaleString()}</h4><small class="text-white-50">Career AST</small></div>
            </div>
        `;

        // UPGRADE: Milestone Watch -- flags round-number career milestones a
        // player is closing in on, the same "X away from Y" framing real
        // broadcasts use during a season.
        const milestoneHtml = (() => {
            if (!p.team || p.retired) return '';
            const targets = [
                {stat: 'PTS', val: careerPTS, marks: [1000, 5000, 10000, 15000, 20000, 25000, 30000], label: 'points'},
                {stat: 'REB', val: careerREB, marks: [500, 1000, 5000, 10000], label: 'rebounds'},
                {stat: 'AST', val: careerAST, marks: [500, 1000, 5000, 10000], label: 'assists'},
            ];
            const near = [];
            targets.forEach(t => {
                const next = t.marks.find(m => m > t.val);
                if (next && (next - t.val) <= Math.max(500, next * 0.1)) near.push(`${(next - t.val).toLocaleString()} ${t.label} from ${next.toLocaleString()}`);
            });
            if (!near.length) return '';
            return `<div class="stat-subpanel mb-3"><div class="small text-warning fw-bold mb-1">🎯 Milestone Watch</div>
                <div class="small text-white-50">${near.join(' &nbsp;•&nbsp; ')}</div></div>`;
        })();

        const awardsList = (p.career_awards || []).slice().sort((a, b) => b.year - a.year);
        let awardsHtml;
        if (awardsList.length === 0) {
            awardsHtml = `<p class="text-white-50 small">No awards or accolades yet.</p>`;
        } else {
            const counts = {};
            awardsList.forEach(a => counts[a.award] = (counts[a.award] || 0) + 1);
            const summary = Object.entries(counts).map(([name, c]) => `${c > 1 ? c + 'x ' : ''}${name}`).join(' &nbsp;•&nbsp; ');
            awardsHtml = `<div class="mb-2 text-warning small fw-bold">${summary}</div>` +
                `<ul class="list-unstyled small text-white-50 mb-0">` +
                awardsList.map(a => `<li>${a.year} — ${a.award}</li>`).join('') +
                `</ul>`;
        }

        // UPGRADE: Player personality trait and career timeline
        const trait = p.personality_trait || 'Professional';
        const traitCfg = {'Leader':'👑','Gym Rat':'🏋','Mentor':'📚','Clutch':'🎯',
                          'Locker Room Cancer':'☠','Emotional':'🌋','Professional':'💼','Lazy':'😴'};
        const traitEmoji = traitCfg[trait] || '💼';
        const traitHtml = `<div class="stat-subpanel mb-3 d-flex align-items-center gap-2">
            <span style="font-size:1.4rem;">${traitEmoji}</span>
            <div><div class="fw-bold text-white">${trait}</div><div class="small text-white-50">Player Personality</div></div>
        </div>`;

        const timeline = (p.timeline || []).sort((a,b) => a.year - b.year);
        const timelineHtml = timeline.length ? `
            <h5 class="border-bottom border-secondary pb-2 mb-3 text-white-50">📅 Career Timeline</h5>
            <div class="d-flex flex-column gap-1 mb-4" style="border-left:2px solid #334155;padding-left:12px;">
                ${timeline.map(t => `<div class="d-flex align-items-center gap-2 small">
                    <span style="font-size:1rem;">${t.icon}</span>
                    <span class="text-white-50">${t.year}</span>
                    <span class="text-white">${t.event}</span>
                </div>`).join('')}
            </div>` : '';

        const careerFullHtml = `
            ${traitHtml}
            ${timelineHtml}
            <h5 class="border-bottom border-secondary pb-2 mb-3 text-white-50">Career Totals</h5>
            ${careerTotalsHtml || '<p class="text-white-50 small">Career totals build up once a season is completed.</p>'}
            ${milestoneHtml}
            <h5 class="border-bottom border-secondary pb-2 mb-3 text-white-50">🏆 Awards &amp; Accolades</h5>
            <div class="mb-4">${awardsHtml}</div>
            <h5 class="border-bottom border-secondary pb-2 mb-3 text-white-50">Season-by-Season</h5>
            ${careerHtml}
        `;

        document.getElementById('player-stats-render').innerHTML =
            headerHtml +
            `<div id="pmtab-overview">${overviewHtml}</div>` +
            `<div id="pmtab-attributes" style="display:none;">${attributesHtml}</div>` +
            `<div id="pmtab-career" style="display:none;">${careerFullHtml}</div>`;

        // Re-apply whichever sub-tab (Overview/Attributes/Career) was active before
        // this rebuild -- previously this always snapped back to Overview every
        // 2 seconds because of the periodic background refresh.
        switchPlayerModalTab(pmActiveTab);

        document.getElementById('modal-overlay').style.display = 'block';
        document.getElementById('player-modal').style.display = 'block';
    }

    function switchPlayerModalTab(tab) {
        pmActiveTab = tab;
        ['overview', 'attributes', 'career'].forEach(t => {
            document.getElementById(`pmtab-${t}`).style.display = (t === tab) ? 'block' : 'none';
            document.getElementById(`pmtab-${t}-btn`).classList.toggle('active', t === tab);
        });
    }

    function closeModals() {
        document.getElementById('modal-overlay').style.display = 'none';
        document.getElementById('boxscore-modal').style.display = 'none';
        document.getElementById('player-modal').style.display = 'none';
        document.getElementById('series-modal').style.display = 'none';
        document.getElementById('game-options-modal').style.display = 'none';
        document.getElementById('coach-modal').style.display = 'none';
        document.getElementById('shortcuts-modal').style.display = 'none';
        document.getElementById('compare-modal').style.display = 'none';
        document.getElementById('press-conf-modal').style.display = 'none';
        document.getElementById('save-load-modal').style.display = 'none';
        openModal = null;
    }

    // UPGRADE: Clickable coach profiles. Mirrors showPlayerModal -- click any
    // coach's name anywhere in the UI to see their career resume (system,
    // career W-L, championships, seasons, and every team they've been on
    // staff for), sourced from the server-side coach_career ledger.
    function showCoachModal(coachName, isRefresh) {
        if (!isRefresh) {
            document.getElementById('boxscore-modal').style.display = 'none';
            document.getElementById('player-modal').style.display = 'none';
            document.getElementById('series-modal').style.display = 'none';
            openModal = {type: 'coach', name: coachName};
        }
        const career = (state.coach_career || {})[coachName];
        // Find which team (if any) currently employs this coach, and pull
        // their live system/scheme + years-with-team from the coaches map.
        let currentTeam = null, current = null;
        Object.entries(state.coaches || {}).forEach(([team, c]) => {
            if (c && c.name === coachName) { currentTeam = team; current = c; }
        });
        document.getElementById('cm-name').innerText = coachName;

        const system = (current && current.system) || (career && career.system) || 'Unknown System';
        const totalWins = career ? career.total_wins : 0;
        const totalLosses = career ? career.total_losses : 0;
        const totalGames = totalWins + totalLosses;
        const winPct = totalGames > 0 ? (totalWins / totalGames * 100).toFixed(1) : '0.0';
        const rings = career ? career.championships : 0;
        const seasonsCoached = career ? career.seasons.length : 0;
        const teamsList = (career && career.teams_coached && career.teams_coached.length)
            ? career.teams_coached.join(', ')
            : (currentTeam || '—');

        let html = `
            <div class="d-flex align-items-center gap-3 mb-3 pb-3 border-bottom border-secondary">
                <div class="player-avatar" style="background:${teamColor(currentTeam || 'Free Agent')};">${coachName.split(' ').map(w=>w[0]).join('').slice(0,2)}</div>
                <div class="flex-fill">
                    <div class="d-flex align-items-center gap-2 mt-1 flex-wrap">
                        <span class="jersey-badge">${system}</span>
                        <span class="jersey-badge">${currentTeam ? currentTeam : 'Unemployed'}</span>
                        ${rings > 0 ? `<span class="jersey-badge" style="color:#facc15;">🏆 x${rings}</span>` : ''}
                    </div>
                    <div class="small text-white-50 mt-1">${COACH_SYSTEM_DESCS[system] || ''}</div>
                </div>
            </div>
            <div class="row text-center mb-3">
                <div class="col-3"><div class="text-warning fw-bold" style="font-size:1.3rem;">${totalWins}</div><div class="small text-white-50">Career W</div></div>
                <div class="col-3"><div class="text-danger fw-bold" style="font-size:1.3rem;">${totalLosses}</div><div class="small text-white-50">Career L</div></div>
                <div class="col-3"><div class="text-info fw-bold" style="font-size:1.3rem;">${winPct}%</div><div class="small text-white-50">Win %</div></div>
                <div class="col-3"><div class="text-white fw-bold" style="font-size:1.3rem;">${seasonsCoached}</div><div class="small text-white-50">Seasons</div></div>
            </div>
            <div class="small text-white-50 mb-3">Teams coached: <span class="text-white">${teamsList}</span></div>
            <h6 class="text-white-50 mt-3">Season-by-Season</h6>`;

        if (!career || !career.seasons.length) {
            html += `<p class="text-white-50">No completed seasons on record yet.</p>`;
        } else {
            html += `<table class="table-dark-custom"><thead><tr><th>Year</th><th>Team</th><th>Record</th><th>Result</th></tr></thead><tbody>`;
            career.seasons.slice().reverse().forEach(s => {
                html += `<tr><td>${s.year}</td><td>${s.team}</td><td>${s.wins}-${s.losses}</td><td>${s.champion ? '🏆 Champion' : ''}</td></tr>`;
            });
            html += `</tbody></table>`;
        }

        document.getElementById('coach-stats-render').innerHTML = html;
        document.getElementById('modal-overlay').style.display = 'block';
        document.getElementById('coach-modal').style.display = 'block';
    }
    window.showCoachModal = showCoachModal;