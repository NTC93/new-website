"""Public nuLiga team groups, standings and club fixtures. No player/private contacts."""
import json,re,hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin,urlsplit,parse_qs
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
import requests

BASE='https://tvbb.liga.nu/cgi-bin/WebObjects/nuLigaTENDE.woa/wa/'
CLUB=BASE+'clubTeams?club=36381'
HOST='tvbb.liga.nu'
TZ=ZoneInfo('Europe/Berlin')
def text(node):return ' '.join(node.get_text(' ',strip=True).split()) if node else ''
def href(a):
    if not a:return ''
    u=urljoin(BASE,a.get('href',''))
    return u if urlsplit(u).scheme=='https' and urlsplit(u).hostname==HOST else ''
def param(url,key):return parse_qs(urlsplit(url).query).get(key,[''])[0]
def fetch(url):
    r=requests.get(url,timeout=(8,35),headers={'User-Agent':'NTC93 club website / public team standings'})
    r.raise_for_status()
    if urlsplit(r.url).hostname!=HOST:raise ValueError('unexpected host')
    return BeautifulSoup(r.content,'html.parser')
def cells(tr):return tr.find_all(['td','th'],recursive=False)
def canonical(s):return re.sub(r'[^a-z0-9äöüß]','',s.casefold())
def category(name,season):
    n=name.casefold()
    if 'mixed' in n or 'doppel' in n or 'mixed/doppel' in season.casefold():return 'Mixed & Doppel'
    if re.match(r'^(u\s*\d|midcourt|kleinfeld)',n):return 'Jugend'
    if n.startswith('damen'):return 'Seniorinnen' if re.match(r'^damen\s+\d',n) else 'Damen'
    if n.startswith('herren'):return 'Senioren' if re.match(r'^herren\s+\d',n) else 'Herren'
    return 'Weitere Teams'
def season_label(s):
    if 'mixed/doppel' in s.casefold():return s.replace('TVBB ','')
    return re.sub(r'^(?:TVBB|DTB|NO)\s+','',s)
def season_sort(s):
    years=re.findall(r'20\d\d',s)
    return ((int(years[0]) if years else 0),2 if 'winter' in s.casefold() else 1 if 'sommer' in s.casefold() else 0)
def club_rows(soup):
    found={}
    for table in soup.find_all('table'):
        for tr in table.find_all('tr'):
            cs=cells(tr)
            if len(cs)<3:continue
            a=next((x for x in cs[0].select('a[href]') if param(href(x),'team')),None)
            g=next((x for c in cs[1:] for x in c.select('a[href]') if param(href(x),'group') and 'groupPage' in urlsplit(href(x)).path),None)
            if not a or not g:continue
            team_url,group_url=href(a),href(g)
            season=param(group_url,'championship') or param(team_url,'championship')
            tid=param(team_url,'team')
            if not season or not tid:continue
            identity=hashlib.sha256((season+'|'+tid).encode()).hexdigest()[:16]
            name=text(a)
            if not name:continue
            found[identity]={'id':identity,'team_id':tid,'name':name,'season':season_label(season),'championship':season,'category':category(name,season),'group':text(g),'group_url':group_url,'source':team_url,'rank':None,'points':'','table':[],'matches':[],'status':'pending'}
    if not found:raise ValueError('No grouped club teams found')
    return list(found.values())
def headers(table):
    for tr in table.find_all('tr'):
        cs=cells(tr)
        labels=[canonical(text(c)) for c in cs]
        if 'mannschaft' in labels and 'rang' in labels:return 'standings',labels
        if 'heimmannschaft' in labels and 'gastmannschaft' in labels:return 'schedule',labels
    return '',[]
def index(labels,*choices):
    for c in choices:
        if c in labels:return labels.index(c)
    return None
def team_id(cell):
    for a in cell.select('a[href]'):
        p=param(href(a),'team')
        if p:return p
    return ''
def club_name(name):
    return bool(re.match(r'^Neuenhagener (?:Tennisclub|TC) 93(?:\s+(?:I{1,3}|IV|V|VI{0,3}|IX|X))?$',name,re.I))
def suffix(name):
    n=re.sub(r'\s*\(\d+er\)\s*$','',name).strip()
    m=re.search(r'\s+(I{1,3}|IV|V|VI{0,3}|IX|X)$',n)
    return m.group(1) if m else 'I'
def own(team,name,tid):
    if tid:return tid==team['team_id']
    return club_name(name) and suffix(name)==suffix(team['name'])
def score(value):
    m=re.fullmatch(r'(\d+)\s*:\s*(\d+)',value)
    return [int(m[1]),int(m[2])] if m else None
