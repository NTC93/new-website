"""Public nuLiga team groups, standings and club fixtures. No player/private contacts."""
import json,re,hashlib,time as clock
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin,urlsplit,parse_qs,urlencode
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
def group_link(url):
    championship=param(url,'championship');group=param(url,'group')
    return BASE+'groupPage?'+urlencode({'championship':championship,'group':group}) if championship and group else url
def is_placement(name):
    return bool(re.search(r'platzierung|play[\s-]?off|endrunde|zwischenrunde|finalrunde|halbfinale|viertelfinale',name,re.I))
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
            team_url,group_url=href(a),group_link(href(g))
            season=param(group_url,'championship') or param(team_url,'championship')
            tid=param(team_url,'team')
            if not season or not tid:continue
            identity=hashlib.sha256((season+'|'+tid).encode()).hexdigest()[:16]
            name=text(a)
            if not name:continue
            found[(identity,param(group_url,'group'))]={'id':identity,'team_id':tid,'name':name,'season':season_label(season),'championship':season,'category':category(name,season),'group':text(g),'group_url':group_url,'source':team_url,'rank':None,'points':'','table':[],'matches':[],'status':'pending','placement':is_placement(text(g)),'rounds':[]}
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
def parse_group(soup,placement=False):
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
                # nuLiga uses a dedicated icon cell (alt/title="Aufsteiger").
                # Read only status icons/labels, never infer promotion from rank.
                marks=[]
                for marker in tr.select('img[alt],img[title],span[title],abbr[title]'):
                    marks.extend(str(marker.get(a,'')) for a in ('alt','title'))
                if fields['rank'] is not None:
                    for cell in cs[:fields['rank']]:
                        marks.append(text(cell))
                r['promotion']=any(re.search(r'\bAufsteiger\b|\bAufstiegsplatz\b',m,re.I) for m in marks)
                r['relegation']=any(re.search(r'\bAbsteiger\b|\bAbstiegsplatz\b',m,re.I) for m in marks)
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
                if (not date and not placement) or not home or not away:continue
                def after(offset):
                    pos=a+offset
                    return text(cs[pos]) if pos<len(cs) else ''
                report=next((href(x) for x in cs[-1].select('a[href]') if href(x)), '')
                round_label=''
                if placement:
                    round_label=next((text(c) for c in cs[:h] if re.search(r'platz|finale|runde',text(c),re.I)), '')
                    if not round_label:
                        number=next((text(c) for c in reversed(cs[:h]) if re.fullmatch(r'\d{1,2}',text(c))), '')
                        if number:round_label='Spiel '+number
                matches.append({'round_label':round_label,'date':date,'time':time,'home':home,'away':away,'home_id':team_id(cs[h]),'away_id':team_id(cs[a]),'score':score(after(1)),'sets':after(2),'games':after(3),'report':report})
    # A legitimate empty schedule can precede the season; never fabricate ranks.
    if not standings and not (placement and matches):raise ValueError('No ranking rows found in group' if not placement else 'No placement matches found')
    return standings,matches
def get_group(task):
    url,placement=task
    err=''
    for attempt in range(3):
        try:return url,parse_group(fetch(url),placement),None
        except Exception as exc:
            err=type(exc).__name__+': '+str(exc)[:160]
            if attempt<2:clock.sleep(1.5*(attempt+1))
    return url,None,err
