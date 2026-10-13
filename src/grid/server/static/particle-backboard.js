import { createParticleExperience } from './particle-lab.js';

// The Grid particle screen inside the workspace.
//  - Four sizes, smallest first: "small" and "medium" float over the stage (drag them by
//    their top edge, or drag their corner to resize), "large" lies across the whole
//    stage, "full" covers the app. − and + step through them, gliding between shapes.
//  - Lay it down and it shrinks into a small "Grid" chip in the corner of the stage
//    (its GPU work stops); the chip brings it back up.
//  - In the desktop app it can also pop out into its own window that goes anywhere on
//    the screen, even outside Grid; "Bring back" returns it here.
export const BACKBOARD_SIZES = ['small', 'medium', 'large', 'full'];
const SIZE_KEY = 'grid.particles.size';
const POS_KEY = 'grid.particles.pos';
const GLIDE_MS = 420;
const EASE = 'cubic-bezier(.22, .9, .24, 1)';
const store = {
  get(key) { try { return globalThis.localStorage?.getItem(key) ?? null; } catch (e) { return null; } },
  set(key, value) { try { globalThis.localStorage?.setItem(key, value); } catch (e) { /* private mode */ } },
};
function savedSize() { const v = store.get(SIZE_KEY); return ['small', 'medium', 'large'].includes(v) ? v : 'large'; }
function lookColor() { try { const c = JSON.parse(store.get('grid.particles.look') || 'null')?.color; return /^#[0-9a-f]{6}$/i.test(c || '') ? c : '#ff0e05'; } catch (e) { return '#ff0e05'; } }
function savedPos() { try { const p = JSON.parse(store.get(POS_KEY) || 'null'); return p && Number.isFinite(p.x) && Number.isFinite(p.y) ? p : null; } catch (e) { return null; } }

export function createParticleBackboard(h, { experience = createParticleExperience, desktop = globalThis.window?.gridDesktop?.particles } = {}) {
  let scene, timer, disposed = false, returnFocus, size = savedSize(), resting = size, docked = false, popped = false, pos = savedPos();
  const root = h('section', { class: 'particle-backboard', 'aria-label': 'Grid particle screen' });
  const grip = h('div', { class: 'backboard-grip', title: 'Drag to move' });
  const smaller = h('button', { class: 'field-pause backboard-size', type: 'button', text: '−', onclick: () => step(-1) });
  const bigger = h('button', { class: 'field-pause backboard-size', type: 'button', text: '+', onclick: () => step(1) });
  const popOutBtn = desktop ? h('button', { class: 'field-pause', type: 'button', text: 'Pop out ↗', title: 'Open Grid in its own window you can move anywhere on your screen', onclick: () => popOut() }) : null;
  const layBtn = h('button', { class: 'field-pause', type: 'button', text: 'Lay down ↓', title: 'Lay the particle screen down (bring it back from the Grid chip)', onclick: () => layDown() });
  const controls = h('div', { class: 'backboard-controls' }, smaller, bigger, popOutBtn, layBtn);
  const chipNote = h('span', { class: 'chip-note', text: '' });
  const chip = h('button', { class: 'backboard-chip', type: 'button', 'aria-label': 'Bring the Grid particle screen back up', onclick: () => raise() },
    h('span', { class: 'chip-orb', 'aria-hidden': 'true' }), h('span', { class: 'chip-name', text: 'Grid' }), chipNote, h('span', { class: 'chip-up', 'aria-hidden': 'true', text: '↑' }));
  const reduced = () => !!globalThis.window?.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const canAnimate = () => !!root.animate && !reduced() && !root.hidden;
  const rect = () => root.getBoundingClientRect?.();

  function mount() {
    if (!scene) {
      scene = experience({ compact: true, tune: true });
      scene.el.querySelector('.particle-enter')?.remove();
      root.prepend(scene.el);
    }
  }
  function unmount() { scene?.dispose(); scene?.el.remove(); scene = null; }

  // Size changes move the real box from its old place and size to the new one, and the
  // particles are drawn fresh at every frame of the way (the canvas follows its box). Nothing
  // ever scales a picture of the cloud, so it never stretches, smears or blurs.
  let glideAnim = null;
  function glide(change) {
    const before = rect();
    glideAnim?.cancel();
    change();
    const after = rect();
    if (!before || !after || !canAnimate() || !before.width || !after.width) return;
    if (Math.abs(before.left - after.left) < 1 && Math.abs(before.top - after.top) < 1
        && Math.abs(before.width - after.width) < 1 && Math.abs(before.height - after.height) < 1) return;
    const st = root.style, keep = {};
    for (const k of ['position', 'inset', 'zIndex', 'maxWidth', 'maxHeight', 'minWidth', 'minHeight']) keep[k] = st[k];
    Object.assign(st, { position: 'fixed', inset: 'auto', zIndex: '1000', maxWidth: 'none', maxHeight: 'none', minWidth: '0', minHeight: '0' });
    const box = (r) => ({ left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
    const anim = root.animate([box(before), box(after)], { duration: GLIDE_MS, easing: EASE });
    glideAnim = anim;
    const done = () => { if (glideAnim === anim) glideAnim = null; Object.assign(st, keep); placeFloating(); };
    anim.onfinish = done; anim.oncancel = done;
  }
  // Coming up from the chip: rise and fade in where it will stand (no scaling).
  function rise() {
    if (!canAnimate()) return;
    root.animate([{ transform: 'translateY(26px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 340, easing: EASE });
  }

  function placeFloating() {
    if (!root.style) return;
    const floating = (size === 'small' || size === 'medium') && !docked;
    if (floating && pos) {
      const parent = root.parentElement, w = root.offsetWidth || 0, hgt = root.offsetHeight || 0;
      const maxX = Math.max(0, (parent?.clientWidth || Infinity) - w), maxY = Math.max(0, (parent?.clientHeight || Infinity) - hgt);
      root.style.left = `${Math.max(0, Math.min(pos.x, maxX))}px`; root.style.top = `${Math.max(0, Math.min(pos.y, maxY))}px`;
    } else { root.style.left = ''; root.style.top = ''; }
  }

  function applySize() {
    for (const s of BACKBOARD_SIZES) root.classList.toggle(`backboard-size-${s}`, s === size && !docked);
    root.classList.toggle('backboard-expanded', size === 'full' && !docked);
    root.classList.toggle('backboard-docked', docked);
    root.classList.toggle('backboard-popped', popped);
    root.setAttribute('data-size', docked ? 'docked' : size);
    const i = BACKBOARD_SIZES.indexOf(size);
    smaller.disabled = i === 0; bigger.disabled = i === BACKBOARD_SIZES.length - 1;
    const name = (s) => ({ small: 'small', medium: 'medium', large: 'regular', full: 'fullscreen' })[s];
    const lbl = (b, word, j) => { const t = j >= 0 && j < BACKBOARD_SIZES.length ? `Make the particle screen ${word} (${name(BACKBOARD_SIZES[j])})` : `Make the particle screen ${word}`; b.setAttribute('aria-label', t); b.title = t; };
    lbl(smaller, 'smaller', i - 1); lbl(bigger, 'bigger', i + 1);
    chipNote.textContent = popped ? 'on your desktop' : '';
    root.style?.setProperty?.('--particle-color', lookColor());   // the chip glows in the chosen color
    chip.setAttribute('aria-label', popped ? 'Bring Grid back into the app' : 'Bring the Grid particle screen back up');
    if (root.style) { root.style.width = ''; root.style.height = ''; }   // forget a hand-dragged size
    placeFloating();
    root.querySelector('.particle-canvas')?.setAttribute('tabindex', size === 'full' && !docked ? '0' : '-1');
  }

  function setSize(next, { animate = true } = {}) {
    if (!BACKBOARD_SIZES.includes(next) || disposed) return;
    if (docked) { size = next; return raise(); }
    const wasFull = size === 'full';
    const change = () => { size = next; applySize(); };
    animate ? glide(change) : change();
    if (next !== 'full') { resting = next; store.set(SIZE_KEY, next); }
    if (next === 'full' && !wasFull) { returnFocus = document.activeElement; bigger.focus?.({ preventScroll: true }); }
    if (next !== 'full' && wasFull && returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
  }
  function step(delta) { setSize(BACKBOARD_SIZES[Math.max(0, Math.min(BACKBOARD_SIZES.length - 1, BACKBOARD_SIZES.indexOf(size) + delta))]); }

  // Lay down: the screen sinks into the chip, then its GPU work stops.
  function layDown() {
    if (disposed || docked) return;
    clearTimeout(timer);
    if (size === 'full') { size = resting; }
    const before = rect();
    docked = true; root.inert = false;
    const finish = () => { if (docked) unmount(); };
    const chipAt = () => { applySize(); return rect(); };
    if (canAnimate() && before?.width) {
      root.classList.add('backboard-sinking');
      const anim = root.animate([{ transform: 'none', opacity: 1 }, { transform: 'translateY(26px)', opacity: 0 }], { duration: 260, easing: 'cubic-bezier(.4,0,.8,.2)' });
      timer = setTimeout(() => { root.classList.remove('backboard-sinking'); chipAt(); chip.animate?.([{ transform: 'translateY(10px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 260, easing: EASE }); finish(); }, 250);
      void anim;
    } else { chipAt(); timer = setTimeout(finish, 0); }
  }

  // Bring up: from the chip back to the size it had.
  function raise() {
    if (disposed) return;
    clearTimeout(timer);
    root.classList.remove('backboard-sinking');
    if (popped) { popped = false; desktop?.close?.(); }
    if (!docked) { mount(); return applySize(); }
    mount(); docked = false; applySize(); rise();
  }

  async function popOut() {
    if (!desktop?.open || disposed) return;
    let ok = false;
    try { ok = await desktop.open(); } catch (e) { ok = false; }
    if (!ok) return;
    popped = true; if (docked) applySize(); else layDown();
  }
  desktop?.onEvent?.((what) => {
    if (disposed) return;
    if (what === 'returned') { popped = false; raise(); }
    else if (what === 'closed') { popped = false; applySize(); }
  });

  // Drag the floating sizes around inside the app by their top edge.
  let drag = null;
  grip.addEventListener?.('pointerdown', (e) => {
    if (docked || !(size === 'small' || size === 'medium')) return;
    drag = { x: e.clientX, y: e.clientY, left: root.offsetLeft || 0, top: root.offsetTop || 0 };
    grip.setPointerCapture?.(e.pointerId); root.classList.add('backboard-dragging'); e.preventDefault?.();
  });
  grip.addEventListener?.('pointermove', (e) => {
    if (!drag) return;
    pos = { x: drag.left + e.clientX - drag.x, y: drag.top + e.clientY - drag.y }; placeFloating();
  });
  const endDrag = () => {
    if (!drag) return; drag = null; root.classList.remove('backboard-dragging');
    pos = { x: root.offsetLeft || 0, y: root.offsetTop || 0 }; store.set(POS_KEY, JSON.stringify(pos));
  };
  grip.addEventListener?.('pointerup', endDrag); grip.addEventListener?.('pointercancel', endDrag);

  function show({ fullscreen = false } = {}) {
    if (disposed) return;
    root.hidden = false; root.inert = false;
    if (docked) raise(); else mount();
    if (fullscreen) setSize('full');
  }
  // dismiss = lay down. auto: work started (a file opened, terminal typing) - a floating screen
  // stays where it is; only the stage-sized one steps aside.
  function dismiss({ auto = false } = {}) {
    if (auto && size !== 'large') return;
    layDown();
  }

  const onKey = event => {
    if (size !== 'full' || docked) return;
    if (event.key === 'Escape') { event.preventDefault(); setSize(resting); }
    if (event.key === 'Tab') {
      const buttons = [...root.querySelectorAll('button:not(:disabled)')];
      if (!buttons.length) return;
      const first = buttons[0], last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  };
  // the popped-out window changed the color: the chip follows
  const onStorage = (e) => { if (e.key === 'grid.particles.look') root.style?.setProperty?.('--particle-color', lookColor()); };
  globalThis.window?.addEventListener?.('storage', onStorage);
  root.append(grip, controls, chip); applySize(); mount(); root.addEventListener('keydown', onKey);
  return { el: root, show, dismiss, layDown, raise, setSize,
    get size() { return size; }, get docked() { return docked; }, get popped() { return popped; },
    react(characters) { if (!disposed && !docked && !root.hidden) scene?.react(characters); },
    dispose() { disposed = true; clearTimeout(timer); scene?.dispose(); root.removeEventListener('keydown', onKey); globalThis.window?.removeEventListener?.('storage', onStorage); if (popped) desktop?.close?.(); } };
}
