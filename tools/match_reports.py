"""Import only public sporting details of nuLiga meeting reports."""
import re
import json
from pathlib import Path
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit,parse_qs,urlencode
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import requests

BASE='https://tvbb.liga.nu/cgi-bin/WebObjects/nuLigaTENDE.woa/wa/meetingReport'
ZONE=ZoneInfo('Europe/Berlin')
def report_url(raw):
    u=urlsplit(raw or '')
    q=parse_qs(u.query)
    meeting=q.get('meeting',[''])[0];championship=q.get('championship',[''])[0]
    if u.scheme!='https' or u.hostname!='tvbb.liga.nu' or not u.path.endswith('/meetingReport') or not re.fullmatch(r'\d{1,12}',meeting) or not championship or len(championship)>150:return ''
    return BASE+'?'+urlencode({'championship':championship,'federation':'TVBB','meeting':meeting})
def norm(node):
    return ' '.join(node.get_text(' ',strip=True).split()) if node else ''
def pair(value):
    m=re.fullmatch(r'\s*(\d+)\s*:\s*(\d+)\s*',value)
    return [int(m[1]),int(m[2])] if m else None
def expanded(cells):
    out=[]
    for c in cells:
        try:n=min(20,max(1,int(c.get('colspan',1))))
        except (ValueError,TypeError):n=1
        out.extend([c]*n)
    return out
def players(cell):
    # Keep names as published, without ranking positions, LK or links.
    values=[]
    raw=cell.get_text('\n',strip=True)
    for line in raw.splitlines():
        v=' '.join(line.split())
        v=re.sub(r'\s*\(\s*\d+(?:\s*,\s*LK[^)]*)?\s*\)\s*',' ',v,flags=re.I).strip()
        if not v or re.fullmatch(r'[\d\s.,()/+-]+',v) or re.fullmatch(r'LK\s*[\d,.]+',v,re.I):continue
        if v not in values:values.append(v)
    # Some layouts place name and position in the same inline element.
    return ' / '.join(values)[:240]
def parse_report(soup,home):
    sections=[]
    for table in soup.find_all('table'):
        heading=table.find_previous(['h2','h3','h4'])
        heading_text=norm(heading).casefold()
        if 'einzel' in heading_text:kind='Einzel'
        elif 'doppel' in heading_text:kind='Doppel'
        else:continue
        header=None
        for tr in table.find_all('tr'):
            cs=expanded(tr.find_all(['td','th'],recursive=False))
            labels=[re.sub(r'[^a-z0-9äöüß]','',norm(c).casefold()) for c in cs]
            if '1satz' in labels and 'matchpunkte' in labels:
                header=labels;break
        if not header:continue
        start=header.index('1satz')
        point=header.index('matchpunkte')
        setcols=[header.index(k) for k in ('1satz','2satz','3satz') if k in header]
        if start<2 or point<=start:continue
        games=[]
        for tr in table.find_all('tr'):
            raw=tr.find_all('td',recursive=False)
            cs=expanded(raw)
            if not raw or len(cs)!=len(header):continue
            if len(set(map(id,cs[:start])))<2:continue
            if re.match(r'^(einzel|doppel|gesamt)(?:\s|$)',norm(raw[0]),re.I):continue
            # The two team names in the header cover rank/position cells and names.
            # Player names are the last substantive text cell in each side.
            teamcols=header[:start]
            split=next((i for i in range(1,len(teamcols)) if teamcols[i] and teamcols[i]!=teamcols[0]),None)
            if split is None or split<1 or split>=start:split=start//2
            def side(cols):
                for c in reversed(cols):
                    value=players(c)
                    if value and not re.fullmatch(r'(?:w\.?o\.?|sw[ghb]?)',value,re.I):return value
                return ''
            h=side(cs[:split]);a=side(cs[split:start])
            if not h and not a:continue
            points=pair(norm(cs[point]))
            if points not in ([1,0],[0,1],[0,0]):continue
            sets=[]
            for idx in setcols:
                val=norm(cs[idx])
                if not val or val in ('-','–'):continue
                # Preserve published score including tiebreak notation. Never copy free text.
                if re.fullmatch(r'[\d\s:()¹²³⁴⁵⁶⁷⁸⁹⁰+\-\[\]]{1,40}',val) and ':' in val:
                    if not home:
                        left,right=val.split(':',1);val=right.strip()+':'+left.strip()
                    sets.append(val)
            if not home:points=list(reversed(points))
            games.append({'ntc':(h if home else a) or '–','opponent':(a if home else h) or '–','sets':sets,'point':points})
        if games:
            sections.append({'kind':kind,'games':games})
    return sections
def fetch_one(task):
    url,home=task
    try:
        r=requests.get(url,timeout=(8,20),headers={'User-Agent':'NTC93 club website / public match results'},allow_redirects=False)
        r.raise_for_status()
        if r.status_code!=200:raise ValueError('unexpected redirect')
        groups=parse_report(BeautifulSoup(r.content,'html.parser'),home)
        if not groups:raise ValueError('no recognizable sporting rows')
        return task,{'sections':groups,'updated':datetime.now(ZONE).isoformat(timespec='seconds')},None
    except Exception as exc:return task,None,type(exc).__name__+': '+str(exc)[:120]
def enrich(rows):
    try:previous=json.loads(Path('site/matches-previous.json').read_text(encoding='utf-8')).get('matches',[])
    except (OSError,ValueError,AttributeError):previous=[]
    old={(report_url(m.get('report','')),m.get('home')):m for m in previous if isinstance(m,dict) and isinstance(m.get('details'),dict) and m['details'].get('sections')}
    tasks={}
    today=datetime.now(ZONE).date()
    for m in rows:
        url=report_url(m.get('report',''))
        if not url or not isinstance(m.get('score'),list):continue
        m['report']=url
        key=(url,m['home']);prev=old.get(key)
        try:recent=datetime.fromisoformat(m['date']).date()>=today-timedelta(days=14)
        except ValueError:recent=True
        if prev and prev.get('score')==m['score']:
            m['details']=prev['details']
            if not recent:continue
        tasks.setdefault(key,[]).append(m)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for key,details,error in pool.map(fetch_one,tasks):
            for m in tasks[key]:
                if details:m['details']=details
                elif not m.get('details'):m['details_status']='unavailable'
            if error:print('::warning::Meeting detail unavailable:',parse_qs(urlsplit(key[0]).query).get('meeting'),error,flush=True)
    print('Public meeting details:',sum(bool(m.get('details',{}).get('sections')) for m in rows),'of',sum(isinstance(m.get('score'),list) for m in rows),'scored matches',flush=True)
