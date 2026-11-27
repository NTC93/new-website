"""Build static staging pages from the public NTC WordPress site."""
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlsplit, unquote
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import copy, re, requests, html, json
from datetime import datetime
from archive_import import discover
from localize import localize

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
menu_paths=set(pages)
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
# Discover the full public archive, not just the first ten hardcoded headlines.
discovered, archive_report=discover(home,route,menu_paths)
news_index={p:(t,d) for p,t,d in NEWS}
for p in front_news:news_index.setdefault(p,('',''))
for p,(t,d) in discovered.items():
    if d and re.fullmatch(r'\d{4}-\d{2}-\d{2}',d):
        d=datetime.strptime(d,'%Y-%m-%d').strftime('%d.%m.%Y')
    old_title,old_date=news_index.get(p,('',''))
    news_index[p]=(t or old_title,d or old_date)
NEWS=[(p,t,d) for p,(t,d) in news_index.items()]
for p,title,date in NEWS:pages[p]=title
print('Archive discovered:',len(NEWS),'posts;',archive_report)

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
news_paths=set(news_index)
def load(item):
    path,label=item
    try:
        soup,url=fetch(urljoin(BASE,path))
        node=extract(soup)
        if node is None: raise ValueError('no content container')
        title=soup.select_one('main h1, .entry-title, h1')
        actual=' '.join(title.stripped_strings) if title else ''
        title=label or actual or (soup.title.get_text(strip=True).split(' – ')[0] if soup.title else path.strip('/'))
        if path in news_paths:
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
            postmeta[path]=(date or news_index[path][1],image,teaser)
        return path,(title,node,url,None)
    except Exception as e:
        return path,(label or path.strip('/'),None,urljoin(BASE,path),str(e))

# Cap concurrency to avoid unnecessary load on the current website.
with ThreadPoolExecutor(max_workers=4) as pool:
    loaded=dict(pool.map(load,pages.items()))
hall = BeautifulSoup('<div><img src="https://ntc93.com/wp-content/uploads/2024/02/1000062201-1024x461.jpg" alt="Tennishalle des NTC"><h2>Ganzjährig Tennis spielen</h2><p>Unsere im Dezember 2023 eröffnete Zweifeld-Tennishalle bietet mit dem Advantage RedCourt Belag ein sandplatzähnliches Spielgefühl – auch im Winter.</p><p><a href="https://ntc93v8.ebusy.de/court-module/3076">Hallenplatz buchen →</a></p><h2>Informationen zur Halle</h2><p><a href="https://ntc93app.de/halle">Halleninformationen, Förderer und Sponsoring</a></p></div>','html.parser').div
loaded['/tennishalle/']=('Tennishalle',hall,'https://ntc93app.de/halle',None)
local={p for p,(_,node,_,err) in loaded.items() if node is not None}
local.update(('/news/','/sponsoren/','/matchcenter/','/redaktion/','/'))
if len(local)<12: raise RuntimeError('Too few pages imported; leaving existing preview untouched')
source=BeautifulSoup((ROOT/'index.html').read_text(),'html.parser')
def rewrite(soup):
    for a in soup.select('a[href]'):
        p=route(a['href'])
        if p in local: a['href']=p
    for a in soup.select('a.brand'): a['href']='/'
    for im in soup.select('img[src]'):
        if im['src'].startswith('media/'): im['src']='/'+im['src']
rewrite(source)
# Shared navigation: retain the original destinations, prefer migrated pages.
def nav_target(label, fallback=''):
    if fallback in ('/matchcenter/','/sponsoren/','/tennishalle/'):
        return fallback
    wanted=' '.join(label.casefold().split())
    for a in home.select('li.menu-item a[href], nav a[href]')+home.select('a[href]'):
        if ' '.join(a.get_text(' ',strip=True).casefold().split())!=wanted: continue
        href=a['href'].strip()
        if not href or href.startswith('#'): continue
        full=urljoin(BASE,href)
        if urlsplit(full).scheme not in ('http','https'): continue
        p=route(full)
        return p if p in local else full
    if not fallback: return ''
    p=route(fallback)
    return p if p in local else urljoin(BASE,fallback)

