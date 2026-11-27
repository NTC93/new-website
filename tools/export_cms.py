"""Build a private CMS seed from the final, localized public website.

No user accounts, secrets, private member data or original external website
dependencies are included. Imported images remain on disk, not duplicated in SQL.
"""
from pathlib import Path
from urllib.parse import urlsplit, unquote
from datetime import datetime
import hashlib, json, re, mimetypes, unicodedata
from bs4 import BeautifulSoup

ROOT=Path('site')
entries={}
media={}
def slug(value):
    s=unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+','-',s).strip('-')[:150] or 'eintrag'
def key(value):
    return hashlib.sha256(value.encode()).hexdigest()[:12]
def clean_text(node):
    if not node:return ''
    copy=BeautifulSoup(str(node),'html.parser')
    for el in copy.select('script,style,button,input,select,iframe,nav,svg,.breadcrumbs,.post-back,.post-date,.article-date,.article-heading,.article-gallery-section,.detail-actions'):
        el.decompose()
    return re.sub(r'\n{3,}','\n\n','\n'.join(x.strip() for x in copy.get_text('\n',strip=True).splitlines() if x.strip())).strip()
def safe_href(value):
    value=str(value or '').strip()
    if not value:return ''
    try:u=urlsplit(value)
    except ValueError:return ''
    if u.scheme in ('http','https') and u.hostname and u.hostname not in ('ntc93.com','www.ntc93.com'):return value
    if value.startswith('/') and not value.startswith('//') and not re.search(r'[\x00-\x20\\]',value):return value
    return ''
def img(node):
    if not node:return ''
    return safe_href(node.get('src',''))
def collect_media(src,alt=''):
    if not src or not src.startswith('/media/'):return
    p=ROOT/unquote(urlsplit(src).path).lstrip('/')
    if not p.is_file():return
    if not p.resolve().is_relative_to((ROOT/'media').resolve()):return
    mime=mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
    name=re.sub(r'^[0-9a-f]{16}-','',p.name)
    prior=media.get(src)
    if prior and prior['alt']:return
    media[src]={'url':src,'name':name[:240],'mime':mime[:80],'alt':str(alt or '')[:240],'size':p.stat().st_size}
def add(kind,ident,title,data,date=None,position=0):
    title=str(title or '').strip()[:200]
    if not title:return
    ident=slug(ident)
    k=(kind,ident)
    if k in entries:return
    entries[k]={'kind':kind,'slug':ident,'title':title,'data':{k:str(v or '') for k,v in data.items()},'publish_at':date or '2000-01-01 00:00:00','position':position}
def gallery(node):
    if not node:return ''
    return '\n'.join(dict.fromkeys(u for u in (img(i) for i in node.select('img[src]')) if u))
def date_of(soup):
    t=soup.select_one('.article-date,.post-date,time')
    if not t:return None
    d=t.get('datetime') or t.get_text(' ',strip=True)
    for fmt in ('%d.%m.%Y','%Y-%m-%d'):
        try:return datetime.strptime(d[:10],fmt).strftime('%Y-%m-%d 00:00:00')
        except ValueError:pass
    return None

