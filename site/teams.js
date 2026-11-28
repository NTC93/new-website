/* NTC team portal. All data comes from the scheduled public nuLiga import. */
(()=>{
 const root=document.querySelector('[data-team-portal]');if(!root)return;
 const mode=root.dataset.teamPortal,category=root.dataset.category||'',source='https://tvbb.liga.nu/cgi-bin/WebObjects/nuLigaTENDE.woa/wa/clubTeams?club=36381';
 const $=(s,r=root)=>r.querySelector(s),el=(tag,cls,value)=>{const a=document.createElement(tag);if(cls)a.className=cls;if(value!==undefined)a.textContent=String(value);return a};
 const link=(label,url,cls='')=>{const a=el('a',cls,label);a.href=url;if(/^https?:\/\//i.test(url)&&new URL(url,location.href).origin!==location.origin){a.target='_blank';a.rel='noopener noreferrer'}return a};
 const qs=new URLSearchParams(location.search);
 const teamURL=t=>'/mannschaften/team/?id='+encodeURIComponent(t.id);
 const groups=['Damen','Herren','Seniorinnen','Senioren','Jugend','Mixed & Doppel','Weitere Teams'];
 const fmt=s=>{const d=String(s||'').split('-');return d.length===3?d[2]+'.'+d[1]+'.'+d[0]:'–'};
 const sort=(a,b)=>a.name.localeCompare(b.name,'de',{numeric:true});
 let data=null,last='',pending=false,season=qs.get('saison')||'',cat=category,selected=qs.get('id')||'';
 const today=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Berlin',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 function sourceLine(t){const a=el('div','tp-source');a.append(el('span','',data?.updated?'Datenstand: '+new Intl.DateTimeFormat('de-DE',{dateStyle:'medium',timeStyle:'short',timeZone:'Europe/Berlin'}).format(new Date(data.updated))+' Uhr · nuLiga / TVBB':'Quelle: nuLiga / TVBB'),link('Original bei nuLiga ↗',t?.group_url||source));return a}
 function select(label,values,value,change){const wrap=el('label','tp-select');wrap.append(el('span','',label));const s=el('select');for(const v of values){const option=el('option','',v.label??v.value);option.value=v.value;s.append(option)}s.value=value;s.addEventListener('change',()=>change(s.value));wrap.append(s);return wrap}
 function metric(label,value){const d=el('div','tp-stat');d.append(el('strong','',value??'–'),el('span','',label));return d}
 function promotion(status){if(!['promoted','position'].includes(status))return null;const mark=el('span','tp-promotion',status==='promoted'?'↑ Aufsteiger':'↑ Aufstiegsplatz');mark.title='Kennzeichnung nach nuLiga';return mark}
 function relegation(status){if(!['relegated','position'].includes(status))return null;const mark=el('span','tp-relegation',status==='relegated'?'↓ Absteiger':'↓ Abstiegsplatz');mark.title='Kennzeichnung nach nuLiga';return mark}
 function rankArrow(r){
  const up=['promoted','position'].includes(r.promotion_status),down=['relegated','position'].includes(r.relegation_status);
  const mark=el('span','tp-rank-arrow'+(up?' up':down?' down':''));
  if(!up&&!down){mark.setAttribute('aria-hidden','true');return mark}
  const description=up?(r.promotion_status==='promoted'?'Aufsteiger':'Aufstiegsplatz'):(r.relegation_status==='relegated'?'Absteiger':'Abstiegsplatz');
  mark.title=description;mark.setAttribute('role','img');mark.setAttribute('aria-label',description);
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');
  const arrow=document.createElementNS('http://www.w3.org/2000/svg','path');
  arrow.setAttribute('d',up?'M12 2 22 12H16V22H8V12H2Z':'M12 22 22 12H16V2H8V12H2Z');
  svg.append(arrow);mark.append(svg);return mark
 }
 function table(t){
  const section=el('section','tp-section');section.append(el('h2','',t.placement?'Tabelle der Platzierungsrunde':'Gruppentabelle'),el('p','tp-muted',t.group));
  if(t.status==='cached')section.append(el('p','tp-muted','Letzter erfolgreicher Datenabruf'+(t.data_updated?' vom '+new Intl.DateTimeFormat('de-DE',{dateStyle:'medium',timeStyle:'short',timeZone:'Europe/Berlin'}).format(new Date(t.data_updated)):'')+'; Aktualisierung vorübergehend nicht verfügbar.'));
  if(t.placement&&!t.table.length){section.append(el('p','tp-muted',t.status==='unavailable'?'Platzierungsrunde momentan nicht abrufbar.':'Platzierungsspiele – keine eigene Gruppentabelle.'),link('Original bei nuLiga ↗',t.group_url));return section}
  if(!t.table.length){section.append(el('p','tp-empty','Gruppentabelle momentan nicht verfügbar.'),link('Tabelle bei nuLiga öffnen ↗',t.group_url));return section}
  const cols=[['rank','Rang'],['name','Mannschaft'],['played','B'],['wins','S'],['draws','U'],['losses','N'],['points','Punkte'],['match_points','Matches'],['sets','Sätze'],['games','Spiele']];
  const scroll=el('div','tp-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','Gruppentabelle, horizontal scrollbar');
  const tab=el('table','tp-table'),head=el('thead'),hr=el('tr');
  for(const [,label] of cols){const th=el('th','',label);th.scope='col';hr.append(th)}
  head.append(hr);tab.append(head);const tbody=el('tbody');
  for(const r of t.table){const tr=el('tr',r.own?'tp-own':r.club?'tp-other-club':'');for(const [k] of cols){const td=el(k==='name'?'th':'td','',r[k]??'–');if(k==='name')td.scope='row';if(k==='rank'){td.classList.add('tp-rank-cell');const wrap=el('span','tp-rank');wrap.append(rankArrow(r),el('span','tp-rank-number',r.rank??'–'));td.replaceChildren(wrap)}tr.append(td)}tbody.append(tr)}
  tab.append(tbody);scroll.append(tab);section.append(scroll,el('p','tp-legend','B = Begegnungen · S = Siege · U = Unentschieden · N = Niederlagen. Goldener Pfeil: Aufstieg / Aufstiegsplatz. Roter Pfeil: Abstieg / Abstiegsplatz. Die ausgewählte NTC-Mannschaft ist hervorgehoben.'));
  return section;
 }
 function fixtures(t,extra=false){
  const section=el('section','tp-section');section.append(el('h2','',extra||t.placement?'Platzierungsspiele / weitere Runde':'Spielplan & Ergebnisse'));
  if(extra||t.placement)section.append(el('p','tp-muted',t.group+(t.table.length?'':' · keine eigene Gruppentabelle')));
  if(extra&&t.table.length)section.append(table(t));
  if(!t.matches.length){section.append(el('p','tp-empty','Noch keine Begegnungen verfügbar.'),link('Spielplan bei nuLiga ↗',t.group_url));return section}
  const scroll=el('div','tp-scroll');scroll.tabIndex=0;const tab=el('table','tp-table tp-fixtures'),h=el('thead'),hr=el('tr');
  for(const x of [...(extra||t.placement?['Runde / Spiel']:[]),'Datum','Uhrzeit','Spielort','Gegner','Ergebnis']){const th=el('th','',x);th.scope='col';hr.append(th)}h.append(hr);tab.append(h);
  const tbody=el('tbody');
  for(const m of t.matches){const tr=el('tr',!m.score&&m.date>=today()?'tp-upcoming':'');if(extra||t.placement)tr.append(el('td','',m.round_label||'Platzierungsspiel'));tr.append(el('td','',fmt(m.date)),el('td','',m.time||'–'),el('td','',m.home?'Heim':'Auswärts'),el('td','',(m.home?'gg. ':'bei ')+m.opponent));const td=el('td');if(Array.isArray(m.score)){const style=m.score[0]>m.score[1]?'win':m.score[0]<m.score[1]?'loss':'draw';const badge=el('span','tp-score '+style,m.score.join(':'));if(m.report){const a=link('',m.report);a.setAttribute('aria-label','Spielbericht '+m.opponent);a.append(badge);td.append(a)}else td.append(badge)}else td.append(el('span','tp-muted','–'));tr.append(td);tbody.append(tr)}
  tab.append(tbody);scroll.append(tab);section.append(scroll);return section
 }
 function additional(t){const section=el('div','tp-rounds');for(const r of t.rounds||[])section.append(fixtures(r,true));return section}
 function card(t){const a=link('',teamURL(t),'tp-card');const head=el('div','tp-card-top');head.append(el('strong','',t.name),el('span','tp-card-arrow','→'));a.append(head,el('div','tp-muted',t.group));if(t.rounds?.length)a.append(el('span','tp-muted','Mit Platzierungsspielen / weiterer Runde'));const mark=promotion(t.promotion_status),down=relegation(t.relegation_status);if(mark){a.classList.add('tp-card-promotion');a.append(mark)}if(down){a.classList.add('tp-card-relegation');a.append(down)}const numbers=el('div','tp-card-numbers');numbers.append(metric('Tabellenplatz',t.rank??'–'),metric('Punkte',t.points||'–'));a.append(numbers);return a}
 function render(){
  if(!data)return;
  const fragment=document.createDocumentFragment(),all=data.teams;
  if(mode==='detail'){
   const t=all.find(x=>x.id===selected||x.aliases?.includes(selected));
   if(!t){fragment.append(el('h1','','Mannschaft nicht verfügbar'),el('p','tp-empty','Dieser Eintrag ist zurzeit nicht verfügbar.'),link('← Alle Mannschaften','/mannschaften/'));root.replaceChildren(fragment);return}
   document.title=t.name+' · '+t.season+' | NTC 93';
   const header=el('div','tp-detail-header');header.append(link('← Alle Mannschaften','/mannschaften/?saison='+encodeURIComponent(t.season),'tp-back'),el('div','tp-kicker',t.season+' · '+t.category),el('h1','',t.name),el('p','tp-muted',t.group));
   const metrics=el('div','tp-metrics');metrics.append(metric('Tabellenplatz',t.rank??'–'),metric('Tabellenpunkte',t.points||'–'),metric('Begegnungen',t.table.find(r=>r.own)?.played||'–'));
   const mark=promotion(t.promotion_status),down=relegation(t.relegation_status);if(mark)header.append(mark);if(down)header.append(down);header.append(metrics);fragment.append(header,table(t),fixtures(t),additional(t),sourceLine(t));root.replaceChildren(fragment);return
  }
  if(!data.seasons.includes(season))season=data.seasons[0]||'';
  const pool=all.filter(t=>t.season===season);
  if(mode==='standings'){
   if(!pool.some(t=>t.id===selected))selected=pool[0]?.id||'';
   const filters=el('div','tp-filters');filters.append(select('Saison',data.seasons.map(value=>({value})),season,v=>{season=v;selected='';render()}),select('Mannschaft',pool.slice().sort(sort).map(t=>({value:t.id,label:t.name+' · '+t.group})),selected,v=>{selected=v;render()}));fragment.append(filters);
   const t=pool.find(x=>x.id===selected);if(t){fragment.append(table(t),additional(t),link('Zur Mannschaftsdetailseite →',teamURL(t),'tp-back'),sourceLine(t))}else fragment.append(el('p','tp-empty','Keine Tabellen verfügbar.'));
   root.replaceChildren(fragment);return
  }
  const filters=el('div','tp-filters');filters.append(select('Saison',data.seasons.map(value=>({value})),season,v=>{season=v;render()}));
  if(!category)filters.append(select('Bereich',[{value:'',label:'Alle Teams'},...groups.map(value=>({value}))],cat,v=>{cat=v;render()}));
  fragment.append(filters,el('p','tp-count',pool.filter(t=>!cat||t.category===cat).length+' Mannschaften · '+season));
  for(const g of groups){if(cat&&g!==cat)continue;const list=pool.filter(t=>t.category===g).sort(sort);if(!list.length)continue;const section=el('section','tp-section');section.append(el('h2','',g));const grid=el('div','tp-grid');list.forEach(t=>grid.append(card(t)));section.append(grid);fragment.append(section)}
  if(!pool.some(t=>!cat||t.category===cat))fragment.append(el('p','tp-empty','Für diese Saison sind in diesem Bereich keine Mannschaften verfügbar.'));
  fragment.append(sourceLine());root.replaceChildren(fragment)
 }
 async function refresh(){
  if(pending)return;pending=true;
  try{const response=await fetch('/teams.json?refresh='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(20000)});if(!response.ok)throw Error('not available');const next=await response.json();if(!Array.isArray(next.teams)||!next.teams.length||!Array.isArray(next.seasons))throw Error('invalid data');const key=JSON.stringify(next);if(key!==last){last=key;data=next;render()}}
  catch{if(!data){root.replaceChildren(el('p','tp-empty','Mannschaftsdaten werden noch bereitgestellt oder sind vorübergehend nicht verfügbar.'),link('Mannschaften bei nuLiga ansehen ↗',source))}}
  finally{pending=false}
 }
 refresh();setInterval(refresh,300000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
})();