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


# Recover real WordPress/Elementor images from lazy-load attributes and srcsets.
def valid_photo_url(value,base):
    if not isinstance(value,str) or not value.strip():return ''
    value=value.strip()
    if value.startswith(('data:','blob:','javascript:','#')):return ''
    u=urljoin(base,value)
    p=urlsplit(u)
    if p.scheme not in ('http','https') or not p.hostname:return ''
    if re.search(r'(?:placeholder|blank\.gif|spacer\.gif|transparent\.png|loading\.gif|dummy-image)',p.path,re.I):return ''
    if not re.search(r'\.(?:jpe?g|png|webp|gif|avif)(?:$|/)',p.path,re.I):return ''
    return u
def photo_key(url):
    p=urlsplit(url)
    return (p.hostname or '',re.sub(r'-(?:\d+x\d+)(?=\.[^.]+$)','',unquote(p.path)).casefold())
def actual_image(im,base):
    if not im:return ''
    choices=[]
    for attr in ('data-srcset','data-lazy-srcset','srcset'):
        for item in (im.get(attr) or '').split(','):
            parts=item.strip().split()
            if not parts:continue
            u=valid_photo_url(parts[0],base)
            if u:
                size=re.match(r'(\d+)w$',parts[-1])
                choices.append((int(size.group(1)) if size else 0,u))
    if choices:
        suitable=[x for x in choices if 900<=x[0]<=1800]
        if suitable:return max(suitable)[1]
        return max(choices)[1]
    for attr in ('data-large-file','data-full-url','data-src','data-lazy-src','data-original','data-lazy','src'):
        u=valid_photo_url(im.get(attr),base)
        if u:return u
    return ''
def article_extra_photos(soup,node,base):
    out=[];seen=set()
    def add(src,alt=''):
        u=valid_photo_url(src,base)
        if not u:return
        key=photo_key(u)
        if key in seen:return
        seen.add(key);out.append((u,str(alt or '')))
    # Images embedded as background gallery tiles, slide images or link-only lightboxes.
    for el in node.find_all(True):
        if el.name=='img':add(actual_image(el,base),el.get('alt',''))
        elif el.name=='a' and (el.has_attr('data-elementor-open-lightbox') or el.find('img') or 'gallery' in ' '.join(el.get('class',[]))):
            add(el.get('href'),el.get('aria-label',''))
        for attr in ('data-bg','data-background','data-background-image','data-src'):
            if el.name!='img':add(el.get(attr),el.get('aria-label',''))
        classes=' '.join(el.get('class',[]))
        if re.search(r'gallery|carousel|swiper|slide|image',classes,re.I):
            for m in re.finditer(r'url\(\s*["\']?([^)"\']+)',el.get('style','')):
                add(m.group(1),el.get('aria-label',''))
        settings=el.get('data-settings')
        if not settings:continue
        if not re.search(r'gallery|carousel|slides',classes+' '+el.get('data-widget_type',''),re.I):continue
        try:
            def walk(obj):
                if isinstance(obj,dict):
                    for k,v in obj.items():
                        if k in ('url','image_url') and isinstance(v,str):add(v,obj.get('alt',''))
                        elif isinstance(v,(dict,list)):walk(v)
                elif isinstance(obj,list):
                    for v in obj:walk(v)
            walk(json.loads(settings))
        except (ValueError,TypeError):pass
    return out

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
            src=actual_image(tag,url) or tag.get('data-src') or tag.get('data-lazy-src') or tag.get('src','')
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
postphotos={}
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
            photos=article_extra_photos(soup,node,url)
            # Featured images often live outside the WordPress article content.
            featured=soup.select_one('main .elementor-widget-theme-post-featured-image img, main img.wp-post-image, article img.wp-post-image, .post-thumbnail img, .featured-image img')
            image=actual_image(featured,url)
            if not image:
                meta=soup.select_one('meta[property="og:image"], meta[name="twitter:image"]')
                image=valid_photo_url(meta.get('content',''),url) if meta else ''
            if image and re.search(r'logo|favicon|platzhalter|placeholder',urlsplit(image).path,re.I):image=''
            if not image and photos:image=photos[0][0]
            postphotos[path]=photos
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
local.update(('/news/','/termine/','/sponsoren/','/matchcenter/','/redaktion/','/anfahrt/','/gastronomie/','/mannschaften/','/damen/','/herren/','/seniorinnen/','/senioren/','/jugendteams/','/mixed-doppel/','/mannschaften/team/','/'))
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
    if fallback in ('/matchcenter/','/sponsoren/','/tennishalle/','/anfahrt/','/gastronomie/','/termine/','/mannschaften/','/damen/','/herren/','/seniorinnen/','/senioren/','/jugendteams/','/mixed-doppel/'):
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
    group('Verein',[('Über den NTC',[('Unser Verein','Über uns','/ueber-uns/'),('Vorstand','Vorstand','/vorstand/'),('Trainer','Trainer','/trainer/'),('Ehrenmitglieder','Ehrenmitglieder','/ehrenmitglieder/'),('Gastronomie','Gastronomie','/gastronomie/'),('Anfahrt & Kontakt','Anfahrt','/anfahrt/')]),('Organisation & Partner',[('Sponsoren','Sponsoren','/sponsoren/'),('Sponsor werden','Sponsor werden','/sponsor-werden/'),('Satzung','Satzung',''),('NTC-Informationen','NTC-Informationen',''),('Platzordnung','Platzordnung',''),('Arbeitskarte','Arbeitskarte','')])],True)
    group('Teams',[('',[('Mannschaften im Überblick','Teams','/mannschaften/'),('Damen','Damen','/damen/'),('Herren','Herren','/herren/'),('Seniorinnen','Seniorinnen','/seniorinnen/'),('Senioren','Senioren','/senioren/'),('Jugendteams','Jugendteams','/jugendteams/'),('Mixed & Doppel','Mixed & Doppel','/mixed-doppel/')])])
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
    return '<section class="sponsor-band" aria-labelledby="sponsor-title"><div class="sponsor-head"><div><div class="section-kicker">Gemeinsam für den NTC</div><h2 id="sponsor-title">Unsere Sponsoren & Partner</h2></div><div class="sponsor-head-actions"><div class="sponsor-controls" aria-label="Sponsorenleiste steuern"><button type="button" data-sponsor-prev aria-label="Vorherige Logos" hidden>←</button><button type="button" data-sponsor-pause aria-label="Automatischen Logowechsel pausieren" aria-pressed="false" hidden>Ⅱ</button><button type="button" data-sponsor-next aria-label="Weitere Logos" hidden>→</button></div><a class="sponsor-link" href="/sponsoren/">Alle Sponsoren →</a></div></div>'+('<div class="sponsor-track" tabindex="0" aria-label="Sponsorenlogos, horizontal scrollbar">'+logos+'</div>')+('' if logos else '<p>Wir danken allen Partnern für ihre Unterstützung.</p>')+'</section>'
