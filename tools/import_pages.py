"""Build static staging pages from the public NTC WordPress site."""
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlsplit, unquote
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import copy, re, requests, html, json

BASE = 'https://ntc93.com/'
HOSTS = {'ntc93.com','www.ntc93.com'}
ROOT = Path('site')
HEADERS = {'User-Agent':'NTC93 website migration (public pages)'}
def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=(10,35))
    r.raise_for_status()
    if urlsplit(r.url).hostname not in HOSTS: raise ValueError('external redirect')
    return BeautifulSoup(r.content,'html.parser'), r.url

def route(url, base=BASE):
    u = urlsplit(urljoin(base,url))
    if u.scheme not in ('http','https') or u.hostname not in HOSTS or u.query: return None
    p = unquote(u.path).strip('/')
    if not p: return '/'
    if len(p)>220 or not re.fullmatch(r'[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*',p): return None
    if p.split('/')[0] in ('wp-admin','wp-json','wp-content','wp-includes','feed','author','tag','category'): return None
    return '/'+p+'/'

home, _ = fetch(BASE)
pages = {}
groups = {}
def add(a, group=None):
    href = a.get('href','')
    title = ' '.join(a.stripped_strings)
    path = route(href)
    if path and path!='/' and title and title.lower() not in ('home','startseite'):
        pages.setdefault(path,title)
        if group and path not in groups.setdefault(group,[]): groups[group].append(path)

# WordPress menu items, including nested dropdowns. Deduplicate desktop/mobile menus.
for li in home.select('li.menu-item'):
    a = li.find('a',recursive=False)
    if not a: continue
    top = li
    for parent in li.parents:
        if parent.name=='li' and 'menu-item' in parent.get('class',[]): top=parent
    t = top.find('a',recursive=False)
    group = ' '.join(t.stripped_strings).strip() if t else ''
    add(a,group)
for nav in home.select('header nav, nav, [role=navigation]'):
    for a in nav.select('a[href]'): add(a)
for a in home.select('footer a[href], .site-footer a[href]'):
    if ' '.join(a.stripped_strings).lower() in ('impressum','datenschutz'): add(a)
for path,title in {'/news/':'Aktuelles','/termine/':'Termine','/verein/':'Verein','/ueber-uns/':'Über uns','/vorstand/':'Vorstand','/mannschaften/':'Teams','/mitglieder/':'Mitglied werden','/jugend/':'Jugend','/impressum/':'Impressum','/datenschutz/':'Datenschutz'}.items(): pages.setdefault(path,title)
# Current news linked from front page (archive pagination is a later migration task).
front_news = []
for a in home.select('a[href]'):
    p = route(a['href'])
    title = ' '.join(a.stripped_strings)
    if p and p not in pages and title.lower()=='weiterlesen':
        front_news.append(p)
        pages.setdefault(p,'')
for p in ['/damen-ii-mit-starkem-remis-herren-30-souveraen/','/grosse-ehre-fuer-gabi-faika/','/erster-aufschlag-fuer-die-wintersaison/']:
    pages.setdefault(p,'')

# Explicitly verified recent article URLs also serve as fallback.
NEWS = [["/damen-ii-mit-starkem-remis-herren-30-souveraen/","Damen II mit starkem Remis, Herren 30 souverän","19.11.2026"],["/grosse-ehre-fuer-gabi-faika/","Große Ehre für Gabi Faika","15.11.2026"],["/erster-aufschlag-fuer-die-wintersaison/","Erster Aufschlag für die Wintersaison","09.11.2026"],["/gemeinsam-fuer-unseren-neuen-kinderspielplatz-jetzt-abstimmen/","Gemeinsam für unseren neuen Kinderspielplatz: Jetzt abstimmen!","04.11.2026"],["/das-fazit-faellt-positiv-aus/","„Das Fazit fällt positiv aus“","22.10.2026"],["/clubmeisterschaften-ntc-nachwuchs-im-wettkampffieber/","NTC-Nachwuchs im Wettkampffieber",""],["/33-jahre-ntc-und-ein-brunch-zum-anstossen/","33 Jahre NTC – und ein Brunch zum Anstoßen",""],["/19-jahre-fuer-die-1-herren-danke-benny/","19 Jahre für die 1. Herren: Danke, Benny!",""],["/u10-midcourt-matchpraxis-startet-in-die-wintersaison/","U10-Midcourt: Matchpraxis startet in die Wintersaison",""],["/damen-65-einladungsturnier-eine-tradition-die-verbindet/","Damen 65: Einladungsturnier mit Tradition",""]]
for p,title,date in NEWS:
    pages[p]=title
