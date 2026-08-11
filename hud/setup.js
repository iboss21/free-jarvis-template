import { Orb, ORB_VARIANTS } from '/orb.js';
import { THEMES, applyTheme } from '/themes.js';
import { mountAtmosphere } from '/atmosphere.js';

const $ = (id) => document.getElementById(id);
const api = async (path, body) => {
  const r = await fetch(path, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  } : {});
  return r.json();
};

const STEP_NAMES = ['', 'welcome', 'system check', 'folders', 'the brain',
                    'voice', 'appearance', 'deploy'];
const TOTAL = 7;

const state = {
  step: 1,
  brain: 'existing',
  voice: 'off',
  lang: 'en',
  theme: 'obsidian',
  variant: 'lattice',
  speed: 1,
  density: 900,
  quant: '',
  dirs: { app: '', vault: '', models: '' },
  preflight: null,
  jobs: [],
};

let atmosphere = null;
let heroOrb = null;
let prevOrb = null;

/* ── navigation ─────────────────────────────────────────────────────── */

function go(n) {
  n = Math.max(1, Math.min(TOTAL, n));
  document.querySelectorAll('.step').forEach((el) => {
    el.classList.toggle('on', Number(el.dataset.step) === n);
  });
  state.step = n;
  $('rail').style.width = `${(n / TOTAL) * 100}%`;
  $('step-n').textContent = n;
  $('step-name').textContent = STEP_NAMES[n];
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (n === 6) mountPreview();
  if (n === 7) renderSummary();
}

document.addEventListener('click', (e) => {
  if (e.target.closest('[data-next]')) go(state.step + 1);
  if (e.target.closest('[data-back]')) go(state.step - 1);
});

/* ── step 1 + 2: preflight ──────────────────────────────────────────── */

const GLYPH = { ok: '●', warn: '◐', bad: '○' };

async function loadPreflight() {
  const pf = await api('/api/setup/preflight');
  state.preflight = pf;

  $('f-os').textContent = pf.platform;
  $('f-py').textContent = pf.python;
  $('f-gpu').textContent = pf.gpu.vram_gb
    ? `${pf.gpu.name} · ${pf.gpu.vram_gb} GB` : 'none detected';

  $('checks').innerHTML = pf.checks.map((c) => {
    const cls = c.ok ? 'ok' : (c.required ? 'bad' : 'warn');
    return `<div class="chk ${cls}">
      <span class="g">${GLYPH[cls]}</span>
      <span><span class="l">${c.label}</span><span class="d">${c.detail}</span></span>
      <span class="d">${c.ok ? '' : (c.fix.startsWith('pip:') ? 'installed at deploy' : c.fix)}</span>
    </div>`;
  }).join('');

  const blocked = pf.checks.some((c) => c.required && !c.ok);
  $('pf-next').disabled = blocked;
  if (blocked) $('pf-next').textContent = 'Fix the red items first';
}

/* ── step 3: folders ────────────────────────────────────────────────── */

async function loadDirs() {
  const d = await api('/api/setup/dirs');
  state.dirs = { app: d.app, vault: d.vault, models: d.models };
  $('d-app').value = d.app;
  $('d-vault').value = d.vault;
  $('d-models').value = d.models;

  $('drives').innerHTML = (d.drives || []).map((dr) =>
    `<div class="drive" data-path="${dr.path}"><b>${dr.path}</b><i>${dr.free_gb} GB free</i></div>`
  ).join('');

  $('drives').addEventListener('click', (e) => {
    const el = e.target.closest('.drive');
    if (!el) return;
    const base = el.dataset.path.replace(/\/$/, '');
    $('d-models').value = `${base}/Reges/models`;
  });

  ['app', 'vault', 'models'].forEach((k) => {
    $(`d-${k}`).addEventListener('input', (e) => { state.dirs[k] = e.target.value; });
  });
}

/* ── step 4: brain ──────────────────────────────────────────────────── */

let catalogData = null;

document.querySelectorAll('[data-brain]').forEach((b) => {
  b.addEventListener('click', () => {
    state.brain = b.dataset.brain;
    document.querySelectorAll('[data-brain]').forEach((x) => x.classList.toggle('sel', x === b));
    $('p-local').hidden = state.brain !== 'local';
    $('p-api').hidden = state.brain !== 'api';
    $('p-existing').hidden = state.brain !== 'existing';
    if (state.brain === 'local' && !catalogData) loadCatalog();
  });
});