SPONSOR_CSS="""
.sponsor-band{max-width:1320px;margin:0 auto;padding:24px clamp(20px,5vw,68px) 42px}.sponsor-head{display:flex;align-items:end;justify-content:space-between;gap:12px;margin-bottom:16px}.sponsor-head h2{font-size:clamp(21px,2.4vw,29px);margin:5px 0;color:#183c2b;letter-spacing:-.03em}.sponsor-link{font-weight:650;color:#146143;font-size:13px;white-space:nowrap}.sponsor-track{display:flex;gap:12px;overflow-x:auto;padding:4px 1px 12px;scroll-snap-type:x proximity}.sponsor-logo{flex:0 0 150px;min-width:0;min-height:88px;background:white;border:1px solid #e1e9e2;border-radius:9px;display:grid;place-items:center;padding:15px;scroll-snap-align:start}.sponsor-logo img{width:100%;height:62px;object-fit:contain}.sponsor-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:26px 0 35px}.sponsor-grid .sponsor-logo{min-height:120px}.sponsor-grid .sponsor-logo img{height:83px}@media(max-width:540px){.sponsor-logo{flex-basis:125px;min-height:75px;padding:12px}.sponsor-logo img{height:50px}.sponsor-head{align-items:flex-start;flex-direction:column;gap:4px}}
"""
source.head.style.append(SPONSOR_CSS)

# Use the original drone footage from the club's published article.
# Only a locally stored video is eligible; no third-party player or tracking.
def integrate_drone_hero(source):
    import subprocess, shutil, tempfile
    article='/der-ntc-aus-der-vogelperspektive/'
    output=ROOT/'media/ntc-drohnenflug-hero.mp4'
    poster=ROOT/'media/ntc-drohnenflug-poster.jpg'
    fullvideo=ROOT/'media/ntc-drohnenflug-original.mp4'
    if not (output.is_file() and poster.is_file() and fullvideo.is_file()):
        try:
            page,url=fetch(urljoin(BASE,article))
            candidates=[]
            def add(value):
                if not isinstance(value,str):return
                u=urljoin(url,html.unescape(value).replace('\\/','/'))
                p=urlsplit(u)
                if p.scheme=='https' and p.hostname in HOSTS and re.search(r'\.(mp4|webm|mov|m4v)$',p.path,re.I) and u not in candidates:candidates.append(u)
            main=page.select_one('main, .site-main, article, .entry-content') or page
            for el in main.select('video, video source, a[href], [data-settings], [data-video-url], [data-src]'):
                for attr in ('src','href','data-src','data-video-url','data-video','data-settings'):
                    value=el.get(attr)
                    if not isinstance(value,str):continue
                    add(value)
                    for m in re.finditer(r'https?://[^"\'<>\s]+?\.(?:mp4|webm|mov|m4v)(?:\?[^"\'<>\s]*)?',html.unescape(value).replace('\\/','/'),re.I):add(m.group())
            # Elementor may keep a self-hosted media URL in serialized widget settings.
            if not candidates:
                for m in re.finditer(r'https?://[^"\'<>\s]+?\.(?:mp4|webm|mov|m4v)',html.unescape(str(main)).replace('\\/','/'),re.I):add(m.group())
            if not candidates:raise ValueError('no self-hosted video found in drone article; external embeds are intentionally not autoplayed')
            if not shutil.which('ffmpeg'):raise ValueError('ffmpeg unavailable')
            output.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory() as temp:
                src=Path(temp)/'source-video'
                for candidate in candidates:
                    try:
                        with requests.get(candidate,headers=HEADERS,timeout=(8,45),stream=True) as response:
                            response.raise_for_status()
                            if urlsplit(response.url).hostname not in HOSTS:raise ValueError('external media redirect')
                            if 'text/html' in response.headers.get('Content-Type',''):raise ValueError('not video')
                            size=0
                            with src.open('wb') as f:
                                for chunk in response.iter_content(1024*1024):
                                    size+=len(chunk)
                                    if size>250*1024*1024:raise ValueError('video exceeds migration size limit')
                                    f.write(chunk)
                        # Optimized 16-second excerpt for the header, plus full article playback.
                        hero=Path(temp)/'hero.mp4';still=Path(temp)/'poster.jpg';whole=Path(temp)/'full.mp4'
                        ff=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-i',str(src)]
                        subprocess.run(ff+['-t','16','-map','0:v:0','-an','-vf',"scale='min(1280,iw)':-2,fps=25",'-c:v','libx264','-preset','fast','-crf','25','-pix_fmt','yuv420p','-movflags','+faststart',str(hero)],check=True,timeout=120)
                        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-ss','1','-i',str(hero),'-frames:v','1','-q:v','3',str(still)],check=True,timeout=30)
                        subprocess.run(ff+['-map','0:v:0','-map','0:a?','-vf',"scale='min(1280,iw)':-2",'-c:v','libx264','-preset','fast','-crf','25','-pix_fmt','yuv420p','-c:a','aac','-b:a','96k','-movflags','+faststart',str(whole)],check=True,timeout=240)
                        shutil.copyfile(hero,output);shutil.copyfile(still,poster);shutil.copyfile(whole,fullvideo)
                        break
                    except Exception as exc:
                        print('::warning::Drone video candidate could not be processed:',type(exc).__name__)
                else:raise ValueError('no playable local drone video')
            print('Drone footage prepared:',output.stat().st_size,'bytes header clip')
        except Exception as exc:
            print('::warning::Drone header unavailable; existing photo slider retained:',str(exc)[:180])
            return False
    slides=source.select_one('.hero .slides')
    script=next((x for x in source.find_all('script') if x.string and 'const slides=[...document.querySelectorAll' in x.string),None)
    if not slides or not script:return False
    video=source.new_tag('video',attrs={'class':'slide drone-slide','muted':'','playsinline':'','preload':'none','poster':'/media/ntc-drohnenflug-poster.jpg','aria-hidden':'true','data-src':'/media/ntc-drohnenflug-hero.mp4','loop':''})
    # Video as first slide; keep all four original photos.
    slides.insert(0,video)
    for im in slides.select('img.slide'):im['class']=[c for c in im.get('class',[]) if c!='active']
    video['class']=['slide','drone-slide','active']
    source.head.style.append(".hero video.drone-slide{width:100%;height:100%;object-fit:cover;object-position:center;pointer-events:none}.hero .drone-slide.active{opacity:1}@media(prefers-reduced-motion:reduce){.hero .slide{transition:none}}")
    script.string="""(()=>{const slides=[...document.querySelectorAll('.hero .slide')],labels=['Unser NTC aus der Vogelperspektive','Unsere Anlage','Unsere Tennishalle','Unser Vereinsleben','Gemeinschaft auf und neben dem Platz'];const topics=[['Tennis in Neuenhagen.','Unser Verein aus einer ganz neuen Perspektive.','Drohnenflug ansehen','/der-ntc-aus-der-vogelperspektive/'],['Tennis in Neuenhagen.','Sport, Gemeinschaft und Vereinsleben beim NTC 93.','Den Verein entdecken','/ueber-uns/'],['Tennis das ganze Jahr.','Unsere Tennishalle – auch im Winter auf dem Platz.','Zur Tennishalle','/tennishalle/'],['Gemeinsam auf dem Platz.','Von der Jugend bis zu den Seniorenteams.','Unsere Teams','/mannschaften/'],['Mehr als ein Verein.','Begegnungen auf und neben dem Tennisplatz.','Aktuelles aus dem NTC','/news/']];const reduced=matchMedia('(prefers-reduced-motion: reduce)'),saveData=!!navigator.connection?.saveData;let index=0,paused=reduced.matches,timer;const p=document.querySelector('#pause');function media(){slides.forEach((s,i)=>{if(s.tagName!=='VIDEO')return;s.pause();if(i===index&&!paused&&!document.hidden&&!saveData){s.muted=true;s.playsInline=true;if(!s.src)s.src=s.dataset.src;s.play().catch(()=>{})}})}function show(n){index=(n+slides.length)%slides.length;slides.forEach((s,i)=>{s.classList.toggle('active',i===index);s.setAttribute('aria-hidden',i===index?'false':'true')});document.querySelector('#count').textContent=String(index+1).padStart(2,'0')+' / '+String(slides.length).padStart(2,'0');document.querySelector('#photoCaption').textContent=labels[index];const t=topics[index];document.querySelector('#slideTitle').textContent=t[0];document.querySelector('#slideText').textContent=t[1];const a=document.querySelector('#slideLink');a.href=t[3];a.textContent=t[2]+' ↗';media()}function schedule(){clearTimeout(timer);media();if(!paused&&!document.hidden)timer=setTimeout(()=>{show(index+1);schedule()},slides[index].tagName==='VIDEO'?16000:6500)}function updatePause(){p.textContent=paused?'▶':'Ⅱ';p.setAttribute('aria-pressed',String(paused));p.setAttribute('aria-label',paused?'Bildwechsel fortsetzen':'Bildwechsel pausieren');schedule()}document.querySelector('#prev').onclick=()=>{show(index-1);schedule()};document.querySelector('#next').onclick=()=>{show(index+1);schedule()};p.onclick=()=>{paused=!paused;updatePause()};document.addEventListener('visibilitychange',schedule);show(reduced.matches||saveData?1:0);updatePause()})();"""
    return True
