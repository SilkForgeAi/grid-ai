// A local GPU particle sculpture. No network, model calls, or project execution.
// Quick colors; any other color can be picked too. Ember is the original glow.
export const SWATCHES = Object.freeze({ ember: '#ff0e05', sunset: '#ff7a1a', gold: '#ffc21a', aurora: '#33f28c',
  glacier: '#1f8cff', violet: '#8f3dff', rose: '#ff2d8f', white: '#ffffff' });
// seed 0 is the original motion; "Shuffle" picks a new seed, which moves the whole flow field.
export const DEFAULT_FIELD = Object.freeze({ speed: 4.2, turbulence: 0.72, glow: 0.8, color: SWATCHES.ember, seed: 0 });
export const SPEED_MAX = 10;
export function hexColor(value) { return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value.trim()) ? value.trim().toLowerCase() : null; }
export function colorVec(hex) { const n = parseInt((hexColor(hex) || DEFAULT_FIELD.color).slice(1), 16); return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255]; }
export function randomSeed() { return 1 + Math.floor(Math.random() * 2147483646); }
// Where a seed's motion samples the noise: a different place gives a different flow.
export function shiftFor(seed) {
  if (!seed) return [0, 0, 0];
  let s = seed >>> 0;
  const random = () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; };
  random();
  return [random() * 12 - 6, random() * 12 - 6, random() * 12 - 6];
}
// The look (color, speed, shape, seed) is shared like the clock: the screen in the app, the
// popped-out window and the Lab all show the same cloud, and it is kept for the next launch.
const LOOK_KEY = 'grid.particles.look';
export function readLook(storage = globalThis.localStorage) {
  try { const v = JSON.parse(storage?.getItem(LOOK_KEY) || 'null'); return v && typeof v === 'object' ? fieldSettings(v) : { ...DEFAULT_FIELD }; }
  catch (_) { return { ...DEFAULT_FIELD }; }
}
export function writeLook(settings, storage = globalThis.localStorage) {
  try { storage?.setItem(LOOK_KEY, JSON.stringify(fieldSettings(settings))); } catch (_) { /* private mode */ }
}
// One cloud, wherever it is shown: its clock and turn are shared (same page, the popped-out
// window, the next launch), so laying it down, bringing it back, resizing or popping it out
// continues the same cloud instead of starting a new one.
const CLOCK_KEY = 'grid.particles.clock';
const SHUFFLE_MS = 2200;
export function readClock(now = Date.now(), storage = globalThis.localStorage) {
  try {
    const c = JSON.parse(storage?.getItem(CLOCK_KEY) || 'null');
    if (!c || !Number.isFinite(c.time) || !Number.isFinite(c.at)) return null;
    const away = Math.max(0, Math.min((now - c.at) / 1000, 3600));
    const speed = Number.isFinite(c.speed) ? Math.max(0, Math.min(c.speed, 10)) : DEFAULT_FIELD.speed;
    const turn = Array.isArray(c.turn) && c.turn.length === 2 && c.turn.every(Number.isFinite) ? c.turn : [0, 0];
    return { time: c.paused ? c.time : c.time + away * speed, turn };
  } catch (_) { return null; }
}
export function writeClock(state, now = Date.now(), storage = globalThis.localStorage) {
  try { storage?.setItem(CLOCK_KEY, JSON.stringify({ time: state.time, at: now, speed: state.speed, paused: !!state.paused, turn: state.turn })); } catch (_) { /* private mode */ }
}
export function fieldSettings(values = {}) {
  const bounded = (key, lo, hi) => Number.isFinite(Number(values[key])) ? Math.max(lo, Math.min(hi, Number(values[key]))) : DEFAULT_FIELD[key];
  const seed = Number(values.seed);
  return { speed: bounded('speed', 0, SPEED_MAX), turbulence: bounded('turbulence', 0, 1.4), glow: bounded('glow', 0, 1.5),
    color: hexColor(values.color) ?? (Object.hasOwn(SWATCHES, values.palette) ? SWATCHES[values.palette] : DEFAULT_FIELD.color),
    seed: Number.isInteger(seed) && seed >= 0 && seed < 2147483648 ? seed : 0 };
}
export function particleSeeds(count) {
  const data = new Float32Array(count * 4);
  let seed = 731;
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  for (let i = 0; i < count; i++) {
    const y = random() * 2 - 1, angle = random() * Math.PI * 2;
    const radius = Math.sqrt(1 - y * y), shell = 0.96 + random() * 0.04;
    data.set([radius * Math.cos(angle) * shell, y * shell, radius * Math.sin(angle) * shell, random()], i * 4);
  }
  return data;
}
const VERTEX = `
precision highp float;
attribute vec4 a_seed;
uniform float u_time, u_aspect, u_pixel, u_turbulence, u_glow, u_pass;
uniform vec2 u_turn;
uniform vec3 u_color, u_shift;
varying vec4 v_color;
float hash(vec3 p) { p=fract(p*.3183099+vec3(.1,.2,.3)); p*=17.; return fract(p.x*p.y*p.z*(p.x+p.y+p.z)); }
float noise(vec3 p) {
 vec3 i=floor(p), f=fract(p); f=f*f*(3.-2.*f);
 return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
 mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);
}
float fbm(vec3 p) { return noise(p)*.57+noise(p*2.03+7.1)*.28+noise(p*4.09+13.3)*.15; }
mat2 rotate(float a) { return mat2(cos(a),-sin(a),sin(a),cos(a)); }
void main() {
 vec3 p=a_seed.xyz, n=a_seed.xyz+u_shift;
 float t=u_time*.19;
 vec3 q=vec3(fbm(n*2.3+vec3(t,0,-t)),fbm(n*2.3+vec3(9,3,t)),fbm(n*2.3+vec3(4,-t,7)));
 vec3 flow=vec3(fbm(n*3.1+q*2.8+vec3(0,t,0)),fbm(n*3.1+q*2.8+vec3(t,11,4)),fbm(n*3.1+q*2.8+vec3(7,0,-t)));
 float ridges=sin((n.y+q.x*.8)*12.+t*.7)*sin((n.x+q.y*.7)*9.-t*.6);
 p += (flow-.5)*(u_turbulence*1.1+.12);
 p *= .83+q.z*.33+ridges*.055*u_turbulence;
 p.xz=rotate(u_time*.045+u_turn.x)*p.xz;
 p.yz=rotate(.18+u_turn.y)*p.yz;
 float hot=smoothstep(.48,.68,fbm(n*2.6+q*1.8+vec3(t*.5,-t*.8,3.)));
 float depth=clamp((p.z+1.3)/2.6,0.,1.);
 float light=.16+depth*.64;
 vec3 ash=mix(vec3(.67,.65,.68),u_color,.3)*light;   // the whole cloud leans toward the chosen color
 vec3 color=mix(ash,u_color*(.65+hot*1.8),clamp(hot*u_glow,0.,1.));
 float perspective=3.5/(3.5-p.z);
 vec2 screen=p.xy*perspective*.64;
 screen.x/=max(u_aspect,1.); screen.y*=min(u_aspect,1.);
 gl_Position=vec4(screen,0.,1.);
 gl_PointSize=(u_pass>.5 ? (16.+hot*26.) : (.9+a_seed.w*.55))*u_pixel*perspective;
 float alpha=u_pass>.5 ? hot*.026*u_glow : (.16+depth*.18)*(1.-hot*.3);
 v_color=vec4(u_pass>.5 ? u_color : color,alpha);
}`;
const FRAGMENT = `precision mediump float; varying vec4 v_color;
void main() { float d=length(gl_PointCoord-.5)*2.; if(d>1.) discard;
 gl_FragColor=vec4(v_color.rgb,v_color.a*pow(1.-d,1.6)); }`;

