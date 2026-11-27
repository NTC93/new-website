/* Accessible sponsor carousel and consent-based map. */
(() => {
  const track=document.querySelector('.sponsor-band .sponsor-track');
  if(track){
    const pause=document.querySelector('[data-sponsor-pause]');
    const prev=document.querySelector('[data-sponsor-prev]');
    const next=document.querySelector('[data-sponsor-next]');
    const reduced=matchMedia('(prefers-reduced-motion: reduce)');
    let stopped=reduced.matches, hovering=false, focused=false, pressed=false, visible=true;
    let direction=1,last=0,fraction=track.scrollLeft,resumeAt=0, edgeUntil=0,ignoreScrollUntil=0;
    track.classList.add('sponsor-auto');
    function overflow(){return track.scrollWidth-track.clientWidth>3}
    function update(){
      const available=overflow();
      for(const b of [pause,prev,next])if(b)b.hidden=!available;
      if(pause){pause.textContent=stopped?'▶':'Ⅱ';pause.setAttribute('aria-label',stopped?'Automatischen Logowechsel starten':'Automatischen Logowechsel pausieren');pause.setAttribute('aria-pressed',String(stopped));}
    }
    function defer(){resumeAt=performance.now()+2400;fraction=track.scrollLeft;edgeUntil=0}
    track.addEventListener('pointerenter',()=>hovering=true);
    track.addEventListener('pointerleave',()=>{hovering=false;defer()});
    track.addEventListener('focusin',()=>focused=true);
    track.addEventListener('focusout',e=>{if(!track.contains(e.relatedTarget)){focused=false;defer()}});
    track.addEventListener('pointerdown',()=>{pressed=true;defer()},{passive:true});
    window.addEventListener('pointerup',()=>{pressed=false;defer()},{passive:true});
    window.addEventListener('pointercancel',()=>{pressed=false;defer()},{passive:true});
    track.addEventListener('wheel',defer,{passive:true});
    if(pause)pause.addEventListener('click',()=>{stopped=!stopped;defer();resumeAt=0;update()});
    for(const [b,d] of [[prev,-1],[next,1]])if(b)b.addEventListener('click',()=>{defer();track.scrollBy({left:d*Math.max(120,track.clientWidth*.55),behavior:reduced.matches?'auto':'smooth'});direction=d;resumeAt=performance.now()+3000});
    reduced.addEventListener('change',()=>{stopped=reduced.matches;update()});
    if('ResizeObserver'in window)new ResizeObserver(()=>{fraction=track.scrollLeft;update()}).observe(track);
    new MutationObserver(()=>{fraction=track.scrollLeft;update()}).observe(track,{childList:true});
    if('IntersectionObserver'in window)new IntersectionObserver(es=>{visible=es[0].isIntersecting;fraction=track.scrollLeft},{threshold:0.01}).observe(track);
    function frame(t){
      const dt=Math.min(50,t-(last||t));last=t;
      const max=Math.max(0,track.scrollWidth-track.clientWidth);
      if(!stopped&&!hovering&&!focused&&!pressed&&visible&&!document.hidden&&max>3&&t>=resumeAt&&t>=edgeUntil){
        // Native scroll preserves manual swiping, real links and keyboard navigation.
        fraction=Math.max(0,Math.min(max,fraction+direction*dt*.026));
        ignoreScrollUntil=t+80;track.scrollLeft=Math.round(fraction);
        if(fraction>=max||fraction<=0){direction=fraction>=max?-1:1;edgeUntil=t+900}
      }else if(t<resumeAt||hovering||focused||pressed||stopped||!visible){fraction=track.scrollLeft}
      requestAnimationFrame(frame);
    }
    track.addEventListener('scroll',()=>{if(performance.now()>ignoreScrollUntil){fraction=track.scrollLeft;resumeAt=performance.now()+1700}},{passive:true});
    update();requestAnimationFrame(frame);
  }
  const load=document.querySelector('[data-load-map]');
  if(load)load.addEventListener('click',()=>{
    const mount=document.querySelector('[data-map-mount]');
    if(!mount)return;
    const iframe=document.createElement('iframe');
    iframe.title='Karte der Tennisanlage des Neuenhagener TC 93';
    iframe.src='https://maps.google.com/maps?q='+encodeURIComponent('Neuenhagener TC 93 e.V., Hildesheimer Straße 11-13, 15366 Neuenhagen bei Berlin, Deutschland')+'&z=16&output=embed';
    iframe.loading='lazy';iframe.referrerPolicy='no-referrer';iframe.allowFullscreen=true;
    mount.replaceChildren(iframe);
    mount.classList.add('map-loaded');
  },{once:true});
})();