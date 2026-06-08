const state = {
  eventSource: null,
  latestData: null,
  lastTeams: [],
  connected: false,
};

const els = {
  sourceUrl: document.getElementById('sourceUrl'),
  teamSelect: document.getElementById('teamSelect'),
  refreshBtn: document.getElementById('refreshBtn'),
  statusText: document.getElementById('statusText'),
  connectionText: document.getElementById('connectionText'),
  errorText: document.getElementById('errorText'),
  head: document.getElementById('scheduleHead'),
  body: document.getElementById('scheduleBody'),
};

function sourceParams() {
  const p = new URLSearchParams();
  p.set('source_url', els.sourceUrl.value.trim());
  return p.toString();
}

function connectEvents() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }

  state.connected = false;
  setConnection('Connecting to live updates...');

  const es = new EventSource(`/api/events?${sourceParams()}`);
  state.eventSource = es;

  es.addEventListener('open', () => {
    state.connected = true;
    setConnection('Connected. Server pushes updates after each refresh.');
  });

  es.addEventListener('snapshot', (event) => {
    const data = JSON.parse(event.data);
    state.latestData = data;
    updateTeamOptions(data.teams);
    renderCurrentFilter();
    setConnection(`Connected. Server polls every ${data.server_poll_seconds || 60} seconds.`);
  });

  es.onerror = () => {
    state.connected = false;
    setConnection('Live connection interrupted. Browser will reconnect automatically...');
  };
}

async function refreshNow() {
  setBusy(true);
  try {
    const res = await fetch('/api/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_url: els.sourceUrl.value.trim(),
        team: els.teamSelect.value,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    state.latestData = data;
    updateTeamOptions(data.teams);
    renderCurrentFilter();
  } catch (err) {
    els.errorText.textContent = String(err);
  } finally {
    setBusy(false);
  }
}

function setBusy(busy) {
  els.refreshBtn.disabled = busy;
  if (busy) els.statusText.textContent = 'Refreshing now...';
}

function setConnection(text) {
  els.connectionText.textContent = text;
}

function updateTeamOptions(teams) {
  const current = els.teamSelect.value;
  const same = JSON.stringify(teams) === JSON.stringify(state.lastTeams);
  if (same) return;

  state.lastTeams = teams;
  els.teamSelect.innerHTML = '<option value="">All teams</option>';
  for (const team of teams) {
    const opt = document.createElement('option');
    opt.value = team;
    opt.textContent = team;
    if (team === current) opt.selected = true;
    els.teamSelect.appendChild(opt);
  }
}

function renderCurrentFilter() {
  if (!state.latestData) return;
  const selectedTeam = els.teamSelect.value;
  const filteredFights = selectedTeam
    ? state.latestData.fights.filter(f => f.opponent_a.team === selectedTeam || f.opponent_b.team === selectedTeam)
    : state.latestData.fights;

  render({
    ...state.latestData,
    selected_team: selectedTeam,
    fights: filteredFights,
  });
}

function render(data) {
  els.errorText.textContent = data.last_error ? `Last refresh error: ${data.last_error}` : '';
  const updated = data.last_updated ? new Date(data.last_updated).toLocaleString() : 'never';
  const teamText = data.selected_team ? ` | team: ${data.selected_team}` : ' | all teams';
  const refreshingText = data.refreshing ? ' | refresh in progress' : '';
  els.statusText.textContent = `Last updated: ${updated} | Tatamis ${data.tatami_ids.join(', ')} | ${data.fights.length} fights shown${teamText}${refreshingText}`;

  const grouped = groupByTatami(data.fights);
  const tatamis = Object.keys(grouped).sort((a, b) => Number(a) - Number(b));
  const actualFightNumbers = actualFightNumbersByTatami(state.latestData?.fights || data.fights);
  renderHead(tatamis, grouped, actualFightNumbers);
  renderBody(tatamis, grouped);
}

function groupByTatami(fights) {
  return fights.reduce((acc, f) => {
    (acc[f.tatami_id] ||= { name: f.tatami_name, fights: [] }).fights.push(f);
    return acc;
  }, {});
}

function actualFightNumbersByTatami(fights) {
  return fights.reduce((acc, fight) => {
    if (fight.is_current && fight.actual_fight_no !== null && fight.actual_fight_no !== undefined) {
      acc[fight.tatami_id] = fight.actual_fight_no;
    }
    return acc;
  }, {});
}

function renderHead(tatamis, grouped, actualFightNumbers) {
  els.head.innerHTML = '';
  if (!tatamis.length) return;
  const r1 = document.createElement('tr');
  const r2 = document.createElement('tr');
  r1.className = 'tatami-title-row';
  r2.className = 'column-title-row';

  for (const id of tatamis) {
    const actualFightNo = actualFightNumbers[id] ?? '-';
    const title = `${grouped[id].name} - actual fight # ${actualFightNo}`;
    r1.innerHTML += `<th class="tatami-header" colspan="3">${escapeHtml(title)}</th>`;
    r2.innerHTML += '<th class="tatami-start">Fight #</th><th class="opponent-a-header">Opponent A</th><th class="opponent-b-header tatami-end">Opponent B</th>';
  }
  els.head.append(r1, r2);
}

function renderBody(tatamis, grouped) {
  els.body.innerHTML = '';
  if (!tatamis.length) {
    els.body.innerHTML = '<tr><td class="empty">No fights match the selected filters, or no data could be parsed yet.</td></tr>';
    return;
  }

  const maxRows = Math.max(...tatamis.map(id => grouped[id].fights.length));
  for (let i = 0; i < maxRows; i++) {
    const tr = document.createElement('tr');
    for (const id of tatamis) {
      const f = grouped[id].fights[i];
      if (!f) {
        tr.innerHTML += '<td class="tatami-start"></td><td></td><td class="tatami-end"></td>';
        continue;
      }
      const currentCls = f.is_current ? 'current' : '';
      tr.innerHTML += `<td class="${cellClasses(currentCls, 'tatami-start')}">${f.actual_fight_no ?? ''}</td>`;
      tr.innerHTML += fighterCell(f.opponent_a, currentCls);
      tr.innerHTML += fighterCell(f.opponent_b, `${currentCls} tatami-end`.trim());
    }
    els.body.appendChild(tr);
  }
}

function cellClasses(...classes) {
  return classes.filter(Boolean).join(' ');
}

function fighterCell(opponent, rowClass) {
  const cls = `${rowClass} ${opponent.is_winner ? 'winner' : ''}`.trim();
  const meta = [opponent.team, opponent.nationality].filter(Boolean).join(' - ');
  return `<td class="${cls}"><div class="fighter">${escapeHtml(opponent.name)}<span class="team">${escapeHtml(meta)}</span></div></td>`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

els.refreshBtn.addEventListener('click', refreshNow);
els.teamSelect.addEventListener('change', renderCurrentFilter);
els.sourceUrl.addEventListener('change', connectEvents);

connectEvents();
