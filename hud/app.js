/* HUD controller.
 *
 * One SSE connection carries the whole agent snapshot. Every frame is complete,
 * so a reconnect mid-task renders correctly from the first message -- there is
 * no replay protocol and no client-side state to get out of sync.
 */

import { Orb } from './orb.js';

const $ = (id) => document.getElementById(id);

const FALLBACK_COLORS = {
  idle: '#2f6f7a', listening: '#dfe9ee', thinking: '#7c5cff',
  reasoning: '#ffab3d', working: '#3ddc84', speaking: '#3d9bff', error: '#ff4d4d',
};

let cfg = { colors: FALLBACK_COLORS, orb_density: 900, orb_speed: 1, reduce_motion: false, ptt: 'ctrl+alt+space' };
let orb = null;
let lastState = null;

/* ── boot ─────────────────────────────────────────────────────────────── */

async function boot() {
  try {
    const r = await fetch('/api/appearance');
    if (r.ok) cfg = { ...cfg, ...(await r.json()) };
  } catch { /* server not up yet — fall back to defaults, don't blank the screen */ }

  orb = new Orb($('orb'), { count: cfg.orb_density, reduceMotion: cfg.reduce_motion, speed: cfg.orb_speed });
  window.REGES = window.REGES || {};
  window.REGES.orb = orb;
  window.REGES.setLevel = (v) => orb.setLevel(v);
  applyState('idle');
  $('ptt-hint').textContent = cfg.ptt;

  buildDeck();
  loadSchedule();
  tickClock();
  setInterval(tickClock, 1000);
  connect();
  wireIntent();
}

/* ── state → palette ──────────────────────────────────────────────────── */

function applyState(name) {
  if (name === lastState) return;
  lastState = name;
  const hex = cfg.colors[name] || FALLBACK_COLORS[name] || FALLBACK_COLORS.idle;
  document.documentElement.style.setProperty('--accent', hex);
  document.documentElement.style.setProperty('--accent-ink', tint(hex, 0.45));
  $('state-name').textContent = name;
  $('deck-status').textContent = name;
  orb.setState(name);
  orb.setColor(hex);
}

/* Lighten toward white so the same hue works as both glow and readable text. */
function tint(hex, amt) {
  const h = hex.replace('#', '');
  const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return '#' + c.map((v) => Math.round(v + (255 - v) * amt).toString(16).padStart(2, '0')).join('');
}

/* ── SSE ──────────────────────────────────────────────────────────────── */

function connect() {
  const es = new EventSource('/stream');

  es.onopen = () => setPip('pip-link', true);
  es.onerror = () => {
    setPip('pip-link', false);
    setPip('pip-core', false);
    // EventSource retries on its own; don't stack reconnect logic on top of it.
  };
  es.onmessage = (ev) => {
    let snap;
    try { snap = JSON.parse(ev.data); } catch { return; }
    render(snap);
  };
}

function render(s) {
  setPip('pip-core', true);
  applyState(s.state);
  orb.setLevel(s.level || 0);

  $('state-label').textContent = s.label || '';
  $('uptime').textContent = fmtUptime(s.uptime_s || 0);

  if (s.tokens) renderGauge(s.tokens);
  if (s.activity) renderLog(s.activity);
  if (s.vitals) renderVitals(s.vitals);
  if (s.caps) {
    setPip('pip-voice', !!s.caps.voice);
    setPip('pip-vault', !!s.caps.vault);
  }
}

function setPip(id, on) { $(id)?.classList.toggle('on', !!on); }