# Prefer the actual content area; do not copy WP theme, navigation or scripts.
def extract(soup):
    for selector in ('main .entry-content','main .elementor[data-elementor-type="wp-page"]','main .elementor[data-elementor-type="wp-post"]','.entry-content','[data-elementor-type="wp-page"]','[data-elementor-type="wp-post"]','main','#content'):
        candidate = soup.select_one(selector)
        if candidate and (candidate.get_text(strip=True) or candidate.find('img')): return copy.deepcopy(candidate)
    return None

allowed = set('div section article p h1 h2 h3 h4 h5 h6 ul ol li dl dt dd table thead tbody tfoot tr th td a img figure figcaption blockquote strong b em i u s small sup sub br hr span time address details summary'.split())
def sanitize(node, url, local):
    for tag in node.select('script,style,noscript,iframe,object,embed,form,input,button,select,textarea,svg,video,audio,link,meta,nav,header,footer,.elementor-location-header,.elementor-location-footer,.elementor-hidden-desktop.elementor-hidden-tablet.elementor-hidden-mobile'):
        tag.decompose()
    for tag in list(node.find_all(True)):
        if tag.name is None: continue
        if tag.name not in allowed:
            tag.unwrap(); continue
        attrs = {}
        if tag.name=='a':
            href=tag.get('href','')
            if href.startswith('#'): attrs['href']=href
            else:
                full=urljoin(url,href)
                scheme=urlsplit(full).scheme
                if scheme in ('https','http','mailto','tel'):
                    p=route(full)
                    attrs['href']=p if p in local else full
                    fragment=urlsplit(full).fragment
                    if p in local and fragment: attrs['href']+='#'+fragment
                    if urlsplit(full).hostname not in HOSTS: attrs['rel']='noopener noreferrer'
        if tag.name=='img':
            src=tag.get('data-src') or tag.get('data-lazy-src') or tag.get('src','')
            full=urljoin(url,src)
            if not src or urlsplit(full).scheme not in ('http','https'):
                tag.decompose(); continue
            attrs={'src':full,'alt':tag.get('alt',''),'loading':'lazy','decoding':'async'}
        if tag.name in ('td','th'):
            for key in ('rowspan','colspan'):
                if str(tag.get(key,'')).isdigit(): attrs[key]=tag[key]
        if tag.get('id') and re.fullmatch(r'[a-zA-Z0-9_-]+',tag['id']): attrs['id']=tag['id']
        if tag.name=='time' and tag.get('datetime'): attrs['datetime']=tag['datetime']
        tag.attrs=attrs
        if tag.name=='h1': tag.name='h2'
    return ''.join(str(x) for x in node.contents)

postmeta = {}
def load(item):
    path,label=item
    try:
        soup,url=fetch(urljoin(BASE,path))
        node=extract(soup)
        if node is None: raise ValueError('no content container')
        title=soup.select_one('main h1, .entry-title, h1')
        actual=' '.join(title.stripped_strings) if title else ''
        title=label or actual or (soup.title.get_text(strip=True).split(' – ')[0] if soup.title else path.strip('/'))
        if path in {p for p,_,_ in NEWS}:
            meta=soup.select_one('meta[property="article:published_time"], meta[itemprop="datePublished"]')
            date=''
            if meta and meta.get('content'):
                m=re.match(r'(\d{4})-(\d{2})-(\d{2})',meta['content'])
                if m: date='.'.join(reversed(m.groups()))
            if not date:
                for t in soup.select('time, .elementor-post-info__item--type-date, .entry-date, .posted-on'):
                    m=re.search(r'\b\d{1,2}\.\d{1,2}\.\d{4}\b',t.get_text(' ',strip=True))
                    if m: date=m.group(); break
            if not date:
                m=re.search(r'\b\d{1,2}\.\d{1,2}\.\d{4}\b',node.get_text(' ',strip=True))
                if m: date=m.group()
            image=soup.select_one('meta[property="og:image"]')
            image=image.get('content','') if image else ''
            if not image:
                im=node.select_one('img')
                image=(im.get('data-src') or im.get('src','')) if im else ''
            image=urljoin(url,image) if image else ''
            if urlsplit(image).scheme not in ('http','https'): image=''
            paras=[' '.join(p.stripped_strings) for p in node.select('p')]
            teaser=next((p for p in paras if len(p)>65),'')
            if not teaser:
                desc=soup.select_one('meta[name="description"],meta[property="og:description"]')
                teaser=desc.get('content','') if desc else ''
            if len(teaser)>145: teaser=teaser[:145].rsplit(' ',1)[0]+' …'
            postmeta[path]=(date,image,teaser)
        return path,(title,node,url,None)
    except Exception as e:
        return path,(label or path.strip('/'),None,urljoin(BASE,path),str(e))