async function loadCatalog() {
  catalogData = await api('/api/setup/catalog');
  const m = catalogData.models[0];
  const rec = catalogData.recommended;
  const gpu = catalogData.gpu;

  $('gpu-line').innerHTML = gpu.vram_gb
    ? `Detected <b>${gpu.name}</b> with <b>${gpu.vram_gb} GB</b>. ${rec.why}`
    : `No GPU detected. ${rec.why}`;

  $('model-card').innerHTML = `
    <h3>${m.name}</h3>
    <p>${m.blurb}</p>
    <div class="meta"><span>${m.params}</span><span>${m.license}</span>
      <span><a href="${m.homepage}" target="_blank" rel="noopener">repository</a></span></div>`;

  state.quant = rec.quant || '';
  $('quants').innerHTML = m.quants.map((q) => {
    const isRec = q.file === rec.quant;
    return `<div class="q ${isRec ? 'sel rec' : ''}" data-file="${q.file}">
      <span><span class="n">${q.label}</span>${q.note ? `<span class="s"> — ${q.note}</span>` : ''}</span>
      <span class="gb">${q.gb} GB</span>
      <span class="tag">${isRec ? 'BEST FOR YOU' : ''}</span>
    </div>`;
  }).join('');

  $('quants').addEventListener('click', (e) => {
    const el = e.target.closest('.q');
    if (!el) return;
    state.quant = el.dataset.file;
    document.querySelectorAll('.q').forEach((x) => x.classList.toggle('sel', x === el));
  });
}

async function loadProviders() {
  const s = await api('/api/settings');
  $('api-provider').innerHTML = s.providers
    .filter((p) => p.kind === 'hosted')
    .map((p) => `<option value="${p.id}">${p.label}</option>`).join('');
}

$('ex-fetch').addEventListener('click', async () => {
  const res = $('ex-res');
  res.className = 'result'; res.textContent = 'looking…';
  const r = await api('/api/models', { provider: 'custom_openai', base_url: $('ex-url').value });
  if (r.ok && r.models.length) {
    res.className = 'result ok';
    res.textContent = `${r.models.length} found: ${r.models.slice(0, 6).join(', ')}`;
    $('ex-model').value = r.models[0];
  } else {
    res.className = 'result bad';
    res.textContent = r.error || 'nothing there — is the server running?';
  }
});

/* ── step 5: voice ──────────────────────────────────────────────────── */

document.querySelectorAll('[data-voice]').forEach((b) => {
  b.addEventListener('click', () => {
    state.voice = b.dataset.voice;
    document.querySelectorAll('[data-voice]').forEach((x) => x.classList.toggle('sel', x === b));
    $('p-voice').hidden = state.voice !== 'on';
    if (state.voice === 'on') {
      loadLanguages();
      $('dep-voice').innerHTML =
        `<div class="hint">At deploy Reges will install <b>faster-whisper</b>` +
        (state.preflight?.gpu?.vram_gb ? ` plus the CUDA runtime so your card does the work` : '') +
        `. Text-to-speech uses what your system already has — nothing to download.</div>`;
    }
  });
});

async function loadLanguages() {
  const sel = $('w-lang');
  if (sel.options.length) return;
  const v = await api('/api/voice/status');
  sel.innerHTML = (v.languages || [{ code: 'en', label: 'English' }])
    .map((l) => `<option value="${l.code}">${l.label}</option>`).join('');
  sel.value = state.lang;
  sel.addEventListener('change', () => { state.lang = sel.value; });
}

/* ── step 6: appearance ─────────────────────────────────────────────── */

function mountPreview() {
  if (prevOrb) return;
  prevOrb = new Orb($('prev-orb'), {
    count: state.density, speed: state.speed, variant: state.variant,
  });
  prevOrb.setState('thinking');
  cycleStates(prevOrb);
}

function cycleStates(orb) {
  const seq = ['idle', 'listening', 'thinking', 'reasoning', 'working', 'speaking'];
  let i = 0;
  setInterval(() => { orb.setState(seq[i++ % seq.length]); }, 2600);
}