def parse_group(soup):
    standings=[];matches=[]
    for table in soup.find_all('table'):
        kind,labels=headers(table)
        if not kind:continue
        if kind=='standings':
            fields={'rank':index(labels,'rang'),'name':index(labels,'mannschaft'),'played':index(labels,'begegnungen','spieleanzahl'),'wins':index(labels,'s'),'draws':index(labels,'u'),'losses':index(labels,'n'),'points':index(labels,'tabpunkte','punkte','tabellenpunkte'),'match_points':index(labels,'matchpunkte'),'sets':index(labels,'sätze','satze'),'games':index(labels,'spiele')}
            for tr in table.find_all('tr'):
                cs=tr.find_all('td',recursive=False)
                if len(cs)!=len(labels):continue
                def get(k):
                    i=fields[k];return text(cs[i]) if i is not None else ''
                name=get('name');rank=get('rank')
                if not name or not re.fullmatch(r'\d+\.?',rank):continue
                r={k:get(k) for k in fields}
                r['rank']=int(rank.rstrip('.'));r['team_id']=team_id(cs[fields['name']])
                standings.append(r)
        else:
            hi=index(labels,'heimmannschaft');ai=index(labels,'gastmannschaft')
            mi=index(labels,'matchpunkte');si=index(labels,'sätze','satze');gi=index(labels,'spiele');ri=index(labels,'spielbericht')
            date='';time=''
            for tr in table.find_all('tr'):
                cs=tr.find_all('td',recursive=False)
                if len(cs)<5:continue
                # nuLiga includes separate weekday, date/time and marker cells;
                # determine columns from the trailing result cells if headers span them.
                if len(cs)==len(labels):h,a=hi,ai
                else:
                    h=len(cs)-6;a=h+1
                if h is None or a is None or h<1 or a>=len(cs):continue
                lead=' '.join(text(c) for c in cs[:h])
                m=re.search(r'\b(\d{1,2}\.\d{1,2}\.20\d{2})\b',lead)
                t=re.search(r'\b(\d{1,2}:\d{2})\b',lead)
                if m:
                    try:date=datetime.strptime(m[1],'%d.%m.%Y').date().isoformat()
                    except ValueError:date=''
                    time=''
                if t:time=t[1].zfill(5)
                home,away=text(cs[h]),text(cs[a])
                if not date or not home or not away:continue
                def after(offset):
                    pos=a+offset
                    return text(cs[pos]) if pos<len(cs) else ''
                report=next((href(x) for x in cs[-1].select('a[href]') if href(x)), '')
                matches.append({'date':date,'time':time,'home':home,'away':away,'home_id':team_id(cs[h]),'away_id':team_id(cs[a]),'score':score(after(1)),'sets':after(2),'games':after(3),'report':report})
    # A legitimate empty schedule can precede the season; never fabricate ranks.
    if not standings:raise ValueError('No ranking rows found in group')
    return standings,matches
def get_group(url):
    try:return url,parse_group(fetch(url)),None
    except Exception as exc:return url,None,type(exc).__name__+': '+str(exc)[:160]
def main():
    teams=club_rows(fetch(CLUB))
    urls=sorted(set(t['group_url'] for t in teams))
    with ThreadPoolExecutor(max_workers=4) as pool:
        groups={u:(data,err) for u,data,err in pool.map(get_group,urls)}
    ok=0
    for team in teams:
        result,err=groups[team['group_url']]
        if not result:
            team['status']='unavailable';print('::warning::Group unavailable:',team['group'],err);continue
        ranks,fixtures=result
        table=[]
        for r in ranks:
            item={k:v for k,v in r.items() if k!='team_id'}
            item['own']=own(team,r['name'],r['team_id'])
            item['club']=club_name(r['name'])
            table.append(item)
        mine=[r for r in table if r['own']]
        if len(mine)!=1:
            # Fallback only when exact team name/suffix identifies a unique row.
            fallback=[r for r in table if club_name(r['name']) and suffix(r['name'])==suffix(team['name'])]
            if len(fallback)==1:
                for r in table:r['own']=r is fallback[0]
                mine=fallback
        if len(mine)==1:team['rank']=mine[0]['rank'];team['points']=mine[0]['points'];team['status']='ok';ok+=1
        else:team['status']='unmatched';print('::warning::Team identity not uniquely identified:',team['name'],team['season'])
        team['table']=table
        for f in fixtures:
            home=own(team,f['home'],f['home_id']);away=own(team,f['away'],f['away_id'])
            if not home and not away:
                # The same exact names are used on standings and fixtures.
                if len(mine)==1:
                    home=f['home']==mine[0]['name'];away=f['away']==mine[0]['name']
            if home==away:continue
            item={'date':f['date'],'time':f['time'],'home':home,'opponent':f['away'] if home else f['home'],'score':f['score'] if home or f['score'] is None else list(reversed(f['score'])),'report':f['report']}
            team['matches'].append(item)
        team['matches'].sort(key=lambda m:(m['date'],m['time']))
    if not ok:raise ValueError('No teams with matched standings; keep previous file')
    seasons=sorted({t['season'] for t in teams},key=season_sort,reverse=True)
    teams.sort(key=lambda t:(t['category'],t['name'],t['id']))
    data={'updated':datetime.now(TZ).isoformat(timespec='seconds'),'source':CLUB,'seasons':seasons,'teams':teams}
    out=Path('site/teams.json');tmp=out.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');tmp.replace(out)
    print(f'nuLiga teams: {len(teams)}, groups: {len(urls)}, matched standings: {ok}, seasons: {seasons}',flush=True)

if __name__=='__main__':main()
