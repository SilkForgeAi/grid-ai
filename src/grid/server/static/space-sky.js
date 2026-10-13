// A quiet deep-space backdrop for the particle screen: a faint galactic band, a few
// soft nebula glows and crisp stars. Drawn once per size (no animation, no GPU work),
// always the same sky (seeded), so it stays clean behind the moving particles.
const STAR_COLORS = [[232, 238, 252], [232, 238, 252], [232, 238, 252], [184, 207, 255], [255, 227, 196]];

function rng(seed) {
  let s = seed >>> 0;
  return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; };
}
function gauss(random) { return (random() + random() + random() + random() - 2) / 2; }

export function paintSky(canvas, width, height, pixel = 1) {
  const ctx = canvas.getContext?.('2d');
  if (!ctx || width < 2 || height < 2) return 0;
  canvas.width = Math.round(width * pixel); canvas.height = Math.round(height * pixel);
  ctx.setTransform(pixel, 0, 0, pixel, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const random = rng(20261012);
  const diag = Math.hypot(width, height);

  // Soft nebula light: deep indigo, a cold teal, a whisper of violet.
  for (const [x, y, r, rgb, a] of [[.78, .22, .55, '58,46,128', .16], [.16, .82, .5, '20,86,110', .12], [.55, .6, .35, '96,40,92', .07]]) {
    const g = ctx.createRadialGradient(x * width, y * height, 0, x * width, y * height, r * diag);
    g.addColorStop(0, `rgba(${rgb},${a})`); g.addColorStop(1, `rgba(${rgb},0)`);
    ctx.fillStyle = g; ctx.fillRect(0, 0, width, height);
  }

  // A faint galactic band running corner to corner.
  const angle = -0.42, cx = width * .5, cy = height * .5, nx = -Math.sin(angle), ny = Math.cos(angle);
  const band = ctx.createLinearGradient(cx - nx * diag * .25, cy - ny * diag * .25, cx + nx * diag * .25, cy + ny * diag * .25);
  band.addColorStop(0, 'rgba(150,160,210,0)'); band.addColorStop(.5, 'rgba(150,160,210,.045)'); band.addColorStop(1, 'rgba(150,160,210,0)');
  ctx.fillStyle = band; ctx.fillRect(0, 0, width, height);

  let drawn = 0;
  const star = (x, y, r, alpha, rgb) => {
    ctx.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha})`;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); drawn++;
  };
  // Dust of tiny stars thickening along the band.
  const dust = Math.round(width * height / 1400);
  for (let i = 0; i < dust; i++) {
    const t = (random() - .5) * diag, off = gauss(random) * diag * .09;
    const x = cx + Math.cos(angle) * t + nx * off, y = cy + Math.sin(angle) * t + ny * off;
    if (x < 0 || y < 0 || x > width || y > height) continue;
    star(x, y, .3 + random() * .3, .12 + random() * .28, STAR_COLORS[0]);
  }
  // The field: mostly faint, some brighter, a rare few with a soft halo.
  const field = Math.round(width * height / 2600);
  for (let i = 0; i < field; i++) {
    const x = random() * width, y = random() * height, k = random();
    const rgb = STAR_COLORS[Math.floor(random() * STAR_COLORS.length)];
    if (k < .965) { star(x, y, k < .75 ? .35 + random() * .35 : .6 + random() * .45, k < .75 ? .25 + random() * .4 : .55 + random() * .4, rgb); continue; }
    const halo = ctx.createRadialGradient(x, y, 0, x, y, 6 + random() * 5);
    halo.addColorStop(0, `rgba(${rgb[0]},${rgb[1]},${rgb[2]},.35)`); halo.addColorStop(1, `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0)`);
    ctx.fillStyle = halo; ctx.fillRect(x - 12, y - 12, 24, 24);
    star(x, y, 1 + random() * .5, .95, rgb);
  }
  return drawn;
}

export function createSky() {
  const canvas = document.createElement('canvas');
  canvas.className = 'space-sky'; canvas.setAttribute('aria-hidden', 'true');
  let last = '';
  const paint = () => {
    const rect = canvas.getBoundingClientRect();
    const pixel = Math.min(window.devicePixelRatio || 1, 2);
    const key = `${Math.round(rect.width)}x${Math.round(rect.height)}@${pixel}`;
    if (key === last) return;
    last = key; paintSky(canvas, rect.width, rect.height, pixel);
  };
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(paint) : null;
  observer?.observe(canvas);
  requestAnimationFrame(paint);
  return { el: canvas, dispose() { observer?.disconnect(); } };
}
