import { ParticleField, DEFAULT_FIELD, SWATCHES, SPEED_MAX, readLook } from './particle-field.js';
const el=(tag,attrs={},...children)=>{const n=document.createElement(tag);for(const [k,v]of Object.entries(attrs)){if(k==='text')n.textContent=v;else if(k.startsWith('on'))n.addEventListener(k.slice(2),v);else n.setAttribute(k,v);}n.append(...children.filter(c=>c!=null));return n;};
let uid=0;
const SWATCH_NAMES={ember:'Ember',sunset:'Sunset',gold:'Gold',aurora:'Aurora',glacier:'Glacier',violet:'Violet',rose:'Rose',white:'White'};
const speedText=v=>`${(Number(v)/DEFAULT_FIELD.speed).toFixed(1)}×`;

// Color dots plus "any color" (the system color picker). Returns the element and a sync().
function colorChoice(pick){
  const wrap=el('div',{class:'field-swatches',role:'group','aria-label':'Particle color'});
  const dots=Object.entries(SWATCHES).map(([name,hex])=>el('button',{type:'button',class:'field-swatch',style:`--c:${hex}`,'data-color':hex,
    title:SWATCH_NAMES[name],'aria-label':`${SWATCH_NAMES[name]} particles`,'aria-pressed':'false',onclick:()=>pick(hex)}));
  const custom=el('input',{type:'color','aria-label':'Pick any color',oninput:()=>pick(custom.value)});
  const any=el('label',{class:'field-swatch field-swatch-any',title:'Any color'},custom);
  wrap.append(...dots,any);
  return {el:wrap,sync(color){
    let known=false;
    for(const d of dots){const on=d.dataset.color===color;known||=on;d.setAttribute('aria-pressed',String(on));}
    any.classList.toggle('picked',!known);any.style.setProperty('--c',known?'transparent':color);
    if(custom.value!==color)custom.value=color;
  }};
}

// The small "Tune" panel on the particle screen: color, speed, shuffle.
function tunePanel(getField){
  const id=`field-tune-${++uid}`;
  const dot=el('span',{class:'tune-dot','aria-hidden':'true'});
  const button=el('button',{class:'field-pause field-tune-btn',type:'button','aria-expanded':'false','aria-controls':id,title:'Color, speed and shuffle'},dot,'Tune');
  const colors=colorChoice(hex=>getField()?.update({color:hex}));
  const out=el('output',{text:speedText(DEFAULT_FIELD.speed)});
  const speed=el('input',{type:'range',min:'0',max:String(SPEED_MAX),step:'.05',value:String(DEFAULT_FIELD.speed),'aria-label':'Speed',
    oninput:()=>{out.textContent=speedText(speed.value);getField()?.update({speed:speed.value});}});
  const shuffle=el('button',{type:'button',class:'tune-shuffle',title:'Send the particles on a new random path',onclick:()=>getField()?.shuffle()},'Shuffle ⤮');
  const reset=el('button',{type:'button',class:'tune-reset',title:'Ember color, normal speed, the original motion',
    onclick:()=>getField()?.update({color:DEFAULT_FIELD.color,speed:DEFAULT_FIELD.speed,seed:0})},'Reset');
  const panel=el('div',{class:'field-tune',id,role:'group','aria-label':'Tune the particles',hidden:''},
    el('div',{class:'tune-head'},el('span',{text:'Color'})),colors.el,
    el('div',{class:'tune-head'},el('span',{text:'Speed'}),out),speed,
    el('div',{class:'tune-actions'},shuffle,reset));
  const outside=e=>{if(!panel.contains(e.target)&&!button.contains(e.target))close();};
  function open(){panel.hidden=false;button.setAttribute('aria-expanded','true');document.addEventListener('pointerdown',outside,true);}
  function close(){if(panel.hidden)return;panel.hidden=true;button.setAttribute('aria-expanded','false');document.removeEventListener('pointerdown',outside,true);}
  button.addEventListener('click',()=>panel.hidden?open():close());
  panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();button.focus();}});
  // stop the backboard's drag strip and the pop-out window's drag area from taking these clicks
  panel.addEventListener('pointerdown',e=>e.stopPropagation());
  return {button,panel,close,sync(look){
    colors.sync(look.color);dot.style.background=look.color;dot.style.boxShadow=`0 0 9px ${look.color}`;
    if(document.activeElement!==speed){speed.value=String(look.speed);out.textContent=speedText(look.speed);}
  },dispose(){close();}};
}

