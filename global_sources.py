"""International feeds with explicit failures and cached evidence."""
import json, time, threading
import intelligence_upgrade as v2

NEWS = [
 ('DW / Germany','https://rss.dw.com/rdf/rss-en-all','Germany'),
 ('France 24 / France','https://www.france24.com/en/rss','France'),
 ('ABC / Australia','https://www.abc.net.au/news/feed/51120/rss.xml','Australia'),
 ('CNA / Singapore','https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml','Singapore'),
 ('Euronews / Europe','https://www.euronews.com/rss?level=theme&name=news','Europe')]
OFFICIAL = [
 ('UK prime minister decisions','https://www.gov.uk/government/organisations/prime-ministers-office-10-downing-street.atom','United Kingdom'),
 ('UK defence decisions','https://www.gov.uk/government/organisations/ministry-of-defence.atom','United Kingdom'),
 ('European Central Bank decisions','https://www.ecb.europa.eu/rss/press.html','Euro area')]
REGIONS={'BBC world news':'United Kingdom','Guardian world news':'United Kingdom','Al Jazeera world news':'Qatar','WHO global health':'Global','WHO Africa health':'Africa','UK foreign policy':'United Kingdom','Federal Reserve decisions':'United States','Medical research / PubMed':'International research'}

def install(engine):
 cache_path=engine.ROOT/'state'/'source_cache.json'
 try:cache=json.loads(cache_path.read_text(encoding='utf-8-sig'))
 except (FileNotFoundError,ValueError):cache={}
 lock=threading.Lock()
 engine.COLLECTORS=[(n,f) for n,f in engine.COLLECTORS if n not in ('GDELT behavior signal','Worldwide news discovery')]
 for kind,feeds in [('News report',NEWS),('Primary source',OFFICIAL)]:
  for name,url,region in feeds:
   REGIONS[name]=region
   engine.COLLECTORS.append((name,lambda n=name,u=url,k=kind:v2.rss(engine,n,u,k)))
 original_collect=engine.collect_source
 def collect(name,fn):
  def retried():
   for attempt in range(2):
    try:return fn()
    except Exception:
     if attempt:raise
     time.sleep(.7)
  result=original_collect(name,retried)
  result['region']=REGIONS.get(name,'Global / United States')
  if result['ok']:
   for a in result.get('details',{}).get('articles',[]):a['country']=result['region']
   result['last_success_at']=engine.utc_now().isoformat()
   with lock:cache[name]=result.copy()
  else:
   old=cache.get(name)
   if old:
    result['last_success_at']=old.get('last_success_at')
    result['details']={'articles':[dict(a,stale=True) for a in old.get('details',{}).get('articles',[])]}
  return result
 engine.collect_source=collect
 original_refresh=engine.refresh
 def refresh():
  data=original_refresh()
  info=data.get('intelligence',{})
  info['model_version']='3.0-international-risk'
  info['coverage']='International reporting and official publications: Africa, Australia, France, Germany, Qatar, Singapore, United Kingdom, United States, Europe and global health/research. Coverage is not exhaustive.'
  cache_path.parent.mkdir(exist_ok=True)
  cache_path.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding='utf-8')
  engine.CACHE['intelligence']=info
  return data
 engine.refresh=refresh
