/* Reges atmosphere.
 *
 * A flat panel reads as a form. Depth reads as a machine you are standing
 * inside. This paints three slow-drifting light fields at quarter resolution
 * and scales them up — the blur is free, the cost is negligible, and the room
 * never sits still.
 *
 * Canvas, not WebGL: it has to run on an integrated chip while a 35B model is
 * eating the GPU next door.
 */

export class Atmosphere {
  constructor(canvas, opts = {}) {
    this.cv = canvas;
    this.ctx = canvas.getContext('2d');
    this.scale = 0.22;                       // render small, upscale, get blur free
    this.reduceMotion = !!opts.reduceMotion;
    this.intensity = opts.intensity ?? 1;
    this.t = 0;
    this.px = 0; this.py = 0;                // parallax target
    this.cx = 0; this.cy = 0;                // parallax current
    this.setTheme(opts.theme);

    this.fields = [
      { r: 0.62, sx: 0.00007, sy: 0.00005, ox: 0.32, oy: 0.38, a: 0.85, par: 26 },
      { r: 0.48, sx: -0.00005, sy: 0.00009, ox: 0.68, oy: 0.30, a: 0.62, par: 16 },
      { r: 0.80, sx: 0.00003, sy: -0.00004, ox: 0.50, oy: 0.78, a: 0.45, par: 9 },
    ];

    this._resize = () => this.resize();
    window.addEventListener('resize', this._resize);
    window.addEventListener('pointermove', (e) => {
      this.px = (e.clientX / window.innerWidth - 0.5) * 2;
      this.py = (e.clientY / window.innerHeight - 0.5) * 2;
    }, { passive: true });

    this.resize();
    this.grain = this.makeGrain();
    this.raf = requestAnimationFrame((ts) => this.loop(ts));
  }

  setTheme(t) {
    this.theme = t || { glow: ['#0d3b44', '#071b22'], accent: '#3fa8bd', grain: 0.035 };
  }

  resize() {
    const w = Math.max(1, Math.floor(window.innerWidth * this.scale));
    const h = Math.max(1, Math.floor(window.innerHeight * this.scale));
    this.cv.width = w; this.cv.height = h;
    this.cv.style.width = '100%';
    this.cv.style.height = '100%';
  }

  makeGrain() {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const g = c.getContext('2d');
    const img = g.createImageData(128, 128);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = 120 + Math.random() * 135;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
    g.putImageData(img, 0, 0);
    return c;
  }

  loop(ts) {
    const dt = Math.min(64, ts - (this._last || ts));
    this._last = ts;
    if (!this.reduceMotion) this.t += dt;

    // ease parallax so the room feels heavy, not twitchy
    this.cx += (this.px - this.cx) * 0.03;
    this.cy += (this.py - this.cy) * 0.03;

    this.draw();
    this.raf = requestAnimationFrame((t) => this.loop(t));
  }

  draw() {
    const { ctx, cv } = this;
    const w = cv.width, h = cv.height;
    const [g1, g2] = this.theme.glow || ['#0d3b44', '#071b22'];

    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = this.theme.bg || '#05080b';
    ctx.fillRect(0, 0, w, h);

    ctx.globalCompositeOperation = 'lighter';
    const cols = [g1, g2, this.theme.accent || '#3fa8bd'];

    this.fields.forEach((f, i) => {
      const drift = this.reduceMotion ? 0 : this.t;
      const x = (f.ox + Math.sin(drift * f.sx + i * 2.1) * 0.16) * w
              - this.cx * f.par * this.scale;
      const y = (f.oy + Math.cos(drift * f.sy + i * 1.4) * 0.13) * h
              - this.cy * f.par * this.scale;
      const rad = f.r * Math.max(w, h) * (0.9 + Math.sin(drift * 0.00004 + i) * 0.1);

      const grd = ctx.createRadialGradient(x, y, 0, x, y, rad);
      const c = cols[i % cols.length];
      grd.addColorStop(0, hexA(c, f.a * 0.55 * this.intensity));
      grd.addColorStop(0.45, hexA(c, f.a * 0.16 * this.intensity));
      grd.addColorStop(1, hexA(c, 0));
      ctx.fillStyle = grd;
      ctx.beginPath();
      ctx.arc(x, y, rad, 0, Math.PI * 2);
      ctx.fill();
    });

    // vignette pulls the eye to the centre where the orb lives
    ctx.globalCompositeOperation = 'multiply';
    const vg = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.72);
    vg.addColorStop(0, 'rgba(255,255,255,1)');
    vg.addColorStop(1, 'rgba(0,0,0,0.55)');
    ctx.fillStyle = vg;
    ctx.fillRect(0, 0, w, h);
    ctx.globalCompositeOperation = 'source-over';
  }

  destroy() {
    cancelAnimationFrame(this.raf);
    window.removeEventListener('resize', this._resize);
  }
}

function hexA(hex, a) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

export function mountAtmosphere(theme, opts = {}) {
  let cv = document.getElementById('atmosphere');
  if (!cv) {
    cv = document.createElement('canvas');
    cv.id = 'atmosphere';
    Object.assign(cv.style, {
      position: 'fixed', inset: '0', width: '100%', height: '100%',
      zIndex: '0', pointerEvents: 'none',
    });
    document.body.prepend(cv);
  }
  return new Atmosphere(cv, { theme, ...opts });
}
