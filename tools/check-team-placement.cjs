/* DOM regression check using the actual imported teams.json and generated page. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const data=JSON.parse(fs.readFileSync('site/teams.json','utf8'));
const html=fs.readFileSync('site/mannschaften/team/index.html','utf8');
const script=fs.readFileSync('site/teams.js','utf8');
const ids=new Set();
for(const team of data.teams){
 assert(!ids.has(team.id),'Duplicate team detail ID: '+team.id+' '+team.name);
 ids.add(team.id);
}
async function main(){
 let tested=0;
 for(const team of data.teams.filter(t=>t.rounds?.some(r=>r.matches?.length))){
  const dom=new JSDOM(html,{url:'https://neu.ntc93.de/mannschaften/team/?id='+encodeURIComponent(team.id),runScripts:'outside-only'});
  const w=dom.window;
  try{
   w.fetch=async()=>({ok:true,json:async()=>data});
   w.AbortSignal=globalThis.AbortSignal;
   w.setInterval=()=>0;
   w.eval(script);
   await new Promise(resolve=>setTimeout(resolve,30));
   const root=w.document.querySelector('[data-team-portal="detail"]');
   assert(root?.querySelector('h1')?.textContent===team.name,'Wrong detail selected: '+team.name);
   const summary=root.querySelector('#platzierungsspiele');
   assert(summary&&!summary.hidden,'Placement summary missing: '+team.name);
   const rows=[...summary.querySelectorAll('.tp-placement-match')];
   const expected=team.rounds.flatMap(r=>r.matches||[]);
   assert.equal(rows.length,expected.length,'Wrong placement count: '+team.name);
   expected.forEach((m,i)=>{
    assert(rows[i].textContent.includes(m.opponent),'Missing placement opponent: '+team.name+' '+m.opponent);
    if(Array.isArray(m.score))assert.equal(rows[i].querySelector('.tp-score')?.textContent,m.score.join(':'),'Missing placement score: '+team.name);
   });
   console.log('Placement DOM verified:',team.name,team.id,expected.length);
   tested+=expected.length;
  }finally{w.close()}
 }
 console.log('Placement fixtures rendered and verified:',tested);
}
main().catch(e=>{console.error(e);process.exitCode=1});