NAV_JS="""(()=>{const n=document.querySelector('#nav');if(!n)return;const gs=[...n.querySelectorAll('.nav-group')];const desktop=()=>matchMedia('(min-width:1221px) and (hover:hover) and (pointer:fine)').matches;function set(g,v){g.querySelector('.nav-trigger').setAttribute('aria-expanded',String(v));g.querySelector('.nav-dropdown').hidden=!v;g.classList.toggle('is-open',v)}function close(except){gs.forEach(g=>{if(g!==except)set(g,false)})}gs.forEach(g=>{const b=g.querySelector('.nav-trigger');b.addEventListener('click',e=>{const open=b.getAttribute('aria-expanded')==='true';close(g);set(g,desktop()&&e.detail>0?true:!open)});g.addEventListener('pointerenter',()=>{if(desktop()){close(g);set(g,true)}});g.addEventListener('pointerleave',()=>{if(desktop()&&!g.matches(':focus-within'))set(g,false)});g.addEventListener('focusout',e=>{if(desktop()&&!g.contains(e.relatedTarget))set(g,false)});g.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();set(g,false);b.focus()}})});document.addEventListener('click',e=>{if(!n.contains(e.target))close()});window.addEventListener('resize',()=>{close()});})();"""
NAV_CSS="""
header{position:relative;z-index:50}
header .nav{gap:clamp(16px,2vw,32px);max-width:1600px;min-height:110px;padding-top:13px;padding-bottom:13px}
header .brand{gap:14px;flex-shrink:0;min-width:0}
header .brand img{width:78px;height:78px;max-width:none;object-fit:contain}
header .brand strong{display:block;font-size:30px;line-height:1.04;letter-spacing:-.04em}
header .brand small{display:block;font-size:12px;line-height:1.35;white-space:nowrap;margin-top:3px}
header .navlinks{gap:clamp(11px,1.35vw,23px);align-items:center}
.nav-group{position:relative;flex-shrink:0}
.nav-trigger{border:0;background:transparent;color:inherit;font:inherit;font-weight:650;cursor:pointer;display:flex;align-items:center;gap:6px;padding:13px 0;white-space:nowrap}
.nav-trigger:after{content:'';width:6px;height:6px;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:rotate(45deg);margin-top:-3px;transition:transform .18s}
.nav-trigger[aria-expanded=true]:after{transform:rotate(225deg);margin-top:3px}
.nav-trigger:hover,.nav-group.is-open .nav-trigger{color:var(--green,#146143)}
.nav-dropdown[hidden]{display:none!important}
.nav-dropdown{position:absolute;top:100%;left:-15px;min-width:235px;max-width:360px;max-height:65vh;overflow:auto;background:white;border:1px solid #dfe7df;border-top:3px solid var(--green,#146143);border-radius:0 0 12px 12px;box-shadow:0 16px 36px #193b2720;padding:9px;display:grid;gap:2px;z-index:100}
.nav-group:nth-last-child(-n+2) .nav-dropdown{left:auto;right:-12px}
.nav-dropdown .nav-section{display:grid;gap:2px;align-content:start;min-width:0}
.nav-dropdown .nav-section+.nav-section{border-top:1px solid #e6ece6;padding-top:8px;margin-top:5px}
.nav-dropdown .nav-section-title{font-size:10px;font-weight:750;text-transform:uppercase;letter-spacing:.07em;color:#687b70;padding:7px 10px 3px}
header .nav-dropdown a{display:block;padding:9px 10px;font-size:13px;line-height:1.4;border-radius:6px;font-weight:550;white-space:normal;color:#1b3526}
header .nav-dropdown a:hover,header .nav-dropdown a:focus-visible{background:#edf5ee;color:var(--green,#146143)}
.nav-dropdown.wide{min-width:465px;max-width:min(630px,85vw);grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:13px}
.nav-dropdown.wide .nav-section+.nav-section{border-top:0;padding-top:0;margin-top:0}
header .navlinks .nav-mobile-booking{display:none}
@media(min-width:1221px){header .navlinks{display:flex!important;position:static;background:none;padding:0;box-shadow:none}header .menu{display:none!important}}
@media(max-width:1220px){header .nav{min-height:88px;padding:12px clamp(16px,4vw,36px);gap:14px}header .brand img{width:60px;height:60px}header .brand strong{font-size:26px}header .brand small{font-size:10px}header .menu{display:flex!important;align-items:center;justify-content:center;flex-shrink:0}header .navlinks{display:none!important;position:absolute;top:100%;left:0;right:0;background:white;box-shadow:0 14px 28px #193b271c;border-top:1px solid #e0e8e1;max-height:calc(100dvh - 100px);overflow-y:auto;padding:12px clamp(18px,5vw,36px) 20px;align-items:stretch;gap:0;flex-direction:column}header .navlinks.open{display:flex!important}header .navlinks>a,.nav-group{border-bottom:1px solid #e4ebe4}header .navlinks>a,.nav-trigger{padding:13px 4px} .nav-trigger{width:100%;justify-content:space-between;font-size:15px}.nav-dropdown,.nav-dropdown.wide{position:static;min-width:0;max-width:none;max-height:none;box-shadow:none;border:0;border-left:2px solid #c8dacf;border-radius:0;margin:0 0 11px 6px;padding:0 0 0 10px;display:grid;grid-template-columns:1fr;gap:3px}.nav-dropdown.wide .nav-section+.nav-section{border-top:1px solid #e6ece6;padding-top:7px;margin-top:4px}header .nav-dropdown a{padding:9px 8px}header .navlinks .nav-mobile-booking{display:block}}
@media(max-width:540px){header .nav{min-height:76px;padding:10px 16px;gap:9px}header .brand{gap:10px}header .brand img{width:52px;height:52px}header .brand strong{display:block;font-size:23px}header .brand small{display:block;font-size:9px}header .booking{display:none!important}header .menu{margin-left:auto;font-size:13px}}
"""
def build_nav(source):
    nav=source.select_one('#nav')
    if not nav: return
    nav.clear()
    def link(label,target,parent):
        if not target: return
        a=source.new_tag('a',href=target);a.string=label;parent.append(a)
    def group(label,sections,wide=False):
        ident='nav-drop-'+str(len(nav.contents))
        g=source.new_tag('div',attrs={'class':'nav-group'})
        b=source.new_tag('button',attrs={'type':'button','class':'nav-trigger','aria-expanded':'false','aria-controls':ident})
        b.string=label;g.append(b)
        d=source.new_tag('div',attrs={'id':ident,'class':'nav-dropdown'+(' wide' if wide else ''),'hidden':''})
        seen=set()
        for heading,entries in sections:
            sect=source.new_tag('div',attrs={'class':'nav-section'})
            if heading:
                t=source.new_tag('div',attrs={'class':'nav-section-title'});t.string=heading;sect.append(t)
            count=0
            for title,lookup,fallback in entries:
                target=nav_target(lookup,fallback)
                if target and target not in seen:
                    link(title,target,sect);seen.add(target);count+=1
            if count:d.append(sect)
        if d.contents:g.append(d);nav.append(g)
    group('Aktuelles',[('',[('Nachrichten','News','/news/'),('Termine','Termine','/termine/'),('NTC Tennis App','NTC Tennis App',''),('TVBB Spielergebnisse','TVBB Spielergebnisse','')])])
    group('Verein',[('Über den NTC',[('Unser Verein','Über uns','/ueber-uns/'),('Vorstand','Vorstand','/vorstand/'),('Trainer','Trainer','/trainer/'),('Ehrenmitglieder','Ehrenmitglieder','/ehrenmitglieder/'),('Gastronomie','Gastronomie','')]),('Organisation & Partner',[('Sponsoren','Sponsoren','/sponsoren/'),('Sponsor werden','Sponsor werden','/sponsor-werden/'),('Satzung','Satzung',''),('NTC-Informationen','NTC-Informationen',''),('Platzordnung','Platzordnung',''),('Arbeitskarte','Arbeitskarte','')])],True)
    group('Teams',[('',[('Mannschaften im Überblick','Teams','/mannschaften/'),('Damen','Damen',''),('Herren','Herren',''),('Seniorinnen','Seniorinnen',''),('Senioren','Senioren',''),('Jugendteams','Jugendteams','')])])
    link('Matchcenter','/matchcenter/',nav)
    group('Jugend',[('Training',[('Jugend im Überblick','Jugend','/jugend/'),('Trainingskonzept','Trainingskonzept',''),('Teamsporttraining','Teamsporttraining',''),('Breitensporttraining','Breitensporttraining',''),('Minitennis','Minitennis',''),('Förderungskonzept','Förderungskonzept','')]),('Mannschaften',[('Jugendteams','Jugendteams',''),('Juniorinnen 15–18','Juniorinnen 15-18',''),('Junioren 15–18','Junioren 15-18',''),('Mixed Teams 10–12','Mixed Teams 10-12','')]),('Jugend-Angebote',[('Feriencamps','Feriencamps',''),('Turniere','Turniere',''),('Konditionstraining','Konditionstraining',''),('Workshops','Workshops',''),('Matchpraxis','Matchpraxis',''),('Jugend trainiert für Olympia','Jugend trainiert für Olympia',''),('Interne Rangliste','Interne Rangliste','')])],True)
    group('Tennishalle',[('',[('Unsere Tennishalle','Tennishalle','/tennishalle/'),('Hallenbuchung','Hallenbuchung','')])])
    group('Mitglieder',[('',[('Mitglied werden','Mitglied werden','/mitglieder/'),('Beiträge','Beiträge',''),('Satzung','Satzung',''),('Persönlicher Bereich','Persönlicher Bereich','')])])
    booking=source.select_one('.booking[href]')
    if booking:
        a=source.new_tag('a',href=booking['href'],attrs={'class':'nav-mobile-booking'});a.string='Platz buchen';nav.append(a)
    small=source.select_one('.brand small')
    if small: small.string='Neuenhagener Tennisclub 93 e. V.'
    source.head.style.append(NAV_CSS)
    script=source.new_tag('script');script.string=NAV_JS;source.body.append(script)
