"""Read the public nuLiga club meeting table, without accessing member data."""
import re, json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
import requests

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
            if len(matches)!=1: continue
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
            if score:
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
def main():
    response=requests.get(URL,timeout=(12,40),headers={'User-Agent':'NTC93 club website / public match schedule'})
    response.raise_for_status()
    rows=parse(BeautifulSoup(response.content,'html.parser'))
    data={'updated':datetime.now(ZoneInfo('Europe/Berlin')).isoformat(timespec='seconds'),'source':URL,'matches':rows}
    out=Path('site/matches.json');out.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    print(f'{len(rows)} public club fixtures imported')
if __name__=='__main__': main()
