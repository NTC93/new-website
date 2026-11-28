(() => {
const root=document.querySelector('[data-matchcenter]');if(!root)return;
const full=root.dataset.matchcenter==='full', source='https://tvbb.liga.nu/cgi-bin/WebObjects/nuLigaTENDE.woa/wa/clubMeetings?club=36381';
const q=s=>root.querySelector(s),el=(tag,cls,value)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(value!==undefined)e.textContent=value;return e};
const localDay=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Berlin',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
let data=null,mode='all',pending=false,lastCheck=0,renderKey='',renderDay='',statusKey='';
const berlinClock=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Berlin',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
const SIX_HOURS=6*60*60*1000;
const starts=new Map();
function berlinStart(m){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(m.date||'')||!/^\d{1,2}:\d{2}$/.test(m.time||''))return null;
 const key=m.date+'T'+m.time;if(starts.has(key))return starts.get(key);
 const [y,mo,d]=m.date.split('-').map(Number),[h,mi]=m.time.split(':').map(Number);
 if(h>23||mi>59)return null;
 const wall=Date.UTC(y,mo-1,d,h,mi);let instant=wall;
 // Convert the Berlin local start into an actual UTC instant, including DST.
 for(let i=0;i<3;i++){
  const p=Object.fromEntries(berlinClock.formatToParts(new Date(instant)).map(x=>[x.type,x.value]));
  const observed=Date.UTC(+p.year,+p.month-1,+p.day,+p.hour%24,+p.minute,+p.second);
  const correction=wall-observed;if(!correction)break;instant+=correction;
 }
 starts.set(key,instant);return instant;
}
function state(m,now,day){
 if(Array.isArray(m.score))return 'scored';
 const start=berlinStart(m);
 if(start===null)return m.date<day?'ended':'upcoming';
 if(now<start)return 'upcoming';
 return now<start+SIX_HOURS?'running':'ended';
}
function currentStates(now=Date.now(),day=localDay()){return data?data.matches.map(m=>state(m,now,day)).join('|'):''}
function updateClock(){
 if(!data)return;
 const day=localDay();if(day!==renderDay||currentStates(Date.now(),day)!==statusKey)display();
}
function dateLabel(m){const d=m.date.split('-');return d[2]+'.'+d[1]+'.'+(full?d[0]:'')}
function external(a,url){a.href=url;a.target='_blank';a.rel='noopener noreferrer'}
let reportDialog=null,reportTrigger=null,oldOverflow='';
function makeDialog(){
 const dialog=el('dialog','mc-report');dialog.setAttribute('aria-labelledby','mc-report-title');
 const bar=el('div','mc-report-bar'),title=el('h2','','Spielbericht');title.id='mc-report-title';
 const close=el('button','mc-report-close','×');close.type='button';close.setAttribute('aria-label','Spielbericht schließen');close.addEventListener('click',()=>dialog.close());
 bar.append(title,close);const content=el('div','mc-report-content');dialog.append(bar,content);document.body.append(dialog);
 dialog.addEventListener('click',e=>{if(e.target===dialog){const b=dialog.getBoundingClientRect();if(e.clientX<b.left||e.clientX>b.right||e.clientY<b.top||e.clientY>b.bottom)dialog.close()}});
 dialog.addEventListener('close',()=>{document.body.style.overflow=oldOverflow;if(reportTrigger?.isConnected)reportTrigger.focus();else root.querySelector('.match-result-button')?.focus();reportTrigger=null});
 return dialog
}
function showReport(m,trigger){
 if(!reportDialog)reportDialog=makeDialog();
 const content=reportDialog.querySelector('.mc-report-content');content.replaceChildren();
 const meta=el('div','mc-report-meta',[m.date.split('-').reverse().join('.'),m.time?m.time+' Uhr':'',m.league,m.home?'Heimspiel':'Auswärtsspiel'].filter(Boolean).join(' · '));
 const scoreboard=el('div','mc-report-scoreboard');
 const our=el('div','mc-report-team ntc');our.append(el('small','','NTC 93'),el('strong','',m.team));
 const other=el('div','mc-report-team opponent');other.append(el('small','','Gegner'),el('strong','',m.opponent));
 const scored=Array.isArray(m.score),result= scored?m.score.join(':'):'–';
 const score=el('div','mc-report-total'+(scored?(m.score[0]>m.score[1]?' win':m.score[0]<m.score[1]?' loss':' draw'):''),result);
 scoreboard.append(our,score,other);content.append(meta,scoreboard);
 if(!scored)content.append(el('p','mc-report-empty','Das Ergebnis wurde bei nuLiga noch nicht eingetragen.'));
 else if(!m.details?.sections?.length)content.append(el('p','mc-report-empty','Die Einzelergebnisse sind noch nicht verfügbar oder konnten nicht übernommen werden.'));
 else{
  for(const section of m.details.sections){
   if(!Array.isArray(section.games)||!section.games.length)continue;
   const group=el('section','mc-report-section'),head=el('div','mc-report-section-head');
   head.append(el('h3','',section.kind==='Doppel'?'Doppelspiele':'Einzelspiele'));
   const total=section.games.reduce((a,g)=>Array.isArray(g.point)?[a[0]+g.point[0],a[1]+g.point[1]]:a,[0,0]);head.append(el('strong','mc-report-subtotal',total.join(':')));group.append(head);
   const labels=el('div','mc-game-labels');labels.append(el('span','','NTC 93'),el('span','','Satzstände'),el('span','','Gegner'));group.append(labels);
   section.games.forEach((g,i)=>{
    const line=el('div','mc-game'),left=el('div','mc-game-side ntc'),right=el('div','mc-game-side opponent'),middle=el('div','mc-game-middle');
    const names=(node,value)=>String(value||'–').split(' / ').forEach(n=>node.append(el('span','',n)));
    names(left,g.ntc);names(right,g.opponent);
    if(Array.isArray(g.point)){if(g.point[0]>g.point[1])left.classList.add('winner');else if(g.point[0]<g.point[1])right.classList.add('winner')}
    middle.append(el('small','',String(i+1)+'. '+section.kind));
    const setline=el('div','mc-game-sets');
    for(const set of Array.isArray(g.sets)?g.sets:[]){setline.append(el('span','',set))}
    if(!setline.children.length)setline.append(el('span','','–'));
    middle.append(setline);line.append(left,middle,right);group.append(line);
   });content.append(group);
  }
  content.append(el('p','mc-report-note','Alle Ergebnisse aus Sicht des NTC: NTC 93 steht immer links.'));
 }
 const foot=el('div','mc-report-foot');foot.append(el('span','','Quelle: nuLiga / TVBB'));
 if(m.report){const a=el('a','','Original-Spielbericht ↗');external(a,m.report);foot.append(a)}
 content.append(foot);
 reportTrigger=trigger;oldOverflow=document.body.style.overflow;document.body.style.overflow='hidden';
 reportDialog.showModal();reportDialog.querySelector('.mc-report-close').focus();
}
function row(m,status){
 const result=status==='scored'||status==='ended';
 const a=el(result?'button':'a','match-row'+(status==='running'?' match-running':status==='ended'?' match-ended':'')+(result?' match-result-button':''));
 if(result){a.type='button';a.setAttribute('aria-haspopup','dialog');a.setAttribute('aria-label','Spielbericht: '+m.team+' '+(m.home?'gegen ':'bei ')+m.opponent);a.addEventListener('click',()=>showReport(m,a))}
 else external(a,m.report||source);
 const info=el('div','match-info'),meta=el('span','match-meta');
 const day=el('time','match-date',dateLabel(m));day.dateTime=m.date;
 meta.append(day,el('span','match-location',m.home?'Heim':'Auswärts'),el('span','match-league',m.league||''));
 info.append(meta,el('strong','match-team',m.team),el('span','match-opponent',(m.home?'gg. ':'bei ')+(m.opponent||'')));a.append(info);
 if(status==='scored'){const score=m.score;const c=score[0]>score[1]?'win':score[0]===score[1]?'draw':'loss';const badge=el('div','match-score '+c,score.join(':'));badge.setAttribute('aria-label',(c==='win'?'Sieg':c==='loss'?'Niederlage':'Unentschieden')+' '+score.join(' zu '));a.append(badge)}
 else if(status==='running'){
  const t=el('div','match-status live');const label=el('strong','match-live-label','Laufend');label.prepend(el('span','match-live-dot'));t.append(label,el('small','','seit '+m.time+' Uhr'));t.title='Status anhand der angesetzten Spielzeit (6 Stunden)';a.append(t);
 }
 else if(status==='ended'){
  const t=el('div','match-status awaiting');t.append(el('strong','','Beendet'),el('small','','Ergebnis offen'));t.title='Spielzeit abgelaufen; Ergebnis bei nuLiga noch nicht eingetragen';a.append(t);
 }
 else{const t=el('div','match-time');t.append(el('strong','',m.time||'–'),el('span','',m.time?'Uhr':'offen'));a.append(t)}
 return a;
}
function display(){
 if(!data)return;
 const today=localDay(),now=Date.now();renderDay=today;statusKey=currentStates(now,today);
 const team=q('[data-team]')?.value||'',matches=data.matches.filter(m=>(mode!=='home'||m.home)&&(!team||m.team===team));
 const rows=matches.map(m=>({match:m,status:state(m,now,today)}));
 const order=(a,b)=>(a.match.date+(a.match.time||'')).localeCompare(b.match.date+(b.match.time||''));
 const results=rows.filter(x=>x.status==='scored'||x.status==='ended').sort((a,b)=>order(b,a));
 const upcoming=rows.filter(x=>x.status==='running'||x.status==='upcoming').sort((a,b)=>(a.status==='running'?0:1)-(b.status==='running'?0:1)||order(a,b));
 for(const [target,rows,isResult] of [['[data-results]',results,true],['[data-fixtures]',upcoming,false]]){
  const box=q(target);if(!box)continue;
  const visible=full?rows:rows.slice(0,3);
  const fragment=document.createDocumentFragment();
  for(const x of visible)fragment.append(row(x.match,x.status));
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
  if(changed){starts.clear();updateTeams();display()}else updateClock();
 }catch(e){
  updateStamp(true);
  if(data){updateClock();return}
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
// Update the time-dependent status independently of the nuLiga data refresh.
setInterval(updateClock,15000);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){updateClock();load()}});
window.addEventListener('focus',()=>{updateClock();load()});
window.addEventListener('online',()=>load(true));
})();