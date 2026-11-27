(() => {
const root=document.querySelector('[data-matchcenter]');if(!root)return;
const full=root.dataset.matchcenter==='full', source='https://tvbb.liga.nu/cgi-bin/WebObjects/nuLigaTENDE.woa/wa/clubMeetings?club=36381';
const q=s=>root.querySelector(s),el=(tag,cls,value)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(value!==undefined)e.textContent=value;return e};
const localDay=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Berlin',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
let data=null,mode='all',pending=false,lastCheck=0,renderKey='',renderDay='';
function dateLabel(m){const d=m.date.split('-');return d[2]+'.'+d[1]+'.'+(full?d[0]:'')}
function external(a,url){a.href=url;a.target='_blank';a.rel='noopener noreferrer'}
function row(m,result){
 const a=el('a','match-row');external(a,m.report||source);
 const info=el('div','match-info'),meta=el('span','match-meta');
 const day=el('time','match-date',dateLabel(m));day.dateTime=m.date;
 meta.append(day,el('span','match-location',m.home?'Heim':'Auswärts'),el('span','match-league',m.league||''));
 info.append(meta,el('strong','match-team',m.team),el('span','match-opponent',(m.home?'gg. ':'bei ')+(m.opponent||'')));a.append(info);
 if(result){const score=m.score;const c=score[0]>score[1]?'win':score[0]===score[1]?'draw':'loss';const badge=el('div','match-score '+c,score.join(':'));badge.setAttribute('aria-label',(c==='win'?'Sieg':c==='loss'?'Niederlage':'Unentschieden')+' '+score.join(' zu '));a.append(badge)}
 else{const t=el('div','match-time');t.append(el('strong','',m.time||'–'),el('span','',m.time?'Uhr':'offen'));a.append(t)}
 return a;
}
function display(){
 if(!data)return;
 const today=localDay();renderDay=today;
 const team=q('[data-team]')?.value||'',matches=data.matches.filter(m=>(mode!=='home'||m.home)&&(!team||m.team===team));
 const results=matches.filter(m=>Array.isArray(m.score)).sort((a,b)=>(b.date+(b.time||'')).localeCompare(a.date+(a.time||'')));
 const upcoming=matches.filter(m=>!m.score&&m.date>=today).sort((a,b)=>(a.date+(a.time||'')).localeCompare(b.date+(b.time||'')));
 for(const [target,rows,isResult] of [['[data-results]',results,true],['[data-fixtures]',upcoming,false]]){
  const box=q(target);if(!box)continue;
  const visible=full?rows:rows.slice(0,3);
  const fragment=document.createDocumentFragment();
  for(const m of visible)fragment.append(row(m,isResult));
  if(!visible.length)fragment.append(el('p','match-empty',isResult?'Keine Ergebnisse vorhanden.':'Keine kommenden Begegnungen im aktuellen Zeitraum.'));
  box.replaceChildren(fragment);
 }
}
function updateTeams(){
 const select=q('[data-team]');if(!select)return;
 const selected=select.value;
 const teams=[...new Set(data.matches.map(m=>m.team))].sort((a,b)=>a.localeCompare(b,'de',{numeric:true}));
 if(JSON.stringify([...select.options].map(x=>x.value).filter(Boolean))===JSON.stringify(teams))return;
 const initial=[...select.options].find(x=>!x.value)||el('option','','Alle Mannschaften');initial.value='';
 select.replaceChildren(initial);
 for(const team of teams){const option=el('option','',team);option.value=team;select.append(option)}
 select.value=teams.includes(selected)?selected:'';
}
function updateStamp(stale=false){
 const target=q('[data-updated]');if(!target)return;
 if(!data){target.textContent='Daten zurzeit nicht verfügbar · direkt bei nuLiga ansehen';return}
 const stamp=new Date(data.updated);
 target.textContent=(Number.isNaN(stamp.getTime())?'Quelle: nuLiga':'Datenstand: '+new Intl.DateTimeFormat('de-DE',{dateStyle:'medium',timeStyle:'short',timeZone:'Europe/Berlin'}).format(stamp)+' Uhr · nuLiga')+(stale?' · Aktualisierung vorübergehend nicht verfügbar':' · automatische Aktualisierung');
}
async function load(force=false){
 if(pending||(!force&&Date.now()-lastCheck<15000))return;
 pending=true;lastCheck=Date.now();
 try{
  const response=await fetch('/matches.json?refresh='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(20000)});
  if(!response.ok)throw Error('data unavailable');
  const next=await response.json();
  if(!Array.isArray(next.matches)||!next.matches.length)throw Error('empty data');
  const nextKey=JSON.stringify(next.matches);
  const changed=nextKey!==renderKey||renderDay!==localDay();
  data=next;renderKey=nextKey;updateStamp();
  if(changed){updateTeams();display()}
 }catch(e){
  updateStamp(true);
  if(data){if(renderDay!==localDay())display();return}
  for(const target of ['[data-results]','[data-fixtures]']){
   const box=q(target);if(!box)continue;
   const a=el('a','match-empty','Begegnungen bei nuLiga öffnen ↗');external(a,source);box.replaceChildren(a);
  }
 }finally{pending=false}
}
q('[data-team]')?.addEventListener('change',display);
root.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>{mode=b.dataset.mode;root.querySelectorAll('[data-mode]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));display()}));
load(true);
// Refresh without reloading the page, resetting filters or interrupting the hero.
setInterval(()=>load(true),5*60*1000);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')load()});
window.addEventListener('focus',()=>load());
window.addEventListener('online',()=>load(true));
})();