DRONE_AVAILABLE=integrate_drone_hero(source)

source.main.append(BeautifulSoup(sponsor_band(),'html.parser'))

# Club calendar fallback stays usable even before the CMS database is available.
def club_event_list(compact=False):
    # Read the same checked-in seed as the CMS to keep the offline fallback in sync.
    raw=(ROOT/'admin/index.php').read_text(encoding='utf-8')
    match=re.search(r"\$eventSeed=json_decode\('([^\n]*)',true\);",raw)
    items=json.loads(match.group(1)) if match else []
    from datetime import date as dt_date
    today=dt_date.today().isoformat()
    months=['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez']
    rows=[]
    for event in sorted(items,key=lambda x:x['data']['date']):
        d=event['data'];start=d['date'];end=d.get('end_date') or start
        if end<today:continue
        day=start[8:10];month=months[int(start[5:7])-1]+' '+start[:4]
        if end>start:
            if end[:7]==start[:7]:day+='–'+end[8:10]
            else:day=start[8:10]+'.'+start[5:7]+'.–'+end[8:10]+'.'+end[5:7]+'.'
        meta=' · '.join(v for v in [(d.get('time','')+' Uhr') if d.get('time') else '',d.get('venue','')] if v)
        status=d.get('status','')
        esc=lambda v:html.escape(str(v),quote=True)
        rows.append('<article class="club-event" data-event-date="'+esc(start)+'" data-event-end="'+esc(end)+'"><div class="club-event-date"><strong>'+esc(day)+'</strong><span>'+esc(month)+'</span></div><div class="club-event-copy"><h3>'+esc(event['title'])+'</h3>'+('<span class="club-event-status">'+esc(status)+'</span>' if status and status!='Bestätigt' else '')+'<p class="club-event-meta">'+esc(meta)+'</p>'+('' if compact else '<p>'+esc(d.get('body',''))+'</p>')+('<a href="'+esc(d['link'])+'">Details →</a>' if d.get('link') else '')+'</div></article>')
    if compact:rows=rows[:4]
    return '<div class="club-event-list" data-club-events="'+('compact' if compact else 'full')+'">'+''.join(rows)+'</div>'