export class ParticleField {
  constructor(canvas, { compact = false, onState = () => {}, onLook = () => {} } = {}) {
    this.canvas = canvas; this.onState = onState; this.onLook = onLook; this.settings = readLook();
    this.rgb = colorVec(this.settings.color); this.shift = shiftFor(this.settings.seed); this.shiftAnim = null;
    this.disposed = false; this.visible = true; this.time = 12; this.turn = [0, 0]; this.targetTurn = [0, 0]; this.raf = 0;
    this.motion = window.matchMedia('(prefers-reduced-motion: reduce)'); this.paused = this.motion.matches;
    this.reaction = 0;
    this.count = compact ? 260000 : 600000; this.last = 0; this.saved = 0;
    const clock = readClock(); if (clock) { this.time = clock.time; this.turn = [...clock.turn]; this.targetTurn = [...clock.turn]; }
    // Transparent: the particles add their light over the pure black behind the canvas.
    this.gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, powerPreference: 'low-power' });
    if (!this.gl) { this.fallback(); return; }
    try { this.init(); } catch (_) { this.fallback(); return; }
    this.resize = new ResizeObserver(() => { this.size(); this.draw(); }); this.resize.observe(canvas);
    this.intersection = new IntersectionObserver(entries => { this.visible = entries[0].isIntersecting; this.schedule(); }); this.intersection.observe(canvas);
    this.onVisibility = () => { if (document.hidden) this.remember(); this.schedule(); }; document.addEventListener('visibilitychange', this.onVisibility);
    this.onMotion = event => { this.paused = event.matches; this.reaction = 0; this.last = 0; this.onState(this.paused); this.schedule(); };
    this.motion.addEventListener('change', this.onMotion);
    this.onLost = event => { event.preventDefault(); this.lost = true; cancelAnimationFrame(this.raf); this.fallback(); };
    canvas.addEventListener('webglcontextlost', this.onLost);
    // Another window (the popped-out screen, the Lab) changed the look: follow it.
    this.onStorage = event => { if (event.key === LOOK_KEY) this.update(readLook(), { save: false }); };
    window.addEventListener?.('storage', this.onStorage);
    this.onDown = event => { this.drag = [event.clientX, event.clientY, ...this.targetTurn]; canvas.setPointerCapture(event.pointerId); };
    this.onMove = event => { if (!this.drag) return; this.targetTurn = [this.drag[2]+(event.clientX-this.drag[0])*.006, this.drag[3]+(event.clientY-this.drag[1])*.006]; if(this.paused){this.turn=[...this.targetTurn];this.draw();} };
    this.onUp = () => { this.drag = null; };
    this.onKey = event => {
      const directions = { ArrowLeft: [-.12,0], ArrowRight: [.12,0], ArrowUp: [0,-.12], ArrowDown: [0,.12] };
      if (directions[event.key]) { event.preventDefault(); this.targetTurn=this.targetTurn.map((v,i)=>v+directions[event.key][i]); this.turn=[...this.targetTurn]; this.draw(); }
    };
    canvas.addEventListener('pointerdown',this.onDown); canvas.addEventListener('pointermove',this.onMove);
    canvas.addEventListener('pointerup',this.onUp); canvas.addEventListener('pointercancel',this.onUp); canvas.addEventListener('keydown',this.onKey);
    this.size(); this.draw(); this.onState(this.paused); this.schedule();
  }
  init() {
    const gl=this.gl;
    const shader=(type,source)=>{ const s=gl.createShader(type); gl.shaderSource(s,source); gl.compileShader(s);
      if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){gl.deleteShader(s);throw Error('Shader unavailable');} return s; };
    this.program=gl.createProgram(); const v=shader(gl.VERTEX_SHADER,VERTEX), f=shader(gl.FRAGMENT_SHADER,FRAGMENT);
    gl.attachShader(this.program,v);gl.attachShader(this.program,f);gl.linkProgram(this.program);gl.deleteShader(v);gl.deleteShader(f);
    if(!gl.getProgramParameter(this.program,gl.LINK_STATUS)) throw Error('Program unavailable');
    gl.useProgram(this.program); this.buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);gl.bufferData(gl.ARRAY_BUFFER,particleSeeds(this.count),gl.STATIC_DRAW);
    const loc=gl.getAttribLocation(this.program,'a_seed');gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,4,gl.FLOAT,false,0,0);
    this.uniforms={};for(const name of ['time','aspect','pixel','turbulence','glow','pass','turn','color','shift'])this.uniforms[name]=gl.getUniformLocation(this.program,'u_'+name);
    gl.enable(gl.BLEND);gl.blendFuncSeparate(gl.SRC_ALPHA,gl.ONE,gl.ONE,gl.ONE);gl.clearColor(0,0,0,0);
  }
  size() {
    if(this.disposed||this.lost)return;
    const rect=this.canvas.getBoundingClientRect();this.pixel=Math.min(window.devicePixelRatio||1,2);
    this.canvas.width=Math.max(1,Math.round(rect.width*this.pixel));this.canvas.height=Math.max(1,Math.round(rect.height*this.pixel));
    this.gl.viewport(0,0,this.canvas.width,this.canvas.height);
  }
  draw() {
    if(this.disposed||this.lost||!this.program)return;
    const gl=this.gl,u=this.uniforms,s=this.settings;gl.useProgram(this.program);gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform1f(u.time,this.time);gl.uniform1f(u.aspect,this.canvas.width/this.canvas.height);gl.uniform1f(u.pixel,this.pixel);
    gl.uniform1f(u.turbulence,s.turbulence+this.reaction*.35);gl.uniform1f(u.glow,s.glow+this.reaction*.65);gl.uniform2fv(u.turn,this.turn);gl.uniform3fv(u.color,this.rgb);gl.uniform3fv(u.shift,this.shift);
    gl.uniform1f(u.pass,1);gl.drawArrays(gl.POINTS,0,Math.min(this.count,6000));gl.uniform1f(u.pass,0);gl.drawArrays(gl.POINTS,0,this.count);
  }
  schedule() {
    cancelAnimationFrame(this.raf);this.raf=0;
    if(this.disposed||this.lost||this.paused||!this.visible||document.hidden){this.last=0;return;}
    this.raf=requestAnimationFrame(now=>{
      const elapsed=this.last?Math.min((now-this.last)/1000,.05):0;this.last=now;this.time+=elapsed*this.settings.speed*(1+this.reaction*.5);
      this.reaction*=Math.exp(-elapsed*3.8);
      if(this.shiftAnim){const a=this.shiftAnim;a.start??=now;const k=Math.min(1,(now-a.start)/SHUFFLE_MS),e=k<.5?4*k*k*k:1-Math.pow(-2*k+2,3)/2;
        this.shift=a.from.map((v,i)=>v+(a.to[i]-v)*e);if(k>=1)this.shiftAnim=null;}
      this.turn=this.turn.map((v,i)=>v+(this.targetTurn[i]-v)*.09);this.draw();
      if(now-this.saved>1000){this.saved=now;this.remember();}this.schedule();
    });
  }
  react(characters = 1) {
    if(this.disposed||this.lost||this.paused||this.motion.matches||!this.visible||document.hidden)return;
    const amount=Number.isFinite(characters)?Math.max(0,Math.min(characters,80)):0;
    this.reaction=Math.min(.18,this.reaction+Math.min(.06,amount*.004));
  }
  update(values, { save = true } = {}) {
    const seed=this.settings.seed;this.settings=fieldSettings({...this.settings,...values});this.rgb=colorVec(this.settings.color);
    if(this.settings.seed!==seed)this.morphTo(shiftFor(this.settings.seed));
    if(save)writeLook(this.settings);
    this.draw();try{this.onLook({...this.settings});}catch(_){}
  }
  // A new random flow. The cloud swirls from the old one into the new one (at once when paused).
  shuffle() { this.update({seed:randomSeed()});return this.settings.seed; }
  morphTo(target) {
    if(this.paused||this.motion?.matches||!this.visible||document.hidden||this.lost){this.shift=[...target];this.shiftAnim=null;return;}
    this.shiftAnim={from:[...this.shift],to:[...target],start:null};
  }
  remember() { if(!this.lost&&!this.disposed||this.disposing) writeClock({time:this.time,speed:this.settings.speed,paused:this.paused,turn:this.targetTurn}); }
  toggle() { this.paused=!this.paused;this.reaction=0;this.last=0;this.onState(this.paused);this.remember();this.schedule();return this.paused; }
  reset() {
    this.settings={...DEFAULT_FIELD};this.rgb=colorVec(this.settings.color);this.shift=[0,0,0];this.shiftAnim=null;writeLook(this.settings);
    this.reaction=0;this.time=12;this.turn=[0,0];this.targetTurn=[0,0];this.draw();try{this.onLook({...this.settings});}catch(_){}
  }
  fallback() {
    this.lost=true;this.canvas.classList.add('field-unavailable');
    this.canvas.parentElement?.classList.add('field-still');this.onState(true,true);
  }
  dispose() {
    this.disposing=true;this.remember();this.disposing=false;
    this.disposed=true;cancelAnimationFrame(this.raf);this.resize?.disconnect();this.intersection?.disconnect();
    document.removeEventListener('visibilitychange',this.onVisibility);if(this.onStorage)window.removeEventListener?.('storage',this.onStorage);this.motion?.removeEventListener('change',this.onMotion);
    for(const [name,fn] of [['webglcontextlost',this.onLost],['pointerdown',this.onDown],['pointermove',this.onMove],['pointerup',this.onUp],['pointercancel',this.onUp],['keydown',this.onKey]])if(fn)this.canvas.removeEventListener(name,fn);
    if(this.gl){if(this.buffer)this.gl.deleteBuffer(this.buffer);if(this.program)this.gl.deleteProgram(this.program);}
  }
}