# Cap concurrency to avoid unnecessary load on the current website.
with ThreadPoolExecutor(max_workers=4) as pool:
    loaded=dict(pool.map(load,pages.items()))
hall = BeautifulSoup('<div><img src="https://ntc93.com/wp-content/uploads/2024/02/1000062201-1024x461.jpg" alt="Tennishalle des NTC"><h2>Ganzjährig Tennis spielen</h2><p>Unsere im Dezember 2023 eröffnete Zweifeld-Tennishalle bietet mit dem Advantage RedCourt Belag ein sandplatzähnliches Spielgefühl – auch im Winter.</p><p><a href="https://ntc93v8.ebusy.de/court-module/3076">Hallenplatz buchen →</a></p><h2>Informationen zur Halle</h2><p><a href="https://ntc93app.de/halle">Halleninformationen, Förderer und Sponsoring</a></p></div>','html.parser').div
loaded['/tennishalle/']=('Tennishalle',hall,'https://ntc93app.de/halle',None)
local={p for p,(_,node,_,err) in loaded.items() if node is not None}
local.add('/news/')
if len(local)<8: raise RuntimeError('Too few pages imported; leaving existing preview untouched')
source=BeautifulSoup((ROOT/'index.html').read_text(),'html.parser')
def rewrite(soup):
    for a in soup.select('a[href]'):
        p=route(a['href'])
        if p in local: a['href']=p
    for a in soup.select('a.brand'): a['href']='/'
    for im in soup.select('img[src]'):
        if im['src'].startswith('media/'): im['src']='/'+im['src']
rewrite(source)
# Add a members link without changing the existing main navigation hierarchy.
nav=source.select_one('#nav')
if nav and '/mitglieder/' in local and not nav.find('a',href='/mitglieder/'):
    a=source.new_tag('a',href='/mitglieder/');a.string='Mitglieder';nav.append(a)
# Build homepage news thumbnails from the same article metadata as the archive.
for row in source.select('.newsrow'):
    p=route(row.get('href',''))
    if p not in postmeta:
        p=row.get('href','') if row.get('href','') in postmeta else p
    if p in postmeta:
        date,image,teaser=postmeta[p]
        thumb=row.select_one('.home-thumb')
        if image and thumb:
            im=source.new_tag('img',attrs={'class':'home-thumb','src':image,'alt':'','loading':'lazy','decoding':'async'})
            thumb.replace_with(im)
        if date and row.find('time'):
            row.find('time').string=date
            m=re.fullmatch(r'(\d{1,2})\.(\d{1,2})\.(\d{4})',date)
            if m: row.find('time')['datetime']=m.group(3)+'-'+m.group(2).zfill(2)+'-'+m.group(1).zfill(2)
# Overview links in each section, instead of deeply nested desktop dropdowns.
def related(path):
    selected=[]
    for group, members in groups.items():
        if path in members: selected.extend(members)
    if path in ('/verein/','/ueber-uns/'): selected.extend(['/verein/','/ueber-uns/','/vorstand/'])
    if path in ('/news/','/termine/'): selected.extend(['/news/','/termine/'])
    if path in ('/mannschaften/','/jugend/','/mitglieder/'): selected.extend([path])
    links=[]
    for p in dict.fromkeys(selected):
        if p in local and p!=path: links.append('<a href="'+html.escape(p,quote=True)+'">'+html.escape(loaded[p][0])+' <span aria-hidden="true">→</span></a>')
    return '<aside class="section-nav" aria-label="Weitere Seiten"><h2>In diesem Bereich</h2>'+''.join(links)+'</aside>' if links else ''

