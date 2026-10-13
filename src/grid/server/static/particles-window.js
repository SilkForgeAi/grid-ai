// Grid's particle screen in its own desktop window: drag it by the top edge anywhere on
// the screen (even outside Grid), "Bring back" docks it into the app again.
import { createParticleExperience } from './particle-lab.js';

const desktop = window.gridDesktop?.particles;
const scene = createParticleExperience({ compact: true, tune: true });
scene.el.querySelector('.particle-enter')?.remove();
document.getElementById('pw').append(scene.el);

const button = (text, title, onclick, cls = 'field-pause') => {
  const b = document.createElement('button');
  b.type = 'button'; b.className = cls; b.textContent = text; b.title = title; b.addEventListener('click', onclick);
  return b;
};
const controls = document.createElement('div');
controls.className = 'pw-controls';
if (desktop) controls.append(button('Bring back ↙', 'Put Grid back inside the app', () => desktop.close({ back: true })));
document.body.append(controls, button('×', 'Close', () => (desktop ? desktop.close({ back: false }) : window.close()), 'pw-close'));
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && desktop) desktop.close({ back: true }); });
window.addEventListener('beforeunload', () => scene.dispose());
