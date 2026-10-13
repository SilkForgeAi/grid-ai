// Follow new output only while the reader is at the end. Native wheel/trackpad
// scrolling is never intercepted; one scheduled update handles a burst of tokens.
export class StreamFollower {
  constructor(stream, button, env = window) {
    this.stream=stream;this.button=button;this.env=env;this.follow=true;this.frame=0;this.disposed=false;
    this.onScroll=()=>{this.follow=this.atEnd();this.updateButton();};
    this.onWheel=event=>{if(event.deltaY<0)this.detach();};
    this.onTouch=()=>this.detach();
    this.onKey=event=>{if(['PageUp','Home','ArrowUp'].includes(event.key))this.detach();};
    this.onJump=()=>{this.follow=true;this.updateButton();stream.scrollTo({top:stream.scrollHeight,behavior:env.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});};
    stream.addEventListener('scroll',this.onScroll,{passive:true});stream.addEventListener('wheel',this.onWheel,{passive:true});
    stream.addEventListener('touchstart',this.onTouch,{passive:true});stream.addEventListener('keydown',this.onKey);button.addEventListener('click',this.onJump);
    this.updateButton();
  }
  atEnd(){return this.stream.scrollHeight-this.stream.scrollTop-this.stream.clientHeight<72;}
  detach(){this.follow=false;this.env.cancelAnimationFrame(this.frame);this.frame=0;this.updateButton();}
  updateButton(){this.button.hidden=this.follow||this.atEnd();}
  contentChanged(){
    if(this.disposed)return;
    if(!this.follow){this.updateButton();return;}
    if(this.frame)return;
    this.frame=this.env.requestAnimationFrame(()=>{this.frame=0;if(!this.disposed&&this.follow){this.stream.scrollTop=this.stream.scrollHeight;this.updateButton();}});
  }
  dispose(){
    this.disposed=true;this.env.cancelAnimationFrame(this.frame);
    for(const [name,fn]of [['scroll',this.onScroll],['wheel',this.onWheel],['touchstart',this.onTouch],['keydown',this.onKey]])this.stream.removeEventListener(name,fn);
    this.button.removeEventListener('click',this.onJump);
  }
}
