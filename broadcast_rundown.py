"""Freeze a dated source-article rundown at the first successful publish after 6 PM ET."""
import json,re
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent

def select(data,now):
    counts={};seen=set();rows=[];wordsets=[]
    articles=sorted(data.get('intelligence',{}).get('articles',[]),key=lambda a:a.get('published_at') or '',reverse=True)
    for a in articles:
        try:
            stamp=datetime.fromisoformat(a['published_at'].replace('Z','+00:00'))
            if a.get('stale') or not timedelta(minutes=-5)<=now-stamp<=timedelta(hours=24):continue
            u=urlsplit(a['url']);assert u.scheme in ('https','http') and u.hostname
            title=str(a['title']).strip();key=re.sub(r'\W+','',title.lower())
            source=str(a.get('source') or u.hostname)
            words=set(re.findall(r'[a-z]{4,}',title.lower()))
            if not key or key in seen or counts.get(source,0)>=2:continue
            if any(len(words&w)/max(len(words),len(w),1)>.65 for w in wordsets):continue
            seen.add(key);wordsets.append(words);counts[source]=counts.get(source,0)+1
            rows.append(dict(title=title,url=a['url'],source=source,published_at=a['published_at'],topic=(a.get('topics') or ['News'])[0],kind=a.get('kind','News report')))
            if len(rows)==10:break
        except (KeyError,ValueError,TypeError,AssertionError):continue
    return rows

def build(out,data,now=None):
    now=now or datetime.now(timezone.utc)
    try:local=now.astimezone(ZoneInfo('America/New_York'))
    except Exception:
        print('BROADCAST: Eastern timezone data unavailable; previous dated edition retained');return
    target=ROOT/'static/broadcast-rundown.json'
    try:previous=json.loads(target.read_text(encoding='utf-8'))
    except (OSError,ValueError):previous={}
    if previous.get('show_date')==local.date().isoformat():return
    if local.hour<18:return
    try:
        stamp=datetime.fromisoformat(data['updated_at'].replace('Z','+00:00'))
        if not timedelta(minutes=-5)<=now-stamp<=timedelta(hours=1):raise ValueError('stale collection')
    except (KeyError,TypeError,ValueError):
        print('BROADCAST: collection is stale; previous dated edition retained');return
    rows=select(data,now)
    if not rows:
        print('BROADCAST: no fresh source reports; previous edition retained');return
    result=dict(show_date=local.date().isoformat(),prepared_at=now.isoformat(),reports=rows,
        note='Original source articles selected from collected feeds, not independently verified or AI-written briefings. Publication is scheduled after 6 PM Eastern; job delays are possible.')
    target.parent.mkdir(exist_ok=True,parents=True);tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(target)
    (out/'broadcast-rundown.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    print('BROADCAST:',result['show_date'],len(rows),'source reports prepared')
