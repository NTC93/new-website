"""Read the public nuLiga club meeting table, without accessing member data."""
import re, json
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
import requests
from match_reports import enrich

URL = 'https://tvbb.liga.nu/cgi-bin/WebObjects/nuLigaTENDE.woa/wa/clubMeetings?club=36381'
TEAM = re.compile(r'^Neuenhagener (?:Tennisclub|TC) 93(?:\s+(I{1,3}|IV|V|VI{0,3}|IX|X))?$', re.I)
def norm(s): return ' '.join(s.split())
def team_label(league, suffix):
    m=re.match(r'^(U\d+\s*[mw]?|[HD](?:\d+)?)\b', league, re.I)
    key=m.group(1).replace(' ','') if m else league
    if key.startswith('U'):
        key=key.replace('m',' männlich').replace('w',' weiblich')
    elif key.startswith('H'): key='Herren'+(' '+key[1:] if key[1:] else '')
    elif key.startswith('D'): key='Damen'+(' '+key[1:] if key[1:] else '')
    return key+(' '+suffix if suffix else '')
def parse(soup):
    rows=[]; seen=set()
    for table in soup.find_all('table'):
        heading=norm(table.get_text(' ',strip=True))
        if not all(x in heading for x in ('Heimmannschaft','Gastmannschaft','Matchpunkte')): continue
        last_date=None; last_time=None
        for tr in table.find_all('tr'):
            cells=tr.find_all('td',recursive=False)
            if len(cells)<7: continue
            txt=[norm(c.get_text(' ',strip=True)) for c in cells]
            matches=[]
            for i,c in enumerate(cells):
                for a in c.find_all('a'):
                    m=TEAM.fullmatch(norm(a.get_text(' ',strip=True)))
                    if m: matches.append((i,m.group(1) or '')); break
            if not matches: continue
            idx,suffix=matches[0]
            # Team cells are adjacent; league is immediately before home.
            # The match result, sets, games and report follow the guest.
            home_index=len(cells)-6
            away_index=home_index+1
            if idx not in (home_index,away_index): continue
            if home_index<2: continue
            is_home=idx==home_index
            leading=' '.join(txt[:home_index-2])
            d=re.search(r'\b(\d{2}\.\d{2}\.\d{4})\b',leading)
            t=re.search(r'\b(\d{1,2}:\d{2})\b',leading)
            if d:
                try: last_date=datetime.strptime(d.group(1),'%d.%m.%Y').date().isoformat()
                except ValueError: last_date=None
                last_time=None
            if t: last_time=t.group(1).zfill(5)
            if not last_date: continue
            league=txt[home_index-1]; venue=txt[home_index-2]
            opponent_cell=cells[away_index if is_home else home_index]
            opponent_link=opponent_cell.find('a')
            opponent=norm(opponent_link.get_text(' ',strip=True) if opponent_link else opponent_cell.get_text(' ',strip=True))
            if not opponent or not league: continue
            score=re.fullmatch(r'(\d+)\s*:\s*(\d+)',txt[away_index+1])
            result=None
            if score and tuple(map(int,score.groups()))!=(0,0):
                a,b=map(int,score.groups())
                result=[a,b] if is_home else [b,a]
            report=cells[-1].find('a',href=True)
            href=urljoin(URL,report['href']) if report else ''
            if urlsplit(href).hostname!='tvbb.liga.nu': href=''
            team=team_label(league,suffix)
            key=(last_date,last_time,team,opponent,is_home)
            if key in seen: continue
            seen.add(key)
            rows.append(dict(date=last_date,time=last_time,team=team,league=league,opponent=opponent,home=is_home,venue=venue,score=result,report=href))
    if not rows: raise ValueError('No matching nuLiga rows found; do not overwrite existing data')
    return sorted(rows,key=lambda x:(x['date'],x['time'] or '',x['team']))
def compact(value):
    return re.sub(r'[^a-z0-9äöüß]','',str(value or '').casefold())
def team_group_label(name):
    name=re.sub(r'\s*\(\d+er\)\s*$','',name).strip()
    return re.sub(r'^(Herren|Damen)\s+0+(?=\s|$)',r'\1',name)
def merge_team_fixtures(rows):
    path=Path('site/teams.json')
    if not path.is_file():return rows
    data=json.loads(path.read_text(encoding='utf-8'))
    today=datetime.now(ZoneInfo('Europe/Berlin')).date()
    start=(today-timedelta(days=35)).isoformat()
    end=(today+timedelta(days=180)).isoformat()
    def key(m):
        return (m.get('date'),compact(m.get('opponent')),bool(m.get('home')))
    existing={}
    for m in rows:existing.setdefault(key(m),[]).append(m)
    added=0
    for team in data.get('teams',[]):
        for group in [team,*team.get('rounds',[])]:
            for f in group.get('matches',[]):
                if not start<=str(f.get('date') or '')<=end:continue
                if not f.get('opponent'):continue
                name=team_group_label(team['name'])
                m=dict(date=f['date'],time=f.get('time') or None,team=name,league=group['group'],opponent=f['opponent'],home=f['home'],venue='',score=f.get('score'),report=f.get('report') or '')
                if m['score']==[0,0]:m['score']=None
                candidates=existing.get(key(m),[])
                direct=[x for x in candidates if compact(x['team'])==compact(name)]
                # Match by meeting ID if both sources provide it.
                from urllib.parse import parse_qs
                mid=parse_qs(urlsplit(m['report']).query).get('meeting')
                same=[x for x in candidates if mid and parse_qs(urlsplit(x.get('report','')).query).get('meeting')==mid]
                hit=same or direct
                if len(hit)==1:
                    target=hit[0]
                    if not target.get('time') and m['time']:target['time']=m['time']
                    if target.get('score') is None and m['score'] is not None:target['score']=m['score']
                    if not target.get('report'):target['report']=m['report']
                    continue
                if len(hit)>1:continue
                # A unique same-time opponent and matching age class may use
                # different short names in the club and group reports.
                def age(n):
                    return re.search(r'\d+',n or '')
                similar=[x for x in candidates if x.get('time')==m['time'] and compact(x['team']).startswith(compact(name.split()[0])) and (age(x['team']).group() if age(x['team']) else '')==(age(name).group() if age(name) else '')]
                if len(similar)==1:continue
                rows.append(m);existing.setdefault(key(m),[]).append(m);added+=1
    print('Additional matchcenter fixtures from team groups:',added,flush=True)
    return rows
def main():
    response=requests.get(URL,timeout=(12,40),headers={'User-Agent':'NTC93 club website / public match schedule'})
    response.raise_for_status()
    rows=parse(BeautifulSoup(response.content,'html.parser'))
    rows=merge_team_fixtures(rows)
    now=datetime.now(ZoneInfo('Europe/Berlin'))
    for row in rows:
        try:row['start_at']=datetime.fromisoformat(row['date']+'T'+row['time']).replace(tzinfo=ZoneInfo('Europe/Berlin')).isoformat()
        except (ValueError,TypeError):row['start_at']=None
    today=now.date().isoformat()
    print('Matchcenter today:',json.dumps([{'team':m['team'],'time':m['time'],'opponent':m['opponent'],'score':m['score']} for m in rows if m['date']==today],ensure_ascii=False),flush=True)
    rows.sort(key=lambda m:(m['date'],m.get('time') or '',m['team']))
    enrich(rows)
    data={'updated':datetime.now(ZoneInfo('Europe/Berlin')).isoformat(timespec='seconds'),'source':URL,'matches':rows}
    out=Path('site/matches.json');out.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    print(f'{len(rows)} public club fixtures imported')
if __name__=='__main__': main()
