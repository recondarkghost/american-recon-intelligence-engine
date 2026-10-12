import json, urllib.request, urllib.parse, xml.etree.ElementTree as ET, hashlib
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parent
NOW=datetime.now(timezone.utc).isoformat()
US=chr(34)+'United States'+chr(34)
QUERIES={'cyber':'(cyberattack OR ransomware OR '+chr(34)+'data breach'+chr(34)+') ('+US+' OR American)','unrest':'(protest OR demonstration OR riot) ('+US+' OR '+chr(34)+'Los Angeles'+chr(34)+' OR '+chr(34)+'New York'+chr(34)+')'}
def fetch(task):
    panel,kind,query=task
    check={'panel':panel,'source':kind,'checked_at':NOW,'ok':False}
    try:
        if kind=='GDELT':
            url='https://api.gdeltproject.org/api/v2/doc/doc?'+urllib.parse.urlencode({'query':query,'mode':'artlist','format':'json','maxrecords':100,'timespan':'72h','sort':'datedesc'})
        else:
            url='https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':query+' when:3d','hl':'en-US','gl':'US','ceid':'US:en'})
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=25) as response: raw=response.read(5000000)
        rows=[]
        if kind=='GDELT':
            payload=json.loads(raw); assert isinstance(payload.get('articles'),list),'Unexpected GDELT response' 
            for a in payload['articles']:
                rows.append({'title':a.get('title',''),'url':a.get('url',''),'source':a.get('domain','GDELT-discovered publisher'),'publisher_country':a.get('sourcecountry'),'indexed_at':a.get('seendate'),'published_at':None})
        else:
            root=ET.fromstring(raw)
            for a in root.findall('.//item'):
                published=None
                try: published=parsedate_to_datetime(a.findtext('pubDate')).astimezone(timezone.utc).isoformat()
                except (TypeError,ValueError,AttributeError): pass
                rows.append({'title':a.findtext('title') or '', 'url':a.findtext('link') or '', 'source':a.findtext('source') or 'Google News indexed publisher','publisher_country':None,'indexed_at':None,'published_at':published})
        valid=[]
        for a in rows:
            if not a['title'] or urllib.parse.urlparse(a['url']).scheme not in ('https','http'): continue
            a.update(id=hashlib.sha256(a['url'].encode()).hexdigest()[:20],discovered_via=kind,first_detected_at=NOW,review_status='Report awaiting verification',us_target_status='U.S. relevance requires source review',attacker_country=None,attribution_status='Not established',event_status='Ongoing status not established')
            valid.append(a)
        check.update(ok=True,reports=len(valid)); return check,valid
    except Exception as error:
        check['error']=str(error)[:180]; return check,[]
def main():
    output=ROOT/'static'/'us-watch.json'; old={}
    try: old=json.loads(output.read_text(encoding='utf-8'))
    except (FileNotFoundError,ValueError): pass
    tasks=[(panel,kind,query) for panel,query in QUERIES.items() for kind in ('GDELT','Google News RSS')]
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(fetch,tasks))
    panels={}
    for panel in QUERIES:
        checks=[c for c,rows in results if c['panel']==panel]
        previous=old.get('panels',{}).get(panel,{})
        prior={a['id']:a for a in previous.get('reports',[]) if a.get('id')}
        found={}
        for check,rows in results:
            if check['panel']!=panel: continue
            for a in rows:
                a['first_detected_at']=prior.get(a['id'],{}).get('first_detected_at',NOW); found[a['id']]=a
        successful=sum(c['ok'] for c in checks)
        if successful:
            reports=list(found.values()); collected=NOW; status='Collected' if successful==len(checks) else 'Partial collection: some feeds unavailable' 
        else:
            reports=previous.get('reports',[]); collected=previous.get('collected_at'); status='All feeds unavailable: previous reports retained' 
        panels[panel]={'collected_at':collected,'status':status,'source_checks':checks,'reports':reports,'measurement':'Source reports, not verified incident counts'}
        print(panel.upper()+': '+status+' | '+str(len(reports))+' reports')
        for c in checks: print(c['source']+': '+('OK' if c['ok'] else c.get('error','Unavailable')))
    payload={'checked_at':NOW,'panels':panels,'coverage':'Keyword-discovered reporting; incomplete coverage. U.S. relevance, event location, ongoing status and attacker attribution require source verification. Publisher country is not attacker country.'}
    text=json.dumps(payload,ensure_ascii=False,indent=2); output.parent.mkdir(parents=True,exist_ok=True)
    tmp=output.with_suffix('.tmp'); tmp.write_text(text,encoding='utf-8'); tmp.replace(output)
    site=ROOT/'.site' 
    if site.is_dir():
        tmp=site/'us-watch.json.tmp'; tmp.write_text(text,encoding='utf-8'); tmp.replace(site/'us-watch.json')
    print('U.S. watch data saved. No country attribution or riot classification inferred.')
if __name__=='__main__': main()