function buildLook() {
  $('themes').innerHTML = Object.entries(THEMES).map(([id, t]) =>
    `<div class="sw ${id === state.theme ? 'sel' : ''}" data-theme="${id}" title="${t.name} — ${t.tag}"
      style="background:radial-gradient(circle at 34% 30%, ${t.accent}, ${t.glow[0]} 58%, ${t.bg})"></div>`
  ).join('');

  $('variants').innerHTML = Object.entries(ORB_VARIANTS).map(([id, v]) =>
    `<div class="vr ${id === state.variant ? 'sel' : ''}" data-variant="${id}" title="${v.tag}">${v.name}</div>`
  ).join('');

  $('themes').addEventListener('click', (e) => {
    const el = e.target.closest('.sw'); if (!el) return;
    state.theme = el.dataset.theme;
    document.querySelectorAll('.sw').forEach((x) => x.classList.toggle('sel', x === el));
    const t = applyTheme(state.theme);
    if (atmosphere) atmosphere.setTheme(t);
    [heroOrb, prevOrb].forEach((o) => o && o.setColors && o.setColors(t.colors));
  });

  $('variants').addEventListener('click', (e) => {
    const el = e.target.closest('.vr'); if (!el) return;
    state.variant = el.dataset.variant;
    document.querySelectorAll('.vr').forEach((x) => x.classList.toggle('sel', x === el));
    if (prevOrb) prevOrb.setVariant(state.variant);
    if (heroOrb) heroOrb.setVariant(state.variant);
  });

  const sync = () => {
    state.speed = parseFloat($('o-speed').value);
    state.density = parseInt($('o-density').value, 10);
    $('o-speed-v').textContent = state.speed === 0
      ? 'frozen' : `~${Math.round(40 / state.speed)}s / turn`;
    $('o-density-v').textContent = `${state.density} points`;
    if (prevOrb) { prevOrb.setSpeed(state.speed); prevOrb.setDensity(state.density); }
  };
  $('o-speed').addEventListener('input', sync);
  $('o-density').addEventListener('input', sync);
  sync();
}

/* ── step 7: deploy ─────────────────────────────────────────────────── */

function renderSummary() {
  const brain = {
    local: `RegesCore 1.0 35B · ${state.quant || 'no file chosen'}`,
    api: `${$('api-provider').value || 'API provider'}`,
    existing: `${$('ex-model').value || 'existing server'} @ ${$('ex-url').value}`,
  }[state.brain];

  const rows = [
    ['Reges', state.dirs.app],
    ['Vault', state.dirs.vault],
    ['Models', state.dirs.models],
    ['Brain', brain],
    ['Voice', state.voice === 'on' ? `on — ${state.lang}` : 'typing only'],
    ['Look', `${THEMES[state.theme].name} · ${ORB_VARIANTS[state.variant].name}`],
  ];
  $('summary').innerHTML = rows.map(([k, v]) =>
    `<div class="sum"><b>${k}</b><span>${v}</span></div>`).join('');
}

function taskEl(id, label) {
  let el = document.querySelector(`.task[data-id="${id}"]`);
  if (!el) {
    el = document.createElement('div');
    el.className = 'task run';
    el.dataset.id = id;
    el.innerHTML = `<div class="top"><span>${label}</span><b>0%</b></div>
                    <div class="det"></div><div class="bar"><i></i></div>`;
    $('tasks').appendChild(el);
  }
  return el;
}

function setTask(id, label, { pct = 0, detail = '', state: st = 'run' } = {}) {
  const el = taskEl(id, label);
  el.className = `task ${st}`;
  el.querySelector('b').textContent = `${Math.round(pct)}%`;
  el.querySelector('.det').textContent = detail;
  el.querySelector('.bar i').style.width = `${pct}%`;
}

async function watchJob(jobId, id, label) {
  return new Promise((resolve) => {
    const tick = async () => {
      const j = await api(`/api/setup/job/${jobId}`);
      setTask(id, label, {
        pct: j.pct || 0, detail: j.detail || '',
        state: j.state === 'done' ? 'done' : (j.state === 'failed' ? 'fail' : 'run'),
      });
      if (j.state === 'running') return setTimeout(tick, 700);
      if (j.state === 'failed') setTask(id, label, { pct: 100, detail: j.error, state: 'fail' });
      resolve(j);
    };
    tick();
  });
}