build_nav(source)

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
# Sponsors from the original homepage section; no invented logos or destinations.
def sponsor_logos():
    heading=next((x for x in home.find_all(re.compile(r'^h[1-6]$')) if re.fullmatch(r'(?:unsere\s+)?sponsoren',x.get_text(' ',strip=True),re.I)),None)
    if not heading:return []
    candidates=[]
    for node in heading.next_elements:
        if node is heading:continue
        name=getattr(node,'name',None)
        if name and re.fullmatch(r'h[1-6]',name):break
        if name=='img':candidates.append((node.get('data-src') or node.get('data-lazy-src') or node.get('src',''),node.get('alt',''),node.find_parent('a')))
        if name and node.get('data-settings'):
            try:
                settings=json.loads(node['data-settings'])
                def visit(obj):
                    if isinstance(obj,dict):
                        u=obj.get('url')
                        if isinstance(u,str):candidates.append((u,obj.get('alt',''),None))
                        for v in obj.values():visit(v)
                    elif isinstance(obj,list):
                        for v in obj:visit(v)
                visit(settings)
            except (ValueError,TypeError):pass
    items=[];seen=set()
    for src,alt,a in candidates:
        u=urljoin(BASE,src)
        if not src or urlsplit(u).scheme not in ('http','https') or not re.search(r'\.(?:png|jpe?g|webp|svg|gif)$',urlsplit(u).path,re.I):continue
        key=re.sub(r'-\d+x\d+(?=\.[^.]+$)','',urlsplit(u).path)
        if key in seen:continue
        seen.add(key)
        label=str(alt or '').strip() or re.sub(r'[-_]+',' ',Path(key).stem).strip() or 'Sponsor'
        target=urljoin(BASE,a.get('href','')) if a and a.get('href') else ''
        if urlsplit(target).scheme not in ('http','https') or route(target) in ('/',None) and urlsplit(target).hostname in HOSTS:target=''
        if re.search(r'\.(?:png|jpe?g|webp|svg|gif)$',urlsplit(target).path,re.I):target=''
        items.append((u,label,target))
    return items
SPONSORS=sponsor_logos()
def sponsor_tiles():
    result=[]
    for img,label,target in SPONSORS:
        body='<img src="'+html.escape(img,quote=True)+'" alt="'+html.escape(label,quote=True)+'" loading="lazy" decoding="async">'
        result.append('<a class="sponsor-logo" href="'+html.escape(target,quote=True)+'">'+body+'</a>' if target else '<div class="sponsor-logo">'+body+'</div>')
    return ''.join(result)
def sponsor_band():
    logos=sponsor_tiles()
    return '<section class="sponsor-band" aria-labelledby="sponsor-title"><div class="sponsor-head"><div><div class="section-kicker">Gemeinsam für den NTC</div><h2 id="sponsor-title">Unsere Sponsoren & Partner</h2></div><a class="sponsor-link" href="/sponsoren/">Alle Sponsoren →</a></div>'+('<div class="sponsor-track">'+logos+'</div>' if logos else '<p>Wir danken allen Partnern für ihre Unterstützung.</p>')+'</section>'
SPONSOR_CSS="""
.sponsor-band{max-width:1320px;margin:0 auto;padding:24px clamp(20px,5vw,68px) 42px}.sponsor-head{display:flex;align-items:end;justify-content:space-between;gap:12px;margin-bottom:16px}.sponsor-head h2{font-size:clamp(21px,2.4vw,29px);margin:5px 0;color:#183c2b;letter-spacing:-.03em}.sponsor-link{font-weight:650;color:#146143;font-size:13px;white-space:nowrap}.sponsor-track{display:flex;gap:12px;overflow-x:auto;padding:4px 1px 12px;scroll-snap-type:x proximity}.sponsor-logo{flex:0 0 150px;min-width:0;min-height:88px;background:white;border:1px solid #e1e9e2;border-radius:9px;display:grid;place-items:center;padding:15px;scroll-snap-align:start}.sponsor-logo img{width:100%;height:62px;object-fit:contain}.sponsor-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:26px 0 35px}.sponsor-grid .sponsor-logo{min-height:120px}.sponsor-grid .sponsor-logo img{height:83px}@media(max-width:540px){.sponsor-logo{flex-basis:125px;min-height:75px;padding:12px}.sponsor-logo img{height:50px}.sponsor-head{align-items:flex-start;flex-direction:column;gap:4px}}
"""
source.head.style.append(SPONSOR_CSS)
source.main.append(BeautifulSoup(sponsor_band(),'html.parser'))