club_events_css="""
.club-events-home{max-width:1320px;margin:0 auto;padding:18px clamp(20px,5vw,68px) 25px}.club-events-heading{display:flex;align-items:end;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line,#dce5df);padding-bottom:10px;margin-bottom:12px}.club-events-heading h2{font-size:clamp(22px,2.4vw,30px);margin:3px 0 0;letter-spacing:-.03em;line-height:1.15}.club-event-list{display:grid;gap:0}.club-event{display:grid;grid-template-columns:74px minmax(0,1fr);gap:17px;padding:15px 0;border-bottom:1px solid var(--line,#dce5df);align-items:start}.club-event-date{min-height:70px;padding:8px 5px;text-align:center;background:#e8f0ea;color:#155d4b;border-radius:4px;display:grid;align-content:center;gap:3px}.club-event-date strong{font-size:28px;line-height:1}.club-event-date span{font-size:11px;font-weight:650}.club-event-copy h3{margin:0 0 4px;font-size:17px;line-height:1.3}.club-event-copy p{font-size:14px;line-height:1.5;margin:5px 0}.club-event-copy p.club-event-meta{font-size:12px;color:var(--muted,#61776d)}.club-event-copy a{font-size:13px;font-weight:700;color:var(--green,#146143);display:inline-block;margin-top:3px}.club-event-status{font-size:11px;font-weight:650;color:#80621c;background:#f5efd9;padding:2px 6px;border-radius:3px}.club-event-list[data-club-events=compact]{grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}.club-event-list[data-club-events=compact] .club-event{grid-template-columns:60px minmax(0,1fr);gap:12px;padding:8px 0}.club-event-list[data-club-events=compact] .club-event-date{min-height:61px}.club-event-list[data-club-events=compact] .club-event-copy h3{font-size:15px}.club-event-page{max-width:1020px;margin:0 auto}.club-event-page .club-event-list{margin:24px 0}.club-event-empty{color:var(--muted,#61776d);font-size:14px;padding:14px 0}.club-event-foot{font-size:14px;color:var(--muted,#61776d);margin:24px 0}@media(max-width:680px){.club-event-list[data-club-events=compact]{grid-template-columns:1fr;gap:6px}.club-event{grid-template-columns:64px minmax(0,1fr);gap:12px}.club-events-heading{align-items:center}}
"""
source.head.style.append(club_events_css)
event_section=BeautifulSoup('<section class="club-events-home"><div class="club-events-heading"><div><div class="eyebrow section-label">Vereinsleben</div><h2>Nächste Termine</h2></div><a class="textlink" href="/termine/">Alle Termine →</a></div>'+club_event_list(True)+'</section>','html.parser')
news_section=source.select_one('.home-layout')
if news_section:news_section.insert_after(event_section)
else:source.main.append(event_section)

# Shared contact and arrival links.
footlinks=source.select_one('.footlinks')
if footlinks and not footlinks.find('a',href='/anfahrt/'):
    a=source.new_tag('a',href='/anfahrt/');a.string='Anfahrt & Kontakt'
    old=footlinks.find('a',href='mailto:info@ntc93.de')
    if old: old.replace_with(a)
    else: footlinks.insert(0,a)
    mail=source.new_tag('a',href='mailto:info@ntc93.de');mail.string='E-Mail'
    footlinks.insert(1,mail)
foot_address=source.select_one('.foot p')
if foot_address:
    for text_node in list(foot_address.find_all(string=True)):
        if 'Hildesheimer Straße' in str(text_node):
            a=source.new_tag('a',href='/anfahrt/',attrs={'class':'foot-address-link'})
            a.string=str(text_node).strip()
            text_node.replace_with(a)
source.head.append(source.new_tag('link',attrs={'rel':'stylesheet','href':'/club-enhancements.css'}))
source.head.append(source.new_tag('script',attrs={'src':'/club-enhancements.js','defer':''}))


# Shared header and sponsor section for staging pages.
# Published content is loaded independently from the generated site.
cms_style=source.new_tag('link',attrs={'rel':'stylesheet','href':'/cms-public.css'})
source.head.append(cms_style)
cms_script=source.new_tag('script',attrs={'src':'/cms-public.js','defer':''})
source.head.append(cms_script)

# Apply the same external-link rule to dynamic CMS and nuLiga content.
EXTERNAL_JS="""(()=>{const internal=new Set([location.hostname,'ntc93.de','www.ntc93.de','neu.ntc93.de']);function fix(a){if(!a.matches('a[href]'))return;try{const u=new URL(a.getAttribute('href'),location.href);if(!['http:','https:'].includes(u.protocol))return;const external=!internal.has(u.hostname.toLowerCase());if(external){if(a.target!=='_blank')a.target='_blank';const rel=new Set(a.rel.split(/\\s+/).filter(Boolean));rel.add('noopener');rel.add('noreferrer');a.rel=[...rel].join(' ')}else if(a.target==='_blank'){a.removeAttribute('target')}}catch{}}function start(){document.querySelectorAll('a[href]').forEach(fix);new MutationObserver(records=>{for(const r of records){if(r.type==='attributes'){fix(r.target);continue}for(const n of r.addedNodes){if(n.nodeType!==1)continue;fix(n);n.querySelectorAll('a[href]').forEach(fix)}}}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['href']});document.addEventListener('click',e=>{const a=e.target.closest?.('a[href]');if(a)fix(a)},true)}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start()})();"""
external_script=source.new_tag('script')
external_script.string=EXTERNAL_JS
source.head.append(external_script)

