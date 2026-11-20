(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {tenant: 'alpha', samples: [], jobs: [], selected: null, busy: false, poll: null, failures: 0};
  const terminal = status => ['succeeded', 'failed', 'cancelled'].includes(status);
  const text = (id, value) => { $(id).textContent = value; };
  const number = value => Number.isFinite(Number(value)) && value !== null && value !== undefined;
  const ms = value => number(value) ? `${Number(value).toFixed(Number(value) < 10 ? 2 : 1)} ms` : '—';
  const integer = value => number(value) ? Number(value).toLocaleString() : '—';
  const memory = value => number(value) ? `${(Number(value) / 1048576).toFixed(2)} MiB` : '—';
  const time = value => {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
  };
  function node(tag, className, content) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (content !== undefined) item.textContent = content;
    return item;
  }
  function notice(message) {
    text('notice', message || '');
    $('notice').classList.toggle('hidden', !message);
  }
  function connection(online) {
    $('connection').className = `connection ${online ? 'online' : 'offline'}`;
    text('connection-text', online ? 'Runtime connected' : 'Connection unavailable');
  }
  async function request(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(path, {
        ...options,
        headers: {'X-Tenant': state.tenant, ...(options.body ? {'Content-Type': 'application/json'} : {}), ...options.headers},
        signal: controller.signal,
        cache: 'no-store'
      });
      let result;
      try { result = await response.json(); } catch (_) { throw new Error(`Server returned HTTP ${response.status}.`); }
      if (!response.ok) {
        const detail = result.detail || result.error || `Request failed (${response.status}).`;
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
      }
      return result;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('The server did not respond within 10 seconds. Check that WasmDock is running.');
      throw error;
    } finally { clearTimeout(timer); }
  }
  function statusPill(status) {
    const safe = ['queued', 'running', 'succeeded', 'failed', 'cancelled'].includes(status) ? status : 'neutral';
    return node('span', `status-pill ${safe}`, String(status || 'unknown').toUpperCase());
  }
  function renderBoundary(job = null) {
    const budgets = job?.budgets || {
      fuel: $('fuel').valueAsNumber,
      memory_mb: $('memory').valueAsNumber,
      timeout_ms: $('timeout').valueAsNumber,
      output_limit: $('output-limit').valueAsNumber,
      workspace: $('workspace-permission').checked
    };
    const entries = {
      fuel: [budgets.fuel, ''],
      memory: [budgets.memory_mb, ' MiB'],
      timeout: [budgets.timeout_ms, ' ms'],
      output: [budgets.output_limit, ' B']
    };
    for (const [name, [value, unit]] of Object.entries(entries)) {
      text('map-' + name, number(value) ? integer(value) + unit : '—');
    }
    text('map-capability', budgets.workspace ? '/workspace · read-only' : 'No directory grant');
    text('envelope-mode', job ? 'Selected job limits' : 'Draft limits');
  }
  function renderJob(job) {
    state.selected = job;
    $('empty-result').classList.add('hidden');
    $('job-result').classList.remove('hidden');
    $('job-status').className = statusPill(job.status).className;
    const label = String(job.status || 'unknown').toUpperCase();
    if ($('job-status').textContent !== label) text('job-status', label);
    text('job-id', job.id || '—');
    const metrics = job.metrics || {};
    text('job-queue', ms(metrics.queue_ms));
    text('job-time', ms(metrics.run_ms));
    text('job-fuel', integer(metrics.fuel_consumed));
    text('job-memory', memory(metrics.memory_bytes));
    text('stdout', job.output || '');
    const diagnostics = [job.stderr, job.error].filter(Boolean).join('\n');
    text('stderr', diagnostics);
    $('stderr').classList.toggle('hidden', !diagnostics);
    const reason = job.reason ? String(job.reason).replaceAll('_', ' ') : '';
    text('job-reason', reason);
    $('job-reason').classList.toggle('hidden', !reason);
    $('event-list').replaceChildren();
    for (const event of job.events || []) {
      const entry = node('li');
      if (typeof event === 'string') entry.textContent = event;
      else {
        const stamp = event.at || event.timestamp || event.time;
        if (stamp) entry.append(node('time', '', time(stamp)));
        const message = event.message || event.event || event.type || JSON.stringify(event);
        entry.append(node('span', '', message));
      }
      $('event-list').append(entry);
    }
    if (!(job.events || []).length) $('event-list').append(node('li', '', 'Awaiting execution events.'));
  }
  function renderHistory(jobs) {
    state.jobs = [...jobs].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
    $('history-body').replaceChildren();
    if (!jobs.length) {
      const row = node('tr'); const cell = node('td', 'table-empty', `No ${state.tenant} executions yet. Run your first plugin above.`);
      cell.colSpan = 6; row.append(cell); $('history-body').append(row); return;
    }
    for (const job of state.jobs.slice(0, 12)) {
      const row = node('tr');
      const id = node('td', '', String(job.id || '').slice(0, 12));
      id.title = job.id || ''; row.append(id);
      const status = node('td'); status.append(statusPill(job.status)); row.append(status);
      row.append(node('td', '', time(job.created_at)), node('td', '', ms(job.metrics?.run_ms)), node('td', '', integer(job.metrics?.fuel_consumed)));
      const action = node('td'); const button = node('button', 'view-job', 'Inspect ↗');
      button.type = 'button'; button.addEventListener('click', () => {
        renderJob(job);
        renderBoundary(job);
        $('result-panel').scrollIntoView({ block: 'start' });
      });
      action.append(button); row.append(action); $('history-body').append(row);
    }
  }
  function renderStats(stats) {
    text('workers', integer(stats.workers)); text('queued', integer(stats.queued));
    text('running', integer(stats.running)); text('completed', integer(stats.completed));
    text('queue-capacity', number(stats.max_queue) ? `${stats.max_queue} total queue capacity` : 'waiting for scheduler');
  }
  function applySample(id) {
    const sample = state.samples.find(s => s.id === id);
    if (sample) {
      $('wat').value = sample.wat || ''; $('stdin').value = sample.default_stdin || '';
      text('sample-description', sample.description || 'A real Wasmtime execution sample.');
      if (/file|denied|capability/i.test(sample.id)) $('workspace-permission').checked = false;
    } else text('sample-description', 'Write a WASI-compatible command module exporting _start. Resource limits still apply.');
  }
  async function loadSamples() {
    const result = await request('/api/samples');
    state.samples = Array.isArray(result) ? result : result.samples || [];
    $('sample').replaceChildren();
    for (const sample of state.samples) {
      const option = node('option', '', sample.name || sample.id); option.value = sample.id; $('sample').append(option);
    }
    const custom = node('option', '', 'Custom WAT module'); custom.value = '__custom__'; $('sample').append(custom);
    const first = state.samples.find(sample => /upper|text|csv|echo/i.test(sample.id)) || state.samples[0];
    if (first) { $('sample').value = first.id; applySample(first.id); }
  }
  async function refresh() {
    const tenantAtStart = state.tenant;
    try {
      const [stats, result] = await Promise.all([request('/api/stats'), request('/api/jobs')]);
      if (tenantAtStart !== state.tenant) return;
      const jobs = Array.isArray(result) ? result : result.jobs || [];
      renderStats(stats); renderHistory(jobs); connection(true); state.failures = 0;
      if (state.selected) {
        const updated = jobs.find(j => j.id === state.selected.id);
        if (updated) renderJob(updated);
        else if (!terminal(state.selected.status)) {
          const job = await request(`/api/jobs/${encodeURIComponent(state.selected.id)}`);
          if (tenantAtStart === state.tenant) renderJob(job);
        }
      }
    } catch (error) {
      state.failures += 1; connection(false);
      if (state.failures === 1) notice(error.message);
    }
  }
  function schedulePoll() {
    clearTimeout(state.poll);
    state.poll = setTimeout(async () => {
      if (!document.hidden) await refresh();
      schedulePoll();
    }, state.failures ? Math.min(15000, 2000 * state.failures) : 1500);
  }
  async function run() {
    if (state.busy) return;
    const wat = $('wat').value;
    if (!wat.trim()) { notice('Add a WebAssembly text module before running.'); $('wat').focus(); return; }
    const payload = {
      wat, stdin: $('stdin').value, fuel: Number($('fuel').value), memory_mb: Number($('memory').value),
      timeout_ms: Number($('timeout').value), output_limit: Number($('output-limit').value), workspace: $('workspace-permission').checked
    };
    if (![payload.fuel, payload.memory_mb, payload.timeout_ms, payload.output_limit].every(n => Number.isInteger(n) && n > 0)) {
      notice('Execution budgets must be positive whole numbers.'); return;
    }
    state.busy = true; $('run-button').disabled = true; text('run-label', 'Submitting…'); notice('');
    const tenant = state.tenant;
    try {
      const job = await request('/api/jobs', {method: 'POST', body: JSON.stringify(payload)});
      if (state.tenant === tenant) { renderJob(job); renderBoundary(job); await refresh(); }
    } catch (error) { notice(error.message); }
    finally { state.busy = false; $('run-button').disabled = false; text('run-label', 'Run plugin'); }
  }
  $('sample').addEventListener('change', event => { applySample(event.target.value); renderBoundary(); });
  for (const id of ['fuel', 'memory', 'timeout', 'output-limit', 'workspace-permission']) {
    $(id).addEventListener('input', () => renderBoundary());
  }
  $('wat').addEventListener('input', () => { const current = state.samples.find(s => s.id === $('sample').value); if (current && $('wat').value !== current.wat) $('sample').value = '__custom__'; });
  $('run-button').addEventListener('click', run);
  document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); run(); } });
  for (const button of document.querySelectorAll('[data-tenant]')) button.addEventListener('click', async () => {
    if (state.busy || state.tenant === button.dataset.tenant) return;
    state.tenant = button.dataset.tenant; state.selected = null; state.jobs = [];
    for (const item of document.querySelectorAll('[data-tenant]')) { const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active)); }
    text('history-tenant', state.tenant.toUpperCase()); $('job-result').classList.add('hidden'); $('empty-result').classList.remove('hidden');
    text('job-status', 'READY'); $('job-status').className = 'status-pill neutral'; renderBoundary(); notice(''); await refresh();
  });
  for (const button of document.querySelectorAll('[data-console]')) button.addEventListener('click', () => {
    const tab = button.dataset.console;
    for (const item of document.querySelectorAll('[data-console]')) { const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active)); }
    $('stdout-view').classList.toggle('hidden', tab !== 'stdout'); $('events-view').classList.toggle('hidden', tab !== 'events');
  });
  for (const button of document.querySelectorAll('[data-challenge]')) button.addEventListener('click', () => {
    const matchers = {fuel: /infinite|loop|fuel/, file: /denied|file|capability/, memory: /memory|grow/};
    const sample = state.samples.find(s => matchers[button.dataset.challenge].test(`${s.id} ${s.name}`.toLowerCase()));
    if (!sample) { notice('This challenge sample is unavailable. Check the loaded sample list.'); return; }
    $('sample').value = sample.id; applySample(sample.id);
    if (button.dataset.challenge === 'fuel') $('fuel').value = '100000';
    if (button.dataset.challenge === 'memory') $('memory').value = '1';
    renderBoundary();
    notice(''); $('workspace').scrollIntoView({block: 'start'}); $('run-button').focus({preventScroll: true});
  });
  $('refresh-button').addEventListener('click', async () => { notice(''); await refresh(); });
  $('copy-job').addEventListener('click', async () => { if (!state.selected) return; try { await navigator.clipboard.writeText(state.selected.id); } catch (_) { notice('Clipboard access is unavailable. Select the visible job identifier to copy it.'); } });
  $('download-result').addEventListener('click', () => {
    if (!state.selected) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(state.selected, null, 2)], {type: 'application/json'}));
    const link = node('a'); link.href = url; link.download = `wasmdock-${String(state.selected.id).replace(/[^a-zA-Z0-9_-]/g, '')}.json`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  renderBoundary();
  (async () => { try { await loadSamples(); await refresh(); } catch (error) { connection(false); notice(error.message); } finally { schedulePoll(); } })();
})();
