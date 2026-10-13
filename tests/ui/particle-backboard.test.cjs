const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function fixture(reduced=false,desktop) {
  let disposed=0,mounted=0,next=0,reactions=0;const jobs=new Map(),listeners=new Map();
  const node=(tag,attrs={},...children)=>({tag,attrs,children,hidden:false,inert:false,isConnected:true,
    classList:{values:new Set(),add(x){this.values.add(x);},remove(x){this.values.delete(x);},contains(x){return this.values.has(x);},toggle(x,on){on?this.add(x):this.remove(x);}},
    append(...items){this.children.push(...items);},prepend(n){this.children.unshift(n);},remove(){this.removed=true;},
    querySelector(){return null;},querySelectorAll(){return this.children.filter(n=>n.tag==='button');},
    setAttribute(k,v){this.attrs[k]=v;},focus(){doc.activeElement=this;},addEventListener(n,f){listeners.set(n,f);},removeEventListener(n){listeners.delete(n);}});
  const original=node('button');const doc={activeElement:original,fullscreenElement:null,addEventListener(n,f){listeners.set(n,f);},removeEventListener(n){listeners.delete(n);}};
  const context=vm.createContext({document:doc,window:{matchMedia:()=>({matches:reduced})},setTimeout(fn,delay){jobs.set(++next,{fn,delay});return next;},clearTimeout(id){jobs.delete(id);}});
  const source=fs.readFileSync('src/grid/server/static/particle-backboard.js','utf8').replace(/^import .*;\n/,'').replace(/^export /gm,'');
  vm.runInContext(source+'\nthis.createParticleBackboard=createParticleBackboard;',context);
  const b=context.createParticleBackboard(node,{desktop,experience(){mounted++;return {el:node('scene'),react(n){reactions+=n;},dispose(){disposed++;}};}});
  return {b,jobs,listeners,doc,original,get reactions(){return reactions;},get disposed(){return disposed;},get mounted(){return mounted;},flush(){const all=[...jobs.values()];jobs.clear();all.forEach(j=>j.fn());}};
}
const controls=b=>b.el.children.find(n=>n.attrs?.class==='backboard-controls').children.filter(Boolean);
const chipOf=b=>b.el.children.find(n=>n.attrs?.class==='backboard-chip');
test('laying the screen down docks it as a Grid chip and frees the scene; bringing it up remounts it',()=>{
 const f=fixture();f.b.dismiss();assert.equal(f.b.docked,true);assert.equal(f.b.el.classList.contains('backboard-docked'),true);
 f.flush();assert.equal(f.disposed,1);assert.equal(f.b.el.hidden,false);
 chipOf(f.b).attrs.onclick();assert.equal(f.b.docked,false);assert.equal(f.mounted,2);assert.equal(f.b.size,'large');
});
test('bringing it up before the scene is freed keeps the same scene',()=>{
 const f=fixture();f.b.dismiss();f.b.show();f.flush();assert.equal(f.disposed,0);assert.equal(f.mounted,1);assert.equal(f.b.docked,false);
});
test('fullscreen is reversible with Escape and restores prior focus',()=>{
 const f=fixture();f.b.show({fullscreen:true});assert.equal(f.b.el.classList.contains('backboard-expanded'),true);
 let prevented=false;f.listeners.get('keydown')({key:'Escape',preventDefault(){prevented=true;}});
 assert.equal(prevented,true);assert.equal(f.b.el.classList.contains('backboard-expanded'),false);assert.equal(f.doc.activeElement,f.original);
});
test('reduced motion lays down at once and unmount cancels pending work',()=>{
 const f=fixture(true);f.b.dismiss();assert.equal([...f.jobs.values()][0].delay,0);f.b.dispose();assert.equal(f.jobs.size,0);assert.equal(f.disposed,1);
 assert.equal(f.listeners.has('keydown'),false);f.b.show();assert.equal(f.mounted,1);
});
test('only a raised screen reacts to replies',()=>{
 const f=fixture();f.b.react(12);assert.equal(f.reactions,12);f.b.dismiss();f.b.react(24);f.flush();f.b.react(48);
 assert.equal(f.reactions,12);f.b.show();f.b.react(6);assert.equal(f.reactions,18);
});
test('smaller and bigger step through small, medium, regular and fullscreen, and stop at the ends',()=>{
 const f=fixture();const [smaller,bigger]=controls(f.b);
 assert.equal(f.b.size,'large');bigger.attrs.onclick();assert.equal(f.b.size,'full');assert.equal(bigger.disabled,true);
 smaller.attrs.onclick();assert.equal(f.b.size,'large');smaller.attrs.onclick();smaller.attrs.onclick();
 assert.equal(f.b.size,'small');assert.equal(smaller.disabled,true);assert.equal(f.b.el.classList.contains('backboard-size-small'),true);
 f.b.setSize('huge');assert.equal(f.b.size,'small');
});
test('the Particles button raises the screen in the workspace, not fullscreen',()=>{
 const f=fixture();f.b.dismiss();f.flush();f.b.show();assert.equal(f.b.size,'large');assert.equal(f.b.docked,false);
 assert.equal(f.b.el.classList.contains('backboard-expanded'),false);
});
test('a floating screen stays while you work; the stage-sized one lays itself down',()=>{
 const f=fixture();f.b.setSize('small');f.b.dismiss({auto:true});assert.equal(f.b.docked,false);
 f.b.dismiss();assert.equal(f.b.docked,true);
 const g=fixture();g.b.dismiss({auto:true});assert.equal(g.b.docked,true);
});
test('no desktop app: no pop-out button',()=>{
 const f=fixture();assert.equal(controls(f.b).some(b=>String(b.attrs.text).startsWith('Pop out')),false);
});
test('pop out opens the desktop window, docks here, and comes back when the window returns it',async()=>{
 let opened=0,closed=0,send;const desktop={async open(){opened++;return true;},close(){closed++;},onEvent(cb){send=cb;}};
 const f=fixture(false,desktop);const pop=controls(f.b).find(b=>String(b.attrs.text).startsWith('Pop out'));
 await pop.attrs.onclick();assert.equal(opened,1);assert.equal(f.b.popped,true);assert.equal(f.b.docked,true);
 send('returned');assert.equal(f.b.popped,false);assert.equal(f.b.docked,false);assert.equal(closed,0);
 await pop.attrs.onclick();chipOf(f.b).attrs.onclick();assert.equal(closed,1);assert.equal(f.b.docked,false);
 await pop.attrs.onclick();send('closed');assert.equal(f.b.popped,false);assert.equal(f.b.docked,true);
});