(ROOT/'index.html').write_text(str(source),encoding='utf-8')
header=str(source.header);footer=str(source.footer)
head=copy.deepcopy(source.head)
head.style.append(css)
head.style.append("\n/* Editorial article photography: responsive, undistorted originals and restrained gallery spacing. */\n.article-heading,.article-reading{max-width:980px;margin-left:auto;margin-right:auto}.article-heading{margin-bottom:20px}.article-heading h1{max-width:920px;font-size:clamp(29px,3.8vw,48px);line-height:1.13}.article-featured{margin:0 0 30px;background:#f3f6f2;border-radius:5px;overflow:hidden;display:flex;justify-content:center;align-items:center}.article-featured img{display:block;width:auto;max-width:100%;height:auto;max-height:570px;object-fit:contain;margin:0}.article-reading .article-content{max-width:820px;margin:auto;font-size:16px;line-height:1.75}.article-reading .article-content .article-figure{display:block;margin:25px 0;background:none;text-align:center}.article-reading .article-content img.article-inline-photo{width:auto;max-width:100%;height:auto;max-height:510px;object-fit:contain;display:block;margin:0 auto;border-radius:4px}.article-reading .article-content .article-figure figcaption{font-size:12px;color:var(--muted);margin:7px auto 0;line-height:1.4}.article-gallery-section{margin:34px 0 0;padding-top:20px;border-top:1px solid var(--line)}.article-gallery-section h2{font-size:23px;margin:0 0 16px}.article-gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:15px;align-items:start}.article-gallery-photo{margin:0;min-width:0;background:#f3f6f2;border-radius:4px;overflow:hidden}.article-gallery-photo img{width:100%;height:auto;aspect-ratio:4/3;object-fit:contain;display:block}.article-featured:empty,.article-figure:empty,.article-gallery-photo:empty{display:none}.article-lightbox-link{display:block;cursor:zoom-in}.article-lightbox-link:focus-visible{outline:2px solid var(--green);outline-offset:3px}.article-lightbox{padding:0;border:0;background:#102521;border-radius:7px;max-width:96vw;max-height:94dvh;color:#fff;overflow:auto}.article-lightbox::backdrop{background:#071612d9}.article-lightbox img{display:block;max-width:94vw;max-height:85dvh;object-fit:contain}.article-lightbox button{display:block;margin:9px 12px 9px auto;padding:7px 12px;border:1px solid #ffffff70;background:#ffffff14;color:white;border-radius:4px;cursor:pointer;font-size:13px}.cms-article .cms-article-image{margin:18px auto 28px;width:auto;max-width:100%;height:auto;max-height:570px;border-radius:4px;object-fit:contain;display:block}.article-reading .article-content p:empty{display:none}@media(max-width:600px){.article-featured{margin-bottom:22px}.article-featured img{max-height:430px}.article-reading .article-content{font-size:15px}.article-gallery{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.article-gallery-photo img{aspect-ratio:1/1}.article-lightbox img{max-width:96vw}}\n")
article_script=source.new_tag('script')
article_script.string="(()=>{const selector='.article-featured img,.article-content img.article-inline-photo,.article-gallery img,.cms-article-image';function enhance(img){if(img.closest('.article-lightbox-link')||img.closest('a'))return;const src=img.currentSrc||img.src;if(!src)return;const a=document.createElement('a');a.className='article-lightbox-link';a.href=src;a.setAttribute('aria-label','Foto vergrößern');img.replaceWith(a);a.append(img);a.addEventListener('click',e=>{if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||!HTMLDialogElement.prototype.showModal)return;e.preventDefault();const d=document.createElement('dialog');d.className='article-lightbox';d.setAttribute('aria-label','Fotoansicht');const close=document.createElement('button');close.type='button';close.textContent='Schließen ×';const photo=document.createElement('img');photo.src=img.currentSrc||img.src;photo.alt=img.alt||'';d.append(close,photo);document.body.append(d);close.onclick=()=>d.close();d.addEventListener('click',ev=>{if(ev.target===d)d.close()});d.addEventListener('close',()=>{d.remove();a.focus()},{once:true});d.showModal();close.focus()})}function scan(){document.querySelectorAll(selector).forEach(enhance)}function start(){scan();const root=document.querySelector('#cms-article');if(root)new MutationObserver(scan).observe(root,{childList:true,subtree:true})}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start()})();"
head.append(article_script)
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
        target=target if target=='/gastronomie/' else matching_link(node,label) or target
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

def news_picture_layout(clean,featured,photos,title):
    # Keep one instance of each photo and retain the original reading order.
    seen=set()
    lead_alt=''
    for im in list(clean.find_all('img')):
        src=im.get('src','')
        if not src:continue
        key=photo_key(src)
        if featured and key==photo_key(featured):
            if not lead_alt:lead_alt=im.get('alt','')
            # Keep captions in the text, but avoid the same photo twice.
            if im.parent.name=='a' and not im.parent.get_text(strip=True):im.parent.decompose()
            else:im.decompose()
            continue
        if key in seen:
            if im.parent.name=='a' and not im.parent.get_text(strip=True):im.parent.decompose()
            else:im.decompose()
            continue
        seen.add(key)
        im['class']=['article-inline-photo']
        im['loading']='lazy';im['decoding']='async'
        if im.parent.name=='a' and not im.parent.get_text(strip=True):
            old=im.parent;old.insert_before(im.extract());old.decompose()
        if im.find_parent('figure') is None:
            f=clean.new_tag('figure',attrs={'class':'article-figure'})
            im.wrap(f)
        else:
            f=im.find_parent('figure');f['class']=list(dict.fromkeys(f.get('class',[])+['article-figure']))
    # Gallery-only Elementor widgets may have no <img> in their rendered body.
    additional=[]
    for src,alt in photos:
        key=photo_key(src)
        if key in seen or featured and key==photo_key(featured):continue
        seen.add(key)
        additional.append('<figure class="article-gallery-photo">'+photo(src,alt,'article-inline-photo')+'</figure>')
    gallery=('<section class="article-gallery-section"><h2>Weitere Bilder</h2><div class="article-gallery">'+''.join(additional)+'</div></section>') if additional else ''
    lead=('<figure class="article-featured"><img src="'+E(featured)+'" alt="'+E(lead_alt)+'" fetchpriority="high" decoding="async"></figure>') if featured else ''
    return lead,str(clean),gallery

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
        links=section_links(node,[('Vorstand','/vorstand/','Ansprechpartner und Verantwortliche'),('Trainer','/trainer/','Training auf und neben dem Platz'),('Ehrenmitglieder','/ehrenmitglieder/','Engagement für unseren Verein'),('Tennishalle','/tennishalle/','Auch im Winter Tennis spielen'),('Sponsoring','/sponsoren/','Unsere Partner kennenlernen'),('Gastronomie','/gastronomie/','Trattoria Due Fratelli auf der Anlage')],url)
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
        lead,article,gallery=news_picture_layout(clean,img,postphotos.get(path,[]),title)
        if path=='/der-ntc-aus-der-vogelperspektive/' and DRONE_AVAILABLE:
            lead='<figure class="article-featured"><video controls playsinline preload="metadata" poster="/media/ntc-drohnenflug-poster.jpg" style="display:block;width:100%;height:auto;max-height:650px" src="/media/ntc-drohnenflug-original.mp4"></video></figure>'

        return crumb+top+'<div class="article-reading">'+lead+'<article class="content article-content">'+article+original+'</article>'+gallery+'</div>'
    # Information and service pages have a quiet title and readable content, not a generic giant hero.
    top=masthead(title,area if area.casefold()!=title.casefold() else 'Neuenhagener TC 93')
    return crumb+top+'<div class="subgrid'+('' if sidebar else ' solo')+'"><article class="content">'+str(clean)+original+'</article>'+sidebar+'</div>'

