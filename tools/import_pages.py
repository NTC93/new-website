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

def load(item):
    path,label=item
    try:
        soup,url=fetch(urljoin(BASE,path))
        node=extract(soup)
        if node is None: raise ValueError('no content container')
        title=soup.select_one('main h1, .entry-title, h1')
        actual=' '.join(title.stripped_strings) if title else ''
        title=label or actual or (soup.title.get_text(strip=True).split(' – ')[0] if soup.title else path.strip('/'))
        return path,(title,node,url,None)
    except Exception as e:
        return path,(label or path.strip('/'),None,urljoin(BASE,path),str(e))

# Cap concurrency to avoid unnecessary load on the current website.
with ThreadPoolExecutor(max_workers=4) as pool:
    loaded=dict(pool.map(load,pages.items()))
local={p for p,(_,node,_,err) in loaded.items() if node is not None}
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
.subpage{max-width:1320px;margin:auto;padding:44px clamp(20px,5vw,68px) 80px;min-height:60vh}.breadcrumbs{font-size:13px;color:#62726d;margin-bottom:32px}.breadcrumbs a{text-decoration:underline;text-underline-offset:3px}.pagetitle{font-size:clamp(42px,6vw,80px);letter-spacing:-.06em;line-height:1.04;margin:0 0 34px}.subgrid{display:grid;grid-template-columns:minmax(0,1fr) minmax(210px,270px);gap:clamp(28px,5vw,80px);align-items:start}.subgrid.solo{grid-template-columns:minmax(0,900px)}.content{min-width:0;font-size:17px;line-height:1.65;overflow-wrap:anywhere}.content h2{font-size:clamp(25px,3vw,40px);line-height:1.15;letter-spacing:-.035em;margin:40px 0 15px}.content h3{font-size:24px;line-height:1.25;margin:28px 0 12px}.content h4,.content h5,.content h6{font-size:19px;margin:22px 0 8px}.content p{margin:0 0 18px}.content a{color:var(--green);text-decoration:underline;text-underline-offset:3px}.content img{max-width:100%;width:auto;height:auto;display:block;margin:18px 0;object-fit:contain;max-height:560px}.content figure{margin:22px 0}.content figcaption{font-size:13px;color:#62726d}.content table{border-collapse:collapse;display:block;max-width:100%;overflow-x:auto;margin:20px 0}.content td,.content th{padding:10px 14px;border:1px solid var(--line);text-align:left}.content th{background:#e8efeb}.content ul,.content ol{padding-left:24px}.section-nav{border-top:3px solid var(--green);padding-top:14px}.section-nav h2{font-size:13px;text-transform:uppercase;letter-spacing:.1em;margin:0 0 12px;color:var(--green)}.section-nav a{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line);padding:11px 0;font-size:14px}.section-nav a:hover{color:var(--green)}.source-note{margin-top:42px;font-size:13px;color:#62726d;border-top:1px solid var(--line);padding-top:16px}.source-note a{text-decoration:underline}
@media(max-width:800px){.subpage{padding-top:28px;padding-bottom:48px}.subgrid{grid-template-columns:1fr}.section-nav{margin-top:20px}.pagetitle{margin-bottom:24px}}
"""
# Main page only uses the current layout. Fix local links and deploy unchanged design.
(ROOT/'index.html').write_text(str(source),encoding='utf-8')
header=str(source.header);footer=str(source.footer)
head=copy.deepcopy(source.head)
head.style.append(css)
for link in head.select('link[href]'):
    if link['href'].startswith('media/'): link['href']='/'+link['href']
menu_js="""const menu=document.querySelector('.menu'),nav=document.querySelector('#nav');menu.onclick=()=>{const open=nav.classList.toggle('open');menu.setAttribute('aria-expanded',String(open))};document.addEventListener('keydown',e=>{if(e.key==='Escape'){nav.classList.remove('open');menu.setAttribute('aria-expanded','false')}});"""
for path,(title,node,url,err) in loaded.items():
    if node is None: print('SKIPPED',path,err); continue
    body=sanitize(node,url,local)
    sidebar=related(path)
    original='<div class="source-note">Inhaltsübernahme aus der bisherigen Vereinswebsite. <a href="'+html.escape(url,quote=True)+'">Originalseite ansehen</a></div>'
    if path=='/termine/': original='<p><a class="textlink" href="'+html.escape(url,quote=True)+'">Aktuellen Kalender auf der bisherigen Website öffnen →</a></p>'+original
    h=copy.deepcopy(head);h.title.string=title+' | NTC 93'
    markup='<!doctype html><html lang="de">'+str(h)+'<body>'+header+'<main class="subpage"><div class="breadcrumbs"><a href="/">Startseite</a> / '+html.escape(title)+'</div><h1 class="pagetitle">'+html.escape(title)+'</h1><div class="subgrid'+('' if sidebar else ' solo')+'"><article class="content">'+body+original+'</article>'+sidebar+'</div></main>'+footer+'<script>'+menu_js+'</script></body></html>'
    out=ROOT/path.strip('/')/'index.html';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(markup,encoding='utf-8')
report={'imported':sorted(local),'skipped':{p:err for p,(_,_,_,err) in loaded.items() if err}}
(ROOT/'migration-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Imported',len(local),'pages:',', '.join(sorted(local)))
