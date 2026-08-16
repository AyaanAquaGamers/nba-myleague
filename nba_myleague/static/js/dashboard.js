// ==========================================================
// HOME DASHBOARD + TOAST NOTIFICATIONS + GLOBAL SEARCH + RECENTLY VIEWED
// A self-contained upgrade pass: none of this existed before. Reuses the
// existing `state` global, teamColor()/teamInitials() helpers, and
// showPlayerModal()/showTeamTrackerDetail() from app-core.js rather than
// duplicating logic.
// ==========================================================

// ---------------- TOAST NOTIFICATIONS ----------------
// Lightweight, non-blocking replacement for alert() on action feedback.
// Several places in the app still use alert() for hard validation errors
// (fine to leave -- those need to actually stop the user), but success/info
// feedback now has a much less jarring option available: showToast(...).
function showToast(message, kind) {
    const stack = document.getElementById('toast-stack');
    if (!stack) return;
    const el = document.createElement('div');
    el.className = `app-toast ${kind || ''}`;
    el.innerText = message;
    stack.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => {
        el.classList.remove('show');
        setTimeout(() => el.remove(), 250);
    }, 3200);
}
window.showToast = showToast;

// ---------------- RECENTLY VIEWED PLAYERS ----------------
// In-memory (not persisted -- resets on refresh, same as everything else
// client-side here) list of the last few players opened via showPlayerModal.
let RECENT_PLAYERS = [];
function trackRecentPlayer(name) {
    if (!name) return;
    RECENT_PLAYERS = [name, ...RECENT_PLAYERS.filter(n => n !== name)].slice(0, 8);
    renderRecentPlayersStrip();
}
window.trackRecentPlayer = trackRecentPlayer;

function renderRecentPlayersStrip() {
    const el = document.getElementById('recent-players-strip');
    if (!el) return;
    if (!RECENT_PLAYERS.length) {
        el.innerHTML = '<span class="hub-result-empty">Players you look up will show up here for quick access.</span>';
        return;
    }
    el.innerHTML = RECENT_PLAYERS.map(name => {
        const p = state.players && state.players[name];
        const ovr = p ? p.rating : '--';
        return `<div class="recent-player-chip" onclick="showPlayerModal('${name.replace(/'/g, "\\'")}')">${hubEscape(name)} <span style="color:#facc15;">${hubEscape(ovr)}</span></div>`;
    }).join('');
}

// Hook into the existing showPlayerModal without editing its body: wrap it
// once DOM is ready so every existing call site (dozens across the app)
// automatically starts feeding the recently-viewed list for free.
document.addEventListener('DOMContentLoaded', () => {
    if (typeof window.showPlayerModal === 'function' && !window.__showPlayerModalWrapped) {
        const original = window.showPlayerModal;
        window.showPlayerModal = function (name, isRefresh) {
            if (!isRefresh) trackRecentPlayer(name);
            return original(name, isRefresh);
        };
        window.__showPlayerModalWrapped = true;
    }
});

// ---------------- GLOBAL QUICK SEARCH ----------------
// Search box in the top bar, works from any tab -- jumps straight to a
// player card or a team's Team Tracker detail page. Nothing like this
// existed before; every lookup required first navigating to the right tab.
let globalSearchDebounce = null;
function globalSearchInput(q) {
    clearTimeout(globalSearchDebounce);
    globalSearchDebounce = setTimeout(() => runGlobalSearch(q), 120);
}
window.globalSearchInput = globalSearchInput;

function runGlobalSearch(q) {
    const box = document.getElementById('global-search-results');
    if (!box) return;
    const query = (q || '').trim().toLowerCase();
    if (query.length < 2) { box.style.display = 'none'; box.innerHTML = ''; return; }
    if (!state.players || !state.teams) { box.style.display = 'none'; return; }

    const teamMatches = Object.keys(state.teams)
        .filter(t => t.toLowerCase().includes(query))
        .slice(0, 4)
        .map(t => ({ type: 'team', name: t }));

    const playerMatches = Object.values(state.players)
        .filter(p => p.name && p.name.toLowerCase().includes(query))
        .sort((a, b) => (b.rating || 0) - (a.rating || 0))
        .slice(0, 8)
        .map(p => ({ type: 'player', name: p.name, sub: `${p.team || 'Free Agent'} · ${p.rating} OVR` }));

    const results = [...teamMatches, ...playerMatches];
    if (!results.length) {
        box.innerHTML = '<div class="gsr-item"><span class="hub-result-empty">No matches.</span></div>';
        box.style.display = 'block';
        return;
    }
    box.innerHTML = results.map(r => `
        <div class="gsr-item" onclick="globalSearchSelect('${r.type}', '${r.name.replace(/'/g, "\\'")}')">
            <span>${r.type === 'team' ? '🏀' : '🧑'} ${hubEscape(r.name)}</span>
            ${r.sub ? `<span class="gsr-sub">${hubEscape(r.sub)}</span>` : ''}
        </div>`).join('');
    box.style.display = 'block';
}
window.runGlobalSearch = runGlobalSearch;

