const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/grid/server/static/app.js', 'utf8');
const context = vm.createContext({ debounce: fn => fn, clearInterval() {}, md() { return { lastElementChild: null, append() {} }; }, h() { throw new Error('card rendering reached'); } });
vm.runInContext(source.slice(source.indexOf('class Workspace {'), source.indexOf('// ------------------------------------------------------------------ layout preference')) + '\nthis.Workspace = Workspace;', context);
function workspace() {
  const w = new context.Workspace({ id: 'demo', name: 'Demo' });
  w.root = { dataset: {}, classList: { toggle(key, value) { this[key] = value; } } };
  w.buttons = ['play', 'code', 'understand'].map(mode => ({ dataset: { mode }, setAttribute(k, v) { this[k] = v; } }));
  w.workshopModes = { querySelectorAll: () => w.buttons };
  w.input = { value: 'my unsent idea', focus() { this.focused = true; } };
  w.editorArea = { tabs: ['unsaved-file'], layout() {} };
  w.termPanel = { fit: { fit() {} } };
  w.showTab = tab => { w.tab = tab; };
  return w;
}
test('mode switching preserves the unsent draft and open files, selects terminal only for Play', () => {
  const w = workspace();
  for (const mode of ['play', 'code', 'understand', 'code']) {
    w.setWorkshopMode(mode);
    assert.equal(w.root.dataset.workshop, mode);
    assert.deepEqual(w.buttons.filter(b => b['aria-pressed'] === 'true').map(b => b.dataset.mode), [mode]);
    assert.equal(w.input.value, 'my unsent idea');
    assert.deepEqual(w.editorArea.tabs, ['unsaved-file']);
  }
  assert.equal(w.tab, 'terminal');
  assert.equal(w.input.focused, true);
});
test('unknown modes cannot hide workspace controls', () => {
  const w = workspace();
  w.setWorkshopMode('play');
  w.setWorkshopMode('made-up');
  assert.equal(w.workshopMode, 'play');
});
test('an approval request reveals Understand before rendering any decision controls', () => {
  const w = workspace();
  w.setWorkshopMode('play');
  assert.throws(() => w.renderAsk({ id: 'approval', prompt: 'Approve this action?' }), /card rendering reached/);
  assert.equal(w.workshopMode, 'understand');
  assert.equal(w.input.focused, true);
});
test('collapsing the file drawer reserves explicit stage and guide tracks', () => {
  const css = fs.readFileSync('src/grid/server/static/workshop.css', 'utf8');
  // A hidden grid item does not reserve an auto-placement slot. Both live surfaces
  // must have an explicit desktop column when the first track is zero-width.
  assert.match(css, /\.workshop > \.center\s*\{\s*grid-column: 2;\s*grid-row: 2;/);
  assert.match(css, /\.workshop > \.convo\s*\{\s*grid-column: 3;\s*grid-row: 2;/);
});

test('a mounted review never hides the Play terminal or focused guide', () => {
  const w = workspace();
  w.editorArea.active = { kind: 'review' };
  for (const mode of ['code', 'play', 'understand', 'code']) {
    w.setWorkshopMode(mode);
    assert.equal(w.root.classList.reviewing, mode === 'code');
  }
});

test('project tabs override the old sidebar height and keep labels centered in fixed pills', () => {
  const css = fs.readFileSync('src/grid/server/static/workshop.css', 'utf8');
  const list = css.match(/\.project-list \{([^}]+)\}/)[1];
  const tab = css.match(/\.project-list a \{([^}]+)\}/)[1];
  assert.match(list, /min-height: 0;/);
  assert.match(list, /align-items: center;/);
  assert.match(tab, /height: 36px;/);
  assert.match(tab, /align-items: center;/);
  assert.match(tab, /padding: 0 12px;/);
});

test('new streamed reply text reacts once; duplicate, thinking, and replay text stay quiet',()=>{
 const w=workspace(), impulses=[];w.backboard={react:n=>impulses.push(n)};
 w.live={sid:1,phase:'text',text:'',meta:{},body:{replaceChildren(){}},el:{querySelector(){return {after(){}};}}};
 w.setLiveStatus=()=>{};w.followTail={contentChanged(){}};
 assert.throws(()=>w.onStream({sid:1,phase:'text',text:'Hello'}),/card rendering reached/);
 assert.deepEqual(impulses,[5]);
 w.live.text='Hello';w.onStream({sid:1,phase:'text',text:'Hello'});assert.deepEqual(impulses,[5]);
 assert.throws(()=>w.onStream({sid:1,phase:'text',text:'Hello again',replay:true}),/card rendering reached/);
 assert.deepEqual(impulses,[5]);
});

 test('typing a chat draft preserves the particle scene', () => {
  const w = workspace(), calls = [];
  w.backboard = { dismiss() { calls.push('dismiss'); } };
  w.autosize = () => calls.push('autosize');
  w.updateSlash = () => calls.push('slash');
  w.onComposerInput();
  assert.deepEqual(calls, ['autosize', 'slash']);
  assert.equal(w.input.value, 'my unsent idea');
 });
 test('starting and ending an agent reply keeps the particle scene visible', () => {
  const w = workspace(), calls = [];
  w.backboard = { dismiss() { calls.push('dismiss'); } };
  w.setPhase = () => {};
  w.runSpin = { classList: { toggle() { throw new Error('status rendering reached'); } } };
  for (const running of [true, false]) {
    assert.throws(() => w.setRunning(running), /status rendering reached/);
    assert.equal(w.running, running);
  }
  assert.deepEqual(calls, []);
 });

vm.runInContext(source.slice(source.indexOf('class EditorArea {'), source.indexOf('// ------------------------------------------------------------------ search across files')) + '\nthis.EditorArea = EditorArea;', context);
test('background file rendering preserves particles; deliberate file activation dismisses them', () => {
  const calls = [], toggle = { toggle() {}, add() {}, remove() {} };
  const e = Object.create(context.EditorArea.prototype);
  e.ws = { root: { classList: toggle }, workshopMode: 'play', backboard: { dismiss() { calls.push('dismiss'); } }, setWorkshopMode() {} };
  e.tabs = []; e.active = { kind: 'file' };
  e.tabBar = { replaceChildren() {} };
  for (const key of ['emptyEl', 'host', 'diffWrap', 'banner']) e[key] = { classList: toggle };
  e.editor = { updateOptions() {} };
  e.render();
  assert.deepEqual(calls, []);
  e.active = null; e.closeInline = () => {}; e.renderReview = () => {}; e.persist = () => {};
  e.activate({ kind: 'review' });
  assert.deepEqual(calls, ['dismiss']);
});