home=BeautifulSoup((ROOT/'index.html').read_text(encoding='utf-8'),'html.parser')
for file in sorted(ROOT.rglob('index.html')):
    if 'admin' in file.relative_to(ROOT).parts:continue
    soup=BeautifulSoup(file.read_text(encoding='utf-8'),'html.parser')
    main=soup.select_one('main')
    if not main:continue
    rel=file.parent.relative_to(ROOT).as_posix()
    path='/' if rel=='.' else '/'+rel+'/'
    for image in soup.select('img[src]'):
        collect_media(img(image),image.get('alt',''))
    for a in main.select('a[href]'):
        href=safe_href(a.get('href'))
        if not href:continue
        ext=Path(urlsplit(href).path).suffix.lower()
        if ext not in ('.pdf','.doc','.docx','.xls','.xlsx','.ppt','.pptx','.zip'):continue
        collect_media(href)
        name=a.get_text(' ',strip=True) or Path(unquote(urlsplit(href).path)).name
        add('documents','dokument-'+key(href),name,{'category':'Vereinsdokumente','link':href,'body':'','source_path':path})
    h=soup.select_one('main h1')
    title=h.get_text(' ',strip=True) if h else (soup.title.get_text(strip=True).split(' | ')[0] if soup.title else rel)
    if main.select_one('.article-heading') and main.select_one('.article-reading'):
        reading=main.select_one('.article-reading')
        article=reading.select_one('.article-content,.content') or reading
        body=clean_text(article)
        lead=reading.select_one('.article-featured img') or reading.select_one('img')
        para=article.select_one('p')
        teaser=para.get_text(' ',strip=True) if para else body[:160]
        add('news',rel,title,{'body':body,'teaser':teaser[:250],'image':img(lead),'gallery':gallery(reading),'source_path':path,'category':'','imported_original':'1'},date_of(soup))
        continue
    if path=='/redaktion/':continue
    body=clean_text(main)
    im=main.select_one('.detail-photo,.gastro-hero img,.slide.active,article img')
    add('pages','startseite' if path=='/' else rel,title,{'path':path,'body':body,'image':img(im),'gallery':gallery(main),'source_path':path,'imported_original':'1'})
    # Extract the actual already-rendered profiles; do not infer people from names elsewhere.
    if path in ('/vorstand/','/trainer/'):
        for card in main.select('.person'):
            name=card.select_one('h3')
            if not name:continue
            section=card.find_parent('section')
            heading=section.select_one('h2') if section else None
            cat=heading.get_text(' ',strip=True) if heading else title
            p=card.select_one('p')
            mail=card.select_one('a[href^="mailto:"]')
            add('people',path.strip('/')+'-'+name.get_text(' ',strip=True),name.get_text(' ',strip=True),{'category':cat,'role':p.get_text(' ',strip=True) if p else '', 'body':clean_text(card),'image':img(card.select_one('img')),'email':mail['href'][7:] if mail else '', 'source_path':path,'imported_original':'1'})
    for panel in main.select('.team-panel'):
        name=panel.select_one('h2,h3')
        if not name:continue
        link=next((safe_href(a.get('href')) for a in panel.select('a[href]') if 'liga.nu' in a.get('href','')), '')
        add('teams',rel+'-'+name.get_text(' ',strip=True),name.get_text(' ',strip=True),{'category':title,'body':clean_text(panel),'image':img(panel.select_one('img')),'gallery':gallery(panel),'link':link,'source_path':path,'imported_original':'1'})
    if path=='/sponsoren/':
        for i,logo in enumerate(main.select('.sponsor-grid .sponsor-logo')):
            image=logo.select_one('img')
            src=img(image)
            if not src:continue
            name=image.get('alt','').strip() or Path(unquote(urlsplit(src).path)).stem
            add('sponsors','sponsor-'+key(src),name,{'image':src,'link':safe_href(logo.get('href')),'body':'','category':'','imported_original':'1'},position=i)
# Existing homepage slide copy and images, from the actual checked-in generated page.
slides=[
 ('Tennis in Neuenhagen.','Sport, Gemeinschaft und Vereinsleben beim NTC 93.','Den Verein entdecken','/ueber-uns/'),
 ('Tennis das ganze Jahr.','Unsere Tennishalle – auch im Winter auf dem Platz.','Zur Tennishalle','/tennishalle/'),
 ('Gemeinsam auf dem Platz.','Von der Jugend bis zu den Seniorenteams.','Unsere Teams','/mannschaften/'),
 ('Mehr als ein Verein.','Begegnungen auf und neben dem Tennisplatz.','Aktuelles aus dem NTC','/news/')]
for i,im in enumerate(home.select('.slides .slide')):
    if i>=len(slides):break
    title,body,button,link=slides[i]
    add('slides','slider-'+str(i+1),title,{'image':img(im),'body':body,'link':link,'button':button,'imported_original':'1'},position=i)
for i,a in enumerate(home.select('#nav a[href]')):
    href=safe_href(a.get('href'))
    if not href:continue
    group=a.find_parent(class_='nav-group')
    heading=group.select_one('.nav-trigger') if group else None
    cat=heading.get_text(' ',strip=True) if heading else 'Hauptnavigation'
    title=a.get_text(' ',strip=True)
    add('menus','menu-'+key(cat+'|'+href),title,{'category':cat,'link':href,'imported_original':'1'},position=i)
for ident,title,value,link in [
 ('vereinsname','Vereinsname','Neuenhagener Tennisclub 93 e. V.',''),
 ('anschrift','Anschrift','Hildesheimer Straße 11–13, 15366 Neuenhagen bei Berlin','/anfahrt/'),
 ('kontakt','Kontakt','info@ntc93.de','/anfahrt/'),
 ('platzbuchung','Platzbuchung','eBuSy','https://ntc93v8.ebusy.de/lite-module/1731'),
 ('matchcenter','Matchcenter','nuLiga / TVBB','/matchcenter/'),
 ('gastronomie','Gastronomie','Trattoria Due Fratelli','/gastronomie/'),
 ('kalender','Kalender-Abo','NTC 93 – Vereinstermine','/admin/?calendar=1')]:
    add('settings',ident,title,{'body':value,'link':link,'imported_original':'1'})
# Include every successfully migrated local asset, including files not referenced
# by a selected template. Public binary data is never copied into the database.
for p in sorted((ROOT/'media').rglob('*')):
    if p.is_file():collect_media('/'+p.relative_to(ROOT).as_posix())
manifest={'version':1,'entries':list(entries.values()),'media':list(media.values())}
out=ROOT/'admin/private/content-seed.json'
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
from collections import Counter
print('CMS seed:',dict(Counter(e['kind'] for e in entries.values())), 'media:',len(media),flush=True)
