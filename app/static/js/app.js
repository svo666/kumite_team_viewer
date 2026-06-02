const state = { timer: null, lastTeams: [] };
const els = {
  sourceUrl: document.getElementById('sourceUrl'),
  tatamiIds: document.getElementById('tatamiIds'),
  teamSelect: document.getElementById('teamSelect'),
  pollSeconds: document.getElementById('pollSeconds'),
  refreshBtn: document.getElementById('refreshBtn'),
  statusText: document.getElementById('statusText'),
  errorText: document.getElementById('errorText'),
  head: document.getElementById('scheduleHead'),
  body: document.getElementById('scheduleBody'),
};

function params(force = false) {
  const p = new URLSearchParams();
  p.set('source_url', els.sourceUrl.value.trim());
  p.set('tatami_ids', els.tatamiIds.value.trim());
  p.set('team', els.teamSelect.value);
  if (force) p.set('force', '1');
  return p.toString();
}

async function load(force = false) {
  setBusy(true);
  try {
    const res = await fetch(`/api/fights?${params(force)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    updateTeamOptions(data.teams, data.selected_team);
    render(data);
  } catch (err) {
    els.errorText.textContent = String(err);
  } finally {
    setBusy(false);
  }
}

function setBusy(busy) {
  els.refreshBtn.disabled = busy;
  if (busy) els.statusText.textContent = 'Loading...';
}

function updateTeamOptions(teams, selected) {
  const same = JSON.stringify(teams) === JSON.stringify(state.lastTeams);
  if (same) return;
  state.lastTeams = teams;
  els.teamSelect.innerHTML = '<option value="">All teams</option>';
  for (const team of teams) {
    const opt = document.createElement('option');
    opt.value = team;
    opt.textContent = team;
    if (team === selected) opt.selected = true;
    els.teamSelect.appendChild(opt);
  }
}

function render(data) {
  els.errorText.textContent = data.last_error ? `Last refresh error: ${data.last_error}` : '';
  const updated = data.last_updated ? new Date(data.last_updated).toLocaleString() : 'never';
  els.statusText.textContent = `Last updated: ${updated} | ${data.fights.length} fights shown`;
  const grouped = groupByTatami(data.fights);
  const tatamis = Object.keys(grouped).sort((a, b) => Number(a) - Number(b));
  renderHead(tatamis, grouped);
  renderBody(tatamis, grouped);
}

function groupByTatami(fights) {
  return fights.reduce((acc, f) => {
    (acc[f.tatami_id] ||= { name: f.tatami_name, fights: [] }).fights.push(f);
    return acc;
  }, {});
}

function renderHead(tatamis, grouped) {
  els.head.innerHTML = '';
  if (!tatamis.length) return;
  const r1 = document.createElement('tr');
  const r2 = document.createElement('tr');
  for (const id of tatamis) {
    r1.innerHTML += `<th class="tatami-header" colspan="5">${escapeHtml(grouped[id].name)}</th>`;
    r2.innerHTML += '<th>Actual #</th><th>Category</th><th>Fight</th><th>Opponent A</th><th>Opponent B</th>';
  }
  els.head.append(r1, r2);
}

function renderBody(tatamis, grouped) {
  els.body.innerHTML = '';
  if (!tatamis.length) {
    els.body.innerHTML = '<tr><td class="empty">No fights match the selected filters.</td></tr>';
    return;
  }
  const maxRows = Math.max(...tatamis.map(id => grouped[id].fights.length));
  for (let i = 0; i < maxRows; i++) {
    const tr = document.createElement('tr');
    for (const id of tatamis) {
      const f = grouped[id].fights[i];
      if (!f) {
        tr.innerHTML += '<td></td><td></td><td></td><td></td><td></td>';
        continue;
      }
      const currentCls = f.is_current ? 'current' : '';
      tr.innerHTML += `<td class="${currentCls}">${f.actual_fight_no ?? ''}</td>`;
      tr.innerHTML += `<td class="${currentCls}">${escapeHtml(f.category)}</td>`;
      tr.innerHTML += `<td class="${currentCls}">${escapeHtml(f.fight)}</td>`;
      tr.innerHTML += fighterCell(f.opponent_a, currentCls);
      tr.innerHTML += fighterCell(f.opponent_b, currentCls);
    }
    els.body.appendChild(tr);
  }
}

function fighterCell(opponent, rowClass) {
  const cls = `${rowClass} ${opponent.is_winner ? 'winner' : ''}`.trim();
  const meta = [opponent.team, opponent.nationality].filter(Boolean).join(' - ');
  return `<td class="${cls}"><div class="fighter">${escapeHtml(opponent.name)}<span class="team">${escapeHtml(meta)}</span></div></td>`;
}

function schedulePolling() {
  clearInterval(state.timer);
  const seconds = Math.max(30, Number(els.pollSeconds.value || 60));
  state.timer = setInterval(() => load(false), seconds * 1000);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

els.refreshBtn.addEventListener('click', () => load(true));
els.teamSelect.addEventListener('change', () => load(false));
els.sourceUrl.addEventListener('change', () => load(true));
els.tatamiIds.addEventListener('change', () => load(true));
els.pollSeconds.addEventListener('change', schedulePolling);

schedulePolling();
load(false);