css="""
.subpage{max-width:1320px;margin:auto;padding:30px clamp(20px,5vw,68px) 60px;min-height:60vh}.breadcrumbs{font-size:13px;color:#62726d;margin-bottom:19px}.breadcrumbs a{text-decoration:underline;text-underline-offset:3px}.pagetitle{font-size:clamp(30px,4vw,47px);letter-spacing:-.045em;line-height:1.13;margin:0 0 25px}.subgrid{display:grid;grid-template-columns:minmax(0,1fr) minmax(210px,270px);gap:clamp(28px,5vw,80px);align-items:start}.subgrid.solo{grid-template-columns:minmax(0,900px)}.content{min-width:0;font-size:15px;line-height:1.68;overflow-wrap:anywhere}.content h2{font-size:clamp(23px,2.4vw,30px);line-height:1.22;letter-spacing:-.025em;margin:29px 0 12px}.content h3{font-size:20px;line-height:1.3;margin:23px 0 10px}.content h4,.content h5,.content h6{font-size:17px;margin:18px 0 8px}.content p{margin:0 0 18px}.content a{color:var(--green);text-decoration:underline;text-underline-offset:3px}.content img{max-width:100%;width:auto;height:auto;display:block;margin:18px 0;object-fit:contain;max-height:420px}.content figure{margin:22px 0}.content figcaption{font-size:13px;color:#62726d}.content table{border-collapse:collapse;display:block;max-width:100%;overflow-x:auto;margin:20px 0}.content td,.content th{padding:10px 14px;border:1px solid var(--line);text-align:left}.content th{background:#e8efeb}.content ul,.content ol{padding-left:24px}.section-nav{border-top:3px solid var(--green);padding-top:14px}.section-nav h2{font-size:13px;text-transform:uppercase;letter-spacing:.1em;margin:0 0 12px;color:var(--green)}.section-nav a{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line);padding:11px 0;font-size:14px}.section-nav a:hover{color:var(--green)}.source-note{margin-top:42px;font-size:13px;color:#62726d;border-top:1px solid var(--line);padding-top:16px}.source-note a{text-decoration:underline}
@media(max-width:800px){.subpage{padding-top:28px;padding-bottom:48px}.subgrid{grid-template-columns:1fr}.section-nav{margin-top:20px}.pagetitle{margin-bottom:24px}}
"""
# Main page only uses the current layout. Fix local links and deploy unchanged design.
(ROOT/'index.html').write_text(str(source),encoding='utf-8')
header=str(source.header);footer=str(source.footer)
head=copy.deepcopy(source.head)
head.style.append(css)
head.style.append("\n.news-page{max-width:1320px;margin:auto;padding:28px clamp(20px,5vw,68px) 64px;min-height:65vh}.news-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;padding-bottom:24px;border-bottom:1px solid var(--line)}.news-heading h1{font-size:clamp(31px,4vw,47px);line-height:1.1;letter-spacing:-.045em;margin:8px 0}.news-heading p{margin:0;color:#586962;font-size:14px}.news-kicker{display:flex;gap:8px;align-items:center;font-size:11px;letter-spacing:.13em;font-weight:700;color:var(--green);text-transform:uppercase}.news-kicker:before{content:'';display:block;width:20px;height:3px;background:var(--yellow)}.news-search{display:flex;flex-direction:column;gap:6px;font-size:12px;font-weight:600;min-width:230px}.news-search input{font:inherit;font-weight:400;font-size:14px;padding:10px 12px;background:white;border:1px solid #cbd9d1;border-radius:5px;width:100%;color:var(--ink)}.archive-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 32px}.archive-item{display:grid;grid-template-columns:126px minmax(0,1fr);gap:15px;padding:19px 0;border-bottom:1px solid var(--line);align-items:start;min-width:0}.archive-item[hidden]{display:none}.archive-img{width:126px;aspect-ratio:4/3;object-fit:cover;border-radius:4px;display:block;background:#e1e9e3}.archive-placeholder{display:grid;place-items:center;color:var(--green);font-weight:750;font-size:16px;letter-spacing:.06em;background:linear-gradient(135deg,#dcece3,#f1f3eb)}.archive-item time{color:#60746a;font-size:11px;display:block;letter-spacing:.025em;margin-bottom:5px}.archive-item h2{font-size:17px;line-height:1.3;letter-spacing:-.018em;margin:0 0 6px;font-weight:700;overflow-wrap:anywhere}.archive-item p{margin:0;font-size:13px;line-height:1.45;color:#52635d;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.archive-read{display:inline-block;font-size:11px;font-weight:700;color:var(--green);margin-top:7px}.archive-item:hover h2{color:var(--green)}.archive-bottom{display:flex;align-items:center;justify-content:space-between;padding-top:23px;gap:15px}.archive-count{font-size:12px;color:#60746a}.archive-empty{padding:24px 0;font-size:14px}.post-date{font-size:12px;color:#60746a;margin:-12px 0 25px}.post-back{display:inline-block;margin:0 0 22px;font-size:13px;color:var(--green);font-weight:650}\n@media(max-width:900px){.archive-grid{grid-template-columns:1fr;gap:0}.archive-item{grid-template-columns:110px minmax(0,1fr);gap:14px}.archive-img{width:110px}}\n@media(max-width:560px){.news-heading{flex-direction:column;align-items:stretch;gap:18px;padding-bottom:16px}.news-page{padding-top:20px;padding-bottom:40px}.archive-item{grid-template-columns:94px minmax(0,1fr);gap:12px;padding:15px 0}.archive-img{width:94px}.archive-item h2{font-size:15px}.archive-item p{font-size:12px}.archive-bottom{align-items:flex-start;flex-direction:column}}\n")
head.style.append("\n/* Consistent club editorial styling on compact content and news pages. */\n.subpage,.news-page{max-width:1350px;padding-left:clamp(20px,4vw,64px);padding-right:clamp(20px,4vw,64px)}\n.breadcrumbs{font-size:12px;color:#596b66;margin:0 0 17px}.pagetitle{font-size:clamp(30px,3.8vw,46px);letter-spacing:-.045em;border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:28px;position:relative}.pagetitle:after{content:'';position:absolute;bottom:-1px;left:0;width:58px;height:4px;background:var(--green)}.content h2{color:var(--deep);font-weight:730}.content h3{color:var(--deep)}.section-nav{border-top:4px solid var(--green);background:#eeeee5;padding:17px 18px}.section-nav h2{color:var(--deep);font-size:11px;letter-spacing:.13em}.section-nav a{line-height:1.45;font-weight:550;font-size:13px}.section-nav a:last-child{border:0}.content th{background:#e2ebe2}.content img{max-height:380px}.source-note{font-size:12px}\n.news-heading{position:relative;overflow:hidden;background:var(--deep);color:#fff;margin:0 0 18px;padding:23px 26px;border:0;align-items:flex-end}.news-heading:after{content:'';position:absolute;right:32%;top:-85px;width:180px;height:260px;transform:rotate(-15deg);border:1px solid #ffffff15;background:linear-gradient(90deg,transparent 49.5%,#ffffff15 49.5% 50.5%,transparent 50.5%);pointer-events:none}.news-heading>div,.news-search{position:relative;z-index:1}.news-kicker{color:var(--yellow);font-size:10px}.news-heading h1{font-size:clamp(28px,3.2vw,40px);margin:7px 0 4px;line-height:1.1}.news-heading p{color:#d5e4dc;font-size:13px}.news-search{font-size:11px;color:#e4ede8;min-width:220px}.news-search input{border-radius:0;border:1px solid #ffffff60;background:#ffffff0e;color:#fff;padding:9px 11px}.news-search input::placeholder{color:#c6d9d3}.archive-grid{gap:0 34px}.archive-item{grid-template-columns:112px minmax(0,1fr);gap:14px;padding:15px 0;align-items:start}.archive-img{width:112px;aspect-ratio:4/3;object-fit:cover;border-radius:0}.archive-placeholder{background:var(--deep);color:var(--yellow);font-weight:800}.archive-item h2{font-size:16px;line-height:1.28;margin:0 0 5px}.archive-item time{color:#526a61;font-size:11px;font-weight:650;margin-bottom:3px}.archive-item p{font-size:12px;line-height:1.45}.archive-read{margin-top:5px;font-size:11px}.archive-bottom{padding:18px 0}.archive-item:hover .archive-img{filter:saturate(1.13)}\n@media(max-width:900px){.archive-grid{grid-template-columns:1fr}.archive-item{grid-template-columns:105px minmax(0,1fr)}.archive-img{width:105px}}\n@media(max-width:560px){.news-heading{padding:18px;gap:14px}.news-search{min-width:0}.archive-item{grid-template-columns:90px minmax(0,1fr);gap:12px}.archive-img{width:90px}.archive-item h2{font-size:15px}.archive-item p{font-size:12px}}\n")
for link in head.select('link[href]'):
    if link['href'].startswith('media/'): link['href']='/'+link['href']
