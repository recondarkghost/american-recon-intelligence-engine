"""Public-source evidence expansion. Model estimates remain uncalibrated."""
import json, re, math, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

TOPICS = {
 'conflict': ('war','missile','military','invasion','ceasefire','nuclear','airstrike','sanction'),
 'unrest': ('protest','riot','unrest','coup','political violence','assassination'),
 'health': ('outbreak','epidemic','pandemic','cholera','mpox','ebola','avian influenza','measles'),
 'economy': ('recession','inflation','bank failure','debt default','interest rate','tariff','unemployment'),
 'weather': ('earthquake','flood','hurricane','cyclone','drought','wildfire','disaster'),
 'infrastructure': ('cyberattack','power outage','blackout','infrastructure','ransomware'),
 'research': ('clinical trial','vaccine','treatment','medical research','discovery')}
FEEDS = [
 ('WHO global health', 'https://www.who.int/rss-feeds/news-english.xml'),
 ('WHO Africa health', 'https://www.afro.who.int/rss.xml'),
 ('UK foreign policy', 'https://www.gov.uk/government/organisations/foreign-commonwealth-development-office.atom'),
 ('Federal Reserve decisions', 'https://www.federalreserve.gov/feeds/press_all.xml')]

def text(v):
 return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', v or '')).strip()
def tags(title):
 t=title.lower()
 return [k for k, words in TOPICS.items() if any(re.search(r'\b'+re.escape(w)+r'\b', t) for w in words)]