# Shared header and sponsor section for staging pages.
# Published content is loaded independently from the generated site.
cms_style=source.new_tag('link',attrs={'rel':'stylesheet','href':'/cms-public.css'})
source.head.append(cms_style)
cms_script=source.new_tag('script',attrs={'src':'/cms-public.js','defer':''})
source.head.append(cms_script)
(ROOT/'index.html').write_text(str(source),encoding='utf-8')
header=str(source.header);footer=str(source.footer)
head=copy.deepcopy(source.head)
head.style.append(css)
head.style.append("\n.news-page{max-width:1320px;margin:auto;padding:28px clamp(20px,5vw,68px) 64px;min-height:65vh}.news-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;padding-bottom:24px;border-bottom:1px solid var(--line)}.news-heading h1{font-size:clamp(31px,4vw,47px);line-height:1.1;letter-spacing:-.045em;margin:8px 0}.news-heading p{margin:0;color:#586962;font-size:14px}.news-kicker{display:flex;gap:8px;align-items:center;font-size:11px;letter-spacing:.13em;font-weight:700;color:var(--green);text-transform:uppercase}.news-kicker:before{content:'';display:block;width:20px;height:3px;background:var(--yellow)}.news-search{display:flex;flex-direction:column;gap:6px;font-size:12px;font-weight:600;min-width:230px}.news-search input{font:inherit;font-weight:400;font-size:14px;padding:10px 12px;background:white;border:1px solid #cbd9d1;border-radius:5px;width:100%;color:var(--ink)}.archive-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 32px}.archive-item{display:grid;grid-template-columns:126px minmax(0,1fr);gap:15px;padding:19px 0;border-bottom:1px solid var(--line);align-items:start;min-width:0}.archive-item[hidden]{display:none}.archive-img{width:126px;aspect-ratio:4/3;object-fit:cover;border-radius:4px;display:block;background:#e1e9e3}.archive-placeholder{display:grid;place-items:center;color:var(--green);font-weight:750;font-size:16px;letter-spacing:.06em;background:linear-gradient(135deg,#dcece3,#f1f3eb)}.archive-item time{color:#60746a;font-size:11px;display:block;letter-spacing:.025em;margin-bottom:5px}.archive-item h2{font-size:17px;line-height:1.3;letter-spacing:-.018em;margin:0 0 6px;font-weight:700;overflow-wrap:anywhere}.archive-item p{margin:0;font-size:13px;line-height:1.45;color:#52635d;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.archive-read{display:inline-block;font-size:11px;font-weight:700;color:var(--green);margin-top:7px}.archive-item:hover h2{color:var(--green)}.archive-bottom{display:flex;align-items:center;justify-content:space-between;padding-top:23px;gap:15px}.archive-count{font-size:12px;color:#60746a}.archive-empty{padding:24px 0;font-size:14px}.post-date{font-size:12px;color:#60746a;margin:-12px 0 25px}.post-back{display:inline-block;margin:0 0 22px;font-size:13px;color:var(--green);font-weight:650}\n@media(max-width:900px){.archive-grid{grid-template-columns:1fr;gap:0}.archive-item{grid-template-columns:110px minmax(0,1fr);gap:14px}.archive-img{width:110px}}\n@media(max-width:560px){.news-heading{flex-direction:column;align-items:stretch;gap:18px;padding-bottom:16px}.news-page{padding-top:20px;padding-bottom:40px}.archive-item{grid-template-columns:94px minmax(0,1fr);gap:12px;padding:15px 0}.archive-img{width:94px}.archive-item h2{font-size:15px}.archive-item p{font-size:12px}.archive-bottom{align-items:flex-start;flex-direction:column}}\n")
head.style.append("\n/* Consistent club editorial styling on compact content and news pages. */\n.subpage,.news-page{max-width:1350px;padding-left:clamp(20px,4vw,64px);padding-right:clamp(20px,4vw,64px)}\n.breadcrumbs{font-size:12px;color:#596b66;margin:0 0 17px}.pagetitle{font-size:clamp(30px,3.8vw,46px);letter-spacing:-.045em;border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:28px;position:relative}.pagetitle:after{content:'';position:absolute;bottom:-1px;left:0;width:58px;height:4px;background:var(--green)}.content h2{color:var(--deep);font-weight:730}.content h3{color:var(--deep)}.section-nav{border-top:4px solid var(--green);background:#eeeee5;padding:17px 18px}.section-nav h2{color:var(--deep);font-size:11px;letter-spacing:.13em}.section-nav a{line-height:1.45;font-weight:550;font-size:13px}.section-nav a:last-child{border:0}.content th{background:#e2ebe2}.content img{max-height:380px}.source-note{font-size:12px}\n.news-heading{position:relative;overflow:hidden;background:var(--deep);color:#fff;margin:0 0 18px;padding:23px 26px;border:0;align-items:flex-end}.news-heading:after{content:'';position:absolute;right:32%;top:-85px;width:180px;height:260px;transform:rotate(-15deg);border:1px solid #ffffff15;background:linear-gradient(90deg,transparent 49.5%,#ffffff15 49.5% 50.5%,transparent 50.5%);pointer-events:none}.news-heading>div,.news-search{position:relative;z-index:1}.news-kicker{color:var(--yellow);font-size:10px}.news-heading h1{font-size:clamp(28px,3.2vw,40px);margin:7px 0 4px;line-height:1.1}.news-heading p{color:#d5e4dc;font-size:13px}.news-search{font-size:11px;color:#e4ede8;min-width:220px}.news-search input{border-radius:0;border:1px solid #ffffff60;background:#ffffff0e;color:#fff;padding:9px 11px}.news-search input::placeholder{color:#c6d9d3}.archive-grid{gap:0 34px}.archive-item{grid-template-columns:112px minmax(0,1fr);gap:14px;padding:15px 0;align-items:start}.archive-img{width:112px;aspect-ratio:4/3;object-fit:cover;border-radius:0}.archive-placeholder{background:var(--deep);color:var(--yellow);font-weight:800}.archive-item h2{font-size:16px;line-height:1.28;margin:0 0 5px}.archive-item time{color:#526a61;font-size:11px;font-weight:650;margin-bottom:3px}.archive-item p{font-size:12px;line-height:1.45}.archive-read{margin-top:5px;font-size:11px}.archive-bottom{padding:18px 0}.archive-item:hover .archive-img{filter:saturate(1.13)}\n@media(max-width:900px){.archive-grid{grid-template-columns:1fr}.archive-item{grid-template-columns:105px minmax(0,1fr)}.archive-img{width:105px}}\n@media(max-width:560px){.news-heading{padding:18px;gap:14px}.news-search{min-width:0}.archive-item{grid-template-columns:90px minmax(0,1fr);gap:12px}.archive-img{width:90px}.archive-item h2{font-size:15px}.archive-item p{font-size:12px}}\n")
head.style.append("\n/* Carry the new graphic identity into the interior without oversized headlines. */\n.subpage,.news-page{max-width:1800px;padding-left:var(--gutter);padding-right:var(--gutter)}\n.pagetitle{border-bottom:1px solid var(--ink);font-size:clamp(29px,3.2vw,43px);padding-bottom:17px}\n.pagetitle:after{width:48px;height:4px;background:var(--yellow)}\n.section-nav{background:transparent;border-top:1px solid var(--ink);padding:13px 0}\n.section-nav h2{color:var(--green)}.section-nav a{font-size:14px}\n.news-heading{background:transparent;color:var(--ink);border-bottom:1px solid var(--ink);padding:0 0 20px;align-items:flex-end;margin-bottom:0}\n.news-heading:after{display:none}.news-kicker{color:var(--green)}\n.news-heading h1{font-size:clamp(30px,3.5vw,43px);font-weight:780}.news-heading p{color:var(--muted)}\n.news-search{color:var(--ink);font-size:12px}.news-search input{border:1px solid var(--ink);background:transparent;color:var(--ink);padding:9px 11px}.news-search input::placeholder{color:var(--muted)}\n.archive-grid{gap:0 32px}.archive-item{padding:18px 0;grid-template-columns:104px minmax(0,1fr);gap:14px}.archive-img{width:104px}.archive-item h2{font-size:16px}.archive-item time{color:var(--green)}.archive-read{color:var(--green)}\n@media(max-width:900px){.archive-grid{grid-template-columns:1fr}}\n@media(max-width:560px){.news-heading{padding:0 0 16px}.archive-item{grid-template-columns:88px minmax(0,1fr);gap:12px;padding:14px 0}.archive-img{width:88px}.archive-item h2{font-size:15px}}\n")
head.style.append("\n/* Individual club pages: photography and service content instead of imported theme blocks. */\n.detail-page{max-width:1400px;padding-top:24px;padding-bottom:64px}.detail-page .breadcrumbs{margin-bottom:20px;display:flex;align-items:center;gap:8px}.detail-mast{background:#edf4ee;display:grid;grid-template-columns:1fr;align-items:stretch;margin-bottom:30px;border-left:4px solid var(--green);overflow:hidden}.detail-mast.has-photo{grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr);min-height:220px}.detail-mast-copy{padding:clamp(23px,3vw,39px);display:flex;flex-direction:column;justify-content:center;align-items:flex-start}.detail-kicker{display:flex;align-items:center;gap:8px;font-size:11px;letter-spacing:.13em;text-transform:uppercase;font-weight:750;color:var(--green);line-height:1.4;margin-bottom:10px}.detail-kicker:before{content:'';height:3px;width:19px;background:var(--yellow)}.detail-mast h1,.article-heading h1{font-size:clamp(29px,3.8vw,48px);font-weight:770;letter-spacing:-.043em;line-height:1.12;margin:0;color:var(--ink)}.detail-mast p{font-size:15px;line-height:1.55;color:#466058;max-width:510px;margin:12px 0 0}.detail-photo{width:100%;height:100%;min-height:225px;max-height:300px;object-fit:cover;display:block}.detail-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:20px}.detail-action{background:var(--green);color:white;padding:10px 14px;display:inline-flex;align-items:center;gap:13px;font-size:13px;font-weight:700;border-radius:4px;border:1px solid var(--green);line-height:1.35}.detail-action:hover{background:#074846}.detail-action.outline{color:var(--green);background:transparent}.detail-action.outline:hover{background:#dcece3}.detail-action span{font-size:16px}.detail-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-bottom:1px solid var(--line);margin:0 0 32px;padding:0 0 24px}.detail-metrics>div{padding:0 24px;border-right:1px solid var(--line)}.detail-metrics>div:first-child{padding-left:0}.detail-metrics>div:last-child{border:0}.detail-metrics strong{font-size:clamp(25px,3.6vw,43px);line-height:1.15;display:block;font-weight:800;letter-spacing:-.04em;color:var(--green)}.detail-metrics span{display:block;color:var(--muted);font-size:12px;margin-top:5px}.detail-section{margin:0 0 32px}.detail-section h2,.people-section h2{font-size:clamp(23px,2.4vw,31px);line-height:1.22;letter-spacing:-.035em;color:var(--ink);margin:0 0 15px}.detail-section>p{max-width:770px;font-size:15px;line-height:1.65;color:var(--muted);margin:0 0 20px}.topic-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px 25px}.topic-link{min-width:0;display:grid;grid-template-columns:1fr;border-bottom:1px solid var(--line);padding:17px 0;color:var(--ink);transition:color .15s,background .15s}.topic-link.with-photo{grid-template-columns:minmax(120px,38%) minmax(0,1fr);align-items:stretch;padding:0;background:#f3f6f2;border-bottom:0}.topic-link.with-photo img{width:100%;height:100%;min-height:112px;max-height:145px;object-fit:cover}.topic-copy{position:relative;padding-right:24px}.with-photo .topic-copy{padding:15px 30px 15px 17px}.topic-copy h3{margin:0 0 5px;font-size:17px;line-height:1.3;letter-spacing:-.015em}.topic-copy p{margin:0;font-size:13px;color:var(--muted);line-height:1.45}.topic-copy span{position:absolute;right:3px;top:2px;color:var(--green);font-size:20px}.with-photo .topic-copy span{right:11px;top:13px}.topic-link:hover{color:var(--green)}.topic-link.with-photo:hover{background:#e5eee6}.detail-textlink{display:inline-block;color:var(--green);font-size:13px;font-weight:700;margin:14px 0 0;text-decoration:underline;text-underline-offset:4px}.detail-note{margin-top:22px!important;font-size:13px!important}.detail-split{display:grid;grid-template-columns:1.2fr 1fr;gap:35px;align-items:start}.detail-split p{color:var(--muted);font-size:15px}.detail-callout{padding:21px 23px;background:#edf4ee;border-top:3px solid var(--green)}.detail-callout h3{font-size:19px;margin:0 0 6px}.detail-callout p{font-size:14px;margin:0 0 14px}.membership-notice{margin:0 0 27px;background:#fbf6df;border-left:4px solid #e3c039;padding:20px 24px}.membership-notice .detail-kicker{color:#655300;margin-bottom:8px}.membership-notice h2{margin:0 0 9px;font-size:23px;line-height:1.2}.membership-notice p{margin:0;font-size:15px;max-width:750px;color:#514b32}.people-section{margin-bottom:32px}.people-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px 25px}.person{display:grid;grid-template-columns:84px minmax(0,1fr);align-items:center;gap:15px;min-height:115px;padding:12px 0;border-bottom:1px solid var(--line)}.person img,.person-placeholder{width:84px;height:100px;object-fit:cover;object-position:center 25%;display:block;border-radius:3px;background:#e7efe7}.person-placeholder{display:grid;place-items:center;color:var(--green);font-weight:750}.person h3{font-size:16px;line-height:1.25;margin:0 0 5px;letter-spacing:-.01em}.person p,.person a{margin:0;display:block;font-size:12px;line-height:1.5;overflow-wrap:anywhere;color:var(--muted)}.person a{color:var(--green);text-decoration:underline}.team-panels{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px 28px}.team-panel{min-width:0;padding:0 0 20px;border-bottom:1px solid var(--line)}.team-panel h2{font-size:23px;letter-spacing:-.03em;margin:0 0 12px;color:var(--deep)}.team-panel img{width:100%;height:auto;max-height:300px;object-fit:contain;display:block;background:#f5f7f3}.team-panel p{font-size:14px}.article-heading{max-width:930px;margin:0 auto 28px}.article-heading .detail-textlink{margin:0 0 15px}.article-date{color:var(--green);font-size:12px;font-weight:650;margin:0 0 9px}.article-reading{max-width:930px;margin:auto}.article-reading .content{font-size:16px;line-height:1.75}.article-reading .post-back,.article-reading .post-date{display:none}.detail-page .subgrid{gap:clamp(28px,5vw,70px)}.detail-page .subgrid.solo{grid-template-columns:minmax(0,880px)}.detail-page .content h2{font-size:clamp(22px,2.2vw,29px);margin:28px 0 12px}.detail-page .content h2:first-child{margin-top:0}.detail-page .content h3{font-size:20px}.detail-page .content img.editorial-image{border-radius:3px;max-height:370px}.detail-page .section-nav{border-top:3px solid var(--green);background:#f1f5ef;padding:18px}.detail-page .section-nav h2{font-size:11px}.detail-page .section-nav a{font-size:13px;gap:8px}.detail-page .source-note{margin-top:30px}.download-link{display:inline-block;padding:8px 12px;background:#edf4ee;font-size:13px;font-weight:650;border-left:3px solid var(--green);text-decoration:none!important}.download-link:before{content:'↓ ';font-weight:800}.detail-page .content table{font-size:14px}.detail-page .content th{background:#e3ede4}.detail-page .content tbody tr:nth-child(even){background:#f5f8f4}\n@media(max-width:1000px){.people-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}\n@media(max-width:720px){.detail-page{padding-top:18px;padding-bottom:40px}.detail-mast{margin-bottom:24px}.detail-mast.has-photo{grid-template-columns:1fr;min-height:0}.detail-mast-copy{padding:22px}.detail-photo{height:200px;min-height:0;max-height:220px}.detail-mast h1,.article-heading h1{font-size:32px}.detail-mast p{font-size:14px}.detail-metrics{padding-bottom:18px;margin-bottom:25px}.detail-metrics>div{padding:0 12px}.detail-metrics span{font-size:11px}.topic-grid,.detail-split,.team-panels{grid-template-columns:1fr;gap:15px}.topic-link.with-photo{grid-template-columns:125px minmax(0,1fr)}.topic-link.with-photo img{min-height:102px;height:100%;max-height:125px}.people-grid{gap:10px;grid-template-columns:1fr}.person{min-height:100px}.person img,.person-placeholder{width:74px;height:87px}.person{grid-template-columns:74px 1fr}.membership-notice{padding:17px 19px}.membership-notice h2{font-size:21px}.detail-page .section-nav{margin-top:0}.article-heading{margin-bottom:23px}.article-reading .content{font-size:15px}}\n")
head.style.append(".archive-controls{display:flex;align-items:end;gap:12px}.archive-controls select{font:inherit;padding:9px 10px;border:1px solid var(--ink);background:white;color:var(--ink)}.archive-controls label:last-child{min-width:105px}#newsMore[hidden]{display:none}@media(max-width:600px){.archive-controls{flex-wrap:wrap}.archive-controls label:first-child{flex:1;min-width:160px}}")
for link in head.select('link[href]'):
    if link['href'].startswith('media/'): link['href']='/'+link['href']