function globalSearchSelect(type, name) {
    document.getElementById('global-search-results').style.display = 'none';
    document.getElementById('global-search-input').value = '';
    if (type === 'player') {
        showPlayerModal(name);
    } else if (type === 'team') {
        if (typeof showTeamDetail === 'function') showTeamDetail(name);
    }
}
window.globalSearchSelect = globalSearchSelect;

document.addEventListener('click', (e) => {
    const wrap = document.querySelector('.global-search-wrap');
    if (wrap && !wrap.contains(e.target)) {
        const box = document.getElementById('global-search-results');
        if (box) box.style.display = 'none';
    }
});

// ---------------- STRATEGY DIALS (Team Management) ----------------
// Segmented pill selectors standing in front of the real (visually-hidden)
// <select> elements, so saveRotation()'s reads and the roster-load code's
// writes to those selects keep working completely untouched.
const STRATEGY_DIAL_IDS = ['strat-offense', 'strat-pace', 'strat-shooting', 'strat-scoring', 'strat-defense', 'strat-rebounding'];

function initStrategyDials() {
    STRATEGY_DIAL_IDS.forEach(id => {
        const select = document.getElementById(id);
        const group = document.getElementById('dial-' + id);
        if (!select || !group || group.dataset.built) return;
        group.dataset.built = '1';
        Array.from(select.options).forEach(opt => {
            const pill = document.createElement('button');
            pill.type = 'button';
            pill.className = 'dial-pill' + (opt.value === select.value ? ' active' : '');
            pill.textContent = opt.textContent;
            pill.onclick = () => {
                select.value = opt.value;
                syncStrategyDials();
            };
            group.appendChild(pill);
        });
    });
}
window.initStrategyDials = initStrategyDials;

function syncStrategyDials() {
    STRATEGY_DIAL_IDS.forEach(id => {
        const select = document.getElementById(id);
        const group = document.getElementById('dial-' + id);
        if (!select || !group) return;
        Array.from(group.children).forEach((pill, i) => {
            pill.classList.toggle('active', select.options[i] && select.options[i].value === select.value);
        });
    });
}
window.syncStrategyDials = syncStrategyDials;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initStrategyDials);
} else {
    initStrategyDials();
}
function findNextGame() {
    if (!state.schedule || state.current_day === undefined) return null;
    const team = state.user_team;
    for (let i = state.current_day; i < state.schedule.length; i++) {
        const day = state.schedule[i];
        if (!Array.isArray(day)) continue;
        const g = day.find(g => g.home === team || g.away === team);
        if (g) return { ...g, day: i };
    }
    return null;
}

// Roster average OVR for a team, used for the head-to-head matchup bar.
// Mirrors the same pattern already used for team snapshot averages elsewhere.
function dashTeamAvgRating(team) {
    if (!state.players) return null;
    const roster = Object.values(state.players).filter(p => p.team === team);
    if (!roster.length) return null;
    return Math.round(roster.reduce((s, p) => s + (p.rating || 0), 0) / roster.length);
}