def date(v):
 try:
  if re.fullmatch(r'\d{8}T\d{6}Z',v): return datetime.strptime(v,'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).isoformat()
  try: d=datetime.fromisoformat(v.replace('Z','+00:00'))
  except ValueError: d=parsedate_to_datetime(v)
  return d.replace(tzinfo=d.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
 except (ValueError,TypeError,AttributeError,OverflowError): return None

NEWS_FEEDS = [("BBC world news", "https://feeds.bbci.co.uk/news/world/rss.xml"), ("Guardian world news", "https://www.theguardian.com/world/rss"), ("Al Jazeera world news", "https://www.aljazeera.com/xml/rss/all.xml")]

def rss(engine, name, url, kind="Primary source"):
 root=ET.fromstring(engine.request_text(url))
 items=[]
 for node in root.iter():
  if node.tag.split('}')[-1] not in ('item','entry'): continue
  fields={c.tag.split('}')[-1]: c for c in node}
  title=text(''.join(fields['title'].itertext())) if 'title' in fields else ''
  link=fields.get('link')
  href=link.attrib.get('href') or link.text if link is not None else ''
  stamp=next((fields[k].text for k in ('pubDate','published','updated','date') if k in fields),None)
  if not title or not str(href).startswith(('http://','https://')):continue
  items.append({'title':title[:240], 'url':href, 'published_at':date(stamp), 'source':name, 'kind':kind, 'topics':tags(title)})
 if not items:raise ValueError('Feed returned no usable reports')
 return .35, {'reports':len(items), 'articles':items[:60], 'note':'Statements are attributed to their issuing body; news reports require verification.'}

def world_news(engine):
 query='(war OR sanctions OR president OR outbreak OR protest OR recession OR earthquake OR flood OR cyberattack OR vaccine) sourcelang:english'
 url='https://api.gdeltproject.org/api/v2/doc/doc?'+urllib.parse.urlencode({'query':query,'mode':'artlist','format':'json','maxrecords':250,'timespan':'3d','sort':'datedesc'})
 result=engine.request_json(url,timeout=30)
 items=[]
 for a in result.get('articles',[]):
  title=text(a.get('title'))
  if not title or not str(a.get('url','')).startswith(('https://','http://')):continue
  items.append({'title':title[:240],'url':a['url'],'published_at':date(a.get('seendate')), 'source':a.get('domain','Worldwide news'), 'country':a.get('sourcecountry'), 'kind':'News report', 'topics':tags(title)})
 if not items:raise ValueError('No recent news reports returned')
 return .35, {'reports':len(items),'articles':items,'note':'News discovery, not verified events. No private social media or hidden chatter access.'}

def research(engine):
 params={'db':'pubmed','term':'((vaccine[Title] OR outbreak[Title] OR treatment[Title]) AND clinical trial[Publication Type]) AND ("last 30 days"[Publication Date])','retmode':'json','retmax':12,'sort':'pub date'}
 data=engine.request_json('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?'+urllib.parse.urlencode(params))
 ids=data.get('esearchresult',{}).get('idlist',[])
 if not ids:return .35, {'reports':0,'articles':[],'note':'No matching recent clinical trial publications'}
 time.sleep(.4)
 data=engine.request_json('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?'+urllib.parse.urlencode({'db':'pubmed','id':','.join(ids),'retmode':'json'}))
 items=[]
 for ident in ids:
  a=data.get('result',{}).get(ident,{})
  if a.get('title'):items.append({'title':text(a['title'])[:240], 'url':'https://pubmed.ncbi.nlm.nih.gov/'+ident+'/', 'published_at':None, 'date_label':a.get('pubdate',''), 'source':'PubMed / '+a.get('source',''), 'kind':'Research publication', 'topics':['research']})
 return .35, {'reports':len(items),'articles':items,'note':'Research publication does not establish clinical effectiveness; does not increase outbreak risk.'}

def bls(engine):
 end=engine.utc_now().year
 data=engine.request_json('https://api.bls.gov/publicAPI/v2/timeseries/data/',method='POST',body={'seriesid':['LNS14000000','CUUR0000SA0'],'startyear':str(end-2),'endyear':str(end)})
 if data.get('status')!='REQUEST_SUCCEEDED':raise ValueError('BLS: '+'; '.join(data.get('message',[])))
 series={x['seriesID']:x.get('data',[]) for x in data.get('Results',{}).get('series',[])}
 def values(key):
  out={}
  for x in series.get(key,[]):
   try:
    if re.fullmatch(r'M(0[1-9]|1[0-2])',x.get('period','')):
     v=float(x['value'])
     if math.isfinite(v):out[(int(x['year']),int(x['period'][1:]))]=v
   except (ValueError,TypeError,KeyError):pass
  return out
 u,c=values('LNS14000000'),values('CUUR0000SA0')
 if not u and not c:raise ValueError('No usable BLS observations')
 unemployment=u[max(u)] if u else None
 key=max(c) if c else None
 prev=c.get((key[0]-1,key[1])) if key else None
 yoy=(c[key]/prev-1)*100 if prev else None
 signal=.25+(max(0,unemployment-3.5)/8 if unemployment is not None else 0)+(max(0,abs(yoy-2)-1)/10 if yoy is not None else 0)
 return min(1,signal),{'unemployment_percent':unemployment,'cpi_yoy_percent':round(yoy,2) if yoy is not None else None,'observation_month':str(max(u or c))}

def solar(engine):
 rows=engine.request_json('https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json')
 vals=[]
 for r in rows[1:]:
  try:
   v=float(r.get('Kp',r.get('kp'))) if isinstance(r,dict) else float(r[1])
   if math.isfinite(v) and 0<=v<=9:vals.append(v)
  except (ValueError,TypeError,IndexError):pass
 if not vals:raise ValueError('No usable Kp observations')
 kp=max(vals[-24:]);return kp/9,{'recent_max_kp':kp,'scale':'0 quiet to 9 extreme'}

def install(engine):
 original=engine.build_forecasts
 engine.COLLECTORS=[(n,(lambda:bls(engine)) if n=='BLS economy' else (lambda:solar(engine)) if n=='NOAA space weather' else fn) for n,fn in engine.COLLECTORS]
 engine.COLLECTORS += [(name,lambda n=name,u=url:rss(engine,n,u)) for name,url in FEEDS]
 engine.COLLECTORS += [(name,lambda n=name,u=url:rss(engine,n,u,'News report')) for name,url in NEWS_FEEDS]
 engine.COLLECTORS += [('Worldwide news discovery',lambda:world_news(engine)),('Medical research / PubMed',lambda:research(engine))]
 def build(sources):
  forecasts,signals=original(sources)
  articles=[]; seen=set()
  for s in sources:
   for a in s.get('details',{}).get('articles',[]):
    key=re.sub(r'[^a-z0-9]','',a['title'].lower())
    if key in seen:continue
    seen.add(key); articles.append(a)
  articles.sort(key=lambda a:a.get('published_at') or '',reverse=True)
  now=engine.utc_now(); recent=[]
  for a in articles:
   stamp=a.get('published_at')
   if not stamp:continue
   try:age=(now-datetime.fromisoformat(stamp)).total_seconds()/86400
   except ValueError:continue
   if 0<=age<=14:recent.append(a)
  for f in forecasts:
   matching=[a for a in recent if f['id'] in a['topics']]
   primary=[a for a in matching if a['kind']=='Primary source']
   domains={urllib.parse.urlparse(a['url']).netloc for a in matching if a['kind']=='News report'}
   adjustment=min(2,len(primary)*.35)+min(1,len(domains)*.1)
   if f['id']=='weather':adjustment+=min(1,signals.get('USGS earthquakes',0))
   for years,x in f['horizons'].items():
    x['probability']=round(min(97,x['probability']+adjustment*(1 if years=='1' else .5)))
    x['margin']=max(x['margin'],20 if len(primary)>1 else 25)
    x['evidence']+=list(dict.fromkeys(a['source'] for a in primary))[:3]
    x['evidence']+=['Worldwide reporting (limited weight)'] if domains else []
    x['evidence']+=['USGS earthquakes'] if f['id']=='weather' and 'USGS earthquakes' in signals else []
   f['supporting_reports']=matching[:6]
  engine.CACHE['intelligence']={'articles':articles[:200],'model_version':'2.0-public-evidence','method':'Experimental base-rate model with bounded evidence adjustments. Headline counts are not event probabilities. Margins are heuristic, not statistical confidence intervals. No measured accuracy improvement claimed.','coverage':'Public official feeds, worldwide news discovery, and PubMed. Not the whole internet; no private chatter.','sources_checked':len(sources),'recent_reports':len(recent)}
  return forecasts,signals
 engine.build_forecasts=build