def previous_data():
    try:return json.loads(Path('site/teams-previous.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
def old_group_key(t):
    return (t.get('championship'),t.get('team_id'),param(t.get('group_url',''),'group'))
def merge_rounds(teams):
    main=[t for t in teams if not t['placement']]
    for extra in [t for t in teams if t['placement']]:
        candidates=[t for t in main if t['championship']==extra['championship'] and t['team_id']==extra['team_id']]
        if len(candidates)!=1:
            candidates=[t for t in main if t['championship']==extra['championship'] and canonical(t['name'])==canonical(extra['name'])]
        if len(candidates)!=1:
            print('::warning::Placement round could not be uniquely assigned:',extra['name'],extra['group'])
            main.append(extra);continue
        parent=candidates[0]
        if parent['id']!=extra['id']:
            parent.setdefault('aliases',[]).append(extra['id'])
        parent['rounds'].append({k:extra[k] for k in ('group','group_url','table','matches','status','placement')})
        print('Placement round assigned:',extra['name'],extra['group'],'->',parent['group'],flush=True)
    return main
def main():
    teams=club_rows(fetch(CLUB))
    urls=sorted({t['group_url']:t['placement'] for t in teams}.items())
    previous=previous_data()
    old={old_group_key(t):t for t in previous.get('teams',[]) if isinstance(t,dict) and t.get('table')}
    with ThreadPoolExecutor(max_workers=2) as pool:
        groups={u:(data,err) for u,data,err in pool.map(get_group,urls)}
    ok=0
    for team in teams:
        result,err=groups[team['group_url']]
        if not result:
            saved=old.get(old_group_key(team))
            if saved:
                for k in ('rank','points','table','matches','promotion_status','relegation_status'):
                    if k in saved:team[k]=saved[k]
                team['status']='cached'
                team['data_updated']=saved.get('data_updated') or previous.get('updated','')
                ok+=1
                print('::warning::Group refresh failed, last valid data retained:',team['name'],team['group'],err)
            else:
                team['status']='unavailable'
                print('::warning::Group unavailable:',team['name'],team['group'],err)
            continue
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
        elif team['placement'] and not table:team['status']='ok'
        else:team['status']='unmatched';print('::warning::Team identity not uniquely identified:',team['name'],team['season'])
        # A current promotion position is not yet a confirmed season result.
        # Only mark a completed competition as promoted when its entire schedule
        # has been played, not simply when the team occupies first place.
        complete=bool(fixtures) and all(f['score'] is not None for f in fixtures)
        for row in table:
            row['promotion_status']=('promoted' if complete else 'position') if row.get('promotion') else ''
        for row in table:
            row['relegation_status']=('relegated' if complete else 'position') if row.get('relegation') else ''
        team['promotion_status']=mine[0]['promotion_status'] if len(mine)==1 else ''
        team['relegation_status']=mine[0]['relegation_status'] if len(mine)==1 else ''
        team['table']=table
        for f in fixtures:
            home=own(team,f['home'],f['home_id']);away=own(team,f['away'],f['away_id'])
            if not home and not away:
                # The same exact names are used on standings and fixtures.
                if len(mine)==1:
                    home=f['home']==mine[0]['name'];away=f['away']==mine[0]['name']
            if home==away:continue
            item={'round_label':f.get('round_label',''),'date':f['date'],'time':f['time'],'home':home,'opponent':f['away'] if home else f['home'],'score':f['score'] if home or f['score'] is None else list(reversed(f['score'])),'report':f['report']}
            team['matches'].append(item)
        team['matches'].sort(key=lambda m:(m['date'] or '9999',m['time']))
        if team['placement']:print('Placement fixtures imported:',team['name'],team['group'],len(team['matches']),flush=True)
    if not ok:raise ValueError('No teams with matched standings; keep previous file')
    teams=merge_rounds(teams)
    seasons=sorted({t['season'] for t in teams},key=season_sort,reverse=True)
    teams.sort(key=lambda t:(t['category'],t['name'],t['id']))
    data={'updated':datetime.now(TZ).isoformat(timespec='seconds'),'source':CLUB,'seasons':seasons,'teams':teams}
    out=Path('site/teams.json');tmp=out.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');tmp.replace(out)
    print(f'nuLiga teams: {len(teams)}, groups: {len(urls)}, matched standings: {ok}, seasons: {seasons}',flush=True)

if __name__=='__main__':main()