for path,(title,node,url,err) in loaded.items():
    if node is None: print('SKIPPED',path,err); continue
    if path in ('/news/','/termine/','/mannschaften/','/damen/','/herren/','/seniorinnen/','/senioren/','/jugendteams/','/mixed-doppel/'): continue
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
# Directions page: use only the verified postal address and club contact.
from urllib.parse import quote
destination='Neuenhagener TC 93 e.V., Hildesheimer Straße 11-13, 15366 Neuenhagen bei Berlin, Deutschland'
dest=quote(destination,safe='')
def directions(mode):
    return 'https://www.google.com/maps/dir/?api=1&amp;destination='+dest+'&amp;travelmode='+mode
map_url='https://www.google.com/maps/search/?api=1&amp;query='+dest
arrival_content='''
<div class="breadcrumbs"><a href="/">Startseite</a> <span aria-hidden="true">›</span> Anfahrt &amp; Kontakt</div>
<div class="detail-mast"><div class="detail-mast-copy"><div class="detail-kicker">So findest du uns</div><h1>Anfahrt &amp; Kontakt</h1><p>Willkommen auf unserer Tennisanlage in Neuenhagen bei Berlin.</p></div></div>
<div class="arrival-grid">
  <div class="arrival-map" data-map-mount>
    <div class="arrival-map-card">
      <svg class="arrival-map-pin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.7"/></svg>
      <h2>Hier findest du den NTC 93</h2><p>Hildesheimer Straße 11–13<br>15366 Neuenhagen bei Berlin</p>
      <button class="detail-action" type="button" data-load-map>Karte anzeigen</button>
      <small>Beim Anzeigen der Karte wird eine Verbindung zu Google Maps hergestellt.</small>
      <noscript><p>Bitte nutze die Routenlinks unterhalb der Karte.</p></noscript>
    </div>
  </div>
  <div class="arrival-info">
    <div class="detail-kicker">Unsere Vereinsanlage</div>
    <h2>Neuenhagener Tennisclub 93 e. V.</h2>
    <address class="arrival-address">Hildesheimer Straße 11–13<br>15366 Neuenhagen bei Berlin</address>
    <div class="arrival-contact"><a href="tel:+493342203823">03342 203823</a><a href="mailto:info@ntc93.de">info@ntc93.de</a></div>
    <div><a class="detail-action" href="'''+map_url+'''">In Google Maps öffnen ↗</a></div>
  </div>
</div>
<section class="detail-section"><h2>Deine Anreise</h2><div class="arrival-routes">
  <div class="arrival-route"><h3>Mit dem Auto</h3><p>Route von deinem Startpunkt bis zur Tennisanlage planen.</p><a href="'''+directions('driving')+'''">Autoroute starten ↗</a></div>
  <div class="arrival-route"><h3>Mit Bus &amp; Bahn</h3><p>Verbindungen mit dem öffentlichen Nahverkehr inklusive Fußweg zur Anlage anzeigen.</p><a href="'''+directions('transit')+'''">ÖPNV-Verbindung suchen ↗</a></div>
  <div class="arrival-route"><h3>Mit dem Fahrrad</h3><p>Die passende Fahrradroute zur Hildesheimer Straße finden.</p><a href="'''+directions('bicycling')+'''">Fahrradroute planen ↗</a></div>
</div></section>
'''
h=copy.deepcopy(head);h.title.string='Anfahrt & Kontakt | NTC 93'
out=ROOT/'anfahrt/index.html';out.parent.mkdir(parents=True,exist_ok=True)
out.write_text('<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="subpage detail-page arrival-page">'+arrival_content+'</main>'+footer+'<script>'+menu_js+'</script></body></html>',encoding='utf-8')

# Gastronomy landing page: keep the restaurant's own website authoritative for
# prices, reservations and exceptional opening hours. Use its existing photos.
GASTRO='https://due-fratelli-neuenhagen.de/'
def gastro_photo(filename):
    url=GASTRO+'media/'+filename
    rel='media/gastronomie/'+filename
    target=ROOT/rel
    try:
        if not target.is_file():
            with requests.get(url,timeout=(6,15),stream=True,headers=HEADERS) as response:
                response.raise_for_status()
                if urlsplit(response.url).hostname!='due-fratelli-neuenhagen.de':raise ValueError('unexpected host')
                data=bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data)>8*1024*1024:raise ValueError('image too large')
                if not (data.startswith(b'\xff\xd8\xff') or (data[:4]==b'RIFF' and data[8:12]==b'WEBP')):raise ValueError('not an image')
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(data)
        return '/'+rel
    except Exception as exc:
        print('::warning::Restaurant photo could not be copied:',filename)
        return url