menu_js="""const menu=document.querySelector('.menu'),nav=document.querySelector('#nav');menu.onclick=()=>{const open=nav.classList.toggle('open');menu.setAttribute('aria-expanded',String(open))};document.addEventListener('keydown',e=>{if(e.key==='Escape'){nav.classList.remove('open');menu.setAttribute('aria-expanded','false')}});"""+NAV_JS

# Editorial templates for the club's different content types.
def E(value): return html.escape(str(value),quote=True)
def href_for(p):
    return p if p in local or p in ('/matchcenter/','/sponsoren/') else (urljoin(BASE,p) if p.startswith('/') else p)
def image_url(im, url=BASE):
    if not im: return ''
    src=im.get('data-src') or im.get('data-lazy-src') or im.get('src','')
    full=urljoin(url,src)
    return full if src and urlsplit(full).scheme in ('https','http') else ''
def photo(src,alt='',cls=''):
    return '<img class="'+E(cls)+'" src="'+E(src)+'" alt="'+E(alt)+'" loading="lazy" decoding="async">' if src else ''
def first_photo(node,url=BASE):
    if not node: return ''
    for im in node.find_all('img'):
        src=image_url(im,url)
        if src and not re.search(r'logo|icon|avatar|placeholder|cropped-logo',src,re.I):
            return src
    return ''
def matching_link(node,label):
    wanted=label.casefold()
    if not node: return ''
    for a in node.find_all('a',href=True):
        if ' '.join(a.stripped_strings).casefold()==wanted:
            return route(a['href']) or urljoin(BASE,a['href'])
    return ''
def preceding_photo(node,label,url=BASE):
    if not node: return ''
    for a in node.find_all('a',href=True):
        if ' '.join(a.stripped_strings).casefold()==label.casefold():
            im=a.find('img') or a.find_previous('img')
            return image_url(im,url)
    return ''
