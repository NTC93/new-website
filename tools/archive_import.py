"""Discover historical public WordPress posts using available standard interfaces."""
from urllib.parse import urljoin,urlsplit,parse_qs,urlencode,urlunsplit
import re, json
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
import requests

BASE='https://ntc93.com/'
HOSTS={'ntc93.com','www.ntc93.com'}
HEADERS={'User-Agent':'NTC93 website migration (public archive)'}
def get(url):
    r=requests.get(url,headers=HEADERS,timeout=(8,25))
    r.raise_for_status()
    if urlsplit(r.url).hostname not in HOSTS: raise ValueError('external redirect')
    return r
def discover(home,route,existing):
    posts={}; errors=[]; evidence=[]; advertised=0
    def add(url,title='',date=''):
        p=route(url)
        if p and p!='/' and p not in existing and not re.match(r'^/news(?:/|$)',p):
            posts.setdefault(p,(title,date))
    # Prefer REST, with its exact published total and actual article URLs.
    for endpoint in ('wp-json/wp/v2/posts','?rest_route=/wp/v2/posts'):
        before=len(posts)
        try:
            def rest(page):
                sep='&' if '?' in endpoint else '?'
                return get(urljoin(BASE,endpoint)+sep+urlencode({'per_page':100,'page':page,'_fields':'link,title,date'}))
            r=rest(1); data=r.json()
            if not isinstance(data,list) or not data: raise ValueError('no post list')
            total=int(r.headers.get('X-WP-Total',0)); pages=int(r.headers.get('X-WP-TotalPages',1))
            for n in range(1,min(pages,100)+1):
                for item in (data if n==1 else rest(n).json()):
                    add(item['link'],BeautifulSoup(item['title']['rendered'],'html.parser').get_text(' ',strip=True),item.get('date','')[:10])
            evidence.append({'method':'REST','total':total,'discovered':len(posts)-before})
            if total and len(posts)>=total:return posts,{'methods':evidence,'expected':total,'errors':errors}
        except Exception as e: errors.append('REST: '+str(e))
    # Standard WordPress/Yoast sitemap, recursively read post sitemap children.
    for root in ('wp-sitemap.xml','sitemap_index.xml','post-sitemap.xml'):
        try:
            queue=[urljoin(BASE,root)];seen=set()
            before=len(posts)
            while queue and len(seen)<100:
                url=queue.pop(0)
                if url in seen or urlsplit(url).hostname not in HOSTS:continue
                seen.add(url)
                xml=BeautifulSoup(get(url).content,'xml') if False else BeautifulSoup(get(url).content,'html.parser')
                for tag in xml.find_all('sitemap'):
                    loc=tag.find('loc')
                    if loc and re.search(r'(?:post|sitemap_index)',loc.get_text(strip=True),re.I):queue.append(loc.get_text(strip=True))
                for tag in xml.find_all('url'):
                    loc=tag.find('loc')
                    if loc and re.search(r'post',urlsplit(url).path,re.I):add(loc.get_text(strip=True))
            if len(posts)>before:evidence.append({'method':'Post sitemap','discovered':len(posts)-before})
        except Exception as e:errors.append('Sitemap: '+str(e))
    # Elementor may paginate with ?e-page-<widget>=N, or pretty pagination.
    # Inspect the actual news widgets and article headings; avoid global menu links.
    archive=urljoin(BASE,'news/')
    def parse_archive(soup):
        nonlocal advertised
        candidates={}
        main=soup.select_one('main') or soup.select_one('.entry-content') or soup
        for a in main.select('article h1 a[href], article h2 a[href], article h3 a[href], article h4 a[href], .elementor-post__title a[href], .elementor-loop-container h2 a[href], .elementor-loop-container h3 a[href], .elementor-loop-container h4 a[href], .elementor-loop-container h5 a[href], .elementor-loop-container h6 a[href], .entry-title a[href]'):
            p=route(a['href']);title=a.get_text(' ',strip=True)
            if p and title and p not in existing and not p.startswith('/news/'):candidates[p]=title
        if not candidates:
            for a in main.select('h2 a[href],h3 a[href],h4 a[href],h5 a[href],h6 a[href]'):
                p=route(a['href']);title=a.get_text(' ',strip=True)
                if p and p not in existing and not p.startswith('/news/') and len(title)>5:candidates[p]=title
        pag=[]
        for a in main.select('a[href]'):
            n=a.get_text(strip=True)
            if n.isdigit() and int(n)>1 and int(n)<=300:
                u=urljoin(archive,a['href'])
                if urlsplit(u).hostname in HOSTS:
                    advertised=max(advertised,int(n));pag.append((int(n),u))
        return candidates,pag
    try:
        soup=BeautifulSoup(get(archive).content,'html.parser');found,links=parse_archive(soup)
        for p,t in found.items():add(p,t)
        perpage=len(found)
        # Discover pagination query keys and infer Elementor widget IDs.
        patterns=set()
        for n,u in links:
            parts=urlsplit(u)
            for k,vs in parse_qs(parts.query).items():
                if vs and vs[0]==str(n):patterns.add(('query',k))
        for widget in soup.select('[data-widget_type][data-id]'):
            typ=widget.get('data-widget_type','')
            if 'posts' in typ or 'loop-grid' in typ:patterns.add(('query','e-page-'+widget['data-id']))
        patterns.update([('path','news/{}/'),('path','news/page/{}/'),('query','paged'),('query','page')])
        def url_for(pattern,n):
            return archive+'?'+urlencode({pattern[1]:n}) if pattern[0]=='query' else urljoin(BASE,pattern[1].format(n))
        def get_page(u):
            try:return parse_archive(BeautifulSoup(get(u).content,'html.parser'))[0]
            except Exception:return {}
        # Only follow pagination schemes that genuinely expose a new page.
        ordered=sorted(patterns)
        with ThreadPoolExecutor(max_workers=4) as pool:
            probes=list(pool.map(get_page,[url_for(p,2) for p in ordered]))
            for pattern,second in zip(ordered,probes):
                if not set(second)-set(found):continue
                before=len(posts)
                for p,t in second.items():add(p,t)
                limit=min(max(advertised,2),300)
                urls=[url_for(pattern,n) for n in range(3,limit+1)]
                for page in pool.map(get_page,urls):
                    for p,t in page.items():add(p,t)
                evidence.append({'method':'Archive pagination '+str(pattern),'discovered':len(posts)-before})
        if advertised>1 and not any('Archive pagination' in e['method'] for e in evidence):errors.append('Archive pagination returned no additional articles')
        evidence.append({'method':'Archive index','pages_advertised':advertised,'first_page_posts':perpage})
    except Exception as e:errors.append('Archive: '+str(e))
    return posts,{'methods':evidence,'expected':max(0,(advertised-1)*5+1) if advertised else 0,'errors':errors}
