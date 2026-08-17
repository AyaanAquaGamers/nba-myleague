    // ===================== TRADE CENTER =====================
    function populateTradePartnerDropdown() {
        const sel = document.getElementById('trade-partner-select');
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = '';
        Object.keys(state.teams).filter(t => t !== state.user_team).forEach(t => {
            const opt = document.createElement('option');
            opt.value = t; opt.innerText = t;
            sel.appendChild(opt);
        });
        if (current && Object.keys(state.teams).includes(current)) sel.value = current;
    }

    function teamAssets(teamName) {
        const players = Object.values(state.players).filter(p => p.team === teamName && !p.retired);
        const picks = Object.values(state.draft_picks || {}).filter(pk => pk.current_team === teamName);
        return {players, picks};
    }

    function pickLabel(pk) {
        return `${pk.year} R${pk.round}${pk.original_team !== pk.current_team ? ' (orig. ' + pk.original_team.split(' ').pop() + ')' : ''}`;
    }

    function renderTradeTab() {
        populateTradePartnerDropdown();
        renderTradeBuilder();
        renderTradeLog();
        renderPendingOffer();
        renderTradeAssetGrid();
        renderTpePanel();
        renderTfPartnerCheckboxes();
        runTradeFinder();
    }

    // UPGRADE: Trade block summary -- everyone the user has marked available,
    // with a one-click remove, right at the top of the Trade Center so it's
    // obvious at a glance who's shopped without digging through the roster tab.
    // UPGRADE: Trade Exceptions (TPE) -- shows your banked exceptions (amount,
    // remaining, and days until they expire) and keeps the propose-trade
    // dropdown in sync so you can spend one on a deal that otherwise wouldn't
    // clear the salary-matching rules.
    function renderTpePanel() {
        const el = document.getElementById('tpe-panel');
        const sel = document.getElementById('trade-tpe-select');
        if (!el) return;
        const tpes = (state.trade_exceptions || {})[state.user_team] || [];
        if (!tpes.length) {
            el.innerHTML = `<div class="alert alert-secondary small mb-0">No banked Trade Exceptions. You get one automatically whenever you trade away more salary than you take back.</div>`;
        } else {
            el.innerHTML = `<div class="p-2 bg-dark rounded border border-info">
                <h6 class="text-info mb-2">🧾 Your Trade Exceptions</h6>
                ${tpes.map(t => {
                    const yearsLeft = t.expire_year - (state.year || t.expire_year);
                    return `<div class="d-flex justify-content-between small mb-1">
                        <span>$${t.remaining.toFixed(1)}M remaining <span class="text-white-50">(of $${t.amount.toFixed(1)}M)</span></span>
                        <span class="text-white-50">expires ${t.expire_year}${yearsLeft <= 0 ? ' (this season)' : ''}</span>
                    </div>`;
                }).join('')}
            </div>`;
        }
        if (sel) {
            const current = sel.value;
            sel.innerHTML = `<option value="">None</option>` + tpes.map(t =>
                `<option value="${t.id}">$${t.remaining.toFixed(1)}M exception (of $${t.amount.toFixed(1)}M)</option>`
            ).join('');
            if (tpes.some(t => t.id === current)) sel.value = current;
        }
    }

    function renderTradeBuilder() {
        const partner = document.getElementById('trade-partner-select').value;
        if (!partner) return;
        document.getElementById('trade-your-team').innerText = state.user_team;
        document.getElementById('trade-their-team').innerText = partner;

        // BUGFIX: this function used to unconditionally wipe tradeSelection
        // and pickProtections every single time it ran -- including on the
        // silent background poll that keeps state fresh (every few seconds).
        // That meant any players/picks you'd clicked into a trade vanished
        // moments later for no visible reason. Now a reset only happens when
        // the trade partner actually changes (see onTradePartnerChange) --
        // this function just repaints the pills, preserving whatever is
        // currently selected.
        if (currentTradePartner !== partner) {
            currentTradePartner = partner;
            tradeSelection = { your_players: [], your_picks: [], their_players: [], their_picks: [] };
            pickProtections = {};
            tradePickerOpenSide = null;
            const protectPanel = document.getElementById('trade-protect-panel');
            if (protectPanel) protectPanel.innerHTML = '';
            const resultPanel = document.getElementById('trade-result-panel');
            if (resultPanel) resultPanel.innerHTML = '';
        }

        const yours = teamAssets(state.user_team);
        const theirs = teamAssets(partner);

        // UI OVERHAUL: 2K's trade screen shows fixed "ADD TRADE ITEM" slots
        // per side -- what's already in the deal sits in a filled slot you
        // can remove with one tap; an empty slot opens a picker instead of
        // permanently showing the whole roster at once.
        const renderSlots = (side, players, picks) => {
            const selPlayers = tradeSelection[side + '_players'];
            const selPicks = tradeSelection[side + '_picks'];
            const filledRows = [
                ...selPlayers.map(name => {
                    const p = players.find(pl => pl.name === name) || SIM_STATE_players_fallback(name);
                    const safeName = name.replace(/'/g, "\\'");
                    return `<div class="trade-slot filled">
                        <span onclick="event.stopPropagation(); showPlayerModal('${safeName}')" style="cursor:pointer;" title="View player card">👁</span>
                        <span class="flex-fill">${name}${p ? ` <small style="color:${attrColor(p.rating)};font-weight:700;">${p.rating} OVR</small>` : ''}</span>
                        <span class="trade-slot-remove" onclick="toggleAssetById('${side}','player','${safeName}')">✕</span>
                    </div>`;
                }),
                ...selPicks.map(id => {
                    const pk = picks.find(x => x.id === id) || (theirs.picks || []).concat(yours.picks || []).find(x => x.id === id);
                    return `<div class="trade-slot filled">
                        <span class="flex-fill">${pk ? pickLabel(pk) : id}</span>
                        <span class="trade-slot-remove" onclick="toggleAssetById('${side}','pick','${id.replace(/'/g, "\\'")}')">✕</span>
                    </div>`;
                }),
            ];
            const slotCount = Math.max(6, filledRows.length + 1);
            while (filledRows.length < slotCount) {
                filledRows.push(`<div class="trade-slot empty" onclick="toggleTradeItemPicker('${side}')">+ ADD TRADE ITEM</div>`);
            }
            return filledRows.join('') + `<div id="trade-picker-${side}" class="trade-item-picker" style="display:none;"></div>`;
        };

        const buildPlayerPills = (players, side) => players.map(p => {
            const isSel = tradeSelection[side + '_players'].includes(p.name);
            if (isSel) return '';
            const safeName = p.name.replace(/'/g, "\\'");
            const ntcTag = (p.contract && p.contract.no_trade_clause) ? ` <small class="text-warning" title="No-trade clause">📜</small>` : '';
            // BUGFIX: this used to also call toggleTradeItemPicker(side, true)
            // on every click, which force-closed the whole dropdown and
            // fully re-rendered the trade builder after selecting a SINGLE
            // item -- made it impossible to add more than one player/pick
            // without reopening the picker from scratch each time. toggleAsset
            // already updates the selection and fairness bar on its own;
            // pickerItemSelected() just removes this one pill and refreshes
            // the "added so far" slots, leaving the dropdown open.
            return `<span class="asset-pill" data-side="${side}" data-type="player" data-id="${p.name}" onclick="toggleAsset(this); pickerItemSelected(this, '${side}');">
                ${p.name} <small style="color:${attrColor(p.rating)}; font-weight:700;">${p.rating} OVR</small>${ntcTag}
            </span>`;
        }).join('') || '<span class="text-muted small">No players available</span>';

        const buildPickPills = (picks, side) => picks.map(pk => {
            const isSel = tradeSelection[side + '_picks'].includes(pk.id);
            if (isSel) return '';
            return `<span class="asset-pill" data-side="${side}" data-type="pick" data-id="${pk.id}" onclick="toggleAsset(this); pickerItemSelected(this, '${side}');">${pickLabel(pk)} <small class="text-muted">(${pk.value ?? '—'} val)</small>${pk.protection && pk.protection !== 'None' ? ` <small class="text-warning">🛡${pk.protection}</small>` : ''}</span>`;
        }).join('') || '<span class="text-muted small">No picks available</span>';

        document.getElementById('trade-your-players').innerHTML = renderSlots('your', yours.players, yours.picks);
        document.getElementById('trade-their-players').innerHTML = renderSlots('their', theirs.players, theirs.picks);
        // BUGFIX (major): renderTradeTab() -- and therefore this function --
        // gets called every time the background heartbeat poll detects ANY
        // state change anywhere in the game, not just trade-related ones,
        // as long as the Trade tab happens to be open. Every call wipes and
        // rebuilds the picker's innerHTML, which silently resets its scroll
        // position to the top. With a full 15-man roster's worth of player
        // pills to scroll through before reaching the draft picks listed
        // after them, this made it feel like the picker "reset" and picks
        // were unreachable -- you'd get partway down and the next ambient
        // heartbeat tick would snap you back to the top. Capture and
        // restore the picker's scroll position across every rebuild.
        const pickerScrollTop = tradePickerOpenSide
            ? (document.getElementById(`trade-picker-${tradePickerOpenSide}`) || {}).scrollTop
            : undefined;
        if (tradePickerOpenSide) {
            const reopenEl = document.getElementById(`trade-picker-${tradePickerOpenSide}`);
            if (reopenEl) {
                const freshContent = tradePickerData[tradePickerOpenSide] || '<span class="text-muted small">Nothing available</span>';
                // Extra guard: if the available items haven't actually
                // changed (the common case for a heartbeat tick that fired
                // for a totally unrelated reason elsewhere in the game),
                // skip touching the DOM at all rather than rebuild-then-
                // restore -- avoids interrupting an in-progress scroll
                // gesture, not just landing on the right final position.
                if (reopenEl.innerHTML !== freshContent) {
                    reopenEl.innerHTML = freshContent;
                    if (pickerScrollTop) reopenEl.scrollTop = pickerScrollTop;
                }
                reopenEl.style.display = 'flex';
            }
        }
        document.getElementById('trade-your-picks').style.display = 'none';
        document.getElementById('trade-their-picks').style.display = 'none';
        tradePickerData = {
            your: buildPlayerPills(yours.players, 'your') + buildPickPills(yours.picks, 'your'),
            their: buildPlayerPills(theirs.players, 'their') + buildPickPills(theirs.picks, 'their'),
        };
        loadTeamNeeds(state.user_team, partner);
        renderProtectPanel();
        updateTradeFairness();
    }

    function pickerItemSelected(pillEl, side) {
        // Remove just the clicked pill immediately so the picker visibly
        // updates without closing, then refresh the slots/fairness bar in
        // the background. renderTradeBuilder() regenerates tradePickerData
        // (already correctly excluding this now-selected item) but does not
        // touch the picker dropdown's own open/closed display state, so it
        // stays open for the next selection.
        if (pillEl && pillEl.remove) pillEl.remove();
        renderTradeBuilder();
    }
    window.pickerItemSelected = pickerItemSelected;

    let tradePickerData = {your: '', their: ''};
    // BUGFIX (major): renderSlots() always bakes `style="display:none;"`
    // into the picker container's own markup, and every renderTradeBuilder()
    // call blindly overwrites that container's innerHTML wholesale --
    // including after adding just ONE item, since pickerItemSelected()
    // calls renderTradeBuilder() to refresh the fairness bar and filled
    // slots. The net effect: the picker dropdown silently snapped shut
    // after every single click, which is exactly what read as "the page
    // resets and won't let me build a trade" -- you could never add more
    // than one asset per side without manually reopening the picker each
    // time. Track which side's picker (if any) is currently open, and
    // restore it after every re-render.
    let tradePickerOpenSide = null;
    function SIM_STATE_players_fallback(name) { return state.players && state.players[name]; }

    function toggleTradeItemPicker(side, forceClose) {
        const el = document.getElementById(`trade-picker-${side}`);
        if (!el) return;
        if (forceClose === true) { el.style.display = 'none'; tradePickerOpenSide = null; renderTradeBuilder(); return; }
        const opening = el.style.display === 'none';
        document.querySelectorAll('.trade-item-picker').forEach(p => p.style.display = 'none');
        tradePickerOpenSide = opening ? side : null;
        if (opening) {
            el.innerHTML = tradePickerData[side] || '<span class="text-muted small">Nothing available</span>';
            el.style.display = 'flex';
        }
    }
    window.toggleTradeItemPicker = toggleTradeItemPicker;

    function toggleAssetById(side, type, id) {
        const key = side + '_' + (type === 'player' ? 'players' : 'picks');
        const arr = tradeSelection[key];
        const idx = arr.indexOf(id);
        if (idx >= 0) arr.splice(idx, 1);
        renderTradeBuilder();
        updateTradeFairness();
    }
    window.toggleAssetById = toggleAssetById;

    async function loadTeamNeeds(userTeam, partner) {
        try {
            const [rYours, rTheirs] = await Promise.all([
                fetch(`/api/team_needs?team=${encodeURIComponent(userTeam)}`), fetch(`/api/team_needs?team=${encodeURIComponent(partner)}`)
            ]);
            const [dYours, dTheirs] = [await rYours.json(), await rTheirs.json()];
            const yEl = document.getElementById('trade-your-needs'), tEl = document.getElementById('trade-their-needs');
            if (yEl) yEl.innerText = (dYours.needs || []).join(', ') || '—';
            if (tEl) tEl.innerText = (dTheirs.needs || []).join(', ') || '—';
        } catch (e) { /* non-critical */ }
    }

    // Known attribute list, mirrored from the backend's gen_attributes() keys.
    // Populated synchronously so the dropdown is never empty -- the old
    // fetch-then-populate approach had a real race: on a real device with
    // several requests firing at once when the Trade tab opens, a user could
    // tap the dropdown before the fetch resolved and see nothing but "Any".
    const KNOWN_ATTRIBUTES = ["Ball Handling", "Ball Security", "Block", "Boxout", "Close Shot",
        "Clutch Factor", "Consistency", "Defensive Rebound", "Driving Dunk", "Driving Layup",
        "Durability", "Free Throw", "Help Defense IQ", "Hustle", "Interior Defense",
        "Lateral Quickness", "Mid-Range", "Off-the-Dribble", "Offensive Rebound", "Passing Accuracy",
        "Perimeter Defense", "Pick & Roll Defense", "Post Control", "Post Defense", "Post Hook",
        "Shot IQ", "Speed", "Speed With Ball", "Stamina", "Standing Dunk", "Steal", "Strength",
        "Three-Point", "Vertical", "Vision"];

    function ensureAttributeCheckboxesPopulated(containerId) {
        const el = document.getElementById(containerId);
        if (!el || el.dataset.populated) return;
        el.dataset.populated = '1';
        el.innerHTML = KNOWN_ATTRIBUTES.map(a =>
            `<div class="form-check form-check-inline" style="width:47%;">
                <input class="form-check-input tf-attr-checkbox" type="checkbox" value="${a}" id="tfattr-${a.replace(/[^a-zA-Z]/g,'')}" onchange="runTradeFinder()">
                <label class="form-check-label small text-white-50" for="tfattr-${a.replace(/[^a-zA-Z]/g,'')}">${a}</label>
            </div>`).join('');
        // Refresh from the server in the background in case the attribute
        // list ever changes -- but the UI is already usable immediately.
        fetch('/api/attribute_options').then(r => r.json()).then(d => {
            if (!d.attributes || !d.attributes.length) return;
            const known = new Set(KNOWN_ATTRIBUTES);
            const extra = d.attributes.filter(a => !known.has(a));
            if (extra.length) {
                el.innerHTML += extra.map(a =>
                    `<div class="form-check form-check-inline" style="width:47%;">
                        <input class="form-check-input tf-attr-checkbox" type="checkbox" value="${a}" id="tfattr-${a.replace(/[^a-zA-Z]/g,'')}" onchange="runTradeFinder()">
                        <label class="form-check-label small text-white-50" for="tfattr-${a.replace(/[^a-zA-Z]/g,'')}">${a}</label>
                    </div>`).join('');
            }
        }).catch(() => {});
    }
    window.ensureAttributeCheckboxesPopulated = ensureAttributeCheckboxesPopulated;

    async function runTradeFinder() {
        const posEl = document.getElementById('tf-position');
        if (!posEl) return; // not on the Trade tab right now -- nothing to refresh
        ensureAttributeCheckboxesPopulated('tf-attribute-checkboxes');
        const selectedAttributes = Array.from(document.querySelectorAll('.tf-attr-checkbox:checked')).map(c => c.value);
        const params = new URLSearchParams({
            team: state.user_team,
            position: document.getElementById('tf-position').value,
            min_rating: document.getElementById('tf-min-rating').value || 0,
            max_salary: document.getElementById('tf-max-salary').value || 999,
            max_age: document.getElementById('tf-max-age').value || 99,
            q: document.getElementById('tf-query').value || '',
            attributes: selectedAttributes.join(','),
            min_attribute: document.getElementById('tf-min-attribute') ? (document.getElementById('tf-min-attribute').value || 0) : 0,
            hide_untouchable: document.getElementById('tf-include-untouchable')?.checked ? '0' : '1',
        });
        const res = await fetch(`/api/trade_finder_search?${params}`);
        const data = await res.json();
        const el = document.getElementById('trade-finder-results');
        const countEl = document.getElementById('trade-finder-count');
        if (!data.success) { el.innerHTML = '<div class="text-white-50 small">No results.</div>'; return; }
        countEl.innerText = `${data.count} match${data.count === 1 ? '' : 'es'}`;
        el.innerHTML = data.results.map(p => `
            <div class="d-flex justify-content-between align-items-center py-1 border-bottom border-secondary small">
                <span><a class="player-link" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')">${p.name}</a>
                    <span class="text-white-50">${p.position} · ${p.team} · Age ${p.age}</span>
                    ${p.on_trade_block ? '<span class="badge bg-warning text-dark ms-1">On Block</span>' : ''}</span>
                <span class="d-flex align-items-center gap-2 flex-wrap justify-content-end">
                    ${(p.attribute_values || []).map(av => `<span class="text-warning fw-bold" style="font-size:0.72rem;">${Math.round(av.value)} ${av.name}</span>`).join('')}
                    <span style="color:${attrColor(p.rating)};font-weight:700;">${p.rating} OVR</span>
                    <span class="text-white-50">$${(p.salary || 0).toFixed(1)}M</span>
                    <button class="btn btn-outline-accent btn-sm py-0 px-2" style="font-size:0.7rem;" onclick="targetTradePlayer('${p.name.replace(/'/g, "\\'")}', '${p.team.replace(/'/g, "\\'")}')">Target</button>
                    <button class="btn btn-sm py-0 px-2" style="font-size:0.85rem;background:none;border:none;" onclick="toggleTradeTargetWatch('${p.name.replace(/'/g, "\\'")}')" title="${p.is_watched ? 'Remove from watchlist' : 'Add to watchlist'}">${p.is_watched ? '★' : '☆'}</button>
                </span>
            </div>`).join('') || '<div class="text-white-50 small">No matches.</div>';
    }
    // UI OVERHAUL: 2K's trade board shows Trade Block / Untouchables / Target
    // List as fixed-size card grids (5 slots per row, empty slots shown as
    // placeholders) rather than plain text lists -- gives a quick visual
    // read on exactly how full/empty each list is.
    // ===================== TRADE FINDER (2K-style: pick your players, see who wants them) =====================
    let tfSelectedPlayers = [];
    let tfSelectedPicks = [];
    function renderTfPartnerCheckboxes() {
        const el = document.getElementById('tf-partner-your-players');
        if (!el) return;
        const roster = Object.values(state.players).filter(p => p.team === state.user_team && !p.retired).sort((a, b) => b.rating - a.rating);
        el.innerHTML = roster.map(p => {
            const isSel = tfSelectedPlayers.includes(p.name);
            const safeName = p.name.replace(/'/g, "\\'");
            return `<span class="asset-pill${isSel ? ' selected' : ''}" onclick="toggleTfSelect('${safeName}')">${p.name} <small style="color:${attrColor(p.rating)};font-weight:700;">${p.rating} OVR</small></span>`;
        }).join('') || '<span class="text-muted small">No players on your roster.</span>';

        // BUGFIX: Trade Finder had no way to include your own draft picks in
        // the shopped package -- only players. Mirror the player pill
        // selector for picks using the same asset data the Trade Center
        // builder already uses.
        const picksEl = document.getElementById('tf-partner-your-picks');
        if (picksEl) {
            const picks = teamAssets(state.user_team).picks || [];
            picksEl.innerHTML = picks.length ? picks.map(pk => {
                const isSel = tfSelectedPicks.includes(pk.id);
                return `<span class="asset-pill${isSel ? ' selected' : ''}" onclick="toggleTfPickSelect('${pk.id}')">📄 ${pickLabel(pk)}</span>`;
            }).join('') : '<span class="text-muted small">No tradeable picks.</span>';
        }
    }
    window.renderTfPartnerCheckboxes = renderTfPartnerCheckboxes;

    function toggleTfSelect(name) {
        const idx = tfSelectedPlayers.indexOf(name);
        if (idx >= 0) tfSelectedPlayers.splice(idx, 1); else tfSelectedPlayers.push(name);
        renderTfPartnerCheckboxes();
    }
    window.toggleTfSelect = toggleTfSelect;

    function toggleTfPickSelect(pickId) {
        const idx = tfSelectedPicks.indexOf(pickId);
        if (idx >= 0) tfSelectedPicks.splice(idx, 1); else tfSelectedPicks.push(pickId);
        renderTfPartnerCheckboxes();
    }
    window.toggleTfPickSelect = toggleTfPickSelect;

    async function findTradePartners() {
        const el = document.getElementById('trade-partner-results');
        if (!tfSelectedPlayers.length && !tfSelectedPicks.length) { showToast('Select at least one of your players or picks first.', 'error'); return; }
        el.innerHTML = '<div class="text-white-50 small">Checking around the league...</div>';
        const params = new URLSearchParams({team: state.user_team, players: tfSelectedPlayers.join(','), picks: tfSelectedPicks.join(',')});
        const res = await fetch(`/api/find_trade_partners?${params}`);
        const data = await res.json();
        if (!data.success) { el.innerHTML = `<div class="text-white-50 small">${data.reason}</div>`; return; }
        if (!data.offers.length) { el.innerHTML = '<div class="text-white-50 small">No teams are interested in that package right now.</div>'; return; }
        // UPGRADE PASS:
        //  - suggested_return used to be a plain comma-joined string of
        //    names -- not clickable, no OVR/position shown. Now uses
        //    suggested_return_detail (name+position+rating) as real
        //    clickable player-modal links.
        //  - draft picks are now included when the player package alone
        //    doesn't cover the value gap (suggested_return_picks).
        //  - "Use This Offer" is renamed "Negotiate" and now actually
        //    switches you to the Trade Center tab with the offer loaded,
        //    instead of silently updating a tab you're not looking at.
        el.innerHTML = data.offers.map(o => {
            const detail = o.suggested_return_detail || o.suggested_return.map(n => ({name: n, position: '', rating: null}));
            const playerChips = detail.map(p => `<a class="player-link" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')">${p.name}</a>
                <span class="text-white-50" style="font-size:0.8em;">${p.position || ''}${p.rating ? ' · ' + p.rating + ' OVR' : ''}</span>`).join(', ');
            const pickChips = (o.suggested_return_picks || []).map(pk =>
                `<span class="badge bg-secondary">${pk.year} Rd ${pk.round}${pk.original_team !== o.team ? ' (via ' + pk.original_team + ')' : ''}${pk.protection !== 'None' ? ' · ' + pk.protection : ''}</span>`
            ).join(' ');
            const returnLine = [playerChips, pickChips].filter(Boolean).join(' + ') || '<span class="text-white-50">nothing of note</span>';
            return `
            <div class="stat-subpanel mb-2">
                <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
                    <span class="fw-bold text-info">${o.team}${o.fills_need ? ' <span class="badge bg-success">Fills Need</span>' : ''}</span>
                    <button class="btn btn-outline-accent btn-sm" onclick='negotiateTradePartnerOffer(${JSON.stringify(o.team)}, ${JSON.stringify(o.suggested_return)}, ${JSON.stringify((o.suggested_return_picks || []).map(pk => pk.id))})'>🤝 Negotiate</button>
                </div>
                <div class="small text-white-50 mt-1">Would likely send back: ${returnLine}</div>
            </div>`;
        }).join('');
    }
    window.findTradePartners = findTradePartners;

    async function negotiateTradePartnerOffer(team, theirPlayers, theirPickIds) {
        const sel = document.getElementById('trade-partner-select');
        sel.value = team;
        onTradePartnerChange();
        setTimeout(() => {
            tradeSelection.your_players = tfSelectedPlayers.slice();
            tradeSelection.your_picks = tfSelectedPicks.slice();
            tradeSelection.their_players = theirPlayers;
            tradeSelection.their_picks = theirPickIds || [];
            renderTradeBuilder();
            // Actually take the user to the Trade Center tab with the offer
            // loaded -- previously this just updated hidden DOM state on a
            // tab that wasn't visible, so nothing appeared to happen.
            switchTradeSubTab('center');
        }, 150);
    }
    window.negotiateTradePartnerOffer = negotiateTradePartnerOffer;
    // Kept as an alias in case anything else still references the old name.
    window.useTradePartnerOffer = negotiateTradePartnerOffer;

    function tradeAssetSlotHtml(p, emptyLabel, removeAction) {
        if (!p) {
            return `<div class="stat-subpanel text-center text-white-50 small" style="min-height:86px; display:flex; align-items:center; justify-content:center; opacity:0.5;">${emptyLabel}</div>`;
        }
        const safeName = p.name.replace(/'/g, "\\'");
        return `<div class="stat-subpanel text-center position-relative" style="min-height:86px;">
            ${removeAction ? `<span style="position:absolute;top:2px;right:6px;cursor:pointer;color:#9db4d9;font-size:0.75rem;" onclick="${removeAction}('${safeName}')" title="Remove">✕</span>` : ''}
            <div style="width:26px;height:26px;margin:0 auto;">${playerSilhouetteSvg(p.name, p.position, teamColor(p.team || ''), 26)}</div>
            <a class="player-link d-block small fw-bold" onclick="showPlayerModal('${safeName}')">${p.name}</a>
            <div class="small text-white-50">${p.team || 'FA'} · ${p.rating} OVR</div>
        </div>`;
    }

    function tradeAssetRow(title, icon, players, emptyLabel, removeAction) {
        const slots = players.slice(0, 5);
        while (slots.length < 5) slots.push(null);
        return `<div class="mb-3">
            <div class="small text-white-50 font-monospace mb-1">${icon} ${title} (${players.length})</div>
            <div class="row g-2">${slots.map(p => `<div class="col">${tradeAssetSlotHtml(p, emptyLabel, removeAction)}</div>`).join('')}</div>
        </div>`;
    }

    function renderTradeAssetGrid() {
        const el = document.getElementById('trade-asset-grid');
        if (!el) return;
        const blockNames = state.trade_block || [];
        const untouchableNames = (state.untradeable || {})[state.user_team] || [];
        const targetNames = (state.trade_targets || {})[state.user_team] || [];
        const blockPlayers = blockNames.map(n => state.players[n]).filter(Boolean);
        const untouchablePlayers = untouchableNames.map(n => state.players[n]).filter(Boolean);
        const targetPlayers = targetNames.map(n => state.players[n]).filter(Boolean);
        el.innerHTML =
            tradeAssetRow('On The Block', '📢', blockPlayers, 'No one on the block', 'toggleTradeBlock') +
            tradeAssetRow('Untouchables', '🔒', untouchablePlayers, 'None locked', 'toggleUntradeable') +
            tradeAssetRow('Target List', '☆', targetPlayers, 'Use ☆ in Trade Finder to watch a player', 'toggleTradeTargetWatch');
    }
    window.renderTradeAssetGrid = renderTradeAssetGrid;

    // ===================== TEAM INTEL TAB =====================
    // 2K-style scouting screen: cycle through every team and see their
    // starting five, 6th man, untouchables, injuries, expiring contracts,
    // and (for your own team) trade block + target list.
    let tiActiveTeam = null;
    let tiRequestSeq = 0;
    async function renderTeamIntelTab(teamName) {
        const sel = document.getElementById('ti-team-select');
        const allTeams = Object.keys(state.teams).sort();
        if (sel && !sel.dataset.populated) {
            sel.innerHTML = allTeams.map(t => `<option value="${t}">${t}</option>`).join('');
            sel.dataset.populated = '1';
        }
        if (!tiActiveTeam) tiActiveTeam = state.user_team;
        if (teamName) tiActiveTeam = teamName;
        if (sel) sel.value = tiActiveTeam;

        // BUGFIX: rapid clicks on the ◀ ▶ cycle arrows (or fast tab
        // switching) used to fire multiple overlapping fetches for
        // different teams -- whichever one happened to resolve LAST won
        // the DOM write, even if it wasn't the team you'd actually landed
        // on. This sequence token makes every call check, right before it
        // touches the DOM, that it's still the most recent request; a
        // superseded one just quietly bows out instead of racing/corrupting
        // the view (or throwing on elements a later render already replaced).
        const mySeq = ++tiRequestSeq;
        const isCurrent = () => mySeq === tiRequestSeq;

        const el = document.getElementById('ti-content');
        el.innerHTML = '<div class="text-white-50 small">Loading intel...</div>';
        let data;
        const attempts = 3;
        for (let attempt = 1; attempt <= attempts; attempt++) {
            try {
                const res = await fetch(`/api/team_intel?team=${encodeURIComponent(tiActiveTeam)}`);
                data = await res.json();
                break;
            } catch (e) {
                if (!isCurrent()) return;
                if (attempt === attempts) {
                    el.innerHTML = `<div class="text-danger small">Failed to load team intel: ${e.message} <button class="btn btn-sm btn-outline-accent ms-2" onclick="renderTeamIntelTab()">Retry</button></div>`;
                    return;
                }
                el.innerHTML = `<div class="text-white-50 small">Loading intel... (retry ${attempt}/${attempts - 1})</div>`;
                await new Promise(r => setTimeout(r, 500 * attempt));
            }
        }
        if (!isCurrent()) return;
        if (!data.success) { el.innerHTML = `<div class="text-white-50">${data.reason || 'Unable to load intel.'}</div>`; return; }

        try {
            if (!isCurrent()) return;
            document.getElementById('ti-team-name').innerText = `${tiActiveTeam===state.user_team ? '⭐ ' : ''}${tiActiveTeam}`;
            document.getElementById('ti-team-sub').innerText = `${data.conference}ern Conference · ${data.wins}-${data.losses}`;
            const chemEl = document.getElementById('ti-chemistry-ring');
            if (chemEl && typeof chemistryRingSvg === 'function') {
                const teamChem = (state.teams[tiActiveTeam] || {}).chemistry;
                chemEl.innerHTML = chemistryRingSvg(teamChem, 50);
            }

            const nameToPlayer = n => state.players[n];
            const starterSlots = ['PG','SG','SF','PF','C'];
            const startersBySlot = {};
            (data.starters || []).forEach(s => { startersBySlot[s.slot] = s.name; });

            let html = `<h5 class="text-white-50 font-monospace mb-2">⭐ Starting Lineup</h5>
                <div class="row g-2 mb-3">${starterSlots.map(slot => {
                    const name = startersBySlot[slot];
                    const p = name ? nameToPlayer(name) : null;
                    return `<div class="col"><div class="stat-subpanel text-center" style="min-height:96px;">
                        <div class="small text-warning fw-bold">${slot}</div>
                        ${p ? `<div style="width:26px;height:26px;margin:0 auto;">${playerSilhouetteSvg(p.name, p.position, teamColor(tiActiveTeam), 26)}</div>
                            <a class="player-link d-block small fw-bold" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')">${p.name}</a>
                            <div class="small text-white-50">${p.rating} OVR</div>`
                            : `<div class="text-white-50 small mt-3">Empty</div>`}
                    </div></div>`;
                }).join('')}</div>`;

            const sixth = data.sixth_man ? nameToPlayer(data.sixth_man) : null;
            html += `<h5 class="text-white-50 font-monospace mb-2">🎽 6th Man</h5>
                <div class="row g-2 mb-3"><div class="col-2">${tradeAssetSlotHtml(sixth, 'None')}</div></div>`;

            html += tradeAssetRow('Untouchables', '🔒', (data.untouchables || []).map(nameToPlayer).filter(Boolean), 'None');

            if (data.is_user_team) {
                html += tradeAssetRow('On The Block', '📢', (data.trade_block || []).map(nameToPlayer).filter(Boolean), 'No one on the block');
                html += tradeAssetRow('Target List', '☆', (data.target_list || []).map(nameToPlayer).filter(Boolean), 'No watched players yet');
            } else {
                html += `<h5 class="text-white-50 font-monospace mb-2">🕵️ Rumored Trade Interest <span class="small" style="font-weight:400;">(scouting read, not confirmed)</span></h5>`;
                html += tradeAssetRow('Rumored Block', '🕵️', (data.trade_block || []).map(nameToPlayer).filter(Boolean), 'Nothing buzzing right now');
            }

            const injuries = (data.injuries || []).map(nameToPlayer).filter(Boolean);
            html += `<h5 class="text-white-50 font-monospace mb-2">🩹 Injuries (${injuries.length})</h5>`;
            html += injuries.length
                ? `<div class="mb-3">${injuries.map(p => `<div class="stat-subpanel mb-1 d-flex justify-content-between align-items-center small">
                    <a class="player-link" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')">${p.name}</a>
                    <span class="text-danger">${p.injury ? `${p.injury.status || ''} · ${p.injury.description} (${p.injury.games_remaining}g)` : ''}</span>
                </div>`).join('')}</div>`
                : `<div class="text-white-50 small mb-3">Fully healthy.</div>`;

            const expiring = (data.expiring_contracts || []).map(nameToPlayer).filter(Boolean);
            html += `<h5 class="text-white-50 font-monospace mb-2">📉 Expiring Contracts (${expiring.length})</h5>`;
            html += expiring.length
                ? `<div class="mb-1">${expiring.map(p => `<div class="stat-subpanel mb-1 d-flex justify-content-between align-items-center small">
                    <a class="player-link" onclick="showPlayerModal('${p.name.replace(/'/g, "\\'")}')">${p.name}</a>
                    <span class="text-white-50">$${((p.contract||{}).salary||0).toFixed(1)}M · ${(p.contract||{}).years_left ?? 0} yr left</span>
                </div>`).join('')}</div>`
                : `<div class="text-white-50 small">No contracts expiring soon.</div>`;

            el.innerHTML = html;
        } catch (e) {
            el.innerHTML = `<div class="text-danger small">Error rendering team intel: ${e.message}</div>`;
        }
    }
    window.renderTeamIntelTab = renderTeamIntelTab;

    function cycleTeamIntel(dir) {
        const allTeams = Object.keys(state.teams).sort();
        const idx = allTeams.indexOf(tiActiveTeam || state.user_team);
        const next = allTeams[(idx + dir + allTeams.length) % allTeams.length];
        renderTeamIntelTab(next);
    }
    window.cycleTeamIntel = cycleTeamIntel;

    async function toggleTradeTargetWatch(playerName) {
        await fetch('/api/toggle_trade_target', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({player_name: playerName})});
        await refreshState();
        await runTradeFinder();
        renderTradeAssetGrid();
    }
    window.toggleTradeTargetWatch = toggleTradeTargetWatch;
    window.runTradeFinder = runTradeFinder;

    async function targetTradePlayer(playerName, team) {
        const sel = document.getElementById('trade-partner-select');
        sel.value = team;
        onTradePartnerChange();
        // give renderTradeBuilder a beat to repaint the partner's assets, then
        // pre-select the targeted player and suggest a fair package for them.
        setTimeout(async () => {
            tradeSelection.their_players = [playerName];
            const target = state.players[playerName];
            const targetValue = await fetch('/api/trade_preview', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
                team_a: state.user_team, team_b: team, players_a: [], picks_a: [], players_b: [playerName], picks_b: []
            })}).then(r => r.json());
            const myRoster = Object.values(state.players).filter(p => p.team === state.user_team && !p.retired)
                .sort((a, b) => a.rating - b.rating);
            let running = 0, pkg = [];
            for (const p of myRoster) {
                if (running >= (targetValue.value_received || 0) * 0.9) break;
                pkg.push(p.name);
                const preview = await fetch('/api/trade_preview', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
                    team_a: state.user_team, team_b: team, players_a: pkg, picks_a: [], players_b: [playerName], picks_b: []
                })}).then(r => r.json());
                running = preview.value_sent || 0;
            }
            tradeSelection.your_players = pkg;
            renderTradeBuilder();
        }, 150);
    }
    window.targetTradePlayer = targetTradePlayer;

    async function findFairDeal() {
        const partner = document.getElementById('trade-partner-select').value;
        if (!partner) { showToast('Select a trade partner first.', 'error'); return; }
        const res = await fetch(`/api/suggest_trade_package?team=${encodeURIComponent(state.user_team)}&partner=${encodeURIComponent(partner)}`);
        const data = await res.json();
        const panel = document.getElementById('trade-result-panel');
        if (!data.success) { panel.innerHTML = `<div class="alert alert-secondary">${data.reason}</div>`; return; }
        tradeSelection = { your_players: data.players_a, your_picks: data.picks_a, their_players: [data.target_player], their_picks: [] };
        panel.innerHTML = `<div class="alert alert-info">Suggested a package built around your need at ${data.need_filled}. Review below and propose if it looks right.</div>`;
        renderTradeBuilder();
    }
    window.findFairDeal = findFairDeal;

    let tradeMode = 2;
    let thirdTeamSelection = { players: [], picks: [] };

    function setTradeMode(mode) {
        tradeMode = mode;
        document.getElementById('btn-trade-2team').className = mode === 2 ? 'btn btn-accent btn-sm' : 'btn btn-outline-accent btn-sm';
        document.getElementById('btn-trade-3team').className = mode === 3 ? 'btn btn-accent btn-sm' : 'btn btn-outline-accent btn-sm';
        // 3-team mode turns the third team into a real peer panel alongside
        // Your Assets / Their Assets (matching col-md-4 each) instead of a
        // cramped little box stacked underneath -- so all three read the
        // same way, not like the third one is an afterthought.
        document.getElementById('trade-third-col').style.display = mode === 3 ? 'block' : 'none';
        document.getElementById('trade-your-col').className = mode === 3 ? 'col-md-4' : 'col-md-6';
        document.getElementById('trade-their-col').className = mode === 3 ? 'col-md-4' : 'col-md-6';
        if (mode === 3) {
            const sel = document.getElementById('trade-third-team-select');
            const partner = document.getElementById('trade-partner-select').value;
            sel.innerHTML = '<option value="">— Select a third team —</option>' +
                Object.keys(state.teams).filter(t => t !== state.user_team && t !== partner)
                    .sort().map(t => `<option value="${t}">${t}</option>`).join('');
            thirdTeamSelection = { players: [], picks: [] };
            document.getElementById('trade-third-players').innerHTML = '';
            document.getElementById('trade-third-picks').innerHTML = '';
            document.getElementById('third-team-assets').style.display = 'none';
            document.getElementById('trade-third-team-label').innerText = '';
            document.getElementById('trade-third-needs').innerText = '';
        }
    }
    window.setTradeMode = setTradeMode;

    async function onThirdTeamChange() {
        const third = document.getElementById('trade-third-team-select').value;
        thirdTeamSelection = { players: [], picks: [] };
        document.getElementById('trade-third-team-label').innerText = third || '';
        if (!third) {
            document.getElementById('third-team-assets').style.display = 'none';
            document.getElementById('trade-third-needs').innerText = '';
            return;
        }
        document.getElementById('third-team-assets').style.display = 'block';
        const { players, picks } = teamAssets(third);
        const buildPills = (items, type) => items.map(item => {
            const id = type === 'player' ? item.name : item.id;
            const label = type === 'player'
                ? `<span onclick="event.stopPropagation();showPlayerModal('${item.name.replace(/'/g,"\\'")}')" style="cursor:pointer;">👁</span> ${item.name} <small style="color:#facc15;">${item.rating} OVR</small>`
                : `${pickLabel(item)}`;
            return `<span class="asset-pill" data-third-type="${type}" data-third-id="${id}" onclick="toggleThirdAsset(this)">${label}</span>`;
        }).join('') || '<span class="text-muted small">None</span>';
        document.getElementById('trade-third-players').innerHTML = buildPills(players, 'player');
        document.getElementById('trade-third-picks').innerHTML = buildPills(picks, 'pick');
        try {
            const r = await fetch(`/api/team_needs?team=${encodeURIComponent(third)}`);
            const d = await r.json();
            document.getElementById('trade-third-needs').innerText = (d.needs || []).join(', ') || '—';
        } catch (e) { /* non-critical */ }
    }
    window.onThirdTeamChange = onThirdTeamChange;

    function toggleThirdAsset(el) {
        const type = el.dataset.thirdType, id = el.dataset.thirdId;
        const arr = type === 'player' ? thirdTeamSelection.players : thirdTeamSelection.picks;
        const idx = arr.indexOf(id);
        if (idx >= 0) { arr.splice(idx, 1); el.classList.remove('selected'); }
        else { arr.push(id); el.classList.add('selected'); }
    }
    window.toggleThirdAsset = toggleThirdAsset;

    async function propose3TeamTrade() {
        const partner = document.getElementById('trade-partner-select').value;
        const third = document.getElementById('trade-third-team-select').value;
        if (!partner || !third) { showToast('Select both trade partners first.', 'error'); return; }
        const user = state.user_team;
        const body = {
            teams: [user, partner, third],
            sends: {
                [user]: { [partner]: { players: tradeSelection.your_players, picks: tradeSelection.your_picks } },
                [partner]: { [user]: { players: tradeSelection.their_players, picks: tradeSelection.their_picks } },
                [third]: { [user]: { players: thirdTeamSelection.players, picks: thirdTeamSelection.picks } },
            }
        };
        const res = await fetch('/api/propose_3team_trade', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
        const data = await res.json();
        const panel = document.getElementById('trade-result-panel');
        if (data.accepted) {
            panel.innerHTML = `<div class="alert alert-success">✅ ${data.reason}</div>`;
            currentTradePartner = null;
            setTradeMode(2);
        } else {
            panel.innerHTML = `<div class="alert alert-danger">❌ ${data.reason}</div>`;
        }
        await refreshState();
        renderTradeBuilder();
    }
    window.propose3TeamTrade = propose3TeamTrade;
    // Explicit user action (changed the dropdown) -- this is the ONLY place
    function onTradePartnerChange() {
        currentTradePartner = null; // forces renderTradeBuilder to treat this as a real change
        renderTradeBuilder();
    }
    window.onTradePartnerChange = onTradePartnerChange;

    function toggleAsset(el) {
        el.classList.toggle('selected');
        const side = el.getAttribute('data-side');
        const type = el.getAttribute('data-type');
        const id = el.getAttribute('data-id');
        const key = side + '_' + (type === 'player' ? 'players' : 'picks');
        const idx = tradeSelection[key].indexOf(id);
        if (el.classList.contains('selected')) {
            if (idx === -1) tradeSelection[key].push(id);
        } else {
            if (idx > -1) tradeSelection[key].splice(idx, 1);
            delete pickProtections[id];
        }
        if (side === 'your' && type === 'pick') renderProtectPanel();
        updateTradeFairness();
    }

    async function updateTradeFairness() {
        const partner = document.getElementById('trade-partner-select').value;
        const bar = document.getElementById('trade-fairness-bar');
        const label = document.getElementById('trade-fairness-label');
        if (!bar || !label) return;
        if (!partner || (!tradeSelection.your_players.length && !tradeSelection.your_picks.length &&
                          !tradeSelection.their_players.length && !tradeSelection.their_picks.length)) {
            bar.style.width = '0%'; label.innerText = '—';
            document.getElementById('trade-salary-out-a').innerText = '$0.0M';
            document.getElementById('trade-salary-out-b').innerText = '$0.0M';
            return;
        }
        const res = await fetch('/api/trade_preview', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
            team_a: state.user_team, team_b: partner, players_a: tradeSelection.your_players, picks_a: tradeSelection.your_picks,
            players_b: tradeSelection.their_players, picks_b: tradeSelection.their_picks, protections: pickProtections
        })});
        const data = await res.json();
        const pct = Math.max(0, Math.min(150, data.fairness_pct || 0));
        bar.style.width = `${Math.min(100, pct)}%`;
        bar.style.background = pct >= 88 ? '#22c55e' : pct >= 65 ? '#facc15' : '#ef4444';
        label.innerText = pct >= 88 ? `Fair for ${partner} (${pct}%)` : `${partner} undervalued at ${pct}% — sweeten the deal`;
        document.getElementById('trade-salary-out-a').innerText = `$${(data.salary_out_a || 0).toFixed(1)}M`;
        document.getElementById('trade-salary-out-b').innerText = `$${(data.salary_out_b || 0).toFixed(1)}M`;
    }

    // Lets the user protect any of THEIR OWN picks being sent out in the trade --
    // if the protection condition hits at draft time, the pick reverts to its
    // original owner and the other team gets a future 2nd rounder instead.
    function renderProtectPanel() {
        const panel = document.getElementById('trade-protect-panel');
        if (!panel) return;
        if (tradeSelection.your_picks.length === 0) { panel.innerHTML = ''; return; }
        let html = `<div class="small text-white-50 mb-1">Protect Your Outgoing Picks</div>`;
        tradeSelection.your_picks.forEach(pid => {
            const pk = state.draft_picks[pid];
            const label = pk ? pickLabel(pk) : pid;
            const current = pickProtections[pid] || 'None';
            html += `<div class="d-flex justify-content-between align-items-center mb-1">
                <span class="small">${label}</span>
                <select class="form-select form-select-sm bg-dark text-white border-secondary" style="width:auto;" onchange="pickProtections['${pid}']=this.value">
                    ${PROTECTION_TIERS.map(t => `<option value="${t}" ${t===current?'selected':''}>${t}</option>`).join('')}
                </select>
            </div>`;
        });
        panel.innerHTML = html;
    }

    async function proposeTrade() {
        const partner = document.getElementById('trade-partner-select').value;
        const tpeSel = document.getElementById('trade-tpe-select');
        const body = {
            team_a: state.user_team, team_b: partner,
            players_a: tradeSelection.your_players, picks_a: tradeSelection.your_picks,
            players_b: tradeSelection.their_players, picks_b: tradeSelection.their_picks,
            protections: pickProtections,
            tpe_id: tpeSel && tpeSel.value ? tpeSel.value : null  // UPGRADE: Trade Exceptions (TPE)
        };
        const res = await fetch('/api/propose_trade', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
        const data = await res.json();
        const panel = document.getElementById('trade-result-panel');
        const ctxTag = data.team_b_context ? ` <span class="badge bg-secondary">${partner} is a ${data.team_b_context}</span>` : '';
        if (data.accepted) {
            panel.innerHTML = `<div class="alert alert-success">✅ ${data.reason}${ctxTag} (Value sent: ${data.value_sent} | Value received: ${data.value_received})</div>`;
            currentTradePartner = null; // assets just changed teams -- force a clean rebuild
        } else {
            const counterTag = data.counter_suggestion ? `<div class="mt-2">💡 <b>Counter-offer idea:</b> ${data.counter_suggestion}</div>` : '';
            panel.innerHTML = `<div class="alert alert-danger">❌ ${data.reason}${ctxTag} ${data.value_sent !== undefined ? `(Value sent: ${data.value_sent} | Value received: ${data.value_received})` : ''}${counterTag}</div>
                <button class="btn btn-outline-accent btn-sm mt-2" onclick="autoSweetenTrade()">🤝 Auto-Sweeten My Offer</button>`;
        }
        await refreshState();
        renderTradeBuilder();
        renderTpePanel();
    }

    // UPGRADE: Negotiate / counter-offer. When a proposed trade is declined,
    // this automatically layers in additional assets from the user's roster
    // (cheapest/lowest-value first, so it doesn't reflexively throw in a
    // star) until the fairness meter clears 90%, then leaves the sweetened
    // package selected so the user can review it and hit Propose again.
    async function autoSweetenTrade() {
        const partner = document.getElementById('trade-partner-select').value;
        if (!partner) return;
        const locked = new Set((state.untradeable || {})[state.user_team] || []);
        const yours = teamAssets(state.user_team);
        const availablePicks = yours.picks
            .filter(pk => !tradeSelection.your_picks.includes(pk.id))
            .sort((a, b) => (a.value || 0) - (b.value || 0));
        const availablePlayers = yours.players
            .filter(p => !tradeSelection.your_players.includes(p.name) && !locked.has(p.name))
            .sort((a, b) => a.rating - b.rating);
        const candidates = [
            ...availablePicks.map(pk => ({type: 'pick', id: pk.id, label: pickLabel(pk)})),
            ...availablePlayers.map(p => ({type: 'player', id: p.name, label: p.name})),
        ];

        const checkFairness = async () => {
            const res = await fetch('/api/trade_preview', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
                team_b: partner, players_a: tradeSelection.your_players, picks_a: tradeSelection.your_picks,
                players_b: tradeSelection.their_players, picks_b: tradeSelection.their_picks, protections: pickProtections
            })});
            return (await res.json()).fairness_pct || 0;
        };

        const added = [];
        let fairness = await checkFairness();
        for (const c of candidates) {
            if (fairness >= 90) break;
            if (c.type === 'player') tradeSelection.your_players.push(c.id);
            else tradeSelection.your_picks.push(c.id);
            added.push(c.label);
            fairness = await checkFairness();
        }

        renderTradeBuilder();
        const panel = document.getElementById('trade-result-panel');
        if (fairness >= 90) {
            panel.innerHTML = `<div class="alert alert-info">🤝 Added ${added.join(', ')} to sweeten the deal -- fairness is now ${fairness.toFixed(1)}%. Review the updated offer and click Propose Trade again.</div>`;
        } else if (added.length) {
            panel.innerHTML = `<div class="alert alert-warning">Added everything available (${added.join(', ')}) but still only ${fairness.toFixed(1)}% fair -- ${partner} may want you to ask for less back instead.</div>`;
        } else {
            panel.innerHTML = `<div class="alert alert-warning">Nothing left on your roster to add. Try asking for less from ${partner} instead.</div>`;
        }
    }
    window.autoSweetenTrade = autoSweetenTrade;

    async function scoutOffer() {
        const res = await fetch('/api/scout_trade_offer', {method: 'POST'});
        const data = await res.json();
        await refreshState();
        renderPendingOffer();
        if (!data.offer) {
            document.getElementById('pending-offer-panel').innerHTML = `<div class="alert alert-secondary">No teams have offers for you right now — check back after simulating more games.</div>`;
        }
    }



    function playerWithOvr(name) {
        const p = getPlayerByName(name);
        if (!p) return name;
        const safeName = name.replace(/'/g, "\\'");
        return `<a class="player-link" onclick="showPlayerModal('${safeName}')">${name}</a> ` +
               `<small style="color:${attrColor(p.rating)}; font-weight:700;">(${p.rating} OVR)</small>`;
    }

    function renderPendingOffer() {
        const panel = document.getElementById('pending-offer-panel');
        const offer = state.pending_offer;
        if (!offer) { panel.innerHTML = ''; return; }

        // Build clickable player pills that open the player modal WITHOUT
        // the trade panel obscuring it. The player modal sits at z-index 1050
        // so it renders on top naturally when opened from here.
        const playerPill = (name) => {
            const p = state.players[name];
            if (!p) return `<b>${name}</b>`;
            const col = teamColor(p.team || 'Free Agent');
            const svg = playerSilhouetteSvg(name, p.position, col, 28);
            const safeName = name.replace(/'/g, "\\'");
            return `<span class="stat-subpanel d-inline-flex align-items-center gap-1 me-1 mb-1 px-2 py-1" style="cursor:pointer;" onclick="showPlayerModal('${safeName}')">
                ${svg} <span class="text-info fw-bold">${name}</span>
                <span class="badge bg-dark ms-1">${p.rating} OVR</span>
            </span>`;
        };

        const sendHtml  = offer.offer_players.map(playerPill).join('') || '<span class="text-white-50">—</span>';
        const sendPicks = offer.offer_picks.map(pid => state.draft_picks[pid] ? pickLabel(state.draft_picks[pid]) : pid).join(', ');
        const wantHtml  = offer.wants_players.map(playerPill).join('') || '<span class="text-white-50">—</span>';

        panel.innerHTML = `
            <div class="p-3 rounded border border-info" style="background:#0d1b2a;">
                <h5 class="mb-3 text-info">📨 Trade Offer from <b>${offer.from_team}</b>
                    <span class="text-muted small ms-2">${offer.context || ''}</span></h5>
                <div class="mb-2">
                    <div class="small text-white-50 mb-1">THEY SEND <span class="text-success">(value ${offer.offer_value ?? '—'})</span></div>
                    <div class="d-flex flex-wrap">${sendHtml}${sendPicks ? `<span class="jersey-badge ms-1">📋 ${sendPicks}</span>` : ''}</div>
                </div>
                <div class="mb-3">
                    <div class="small text-white-50 mb-1">THEY WANT <span class="text-warning">(value ${offer.want_value ?? '—'})</span></div>
                    <div class="d-flex flex-wrap">${wantHtml}</div>
                </div>
                <div class="d-flex gap-2 flex-wrap">
                    <button class="btn btn-success fw-bold px-4" onclick="respondOffer(true)">✅ Accept</button>
                    <button class="btn btn-outline-danger px-4" onclick="respondOffer(false)">❌ Decline</button>
                    <button class="btn btn-outline-warning px-4" onclick="openNegotiateBuilder()">🤝 Negotiate</button>
                </div>
                <div id="negotiate-panel" class="mt-3" style="display:none;"></div>
            </div>
        `;
    }

    // 2K-style Negotiate: instead of a black-box "AI sweetens it for you"
    // button, open the real trade builder pre-filled with exactly what was
    // offered, fully editable on both sides -- add/remove any player or pick,
    // then send it back as your own counter-proposal.
    async function openNegotiateBuilder() {
        const offer = state.pending_offer;
        if (!offer) return;
        const overlay = document.getElementById('offer-popup-overlay');
        const modalBox = document.getElementById('offer-popup-modal');
        if (overlay) overlay.style.display = 'none';
        if (modalBox) modalBox.style.display = 'none';
        pendingOfferModalOpen = false;
        await fetch('/api/respond_offer', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({accept: false})});
        await refreshState();
        switchTab('trade', document.querySelector(`button[onclick*="'trade'"]`));
        setTimeout(() => {
            switchTradeSubTab('center');
            const sel = document.getElementById('trade-partner-select');
            if (sel) sel.value = offer.from_team;
            onTradePartnerChange();
            setTimeout(() => {
                tradeSelection.their_players = (offer.offer_players || []).slice();
                tradeSelection.their_picks = (offer.offer_picks || []).slice();
                tradeSelection.your_players = (offer.wants_players || []).slice();
                tradeSelection.your_picks = (offer.wants_picks || []).slice();
                renderTradeBuilder();
                const panel = document.getElementById('trade-result-panel');
                if (panel) panel.innerHTML = `<div class="alert alert-info py-2 mb-0">🤝 Negotiating with ${offer.from_team} -- add or remove players/picks on either side below, then hit Propose Trade to send your counter.</div>`;
            }, 250);
        }, 100);
    }
    window.openNegotiateBuilder = openNegotiateBuilder;

    async function negotiateOffer(panelId, rerenderFn) {
        // Auto-sweeten the incoming offer: ask the AI to add another asset
        // or reduce what they're asking for. We re-use the autoSweetenTrade
        // pattern but from the receiving side -- counter by asking the AI
        // to add their cheapest available pick or bench player to the deal.
        panelId = panelId || 'negotiate-panel';
        rerenderFn = rerenderFn || renderPendingOffer;
        const offer = state.pending_offer;
        if (!offer) return;
        const panel = document.getElementById(panelId);
        if (!panel) return;
        panel.style.display = 'block';
        panel.innerHTML = `<div class="text-white-50 small">📞 Counter-offering to ${offer.from_team}...</div>`;

        const res = await fetch('/api/counter_offer', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({})});
        const data = await res.json();
        if (data.success) {
            panel.innerHTML = `<div class="alert alert-info py-2 mb-0">${data.message}</div>`;
            await refreshState();
            rerenderFn();
        } else {
            panel.innerHTML = `<div class="alert alert-warning py-2 mb-0">${data.reason || 'Counter-offer failed.'}</div>`;
        }
    }
    window.negotiateOffer = negotiateOffer;

    async function respondOffer(accept) {
        const res = await fetch('/api/respond_offer', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({accept})});
        const data = await res.json();
        await refreshState();
        renderTradeTab();
        if (data.status === 'rejected') {
            document.getElementById('pending-offer-panel').innerHTML =
                `<div class="alert alert-danger">Trade fell through: ${data.reason}</div>`;
        }
    }

    function renderTradeLog() {
        const el = document.getElementById('trade-log-list');
        if (!el) return;
        if (!state.trade_log || state.trade_log.length === 0) {
            el.innerHTML = '<p class="text-muted small">No trades yet this season.</p>';
            return;
        }
        el.innerHTML = state.trade_log.map(t => `
            <div class="p-2 mb-2 bg-dark rounded border border-secondary small">
                <b>${t.team_a}</b> traded ${t.sent_by_a.join(', ')} to <b>${t.team_b}</b> for ${t.sent_by_b.join(', ')}
            </div>
        `).join('');
    }

    // ===================== FRONT OFFICE (Offseason / Draft / Free Agency) =====================
    function mvpComposite(p) {
        const s = p.stats || {};
        const gp = s.GP || 0;
        if (gp < 5) return -999;
        const ppg = s.PTS/gp, rpg = s.REB/gp, apg = s.AST/gp, spg = (s.STL||0)/gp, bpg = (s.BLK||0)/gp;
        const t = state.teams[p.team];
        const winPct = t ? t.wins / Math.max(1, t.wins+t.losses) : 0.5;
        return ppg*1.0 + rpg*0.75 + apg*1.1 + spg*1.5 + bpg*1.5 + winPct*12;
    }

    function dpoyComposite(p) {
        const s = p.stats || {}, gp = s.GP || 0;
        if (gp < 5) return -999;
        const spg = (s.STL||0)/gp, bpg = (s.BLK||0)/gp;
        const interiorD = (p.attributes && p.attributes["Interior Defense"]) || 60;
        const perimD = (p.attributes && p.attributes["Perimeter Defense"]) || 60;
        const t = state.teams[p.team];
        const winPct = t ? t.wins / Math.max(1, t.wins+t.losses) : 0.5;
        return spg*2.2 + bpg*2.2 + (interiorD+perimD)*0.06 + winPct*6;
    }

    function mipComposite(p) {
        const s = p.stats || {}, gp = s.GP || 0;
        const ct = p.career_totals || {};
        if (gp < 5 || (ct.SEASONS||0) < 1 || (ct.GP||0) < 5) return -999;
        const curPpg = s.PTS/gp;
        const priorPpg = ct.PTS/Math.max(1, ct.GP);
        return (curPpg - priorPpg)*2.5 + Math.max(0, curPpg - priorPpg) * 0.5;
    }

    function royComposite(p) {
        if (p.draft_year !== state.year) return -999;
        const s = p.stats || {}, gp = s.GP || 0;
        if (gp < 3) return -999;
        return (s.PTS/gp)*1.0 + (s.REB/gp)*0.75 + (s.AST/gp)*1.1;
    }

    const COACH_SYSTEM_DESCS = {
        "7 Seconds or Less": "Up-tempo, three-happy pace-and-space system.",
        "Grit and Grind": "Bruising, defense-and-rebounding-first identity.",
        "Motion Read-and-React": "Constant off-ball movement, extra passing reads.",
        "Point-Center Hub": "Offense runs through a playmaking big at the elbow/post.",
        "Switch-Everything Defense": "Versatile, position-less perimeter defense.",
        "Small-Ball Spacing": "Shoots and spaces the floor from every position.",
        "Pound-the-Rock Post Offense": "Deliberate, post-heavy, low-turnover half-court system.",
        "Full-Court Chaos Press": "Relentless full-court pressure, forces mistakes.",
    };
    const AWARD_LADDERS = {
        mvp: {label: "🏆 MVP Ladder", fn: mvpComposite},
        dpoy: {label: "🛡️ DPOY Ladder", fn: dpoyComposite},
        mip: {label: "📈 MIP Ladder", fn: mipComposite},
        roy: {label: "🌟 ROY Ladder", fn: royComposite},
    };
    let activeAwardLadder = 'mvp';

    function switchAwardLadder(kind) {
        activeAwardLadder = kind;
        renderMvpLadder();
    }
    window.switchAwardLadder = switchAwardLadder;

    function renderMvpLadder() {
        const el = document.getElementById('stats-mvp-ladder');
        if (!el || state.stage !== 'regular_season') { if (el) el.innerHTML = ''; return; }
        const cfg = AWARD_LADDERS[activeAwardLadder];
        const candidates = Object.values(state.players).filter(p => !p.retired)
            .map(p => ({p, score: cfg.fn(p)})).filter(c => c.score > -999)
            .sort((a,b) => b.score - a.score).slice(0, 5);
        const tabsHtml = Object.entries(AWARD_LADDERS).map(([k, v]) =>
            `<button class="pm-tab-btn ${k===activeAwardLadder?'active':''}" onclick="switchAwardLadder('${k}')">${v.label.replace(/^\\S+\\s/, '')}</button>`
        ).join('');
        if (!candidates.length) {
            el.innerHTML = `<div class="dashboard-card">
                <h3 class="section-title mb-2">${cfg.label}</h3>
                <div class="d-flex border-bottom border-secondary mb-3">${tabsHtml}</div>
                <div class="text-white-50 small">Not enough games played yet to seed this race.</div>
            </div>`;
            return;
        }
        const medals = ['🥇', '🥈', '🥉'];
        const top3 = candidates.slice(0, 3);
        const podiumHtml = `<div class="lb-podium">
            ${top3.map((c, idx) => {
                const s = c.p.stats, gp = s.GP || 1;
                const safeName = c.p.name.replace(/'/g, "\\'");
                return `<div class="lb-podium-card rank-${idx+1}">
                    <div class="lb-medal">${medals[idx]}</div>
                    <div class="lb-avatar" style="background:${teamColor(c.p.team || '')};">${teamInitials(c.p.team || c.p.name)}</div>
                    <a class="player-link lb-podium-name d-block" onclick="showPlayerModal('${safeName}')">${c.p.name}${c.p.team===state.user_team?' ⭐':''}</a>
                    <div class="lb-podium-team">${c.p.team || 'FA'}</div>
                    <div class="lb-podium-stats">
                        <div><div class="lb-podium-stat-num">${(s.PTS/gp).toFixed(1)}</div><div class="lb-podium-stat-label">PPG</div></div>
                        <div><div class="lb-podium-stat-num">${(s.REB/gp).toFixed(1)}</div><div class="lb-podium-stat-label">RPG</div></div>
                        <div><div class="lb-podium-stat-num">${(s.AST/gp).toFixed(1)}</div><div class="lb-podium-stat-label">APG</div></div>
                    </div>
                </div>`;
            }).join('')}
        </div>`;
        const rest = candidates.slice(3);
        const restTableHtml = rest.length ? `<table class="table-dark-custom mt-3"><thead><tr><th>#</th><th>Player</th><th>Team</th><th>PPG</th><th>RPG</th><th>APG</th></tr></thead><tbody>
            ${rest.map((c, idx) => {
                const s = c.p.stats, gp = s.GP || 1;
                return `<tr><td>${idx+4}</td><td><a class="player-link" onclick="showPlayerModal('${c.p.name.replace(/'/g,"\\'")}')">${c.p.name}</a>${c.p.team===state.user_team?' ⭐':''}</td>
                    <td>${c.p.team}</td><td class="text-warning">${(s.PTS/gp).toFixed(1)}</td><td>${(s.REB/gp).toFixed(1)}</td><td>${(s.AST/gp).toFixed(1)}</td></tr>`;
            }).join('')}
            </tbody></table>` : '';
        el.innerHTML = `<div class="dashboard-card">
            <h3 class="section-title mb-2">${cfg.label}</h3>
            <div class="d-flex border-bottom border-secondary mb-3">${tabsHtml}</div>
            ${podiumHtml}
            ${restTableHtml}
        </div>`;
    }

    // UPGRADE: Coach hiring/firing UI + market, and the "recommended dials" hint.
    function renderCoachPanel() {
        const el = document.getElementById('fo-coach');
        if (!el) return;
        const coach = (state.coaches || {})[state.user_team];
        const market = state.coach_market || [];
        const recs = state.recommended_dials || {};
        const dialLabels = {offensive_priority: "Offense", defensive_priority: "Defense", pace: "Pace",
                             rebounding_style: "Rebounding", shooting_willingness: "Shooting"};
        let html = `<div class="dashboard-card"><h3 class="section-title mb-2">🧑‍💼 Coaching Staff</h3>`;
        if (coach) {
            const recHtml = Object.keys(recs).length
                ? `<div class="small text-info mt-2">💡 Recommended dials to activate ${coach.name}'s scheme bonus: ` +
                  Object.entries(recs).map(([field, val]) => `<b>${dialLabels[field] || field}: ${val}</b>`).join(', ') +
                  ` <span class="text-white-50">(set these in Team Management → Lineup)</span></div>`
                : '';
            html += `
                <div class="fo-coach-spotlight">
                    <div>
                        <a class="coach-link" onclick="showCoachModal('${coach.name.replace(/'/g,"\\'")}')"><b>${coach.name}</b></a>
                        <span class="fo-system-badge">${coach.system}</span>
                        <div class="small text-muted mt-1">${(COACH_SYSTEM_DESCS[coach.system] || '')} · ${coach.years_with_team} yr(s) with team</div>
                        ${recHtml}
                    </div>
                    <button class="btn btn-danger-custom btn-sm" onclick="fireCoach()">Fire Coach</button>
                </div>`;
        } else {
            html += `<div class="alert alert-warning">No head coach on staff -- no scheme bonus is active. Hire one below.</div>`;
        }
        html += `<h6 class="text-white-50 mt-3">Available Candidates</h6><div class="fo-candidate-grid">`;
        market.forEach(c => {
            html += `<div class="fo-candidate-card">
                    <div><a class="coach-link" onclick="showCoachModal('${c.name.replace(/'/g,"\\'")}')"><b>${c.name}</b></a><span class="fo-system-badge">${c.system}</span></div>
                    <button class="btn btn-outline-accent btn-sm" onclick="hireCoach('${c.id}')">Hire</button>
                </div>`;
        });
        html += `</div></div>`;
        el.innerHTML = html;
    }

    async function fireCoach() {
        const res = await fetch('/api/fire_coach', {method: 'POST'});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        renderCoachPanel();
    }
    window.fireCoach = fireCoach;

    async function hireCoach(candidateId) {
        const res = await fetch('/api/hire_coach', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({candidate_id: candidateId})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        renderCoachPanel();
    }
    window.hireCoach = hireCoach;

    // UPGRADE: Player morale/trade-request system -- shows active requests league-wide.
    function renderTradeRequestsPanel() {
        const el = document.getElementById('fo-trade-requests');
        if (!el) return;
        const reqs = state.trade_requests || [];
        if (!reqs.length) { el.innerHTML = ''; return; }
        el.innerHTML = `<div class="dashboard-card">
            <h3 class="section-title mb-2">📢 Trade Requests</h3>
            ${reqs.map(r => `<div class="p-2 mb-1 bg-dark rounded border border-warning small">
                <a class="player-link" onclick="showPlayerModal('${r.player}')">${r.player}</a>
                <span class="text-white-50">(${r.team}, ${r.rating} OVR)</span> has asked out, citing ${r.reason}.
            </div>`).join('')}
        </div>`;
    }

    // ─── SALARY ARBITRATION PANEL ─────────────────────────────────────────────
    function renderArbitrationPanel() {
        const el = document.getElementById('fo-arbitration');
        if (!el) return;
        const demands = state.pending_arbitration || [];
        if (!demands.length) { el.innerHTML = ''; return; }
        let html = `<h4 class="text-white-50 font-monospace mb-3">⚖️ Salary Arbitration</h4>
            <div class="alert alert-warning py-2 mb-3 small">Players outperforming their contracts have filed for arbitration. Resolve before the offseason ends.</div>
            <div class="row g-3">`;
        demands.forEach(d => {
            const compromise = ((d.current_salary + d.market_rate) / 2).toFixed(1);
            html += `<div class="col-md-6">
                <div class="p-3 rounded" style="background:#1f2937;border:1px solid #f97316;">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <a class="player-link fw-bold" onclick="showPlayerModal('${d.player.replace(/'/g,"\\'")}')">${d.player}</a>
                        <span class="badge bg-warning text-dark">⚖️ ARBI</span>
                    </div>
                    <div class="small mb-2">
                        <span class="text-white-50">Current: </span><span class="text-white">$${d.current_salary}M</span>
                        <span class="mx-2">→</span>
                        <span class="text-white-50">Market: </span><span class="text-warning">$${d.market_rate}M</span>
                        <span class="ms-2 text-info">${d.ppg} PPG · ${d.rating} OVR</span>
                    </div>
                    <div class="d-flex gap-2 flex-wrap">
                        <button class="btn btn-success btn-sm" onclick="resolveArb('${d.player.replace(/'/g,"\\'")}','accept')">✅ Accept $${d.market_rate}M</button>
                        <button class="btn btn-outline-warning btn-sm" onclick="resolveArb('${d.player.replace(/'/g,"\\'")}','compromise')">🤝 Split $${compromise}M</button>
                        <button class="btn btn-outline-danger btn-sm" onclick="resolveArb('${d.player.replace(/'/g,"\\'")}','decline')">❌ Decline</button>
                    </div>
                </div>
            </div>`;
        });
        el.innerHTML = html + '</div>';
    }
    async function resolveArb(playerName, choice) {
        const res = await fetch('/api/resolve_arbitration', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({player_name: playerName, choice})});
        const d = await res.json();
        if (!d.success) { showToast(d.reason, 'error'); return; }
        await refreshState();
        renderArbitrationPanel();
        renderRosterTab(true);
    }
    window.resolveArb = resolveArb;

    // ─── TEAM FACILITIES ────────────────────────────────────────────────────
    const FACILITY_DEPTS_JS = {
        Training:  {emoji:'🏋', desc:'Boosts G-League dev XP per game', bonusLabel: lvl => `${['1.00x','1.05x','1.12x','1.20x','1.30x'][lvl-1]} XP`, costs:[3,6,10,15]},
        Medical:   {emoji:'🏥', desc:'Reduces injury duration',          bonusLabel: lvl => `${['100%','90%','80%','68%','55%'][lvl-1]} duration`, costs:[3,6,10,15]},
        Scouting:  {emoji:'🔭', desc:'Bonus scout points per season',    bonusLabel: lvl => `+${[0,2,5,8,12][lvl-1]} pts`, costs:[2,5,8,12]},
        Analytics: {emoji:'📊', desc:'Better draft grade precision',     bonusLabel: lvl => `+${[0,5,10,16,25][lvl-1]} reveal`, costs:[2,5,8,12]},
    };

    async function renderFacilitiesPanel() {
        const el = document.getElementById('fo-facilities');
        if (!el) return;
        const fac = state.facilities || {};
        const cap = (state.teams[state.user_team] || {}).cap_space || 0;
        let html = `<h4 class="text-white-50 font-monospace mb-3">🏗 Team Facilities</h4>
            <div class="row g-3">`;
        for (const [dept, cfg] of Object.entries(FACILITY_DEPTS_JS)) {
            const lvl = fac[dept] || 1;
            const cost = cfg.costs[lvl - 1] ?? null;
            const maxed = lvl >= 5;
            const canAfford = cap >= (cost || 999);
            const stars = '⭐'.repeat(lvl) + '☆'.repeat(5 - lvl);
            html += `<div class="col-md-6">
                <div class="p-3 bg-dark rounded border border-secondary">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span class="fw-bold text-white">${cfg.emoji} ${dept}</span>
                        <span class="small">${stars}</span>
                    </div>
                    <div class="small text-white-50 mb-2">${cfg.desc} · <span class="text-info">${cfg.bonusLabel(lvl)}</span></div>
                    ${maxed
                        ? `<span class="badge bg-success">MAX LEVEL</span>`
                        : `<button class="btn btn-outline-accent btn-sm" onclick="upgradeFacility('${dept}')" ${!canAfford ? 'disabled' : ''}>
                            Upgrade to Lv${lvl+1} — $${cost}M ${!canAfford ? '(need more cap space)' : ''}
                           </button>`}
                </div>
            </div>`;
        }
        html += '</div>';
        el.innerHTML = html;
    }

    async function upgradeFacility(dept) {
        const res = await fetch('/api/upgrade_facility', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({dept})});
        const d = await res.json();
        if (!d.success) { showToast(d.reason, 'error'); return; }
        await refreshState();
        renderFacilitiesPanel();
    }
    window.upgradeFacility = upgradeFacility;

    // ─── ARENA CUSTOMIZATION ─────────────────────────────────────────────────
    const ARENA_COURTS_JS   = ['Classic Hardwood','Dark Court','City Edition','Throwback','Championship Edition'];
    const ARENA_VIBES_JS    = ['Neutral','Loud','Electric','Intimidating','Homey'];

    function renderArenaPanel() {
        const el = document.getElementById('fo-arena');
        if (!el) return;
        const arena = state.arena || {};
        el.innerHTML = `<h4 class="text-white-50 font-monospace mb-3 mt-2">🏟 Arena Customization</h4>
            <div class="row g-3">
                <div class="col-md-4">
                    <label class="small text-white-50 mb-1">Court Style</label>
                    <select class="form-select bg-dark text-white border-secondary" onchange="setArena('court', this.value)">
                        ${ARENA_COURTS_JS.map(c => `<option ${arena.court===c?'selected':''}>${c}</option>`).join('')}
                    </select>
                </div>
                <div class="col-md-4">
                    <label class="small text-white-50 mb-1">Crowd Vibe</label>
                    <select class="form-select bg-dark text-white border-secondary" onchange="setArena('vibe', this.value)">
                        ${ARENA_VIBES_JS.map(v => `<option ${arena.vibe===v?'selected':''}>${v}</option>`).join('')}
                    </select>
                </div>
                <div class="col-md-4">
                    <label class="small text-white-50 mb-1">Team Nickname / Tagline</label>
                    <input class="form-control bg-dark text-white border-secondary" maxlength="40" placeholder="e.g. 'The City'" value="${arena.nickname||''}" oninput="setArena('nickname', this.value)">
                </div>
            </div>
            <div class="stat-subpanel mt-3">
                <span class="text-white-50 small">Current: </span>
                <span class="text-white fw-bold">${arena.court||'Classic Hardwood'}</span>
                <span class="mx-2 text-white-50">·</span>
                <span class="text-white">${arena.vibe||'Neutral'} Crowd</span>
                ${arena.nickname ? `<span class="mx-2 text-white-50">·</span><span class="text-info fst-italic">"${arena.nickname}"</span>` : ''}
            </div>`;
    }

    let arenaDebounce = null;
    async function setArena(key, val) {
        clearTimeout(arenaDebounce);
        arenaDebounce = setTimeout(async () => {
            await fetch('/api/set_arena', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({[key]: val})});
            await refreshState();
            renderArenaPanel();
        }, 400);
    }
    window.setArena = setArena;

    function renderFrontOfficeTab() {
        renderScoutingHub();
        renderCoachPanel();
        renderTradeRequestsPanel();
        renderFrontOfficeExtras();
        renderFacilitiesPanel();
        renderArenaPanel();
        renderArbitrationPanel();

        const el = document.getElementById('fo-content');
        if (!el) return;

        if (state.stage === 'regular_season') {
            el.innerHTML = `<p class="text-white-50">The season is underway. Retirements, progression, the draft, and free agency unlock once the playoffs conclude -- but scouting never stops, see below.</p>`;
        } else if (state.stage === 'play_in') {
            el.innerHTML = `<p class="text-white-50">The Play-In Tournament is deciding the final two seeds in each conference. Check the 🏆 Playoffs tab to run it.</p>`;
        } else if (state.stage === 'playoffs') {
            el.innerHTML = `<p class="text-white-50">Playoffs are in progress. Finish the postseason to open the offseason hub -- but scouting never stops, see below.</p>`;
        } else if (state.stage === 'offseason') {
            renderOffseasonPanel(el);
        } else if (state.stage === 'draft') {
            renderDraftPanel(el);
        } else if (state.stage === 'free_agency') {
            const cap = state.teams[state.user_team].cap_space;
            const userRosterSize = Object.values(state.players).filter(p => p.team === state.user_team && !p.retired).length;
            const over = userRosterSize > 15;
            el.innerHTML = `
                <div class="alert alert-info">Free agency is open! Head to the <b>💰 Free Agency</b> tab to sign players (cap space: $${cap}M).</div>
                <div class="${over ? 'alert alert-danger' : 'alert alert-secondary'} mb-3">
                    Roster: <b>${userRosterSize} / 15</b>${over ? ` — waive ${userRosterSize - 15} player(s) in 🧑‍💼 Team Management → Lineup before the season can start.` : ' — you are eligible to start the season.'}
                </div>
                <div class="d-flex gap-2">
                    <button class="btn btn-outline-info" onclick="simulateFAPeriod()">🤖 Simulate League FA Moves</button>
                    <button class="btn btn-accent" ${over ? 'disabled title="Waive players down to 15 first"' : ''} onclick="startNewSeason()">🏀 Start New Season</button>
                </div>
                <div id="fa-signed-msg" class="mt-3"></div>
            `;
        }
    }

    // ===================== UPGRADE BATCH 2: FRONT OFFICE EXTRAS =====================
    async function renderFrontOfficeExtras() {
        const el = document.getElementById('fo-extras');
        if (!el) return;
        const userTeam = state.user_team;
        const myColor = (state.team_colors && state.team_colors[userTeam] && state.team_colors[userTeam].primary) || teamColor(userTeam);
        const agg = (state.trade_aggressiveness !== undefined) ? state.trade_aggressiveness : 50;

        const [trustRes, capRes, rivalRes, injRes] = await Promise.all([
            fetch('/api/gm_trust').then(r => r.json()),
            fetch('/api/cap_projection?team=' + encodeURIComponent(userTeam)).then(r => r.json()),
            fetch('/api/rivalries?team=' + encodeURIComponent(userTeam)).then(r => r.json()),
            fetch('/api/injury_report').then(r => r.json()),
        ]);

        const trustRows = Object.entries(trustRes.trust || {}).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([t, v]) => {
            const color = v >= 65 ? '#10b981' : v >= 40 ? '#eab308' : '#ef4444';
            // UPGRADE: Show rival GM archetype alongside trust score
            const archetypeName = (state.gm_archetypes || {})[t];
            const archetypes = {
                "Dealmaker":       {emoji:"📞", desc:"Loves blockbusters"},
                "Analytics GM":    {emoji:"📊", desc:"Wants fair deals"},
                "Win-Now GM":      {emoji:"🏆", desc:"Mortgages future"},
                "Patient Builder": {emoji:"🌱", desc:"Trusts the process"},
                "Loyalist":        {emoji:"🤝", desc:"Keeps his guys"},
            };
            const arch = archetypes[archetypeName] || {};
            const archBadge = arch.emoji ? `<span title="${archetypeName}: ${arch.desc}" class="text-white-50 ms-1" style="font-size:0.75rem;">${arch.emoji}</span>` : '';
            return `<div class="d-flex justify-content-between small mb-1"><span>${teamLogoHtml(t, 16)} ${t}${archBadge}</span><span style="color:${color};font-weight:700;">${Math.round(v)}</span></div>`;
        }).join('') || '<p class="text-white-50 small">No trade history with other front offices yet.</p>';

        const capRows = (capRes.projection || []).map(row => `
            <tr><td>${row.year}</td><td>$${row.committed}M</td><td class="${row.cap_space_est < 0 ? 'text-danger' : 'text-success'}">$${row.cap_space_est}M</td><td>${row.contracts_expiring}</td></tr>
        `).join('');

        const rivalRows = (rivalRes.rivalries || []).map(r => {
            const heat = r.heat || 0;
            const heatPct = Math.min(100, heat);
            const heatColor = heat >= 80 ? '#ef4444' : heat >= 55 ? '#f97316' : heat >= 30 ? '#facc15' : '#9db4d9';
            const intensityEmojis = heat >= 80 ? '🔥🔥🔥' : heat >= 55 ? '🔥🔥' : heat >= 30 ? '🔥' : '😤';
            const latestMoment = r.moments && r.moments.length ? r.moments[r.moments.length-1].text : null;
            const seriesA = (r.series_wins || {})[r.teams && r.teams[0]] || 0;
            const seriesB = (r.series_wins || {})[r.teams && r.teams[1]] || 0;
            return `<div class="mb-3 p-2 rounded" style="background:#1f2937;border-left:3px solid ${heatColor};">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span class="fw-bold text-white">${intensityEmojis} ${r.team}</span>
                    <span class="text-white-50 small">${r.meetings} games · ${r.playoff_meetings || 0} playoff</span>
                </div>
                <div class="progress mb-1" style="height:5px;background:#334155;">
                    <div style="width:${heatPct}%;height:100%;background:${heatColor};border-radius:3px;"></div>
                </div>
                ${seriesA || seriesB ? `<div class="small text-white-50">All-time: ${seriesA}–${seriesB}</div>` : ''}
                ${latestMoment ? `<div class="small text-warning mt-1 fst-italic">"${latestMoment}"</div>` : ''}
            </div>`;
        }).join('') || '<p class="text-white-50 small">No rivalries yet — playoff meetings build intensity fast.</p>';

        // Team Needs panel
        const roster = Object.values(state.players).filter(p => p.team === state.user_team && !p.retired);
        const posCounts = {PG:0, SG:0, SF:0, PF:0, C:0};
        roster.forEach(p => {
            if (posCounts.hasOwnProperty(p.position)) posCounts[p.position]++;
            if (p.secondary_position && posCounts.hasOwnProperty(p.secondary_position)) posCounts[p.secondary_position] += 0.5;
        });
        const needStars = (cnt) => {
            const need = Math.max(0, 3 - Math.round(cnt));
            return '★'.repeat(need) + '☆'.repeat(3 - need);
        };
        const teamNeedsHtml = Object.entries(posCounts).map(([pos, cnt]) => {
            const need = Math.max(0, 3 - Math.round(cnt));
            const color = need >= 3 ? '#ef4444' : need >= 2 ? '#f97316' : need >= 1 ? '#facc15' : '#22c55e';
            return `<div class="d-flex justify-content-between align-items-center mb-1 small">
                <span class="text-white fw-bold">${pos}</span>
                <span style="color:${color};">${needStars(cnt)}</span>
                <span class="text-white-50">${Math.round(cnt)} rostered</span>
                <span class="badge" style="background:${color};color:#000;">${need >= 3 ? 'CRITICAL' : need >= 2 ? 'NEED' : need >= 1 ? 'DEPTH' : 'OK'}</span>
            </div>`;
        }).join('');

        const injuredNow = (injRes.report || []);
        const injRows = injuredNow.slice(0, 12).map(p => `
            <div class="p-2 mb-2 bg-dark rounded border border-secondary">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <a class="player-link fw-bold" onclick="showPlayerModal('${p.name.replace(/'/g,"\\'")}')">
                            ${p.name}</a> <span class="text-white-50 small">(${p.team})</span>
                        <div class="small text-danger mt-1">${p.description || '—'}</div>
                        <div class="d-flex gap-2 mt-1 flex-wrap">
                            <span class="badge" style="background:${p.status_color||'#999'};color:#000;">${p.status||'Out'}</span>
                            ${p.region ? `<span class="badge bg-secondary">${p.region}</span>` : ''}
                            ${p.reinjury_risk ? `<span class="badge bg-warning text-dark">⚠ Re-injury Risk</span>` : ''}
                            ${p.injury_prone ? `<span class="badge bg-danger">🩹 Injury Prone</span>` : ''}
                        </div>
                    </div>
                    <div class="text-end small">
                        <div class="text-white-50">${p.games_remaining}g out</div>
                        <div class="text-success">Return: ~${p.return_probability}%</div>
                    </div>
                </div>
            </div>`).join('') || '<p class="text-white-50 small">No injuries league-wide right now.</p>';

        const staff = (state.assistant_coaches && state.assistant_coaches[userTeam]) || [];
        const staffRows = staff.map(c => `
            <div class="d-flex justify-content-between align-items-center small mb-1">
                <span>${c.name} <span class="text-white-50">(${c.role}, +${c.bonus})</span></span>
                <button class="btn btn-outline-accent" style="padding:2px 8px;font-size:0.7rem;" onclick="fireAssistant('${c.name.replace(/'/g, "\\'")}')">Fire</button>
            </div>`).join('') || '<p class="text-white-50 small">No assistant coaches hired yet.</p>';
        const marketOptions = (state.assistant_coach_market || []).map(c =>
            `<option value="${c.name}">${c.name} — ${c.role} (+${c.bonus})</option>`).join('');

        const practicePts = (state.practice_points && state.practice_points[userTeam]) || 0;
        const practiceSection = state.stage === 'offseason' ? `
            <div class="mt-3 pt-3 border-top border-secondary">
                <h6 class="text-white-50">🏋️ Practice Focus (${practicePts} point${practicePts === 1 ? '' : 's'} left this offseason)</h6>
                <div class="d-flex gap-2 flex-wrap">
                    <select id="practice-player" class="form-select form-select-sm" style="width:auto;">
                        ${team_roster_options(userTeam)}
                    </select>
                    <select id="practice-focus" class="form-select form-select-sm" style="width:auto;">
                        <option>Shooting</option><option>Finishing</option><option>Playmaking</option><option>Defense</option><option>Physical</option>
                    </select>
                    <input id="practice-pts" type="number" min="1" max="${practicePts}" value="1" class="form-control form-control-sm" style="width:70px;">
                    <button class="btn btn-accent btn-sm" onclick="allocatePracticePoints()">Assign</button>
                </div>
                <div id="practice-msg" class="small mt-2"></div>
            </div>` : '';

        el.innerHTML = `
            <div class="row g-3">
                <div class="col-md-6">
                    <div class="dashboard-card">
                        <h5 class="section-title">🎨 Team Colors</h5>
                        <div class="d-flex align-items-center gap-3">
                            <input type="color" id="team-color-picker" value="${myColor}" style="width:50px;height:36px;border:none;background:none;">
                            <button class="btn btn-outline-accent btn-sm" onclick="saveTeamColor()">Save Color</button>
                            <span class="team-logo-mini" style="width:28px;height:28px;background:${myColor};"></span>
                        </div>
                        <h6 class="text-white-50 mt-3">🤝 AI Trade Aggressiveness (league-wide): <span id="agg-val">${Math.round(agg)}</span></h6>
                        <input type="range" min="0" max="100" value="${agg}" class="form-range" id="agg-slider" oninput="document.getElementById('agg-val').innerText = this.value" onchange="setTradeAggressiveness(this.value)">
                        <p class="text-white-50 small mb-0">Higher = AI teams accept worse deals league-wide. Lower = they hold out for fair value.</p>
                    </div>
                    <div class="dashboard-card mt-3">
                        <h5 class="section-title">🧑‍🏫 Coaching Staff</h5>
                        ${staffRows}
                        ${marketOptions ? `<div class="d-flex gap-2 mt-2"><select id="assistant-market" class="form-select form-select-sm">${marketOptions}</select><button class="btn btn-accent btn-sm" onclick="hireAssistant()">Hire</button></div>` : '<p class="text-white-50 small">No candidates currently on the market.</p>'}
                    </div>
                    ${practiceSection}
                </div>
                <div class="col-md-6">
                    <div class="dashboard-card">
                        <h5 class="section-title">🤝 GM Trust (other front offices)</h5>
                        ${trustRows}
                    </div>
                    <div class="dashboard-card mt-3">
                        <h5 class="section-title">💵 Cap Projection</h5>
                        <table class="table-dark-custom"><thead><tr><th>Year</th><th>Committed</th><th>Cap Space Est.</th><th>Expiring</th></tr></thead><tbody>${capRows}</tbody></table>
                    </div>
                    <div class="dashboard-card mt-3">
                        <h5 class="section-title">🔥 Rivalries</h5>
                        ${rivalRows}
                    </div>
                    <div class="dashboard-card mt-3" id="team-needs-card">
                        <h5 class="section-title">📋 Team Needs</h5>
                        ${teamNeedsHtml}
                    </div>
                    <div class="dashboard-card mt-3">
                        <h5 class="section-title">🩹 League Injury Report</h5>
                        ${injRows}
                        <a href="/api/export_stats_csv" class="btn btn-outline-accent btn-sm mt-2">⬇ Export Season Stats (CSV)</a>
                    </div>
                </div>
            </div>
        `;
    }
    window.renderFrontOfficeExtras = renderFrontOfficeExtras;

    function team_roster_options(teamName) {
        return Object.values(state.players).filter(p => p.team === teamName && !p.retired)
            .map(p => `<option value="${p.name}">${p.name} (${p.rating} OVR)</option>`).join('');
    }

    async function saveTeamColor() {
        const primary = document.getElementById('team-color-picker').value;
        const res = await fetch('/api/set_team_colors', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({team: state.user_team, primary})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        renderFrontOfficeExtras();
    }
    window.saveTeamColor = saveTeamColor;

    async function setTradeAggressiveness(value) {
        const res = await fetch('/api/set_trade_aggressiveness', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({value})});
        const data = await res.json();
        if (!data.success) showToast(data.reason, 'error');
        await refreshState();
    }
    window.setTradeAggressiveness = setTradeAggressiveness;

    async function hireAssistant() {
        const name = document.getElementById('assistant-market').value;
        const res = await fetch('/api/hire_assistant', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        renderFrontOfficeExtras();
    }
    window.hireAssistant = hireAssistant;

    async function fireAssistant(name) {
        if (!confirm(`Fire ${name} from your coaching staff?`)) return;
        const res = await fetch('/api/fire_assistant', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        renderFrontOfficeExtras();
    }
    window.fireAssistant = fireAssistant;

    async function allocatePracticePoints() {
        const player_name = document.getElementById('practice-player').value;
        const focus = document.getElementById('practice-focus').value;
        const points = document.getElementById('practice-pts').value;
        const res = await fetch('/api/allocate_practice_points', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({player_name, focus, points})});
        const data = await res.json();
        const msg = document.getElementById('practice-msg');
        if (!data.success) { msg.innerHTML = `<span class="text-danger">${data.reason}</span>`; return; }
        msg.innerHTML = `<span class="text-success">Assigned! ${points} pt(s) left: ${data.remaining}. New rating: ${data.new_rating}.</span>`;
        await refreshState();
        renderFrontOfficeExtras();
    }
    window.allocatePracticePoints = allocatePracticePoints;

    async function editProspect(oldName) {
        const newName = prompt(`Rename prospect "${oldName}" to (leave blank to keep name):`, oldName);
        const newPosition = prompt(`Position for this prospect (PG/SG/SF/PF/C, leave blank to keep current):`, '');
        if (newName === null && !newPosition) return;
        const body = {old_name: oldName};
        if (newName && newName.trim() && newName.trim() !== oldName) body.new_name = newName.trim();
        if (newPosition && newPosition.trim()) body.new_position = newPosition.trim().toUpperCase();
        const res = await fetch('/api/edit_draft_prospect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        renderScoutingHub();
    }
    window.editProspect = editProspect;

    async function scoutProspect(name, points) {
        const res = await fetch('/api/scout_prospect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, points})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        renderScoutingHub();
    }
    window.scoutProspect = scoutProspect;

    // UPGRADE: Scouting "assign all points" quick-action.
    async function scoutTopProspects(n) {
        const res = await fetch('/api/scout_top_prospects', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({n})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        await refreshState();
        renderScoutingHub();
    }
    window.scoutTopProspects = scoutTopProspects;

    // UPGRADE: Scouting combine drills. Each prospect card in the scouting
    // hub shows which drills have been run (result displayed) and which
    // haven't (button to run them). Results are noisy measurements of the
    // underlying attribute, so "Vertical: 81" on a player whose true
    // Athleticism is 74 is plausible but misleading -- just like the real
    // combine. Running all five drills costs 5 scout points total and
    // tightens the OVR confidence interval shown on the card.
    const COMBINE_DRILLS = ['Vertical','Sprint','Agility','Shooting','Strength'];
    const DRILL_LABELS = {Vertical:'⬆️ Vertical', Sprint:'💨 Sprint', Agility:'🔄 Agility', Shooting:'🎯 Shooting', Strength:'💪 Strength'};

    function cssSafeTC(s) { return s.replace(/[^a-zA-Z0-9]/g, '_'); }
    function toggleProspectDetails(safeId) {
        const el = document.getElementById(`prospect-details-${safeId}`);
        const label = document.getElementById(`prospect-details-toggle-${safeId}`);
        if (!el) return;
        const opening = el.style.display === 'none';
        el.style.display = opening ? 'block' : 'none';
        if (label) label.textContent = (opening ? '▾' : '▸') + ' Details';
    }
    window.toggleProspectDetails = toggleProspectDetails;

    function renderCombineButtons(prospectName) {
        const results = (state.combine_results || {})[prospectName] || {};
        const allDone = COMBINE_DRILLS.every(d => d in results);
        if (allDone) {
            return `<div class="d-flex flex-wrap gap-1 mt-1">` +
                COMBINE_DRILLS.map(d => `<span class="badge bg-secondary" style="font-size:0.6rem;" title="${results[d].desc}">${DRILL_LABELS[d]}: <b>${results[d].measured}</b></span>`).join('') +
                `</div>`;
        }
        const notRun = COMBINE_DRILLS.filter(d => !(d in results));
        const doneHtml = COMBINE_DRILLS.filter(d => d in results)
            .map(d => `<span class="badge bg-secondary" style="font-size:0.6rem;">${DRILL_LABELS[d]}: <b>${results[d].measured}</b></span>`).join('');
        const btnHtml = notRun.map(d =>
            `<button class="btn py-0 px-1 btn-outline-info" style="font-size:0.6rem;" onclick="runCombineDrill('${prospectName.replace(/'/g,"\\'")}','${d}')" title="Run ${d} drill (costs 1 scout point)">${DRILL_LABELS[d]}</button>`
        ).join('');
        return `<div class="d-flex flex-wrap gap-1 mt-1">${doneHtml}${btnHtml}</div>`;
    }

    async function runCombineDrill(prospectName, drillName) {
        const res = await fetch('/api/run_combine_drill', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({prospect_name: prospectName, drill_name: drillName})});
        const data = await res.json();
        if (!data.success) { showToast(data.reason, 'error'); return; }
        const r = data.result;
        await refreshState();
        renderScoutingHub();
        pushLocalNotification(`${prospectName} — ${r.drill}: ${r.measured} (${r.desc}). ${data.points_remaining} scout pts left.`);
    }
    window.runCombineDrill = runCombineDrill;
    // to set your own ranking vs the generated grades. Persists in memory
    // across scouting hub re-renders for the life of the session.
    let customBigBoard = [];      // ordered list of prospect names (user's board)
    let bigBoardEditMode = false;
    let bigBoardDragSrc = null;

    function toggleBigBoardEdit() {
        bigBoardEditMode = !bigBoardEditMode;
        renderScoutingHub();
    }
    window.toggleBigBoardEdit = toggleBigBoardEdit;

    function resetBigBoard() {
        customBigBoard = [];
        bigBoardEditMode = false;
        renderScoutingHub();
    }
    window.resetBigBoard = resetBigBoard;

    function onBigBoardDragStart(e) {
        bigBoardDragSrc = e.currentTarget.dataset.prospect;
        e.dataTransfer.effectAllowed = 'move';
    }
    window.onBigBoardDragStart = onBigBoardDragStart;

    function onBigBoardDrop(e) {
        e.preventDefault();
        const dest = e.currentTarget.dataset.prospect;
        if (!bigBoardDragSrc || bigBoardDragSrc === dest) return;
        // Rebuild full ordered list from the currently displayed order, then
        // splice src out and insert it before dest.
        const grid = document.getElementById('draft-bigboard-grid');
        if (!grid) return;
        const cards = [...grid.querySelectorAll('[data-prospect]')].map(el => el.dataset.prospect);
        let board = customBigBoard.length ? [...customBigBoard] : [...cards];
        // Ensure all current prospects are represented
        cards.forEach(n => { if (!board.includes(n)) board.push(n); });
        const srcIdx = board.indexOf(bigBoardDragSrc);
        const dstIdx = board.indexOf(dest);
        if (srcIdx !== -1) board.splice(srcIdx, 1);
        board.splice(dstIdx, 0, bigBoardDragSrc);
        customBigBoard = board;
        renderScoutingHub();
    }
    window.onBigBoardDrop = onBigBoardDrop;

    // Scouting is always available, from day one of the season, just like a real
    // front office would keep tabs on next year's draft class and pending free
    // agents year-round -- not just once the offseason officially opens.
    async function renderScoutingHub() {
        const hub = document.getElementById('fo-scouting');
        if (!hub) return;

        const prospects = (state.draft_class || []).slice().sort((a, b) => {
            // UPGRADE: Custom draft big board -- if the GM has reordered the board,
            // use their custom ranking; otherwise default to the generated grades.
            const aCustom = customBigBoard.indexOf(a.name);
            const bCustom = customBigBoard.indexOf(b.name);
            if (aCustom !== -1 && bCustom !== -1) return aCustom - bCustom;
            if (aCustom !== -1) return -1;
            if (bCustom !== -1) return 1;
            const aScore = a.rating != null ? a.rating : (a.overall_range.low + a.overall_range.high) / 2;
            const bScore = b.rating != null ? b.rating : (b.overall_range.low + b.overall_range.high) / 2;
            return bScore - aScore;
        });
        const draftLocked = state.draft && state.draft.active;
        const scoutPtsLeft = state.scout_points_remaining != null ? state.scout_points_remaining : 0;

        // 2K-style regional scouting: allocate scouting points across real
        // prospect pipelines (EuroLeague, NCAA, G-League, etc.) -- the more
        // invested in a region, the tighter the fog-of-war grade band gets
        // on every prospect scouted out of it.
        let strengthBadge = '';
        try {
            const sRes = await fetch('/api/draft_class_strength');
            const sData = await sRes.json();
            if (sData && sData.class_grade) strengthBadge = ` <span class="badge bg-info text-dark" title="Overall class strength">Class Grade: ${sData.class_grade}</span>`;
        } catch (e) { /* non-critical */ }

        let regionHtml = `<div class="stat-subpanel mb-3">
            <div class="d-flex justify-content-between align-items-center mb-2">
                <h6 class="text-info m-0">🌍 Regional Scouting${strengthBadge}</h6>
                <span class="small text-white-50">${scoutPtsLeft} scouting pts available</span>
            </div>
            <div class="small text-white-50 mb-2">
                More points in a region = tighter, more accurate grades on prospects from there (fewer "68-88 OVR" wide guesses, more real numbers).
                Don't want to micromanage six regions? Just hit Auto-Scout below.
            </div>
            <button class="btn btn-sm btn-accent mb-2" onclick="autoInvestScouting()" ${scoutPtsLeft <= 0 ? 'disabled' : ''}>🪄 Auto-Scout (spend all ${scoutPtsLeft} pts where it helps most)</button>
            <div class="small text-white-50" style="cursor:pointer;" onclick="toggleManualScoutingRegions()">
                <span id="manual-scouting-toggle-label">▸ Manual region-by-region control</span>
            </div>
            <div class="row g-2 mt-1" id="manual-scouting-regions" style="display:none;">`;
        ['EuroLeague', 'G-League', 'NCAA', 'Australia/NBL', 'China/CBA', 'Africa/BAL'].forEach(region => {
            const invested = ((state.scouting_regions || {})[state.user_team] || {})[region] || 0;
            regionHtml += `<div class="col-md-4 col-6">
                <div class="small text-white-50">${region} <span class="text-info">(${invested} pts)</span></div>
                <div class="d-flex gap-1">
                    <button class="btn btn-outline-accent btn-sm py-0 px-2" style="font-size:0.7rem;" onclick="investScoutingRegion('${region}', 1)" ${scoutPtsLeft <= 0 ? 'disabled' : ''}>+1</button>
                    <button class="btn btn-outline-accent btn-sm py-0 px-2" style="font-size:0.7rem;" onclick="investScoutingRegion('${region}', 5)" ${scoutPtsLeft < 5 ? 'disabled' : ''}>+5</button>
                </div>
            </div>`;
        });
        regionHtml += `</div></div>`;

        let prospectHtml = `<div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
            <h5 class="text-white-50 mt-2">📋 ${state.year} Draft Prospects Board <small class="text-muted">(${prospects.length} scouted)</small></h5>
            <div class="d-flex gap-2">
                <button class="btn btn-sm btn-outline-info" onclick="scoutTopProspects(5)" ${scoutPtsLeft <= 0 ? 'disabled' : ''}>🔎 Scout Top 5 Remaining</button>
                <button class="btn btn-sm ${bigBoardEditMode ? 'btn-warning' : 'btn-outline-accent'}" onclick="toggleBigBoardEdit()" title="Toggle custom big board reordering">📝 ${bigBoardEditMode ? 'Done' : 'My Board'}</button>
                ${customBigBoard.length > 0 ? `<button class="btn btn-sm btn-outline-danger" onclick="resetBigBoard()">↩ Reset</button>` : ''}
                <div class="dropdown d-inline-block">
                    <button class="btn btn-sm btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown">⚙ More Tools</button>
                    <ul class="dropdown-menu dropdown-menu-dark dropdown-menu-end">
                        <li><a class="dropdown-item" href="#" onclick="runDraftLotteryCeremony();return false;">🎱 Run Draft Lottery Ceremony</a></li>
                        <li><a class="dropdown-item" href="#" onclick="developAcademyProspect();return false;">🏫 Develop Academy Prospect</a></li>
                        <li><a class="dropdown-item" href="#" onclick="openRedraftSimulator();return false;">🔁 Redraft a Past Class</a></li>
                    </ul>
                </div>
            </div>
        </div>
        ${bigBoardEditMode ? `<div class="alert alert-info py-1 px-2 small mb-2">🖱️ Drag and drop prospect cards below to reorder your personal big board. Your order is saved automatically.</div>` : ''}
        `;
        prospectHtml += `<div class="row mb-2" style="max-height:380px; overflow-y:auto;" id="draft-bigboard-grid" ondragover="event.preventDefault()">`;
        prospects.slice(0, 20).forEach((p, idx) => {
            const ovrDisplay = p.rating != null ? p.rating : `${p.overall_range.low}-${p.overall_range.high}`;
            const potDisplay = p.potential_grade;
            const canScoutMore = p.scout_points_invested < 10;
            const customRank = customBigBoard.indexOf(p.name);
            const rankBadge = customRank !== -1 ? `<span class="badge bg-warning text-dark me-1" style="font-size:0.6rem;">MY #${customRank+1}</span>` : '';
            const safeName = p.name.replace(/'/g, "\\'");
            // UI SIMPLIFICATION PASS: the main board used to show every
            // prospect's potential grade, projection, scouting-confidence
            // bar, and all 5 individual combine-drill buttons inline, all
            // the time -- for 20 prospects at once that's a wall of detail
            // that buries the one thing you actually scan the board for
            // (name / OVR / age / position). Everything else now lives
            // behind a per-card "Details" toggle, collapsed by default.
            prospectHtml += `<div class="col-md-6 col-lg-3 mb-2" draggable="${bigBoardEditMode}" data-prospect="${p.name}"
                ondragstart="onBigBoardDragStart(event)" ondrop="onBigBoardDrop(event)" ondragover="event.preventDefault()">
                <div class="prospect-card${bigBoardEditMode ? ' border-warning' : ''}" style="${bigBoardEditMode ? 'cursor:grab;' : ''}">
                    <div class="d-flex justify-content-between align-items-start">
                        <a class="player-link" onclick="showPlayerModal('${safeName}')">${rankBadge}#${idx + 1} ${p.name}</a>
                        ${!draftLocked ? `<button class="btn btn-sm p-0 px-1 text-white-50" style="background:none;border:none;" title="Edit prospect" onclick="editProspect('${safeName}')">✏️</button>` : ''}
                    </div>
                    <div class="small text-muted">${p.position} · Age ${p.age} · OVR ${ovrDisplay}</div>
                    <div class="small text-info" style="cursor:pointer;" onclick="toggleProspectDetails('${cssSafeTC(p.name)}')">
                        <span id="prospect-details-toggle-${cssSafeTC(p.name)}">▸ Details</span>
                    </div>
                    <div id="prospect-details-${cssSafeTC(p.name)}" style="display:none;">
                        <div class="small"><span class="text-success">Potential: ${potDisplay}</span> · <span class="text-info">${p.projected}</span></div>
                        <div class="scout-progress-track mt-1" title="Scouting confidence: ${p.scout_points_invested}/10 -- higher means a tighter, more accurate OVR estimate">
                            <div class="scout-progress-fill" style="width:${Math.min(100, p.scout_points_invested * 10)}%;"></div>
                        </div>
                        ${canScoutMore && scoutPtsLeft > 0 ? `<button class="btn btn-sm btn-outline-info py-0 px-1 mt-1" style="font-size:0.7rem;" onclick="scoutProspect('${safeName}', 2)">🔍 Scout More</button>` : `<span class="small text-white-50">${p.scout_points_invested >= 10 ? '✓ Fully scouted' : 'Out of scouting points'}</span>`}
                        ${renderCombineButtons(p.name)}
                    </div>
                </div>
            </div>`;
        });
        prospectHtml += `</div>`;

        const upcomingFAs = Object.values(state.players)
            .filter(p => !p.retired && p.team && p.contract && p.contract.years_left <= 1)
            .sort((a, b) => b.rating - a.rating);
        let faHtml = `<h5 class="text-white-50 mt-3">🔍 Upcoming Free Agents <small class="text-muted">(${upcomingFAs.length} expiring contracts)</small></h5>`;
        faHtml += `<div class="row" style="max-height:280px; overflow-y:auto;">`;
        upcomingFAs.slice(0, 20).forEach(p => {
            faHtml += `<div class="col-md-6 col-lg-3 mb-2">
                <div class="fa-card">
                    <a class="player-link" onclick="showPlayerModal('${p.name}')">${p.name}</a>
                    <div class="small text-muted">${p.position} · Age ${p.age} · OVR ${p.rating} · ${p.team}</div>
                    <div class="small text-warning">$${p.contract.salary}M · ${p.contract.years_left} yr left</div>
                </div>
            </div>`;
        });
        faHtml += `</div>`;

        hub.innerHTML = `<div class="p-3 mb-3 bg-dark border border-secondary rounded">${regionHtml}${prospectHtml}${faHtml}</div>`;
    }

    async function investScoutingRegion(region, points) {
        await fetch('/api/invest_scouting_region', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({team: state.user_team, region, points})});
        await refreshState();
        renderScoutingHub();
    }
    window.investScoutingRegion = investScoutingRegion;

    // UPGRADE (scouting simplification pass): most people don't have an
    // opinion on which of 6 real-world leagues to invest scouting points
    // in -- that's a lot of upfront decision-making for a system whose
    // payoff (tighter grade ranges) isn't obvious until later. Auto-Scout
    // spreads available points across regions using the same "where does
    // this draft class actually have talent" signal the class-strength
    // grade already computes, so one click gets a sensible default and the
    // manual grid stays available (collapsed) for anyone who wants control.
    async function autoInvestScouting() {
        const pts = state.scout_points_remaining || 0;
        if (pts <= 0) return;
        const regions = ['EuroLeague', 'G-League', 'NCAA', 'Australia/NBL', 'China/CBA', 'Africa/BAL'];
        const current = (state.scouting_regions || {})[state.user_team] || {};
        // Spend evenly across the two least-invested regions first, so a
        // single click actually broadens coverage instead of dumping
        // everything into whichever region happened to be listed first.
        const sorted = regions.slice().sort((a, b) => (current[a] || 0) - (current[b] || 0));
        let remaining = pts;
        for (const region of sorted) {
            if (remaining <= 0) break;
            const chunk = Math.min(remaining, Math.max(1, Math.ceil(pts / regions.length)));
            await fetch('/api/invest_scouting_region', {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({team: state.user_team, region, points: chunk})});
            remaining -= chunk;
        }
        await refreshState();
        renderScoutingHub();
        if (typeof showToast === 'function') showToast('Scouting points auto-invested across the weakest-covered regions.', 'success');
    }
    window.autoInvestScouting = autoInvestScouting;

    function toggleManualScoutingRegions() {
        const el = document.getElementById('manual-scouting-regions');
        const label = document.getElementById('manual-scouting-toggle-label');
        if (!el) return;
        const opening = el.style.display === 'none';
        el.style.display = opening ? 'flex' : 'none';
        if (label) label.textContent = (opening ? '▾' : '▸') + ' Manual region-by-region control';
    }
    window.toggleManualScoutingRegions = toggleManualScoutingRegions;

    async function runDraftLotteryCeremony() {
        const res = await fetch('/api/draft_lottery_ceremony', {method: 'POST'});
        const data = await res.json();
        showToast(data.reason || data.message || 'Draft lottery ceremony complete -- check the draft order.', data.success === false ? 'error' : 'success');
        await refreshState();
        renderScoutingHub();
    }
    window.runDraftLotteryCeremony = runDraftLotteryCeremony;

    async function developAcademyProspect() {
        const res = await fetch('/api/develop_academy_prospect', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({team: state.user_team})});
        const data = await res.json();
        showToast(data.reason || data.message || 'Academy prospect development processed.', data.success === false ? 'error' : 'success');
        await refreshState();
        renderScoutingHub();
    }
    window.developAcademyProspect = developAcademyProspect;

    async function openRedraftSimulator() {
        const year = prompt('Redraft which past draft year?');
        if (!year) return;
        const res = await fetch(`/api/redraft_simulator?year=${encodeURIComponent(year)}`);
        const data = await res.json();
        if (!data.success && data.reason) { showToast(data.reason, 'error'); return; }
        // BUGFIX: this used to jam the entire redraft (often 30-60 picks)
        // into a single toast notification -- unreadable wall of text in a
        // box meant for a one-line status message that auto-dismisses in
        // a few seconds. Render it as a real scrollable result panel next
        // to the prospects board instead, same pattern as every other
        // "tool result" in this hub.
        const rows = (data.redraft || []).map(p =>
            `<div class="ladder-row"><span class="ladder-name">${p.redraft_pick}. ${p.player.replace(/</g,'&lt;')}</span><span class="ladder-stat">${p.actual_rating_now} OVR now</span></div>`
        ).join('');
        let panel = document.getElementById('redraft-result-panel');
        if (!panel) {
            panel = document.createElement('div');
            panel.id = 'redraft-result-panel';
            panel.className = 'dashboard-card mt-3';
            const anchor = document.getElementById('draft-bigboard-grid');
            if (anchor && anchor.parentElement) anchor.parentElement.insertBefore(panel, anchor);
        }
        panel.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-2">
                <h6 class="text-info m-0">🔁 Redraft of ${String(year).replace(/</g,'&lt;')} -- with what we know now</h6>
                <button class="btn btn-sm btn-outline-secondary" onclick="document.getElementById('redraft-result-panel').remove()">✕</button>
            </div>
            <div style="max-height:320px; overflow-y:auto;">${rows || '<span class="hub-result-empty">No data available for that year.</span>'}</div>`;
        panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    }
    window.openRedraftSimulator = openRedraftSimulator;

    function renderOffseasonPanel(el) {
        if (!state.offseason_report) {
            el.innerHTML = `
                <div class="alert alert-warning">The season has ended. Process retirements, aging, and player development before the draft.</div>
                <button class="btn btn-accent btn-lg" onclick="processOffseason()">🌴 Process Retirements & Progression</button>
            `;
            return;
        }
        const r = state.offseason_report;
        let html = `<div class="alert alert-success">Offseason processed! ${r.retired.length} player(s) retired, ${r.now_free_agents.length} contract(s) expired to free agency.</div>`;
        html += `<div class="row">`;
        html += `<div class="col-md-4"><h5 class="text-white-50">🏁 Retirements (${r.retired.length})</h5><div style="max-height:250px; overflow-y:auto;">`;
        r.retired.forEach(p => html += `<div class="small p-2 mb-1 bg-dark rounded border border-secondary">${p.name} (${p.team}, age ${p.age})</div>`);
        html += `</div></div>`;
        html += `<div class="col-md-4"><h5 class="text-success">📈 Biggest Progressions <span class="text-white-50" style="cursor:help;font-size:0.8rem;" title="Progression isn't linear -- young players (under ~25) and high-potential prospects swing the most, while physical attributes (Speed, Vertical, Stamina) decline noticeably faster after age 30.">ⓘ</span></h5><div style="max-height:250px; overflow-y:auto;">`;
        r.progressed.forEach(p => html += `<div class="small p-2 mb-1 bg-dark rounded border border-secondary"><a class="player-link" onclick="showPlayerModal('${p.name}')">${p.name}</a> <span class="text-white-50">(${p.team})</span> +${p.delta} → <span style="color:${attrColor(p.new_rating)}; font-weight:700;">${p.new_rating} OVR</span></div>`);
        html += `</div></div>`;
        html += `<div class="col-md-4"><h5 class="text-danger">📉 Biggest Regressions <span class="text-white-50" style="cursor:help;font-size:0.8rem;" title="Physical attributes decline faster after 30 -- older vets with low potential headroom regress harder and more predictably than young players with room to grow.">ⓘ</span></h5><div style="max-height:250px; overflow-y:auto;">`;
        r.regressed.forEach(p => html += `<div class="small p-2 mb-1 bg-dark rounded border border-secondary"><a class="player-link" onclick="showPlayerModal('${p.name}')">${p.name}</a> <span class="text-white-50">(${p.team})</span> ${p.delta} → <span style="color:${attrColor(p.new_rating)}; font-weight:700;">${p.new_rating} OVR</span></div>`);
        html += `</div></div>`;
        html += `</div>`;
        html += `<button class="btn btn-accent btn-lg mt-3 w-100" onclick="beginDraft()">🎓 Proceed to the Draft</button>`;
        el.innerHTML = html;
    }

    async function processOffseason() {
        await fetch('/api/process_offseason', {method: 'POST'});
        await refreshState();
        renderFrontOfficeTab();
    }

    async function beginDraft() {
        await fetch('/api/start_draft', {method: 'POST'});
        await refreshState();
        renderFrontOfficeTab();
    }

    function renderDraftPanel(el) {
        const d = state.draft;
        // UPGRADE: Better draft presentation — big pick announcement header
        const round = d.order && d.index < d.order.length ? (state.draft_picks[d.order[d.index]] || {}).round : 1;
        let html = `<div class="text-center mb-3">
            <div class="font-monospace text-warning" style="font-size:0.8rem;letter-spacing:3px;">🏀 ${d.year} NBA DRAFT</div>
            <div class="text-white-50 small">Round ${round || 1} · Pick ${Math.min(d.index+1, (d.order||[]).length)} of ${(d.order||[]).length}</div>
        </div>`;

        if (!d.active) {
            html += `<div class="alert alert-success text-center">🎉 Draft Complete! Head to Free Agency to fill your roster.</div>`;
            el.innerHTML = html + renderDraftResults();
            return;
        }

        const pickId = d.order[d.index];
        const pk = state.draft_picks[pickId];
        const onClockTeam = pk.current_team;
        const isUserTurn = onClockTeam === state.user_team;

        html += `<div class="p-3 mb-3 rounded text-center ${isUserTurn ? '' : ''}" style="background:${isUserTurn ? '#0d2b1a' : '#1f2937'};border:2px solid ${isUserTurn ? '#22c55e' : '#334155'};">
            <div class="small text-white-50">ON THE CLOCK</div>
            <div class="fw-bold" style="font-size:1.3rem;color:${teamColor(onClockTeam)};">${onClockTeam}</div>
            <button class="btn btn-sm btn-outline-accent mt-1" onclick="openDraftTradePrompt()">🔁 Draft-Day Trade</button>
        </div>`;

        if (isUserTurn) {
            // Team needs for smarter picking guidance
            const needs = getTeamNeeds(state.user_team);
            if (needs.length) {
                html += `<div class="d-flex gap-2 flex-wrap mb-3">
                    <span class="small text-white-50">Your needs:</span>
                    ${needs.map(n => `<span class="badge bg-secondary">${n.pos} (${n.stars})</span>`).join('')}
                </div>`;
            }
            html += `<div class="row g-2" style="max-height:520px; overflow-y:auto;">`;
            const sorted = (state.draft_class || []).slice().sort((a,b) => {
                const ai = customBigBoard.indexOf(a.name), bi = customBigBoard.indexOf(b.name);
                if (ai !== -1 && bi !== -1) return ai - bi;
                return b.rating - a.rating;
            });
            sorted.forEach((p, idx) => {
                const ovrDisplay = p.rating != null ? p.rating : `${p.overall_range?.low}–${p.overall_range?.high}`;
                const starRating = Math.min(5, Math.max(1, Math.round((p.rating - 55) / 9)));
                const stars = '⭐'.repeat(starRating);
                const intlBadge = p.international ? `<span class="badge bg-info" style="font-size:0.6rem;">🌍 ${p.origin}</span>` : '';
                const archetype = getPlayerArchetype(p);
                const peak = getPeakLabel(p.age, p.position);
                const combineRes = (state.combine_results || {})[p.name] || {};
                const combineCount = Object.keys(combineRes).length;
                // Strengths and weaknesses from attributes
                const attrs = p.attributes || {};
                const sortedAttrs = Object.entries(attrs).sort((a,b) => b[1]-a[1]);
                const strengths = sortedAttrs.slice(0,2).map(([k])=>k).join(', ');
                const weaknesses = sortedAttrs.slice(-2).map(([k])=>k).join(', ');
                html += `<div class="col-md-6">
                    <div class="prospect-card">
                        <div class="d-flex justify-content-between align-items-start mb-1">
                            <div>
                                <div class="d-flex align-items-center gap-1 flex-wrap">
                                    <a class="player-link fw-bold" onclick="showPlayerModal('${p.name.replace(/'/g,"\\'")}')">#${idx+1} ${p.name}</a>
                                    ${intlBadge}
                                </div>
                                <div class="small text-muted">${p.position} · Age ${p.age} · ${stars}</div>
                            </div>
                            <div class="text-center">
                                <div class="fw-bold text-warning">${ovrDisplay}</div>
                                <div class="small text-white-50">OVR</div>
                            </div>
                        </div>
                        <div class="d-flex gap-1 flex-wrap mb-1">
                            <span class="badge bg-dark border border-secondary text-info" style="font-size:0.62rem;">${archetype}</span>
                            <span class="badge bg-dark border border-secondary" style="font-size:0.62rem;color:${getPeakColor(p.age,p.position)}">${peak}</span>
                            <span class="badge bg-dark border border-secondary text-success" style="font-size:0.62rem;">Pot: ${p.potential_grade}</span>
                            ${combineCount > 0 ? `<span class="badge bg-dark border border-info text-info" style="font-size:0.62rem;">🔬 ${combineCount}/5 drills</span>` : ''}
                        </div>
                        ${strengths ? `<div class="small text-success">✓ ${strengths}</div>` : ''}
                        ${weaknesses ? `<div class="small text-danger">✗ ${weaknesses}</div>` : ''}
                        <div class="d-flex justify-content-between align-items-center mt-2">
                            <span class="small text-white-50">${p.projected}</span>
                            <button class="btn btn-sm btn-accent" onclick="draftPick('${p.name.replace(/'/g,"\\'")}')">Draft</button>
                        </div>
                    </div>
                </div>`;
            });
            html += `</div>`;
        } else {
            html += `<p class="text-white-50">Waiting on other franchises — resolves automatically up to your next pick.</p>`;
        }

        html += renderDraftResults();
        el.innerHTML = html;
    }

    // Team Needs helper — returns which positions the team is thin at
    function getTeamNeeds(teamName) {
        const roster = Object.values(state.players).filter(p => p.team === teamName && !p.retired);
        const counts = {PG:0, SG:0, SF:0, PF:0, C:0};
        roster.forEach(p => {
            if (counts.hasOwnProperty(p.position)) counts[p.position]++;
            if (p.secondary_position && counts.hasOwnProperty(p.secondary_position)) counts[p.secondary_position] += 0.5;
        });
        return Object.entries(counts)
            .filter(([,v]) => v < 3)
            .sort((a,b) => a[1]-b[1])
            .map(([pos, cnt]) => ({pos, count: Math.round(cnt), stars: '★'.repeat(Math.max(1, 3 - Math.round(cnt))) + '☆'.repeat(Math.min(3, Math.round(cnt)))}));
    }

    async function openDraftTradePrompt() {
        const otherTeam = prompt("Propose a draft-day trade with which team? (exact team name)");
        if (!otherTeam || !state.teams[otherTeam]) { if (otherTeam) showToast("Unknown team name.", 'error'); return; }
        const myPickIds = Object.values(state.draft_picks).filter(pk => pk.current_team === state.user_team).map(pk => `${pk.year} R${pk.round} (${pk.id})`);
        const theirPickIds = Object.values(state.draft_picks).filter(pk => pk.current_team === otherTeam).map(pk => `${pk.year} R${pk.round} (${pk.id})`);
        const give = prompt(`Your available picks:\n${myPickIds.join(`\n`)}\n\nEnter the pick id(s) you're offering, comma-separated:`);
        if (give === null) return;
        const get = prompt(`${otherTeam}'s available picks:\n${theirPickIds.join(`\n`)}\n\nEnter the pick id(s) you want, comma-separated:`);
        if (get === null) return;
        const picks_a = give.split(',').map(s => s.trim()).filter(Boolean);
        const picks_b = get.split(',').map(s => s.trim()).filter(Boolean);
        const res = await fetch('/api/draft_trade', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({team_a: state.user_team, players_a: [], picks_a, team_b: otherTeam, players_b: [], picks_b})});
        const data = await res.json();
        showToast(data.reason || (data.accepted ? 'Trade accepted!' : 'Trade rejected.'), 'error');
        if (data.accepted) { await refreshState(); renderDraftPanel(document.getElementById('fo-content')); }
    }
    window.openDraftTradePrompt = openDraftTradePrompt;

    function renderDraftResults() {
        if (!state.draft.results || state.draft.results.length === 0) return '';
        let html = `<h6 class="text-white-50 mt-4 mb-2">📋 Draft Results So Far</h6><div style="max-height:280px; overflow-y:auto;">`;
        state.draft.results.slice().reverse().forEach(res => {
            const p = state.players[res.player] || {};
            const arch = getPlayerArchetype(p);
            const isUser = res.team === state.user_team;
            html += `<div class="small p-2 mb-1 rounded border d-flex justify-content-between align-items-center" style="background:${isUser?'#0d2b1a':'#1f2937'};border-color:${isUser?'#22c55e':'#334155'} !important;">
                <span><span class="text-white-50">#${res.pick_number}</span> <span class="fw-bold" style="color:${teamColor(res.team)}">${res.team}</span></span>
                <span><a class="player-link" onclick="showPlayerModal('${res.player.replace(/'/g,"\\'")}')">${res.player}</a> <span class="text-white-50">${res.position}</span>
                    <span class="badge bg-dark border border-secondary ms-1 text-info" style="font-size:0.6rem;">${arch}</span></span>
                <span class="text-warning">${res.rating} OVR · ${res.potential_grade}</span>
            </div>`;
        });
        html += `</div>`;
        return html;
    }

    async function draftPick(prospectName, confirmed) {
        const res = await fetch('/api/draft_pick', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({prospect_name: prospectName, confirm: !!confirmed})});
        const data = await res.json();
        if (data.status === 'warning' && data.requires_confirm) {
            if (confirm(data.reason)) {
                await draftPick(prospectName, true);
            }
            return;
        }
        await refreshState();
        renderFrontOfficeTab();
    }

    function setFaPositionFilter(pos) {
        const input = document.getElementById('fa-position');
        if (input) input.value = pos;
        document.querySelectorAll('#fa-position-pills .fa-pill').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-pos') === pos);
        });
        renderFreeAgencyTab();
    }
    window.setFaPositionFilter = setFaPositionFilter;

    function renderFreeAgencyTab() {
        const el = document.getElementById('fa-tab-content');
        if (!el) return;
        const roster = Object.values(state.players).filter(p => p.team === state.user_team && !p.retired);
        const cap = state.teams[state.user_team].cap_space;
        const twoWayCount = roster.filter(p => p.two_way).length;
        let html = `<div class="alert alert-info">Your roster: ${roster.length}/15 · Cap space: $${cap}M · Two-Way Slots: ${twoWayCount}/2</div>`;

        if (state.stage === 'free_agency') {
            const pct = Math.min(100, Math.round((state.fa_day / state.fa_days_total) * 100));
            html += `
                <div class="p-3 bg-dark border border-secondary rounded mb-3">
                    <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
                        <h5 class="text-white m-0 font-monospace">Free Agency Period: Day ${state.fa_day} / ${state.fa_days_total}</h5>
                        <div class="d-flex gap-2">
                            <button class="btn btn-info" onclick="simFADay()">▶ Sim 1 Day</button>
                            <button class="btn btn-outline-accent btn-sm" style="border:1px solid #3b82f6;color:#93c5fd;" onclick="simFARest()">⏩ Sim Rest of FA Period</button>
                        </div>
                    </div>
                    <div class="progress mt-2" style="height:8px; background:#1f2937;">
                        <div class="progress-bar bg-info" style="width:${pct}%;"></div>
                    </div>
                    <div id="fa-day-log" class="mt-2 small"></div>
                </div>
            `;
        }

        html += `<div id="fa-tab-signed-msg"></div>`;

        if (!state.free_agents || state.free_agents.length === 0) {
            html += `<p class="text-white-50 mt-3">No unsigned free agents on the wire right now -- check back after contracts expire, players get released, or a signing window opens.</p>`;
            el.innerHTML = html;
            return;
        }

        html += `<h5 class="text-white-50 mt-3">Available Free Agents (${state.free_agents.length})</h5>`;
        html += `<div class="row" style="max-height:600px; overflow-y:auto;">`;
        const faQuery = (document.getElementById('fa-query')?.value || '').trim().toLowerCase();
        const faPosition = document.getElementById('fa-position')?.value || '';
        const faMinRating = parseInt(document.getElementById('fa-min-rating')?.value || '0', 10) || 0;
        let sorted = state.free_agents.slice().sort((a, b) => b.rating - a.rating);
        if (faQuery) sorted = sorted.filter(p => p.name.toLowerCase().includes(faQuery));
        if (faPosition) sorted = sorted.filter(p => p.position === faPosition);
        if (faMinRating) sorted = sorted.filter(p => p.rating >= faMinRating);
        if (!sorted.length) {
            html += `</div><p class="text-white-50 mt-2">No free agents match those filters.</p>`;
            el.innerHTML = html;
            return;
        }
        sorted.forEach(p => {
            const asking = p.asking_price != null ? p.asking_price : '—';
            const eligBadges = (p.fa_eligibility || []).map(b =>
                `<span class="badge bg-secondary me-1" style="font-size:0.65rem;">${b}</span>`).join('');
            const personalityIcon = {'Loyalty':'🤝','Business':'💰','Ring Chaser':'💍','Balanced':'⚖️'}[p.agent_personality] || '';
            const personalityBadge = p.agent_personality ? `<span class="badge bg-dark border border-secondary me-1" style="font-size:0.65rem;" title="Negotiating style">${personalityIcon} ${p.agent_personality}</span>` : '';
            html += `<div class="col-md-6">
                <div class="fa-card d-flex justify-content-between align-items-center">
                    <div>
                        <a class="player-link" onclick="showPlayerModal('${p.name}')">${p.name}</a>
                        <div class="small text-muted">${p.position} · Age ${p.age} · OVR ${p.rating}</div>
                        <div class="small text-warning">Asking: $${asking}M</div>
                        <div class="mt-1">${eligBadges}${personalityBadge}</div>
                    </div>
                    <div class="d-flex flex-column gap-1">
                        <button class="btn btn-sm btn-accent" onclick="signFATab('${p.name}')">Sign at Asking</button>
                        <button class="btn btn-sm btn-outline-info" onclick="openNegotiateModal('${p.name}', ${asking}, true)">Negotiate</button>
                        <button class="btn btn-sm btn-outline-warning" onclick="signTwoWay('${p.name}')" title="G-League / two-way deal -- doesn't count against the 15-man roster">🎽 Two-Way</button>
                    </div>
                </div>
            </div>`;
        });
        html += `</div>`;
        el.innerHTML = html;
    }

    async function simFADay() {
        const res = await fetch('/api/simulate_fa_day', {method: 'POST'});
        const data = await res.json();
        await refreshState();
        renderFreeAgencyTab();
        const log = document.getElementById('fa-day-log');
        if (log) {
            log.innerHTML = data.signed_count > 0
                ? `<span class="text-info">Day ${data.fa_day}: ${data.signed_count} AI signing(s) — ` +
                  data.signed.map(s => `${s.player} → ${s.team} ($${s.salary}M)`).join(', ') + `</span>`
                : `<span class="text-white-50">Day ${data.fa_day}: no new AI signings.</span>`;
        }
    }

    async function simFARest() {
        await fetch('/api/simulate_fa_period', {method: 'POST'});
        await refreshState();
        renderFreeAgencyTab();
        const log = document.getElementById('fa-day-log');
        if (log) log.innerHTML = `<span class="text-info">Fast-forwarded through the rest of the free agency period.</span>`;
    }

    async function signTwoWay(name) {
        const res = await fetch('/api/sign_two_way', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name})});
        const data = await res.json();
        await refreshState();
        renderFreeAgencyTab();
        const msg = document.getElementById('fa-tab-signed-msg');
        if (msg) msg.innerHTML = data.success
            ? `<div class="alert alert-info">✅ Signed ${data.player} to a two-way (G-League) contract.</div>`
            : `<div class="alert alert-danger">❌ ${data.reason}</div>`;
    }
    window.signTwoWay = signTwoWay;

    async function signFATab(name, offerSalary) {
        const payload = {name};
        if (offerSalary !== undefined && offerSalary !== null) payload.offer_salary = offerSalary;
        const res = await fetch('/api/sign_free_agent', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
        const data = await res.json();
        await refreshState();
        renderFreeAgencyTab();

        const msg = document.getElementById('fa-tab-signed-msg');
        if (!msg) return;
        if (data.bidding_war) {
            msg.innerHTML = `
                <div class="alert alert-warning">
                    <h5 class="mb-2">💰 Bidding War! ${data.competing_team} wants ${data.player} too.</h5>
                    <p class="mb-2">Your opening offer was $${data.base_salary}M. To win the bidding war you'll need to match <b>$${data.required_salary}M</b>.</p>
                    <div class="d-flex gap-2">
                        <button class="btn btn-success" onclick="resolveBid(true)">Match $${data.required_salary}M</button>
                        <button class="btn btn-outline-danger" onclick="resolveBid(false)">Let ${data.competing_team} Have Him</button>
                    </div>
                </div>
            `;
            return;
        }
        msg.innerHTML = data.success
            ? `<div class="alert alert-success">Signed ${data.player} for $${data.salary}M!</div>`
            : `<div class="alert alert-danger">${data.reason}</div>`;
    }

    function openNegotiateModal(name, asking, fromFaTab) {
        const existing = document.getElementById('negotiate-modal-overlay');
        if (existing) existing.remove();
        const wrap = document.createElement('div');
        wrap.id = 'negotiate-modal-overlay';
        wrap.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.6); z-index:2000; display:flex; align-items:center; justify-content:center;';
        wrap.innerHTML = `
            <div class="dashboard-card" style="width:400px;">
                <h5 class="text-info mb-3">Negotiate with ${name}</h5>
                <p class="small text-white-50 mb-2">Market ask: <b class="text-warning">$${asking}M</b>. Structured offers well below asking price risk being turned down.</p>
                <label class="form-label text-white-50 small">Your Offer ($M / yr)</label>
                <input type="number" id="negotiate-salary-input" class="form-control bg-dark text-white border-secondary mb-3" value="${asking}" min="1" step="0.1">
                <div class="d-flex gap-2">
                    <button class="btn btn-accent flex-fill" onclick="sendStructuredOffer('${name}')">Send Offer</button>
                    <button class="btn btn-outline-secondary flex-fill" onclick="document.getElementById('negotiate-modal-overlay').remove()">Cancel</button>
                </div>
            </div>
        `;
        wrap.dataset.fromFaTab = fromFaTab ? "1" : "";
        document.body.appendChild(wrap);
    }

    async function sendStructuredOffer(name) {
        const val = parseFloat(document.getElementById('negotiate-salary-input').value);
        const overlay = document.getElementById('negotiate-modal-overlay');
        const fromFaTab = overlay && overlay.dataset.fromFaTab === "1";
        if (overlay) overlay.remove();
        if (fromFaTab) {
            await signFATab(name, isNaN(val) ? null : val);
        } else {
            await signFA(name, isNaN(val) ? null : val);
        }
    }

    async function signFA(name, offerSalary) {
        const payload = {name};
        if (offerSalary !== undefined && offerSalary !== null) payload.offer_salary = offerSalary;
        const res = await fetch('/api/sign_free_agent', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
        const data = await res.json();
        await refreshState();

        const msg = document.getElementById('fa-signed-msg');
        if (data.bidding_war) {
            renderFrontOfficeTab();
            if (msg) {
                msg.innerHTML = `
                    <div class="alert alert-warning">
                        <h5 class="mb-2">💰 Bidding War! ${data.competing_team} wants ${data.player} too.</h5>
                        <p class="mb-2">Your opening offer was $${data.base_salary}M. To win the bidding war you'll need to match <b>$${data.required_salary}M</b>.</p>
                        <div class="d-flex gap-2">
                            <button class="btn btn-success" onclick="resolveBid(true)">Match $${data.required_salary}M</button>
                            <button class="btn btn-outline-danger" onclick="resolveBid(false)">Let ${data.competing_team} Have Him</button>
                        </div>
                    </div>
                `;
            }
            return;
        }

        renderFrontOfficeTab();
        if (msg) {
            msg.innerHTML = data.success
                ? `<div class="alert alert-success">Signed ${data.player} for $${data.salary}M!</div>`
                : `<div class="alert alert-danger">${data.reason}</div>`;
        }
    }

    async function resolveBid(match) {
        const res = await fetch('/api/resolve_bid', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({match})});
        const data = await res.json();
        await refreshState();
        if (state.current_tab === 'freeagency') { renderFreeAgencyTab(); } else { renderFrontOfficeTab(); }
        const msg = document.getElementById('fa-tab-signed-msg') || document.getElementById('fa-signed-msg');
        if (!msg) return;
        if (data.status === 'matched') {
            msg.innerHTML = `<div class="alert alert-success">You matched the offer and signed him for $${data.salary}M!</div>`;
        } else if (data.status === 'lost_to_rival') {
            msg.innerHTML = `<div class="alert alert-secondary">You passed — ${data.team} signed him for $${data.salary}M.</div>`;
        } else if (data.status === 'could_not_afford') {
            msg.innerHTML = `<div class="alert alert-danger">You didn't have the cap space to match — ${data.team} signed him for $${data.salary}M.</div>`;
        }
    }

    async function simulateFAPeriod() {
        const res = await fetch('/api/simulate_fa_period', {method: 'POST'});
        const data = await res.json();
        await refreshState();
        renderFrontOfficeTab();
        const msg = document.getElementById('fa-signed-msg');
        if (msg) msg.innerHTML = `<div class="alert alert-info">Other franchises signed ${data.signed_count} free agents.</div>`;
    }

    async function startNewSeason() {
        const res = await fetch('/api/start_new_season', {method: 'POST'});
        const data = await res.json();
        if (data.status === 'blocked') {
            showToast(data.reason, 'error');
            await refreshState();
            renderFrontOfficeTab();
            return;
        }
        await refreshState();
        switchTab('roster', document.querySelector("button[onclick*='roster']"));
    }

    // ===================== LEAGUE HISTORY =====================
    // BUGFIX: this used to render three headerless, permanently-empty
    // columns on a brand-new league (0 games played means the backend
    // correctly returns empty arrays) with zero indication of *why* --
    // looked exactly like a broken/dead panel. Add a real empty state, and
    // show position + OVR next to every player name here too.
    async function renderCareerLeaders() {
        const el = document.getElementById('career-leaders-content');
        if (!el) return;
        el.innerHTML = '<div class="text-white-50 small">Loading...</div>';
        let data;
        try {
            const res = await fetch('/api/career_leaders');
            data = await res.json();
        } catch (e) {
            el.innerHTML = '<div class="text-danger small">Could not load career leaders -- try again.</div>';
            return;
        }
        if (!data.games_played_league_wide) {
            el.innerHTML = `<div class="text-white-50 small col-12">
                No games have been played yet this league, so there's no career leaderboard to show.
                Sim a few games and check back -- this fills in automatically as stats accumulate.
            </div>`;
            return;
        }
        const col = (title, key, rows) => `
            <div class="col-md-4 mb-3">
                <h6 class="text-warning">${title}</h6>
                <div style="max-height:340px; overflow-y:auto;">
                <table class="table-dark-custom"><tbody>
                ${rows.length ? rows.map((r,i) => `<tr>
                    <td>${i+1}</td>
                    <td><a class="player-link" onclick="showPlayerModal('${r.name.replace(/'/g,"\\'")}')">${r.name}</a>
                        <span class="text-white-50" style="font-size:0.82em;">${r.position || ''} · ${r.rating || 0} OVR</span></td>
                    <td class="text-end">${r[key].toLocaleString()}</td></tr>`).join('')
                    : `<tr><td colspan="3" class="text-white-50 small">No qualifying players yet.</td></tr>`}
                </tbody></table>
                </div>
            </div>`;
        el.innerHTML = col('Career Points', 'pts', data.points || []) + col('Career Rebounds', 'reb', data.rebounds || []) + col('Career Assists', 'ast', data.assists || []);
    }

    function renderHistoryTab() {
        renderCareerLeaders();
        const el = document.getElementById('history-content');
        if (!el) return;
        if (!state.history || state.history.length === 0) {
            el.innerHTML = `<p class="text-white-50">No championships have been decided yet. Complete a full season and playoffs to start the record book.</p>`;
            return;
        }
        let html = `<div class="hist-timeline">`;
        state.history.slice().reverse().forEach(h => {
            const isUser = h.champion === state.user_team;
            html += `<div class="hist-timeline-item">
                <div class="hist-timeline-dot"></div>
                <div class="hist-timeline-card">
                    <div class="hist-timeline-year">Season ${h.year}</div>
                    <div class="hist-timeline-champ">🏆 <span class="${isUser ? 'uc' : ''}">${h.champion || '—'}</span></div>
                    <div class="hist-timeline-meta">
                        <span>Finals MVP: <b>${h.finals_mvp ? `<a class="player-link" onclick="showPlayerModal('${h.finals_mvp.replace(/'/g,"\\'")}')">${h.finals_mvp}</a>` : '—'}</b> ${h.finals_mvp_stat ? `<span class="text-muted">${h.finals_mvp_stat}</span>` : ''}</span>
                        <span>League MVP: <b>${h.mvp ? `<a class="player-link" onclick="showPlayerModal('${h.mvp.replace(/'/g,"\\'")}')">${h.mvp}</a>` : '—'}</b></span>
                        <span>Rookie of the Year: <b>${h.roy ? `<a class="player-link" onclick="showPlayerModal('${h.roy.replace(/'/g,"\\'")}')">${h.roy}</a>` : '—'}</b></span>
                    </div>
                    ${h.highlight_reel && h.highlight_reel.length ? `<div class="hist-timeline-reel">${h.highlight_reel.map(r => `<div>${r}</div>`).join('')}</div>` : ''}
                </div>
            </div>`;
        });
        html += `</div>`;

        const retirees = (state.retired_players || []).slice();
        if (retirees.length > 0) {
            const hof = retirees.filter(r => r.hall_of_fame)
                .sort((a, b) => (b.mvps - a.mvps) || (b.championships - a.championships) || (b.all_star_selections - a.all_star_selections));
            html += `<h5 class="text-white-50 font-monospace mt-4 mb-2">🏛 Hall of Fame</h5>`;
            if (hof.length === 0) {
                html += `<p class="text-white-50 small">No inductees yet — legends need a stacked resume (multiple MVPs or a half-dozen+ major accolades) to punch their ticket.</p>`;
            } else {
                html += `<div style="max-height:320px; overflow-y:auto;"><table class="table-dark-custom">
                    <thead><tr><th>Player</th><th>Last Team</th><th>Retired Age</th><th>Peak OVR</th><th>MVPs</th><th>Rings</th><th>All-Stars</th><th>Career Pts</th></tr></thead><tbody>`;
                hof.forEach(r => {
                    html += `<tr><td>🏅 ${r.name}</td><td>${r.team || '—'}</td><td>${r.age}</td><td class="text-warning">${r.final_rating}</td>
                        <td>${r.mvps || 0}</td><td>${r.championships || 0}</td><td>${r.all_star_selections || 0}</td><td>${(r.career_points || 0).toLocaleString()}</td></tr>`;
                });
                html += `</tbody></table></div>`;
            }

            const nonHof = retirees.filter(r => !r.hall_of_fame && (r.all_star_selections > 0 || r.championships > 0))
                .sort((a, b) => b.final_rating - a.final_rating).slice(0, 15);
            if (nonHof.length > 0) {
                html += `<h5 class="text-white-50 font-monospace mt-4 mb-2">Notable Retirees</h5>`;
                html += `<div style="max-height:260px; overflow-y:auto;"><table class="table-dark-custom">
                    <thead><tr><th>Player</th><th>Last Team</th><th>Retired Age</th><th>Peak OVR</th><th>All-Stars</th><th>Rings</th></tr></thead><tbody>`;
                nonHof.forEach(r => {
                    html += `<tr><td>${r.name}</td><td>${r.team || '—'}</td><td>${r.age}</td><td class="text-warning">${r.final_rating}</td>
                        <td>${r.all_star_selections || 0}</td><td>${r.championships || 0}</td></tr>`;
                });
                html += `</tbody></table></div>`;
            }
        }

        // UPGRADE: Real historical stats archive -- franchise records + retired numbers.
        const fr = state.franchise_records || {};
        const rn = state.retired_numbers || {};
        const frTeams = Object.keys(fr).filter(t => fr[t].best_season_wins || fr[t].best_season_scorer);
        if (frTeams.length > 0) {
            html += `<h5 class="text-white-50 font-monospace mt-4 mb-2">📜 Franchise Records</h5>
                <div style="max-height:280px; overflow-y:auto;"><table class="table-dark-custom">
                <thead><tr><th>Team</th><th>Best Season</th><th>Best Season Scorer</th><th>Retired Numbers</th></tr></thead><tbody>`;
            frTeams.sort().forEach(t => {
                const bw = fr[t].best_season_wins;
                const bs = fr[t].best_season_scorer;
                const nums = (rn[t] || []).map(x => `#${x.number} ${x.player}`).join(', ') || '—';
                html += `<tr><td>${t}</td>
                    <td>${bw ? `${bw.wins} wins (${bw.year})` : '—'}</td>
                    <td>${bs ? `${bs.player} — ${bs.ppg} PPG (${bs.year})` : '—'}</td>
                    <td class="small">${nums}</td></tr>`;
            });
            html += `</tbody></table></div>`;
        }

        // UPGRADE: Season-over-season franchise win% graph. state.history
        // already carries a full-league standings snapshot per year (see
        // record_league_history on the server) -- this just turns that into
        // a lightweight inline-SVG line chart per team, with a dropdown to
        // pick which franchise to look at (defaults to the user's team).
        if (state.history.length >= 2) {
            if (!winGraphTeam) winGraphTeam = state.user_team;
            const teamOpts = Object.keys(state.teams).sort()
                .map(t => `<option value="${t}" ${t === winGraphTeam ? 'selected' : ''}>${t}</option>`).join('');
            html += `<h5 class="text-white-50 font-monospace mt-4 mb-2">📈 Franchise Win% Over Time</h5>
                <div class="d-flex align-items-center gap-2 mb-2">
                    <label class="small text-white-50 mb-0">Team:</label>
                    <select class="form-select form-select-sm bg-dark text-white border-secondary" style="width:auto;" onchange="setWinGraphTeam(this.value)">${teamOpts}</select>
                </div>
                <div id="win-graph-render"></div>`;
        }

        el.innerHTML = html;
        renderWinGraph();
        renderNewsArchive();

        // UPGRADE: League news archive — persistent scrollable history
    async function renderNewsArchive() {
        const el = document.getElementById('news-archive-panel');
        if (!el) return;
        const cats = ['all','trade','transaction','contract','injury','ceremony','rivalry','general'];
        const catFilter = el.dataset.cat || 'all';
        const url = catFilter === 'all' ? '/api/news_archive' : `/api/news_archive?category=${catFilter}`;
        const res = await fetch(url);
        const data = await res.json();
        const news = data.news || [];
        const catBtns = cats.map(c => `<button class="btn btn-sm ${c===catFilter?'btn-accent':'btn-outline-accent'} me-1 mb-1" onclick="setNewsArchiveCat('${c}')">${c}</button>`).join('');
        let html = `<h5 class="text-white-50 font-monospace mb-2">📰 League News Archive <span class="small text-muted">(${data.total} items)</span></h5>
            <div class="mb-2 d-flex flex-wrap gap-1">${catBtns}</div>
            <div style="max-height:320px;overflow-y:auto;-webkit-overflow-scrolling:touch;">`;
        if (!news.length) {
            html += `<p class="text-white-50 small">No news yet — play through a season to build the archive.</p>`;
        } else {
            const catColors = {trade:'#38bdf8',transaction:'#34d399',contract:'#a78bfa',injury:'#ef4444',ceremony:'#facc15',rivalry:'#f97316',general:'#9db4d9'};
            news.forEach(n => {
                const col = catColors[n.category] || '#9db4d9';
                html += `<div class="d-flex gap-2 small py-1 border-bottom border-secondary align-items-start">
                    <span style="color:${col};font-size:1rem;flex-shrink:0;">${n.emoji||'📋'}</span>
                    <div>
                        <span class="text-white">${n.text}</span>
                        <span class="text-white-50 ms-2" style="font-size:0.7rem;">${n.year ? 'Y'+n.year : ''} D${n.day||''}</span>
                    </div>
                </div>`;
            });
        }
        html += `</div>`;
        el.innerHTML = html;
    }
    function setNewsArchiveCat(cat) {
        const el = document.getElementById('news-archive-panel');
        if (el) { el.dataset.cat = cat; renderNewsArchive(); }
    }
    window.setNewsArchiveCat = setNewsArchiveCat;
        const legacyEl = document.getElementById('legacy-score-panel');
        if (!legacyEl) return;
        const log = state.legacy_log || [];
        const totalPts = state.legacy_score || 0;
        const tier = totalPts >= 3000 ? {label:'Hall of Fame', color:'#facc15'} :
                     totalPts >= 1500 ? {label:'Dynasty Builder', color:'#34d399'} :
                     totalPts >= 750  ? {label:'Franchise Cornerstone', color:'#38bdf8'} :
                     totalPts >= 250  ? {label:'Rising Executive', color:'#a78bfa'} :
                                        {label:'Rookie GM', color:'#9db4d9'};
        let legHtml = `<h5 class="text-white-50 font-monospace mt-4 mb-2">🏛 GM Legacy Score</h5>
            <div class="d-flex align-items-center gap-3 mb-3">
                <div class="ovr-badge" style="border-color:${tier.color};color:${tier.color};font-size:1.3rem;padding:12px 16px;">${totalPts}</div>
                <div><div class="fw-bold" style="color:${tier.color};">${tier.label}</div>
                <div class="small text-white-50">Across ${log.length} completed season${log.length !== 1 ? 's' : ''}</div></div>
            </div>`;
        if (log.length) {
            legHtml += `<table class="table-dark-custom"><thead><tr><th>Year</th><th>Season Pts</th><th>Total</th><th>Key Moments</th></tr></thead><tbody>`;
            log.slice().reverse().forEach(entry => {
                legHtml += `<tr>
                    <td>${entry.year}</td>
                    <td class="text-warning fw-bold">+${entry.pts}</td>
                    <td>${entry.total}</td>
                    <td class="small text-white-50">${(entry.events || []).join(' · ') || '—'}</td>
                </tr>`;
            });
            legHtml += `</tbody></table>`;
        } else {
            legHtml += `<p class="text-white-50 small">Complete your first season to start building your legacy.</p>`;
        }
        legacyEl.innerHTML = legHtml;

        // Trophy Room
        const trEl = document.getElementById('trophy-room-panel');
        if (trEl && (state.trophy_room||[]).length) {
            let trHtml = `<h5 class="text-white-50 font-monospace mt-4 mb-2">🏆 Trophy Room</h5><div class="d-flex flex-wrap gap-3">`;
            (state.trophy_room||[]).forEach(t => {
                trHtml += `<div class="p-3 rounded text-center" style="background:#1f2937;border:1px solid #facc1540;min-width:120px;">
                    <div style="font-size:2.5rem;">🏆</div>
                    <div class="fw-bold text-warning">${t.year}</div>
                    <div class="small text-white">${t.champion}</div>
                    ${t.coach ? `<div class="small text-white-50">Coach: ${t.coach}</div>` : ''}
                    ${t.finals_mvp ? `<div class="small text-white-50">FMVP: ${t.finals_mvp}</div>` : ''}
                    <div class="small text-success">${t.wins}W</div>
                </div>`;
            });
            trEl.innerHTML = trHtml + '</div>';
        } else if (trEl) { trEl.innerHTML = ''; }

        // Franchise GOAT
        const goatEl = document.getElementById('franchise-goat-panel');
        if (goatEl) {
            const goat = (state.franchise_goat||{})[state.user_team];
            if (goat && goat.player) {
                goatEl.innerHTML = `<h5 class="text-white-50 font-monospace mt-4 mb-2">🐐 Franchise GOAT — ${state.user_team}</h5>
                <div class="row g-3">
                    <div class="col-md-4"><div class="p-2 bg-dark rounded border border-secondary text-center">
                        <div class="small text-white-50">Greatest Player</div>
                        <a class="player-link fw-bold d-block mt-1" onclick="showPlayerModal('${(goat.player||'').replace(/'/g,"\\'")}')">${goat.player}</a>
                        <div class="small text-warning">${goat.player_pos||''} · ${goat.player_rating||0} Peak OVR</div>
                    </div></div>
                    ${goat.coach ? `<div class="col-md-4"><div class="p-2 bg-dark rounded border border-secondary text-center">
                        <div class="small text-white-50">Greatest Coach</div>
                        <a class="coach-link fw-bold d-block mt-1" onclick="showCoachModal('${(goat.coach||'').replace(/'/g,"\\'")}')">${goat.coach}</a>
                        <div class="small text-white-50">${goat.coach_system||''} · ${goat.coach_wins||0} wins</div>
                    </div></div>` : ''}
                    ${goat.best_season_wins ? `<div class="col-md-4"><div class="p-2 bg-dark rounded border border-secondary text-center">
                        <div class="small text-white-50">Best Season</div>
                        <div class="fw-bold text-white mt-1">${goat.best_season_year}</div>
                        <div class="small text-success">${goat.best_season_wins} wins</div>
                    </div></div>` : ''}
                </div>`;
            } else { goatEl.innerHTML = ''; }
        }

        // Team Records
        const recEl = document.getElementById('team-records-panel');
        if (recEl) {
            const rec = (state.team_records||{})[state.user_team];
            if (rec && rec.most_wins) {
                recEl.innerHTML = `<h5 class="text-white-50 font-monospace mt-4 mb-2">📋 Franchise Records</h5>
                <div class="row g-2 text-center">
                    <div class="col-3"><div class="p-2 bg-dark rounded border border-secondary">
                        <div class="h4 text-warning mb-0">${rec.most_wins}</div><div class="small text-white-50">Best W (${rec.best_season_year||'?'})</div></div></div>
                    <div class="col-3"><div class="p-2 bg-dark rounded border border-secondary">
                        <div class="h4 text-info mb-0">${rec.longest_win_streak}</div><div class="small text-white-50">Win Streak</div></div></div>
                    <div class="col-3"><div class="p-2 bg-dark rounded border border-secondary">
                        <div class="h4 text-success mb-0">${rec.championships||0}</div><div class="small text-white-50">Titles</div></div></div>
                </div>`;
            } else { recEl.innerHTML = ''; }
        }

        // Hall of Fame
        const hofEl = document.getElementById('hof-panel');
        if (hofEl) {
            const hof = (state.hall_of_fame || []).slice().sort((a,b) => b.year - a.year);
            if (!hof.length) { hofEl.innerHTML = ''; }
            else {
                let hofHtml = `<h5 class="text-white-50 font-monospace mt-4 mb-2">🏛 Hall of Fame</h5>
                    <div class="row g-2">`;
                hof.forEach(p => {
                    hofHtml += `<div class="col-md-4">
                        <div class="p-2 bg-dark rounded border border-warning" style="border-color:#facc1540 !important;">
                            <div class="d-flex align-items-center gap-2">
                                ${playerSilhouetteSvg(p.player, p.position||'SF', '#facc15', 36)}
                                <div>
                                    <div class="fw-bold text-warning"><a class="player-link" onclick="showPlayerModal('${p.player.replace(/'/g,"\\'")}')">${p.player}</a></div>
                                    <div class="small text-white-50">Class of ${p.year} · ${p.position||'?'}</div>
                                    <div class="small text-white-50">${p.seasons} seasons · ${p.championships}x champ · ${p.mvps}x MVP</div>
                                </div>
                            </div>
                        </div>
                    </div>`;
                });
                hofEl.innerHTML = hofHtml + '</div>';
            }
        }

        // Retired jerseys
        const rjEl = document.getElementById('retired-jerseys-panel');
        if (rjEl) {
            const rj = (state.retired_jerseys || []);
            if (!rj.length) { rjEl.innerHTML = ''; }
            else {
                let rjHtml = `<h5 class="text-white-50 font-monospace mt-4 mb-2">🏟 Retired Jerseys</h5><div class="row g-2">`;
                rj.slice().reverse().forEach(c => {
                    rjHtml += `<div class="col-md-3 col-6">
                        <div class="p-2 text-center bg-dark rounded border border-secondary">
                            <div style="font-size:2rem;font-weight:900;color:#facc15;">#${c.jersey}</div>
                            <div class="small fw-bold text-white">${c.player}</div>
                            <div class="small text-white-50">${c.team}</div>
                            <div class="small text-white-50">${c.seasons} seasons · ${c.championships}x 🏆</div>
                        </div>
                    </div>`;
                });
                rjEl.innerHTML = rjHtml + '</div>';
            }
        }
    }

    let winGraphTeam = null;
    function setWinGraphTeam(team) {
        winGraphTeam = team;
        renderHistoryTab();
    }
    window.setWinGraphTeam = setWinGraphTeam;

    function renderWinGraph() {
        const el = document.getElementById('win-graph-render');
        if (!el || !winGraphTeam) return;
        const years = state.history.slice().sort((a, b) => a.year - b.year);
        const pts = years.map(h => {
            const rec = (h.standings || {})[winGraphTeam];
            const gp = rec ? rec.wins + rec.losses : 0;
            return {year: h.year, pct: gp > 0 ? rec.wins / gp : 0, wins: rec ? rec.wins : 0, losses: rec ? rec.losses : 0};
        }).filter(p => p.wins + p.losses > 0);
        if (pts.length < 2) { el.innerHTML = `<p class="text-white-50 small">Not enough completed seasons for ${winGraphTeam} yet.</p>`; return; }

        const W = 700, H = 220, padL = 40, padR = 20, padT = 20, padB = 30;
        const plotW = W - padL - padR, plotH = H - padT - padB;
        const xStep = plotW / (pts.length - 1);
        const xy = (i, pct) => [padL + i * xStep, padT + plotH - (pct * plotH)];

        const linePts = pts.map((p, i) => xy(i, p.pct).join(',')).join(' ');
        const color = teamColor(winGraphTeam);

        // Gridlines at 0%, 25%, 50%, 75%, 100%
        let gridSvg = '';
        [0, 0.25, 0.5, 0.75, 1].forEach(pct => {
            const y = padT + plotH - (pct * plotH);
            gridSvg += `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="#334155" stroke-width="1"/>`;
            gridSvg += `<text x="${padL - 8}" y="${y + 4}" fill="#9db4d9" font-size="10" text-anchor="end">${Math.round(pct * 100)}%</text>`;
        });

        let dotsSvg = '';
        let labelsSvg = '';
        pts.forEach((p, i) => {
            const [x, y] = xy(i, p.pct);
            dotsSvg += `<circle cx="${x}" cy="${y}" r="4" fill="${color}" stroke="#0b0f19" stroke-width="1.5">
                <title>${p.year}: ${p.wins}-${p.losses} (${(p.pct * 100).toFixed(1)}%)</title>
            </circle>`;
            if (i === 0 || i === pts.length - 1 || i % Math.ceil(pts.length / 10) === 0) {
                labelsSvg += `<text x="${x}" y="${H - 8}" fill="#9db4d9" font-size="10" text-anchor="middle">${p.year}</text>`;
            }
        });

        el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" style="width:100%; max-width:${W}px; background:#0b0f19; border-radius:8px;">
            ${gridSvg}
            <polyline points="${linePts}" fill="none" stroke="${color}" stroke-width="2.5"/>
            ${dotsSvg}
            ${labelsSvg}
        </svg>`;
    }

    // --- Bottom scrolling ticker: league-wide PPG/RPG/APG/SPG/BPG leaders ---
    function renderTicker() {
        const track = document.getElementById('ticker-track');
        if (!track || !state.players) return;
        const qualified = Object.values(state.players).filter(p => !p.retired && p.stats && p.stats.GP >= 5);
        if (qualified.length === 0) { track.innerHTML = `<span>Season underway — league leaders will populate once games are played.</span>`; return; }

        const leaderFor = (statKey, label) => {
            const sorted = qualified.slice().sort((a, b) => (b.stats[statKey] / b.stats.GP) - (a.stats[statKey] / a.stats.GP));
            const top = sorted[0];
            const avg = (top.stats[statKey] / top.stats.GP).toFixed(1);
            return `<span><span class="tk-label">${label} LEADER:</span> ${top.name} (${top.team}) <span class="tk-val">${avg}</span></span>`;
        };

        const parts = [
            leaderFor('PTS', 'PPG'), leaderFor('REB', 'RPG'), leaderFor('AST', 'APG'),
            leaderFor('STL', 'SPG'), leaderFor('BLK', 'BPG'),
        ];
        if (state.awards && state.awards.MVP) {
            parts.push(`<span><span class="tk-label">MVP RACE:</span> ${state.awards.MVP.name} (${state.awards.MVP.team}) <span class="tk-val">${state.awards.MVP.stat}</span></span>`);
        }
        if (state.awards && state.awards.All_NBA && state.awards.All_NBA.First) {
            const firstTeam = state.awards.All_NBA.First.map(p => p.name).join(', ');
            parts.push(`<span><span class="tk-label">ALL-NBA FIRST TEAM:</span> <span class="tk-val">${firstTeam}</span></span>`);
        }
        if (state.awards && state.awards.All_Defensive && state.awards.All_Defensive.First) {
            const defTeam = state.awards.All_Defensive.First.map(p => p.name).join(', ');
            parts.push(`<span><span class="tk-label">ALL-DEFENSIVE FIRST TEAM:</span> <span class="tk-val">${defTeam}</span></span>`);
        }
        if (state.awards && state.awards.Finals_MVP) {
            parts.push(`<span><span class="tk-label">FINALS MVP:</span> ${state.awards.Finals_MVP.name} (${state.awards.Finals_MVP.team}) <span class="tk-val">${state.awards.Finals_MVP.stat}</span></span>`);
        }
        track.innerHTML = parts.join('');
    }

    refreshState();