/* Published CMS content is additive until the existing website migration is complete. */
(() => {
 const path=location.pathname.replace(/\/?$/,'/');
 const $=(s,r=document)=>r.querySelector(s);
 const make=(tag,cls,text)=>{const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=String(text);return x};
 const safe=(url)=>{try{if(!url)return '';const u=new URL(url,location.origin);return ['http:','https:'].includes(u.protocol)&&!['ntc93.com','www.ntc93.com'].includes(u.hostname.toLowerCase())?u.href:''}catch{return ''}};
 const img=(src,cls,alt='')=>{if(!safe(src))return null;const el=make('img',cls);el.src=safe(src);el.alt=alt;el.loading='lazy';el.decoding='async';return el};
 const date=(v)=>{if(!v)return '';const m=String(v).match(/^(\d{4})-(\d{2})-(\d{2})/);return m?m[3]+'.'+m[2]+'.'+m[1]:String(v)};
 async function items(kind){try{const r=await fetch('/admin/?public='+encodeURIComponent(kind),{credentials:'omit',cache:'no-cache'});if(!r.ok)return [];const data=await r.json();return Array.isArray(data.items)?data.items:[]}catch{return []}}
 function articleLink(item){return '/redaktion/?slug='+encodeURIComponent(item.slug)}
 function paragraphs(parent,body){for(const p of String(body||'').split(/\n\s*\n/).filter(Boolean)){const el=make('p','',p);el.style.whiteSpace='pre-line';parent.append(el)}}
 async function news(){const list=await items('news');if(!list.length)return;
 if(path==='/'){const box=$('.news');if(!box)return;const rows=[...box.querySelectorAll('.newsrow')];for(const item of list.slice(0,3).reverse()){const a=make('a','newsrow');a.href=articleLink(item);const photo=img(item.data.image,'home-thumb')||make('span','home-thumb fallback','NTC');const d=make('div');d.append(make('time','',date(item.publish_at)),make('strong','',item.title));a.append(photo,d,make('span','arrow','↗'));box.insertBefore(a,box.querySelector('.newsrow'))}const all=[...box.querySelectorAll('.newsrow')];all.slice(3).forEach(n=>n.remove())}
 if(path==='/news/'){const grid=$('.archive-grid');if(!grid)return;for(const item of list.slice().reverse()){const a=make('a','archive-item');a.href=articleLink(item);const photo=img(item.data.image,'archive-img')||make('span','archive-img archive-placeholder','NTC');const copy=make('div');copy.append(make('time','',date(item.publish_at)),make('h2','',item.title),make('p','',item.data.teaser||''),make('span','archive-read','Weiterlesen →'));a.append(photo,copy);grid.prepend(a)}document.dispatchEvent(new Event('ntc-news-updated'))}
 }
 async function article(){const root=$('#cms-article');if(!root)return;const slug=new URLSearchParams(location.search).get('slug');const row=(await items('news')).find(x=>x.slug===slug);root.replaceChildren();if(!row){root.append(make('h1','','Nachricht nicht verfügbar'),make('p','','Die Meldung wurde nicht veröffentlicht oder ist nicht mehr verfügbar.'));return}
 document.title=row.title+' | NTC 93';const dateEl=make('p','article-date',date(row.publish_at));const title=make('h1','pagetitle',row.title);root.append(dateEl,title);const lead=make('p','cms-lead',row.data.teaser||'');if(row.data.teaser)root.append(lead);const photo=img(row.data.image,'cms-article-image',row.title);if(photo)root.append(photo);const body=make('div','content');paragraphs(body,row.data.body);root.append(body)}
 async function sponsors(){const box=$('.sponsor-grid')||$('.sponsor-track');if(!box)return;const list=await items('sponsors');for(const item of list){const image=img(item.data.image,'',item.title);if(!image)continue;if([...box.querySelectorAll('img')].some(x=>x.src===image.src))continue;const link=safe(item.data.link);const el=make(link?'a':'div','sponsor-logo');if(link)el.href=link;el.append(image);box.append(el)}}
 async function notices(){const list=await items('notices');if(!list.length)return;const main=$('main');if(!main)return;const box=make('section','cms-notices');box.setAttribute('aria-label','Aktuelle Hinweise');for(const item of list){const el=make('div','cms-notice');el.append(make('strong','',item.title),make('p','',item.data.body||''));const link=safe(item.data.link);if(link){const a=make('a','','Weitere Informationen ↗');a.href=link;el.append(a)}box.append(el)}main.prepend(box)}

 async function events(){
  const target=$('[data-club-events]');if(!target)return;
  const compact=target.dataset.clubEvents==='compact';
  const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Berlin',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  // Remove expired fallback rows even when the CMS is temporarily unavailable.
  target.querySelectorAll('[data-event-date]').forEach(x=>{if(x.dataset.eventDate<today)x.remove()});
  try{
   const response=await fetch('/admin/?public=events',{credentials:'omit',cache:'no-cache'});
   if(!response.ok)throw Error('CMS unavailable');
   const payload=await response.json();if(!Array.isArray(payload.items))throw Error('Invalid event list');
   const upcoming=payload.items.filter(x=>x.data&&typeof x.data.date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(x.data.date)&&x.data.date>=today).sort((a,b)=>a.data.date.localeCompare(b.data.date)||String(a.data.time||'').localeCompare(String(b.data.time||'')));
   target.replaceChildren();
   for(const item of (compact?upcoming.slice(0,4):upcoming)){
    const row=make('article','club-event');row.dataset.eventDate=item.data.date;
    const d=new Date(item.data.date+'T12:00:00Z');
    const dt=make('div','club-event-date');dt.append(make('strong','',item.data.date.slice(8)),make('span','',new Intl.DateTimeFormat('de-DE',{month:'short',year:'numeric',timeZone:'Europe/Berlin'}).format(d)));
    const copy=make('div','club-event-copy');copy.append(make('h3','',item.title));
    if(item.data.status&&item.data.status.toLowerCase()!=='bestätigt')copy.append(make('span','club-event-status',item.data.status));
    const time=item.data.time?(item.data.time.includes('Uhr')?item.data.time:item.data.time+' Uhr'):'';
    const meta=[time,item.data.venue].filter(Boolean).join(' · ');
    if(meta)copy.append(make('p','club-event-meta',meta));
    if(!compact)paragraphs(copy,item.data.body);
    const link=safe(item.data.link);if(link){const linkEl=make('a','','Details →');linkEl.href=link;copy.append(linkEl)}
    row.append(dt,copy);target.append(row)
   }
  }catch{}
  if(!target.children.length)target.append(make('p','club-event-empty','Zurzeit sind keine weiteren Vereinstermine eingetragen.'));
 }

 if(path==='/'||path==='/news/')news();if(path==='/redaktion/')article();if(path==='/'||path==='/sponsoren/')sponsors();if(path==='/')notices();if(path==='/'||path==='/termine/')events();
})();