def link_button(label,target,secondary=False):
    return '<a class="detail-action'+(' outline' if secondary else '')+'" href="'+E(href_for(target))+'">'+E(label)+' <span aria-hidden="true">↗</span></a>'
def section_links(node, entries, url=BASE, pictures=False):
    tiles=[]
    for label,target,desc in entries:
        target=matching_link(node,label) or target
        if not target: continue
        img=preceding_photo(node,label,url) if pictures else ''
        tiles.append('<a class="topic-link'+(' with-photo' if img else '')+'" href="'+E(href_for(target))+'">'+photo(img,'')+'<div class="topic-copy"><h3>'+E(label)+'</h3><p>'+E(desc)+'</p><span aria-hidden="true">→</span></div></a>')
    return '<div class="topic-grid">'+''.join(tiles)+'</div>'
def masthead(title,kicker,description='',image='',actions=''):
    return '<div class="detail-mast'+(' has-photo' if image else '')+'"><div class="detail-mast-copy"><div class="detail-kicker">'+E(kicker)+'</div><h1>'+E(title)+'</h1>'+('<p>'+E(description)+'</p>' if description else '')+(('<div class="detail-actions">'+actions+'</div>') if actions else '')+'</div>'+photo(image,'','detail-photo')+'</div>'
def metrics(items):
    return '<div class="detail-metrics">'+''.join('<div><strong>'+E(v)+'</strong><span>'+E(l)+'</span></div>' for v,l in items)+'</div>'
def article_body(raw,title):
    clean=BeautifulSoup(raw,'html.parser')
    # Remove empty theme markup and the redundant page heading.
    for el in list(clean.find_all(['h2','h3','h4','h5','h6','p','span'])):
        if el.name is None: continue
        text=' '.join(el.stripped_strings)
        if not text and not el.find(['img','a']): el.decompose(); continue
        if el.name.startswith('h') and text.casefold()==title.strip().casefold(): el.decompose()
    for im in list(clean.find_all('img')):
        if re.search(r'(?:cropped-)?logo[^/]*\.(?:png|jpg|webp)',im.get('src',''),re.I):
            # Logos in people profiles are handled separately; keep original content here.
            continue
        im['class']=['editorial-image']
    for a in clean.find_all('a',href=True):
        if re.search(r'\.pdf(?:$|\?)',a['href'],re.I): a['class']=['download-link']
    for t in clean.find_all('table'):
        t['class']=['data-table']
    # Preserve the imported text and links; drop only empty wrappers.
    for el in reversed(clean.find_all(['div','section'])):
        if not el.get_text(strip=True) and not el.find(['img','a','table','hr']): el.decompose()
    return clean
def people_profiles(clean, default_group='Vorstand'):
    # The existing people pages use image, name (h4), role and contact in reading order.
    # Do not guess identity from photos: only use the image directly preceding the named entry.
    headings=[h for h in clean.find_all('h4') if len(h.get_text(' ',strip=True).split())>=2]
    if len(headings)<4: return ''
    groups=[]; current=None; cards=[]
    for h in headings:
        group=h.find_previous('h2')
        group_name=group.get_text(' ',strip=True) if group else default_group
        if group_name!=current:
            if cards: groups.append((current,cards))
            current=group_name;cards=[]
        im=h.find_previous('img')
        previous_name=h.find_previous('h4')
        picture=image_url(im) if im and im.find_previous('h4') is previous_name else ''
        name=h.get_text(' ',strip=True)
        detail=[]; seen=set()
        for nxt in h.next_elements:
            if getattr(nxt,'name',None) in ('h2','h4','img'): break
            if getattr(nxt,'name',None) is not None or not isinstance(nxt,str): continue
            if nxt.parent is h or h in nxt.parents: continue
            val=' '.join(nxt.split())
            if val and val not in seen and len(val)<240:
                seen.add(val);detail.append(val)
        lines=[]
        for val in detail:
            mail=re.fullmatch(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}',val)
            telephone=re.fullmatch(r'(?:Tel:\s*)?\+?\d[\d /()-]{5,}',val,re.I)
            lines.append('<a href="mailto:'+E(val)+'">'+E(val)+'</a>' if mail else '<a href="tel:'+E(re.sub(r'[^+\d]','',val))+'">'+E(val)+'</a>' if telephone else '<p>'+E(val)+'</p>')
        cards.append('<div class="person">'+(photo(picture,'') if picture else '<span class="person-placeholder" aria-hidden="true">NTC</span>')+'<div><h3>'+E(name)+'</h3>'+''.join(lines)+'</div></div>')
    if cards: groups.append((current,cards))
    return ''.join('<section class="people-section"><h2>'+E(g)+'</h2><div class="people-grid">'+''.join(cs)+'</div></section>' for g,cs in groups)
def team_panels(clean):
    headings=[h for h in clean.find_all('h3') if h.get_text(strip=True)]
    if not headings: return ''
    blocks=[]
    for h in headings:
        name=h.get_text(' ',strip=True)
        fragments=[]
        for nxt in h.next_elements:
            if not getattr(nxt,'name',None): continue
            if nxt.name in ('h2','h3'): break
            if nxt.name=='img':
                fragments.append(photo(image_url(nxt),nxt.get('alt','')))
            elif nxt.name in ('p','ul','ol','table') and nxt.get_text(strip=True):
                if nxt.find_parent(['p','ul','ol','table']) is None:
                    fragments.append(str(nxt))
        blocks.append('<section class="team-panel"><h2>'+E(name)+'</h2>'+''.join(fragments)+'<a class="detail-textlink" href="/matchcenter/">Spielplan &amp; Ergebnisse im Matchcenter →</a></section>')
    return '<div class="team-panels">'+''.join(blocks)+'</div>'
