import json,re,urllib.request,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
NOW=datetime.now(timezone.utc).isoformat()
CHANNELS=[('France 24','FRANCE24English','EUROPE',48.86,2.35),('Al Jazeera','aljazeeraenglish','MIDDLE EAST',25.29,51.53),('DW News','DWNews','EUROPE',52.52,13.4),('Sky News','SkyNews','EUROPE',51.51,-.13),('CNA','ChannelNewsAsia','ASIA',1.35,103.82),('NHK WORLD','NHKWORLDJAPAN','ASIA',35.68,139.69),('ABC News','ABCNews','AMERICAS',40.71,-74.01),('CBS News','CBSNews','AMERICAS',40.71,-74.01),('NBC News','NBCNews','AMERICAS',40.71,-74.01),('Bloomberg','markets','AMERICAS',40.71,-74.01),('Euronews','euronews','EUROPE',45.76,4.84),('NASA','NASA','AMERICAS',38.91,-77.04)]
def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req,timeout=18) as r:return r.read(5000000).decode('utf-8',errors='replace')
def channel(c):
    name,handle,region,lat,lng=c;rows=[];errors=[];page='';base='https://www.youtube.com/@'+handle
    def item(title,vid,kind,published='',live=False):
        return {'name':name+' | '+title,'id':vid,'region':region,'kind':kind,'lat':lat,'lng':lng,'locationLabel':'Publisher origin; not footage location','published_at':published,'checked_at':NOW,'live':live}
    try:
        page=get(base+'/live');m=re.search(r'ytInitialPlayerResponse\s*=\s*',page)
        if m:
            d=json.JSONDecoder().raw_decode(page[m.end():])[0];v=d.get('videoDetails',{});status=d.get('playabilityStatus',{});live=d.get('microformat',{}).get('playerMicroformatRenderer',{}).get('liveBroadcastDetails',{}).get('isLiveNow')
            if live and status.get('status')=='OK' and status.get('playableInEmbed',True) and re.fullmatch(r'[A-Za-z0-9_-]{11}',v.get('videoId','')):
                rows.append(item(v.get('title','Broadcast'),v['videoId'],'LIVE AT COLLECTION / broadcaster',live=True))
    except Exception as e:errors.append('Live check: '+str(e)[:100])
    try:
        if not page:page=get(base)
        q=chr(34);m=re.search(q+'externalId'+q+r'\s*:\s*'+q+r'(UC[A-Za-z0-9_-]{22})'+q,page) or re.search(q+'channelId'+q+r'\s*:\s*'+q+r'(UC[A-Za-z0-9_-]{22})'+q,page)
        if not m:raise ValueError('Channel ID unavailable')
        root=ET.fromstring(get('https://www.youtube.com/feeds/videos.xml?channel_id='+m.group(1)));ns={'a':'http://www.w3.org/2005/Atom','y':'http://www.youtube.com/xml/schemas/2015'}
        for entry in root.findall('a:entry',ns)[:4]:
            vid=entry.findtext('y:videoId','',ns);title=entry.findtext('a:title','',ns);published=entry.findtext('a:published','',ns)
            try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(published.replace('Z','+00:00'))).total_seconds()
            except Exception:continue
            if 0<=age<=172800 and re.fullmatch(r'[A-Za-z0-9_-]{11}',vid) and not any(x.get('id')==vid for x in rows):rows.append(item(title,vid,'RECENT VIDEO / live status unverified',published))
    except Exception as e:errors.append('Recent videos: '+str(e)[:100])
    return rows,{'source':name,'videos':len(rows),'errors':errors}
def rss_feed(c):
    name,url,country=c;rows=[]
    try:
        root=ET.fromstring(get(url))
        for entry in root.iter():
            if entry.tag.split('}')[-1] not in ['item','entry']:continue
            title=next((x.text for x in entry if x.tag.split('}')[-1]=='title'),'Video') or 'Video' 
            for media in entry.iter():
                u=media.get('url','');mime=media.get('type','');tag=media.tag.split('}')[-1];path=u.split('?')[0].lower()
                if tag not in ['enclosure','content'] or not u.startswith('https://'):continue
                if not (mime.startswith('video/') or path.endswith(('.mp4','.webm','.m3u8'))):continue
                rows.append({'name':name+' | '+title,'url':u,'type':'hls' if path.endswith('.m3u8') else 'video','region':'WORLD','kind':'Publisher video attachment / live status unverified','checked_at':NOW,'live':False});break
            if len(rows)>=4:break
        return rows,{'source':name,'videos':len(rows),'errors':[]}
    except Exception as e:return [],{'source':name,'videos':0,'errors':[str(e)[:100]]}
if __name__=='__main__':
    results=[]
    with ThreadPoolExecutor(max_workers=6) as pool:results.extend(pool.map(channel,CHANNELS))
    try:
        import global_sources
        feeds=list(global_sources.NEWS)+list(global_sources.OFFICIAL)
        with ThreadPoolExecutor(max_workers=6) as pool:results.extend(pool.map(rss_feed,feeds))
    except Exception as e:print('News-feed discovery:',e)
    videos=[];seen=set();checks=[]
    for rows,check in results:
        checks.append(check);print(check['source'],':',check['videos'],'videos','; '.join(check['errors']))
        for row in rows:
            key=row.get('id') or row.get('url')
            if key not in seen:seen.add(key);videos.append(row)
    if not videos:raise SystemExit('No videos collected; empty catalogue not saved')
    videos.sort(key=lambda v:(v.get('live',False),v.get('published_at','')),reverse=True)
    output=Path('static/video-feeds.json');output.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps({'updated_at':NOW,'videos':videos,'source_checks':checks},ensure_ascii=False,indent=2);output.write_text(payload,encoding='utf-8')
    if Path('.site').is_dir():Path('.site/video-feeds.json').write_text(payload,encoding='utf-8')
    print('CATALOGUE:',len(videos),'videos;',sum(v.get('live') is True for v in videos),'broadcasts reported live at collection')