function fmtUptime(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

/* ── token gauge ──────────────────────────────────────────────────────── */

function renderGauge(t) {
  // t.total is BILLABLE (cloud) tokens only. Local runs on your own hardware
  // and has no per-token bill, so it is counted separately and never priced.
  const local = t.local_total || 0;
  $('tok-count').textContent = t.total.toLocaleString();
  const el = $('tok-local');
  if (el) el.textContent = local ? `  +${local.toLocaleString()} local · free` : '';
  $('tok-pct').textContent = `${t.pct}%`;
  $('tok-cost').textContent = t.usd > 0 ? `$${t.usd.toFixed(4)}` : '$0.0000';
  $('gauge-fill').style.width = Math.min(100, t.pct) + '%';
  const g = $('gauge');
  g.classList.toggle('warn', t.pct >= 80 && t.pct < 100);
  g.classList.toggle('over', t.pct >= 100);
}

/* ── activity log ─────────────────────────────────────────────────────── */

const GLYPH = { tokens: '⧗', warn: '!', error: '✗', skill: '▸', vault: '▪', router: '⌁' };
let lastLogTs = 0;

function renderLog(rows) {
  const fresh = rows.filter((r) => r.t > lastLogTs);
  if (!fresh.length) return;
  lastLogTs = rows[rows.length - 1].t;

  const el = $('log');
  for (const r of fresh) {
    const div = document.createElement('div');
    div.className = 'log-row' + (r.kind === 'warn' ? ' warn' : r.kind === 'error' ? ' error' : '');
    div.innerHTML =
      `<time>${new Date(r.t * 1000).toTimeString().slice(0, 8)}</time>` +
      `<i>${GLYPH[r.kind] || '·'}</i><span></span>`;
    div.lastChild.textContent = r.msg;   // textContent, not innerHTML — log lines are untrusted
    el.prepend(div);
  }
  while (el.children.length > 60) el.lastChild.remove();
}

/* ── vitals ───────────────────────────────────────────────────────────── */

function renderVitals(vitals) {
  const el = $('vitals');
  el.innerHTML = '';
  for (const v of vitals) {
    const wrap = document.createElement('div');
    wrap.className = 'vital';

    const head = document.createElement('div');
    head.className = 'vital-head';
    const name = document.createElement('span');
    name.textContent = v.label;
    const delta = document.createElement('b');
    delta.textContent = v.delta || '';
    head.append(name, delta);

    const val = document.createElement('div');
    val.className = 'vital-val';
    val.textContent = v.value;

    wrap.append(head, val);
    if (v.series?.length > 1) wrap.append(sparkline(v.series));
    el.append(wrap);
  }
}

function sparkline(series) {
  const W = 240, H = 26, NS = 'http://www.w3.org/2000/svg';
  const min = Math.min(...series), max = Math.max(...series);
  const span = (max - min) || 1;
  const pts = series.map((v, i) => [
    i / (series.length - 1) * W,
    H - 2 - ((v - min) / span) * (H - 4),
  ]);

  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'spark');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'none');

  const path = document.createElementNS(NS, 'path');
  path.setAttribute('d', 'M' + pts.map((p) => p.map((n) => n.toFixed(1)).join(' ')).join(' L'));
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', 'var(--accent)');
  path.setAttribute('stroke-width', '1');
  path.setAttribute('vector-effect', 'non-scaling-stroke');

  const dot = document.createElementNS(NS, 'circle');
  dot.setAttribute('cx', pts.at(-1)[0]);
  dot.setAttribute('cy', pts.at(-1)[1]);
  dot.setAttribute('r', '1.6');
  dot.setAttribute('fill', 'var(--accent)');

  svg.append(path, dot);
  return svg;
}

/* ── command deck ─────────────────────────────────────────────────────── */

async function buildDeck() {
  let cmds = [];
  try {
    const r = await fetch('/api/commands');
    if (r.ok) cmds = await r.json();
  } catch { /* offline — deck stays empty rather than showing fake buttons */ }

  const el = $('deck');
  el.innerHTML = '';
  for (const c of cmds) {
    const b = document.createElement('button');
    b.className = 'cmd';
    b.textContent = c.label;
    b.title = c.description || '';
    b.onclick = () => send(c.intent);
    el.append(b);
  }
}

async function loadSchedule() {
  let slots = [];
  try {
    const r = await fetch('/api/today');
    if (r.ok) slots = await r.json();
  } catch { /* leave empty */ }

  $('today-date').textContent = new Date().toLocaleDateString(undefined,
    { month: 'short', day: 'numeric' });

  const el = $('schedule');
  el.innerHTML = '';
  for (const s of slots) {
    const row = document.createElement('div');
    row.className = 'slot' + (s.now ? ' now' : s.done ? ' done' : '');
    const t = document.createElement('time');
    t.textContent = s.time || '';
    const txt = document.createElement('div');
    txt.textContent = s.text;
    row.append(t, txt);
    el.append(row);
  }
}

/* ── intent ───────────────────────────────────────────────────────────── */

function wireIntent() {
  const input = $('intent');
  input.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || !input.value.trim()) return;
    send(input.value.trim());
    input.value = '';
  });
  // Any keystroke that isn't already in a field focuses the intent line.
  document.addEventListener('keydown', (e) => {
    if (e.target === input || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key.length === 1) input.focus();
  });
}

async function send(text) {
  try {
    await fetch('/api/intent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
  } catch {
    applyState('error');
  }
}

/* ── clock ────────────────────────────────────────────────────────────── */

function tickClock() {
  const d = new Date();
  $('clock').firstChild.nodeValue =
    `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  $('secs').textContent = ':' + String(d.getSeconds()).padStart(2, '0');
}

boot();