def layout_detail(path,title,node,url,body,sidebar,original):
    clean=article_body(body,title)
    area=title
    # Match the actual menu grouping rather than adding the same photo header everywhere.
    for group, members in groups.items():
        if path in members and group: area=group;break
    crumb='<div class="breadcrumbs"><a href="/">Startseite</a> <span aria-hidden="true">›</span> '+E(title)+'</div>'
    for a in clean.find_all('a',href=True):
        if a['href'].startswith('/'): a['href']=href_for(a['href'])
    # Main landing pages receive purpose-built overview layouts.
    if path in ('/ueber-uns/','/verein/'):
        top=masthead('Unser Verein','Neuenhagener TC 93','Tennis, Gemeinschaft und Vereinsleben seit 1993.','/media/anlage.jpg',link_button('Vorstand','/vorstand/')+link_button('Mitgliedschaft','/mitglieder/',True))
        stats=metrics([('1993','Gegründet'),('7','Sandplätze'),('2','Hallenplätze')])
        links=section_links(node,[('Vorstand','/vorstand/','Ansprechpartner und Verantwortliche'),('Trainer','/trainer/','Training auf und neben dem Platz'),('Ehrenmitglieder','/ehrenmitglieder/','Engagement für unseren Verein'),('Tennishalle','/tennishalle/','Auch im Winter Tennis spielen'),('Sponsoring','/sponsoren/','Unsere Partner kennenlernen'),('Gastronomie','https://due-fratelli-neuenhagen.de/','Trattoria Due Fratelli auf der Anlage')],url)
        main='<section class="detail-section"><h2>Ein Club, viele Möglichkeiten</h2><p>Auf unseren Sandplätzen und in der Tennishalle treffen sich Freizeit- und Mannschaftsspieler. Training, Turniere, Jugendarbeit und die gemeinsame Zeit auf der Anlage gehören zum Vereinsleben.</p>'+links+'</section>'
        return crumb+top+stats+main+'<section class="detail-section"><h2>Vereinsinformationen</h2>'+section_links(node,[('Satzung','/satzung/','Grundlagen unseres Vereins'),('NTC-Informationen',matching_link(home,'NTC-Informationen'),'Wissenswertes für Mitglieder'),('Platzordnung','/platzordnung/','Regeln auf der Anlage'),('Arbeitskarte',matching_link(home,'Arbeitskarte'),'Vereinsarbeit organisieren')],url)+'</section>'+original
    if path=='/mannschaften/':
        top=masthead('Unsere Mannschaften','Sport & Wettkampf','Von der Jugend bis zu den Seniorenteams – alle Mannschaftsbereiche auf einen Blick.','',link_button('Matchcenter','/matchcenter/'))
        links=section_links(node,[('Damen','/damen/','Damenmannschaften'),('Herren','/herren/','Herrenmannschaften'),('Seniorinnen','/seniorinnen/','Damen in den Altersklassen'),('Senioren','/senioren/','Herren in den Altersklassen')],url,True)
        return crumb+top+'<section class="detail-section"><h2>Teams im Überblick</h2>'+links+'<a class="detail-textlink" href="'+E(href_for('/jugendteams/'))+'">Zu den Jugendteams →</a></section>'+original
    if path=='/jugend/':
        top=masthead('Jugend & Nachwuchs','Tennis von Anfang an','Training, Mannschaftssport, Turniere und gemeinsame Erlebnisse für Kinder und Jugendliche.',first_photo(node,url),link_button('Trainingskonzept','/trainingskonzept/'))
        links=section_links(node,[('Trainingskonzept','/trainingskonzept/','Vom Minitennis bis zum Mannschaftstraining'),('Jugendteams','/jugendteams/','Gemeinsam im Wettkampf'),('Jugend-Angebote','/jugend-angebote/','Camps, Turniere und weitere Aktivitäten'),('Förderungskonzept','/foerderungskonzept/','Sportliche Entwicklung unterstützen')],url,True)
        return crumb+top+'<section class="detail-section"><h2>Unser Angebot</h2>'+links+'<p class="detail-note">Die Kinder- und Jugendarbeit wird durch die Gemeinde Neuenhagen bei Berlin gefördert.</p></section>'+original
    if path=='/tennishalle/':
        top=masthead('Unsere Tennishalle','Tennis das ganze Jahr','Zwei Plätze mit sandplatzähnlichem Spielgefühl – auch in der Wintersaison.','/media/halle.jpg',link_button('Hallenplatz buchen','https://ntc93v8.ebusy.de/court-module/3076')+link_button('Halleninformationen','https://ntc93app.de/halle',True))
        return crumb+top+metrics([('2','Hallenplätze'),('2023','Eröffnet'),('RedCourt','Spielbelag')])+'<section class="detail-section detail-split"><div><h2>Ganzjährig auf dem Platz</h2><p>Die vereinseigene Halle ergänzt unsere Außenanlage. Freie Plätze und Buchungskonditionen sind direkt im Buchungssystem verfügbar.</p></div><div class="detail-callout"><h3>Dein nächstes Hallenspiel</h3><p>Verfügbare Zeiten prüfen und online buchen.</p>'+link_button('Zur Hallenbuchung','https://ntc93v8.ebusy.de/court-module/3076')+'</div></section>'+original
    if path=='/mitglieder/':
        top=masthead('Mitgliedschaft','Vereinsservice','Informationen zur Mitgliedschaft, Beiträgen und zum Einstieg in den NTC.','')
        notice='<aside class="membership-notice"><div class="detail-kicker">Wichtiger Hinweis</div><h2>Vorübergehender Aufnahmestopp</h2><p>Aufgrund der derzeitigen Auslastung können wir aktuell keine neuen Mitglieder regulär aufnehmen. Sobald eine Aufnahme wieder möglich ist, informiert der Verein.</p><a class="detail-textlink" href="mailto:info@ntc93.de">Kontakt zum Verein →</a></aside>'
        links=section_links(node,[('Beiträge','/beitraege/','Informationen zu den Mitgliedsbeiträgen'),('Satzung','/satzung/','Grundlagen der Mitgliedschaft'),('Persönlicher Bereich',matching_link(home,'Persönlicher Bereich') or 'https://ntc93app.de/','Digitale Vereinsservices'),('Platzordnung','/platzordnung/','Regeln für die Nutzung unserer Anlage')],url)
        # Keep the original membership details accessible below the important notice.
        return crumb+top+notice+'<section class="detail-section"><h2>Mitgliederservice</h2>'+links+'</section><div class="subgrid'+('' if sidebar else ' solo')+'"><article class="content">'+str(clean)+original+'</article>'+sidebar+'</div>'
    if path in ('/vorstand/','/trainer/'):
        is_board=path=='/vorstand/'
        top=masthead('Vorstand & Beirat' if is_board else 'Unser Trainerteam','Menschen im Verein','Die Ansprechpartner für den Vereinsalltag und die sportliche Entwicklung.' if is_board else 'Training für unterschiedliche Altersklassen und Spielstärken.')
        profiles=people_profiles(clean,'Vorstand' if is_board else 'Trainer')
        if profiles: return crumb+top+profiles+original
    if path in ('/damen/','/herren/','/seniorinnen/','/senioren/'):
        top=masthead(title.title(),'Unsere Mannschaften','Mannschaftsvorstellungen und aktuelle Begegnungen.',actions=link_button('Matchcenter','/matchcenter/'))
        panels=team_panels(clean)
        if panels: return crumb+top+panels+original
    if path in postmeta:
        date,img,_=postmeta[path]
        top='<div class="article-heading"><a class="detail-textlink" href="/news/">← Alle Nachrichten</a>'+('<p class="article-date">'+E(date)+'</p>' if date else '')+'<h1>'+E(title)+'</h1></div>'
        return crumb+top+'<div class="article-reading"><article class="content">'+str(clean)+original+'</article></div>'
    # Information and service pages have a quiet title and readable content, not a generic giant hero.
    top=masthead(title,area if area.casefold()!=title.casefold() else 'Neuenhagener TC 93')
    return crumb+top+'<div class="subgrid'+('' if sidebar else ' solo')+'"><article class="content">'+str(clean)+original+'</article>'+sidebar+'</div>'

for path,(title,node,url,err) in loaded.items():
    if node is None: print('SKIPPED',path,err); continue
    if path=='/news/': continue
    body=sanitize(node,url,local)
    sidebar=related(path)
    if path in postmeta:
        sidebar=''
        date=postmeta[path][0] or next((d for p,t,d in NEWS if p==path),'')
        body='<a class="post-back" href="/news/">← Zur Nachrichtenübersicht</a>' + ('<p class="post-date">'+html.escape(date)+'</p>' if date else '') + body
    original=''
    h=copy.deepcopy(head);h.title.string=title+' | NTC 93'
    page_content=layout_detail(path,title,node,url,body,sidebar,original)
    markup='<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="subpage detail-page">'+page_content+'</main>'+footer+'<script>'+menu_js+'</script></body></html>'
    out=ROOT/path.strip('/')/'index.html';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(markup,encoding='utf-8')

# The old page renders desktop and mobile archives in parallel. Use one curated, deduplicated index.
def esc(value): return html.escape(str(value),quote=True)
items=[]
def date_key(row):
    d=postmeta.get(row[0],('','',''))[0] or row[2]
    try:return datetime.strptime(d,'%d.%m.%Y')
    except (ValueError,TypeError):return datetime.min