room=gastro_photo('trattoria-gastraum.webp')
terrace=gastro_photo('restaurant-abend.jpg')
pizza=gastro_photo('gericht-pizza.jpg')
entrance=gastro_photo('restaurant-aussen.jpg')
gastro_css="""
.gastro-page{max-width:1400px}.gastro-hero{display:grid;grid-template-columns:1fr 1.15fr;background:#f4f3ea;overflow:hidden;border-radius:4px;align-items:stretch;margin-bottom:32px}.gastro-hero-copy{padding:clamp(25px,4vw,54px);align-self:center}.gastro-hero h1{font-size:clamp(32px,4.2vw,55px);line-height:1.04;letter-spacing:-.04em;margin:12px 0 16px}.gastro-hero p{font-size:16px;line-height:1.65;color:var(--muted);max-width:490px;margin:0 0 22px}.gastro-hero>img{width:100%;height:100%;min-height:320px;max-height:460px;object-fit:cover}.gastro-actions{display:flex;flex-wrap:wrap;gap:10px}.gastro-gallery{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin:24px 0 34px}.gastro-gallery figure{margin:0}.gastro-gallery img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:4px;display:block}.gastro-gallery figcaption{font-size:13px;font-weight:650;margin-top:8px;color:var(--muted)}.gastro-info{display:grid;grid-template-columns:1fr 1fr;gap:28px;border-top:1px solid var(--line);padding-top:24px}.gastro-info h2{font-size:23px;margin:0 0 14px;letter-spacing:-.025em}.gastro-hours{margin:0;padding:0}.gastro-hours div{display:flex;justify-content:space-between;gap:15px;padding:8px 0;border-bottom:1px solid var(--line);font-size:14px}.gastro-hours dd{margin:0;font-weight:650}.gastro-info p,.gastro-info address{font-size:14px;line-height:1.65;font-style:normal}.gastro-info a:not(.detail-action){color:var(--green);font-weight:650}.gastro-note{color:var(--muted);font-size:12px!important}.gastro-info .detail-action{margin-top:7px}@media(max-width:720px){.gastro-hero{grid-template-columns:1fr}.gastro-hero>img{min-height:0;height:250px;max-height:none}.gastro-hero-copy{padding:24px}.gastro-hero p{font-size:14px}.gastro-gallery{gap:9px}.gastro-gallery figcaption{font-size:11px}.gastro-info{grid-template-columns:1fr;gap:25px}}
"""
gastro_content='<div class="breadcrumbs"><a href="/">Startseite</a> › Gastronomie</div>'
gastro_content+='<div class="gastro-hero"><div class="gastro-hero-copy"><div class="detail-kicker">Unsere Gastronomie · Benvenuti</div><h1>Trattoria<br>Due Fratelli</h1><p>Ein Stück Italien auf unserer Tennisanlage. Ob nach dem Training, mit der Mannschaft oder für einen gemütlichen Abend mit Familie und Freunden – hier sind auch Gäste herzlich willkommen.</p><div class="gastro-actions">'+link_button('Speisekarte ansehen',GASTRO+'speisekarte/')+link_button('Tisch reservieren',GASTRO+'reservieren/',True)+'</div></div><img src="'+E(room)+'" alt="Gastraum der Trattoria Due Fratelli" decoding="async"></div>'
gastro_content+='<section class="detail-section"><h2>Italienische Küche. Direkt am Platz.</h2><p>Steinofenpizza, Pasta und italienische Fisch- und Fleischgerichte – dazu eine gemütliche Terrasse mit Blick auf die Vereinsanlage. Ein Treffpunkt für Vereinsmitglieder und Gäste.</p><div class="gastro-gallery">'
for url,alt in [(terrace,'Terrasse am Clubhaus'),(pizza,'Pizza aus der Küche'),(entrance,'Eingang zur Trattoria')]:
    gastro_content+='<figure>'+photo(url,alt)+'<figcaption>'+E(alt)+'</figcaption></figure>'
gastro_content+='</div></section><div class="gastro-info"><section><div class="detail-kicker">Öffnungszeiten</div><h2>Wir freuen uns auf euch</h2><dl class="gastro-hours"><div><dt>Montag</dt><dd>Ruhetag</dd></div><div><dt>Dienstag – Freitag</dt><dd>14–22 Uhr</dd></div><div><dt>Samstag – Sonntag</dt><dd>12–22 Uhr</dd></div></dl><p class="gastro-note">Abweichende Feiertagszeiten und aktuelle Angebote findet ihr auf der Restaurantwebsite.</p>'+link_button('Zur Restaurantwebsite',GASTRO)+'</section><section><div class="detail-kicker">Kontakt & Reservierung</div><h2>So erreicht ihr Due Fratelli</h2><address>Hildesheimer Straße 11–13<br>15366 Neuenhagen bei Berlin</address><p><a href="tel:+493342203823">03342 203823</a><br><a href="mailto:info@due-fratelli-neuenhagen.de">info@due-fratelli-neuenhagen.de</a></p><p><a href="/anfahrt/">Anfahrt zur Vereinsanlage →</a></p>'+link_button('Online reservieren',GASTRO+'reservieren/')+'</section></div>'
h=copy.deepcopy(head);h.title.string='Gastronomie – Trattoria Due Fratelli | NTC 93'
h.style.append(gastro_css)
out=ROOT/'gastronomie/index.html';out.parent.mkdir(parents=True,exist_ok=True)
out.write_text('<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="subpage detail-page gastro-page">'+gastro_content+'</main>'+footer+'<script>'+menu_js+'</script></body></html>',encoding='utf-8')


# Dedicated event calendar, no dependence on legacy calendar widgets.
h=copy.deepcopy(head);h.title.string='Termine | NTC 93'
calendar_subscription='<section class="calendar-subscription"><div><h2>NTC-Termine abonnieren</h2><p>Neue Termine und Änderungen werden automatisch mit deinem Kalender synchronisiert (je nach Aktualisierungsintervall deiner Kalender-App).</p></div><div class="calendar-actions"><a class="detail-action" id="calendarWebcal" href="webcal://neu.ntc93.de/admin/?calendar=1">Kalender abonnieren</a><a class="detail-action outline" href="/admin/?calendar=1">iCal-Datei öffnen</a></div><label for="calendarUrl">Kalender-URL für Google Kalender, Outlook und andere Apps</label><div class="calendar-url"><input id="calendarUrl" readonly value="https://neu.ntc93.de/admin/?calendar=1"><button type="button" class="detail-action outline" id="calendarCopy">Kopieren</button></div><p class="calendar-note">Google Kalender: Weitere Kalender → Per URL. Outlook: Kalender hinzufügen → Aus dem Internet abonnieren. Apple Kalender: Neues Kalenderabonnement.</p></section>'
calendar_script="""(()=>{const url=location.origin+'/admin/?calendar=1',field=document.querySelector('#calendarUrl'),link=document.querySelector('#calendarWebcal'),copy=document.querySelector('#calendarCopy');if(!field||!link||!copy)return;field.value=url;link.href=url.replace(/^https?:/,'webcal:');copy.onclick=async()=>{try{await navigator.clipboard.writeText(url);copy.textContent='Kopiert'}catch{field.focus();field.select()}}})();"""
h.style.append(".calendar-subscription{background:#edf4ee;border:1px solid #d5e4d8;padding:22px;border-radius:6px;margin:26px 0}.calendar-subscription h2{font-size:22px;margin:0 0 7px}.calendar-subscription p{font-size:14px;line-height:1.55}.calendar-actions{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 18px}.calendar-subscription label{font-size:12px;font-weight:650;display:block;margin:0 0 5px}.calendar-url{display:flex;gap:8px}.calendar-url input{min-width:0;flex:1;padding:9px;border:1px solid #b9cbbf;background:white;border-radius:4px;font:inherit;font-size:13px}.calendar-note{font-size:12px!important;color:var(--muted)}.club-event-date strong{font-size:clamp(17px,2.1vw,25px)}")
event_page='<div class="club-event-page"><div class="breadcrumbs"><a href="/">Startseite</a> › Termine</div>'+masthead('Termine','Vereinsleben','Die kommenden Veranstaltungen und Termine unseres Tennisclubs.')+calendar_subscription+club_event_list()+'<p class="club-event-foot">Die Punktspieltermine findest du im <a class="textlink" href="/matchcenter/">Matchcenter →</a>.</p></div>'
out=ROOT/'termine/index.html';out.parent.mkdir(parents=True,exist_ok=True)
out.write_text('<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="subpage detail-page">'+event_page+'</main>'+footer+'<script>'+menu_js+calendar_script+'</script></body></html>',encoding='utf-8')