menu_js="""const menu=document.querySelector('.menu'),nav=document.querySelector('#nav');menu.onclick=()=>{const open=nav.classList.toggle('open');menu.setAttribute('aria-expanded',String(open))};document.addEventListener('keydown',e=>{if(e.key==='Escape'){nav.classList.remove('open');menu.setAttribute('aria-expanded','false')}});"""
for path,(title,node,url,err) in loaded.items():
    if node is None: print('SKIPPED',path,err); continue
    if path=='/news/': continue
    body=sanitize(node,url,local)
    sidebar=related(path)
    if path in postmeta:
        sidebar=''
        date=postmeta[path][0] or next((d for p,t,d in NEWS if p==path),'')
        body='<a class="post-back" href="/news/">← Zur Nachrichtenübersicht</a>' + ('<p class="post-date">'+html.escape(date)+'</p>' if date else '') + body
    original='<div class="source-note">Inhaltsübernahme aus der bisherigen Vereinswebsite. <a href="'+html.escape(url,quote=True)+'">Originalseite ansehen</a></div>'
    if path=='/termine/': original='<p><a class="textlink" href="'+html.escape(url,quote=True)+'">Aktuellen Kalender auf der bisherigen Website öffnen →</a></p>'+original
    h=copy.deepcopy(head);h.title.string=title+' | NTC 93'
    markup='<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="subpage"><div class="breadcrumbs"><a href="/">Startseite</a> / '+html.escape(title)+'</div><h1 class="pagetitle">'+html.escape(title)+'</h1><div class="subgrid'+('' if sidebar else ' solo')+'"><article class="content">'+body+original+'</article>'+sidebar+'</div></main>'+footer+'<script>'+menu_js+'</script></body></html>'
    out=ROOT/path.strip('/')/'index.html';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(markup,encoding='utf-8')

