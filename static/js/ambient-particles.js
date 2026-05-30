/**
 * Agri-Vision Ambient Particle Background
 * -----------------------------------------
 * Production-grade, SSR-safe, accessibility-friendly canvas particle layer.
 * - Decorative only (aria-hidden)
 * - Respects prefers-reduced-motion
 * - Performance-aware: capped particle count, pauses on hidden tab
 * - Theme-aware: reads CSS variables (emerald green / ai blue)
 */
(function () {
  'use strict';

  /**
   * Seeded RNG (Mulberry32)
   * Deterministic across SSR/client to avoid “random first paint” differences.
   */
  function mulberry32(seed) {
    let t = seed >>> 0;
    return function () {
      t += 0x6D2B79F5;
      let r = Math.imul(t ^ (t >>> 15), 1 | t);
      r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }

  function clamp(n, min, max) {
    return Math.max(min, Math.min(max, n));
  }

  function prefersReducedMotion() {
    return (
      typeof window !== 'undefined' &&
      window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    );
  }

  function getCssVar(name) {
    try {
      const v = getComputedStyle(document.documentElement).getPropertyValue(name);
      return (v || '').trim();
    } catch {
      return '';
    }
  }

  function parseCssColorToRgba(color, fallback) {
    // Accepts hex (#RRGGBB) only (repo uses hex variables).
    const hex = (color || '').toLowerCase();
    if (!hex) return fallback;
    if (hex.startsWith('#') && (hex.length === 7 || hex.length === 4)) {
      let r, g, b;
      if (hex.length === 7) {
        r = parseInt(hex.slice(1, 3), 16);
        g = parseInt(hex.slice(3, 5), 16);
        b = parseInt(hex.slice(5, 7), 16);
      } else {
        // #RGB
        r = parseInt(hex[1] + hex[1], 16);
        g = parseInt(hex[2] + hex[2], 16);
        b = parseInt(hex[3] + hex[3], 16);
      }
      return { r, g, b };
    }
    return fallback;
  }

  function seededFromString(str) {
    // Simple hash -> uint32
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  const DEFAULTS = {
    // Density is further scaled by breakpoint + device.
    baseCount: 240,
    dprMax: 2,

    // Motion ranges (calm/premium)
    // Speeds are small; movement is drift + gentle wobble.
    layers: [
      { countMul: 1.0, speed: 0.20, alpha: 0.08, radius: [0.6, 1.25] },
      { countMul: 0.55, speed: 0.28, alpha: 0.12, radius: [0.7, 1.6] },
      { countMul: 0.18, speed: 0.38, alpha: 0.16, radius: [1.0, 2.2] },
    ],

    // Avoid distracting brightness
    glowChance: 0.03,
    glowAlphaMul: 0.55,

    // Update throttling
    maxFpsWhenVisible: 60,
  };

  function AmbientParticles(canvas, root) {
    this.canvas = canvas;
    this.root = root;
    this.ctx = null;

    this.running = false;
    this.rafId = 0;

    this.dpr = 1;
    this.w = 0;
    this.h = 0;

    this.particles = [];
    this.layers = DEFAULTS.layers;

    this.lastTs = 0;
    this.frameInterval = 1000 / DEFAULTS.maxFpsWhenVisible;

    this.pointerFine = false;
    this.pointer = { x: 0.5, y: 0.35 };

    this.seed = 0;
    this.rand = Math.random;

    this.colors = {
      // Fallbacks
      a: { r: 46, g: 139, b: 87 }, // emerald green
      b: { r: 74, g: 144, b: 226 }, // ai-blue
      c: { r: 100, g: 181, b: 246 },
    };
  }

  AmbientParticles.prototype.readTheme = function () {
    const emerald = getCssVar('--emerald-green');
    const aiBlue = getCssVar('--ai-blue');
    const freshGreen = getCssVar('--fresh-green');

    // We map multiple variables into 2–3 palette endpoints.
    this.colors.a = parseCssColorToRgba(emerald, this.colors.a);
    this.colors.b = parseCssColorToRgba(aiBlue, this.colors.b);

    const fresh = parseCssColorToRgba(freshGreen, this.colors.c);
    // Use fresh for accent.
    this.colors.c = fresh;
  };

  AmbientParticles.prototype.computeSeed = function () {
    const theme = (document.documentElement.getAttribute('data-theme') || 'light').toString();
    const device = (window.innerWidth || 0) + 'x' + (window.innerHeight || 0);
    this.seed = seededFromString('ambient-particles:' + theme + ':' + device);
    this.rand = mulberry32(this.seed);
  };

  AmbientParticles.prototype.pickColor = function (layerIndex) {
    // Layer 0/1 mostly emerald/ai, layer 2 slightly more accent.
    const r = this.rand();
    if (layerIndex === 2) {
      if (r < 0.55) return this.colors.c;
      if (r < 0.85) return this.colors.b;
      return this.colors.a;
    }

    if (r < 0.60) return this.colors.a;
    return this.colors.b;
  };

  AmbientParticles.prototype.resize = function () {
    const rect = this.root && this.root.getBoundingClientRect ? this.root.getBoundingClientRect() : null;
    const width = rect ? rect.width : this.canvas.parentElement ? this.canvas.parentElement.clientWidth : window.innerWidth;
    const height = rect ? rect.height : this.canvas.parentElement ? this.canvas.parentElement.clientHeight : window.innerHeight;

    if (!width || !height) return;

    this.dpr = clamp(window.devicePixelRatio || 1, 1, DEFAULTS.dprMax);
    this.w = Math.floor(width);
    this.h = Math.floor(height);

    const cw = Math.max(1, Math.floor(this.w * this.dpr));
    const ch = Math.max(1, Math.floor(this.h * this.dpr));

    // Avoid unnecessary reallocations.
    if (this.canvas.width !== cw || this.canvas.height !== ch) {
      this.canvas.width = cw;
      this.canvas.height = ch;
    }

    this.canvas.style.width = this.w + 'px';
    this.canvas.style.height = this.h + 'px';

    this.rebuildParticles();
  };

  AmbientParticles.prototype.breakpointScale = function () {
    const w = window.innerWidth || 0;
    if (w <= 420) return 0.35; // very small screens
    if (w <= 768) return 0.55; // mobile/tablet
    if (w <= 1024) return 0.75; // small desktop/tablet
    return 1.0;
  };

  AmbientParticles.prototype.rebuildParticles = function () {
    this.ctx = this.canvas.getContext && this.canvas.getContext('2d');
    if (!this.ctx) return;

    // Respect reduced motion: freeze by not animating (still draws once).
    // Particle creation is fine for “visual depth”.

    const scale = this.breakpointScale();
    const base = Math.floor(DEFAULTS.baseCount * scale);

    const total = this.layers.reduce((acc, l) => acc + Math.floor(base * l.countMul), 0);

    // Hard cap for perf.
    const maxTotal = Math.floor(420 * scale + 140); // conservative
    const count = Math.min(total, maxTotal);

    // Create per-layer particles with proportional allocation.
    this.particles = [];

    // Precompute alpha/size ranges.
    let allocated = 0;
    for (let layerIndex = 0; layerIndex < this.layers.length; layerIndex++) {
      const layer = this.layers[layerIndex];
      const layerCount = Math.floor((count * (layer.countMul / this.layers.reduce((a, b) => a + b.countMul, 0))));

      for (let i = 0; i < layerCount; i++) {
        const u = this.rand();
        const v = this.rand();

        const radius = layer.radius[0] + this.rand() * (layer.radius[1] - layer.radius[0]);

        // Depth effect: use small parallax offsets and opacity.
        const depth = layerIndex / (this.layers.length - 1);

        // Normalized position.
        const x = u * this.w;
        const y = v * this.h;

        // Gentle motion parameters.
        const phase = this.rand() * Math.PI * 2;
        const driftX = (this.rand() - 0.5) * (10 + depth * 18);
        const driftY = (this.rand() * 0.5 + 0.15) * (18 + depth * 22);

        // Slight velocity (scaled by layer speed)
        const speed = layer.speed * (0.8 + this.rand() * 0.7);

        const col = this.pickColor(layerIndex);

        const glow = this.rand() < DEFAULTS.glowChance && layerIndex > 0;
        this.particles.push({
          layerIndex,
          x,
          y,
          radius,
          alpha: layer.alpha * (0.7 + this.rand() * 0.8),
          speed,
          phase,
          driftX,
          driftY,
          depth,
          col,
          glow,
          glowStrength: glow ? (0.35 + this.rand() * 0.65) * DEFAULTS.glowAlphaMul : 0,
        });
        allocated++;
      }
    }
  };

  AmbientParticles.prototype.drawOnce = function (timeMs) {
    if (!this.ctx) return;

    const ctx = this.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);

    const cw = this.canvas.width;
    const ch = this.canvas.height;

    // Clear with transparency to avoid expensive full opaque paints.
    ctx.clearRect(0, 0, cw, ch);

    ctx.scale(this.dpr, this.dpr);

    const t = (timeMs || 0) * 0.001;

    // Slight vignette for depth (very subtle).
    // (Only drawn once per frame; but cheap enough for calm particle count.)
    // Commented out to minimize paint cost; keep particles only.

    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i];

      // Slow drift + organic wobble via sine.
      // Movement is deterministic with seed + phase.
      const wobble = Math.sin(t * p.speed + p.phase) * 0.5;

      // Wrap-around to avoid “restarts”.
      let x = p.x + wobble * p.driftX;
      let y = p.y + (t * p.driftY * 0.02);

      // Wrap in bounds with smoothness.
      if (y < -20) y = this.h + 20;
      if (y > this.h + 20) y = -20;
      if (x < -20) x = this.w + 20;
      if (x > this.w + 20) x = -20;

      // Soft glow only for rare particles.
      if (p.glow) {
        ctx.beginPath();
        ctx.fillStyle = 'rgba(' + p.col.r + ',' + p.col.g + ',' + p.col.b + ',' + (p.alpha * p.glowStrength) + ')';
        // Draw larger translucent circle.
        ctx.arc(x, y, p.radius * 2.3, 0, Math.PI * 2);
        ctx.fill();
      }

      // Core dot
      ctx.beginPath();
      ctx.fillStyle = 'rgba(' + p.col.r + ',' + p.col.g + ',' + p.col.b + ',' + p.alpha + ')';
      ctx.arc(x, y, p.radius, 0, Math.PI * 2);
      ctx.fill();
    }
  };

  AmbientParticles.prototype.tick = function (ts) {
    if (!this.running) return;

    const now = ts || performance.now();
    if (now - this.lastTs < this.frameInterval) {
      this.rafId = requestAnimationFrame(this.tick.bind(this));
      return;
    }

    this.lastTs = now;

    const reduced = prefersReducedMotion();
    if (reduced) {
      // Freeze: draw once and stop RAF.
      this.drawOnce(now);
      this.running = false;
      return;
    }

    this.drawOnce(now);

    this.rafId = requestAnimationFrame(this.tick.bind(this));
  };

  AmbientParticles.prototype.start = function () {
    if (this.running) return;

    this.readTheme();
    this.computeSeed();

    this.resize();

    this.running = true;
    this.lastTs = 0;
    this.rafId = requestAnimationFrame(this.tick.bind(this));
  };

  AmbientParticles.prototype.stop = function () {
    if (!this.running) {
      // still ensure no RAF leaks
      if (this.rafId) cancelAnimationFrame(this.rafId);
      this.running = false;
      return;
    }

    this.running = false;
    if (this.rafId) cancelAnimationFrame(this.rafId);
    this.rafId = 0;
  };

  function initAmbientParticles() {
    if (typeof window === 'undefined' || typeof document === 'undefined') return;

    const root = document.getElementById('ambient-particles-root');
    const canvas = document.getElementById('ambient-particles-canvas');
    if (!root || !canvas) return;

    // Respect OS reduced motion and also allow explicit opt-out.
    if (root.getAttribute('data-particles') === 'off') return;

    // If canvas is outside DOM or zero-size, bail.
    const rect = root.getBoundingClientRect();
    if (!rect.width || !rect.height) {
      // Still create, but delay until resize.
    }

    const system = new AmbientParticles(canvas, root);

    // Pause when hidden
    const onVis = function () {
      if (document.hidden) system.stop();
      else {
        // Re-start if reduced motion is NOT enabled.
        if (!prefersReducedMotion()) system.start();
        else system.drawOnce(performance.now());
      }
    };

    document.addEventListener('visibilitychange', onVis, { passive: true });

    // Resize with debounce (cheap & safe)
    let resizeT = 0;
    const onResize = function () {
      window.clearTimeout(resizeT);
      resizeT = window.setTimeout(function () {
        // Rebuild particles; but avoid restarting RAF if already frozen.
        if (prefersReducedMotion()) {
          system.drawOnce(performance.now());
        } else {
          // keep running; rebuild handled by resize
          system.resize();
        }
      }, 120);
    };
    window.addEventListener('resize', onResize, { passive: true });

    system.start();
  }

  if (typeof document !== 'undefined') {
    // DOMContentLoaded keeps it deterministic and SSR-safe (client only).
    document.addEventListener('DOMContentLoaded', initAmbientParticles, { passive: true });
  }
})();

