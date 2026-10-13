const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function load(name,exports,extra={}) {const ctx=vm.createContext({...extra});vm.runInContext(fs.readFileSync(`src/grid/server/static/${name}.js`,'utf8').replaceAll('export ','')+`\nObject.assign(this,{${exports}});`,ctx);return ctx;}
const particle=load('particle-field','fieldSettings,particleSeeds,colorVec,readLook,writeLook,shiftFor,randomSeed');
test('particle controls reject nonfinite values, clamp extremes and reject inherited palettes',()=>{
 const s=particle.fieldSettings({speed:Infinity,turbulence:-20,glow:99,palette:'__proto__',color:'red',seed:-3});
 assert.equal(s.speed,4.2);assert.equal(s.turbulence,0);assert.equal(s.glow,1.5);assert.equal(s.color,'#ff0e05');assert.equal(s.seed,0);
 assert.equal(particle.fieldSettings({palette:'glacier'}).color,'#1f8cff');
 assert.equal(particle.fieldSettings({color:' #A1B2C3 '}).color,'#a1b2c3');
 assert.equal(particle.fieldSettings({color:'#12345'}).color,'#ff0e05');
 assert.equal(particle.fieldSettings({seed:2.5}).seed,0);assert.equal(particle.fieldSettings({seed:77}).seed,77);
});
test('any color becomes shader light; the look is shared and survives bad storage',()=>{
 assert.deepEqual([...particle.colorVec('#ff0080')].map(v=>+v.toFixed(3)),[1,0,0.502]);
 assert.deepEqual([...particle.colorVec('nope')].map(v=>+v.toFixed(3)),[1,0.055,0.02]);
 const mem={};const storage={getItem:k=>mem[k]??null,setItem:(k,v)=>{mem[k]=v;}};
 assert.equal(particle.readLook(storage).color,'#ff0e05');
 particle.writeLook({color:'#33f28c',speed:9,seed:5},storage);
 const look=particle.readLook(storage);assert.equal(look.color,'#33f28c');assert.equal(look.speed,9);assert.equal(look.seed,5);
 particle.writeLook({speed:99},storage);assert.equal(particle.readLook(storage).speed,10);
 mem['grid.particles.look']='{bad';assert.equal(particle.readLook(storage).seed,0);
});
test('shuffle moves the flow to a new place; seed 0 is the original motion',()=>{
 assert.deepEqual([...particle.shiftFor(0)],[0,0,0]);
 const a=particle.shiftFor(12345),b=particle.shiftFor(12345),c=particle.shiftFor(999);
 assert.deepEqual(a,b);assert.notDeepEqual(a,c);for(const v of [...a,...c])assert.ok(v>=-6&&v<=6);
 for(let i=0;i<50;i++){const s=particle.randomSeed();assert.ok(Number.isInteger(s)&&s>=1&&s<2147483648);}
});
test('changing the seed swirls into the new flow, or jumps there when paused',()=>{
 const {ParticleField}=load('particle-field','ParticleField',{document:{hidden:false}});
 const make=paused=>Object.assign(Object.create(ParticleField.prototype),{settings:{...particle.fieldSettings({})},shift:[0,0,0],paused,visible:true,motion:{matches:false},draw(){},onLook(){}});
 const moving=make(false);ParticleField.prototype.update.call(moving,{seed:42},{save:false});
 assert.deepEqual([...moving.shift],[0,0,0]);assert.deepEqual([...moving.shiftAnim.to],[...particle.shiftFor(42)]);
 const still=make(true);ParticleField.prototype.update.call(still,{seed:42},{save:false});
 assert.deepEqual([...still.shift],[...particle.shiftFor(42)]);assert.equal(still.shiftAnim,null);
 const color=make(false);ParticleField.prototype.update.call(color,{color:'#ffffff'},{save:false});assert.equal(color.shiftAnim,undefined);assert.deepEqual([...color.rgb],[1,1,1]);
});
test('particle seeds are deterministic finite positions in a thin spherical shell',()=>{
 const a=particle.particleSeeds(1000), b=particle.particleSeeds(1000);assert.deepEqual(a,b);
 for(let i=0;i<a.length;i+=4){const r=Math.hypot(a[i],a[i+1],a[i+2]);assert.ok(r>=.95999&&r<=1.00001);assert.ok(a[i+3]>=0&&a[i+3]<1);}
});
function target(){return {listeners:{},addEventListener(n,f){this.listeners[n]=f;},removeEventListener(n){delete this.listeners[n];}};}
function follower(){
 const stream=Object.assign(target(),{scrollHeight:1000,scrollTop:800,clientHeight:200,scrollTo(v){this.jump=v;this.scrollTop=v.top;}}),button=target(),jobs=new Map();let next=0;
 const env={requestAnimationFrame(fn){jobs.set(++next,fn);return next;},cancelAnimationFrame(id){jobs.delete(id);},matchMedia(){return {matches:true};}};
 const {StreamFollower}=load('scroll-follow','StreamFollower');const f=new StreamFollower(stream,button,env);
 const flush=()=>{const pending=[...jobs.values()];jobs.clear();pending.forEach(fn=>fn());};return {f,stream,button,jobs,flush};
}
test('stream bursts coalesce and upward scrolling cancels pending following',()=>{
 const {f,stream,jobs,flush}=follower();stream.scrollHeight=1200;f.contentChanged();f.contentChanged();assert.equal(jobs.size,1);
 stream.listeners.wheel({deltaY:-1});flush();assert.equal(stream.scrollTop,800);assert.equal(f.follow,false);
});
test('new messages keep an earlier reader in place and reveal return control',()=>{
 const {f,stream,button}=follower();f.detach();stream.scrollTop=400;stream.scrollHeight=1300;f.contentChanged();assert.equal(stream.scrollTop,400);assert.equal(button.hidden,false);
 button.listeners.click();assert.equal(stream.jump.behavior,'auto');assert.equal(f.follow,true);assert.equal(button.hidden,true);
});
test('returning to end resumes following and unmount releases pending work',()=>{
 const {f,stream,jobs,flush}=follower();f.detach();stream.scrollTop=800;stream.listeners.scroll();assert.equal(f.follow,true);
 stream.scrollHeight=1200;f.contentChanged();flush();assert.equal(stream.scrollTop,1200);
 f.contentChanged();f.dispose();assert.equal(jobs.size,0);assert.equal(Object.keys(stream.listeners).length,0);
});
test('no-WebGL fallback is quiet and disposable',()=>{
 let state;const classes=[];const canvas=Object.assign(target(),{getContext:()=>null,classList:{add:x=>classes.push(x)},parentElement:{classList:{add:x=>classes.push(x)}}});
 const {ParticleField}=load('particle-field','ParticleField',{window:{matchMedia:()=>({matches:true,removeEventListener(){}})},document:{removeEventListener(){}},cancelAnimationFrame(){}});
 const f=new ParticleField(canvas,{onState:(...s)=>state=s});assert.deepEqual(state,[true,true]);assert.ok(classes.includes('field-still'));f.dispose();assert.equal(f.disposed,true);
});
test('reply reactions stay subtle and ignore pause, reduced motion and hidden views',()=>{
 const {ParticleField}=load('particle-field','ParticleField',{document:{hidden:false}});
 const f={reaction:0,motion:{matches:false},visible:true};
 for(let i=0;i<100;i++)ParticleField.prototype.react.call(f,80);
 assert.equal(f.reaction,.18);
 for(const blocked of [{paused:true},{motion:{matches:true}},{visible:false},{disposed:true},{lost:true}]) {
   const quiet={reaction:0,motion:{matches:false},visible:true,...blocked};ParticleField.prototype.react.call(quiet,40);assert.equal(quiet.reaction,0);
 }
 ParticleField.prototype.react.call(f,NaN);assert.equal(f.reaction,.18);
});
test('reply impulse decays between animation frames without changing user settings',()=>{
 let tick;const {ParticleField}=load('particle-field','ParticleField',{document:{hidden:false},cancelAnimationFrame(){},requestAnimationFrame(fn){tick=fn;return 1;}});
 const f={reaction:.18,last:100,time:12,settings:{speed:4.2},turn:[0,0],targetTurn:[0,0],visible:true,draw(){},schedule(){}};
 ParticleField.prototype.schedule.call(f);tick(150);assert.ok(f.reaction>0&&f.reaction<.18);assert.equal(f.settings.speed,4.2);assert.ok(f.time>12.21&&f.time<12.24);
});

test('the cloud keeps one clock: it continues where it was across lay down, pop out and relaunch',()=>{
 const {readClock,writeClock}=load('particle-field','readClock,writeClock');
 const mem={};const storage={getItem:k=>mem[k]??null,setItem:(k,v)=>{mem[k]=v;}};
 assert.equal(readClock(0,storage),null);
 writeClock({time:100,speed:4,paused:false,turn:[.3,-.2]},1000,storage);
 const later=readClock(3000,storage);assert.equal(later.time,108);assert.deepEqual([...later.turn],[.3,-.2]);
 writeClock({time:50,speed:4,paused:true,turn:[0,0]},1000,storage);assert.equal(readClock(99000,storage).time,50);
 writeClock({time:10,speed:4,paused:false,turn:[0,0]},0,storage);assert.equal(readClock(1e12,storage).time,10+3600*4);
 mem['grid.particles.clock']='{bad';assert.equal(readClock(0,storage),null);
});