# Replace photo-based legacy team pages with the nuLiga data portal.
teamhead=copy.deepcopy(head)
teamhead.append(source.new_tag('link',attrs={'rel':'stylesheet','href':'/teams.css'}))
teamhead.append(source.new_tag('script',attrs={'src':'/teams.js','defer':''}))
team_routes={'/mannschaften/':('Mannschaften',''),'/damen/':('Damen','Damen'),'/herren/':('Herren','Herren'),'/seniorinnen/':('Seniorinnen','Seniorinnen'),'/senioren/':('Senioren','Senioren'),'/jugendteams/':('Jugendteams','Jugend'),'/mixed-doppel/':('Mixed & Doppel','Mixed & Doppel'),'/mannschaften/team/':('Mannschaft','')}
for route_path,(title,category) in team_routes.items():
    detail=route_path=='/mannschaften/team/'
    h=copy.deepcopy(teamhead);h.title.string=title+' | NTC 93'
    intro='' if detail else masthead(title,'Mannschaftsspielbetrieb','Alle Mannschaften, Tabellenplätze und Spielpläne nach Saison. Die Daten stammen direkt aus nuLiga / TVBB.')
    if category:intro+='<p><a class="detail-textlink" href="/mannschaften/">← Alle Mannschaften</a></p>'
    crumb='<div class="breadcrumbs"><a href="/">Startseite</a> › <a href="/mannschaften/">Mannschaften</a>'+(' › '+E(title) if route_path!='/mannschaften/' else '')+'</div>'
    content=crumb+intro+'<div class="team-portal" data-team-portal="'+('detail' if detail else 'overview')+'" data-category="'+E(category)+'"><p class="tp-empty">Mannschaftsdaten werden geladen …</p><noscript><a href="https://tvbb.liga.nu/cgi-bin/WebObjects/nuLigaTENDE.woa/wa/clubTeams?club=36381" target="_blank" rel="noopener noreferrer">Mannschaften bei nuLiga ↗</a></noscript></div>'
    out=ROOT/route_path.strip('/')/'index.html';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text('<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="subpage detail-page">'+content+'</main>'+footer+'<script>'+menu_js+'</script></body></html>',encoding='utf-8')
# Third area in Matchcenter: all standings, independent from match filters.
mc=ROOT/'matchcenter/index.html'
if mc.is_file():
    page=BeautifulSoup(mc.read_text(encoding='utf-8'),'html.parser')
    page.head.append(page.new_tag('link',attrs={'rel':'stylesheet','href':'/teams.css'}))
    page.head.append(page.new_tag('script',attrs={'src':'/teams.js','defer':''}))
    page.main.append(BeautifulSoup('<section class="tp-matchcenter" id="tabellen"><div class="detail-kicker">Mannschaftsspielbetrieb</div><h2>Tabellen</h2><p>Wähle die Saison und eine Mannschaft aus, um die vollständige Gruppentabelle aufzurufen.</p><div class="team-portal" data-team-portal="standings"><p class="tp-empty">Tabellen werden geladen …</p></div></section>','html.parser'))
    mc.write_text(str(page),encoding='utf-8')

# Resolve internal routes and copy all linked legacy media after every page has been rendered.
migration=localize(ROOT)

# Static links receive the policy too, so it works even with JavaScript disabled.
# Navigation to the club restaurant goes through the new local landing page.
for file in ROOT.rglob('*.html'):
    soup=BeautifulSoup(file.read_text(encoding='utf-8'),'html.parser')
    for a in soup.select('a[href]'):
        try:
            u=urlsplit(a['href'])
            host=(u.hostname or '').lower()
        except ValueError:continue
        if host=='due-fratelli-neuenhagen.de' and u.path in ('','/') and not u.query and not u.fragment:
            if file!=ROOT/'gastronomie/index.html' or a.find_parent('footer') or a.find_parent('header'):
                a['href']='/gastronomie/'
                a.attrs.pop('target',None)
                continue
        if host and u.scheme in ('','http','https') and host not in ('ntc93.de','www.ntc93.de','neu.ntc93.de'):
            a['target']='_blank'
            rel=a.get('rel',[])
            if isinstance(rel,str):rel=rel.split()
            a['rel']=list(dict.fromkeys([*rel,'noopener','noreferrer']))
        elif not host or host in ('ntc93.de','www.ntc93.de','neu.ntc93.de'):
            a.attrs.pop('target',None)
    file.write_text(str(soup),encoding='utf-8')

archive_report['discovered']=len(NEWS)
archive_report['imported']=sum(1 for p,_,_ in NEWS if p in local)
archive_report['failed']=[p for p,_,_ in NEWS if p not in local]
report={'sponsor_count':len(SPONSORS),'archive':archive_report,'media_and_links':migration,'imported':sorted(local),'skipped':{p:re.sub(r'https?://[^\s]+','[URL]',err) for p,(_,_,_,err) in loaded.items() if err}}
if archive_report['expected'] and archive_report['imported']<archive_report['expected']:
    print('::warning::Archive incomplete: '+str(archive_report['imported'])+' imported, at least '+str(archive_report['expected'])+' indicated by source')
print('Legacy asset/link migration:',migration['assets_downloaded'],'files;',len(migration['missing_assets']),'missing assets;',len(migration['unresolved_links']),'unresolved references')

(ROOT/'migration-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Imported',len(local),'pages:',', '.join(sorted(local)))