$('deploy').addEventListener('click', async () => {
  const btn = $('deploy');
  btn.disabled = true;
  btn.textContent = 'Deploying…';
  $('tasks').innerHTML = '';

  // 1. folders
  setTask('dirs', 'Creating folders', { pct: 20 });
  const f = await api('/api/setup/folders', state.dirs);
  setTask('dirs', 'Creating folders', {
    pct: 100, state: f.ok ? 'done' : 'fail',
    detail: f.ok ? `${f.created.length} created · ${f.disk.free_gb} GB free` : f.error,
  });

  // 2. python packages
  const pkgs = [];
  if (state.voice === 'on') pkgs.push('faster-whisper');
  if (state.voice === 'on' && state.preflight?.gpu?.vram_gb)
    pkgs.push('nvidia-cublas-cu12', 'nvidia-cudnn-cu12');
  if (pkgs.length) {
    const r = await api('/api/setup/install', { packages: pkgs });
    if (r.ok) await watchJob(r.job, 'pip', `Installing ${pkgs.join(', ')}`);
    else setTask('pip', 'Installing packages', { pct: 100, state: 'fail', detail: r.error });
  }

  // 3. model download
  if (state.brain === 'local' && state.quant) {
    const r = await api('/api/setup/download', { file: state.quant, dest: state.dirs.models });
    if (r.already) {
      setTask('dl', 'Model already on disk', { pct: 100, state: 'done', detail: r.path });
    } else if (r.ok) {
      await watchJob(r.job, 'dl', `Downloading ${state.quant}`);
    } else {
      setTask('dl', 'Downloading model', { pct: 100, state: 'fail', detail: r.error });
    }
  }

  // 4. write config
  setTask('cfg', 'Writing configuration', { pct: 45 });
  const model = {};
  if (state.brain === 'existing') {
    model.local_base_url = $('ex-url').value;
    model.local_model = $('ex-model').value;
    model.router_tier = 'local'; model.reasoning_tier = 'local';
  } else if (state.brain === 'api') {
    model.remote_enabled = true;
    model.router_tier = 'local'; model.reasoning_tier = 'remote';
  } else {
    model.local_base_url = 'http://127.0.0.1:1234/v1';
    model.local_model = state.quant.replace(/\.gguf$/, '');
    model.router_tier = 'local'; model.reasoning_tier = 'local';
  }

  const fin = await api('/api/setup/finish', {
    paths: state.dirs,
    model,
    api_key: state.brain === 'api' ? $('api-key').value : '',
    api_key_provider: state.brain === 'api' ? $('api-provider').value : '',
    voice: { enabled: state.voice === 'on', stt_language: state.lang },
    appearance: {
      theme: state.theme, orb_variant: state.variant,
      orb_speed: state.speed, orb_density: state.density,
    },
  });
  setTask('cfg', 'Writing configuration', {
    pct: 100, state: fin.ok ? 'done' : 'fail',
    detail: fin.ok ? fin.saved_to : fin.error,
  });

  if (!fin.ok) { btn.disabled = false; btn.textContent = 'Try again'; return; }

  // 5. alive
  const alive = document.createElement('div');
  alive.className = 'alive on';
  alive.innerHTML = `<h1><em>Reges is</em> <strong>awake.</strong></h1>
    <p class="lede" style="text-align:center">Taking you to the console…</p>`;
  document.body.appendChild(alive);
  setTimeout(() => { window.location.href = '/'; }, 2200);
});

/* ── boot ───────────────────────────────────────────────────────────── */

(async function boot() {
  const t = applyTheme(state.theme);
  atmosphere = mountAtmosphere(t);

  heroOrb = new Orb($('hero-orb'), { count: 1100, speed: 1, variant: 'lattice' });
  heroOrb.setState('reasoning');
  cycleStates(heroOrb);

  buildLook();
  await Promise.all([loadPreflight(), loadDirs(), loadProviders()]);
  document.querySelector('[data-brain="existing"]').click();
  document.querySelector('[data-voice="off"]').click();
  go(1);
})();
