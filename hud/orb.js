/* The neural orb.
 *
 * A rotating sphere of particles projected to 2D. Each agent state gets its own
 * MOTION SIGNATURE, not just its own colour -- motion reads faster than hue at a
 * glance, which is the whole point of a HUD you glance at.
 *
 * Signatures:
 *   idle       slow drift, low opacity, wide
 *   listening  particles pull inward, radius pulses to mic RMS
 *   thinking   fast orbital churn, high link density
 *   reasoning  slow breathe -- expansion and contraction at wide radius
 *   working    tight lattice rotation with trailing streaks
 *   speaking   radius modulated by output level, forward bias
 *   error      jitter, links decay, particles fall
 */

const STATES = {
  // spin is radians per millisecond. 0.00016 ~= one revolution every 40s.
  // Anything above ~0.0006 reads as "spinning" rather than "alive" at idle.
  idle:      { spin: 0.00016, radius: 1.00, jitter: 0.06, links: 0.20, alpha: 0.55, breathe: 0.030, breatheHz: 0.18, streak: 0 },
  listening: { spin: 0.00035, radius: 0.86, jitter: 0.10, links: 0.34, alpha: 0.85, breathe: 0.020, breatheHz: 0.90, streak: 0 },
  thinking:  { spin: 0.00110, radius: 0.97, jitter: 0.42, links: 0.62, alpha: 0.92, breathe: 0.045, breatheHz: 1.30, streak: 0.10 },
  reasoning: { spin: 0.00045, radius: 1.10, jitter: 0.18, links: 0.46, alpha: 0.95, breathe: 0.150, breatheHz: 0.26, streak: 0 },
  working:   { spin: 0.00090, radius: 0.93, jitter: 0.08, links: 0.78, alpha: 1.00, breathe: 0.014, breatheHz: 2.20, streak: 0.34 },
  speaking:  { spin: 0.00050, radius: 1.02, jitter: 0.14, links: 0.40, alpha: 1.00, breathe: 0.090, breatheHz: 0.00, streak: 0 },
  error:     { spin: 0.00020, radius: 0.90, jitter: 1.60, links: 0.06, alpha: 0.70, breathe: 0.020, breatheHz: 3.60, streak: 0 },
};

function lerp(a, b, t) { return a + (b - a) * t; }

