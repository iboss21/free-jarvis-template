/* Reges voice — push to talk, in the browser.
 *
 * The mic is already here. No sounddevice, no keyboard hook, no admin rights.
 *
 *   hold SPACE (or the mic button) -> MediaRecorder captures
 *   release                        -> POST to 127.0.0.1 -> local transcription
 *   transcript                     -> /api/ask -> the agent answers
 *   answer                         -> /api/voice/tts, or the browser speaks it
 *
 * Audio only ever travels to localhost. Nothing is uploaded anywhere.
 */
(function () {
  const PTT_KEY = 'Space';
  const MAX_MS = 30000;
  let media = null, recorder = null, chunks = [], holding = false, busy = false;
  let maxTimer = null;
  let caps = null, analyser = null, audioCtx = null, levelTimer = null;

  const el = {
    input: document.querySelector('#intent, #intent-input, input[type=text]'),
    orbLabel: document.querySelector('#orb-label, .orb-label'),
  };

  // ---------------------------------------------------------------- UI
  const bar = document.createElement('div');
  bar.id = 'voice-bar';
  bar.innerHTML = `
    <button id="voice-btn" title="hold to talk (or hold Space)">
      <span class="dot"></span><span class="lbl">HOLD TO TALK</span>
    </button>
    <span id="voice-status"></span>`;
  Object.assign(bar.style, {
    position: 'fixed', left: '50%', transform: 'translateX(-50%)',
    bottom: '14px', display: 'flex', alignItems: 'center', gap: '12px',
    zIndex: 60, fontSize: '10px', letterSpacing: '.18em',
  });
  document.body.appendChild(bar);

  const style = document.createElement('style');
  style.textContent = `
    #voice-btn{display:flex;align-items:center;gap:9px;background:#0b0f14;
      border:1px solid #1c2430;color:#8aa0b4;padding:7px 15px;border-radius:2px;
      font:inherit;font-size:10px;letter-spacing:.18em;cursor:pointer;
      transition:border-color .15s,color .15s}
    #voice-btn:hover{border-color:#2b6cb0;color:#cfe0ee}
    #voice-btn.live{border-color:#22d3ee;color:#22d3ee}
    #voice-btn.busy{border-color:#8b5cf6;color:#8b5cf6}
    #voice-btn.off{opacity:.4;cursor:not-allowed}
    #voice-btn .dot{width:6px;height:6px;border-radius:50%;background:currentColor;
      opacity:.45;transition:opacity .1s,transform .1s}
    #voice-btn.live .dot{opacity:1}
    #voice-status{opacity:.45;max-width:46vw;overflow:hidden;text-overflow:ellipsis;
      white-space:nowrap}`;
  document.head.appendChild(style);

  const btn = document.getElementById('voice-btn');
  const status = document.getElementById('voice-status');
  const dot = btn.querySelector('.dot');
  const lbl = btn.querySelector('.lbl');

  const say = (t) => { status.textContent = t || ''; };

  // ------------------------------------------------------------- caps
  async function loadCaps() {
    try {
      caps = await (await fetch('/api/voice/status')).json();
    } catch { caps = null; }
    if (!caps || !caps.can_listen) {
      btn.classList.add('off');
      lbl.textContent = 'VOICE OFF';
      say('no local speech engine — pip install faster-whisper');
      return false;
    }
    say(`ears: ${caps.stt_active} · mouth: ${caps.tts_active}`);
    return true;
  }

  // ------------------------------------------------------------- level
  function startLevel(stream) {
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const src = audioCtx.createMediaStreamSource(stream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);
      levelTimer = setInterval(() => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
        const rms = Math.sqrt(sum / buf.length);
        dot.style.transform = `scale(${1 + Math.min(rms * 9, 2.4)})`;
        if (window.REGES && window.REGES.setLevel) window.REGES.setLevel(rms);
      }, 60);
    } catch { /* level meter is cosmetic */ }
  }

  function stopLevel() {
    clearInterval(levelTimer); levelTimer = null;
    dot.style.transform = '';
    if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
  }

  // ------------------------------------------------------------ record
  async function begin() {
    if (holding || busy || !caps || !caps.can_listen) return;
    holding = true;
    btn.classList.add('live'); lbl.textContent = 'LISTENING'; say('');
    try {
      media = media || await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch (e) {
      holding = false; btn.classList.remove('live'); lbl.textContent = 'MIC BLOCKED';
      say('browser denied microphone access');
      return;
    }
    // getUserMedia is async. If the key came back up while we were waiting,
    // do not start a recorder nobody is going to stop.
    if (!holding) { reset(); return; }
    chunks = [];
    const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus' : '';
    recorder = new MediaRecorder(media, mime ? { mimeType: mime } : undefined);
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = send;
    recorder.start();
    startLevel(media);
    clearTimeout(maxTimer);
    maxTimer = setTimeout(() => { if (holding) { say('max 30s'); end(); } }, MAX_MS);
  }

  function reset() {
    holding = false;
    btn.classList.remove('live');
    if (!busy) lbl.textContent = 'HOLD TO TALK';
    stopLevel();
    clearTimeout(maxTimer);
  }

  function end() {
    if (!holding) { reset(); return; }
    reset();
    try {
      if (recorder && recorder.state !== 'inactive') recorder.stop();
    } catch (e) { /* already stopped */ }
  }

  // -------------------------------------------------------------- send
  async function send() {
    const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
    if (blob.size < 2000) { say('too short — hold longer'); lbl.textContent = 'HOLD TO TALK'; return; }

    busy = true; btn.classList.add('busy'); lbl.textContent = 'TRANSCRIBING';
    try {
      const r = await fetch('/api/voice/stt', {
        method: 'POST',
        headers: { 'Content-Type': blob.type || 'audio/webm' },
        body: blob,
      });
      const out = await r.json();
      if (!out.ok) { say(out.error || 'transcription failed'); return; }
      const text = (out.text || '').trim();
      if (!text) { say('heard nothing'); return; }

      say(`"${text}"  (${out.engine}, ${out.ms}ms)`);
      if (el.input) el.input.value = text;

      lbl.textContent = 'THINKING';
      const ask = await (await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })).json();

      const reply = (ask.reply || '').trim();
      if (reply) { say(reply.slice(0, 160)); await speak(reply); }
      else if (ask.error) say(ask.error);
    } catch (e) {
      say(String(e).slice(0, 140));
    } finally {
      busy = false; btn.classList.remove('busy'); lbl.textContent = 'HOLD TO TALK';
    }
  }

  // ------------------------------------------------------------- speak
  async function speak(text) {
    lbl.textContent = 'SPEAKING';
    try {
      const r = await fetch('/api/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      const ctype = r.headers.get('Content-Type') || '';
      if (ctype.startsWith('audio/')) {
        const url = URL.createObjectURL(await r.blob());
        await new Promise((res) => {
          const a = new Audio(url);
          a.onended = a.onerror = () => { URL.revokeObjectURL(url); res(); };
          a.play().catch(res);
        });
        return;
      }
      // Server has no voice — the browser does. Still local.
      await browserSpeak(text);
    } catch {
      await browserSpeak(text);
    }
  }

  function browserSpeak(text) {
    return new Promise((res) => {
      if (!window.speechSynthesis) return res();
      const u = new SpeechSynthesisUtterance(text.slice(0, 1200));
      u.rate = 1.05;
      u.onend = u.onerror = () => res();
      window.speechSynthesis.speak(u);
    });
  }

  // ------------------------------------------------------------ wiring
  btn.addEventListener('mousedown', begin);
  btn.addEventListener('touchstart', (e) => { e.preventDefault(); begin(); }, { passive: false });
  window.addEventListener('mouseup', end);
  window.addEventListener('touchend', end);

  function typing(e) {
    const t = e.target;
    return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
  }
  window.addEventListener('keydown', (e) => {
    if (e.code !== PTT_KEY || e.repeat || typing(e)) return;
    e.preventDefault();
    e.stopPropagation();   // capture phase — the HUD never sees this space
    // The HUD focuses the intent box on keypress. Take focus back or the
    // space lands in the input and keyup never reaches us.
    const a = document.activeElement;
    if (a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA')) a.blur();
    begin();
  }, true);

  window.addEventListener('keyup', (e) => {
    if (e.code !== PTT_KEY) return;
    // Once a hold is in progress, ALWAYS end it — never mind where focus
    // drifted to in between. A stuck-open mic is the worst failure here.
    if (holding) { e.preventDefault(); e.stopPropagation(); end(); return; }
    if (typing(e)) return;
    e.preventDefault(); end();
  }, true);

  // Any of these can strand an open mic. All of them close it.
  window.addEventListener('blur', end);
  document.addEventListener('visibilitychange', () => { if (document.hidden) end(); });

  loadCaps();
  window.REGES_VOICE = { begin, end, speak, caps: () => caps, reload: loadCaps };
})();
