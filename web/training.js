'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  };
  let busy = false;
  let selectedMission = null;
  let ctfCatalog = null;
  let ctfJobId = null;
  const display = value => value === null || value === undefined || value === '' ? 'Unavailable' : String(value);
  const button = (parent, label, handler, className) => {
    const item = el('button', label, className);
    item.type = 'button';
    item.addEventListener('click', handler);
    parent.append(item);
    return item;
  };
  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin', ...options,
      headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json', 'X-Lab-Request': '1' } : {}), ...options.headers }
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
    return body;
  }
  const ctfPanel = document.createElement('section');
  ctfPanel.id = 'ctfPracticePanel';
  ctfPanel.className = 'panel';
  ctfPanel.innerHTML = '<p class="eyebrow">PINNED PUBLIC SOURCE / OFFLINE ONLY</p><h2>CTF practice lab</h2><p class="help">Twenty self-contained encoding and cipher warmups from a pinned MIT-licensed CTF collection. These are published challenge exercises, not incident telemetry; answers stay in a separate local organizer file and attempts never enter evidence or training datasets.</p><label for="ctfChallenge">Challenge</label><select id="ctfChallenge"></select><p id="ctfDescription"></p><details><summary>Challenge hint</summary><p id="ctfHint"></p></details><form id="ctfAttemptForm"><label for="ctfFlag">Submit flag</label><input id="ctfFlag" maxlength="160" autocomplete="off" required><button>Check flag</button></form><label for="ctfRole">Shared SLM role context</label><select id="ctfRole"><option value="analyst">Analyst</option><option value="defender">Defender</option><option value="web_blue">Web blue team</option><option value="web_red">Web red team</option><option value="nexus">DFIR</option><option value="aegis">Purple team</option></select><button id="ctfPractice" type="button">Ask the local model to solve</button><p id="ctfMessage" role="status" aria-live="polite"></p><pre id="ctfResponse" class="ops-result" aria-live="polite"></pre><p id="ctfProvenance" class="help"></p>';
  $('trainingConsole').after(ctfPanel);

  function renderCtf(data) {
    ctfCatalog = data;
    const select = $('ctfChallenge');
    const prior = select.value;
    select.replaceChildren();
    for (const challenge of data.challenges || []) {
      const option = document.createElement('option');
      option.value = challenge.id;
      option.textContent = `${challenge.title} · ${challenge.category} · ${challenge.points} pts${challenge.solved ? ' · solved' : ''}`;
      select.append(option);
    }
    if ([...select.options].some(option => option.value === prior)) select.value = prior;
    showCtfChallenge();
    const source = data.source || {};
    $('ctfProvenance').textContent = data.status === 'ready'
      ? `${data.challenges?.length || 0} challenges · ${data.challenges?.reduce((n, c) => n + (c.solved ? 1 : 0), 0) || 0} solved · ${source.source_repository || 'Source unavailable'} @ ${(source.source_commit || '').slice(0, 12)} · ${source.license || 'license unavailable'} · no network targets`
      : `CTF catalog unavailable: ${data.error || 'not initialized'}`;
  }

  function showCtfChallenge() {
    const challenge = ctfCatalog?.challenges?.find(item => item.id === $('ctfChallenge').value);
    $('ctfDescription').textContent = challenge ? `${challenge.description} (${challenge.points} points)` : 'Offline CTF catalog is unavailable.';
    $('ctfHint').textContent = challenge?.hint || 'No hint is available.';
  }

  async function pollCtfJob() {
    if (!ctfJobId) return;
    try {
      const state = await api('/api/state');
      const job = state.jobs.find(item => item.id === ctfJobId);
      if (!job) return;
      if (job.status === 'running') return;
      if (job.status === 'failed') $('ctfResponse').textContent = `Practice failed: ${job.error || 'unknown error'}`;
      else {
        const model = job.result?.model_response || {};
        const attempt = job.result?.attempt || {};
        $('ctfResponse').textContent = `${model.text || 'The local model returned no text.'}\n\nModel flag check: ${attempt.correct ? 'correct' : 'not solved'} · Device: ${model.device_name || model.device || 'unavailable'}`;
      }
      ctfJobId = null;
      await refresh();
    } catch (error) {
      $('ctfMessage').textContent = `Could not retrieve model result: ${error.message}`;
      ctfJobId = null;
    }
  }
  function renderTopology(topology, data) {
    const root = $('trainingTopology');
    root.replaceChildren();
    const services = data.services || [];
    if (!topology?.available) {
      root.append(el('p', topology?.note || 'Declared service topology is unavailable.', 'training-empty'));
      return;
    }
    const observed = Object.fromEntries(services.map(item => [item.service, item]));
    for (const network of topology.networks || []) {
      const box = el('section', undefined, 'training-network');
      box.append(el('strong', `${network.id} · ${network.internal ? 'internal network' : 'non-internal network'}`));
      const members = (topology.nodes || []).filter(node => (node.networks || []).includes(network.id));
      const nodeList = el('div', undefined, 'training-topology');
      for (const service of members) {
        const probe = observed[service.id];
        const status = probe?.status || 'not_probed';
        const node = el('article', undefined, 'training-node');
        node.dataset.status = status;
        node.tabIndex = 0;
        node.title = `${service.id} membership in ${network.id} is from the compose declaration`;
        node.append(el('strong', service.id), el('span', probe ? `${status} · HTTP ${display(probe.http_status)}` : 'No live health probe'),
          el('small', `${service.host_published ? 'Host published' : 'No host port declared'}${service.host_bindings?.length ? ` · ${service.host_bindings.map(x => x.scope).join(', ')}` : ''}`));
        nodeList.append(node);
      }
      box.append(nodeList);
      root.append(box);
    }
    root.append(el('p', `Health probes: ${data.status || 'unknown'} · Topology source: ${topology.source} · ${topology.note}`, 'help'));
  }
  function renderAttack(refs = []) {
    const root = $('trainingAttackRefs');
    root.replaceChildren();
    for (const reference of refs) {
      const item = el('article', undefined, 'training-technique');
      item.append(el('strong', `${reference.id} · ${reference.name}`),
        el('small', `${reference.status} — reference context, not observed activity`));
      root.append(item);
    }
  }
  function renderMissions(missions) {
    const root = $('trainingMissions');
    root.replaceChildren();
    if (!missions.length) {
      root.append(el('p', 'No live review records yet. Start a read-only review to capture current AZRAEL service measurements.', 'training-empty'));
      return;
    }
    for (const mission of missions) {
      const card = el('article', undefined, 'training-mission');
      const header = el('header');
      header.append(el('strong', `${mission.scenario_id} · ${mission.status}`),
        el('span', `${mission.created_at} · completion ${display(mission.completion_score)}%`));
      card.append(header, el('small', `ID ${mission.id} · evidence SHA-256 ${mission.source_sha256} · review ${mission.review_status}${mission.dataset_split ? ` · split ${mission.dataset_split}` : ''}`));
      const counts = Object.entries(mission.task_counts || {}).map(([state, count]) => `${state}: ${count}`).join(' · ');
      card.append(el('p', counts || 'Tasks are queued.'));
      button(card, 'Open / replay record', () => loadMission(mission.id), 'quiet');
      if (['queued', 'running', 'cancel_requested'].includes(mission.status)) {
        button(card, 'Cancel mission', async () => {
          try { await api(`/api/training/missions/${mission.id}/cancel`, { method: 'POST', body: '{}' }); await refresh(mission.id); }
          catch (error) { message(error.message); }
        }, 'quiet');
      }
      if (mission.review_status === 'accepted') {
        const link = el('a', 'Export reviewed record ↗');
        link.href = `/api/training/missions/${mission.id}/export`;
        link.target = '_blank'; link.rel = 'noopener'; card.append(link);
      }
      root.append(card);
    }
  }
  function renderMetrics(metrics) {
    const root = $('trainingRoleMetrics');
    root.replaceChildren();
    const table = el('table', undefined, 'ops-table');
    const head = el('thead');
    const tr = el('tr');
    ['Role', 'Tasks', 'Completed', 'Failed', 'Cancelled', 'Mean latency'].forEach(x => tr.append(el('th', x)));
    head.append(tr); table.append(head);
    const body = el('tbody');
    for (const role of metrics.roles || []) {
      const row = el('tr');
      const mean = role.task_count ? Math.round(role.latency_total_ms / role.task_count) : null;
      [role.role, role.task_count, role.completed, role.failed, role.cancelled, mean === null ? 'Unavailable' : `${mean} ms`]
        .forEach(value => row.append(el('td', value)));
      body.append(row);
    }
    table.append(body); root.append(table);
    const versions = $('trainingDatasetVersions');
    versions.replaceChildren();
    for (const item of metrics.dataset_versions || []) {
      versions.append(el('p', `${item.split} dataset · ${item.mission_ids.length} reviewed record(s) · SHA-256 ${item.version_hash} · reviewer ${item.reviewer}`));
    }
    if (!(metrics.dataset_versions || []).length) versions.append(el('p', 'No human-reviewed training dataset versions yet.', 'training-empty'));
  }
  function renderStatus(coordinator) {
    const root = $('trainingStatus');
    root.replaceChildren();
    const cards = [
      ['Coordinator', coordinator.status], ['Queue', `${coordinator.queue_depth} queued · limit ${coordinator.concurrency_limit}`],
      ['Shared model', coordinator.shared_slm ? 'One local SLM / serialized' : 'Unavailable'],
      ['Emergency stop', coordinator.emergency_stopped ? 'ENGAGED' : 'Clear']
    ];
    for (const [title, value] of cards) {
      const card = el('article', undefined, 'ops-stat');
      card.append(el('span', title), el('strong', value)); root.append(card);
    }
    $('trainingReset').hidden = !coordinator.emergency_stopped;
    $('trainingStart').disabled = coordinator.emergency_stopped;
  }
  function renderMission(mission) {
    selectedMission = mission.id;
    const root = $('trainingMissionDetail');
    root.replaceChildren();
    const heading = el('div', undefined, 'section-heading');
    heading.append(el('h4', 'Historical replay · stored mission record'), el('span', mission.status));
    root.append(heading, el('p', `Scenario ${mission.scenario_id} v${mission.scenario_version} · source SHA-256 ${mission.source_sha256} · captured ${mission.created_at}`));
    root.append(el('p', 'Replay shows the exact persisted live observation snapshot and role outputs. It does not re-run tasks or change services. The seven role contexts use one shared local model; their output is unverified until reviewed.'));
    const snapshot = document.createElement('details');
    snapshot.append(el('summary', 'Inspect measured observations and provenance'));
    const pre = el('pre', JSON.stringify(mission.snapshot, null, 2)); snapshot.append(pre); root.append(snapshot);
    const timeline = el('div', undefined, 'training-timeline');
    for (const task of mission.tasks || []) {
      const item = el('article', undefined, 'training-task');
      item.dataset.state = task.state;
      const header = el('header');
      header.append(el('strong', `${task.phase} · ${task.role}`), el('span', task.state));
      item.append(header, el('small', `Dependencies: ${(task.depends_on || []).join(', ') || 'live snapshot'} · input ${display(task.input_sha256)} · ${display(task.latency_ms)}${task.latency_ms === null ? '' : ' ms'}`));
      if (task.output?.text) item.append(el('p', task.output.text));
      if (task.error) item.append(el('p', `Error: ${task.error}`, 'ops-error'));
      timeline.append(item);
    }
    root.append(timeline);
    if (mission.completion_score !== null) root.append(el('p', `Workflow completeness: ${mission.completion_score}% (task coverage only, not response accuracy).`));
    if (mission.review_status === 'pending_review' && ['pending_review', 'partial'].includes(mission.status)) {
      const form = document.createElement('form');
      form.className = 'training-review';
      const disposition = document.createElement('select');
      disposition.id = 'trainingDisposition';
      disposition.append(new Option('Accept into training split', 'training'), new Option('Accept into validation split', 'validation'), new Option('Accept into test split', 'test'), new Option('Reject record', 'reject'));
      const confidence = document.createElement('input'); confidence.id = 'trainingConfidence'; confidence.type = 'number'; confidence.min = '0'; confidence.max = '1'; confidence.step = '0.01'; confidence.value = '0.8'; confidence.required = true;
      const note = document.createElement('textarea'); note.id = 'trainingReviewNote'; note.maxLength = 2000; note.required = true; note.placeholder = 'Explain provenance, label, and output review';
      const dispositionLabel = el('label', 'Human decision'); dispositionLabel.append(disposition);
      const confidenceLabel = el('label', 'Reviewer confidence (0–1)'); confidenceLabel.append(confidence);
      const noteLabel = el('label', 'Review note'); noteLabel.append(note);
      const submit = el('button', 'Record human review'); submit.type = 'submit';
      form.append(dispositionLabel, confidenceLabel, noteLabel, submit);
      form.addEventListener('submit', async event => {
        event.preventDefault(); submit.disabled = true;
        const decision = disposition.value === 'reject' ? 'reject' : 'accept';
        const payload = { decision, confidence: Number(confidence.value), note: note.value };
        if (decision === 'accept') payload.split = disposition.value;
        try { await api(`/api/training/missions/${mission.id}/review`, { method: 'POST', body: JSON.stringify(payload) }); await refresh(mission.id); }
        catch (error) { message(error.message); submit.disabled = false; }
      });
      root.append(form);
    } else if (mission.review) {
      root.append(el('p', `Human review: ${mission.review.decision} by ${mission.review.reviewer} · confidence ${mission.review.confidence} · ${mission.review.note}`));
      if (mission.dataset_version_hash) root.append(el('p', `Dataset version ${mission.dataset_split}: ${mission.dataset_version_hash}`));
    }
  }
  async function loadMission(id) {
    try { renderMission(await api(`/api/training/missions/${id}`)); }
    catch (error) { message(error.message); }
  }
  function message(value = '') { $('trainingMessage').textContent = value; }
  async function refresh(preferredId = selectedMission) {
    if (busy || $('workspace')?.hidden) return;
    busy = true;
    try {
      const [training, containers] = await Promise.all([api('/api/training'), api('/api/ops/containers')]);
      const ctf = await api('/api/ctf').catch(error => ({status: 'unavailable', error: error.message, source: {}, challenges: []}));
      renderStatus(training.coordinator);
      renderMissions(training.missions);
      renderTopology(training.coordinator.topology, containers);
      renderAttack(training.coordinator.attack_references);
      renderMetrics(training.coordinator);
      renderCtf(ctf);
      const chosen = training.missions.find(item => item.id === preferredId) || training.missions[0];
      if (chosen) await loadMission(chosen.id);
      else $('trainingMissionDetail').replaceChildren(el('p', 'Start a live review to create a replayable, evidence-linked record.', 'training-empty'));
      message('');
    } catch (error) { message(`Live training data unavailable: ${error.message}`); }
    finally { busy = false; }
  }
  $('trainingStartForm').addEventListener('submit', async event => {
    event.preventDefault();
    const buttonElement = $('trainingStart'); buttonElement.disabled = true; message('Capturing live measurements and queueing the approved role review…');
    try {
      const result = await api('/api/training/missions', { method: 'POST', body: JSON.stringify({ approved: $('trainingApprove').checked, priority: $('trainingPriority').value }) });
      $('trainingApprove').checked = false;
      await refresh(result.mission_id);
    } catch (error) { message(error.message); }
    finally { buttonElement.disabled = false; }
  });
  $('trainingEmergency').addEventListener('click', async () => {
    if (!confirm('Stop queued and active training tasks? AZRAEL services will remain running.')) return;
    try { await api('/api/training/emergency-stop', { method: 'POST', body: '{}' }); await refresh(); }
    catch (error) { message(error.message); }
  });
  $('trainingReset').addEventListener('click', async () => {
    if (!confirm('Reset the training coordinator emergency stop?')) return;
    try { await api('/api/training/reset', { method: 'POST', body: JSON.stringify({ confirmed: true }) }); await refresh(); }
    catch (error) { message(error.message); }
  });
  $('trainingRefresh').addEventListener('click', () => refresh());
  $('ctfChallenge').addEventListener('change', showCtfChallenge);
  $('ctfAttemptForm').addEventListener('submit', async event => {
    event.preventDefault();
    $('ctfMessage').textContent = '';
    try {
      const result = await api('/api/ctf/attempt', {method: 'POST', body: JSON.stringify({challenge_id: $('ctfChallenge').value, flag: $('ctfFlag').value})});
      $('ctfMessage').textContent = result.correct ? 'Correct flag. Progress saved in the isolated CTF practice store.' : 'That flag did not match. Try the hint or ask the local model.';
      $('ctfFlag').value = '';
      await refresh();
    } catch (error) { $('ctfMessage').textContent = error.message; }
  });
  $('ctfPractice').addEventListener('click', async () => {
    $('ctfMessage').textContent = '';
    $('ctfResponse').textContent = '';
    try {
      const response = await api('/api/ctf/practice', {method: 'POST', body: JSON.stringify({challenge_id: $('ctfChallenge').value, role: $('ctfRole').value})});
      ctfJobId = response.job_id;
      $('ctfMessage').textContent = 'Queued for the shared local SLM. The answer key is not included in its prompt.';
      pollCtfJob();
    } catch (error) { $('ctfMessage').textContent = error.message; }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  setInterval(refresh, 5000);
  setInterval(pollCtfJob, 1000);
  refresh();
})();