function hexToRgb(hex) {
  const h = (hex || '#2f6f7a').replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

export class Orb {
  constructor(canvas, opts = {}) {
    this.cv = canvas;
    this.ctx = canvas.getContext('2d', { alpha: true });
    this.count = opts.count || 900;
    this.reduceMotion = !!opts.reduceMotion;
    // 0 = frozen, 1 = default, 2 = double. Set from settings.
    this.speed = (opts.speed === undefined || opts.speed === null)
      ? 1 : Math.max(0, Math.min(3, Number(opts.speed) || 0));

    this.state = 'idle';
    this.level = 0;            // 0..1 audio RMS
    this.rgb = [47, 111, 122];
    this.targetRgb = [47, 111, 122];

    // Current (eased) signature. Easing between signatures is what makes state
    // changes feel like the same object changing mood rather than a hard cut.
    this.sig = { ...STATES.idle };
    this.target = { ...STATES.idle };

    this.rotY = 0;
    this.rotX = 0.32;
    this.t = 0;

    this._build();
    this._resize();
    window.addEventListener('resize', () => this._resize());
    this._raf = requestAnimationFrame((ts) => this._loop(ts));
  }

  /* Fibonacci sphere: even distribution without the polar clustering you get
     from naive random spherical coords. */
  _build() {
    this.pts = [];
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < this.count; i++) {
      const y = 1 - (i / (this.count - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const th = golden * i;
      this.pts.push({
        x: Math.cos(th) * r, y, z: Math.sin(th) * r,
        seed: Math.random() * Math.PI * 2,
        drift: 0.6 + Math.random() * 0.8,
        px: 0, py: 0, pd: 0,
      });
    }
  }

  _resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const box = this.cv.parentElement.getBoundingClientRect();
    const size = Math.max(220, Math.min(box.width * 0.86, box.height * 0.68, 620));
    this.cv.style.width = size + 'px';
    this.cv.style.height = size + 'px';
    this.cv.width = Math.round(size * dpr);
    this.cv.height = Math.round(size * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.size = size;
    this.R = size * 0.34;
  }

  setState(name) {
    if (!STATES[name]) name = 'idle';
    this.state = name;
    this.target = { ...STATES[name] };
  }

  setColor(hex) { this.targetRgb = hexToRgb(hex); }
  setLevel(v) { this.level = Math.max(0, Math.min(1, v || 0)); }

  setSpeed(v) { this.speed = Math.max(0, Math.min(3, Number(v) || 0)); }
  setDensity(n) { this.count = Math.max(120, Math.min(4000, n | 0)); this._build(); }

  _loop(ts) {
    const dt = Math.min(48, ts - (this._last || ts));
    this._last = ts;
    this.t += dt;

    // Ease signature + colour toward target.
    const k = this.reduceMotion ? 1 : 0.055;
    for (const key in this.target) this.sig[key] = lerp(this.sig[key], this.target[key], k);
    for (let i = 0; i < 3; i++) this.rgb[i] = lerp(this.rgb[i], this.targetRgb[i], 0.05);

    this._draw(dt);
    this._raf = requestAnimationFrame((t) => this._loop(t));
  }

  _draw(dt) {
    const ctx = this.ctx, S = this.size, C = S / 2, s = this.sig;
    ctx.clearRect(0, 0, S, S);

    if (!this.reduceMotion) {
      this.rotY += s.spin * dt * this.speed;
      this.rotX += s.spin * 0.22 * dt * this.speed;
    }

    // Radius: base signature + breathe + audio level where the state uses it.
    let breathe = Math.sin(this.t / 1000 * s.breatheHz * Math.PI * 2) * s.breathe;
    if (this.state === 'speaking' || this.state === 'listening') {
      breathe += this.level * 0.22;
    }
    const R = this.R * (s.radius + breathe);

    const [cr, cg, cb] = this.rgb.map(Math.round);
    const cosY = Math.cos(this.rotY), sinY = Math.sin(this.rotY);
    const cosX = Math.cos(this.rotX), sinX = Math.sin(this.rotX);

    // Core glow -- gives the sphere a light source rather than a flat point cloud.
    const glow = ctx.createRadialGradient(C, C, 0, C, C, R * 1.5);
    glow.addColorStop(0, `rgba(${cr},${cg},${cb},${0.30 * s.alpha})`);
    glow.addColorStop(0.45, `rgba(${cr},${cg},${cb},${0.07 * s.alpha})`);
    glow.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = glow;
    ctx.beginPath(); ctx.arc(C, C, R * 1.5, 0, Math.PI * 2); ctx.fill();

    // Project.
    const jitterAmp = s.jitter * (this.reduceMotion ? 0 : 1);
    for (const p of this.pts) {
      const wob = Math.sin(this.t / 900 * p.drift + p.seed) * 0.02 * (1 + jitterAmp * 6);
      const rr = 1 + wob;
      let x = p.x * rr, y = p.y * rr, z = p.z * rr;

      let x1 = x * cosY - z * sinY;
      let z1 = x * sinY + z * cosY;
      let y1 = y * cosX - z1 * sinX;
      let z2 = y * sinX + z1 * cosX;

      // Perspective: far side smaller and dimmer, so the sphere reads as a solid.
      const depth = (z2 + 1.6) / 2.6;
      const scale = 0.62 + depth * 0.55;
      p.px = C + x1 * R * scale;
      p.py = C + y1 * R * scale;
      p.pd = depth;
    }

    // Links between near neighbours on the front hemisphere only. Sampled, not
    // exhaustive -- an O(n^2) pass at 900 points would cost more than the
    // information it adds.
    if (s.links > 0.03) {
      ctx.lineWidth = 0.5;
      const step = Math.max(1, Math.floor(this.pts.length / 260));
      const maxD = R * 0.20;
      for (let i = 0; i < this.pts.length; i += step) {
        const a = this.pts[i];
        if (a.pd < 0.5) continue;
        for (let j = i + step; j < Math.min(i + step * 7, this.pts.length); j += step) {
          const b = this.pts[j];
          if (b.pd < 0.5) continue;
          const dx = a.px - b.px, dy = a.py - b.py;
          const d = Math.hypot(dx, dy);
          if (d > maxD) continue;
          const al = (1 - d / maxD) * s.links * s.alpha * 0.5;
          ctx.strokeStyle = `rgba(${cr},${cg},${cb},${al})`;
          ctx.beginPath(); ctx.moveTo(a.px, a.py); ctx.lineTo(b.px, b.py); ctx.stroke();
        }
      }
    }

    // Particles.
    for (const p of this.pts) {
      const a = (0.15 + p.pd * 0.85) * s.alpha;
      const rad = 0.55 + p.pd * 1.5;

      if (s.streak > 0.02 && p.pd > 0.6) {
        ctx.strokeStyle = `rgba(${cr},${cg},${cb},${a * 0.45})`;
        ctx.lineWidth = rad * 0.7;
        ctx.beginPath();
        ctx.moveTo(p.px, p.py);
        ctx.lineTo(p.px - (p.px - C) * s.streak * 0.10, p.py - (p.py - C) * s.streak * 0.10);
        ctx.stroke();
      }

      ctx.fillStyle = p.pd > 0.88
        ? `rgba(255,255,255,${a * 0.85})`   // specular highlight on the nearest points
        : `rgba(${cr},${cg},${cb},${a})`;
      ctx.beginPath(); ctx.arc(p.px, p.py, rad, 0, Math.PI * 2); ctx.fill();
    }

    // Listening ring: a physical readout of mic level, drawn outside the sphere.
    if (this.state === 'listening' && this.level > 0.01) {
      ctx.strokeStyle = `rgba(${cr},${cg},${cb},${0.30 + this.level * 0.5})`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(C, C, R * (1.32 + this.level * 0.30), 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  destroy() { cancelAnimationFrame(this._raf); }
}
