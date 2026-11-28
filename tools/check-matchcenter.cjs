/* Check the actual Matchcenter script with fixed Berlin-local match times. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const script=fs.readFileSync('site/matchcenter.js','utf8');
async function main(){
 const date='2026-11-28';
 const matches=Array.from({length:5},(_,i)=>({date,time:'10:00',start_at:date+'T10:00:00+01:00',team:'Test '+i,opponent:'Gast '+i,home:true,score:null,league:'Test'}));
 matches.push({date,time:'17:00',start_at:date+'T17:00:00+01:00',team:'Später',opponent:'Gast',home:true,score:null});
 matches.push({date,time:'10:00',start_at:date+'T10:00:00+01:00',team:'Mit Ergebnis',opponent:'Gast',home:false,score:[4,2]});
 const dom=new JSDOM('<div data-matchcenter="home"><div><h3>Termine</h3><div data-fixtures></div></div><div data-results></div></div>',{url:'https://neu.ntc93.de/',runScripts:'outside-only'});
 const w=dom.window;
 let now=Date.parse(date+'T15:00:00+01:00');
 const RealDate=w.Date;
 w.Date=class extends RealDate{constructor(...a){super(...(a.length?a:[now]))}static now(){return now}};
 w.AbortSignal=globalThis.AbortSignal;
 w.fetch=async()=>({ok:true,json:async()=>({matches,updated:new Date().toISOString()})});
 const timers=[];w.setInterval=(cb,ms)=>{timers.push({cb,ms});return 1};
 try{
  w.eval(script);
  await new Promise(resolve=>setTimeout(resolve,30));
  const live=w.document.querySelector('[data-live-fixtures]');
  assert.equal(live.querySelectorAll('.match-running').length,5,'All running matches must be displayed, not only three');
  assert.equal(w.document.querySelectorAll('[data-results] .match-result-button').length,1,'Submitted result must be shown immediately');
  now=Date.parse(date+'T16:00:00+01:00');
  const clock=timers.find(t=>t.ms===15000);assert(clock);clock.cb();
  assert(live.hidden,'Live section must disappear at six-hour boundary');
  assert.equal(w.document.querySelectorAll('[data-results] .match-ended').length,2,'Ended matches must enter latest-three result list');
  assert(w.document.querySelector('[data-results]').textContent.includes('Ergebnis offen'));
  assert(w.document.querySelector('[data-fixtures]').textContent.includes('Später'));
  console.log('Matchcenter status DOM verified: running, 6-hour transition, open scores, later fixtures');
 }finally{w.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