# The old page renders desktop and mobile archives in parallel. Use one curated, deduplicated index.
def esc(value): return html.escape(str(value),quote=True)
items=[]
for path,title,fallback_date in NEWS:
    if path not in local: continue
    date,image,teaser=postmeta.get(path,('','',''))
    date=date or fallback_date
    target=path if path in local else urljoin(BASE,path)
    thumb=('<img class="archive-img" src="'+esc(image)+'" alt="" loading="lazy" decoding="async">') if image else '<span class="archive-img archive-placeholder" aria-hidden="true">NTC</span>'
    items.append('<a class="archive-item" href="'+esc(target)+'">'+thumb+'<div>'+('<time>'+esc(date)+'</time>' if date else '')+'<h2>'+esc(title)+'</h2>'+('<p>'+esc(teaser)+'</p>' if teaser else '')+'<span class="archive-read">Weiterlesen →</span></div></a>')
h=copy.deepcopy(head);h.title.string='Aktuelles | NTC 93'
filter_js="""const search=document.querySelector('#newsSearch'),items=[...document.querySelectorAll('.archive-item')],count=document.querySelector('#newsCount'),empty=document.querySelector('#newsEmpty');search.addEventListener('input',()=>{let n=0;const q=search.value.toLocaleLowerCase('de').trim();for(const item of items){item.hidden=!item.textContent.toLocaleLowerCase('de').includes(q);if(!item.hidden)n++}count.textContent=n+' von '+items.length+' Meldungen';empty.hidden=n!==0});"""
news_markup='<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="news-page"><div class="breadcrumbs"><a href="/">Startseite</a> / Aktuelles</div><div class="news-heading"><div><div class="news-kicker">Vereinsleben &amp; Sport</div><h1>Aktuelles</h1><p>Nachrichten und Berichte rund um den NTC 93.</p></div><label class="news-search" for="newsSearch">Meldungen durchsuchen<input id="newsSearch" type="search" placeholder="Suchbegriff eingeben …"></label></div><div class="archive-grid">'+''.join(items)+'</div><p id="newsEmpty" class="archive-empty" hidden>Keine passenden Meldungen gefunden.</p><div class="archive-bottom"><span id="newsCount" class="archive-count" aria-live="polite">'+str(len(items))+' aktuelle Meldungen</span><a class="textlink" href="https://ntc93.com/news/">Ältere Beiträge im bisherigen Archiv →</a></div></main>'+footer+'<script>'+menu_js+filter_js+'</script></body></html>'
out=ROOT/'news/index.html';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(news_markup,encoding='utf-8')

report={'imported':sorted(local),'skipped':{p:err for p,(_,_,_,err) in loaded.items() if err}}
(ROOT/'migration-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Imported',len(local),'pages:',', '.join(sorted(local)))