export function createParticleExperience({compact=false,tune=false}={}) {
  let field;
  const status=el('span',{class:'field-status',text:'LIVE PARTICLE STUDY'});
  const pause=el('button',{class:'field-pause',type:'button',text:'Pause motion',onclick:()=>field?.toggle()});
  const canvas=el('canvas',{class:'particle-canvas',tabindex:compact?'-1':'0',role:'img','aria-label':'A turning cloud of ash-like particles with glowing folds. Drag to turn, or focus and use arrow keys.'});
  const viewport=el('div',{class:'particle-viewport'},canvas);
  const tuner=tune?tunePanel(()=>field):null;
  const root=el('section',{class:`particle-experience ${compact?'particle-compact':''}`,'aria-label':'Particle Lab'},
    el('div',{class:'particle-topline'},el('span',{text:'GRID'}),status),viewport,
    el('div',{class:'particle-caption'},el('div',{},el('span',{class:'field-eyebrow',text:'A LITTLE CODE. A LIVING WORLD.'}),el('h2',{text:'Grid'})),
      el('div',{class:'caption-buttons'},pause,tuner?.button)),tuner?.panel);
  const syncers=[];if(tuner)syncers.push(tuner.sync);
  if(compact){root.append(el('a',{class:'particle-enter',href:'#/lab',text:'Enter the Particle Lab ↗'}));}
  else {
    const colors=colorChoice(hex=>field?.update({color:hex}));syncers.push(look=>colors.sync(look.color));
    const controls=el('div',{class:'field-controls'});
    for(const [key,title,help,max]of [['speed','Flow','How fast the cloud moves.',SPEED_MAX],['turbulence','Shape','From a quiet sphere to turbulent folds.',1.4],['glow','Glow','How brightly the color shines through.',1.5]]){
      const fmt=v=>key==='speed'?speedText(v):Math.round(v*100)+'%';
      const output=el('output',{text:fmt(DEFAULT_FIELD[key])});
      const input=el('input',{id:`field-${key}`,type:'range',min:'0',max:String(max),step:'.01',value:String(DEFAULT_FIELD[key]),'aria-describedby':`field-${key}-help`,oninput:()=>{
        field?.update({[key]:input.value});output.textContent=fmt(input.value);
      }});
      syncers.push(look=>{if(document.activeElement!==input){input.value=String(look[key]);output.textContent=fmt(look[key]);}});
      controls.append(el('div',{class:'field-control'},el('label',{for:`field-${key}`},el('span',{text:title}),output),input,el('p',{id:`field-${key}-help`,text:help})));
    }
    root.append(el('div',{class:'field-toolbar'},colors.el,el('div',{class:'field-actions'},
      el('button',{class:'field-reset',type:'button',text:'Shuffle motion ⤮',title:'Send the particles on a new random path',onclick:()=>field?.shuffle()}),
      el('button',{class:'field-reset',type:'button',text:'Reset experiment',onclick:()=>field?.reset()}))),controls);
  }
  const sync=look=>{for(const fn of syncers)fn(look);};
  sync(readLook());
  let disposed=false;
  const mount=()=>{if(disposed)return;field=new ParticleField(canvas,{compact,onLook:sync,onState:(paused,unavailable)=>{
    pause.textContent=paused?'Resume motion':'Pause motion';pause.setAttribute('aria-pressed',String(paused));
    status.textContent=unavailable?'STILL STUDY · GRAPHICS UNAVAILABLE':paused?'MOTION PAUSED':'LIVE PARTICLE STUDY';
    if(unavailable){pause.disabled=true;root.querySelectorAll('input, button.field-swatch, .field-reset, .field-tune button, .field-tune-btn').forEach(n=>n.disabled=true);}
  }});sync(field.settings);};
  // Mount after layout, so the initial canvas has its real dimensions.
  const frame=requestAnimationFrame(mount);
  return {el:root,react(characters){field?.react(characters);},dispose(){disposed=true;cancelAnimationFrame(frame);tuner?.dispose();field?.dispose();}};
}