function renderDashboardTab() {
    const root = document.getElementById('dashboard-root');
    if (!root || !state.teams) return;
    const team = state.user_team;
    const td = state.teams[team];
    if (!td) return;

    const record = `${td.wins}-${td.losses}`;
    const streakLabel = td.streak > 0 ? `W${td.streak}` : td.streak < 0 ? `L${Math.abs(td.streak)}` : '—';
    const streakColor = td.streak > 0 ? 'var(--db-green)' : td.streak < 0 ? 'var(--db-red)' : 'var(--db-muted)';
    const capColor = td.cap_space >= 0 ? 'var(--db-green)' : 'var(--db-red)';

    const next = findNextGame();
    let matchupHtml = '<div class="db-empty">No more games scheduled.</div>';
    if (next) {
        const isHome = next.home === team;
        const opp = isHome ? next.away : next.home;
        const daysAway = next.day - (state.current_day || 0);
        const myOvr = dashTeamAvgRating(team);
        const oppOvr = dashTeamAvgRating(opp);
        let ovrBarHtml = '';
        if (myOvr !== null && oppOvr !== null) {
            const total = myOvr + oppOvr || 1;
            const leftPct = Math.round((myOvr / total) * 100);
            ovrBarHtml = `
                <div class="db-ovr-compare">
                    <div class="db-ovr-row">
                        <span class="db-ovr-num" style="color:var(--db-cyan);">${myOvr}</span>
                        <div class="db-ovr-track">
                            <div class="db-ovr-fill-left" style="width:${leftPct}%;"></div>
                            <div class="db-ovr-fill-right" style="width:${100 - leftPct}%;"></div>
                        </div>
                        <span class="db-ovr-num" style="color:var(--db-amber);">${oppOvr}</span>
                    </div>
                    <div class="db-ovr-caption">Roster OVR Comparison</div>
                </div>`;
        }
        matchupHtml = `
            <div class="db-metric-sub text-center mb-2" style="text-transform:uppercase; letter-spacing:1px;">
                ${daysAway <= 0 ? 'TODAY' : `In ${daysAway} day${daysAway === 1 ? '' : 's'}`} · ${isHome ? 'HOME' : 'AWAY'}
            </div>
            <div class="db-matchup-teams">
                <div>${teamLogoHtml(team, 46)}<div class="db-matchup-name">${hubEscape(team)}</div></div>
                <span class="db-matchup-vs">${isHome ? 'VS' : '@'}</span>
                <div>${teamLogoHtml(opp, 46)}<div class="db-matchup-name">${hubEscape(opp)}</div></div>
            </div>
            ${ovrBarHtml}
            <button class="db-jump-btn" onclick="dashJumpToGame('${next.home.replace(/'/g,"\\'")}', '${next.away.replace(/'/g,"\\'")}')">▶ Jump Into This Game</button>`;
    }

    const newsItems = (state.news || []).slice(0, 8);
    const newsHtml = newsItems.length
        ? newsItems.map(n => `
            <div class="db-news-item">
                <span>${n.icon || '📰'}</span>
                <span class="db-news-day">DAY ${n.day}</span>
                <span>${hubEscape(n.text)}</span>
            </div>`).join('')
        : '<div class="db-empty">No news yet — sim some games to get the wire rolling.</div>';

    root.innerHTML = `
        <div class="db-headline"><span class="db-live-dot"></span>${hubEscape(team)} Dashboard</div>

        <div class="db-metric-bar">
            <div class="db-metric-tile">
                <div class="db-metric-label">Record</div>
                <div class="db-metric-value">${record}</div>
                <div class="db-metric-sub" style="color:${streakColor};">${streakLabel} · ${hubEscape(td.conference || '')}</div>
            </div>
            <div class="db-metric-tile">
                <div class="db-metric-label">Cap Space</div>
                <div class="db-metric-value" style="color:${capColor};">$${hubEscape(td.cap_space)}M</div>
                <div class="db-metric-sub">Against the salary cap</div>
            </div>
            <div class="db-metric-tile">
                <div class="db-metric-label">Fan Approval</div>
                <div class="db-metric-value" id="db-fan-approval-val">--</div>
                <div class="db-metric-sub">Live from the fanbase</div>
            </div>
            <div class="db-metric-tile">
                <div class="db-metric-label">Next Game</div>
                <div class="db-metric-value">${next ? (next.day - (state.current_day || 0) <= 0 ? 'Today' : `+${next.day - (state.current_day || 0)}d`) : '—'}</div>
                <div class="db-metric-sub">${next ? (next.home === team ? 'Home' : 'Away') + ' vs ' + hubEscape(next.home === team ? next.away : next.home) : 'Nothing scheduled'}</div>
            </div>
        </div>

        <div class="db-split">
            <div class="db-panel">
                <div class="db-panel-title">Next Matchup Preview</div>
                ${matchupHtml}
            </div>
            <div class="db-panel">
                <div class="db-panel-title">League News Wire</div>
                <div class="db-news-feed">${newsHtml}</div>
            </div>
        </div>

        <div class="subsection-title mt-0">Quick Actions</div>
        <div class="db-quick-grid">
            <div class="db-quick-btn" onclick="dashGoTab('roster')"><span class="dqb-icon">🧑‍💼</span><span class="dqb-label">Team Management</span></div>
            <div class="db-quick-btn" onclick="dashGoTab('trade')"><span class="dqb-icon">🔁</span><span class="dqb-label">Trade Center</span></div>
            <div class="db-quick-btn" onclick="dashGoTab('calendar')"><span class="dqb-icon">📅</span><span class="dqb-label">Sim / Calendar</span></div>
            <div class="db-quick-btn" onclick="dashGoTab('hub-gm')"><span class="dqb-icon">🎙️</span><span class="dqb-label">GM Career</span></div>
            <div class="db-quick-btn" onclick="dashGoTab('stats')"><span class="dqb-icon">📊</span><span class="dqb-label">League Leaders</span></div>
            <div class="db-quick-btn" onclick="dashGoTab('hub-media')"><span class="dqb-icon">📰</span><span class="dqb-label">Media &amp; Fans</span></div>
        </div>

        <div class="subsection-title">Recently Viewed Players</div>
        <div class="recent-players-strip" id="recent-players-strip"></div>
    `;
    renderRecentPlayersStrip();
    fetchDashboardFanApproval(team);
}
window.renderDashboardTab = renderDashboardTab;

