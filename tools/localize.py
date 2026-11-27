"""Remove legacy website dependencies from the generated public site."""
from pathlib import Path
from urllib.parse import urljoin,urlsplit,unquote
from concurrent.futures import ThreadPoolExecutor
import hashlib,re,json
from bs4 import BeautifulSoup
import requests

BASE='https://ntc93.com/'
HOSTS={'ntc93.com','www.ntc93.com'}
ASSET_EXT={'.jpg','.jpeg','.png','.gif','.webp','.avif','.ico','.pdf','.svg','.doc','.docx','.xls','.xlsx','.ppt','.pptx','.zip','.mp4'}
# SVG is served only after rejecting active or externally referenced content.
def legacy(u):
    try:return urlsplit(urljoin(BASE,u)).hostname in HOSTS
    except ValueError:return False
def absolute_legacy(u):
    return u.startswith(('http://','https://','//')) and legacy(u)
def localize(root):
    root=Path(root);files=list(root.rglob('*.html'));assets={};missing=set()
    def asset_url(u):
        if not absolute_legacy(u):return None
        parsed=urlsplit(urljoin(BASE,u))
        ext=Path(unquote(parsed.path)).suffix.lower()
        if ext not in ASSET_EXT:return None
        return parsed._replace(fragment='').geturl()
    def local_path(u):
        p=urlsplit(u);ext=Path(unquote(p.path)).suffix.lower()
        name=re.sub(r'[^a-zA-Z0-9._-]+','-',Path(unquote(p.path)).stem).strip('-')[:72] or 'datei'
        return 'media/import/'+hashlib.sha256(u.encode()).hexdigest()[:16]+'-'+name+ext
    # Scan rendered pages, not original templates. Keep the final site independent.
    docs={}
    for file in files:
        soup=BeautifulSoup(file.read_text(encoding='utf-8'),'html.parser');docs[file]=soup
        for tag in soup.find_all(True):
            for attr in ('src','href','poster','data-src'):
                v=tag.get(attr)
                if isinstance(v,str):
                    a=asset_url(v)
                    if a:assets[a]=local_path(a)
    def download(item):
        url,rel=item;path=root/rel
        if path.is_file() and path.stat().st_size>0:return url,True
        try:
            with requests.get(url,timeout=(8,45),stream=True,headers={'User-Agent':'NTC93 website migration (public assets)'}) as r:
                r.raise_for_status()
                if urlsplit(r.url).hostname not in HOSTS:raise ValueError('external redirect')
                mime=r.headers.get('Content-Type','').split(';')[0].lower()
                if mime in ('text/html','application/xhtml+xml','text/plain','application/javascript','text/javascript'):raise ValueError('unexpected document type')
                chunks=[];size=0
                for chunk in r.iter_content(65536):
                    size+=len(chunk)
                    if size>40*1024*1024:raise ValueError('asset too large')
                    chunks.append(chunk)
                data=b''.join(chunks)
                if not data:raise ValueError('empty asset')
                if path.suffix=='.svg':
                    text=data.decode('utf-8')
                    if re.search(r'<(?:script|foreignObject|iframe|object|embed)\b|\bon[a-z]+\s*=|(?:href|src)\s*=\s*["\'](?!#)|<!DOCTYPE|@import|url\(\s*["\']?(?!#)',text,re.I):raise ValueError('unsafe SVG')
                if path.suffix=='.pdf' and not data.startswith(b'%PDF-'):raise ValueError('not PDF')
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            return url,True
        except Exception:return url,False
    with ThreadPoolExecutor(max_workers=5) as pool:
        status=dict(pool.map(download,assets.items()))
    for u,ok in status.items():
        if not ok:missing.add(urlsplit(u).path)
    unresolved=set()
    for file,soup in docs.items():
        for tag in list(soup.find_all(True)):
            if not tag.name:continue
            for attr in ('src','href','poster','data-src'):
                v=tag.get(attr)
                if not isinstance(v,str) or not absolute_legacy(v):continue
                a=asset_url(v);u=urlsplit(urljoin(BASE,v));replacement=None
                if a and status.get(a):replacement='/'+assets[a]+('#'+u.fragment if u.fragment else '')
                elif not a:
                    p=unquote(u.path).strip('/')
                    if not u.query and (root/p/'index.html').is_file():replacement=('/'+p+'/' if p else '/')+('#'+u.fragment if u.fragment else '')
                if replacement:tag[attr]=replacement
                else:
                    unresolved.add((str(file.relative_to(root)),u.path))
                    if tag.name=='a':
                        # Keep readable label, but never send visitors to the old website.
                        tag.unwrap();break
                    if tag.name in ('img','source','link','iframe'):
                        tag.decompose();break
                    del tag[attr]
            if not tag.name:continue
            for attr in ('srcset','data-srcset'):
                if attr in tag.attrs and 'ntc93.com' in str(tag[attr]).lower():del tag[attr]
        # URLs in text or scripts must not survive as clickable old references.
        for t in list(soup.find_all(string=True)):
            if t.parent and t.parent.name not in ('script','style') and re.search(r'https?://(?:www\.)?ntc93\.com(?:/[^ \t\r\n<>]*)?',str(t),re.I):
                t.replace_with(re.sub(r'https?://(?:www\.)?ntc93\.com(?:/[^ \t\r\n<>]*)?','',str(t),flags=re.I))
        output=str(soup)
        if re.search(r'(?:https?:)?//(?:www\.)?ntc93\.com(?=[/:?#"\'\s]|$)',output,re.I):
            raise RuntimeError('Remaining legacy URL in '+str(file))
        file.write_text(output,encoding='utf-8')
    return {'assets_downloaded':sum(status.values()),'missing_assets':sorted(missing),'unresolved_links':[{'page':p,'path':u} for p,u in sorted(unresolved)]}