for path,title,fallback_date in sorted(NEWS,key=date_key,reverse=True):
    if path not in local: continue
    title=loaded[path][0]
    date,image,teaser=postmeta.get(path,('','',''))
    date=date or fallback_date
    target=path
    thumb=('<img class="archive-img" src="'+esc(image)+'" alt="" loading="lazy" decoding="async">') if image else '<span class="archive-img archive-placeholder" aria-hidden="true">NTC</span>'
    items.append('<a class="archive-item" href="'+esc(target)+'">'+thumb+'<div>'+('<time>'+esc(date)+'</time>' if date else '')+'<h2>'+esc(title)+'</h2>'+('<p>'+esc(teaser)+'</p>' if teaser else '')+'<span class="archive-read">Weiterlesen →</span></div></a>')
h=copy.deepcopy(head);h.title.string='Aktuelles | NTC 93'
filter_js="""(()=>{const search=document.querySelector('#newsSearch'),year=document.querySelector('#newsYear'),count=document.querySelector('#newsCount'),empty=document.querySelector('#newsEmpty'),more=document.querySelector('#newsMore'),grid=document.querySelector('.archive-grid');let limit=24;function refreshYears(){const current=year.value;const years=[...new Set([...grid.children].map(x=>(x.querySelector('time')?.textContent||'').match(/\\d{4}$/)?.[0]).filter(Boolean))].sort().reverse();year.replaceChildren(new Option('Alle Jahre',''),...years.map(y=>new Option(y,y)));if(years.includes(current))year.value=current}function render(){const q=search.value.toLocaleLowerCase('de').trim(),y=year.value;let found=0,visible=0;for(const item of grid.children){const match=item.textContent.toLocaleLowerCase('de').includes(q)&&(!y||(item.querySelector('time')?.textContent||'').endsWith(y));if(match)found++;item.hidden=!match||found>limit;if(!item.hidden)visible++}count.textContent=visible+' von '+found+' Meldungen';empty.hidden=found!==0;more.hidden=visible>=found}search.addEventListener('input',()=>{limit=24;render()});year.addEventListener('change',()=>{limit=24;render()});more.addEventListener('click',()=>{limit+=24;render()});document.addEventListener('ntc-news-updated',()=>{refreshYears();render()});refreshYears();render()})();"""
news_markup='<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="news-page"><div class="breadcrumbs"><a href="/">Startseite</a> / Aktuelles</div><div class="news-heading"><div><div class="news-kicker">Vereinsleben &amp; Sport</div><h1>Aktuelles</h1><p>Nachrichten und Berichte rund um den NTC 93.</p></div><div class="archive-controls"><label class="news-search" for="newsSearch">Meldungen durchsuchen<input id="newsSearch" type="search" placeholder="Suchbegriff eingeben …"></label><label class="news-search" for="newsYear">Jahr<select id="newsYear"><option value="">Alle Jahre</option></select></label></div></div><div class="archive-grid">'+''.join(items)+'</div><p id="newsEmpty" class="archive-empty" hidden>Keine passenden Meldungen gefunden.</p><div class="archive-bottom"><span id="newsCount" class="archive-count" aria-live="polite">'+str(len(items))+' Meldungen im Archiv</span><button class="detail-action" id="newsMore" type="button" hidden>Weitere Meldungen laden ↓</button></div></main>'+footer+'<script>'+menu_js+filter_js+'</script></body></html>'
out=ROOT/'news/index.html';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(news_markup,encoding='utf-8')


# Independent matchcenter: same navigation, filters and full public fixture list.
h=copy.deepcopy(head);h.title.string='Matchcenter | NTC 93'
match_body='<div class="matchcenter match-full" data-matchcenter="full"><div class="match-shell"><div class="match-filters"><button type="button" data-mode="all" aria-pressed="true">Alle Begegnungen</button><button type="button" data-mode="home" aria-pressed="false">Nur Heimspiele</button><label>Mannschaft <select data-team><option value="">Alle Mannschaften</option></select></label></div><div class="match-columns"><div class="match-column"><h3>Kommende Punktspiele</h3><div data-fixtures><p class="match-empty">Spielplan wird geladen …</p></div></div><div class="match-column"><h3>Ergebnisse</h3><div data-results><p class="match-empty">Ergebnisse werden geladen …</p></div></div></div><div class="match-foot"><span data-updated aria-live="polite">Quelle: nuLiga / TVBB</span><a href="https://tvbb.liga.nu/cgi-bin/WebObjects/nuLigaTENDE.woa/wa/clubMeetings?club=36381">Original-Spielplan ↗</a></div></div></div>'
match_markup='<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="subpage"><div class="breadcrumbs"><a href="/">Startseite</a> / Matchcenter</div><h1 class="pagetitle">Matchcenter</h1>'+match_body+'</main>'+footer+'<script>'+menu_js+'</script><script src="/matchcenter.js" defer></script></body></html>'
out=ROOT/'matchcenter/index.html';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(match_markup,encoding='utf-8')

# Dedicated sponsor page using the shared design.
h=copy.deepcopy(head);h.title.string='Sponsoren & Partner | NTC 93'
sponsor_content='<div class="breadcrumbs"><a href="/">Startseite</a> / Sponsoren</div><h1 class="pagetitle">Sponsoren & Partner</h1><p>Vielen Dank an unsere Partner für ihre Unterstützung des Neuenhagener Tennisclub 93 e. V.</p>'+('<div class="sponsor-grid">'+sponsor_tiles()+'</div>' if SPONSORS else '<p>Die Sponsorenübersicht wird ergänzt.</p>')+'<a class="detail-action" href="'+html.escape(nav_target('Sponsor werden','/sponsor-werden/'),quote=True)+'">Sponsor werden ↗</a>'
out=ROOT/'sponsoren/index.html';out.parent.mkdir(parents=True,exist_ok=True);out.write_text('<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="subpage detail-page">'+sponsor_content+'</main>'+footer+'<script>'+menu_js+'</script></body></html>',encoding='utf-8')

# Dynamic article shell for CMS news, independent of static legacy articles.
h=copy.deepcopy(head);h.title.string='Nachricht | NTC 93'
out=ROOT/'redaktion/index.html';out.parent.mkdir(parents=True,exist_ok=True)
out.write_text('<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="subpage detail-page"><div class="breadcrumbs"><a href="/">Startseite</a> / <a href="/news/">Aktuelles</a></div><article id="cms-article" class="cms-article"><p>Nachricht wird geladen …</p></article></main>'+footer+'<script>'+menu_js+'</script></body></html>',encoding='utf-8')
# Resolve internal routes and copy all linked legacy media after every page has been rendered.
migration=localize(ROOT)
archive_report['discovered']=len(NEWS)
archive_report['imported']=sum(1 for p,_,_ in NEWS if p in local)
archive_report['failed']=[p for p,_,_ in NEWS if p not in local]
report={'sponsor_count':len(SPONSORS),'archive':archive_report,'media_and_links':migration,'imported':sorted(local),'skipped':{p:re.sub(r'https?://[^\s]+','[URL]',err) for p,(_,_,_,err) in loaded.items() if err}}
if archive_report['expected'] and archive_report['imported']<archive_report['expected']:
    print('::warning::Archive incomplete: '+str(archive_report['imported'])+' imported, at least '+str(archive_report['expected'])+' indicated by source')
print('Legacy asset/link migration:',migration['assets_downloaded'],'files;',len(migration['missing_assets']),'missing assets;',len(migration['unresolved_links']),'unresolved references')

(ROOT/'migration-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Imported',len(local),'pages:',', '.join(sorted(local)))