// Small helper so quick-action tiles can switch tabs without building an
// onclick string that nests double quotes inside an attribute already
// delimited by double quotes -- that pattern silently breaks the handler
// (the HTML attribute parser has no concept of backslash-escaping, so it
// truncates the value at the first literal '"' it hits, mid-expression).
function dashGoTab(tabId) {
    const btn = document.querySelector(`.side-nav-btn[onclick*="switchTab('${tabId}'"]`)
        || document.querySelector(`.nav-btn[onclick*="switchTab('${tabId}'"]`);
    switchTab(tabId, btn);
}
window.dashGoTab = dashGoTab;

async function dashJumpToGame(home, away) {
    // BUGFIX: this used to call watchLiveGame() directly, but /api/watch_game
    // only ever accepts a matchup that's on *today's* schedule -- and the
    // dashboard's "Next Matchup" game is very often a few days out on a
    // fresh league. Clicking the button just threw a raw alert() error
    // ("That matchup isn't on today's schedule") instead of doing anything,
    // which is exactly the kind of thing a reviewer hits in their first five
    // minutes. Mirror what the Calendar tab's "Jump In Game" button already
    // does correctly: sim forward (day by day, so the UI visibly updates)
    // until that matchup is actually today's game, then watch it live.
    const next = findNextGame();
    if (!next || !((next.home === home && next.away === away) || (next.home === away && next.away === home))) {
        // Fallback: just go to the calendar if we can't confidently resolve
        // which day this matchup is on from here.
        dashGoTab('calendar');
        return;
    }
    const btn = event && event.currentTarget;
    if (btn) { btn.disabled = true; btn.innerText = '⏳ Advancing to game day...'; }
    try {
        if (next.day > (state.current_day || 1)) {
            await simToDay(next.day - 1);
        }
        const day = state.schedule && state.schedule[next.day];
        const stillScheduled = Array.isArray(day) && day.some(g =>
            (g.home === home && g.away === away) || (g.home === away && g.away === home));
        if (!stillScheduled) {
            showToast("That matchup changed while advancing -- check the calendar for what's next.", 'error');
            dashGoTab('calendar');
            return;
        }
    } finally {
        if (btn) { btn.disabled = false; btn.innerText = '▶ Jump Into This Game'; }
    }
    dashGoTab('livegame');
    if (typeof watchLiveGame === 'function') watchLiveGame(home, away);
}
window.dashJumpToGame = dashJumpToGame;

async function fetchDashboardFanApproval(team) {
    const el = document.getElementById('db-fan-approval-val');
    if (!el) return;
    try {
        const res = await fetch(`/api/fan_approval?team=${encodeURIComponent(team)}`);
        const data = await res.json();
        const val = data.fan_approval;
        if (typeof val === 'number' && document.getElementById('db-fan-approval-val')) {
            document.getElementById('db-fan-approval-val').textContent = `${Math.round(val)}%`;
        }
    } catch (e) { /* leave placeholder on failure */ }
}
