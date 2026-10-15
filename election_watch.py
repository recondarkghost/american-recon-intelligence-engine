"""Experimental poll-only 2026 race model. No measured calibration claim."""
import json, math, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timezone, date
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parent
BASE='https://api.pollresults.org/v1.0/politics/results/'
ELECTION=date(2026,11,3)
VERSION='1.0-poll-only-unvalidated'

def flag(v):
    return str(v).strip().lower() not in ('','false','0','none','null')

def fetch(office):
    polls=[]; cursor=None; seen=set()
    for page in range(12):
        args={'limit':100}
        if cursor: args['cursor']=cursor
        req=urllib.request.Request(BASE+office+'?'+urllib.parse.urlencode(args),headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=12) as response: data=json.load(response)
        if not isinstance(data.get('results'),list): raise ValueError('Invalid results schema')
        polls.extend(data['results']); cursor=data.get('cursor')
        if not cursor:return polls,False
        if cursor in seen:raise ValueError('Repeated pagination cursor')
        seen.add(cursor)
    return polls,True

def normalize(p,office,now):
    if str(p.get('cycle'))!='2026' or p.get('electionDate')!='2026-11-03' or flag(p.get('hypothetical')):return []
    stamp=datetime.strptime(p['endDate'],'%m/%d/%y').replace(tzinfo=timezone.utc)
    age=(now.date()-stamp.date()).days
    state=str(p.get('state','')).upper()
    if age<0 or age>45 or len(state)!=2:return []
    rows=[]
    for q in p.get('questions',[]):
        if q.get('stage')!='general' or q.get('subpopulation') or flag(q.get('tracking')):continue
        answers=q.get('answers',[])
        if any(a.get('rankedChoiceRound') is not None or flag(a.get('rankedChoiceReallocated')) or flag(a.get('rankedChoiceFinal')) for a in answers):continue
        pair=[a for a in answers if a.get('party') in ('DEM','REP')]
        if len(pair)!=2 or {a['party'] for a in pair}!={'DEM','REP'}:continue
        d=next(a for a in pair if a['party']=='DEM');r=next(a for a in pair if a['party']=='REP')
        dp,rp=float(d['pct']),float(r['pct']);n=float(q.get('sampleSize') or 0)
        if not all(math.isfinite(x) for x in (dp,rp,n)) or not 0<=dp<=100 or not 0<=rp<=100 or not 0<dp+rp<=100.5 or not 100<=n<=100000:continue
        noncandidate={'undecided','dontknow','notsure','refused','wouldnotvote','willnotvote','noanswer','dontknowrefused','undecideddontknow','undecidedrefused','undecidednotsure','dontknowundecided'}; other=max([float(a.get('pct') or 0) for a in answers if a.get('candidateId') and a.get('party') not in ('DEM','REP') and not any(''.join(c for c in str(a.get(k) or '').lower() if c.isalpha()) in noncandidate for k in ('candidateName','answer'))]+[0])
        race=str(q.get('raceId') or '')
        if not race or not d.get('candidateId') or not r.get('candidateId'):continue
        pollster=str(p.get('pollsterId') or p.get('pollster') or '').strip()
        if not pollster:continue
        rows.append(dict(id=office+':'+state+':'+race,office=office,state=state,seat=str(q.get('seatNumber') or q.get('seatName') or ''),race_id=race,dem=d.get('candidateName') or d.get('answer'),rep=r.get('candidateName') or r.get('answer'),pair=(d['candidateId'],r['candidateId']),dem_pct=dp,rep_pct=rp,n=n,age=age,end=stamp.date().isoformat(),pollster=pollster,pollster_name=p.get('pollster') or pollster,poll_id=str(p.get('pollId') or ''),url=p.get('url') or '',population=q.get('population'),other=other,internal=flag(p.get('internal')) or flag(p.get('partisan'))))
    return rows

def model(rows,now):
    groups={}
    for row in rows:groups.setdefault(row['id'],[]).append(row)
    results=[]
    for ident,items in groups.items():
        items.sort(key=lambda x:(x['end'],x['population']=='lv',x['n']),reverse=True)
        latest=items[0];items=[x for x in items if x['pair']==latest['pair']]
        unique={}
        for x in items:
            if x['pollster'] not in unique:unique[x['pollster']]=x
        items=list(unique.values());weights=[math.sqrt(min(x['n'],1500))*2**(-x['age']/14)*(.5 if x['internal'] else 1) for x in items]
        total=sum(weights);w=[x/total for x in weights];neff=1/sum(x*x for x in w)
        dem=sum(z*x['dem_pct'] for z,x in zip(w,items));rep=sum(z*x['rep_pct'] for z,x in zip(w,items));margin=dem-rep
        variance=sum(z*((x['dem_pct']-x['rep_pct'])-margin)**2 for z,x in zip(w,items))
        sampling=sum(z*z*10000*((x['dem_pct']+x['rep_pct'])/100-((x['dem_pct']-x['rep_pct'])/100)**2)/x['n'] for z,x in zip(w,items))
        days=max(0,(ELECTION-now.date()).days);und=max(0,100-dem-rep)
        sigma=math.sqrt(4**2+variance/max(1,neff)+sampling+(days*.06)**2+(und*.12)**2)
        reason=None
        if now.date()>=ELECTION:reason='Pre-election model stopped; consult official election results'
        elif latest['state'] in ('AK','ME'):reason='Ranked-choice rules require a separate model'
        elif max(x['other'] for x in items)>5:reason='Material third-candidate support; two-candidate model withheld'
        elif len(items)<3 or neff<2:reason='Need at least 3 pollsters and effective poll count of 2'
        elif latest['age']>14:reason='Latest poll is more than 14 days old'
        probability=None if reason else 50*(1+math.erf(margin/(sigma*math.sqrt(2))))
        r={k:latest[k] for k in ('id','office','state','seat','race_id','dem','rep')}
        r.update(dem_poll=round(dem,1),rep_poll=round(rep,1),margin=round(margin,1),dem_win=None if probability is None else round(probability,1),rep_win=None if probability is None else round(100-round(probability,1),1),sigma=round(sigma,2),pollsters=len(items),effective_polls=round(neff,2),latest_poll=latest['end'],status=reason or 'Experimental probability; not historically calibrated',polls=[{k:x[k] for k in ('pollster_name','end','dem_pct','rep_pct','n','url','internal')} for x in items])
        results.append(r)
    return sorted(results,key=lambda x:(x['state'],x['office'],x['seat'],x['id']))

def main():
    now=datetime.now(timezone.utc);output=ROOT/'static/election-watch.json'
    try:previous=json.loads(output.read_text(encoding='utf-8'))
    except (OSError,ValueError):previous={}
    def office(kind):
        try:
            data,truncated=fetch(kind);rows=[];rejected=0
            for p in data:
                try:rows.extend(normalize(p,kind,now))
                except (KeyError,ValueError,TypeError,OverflowError):rejected+=1
            return kind,rows,dict(office=kind,ok=True,truncated=truncated,downloaded=len(data),usable=len(rows),rejected=rejected)
        except Exception as e:return kind,[],dict(office=kind,ok=False,error=str(e)[:180])
    with ThreadPoolExecutor(max_workers=3) as pool: batches=list(pool.map(office,('senate','house','governor')))
    races=[];checks=[]
    for kind,rows,check in batches:
        checks.append(check)
        if check['ok']:
            for r in model(rows,now):r['collected_at']=now.isoformat();races.append(r)
        else:
            for r in previous.get('races',[]):
                if r.get('office')==kind:races.append(dict(r,dem_win=None,rep_win=None,status='Source unavailable; older poll snapshot retained, win odds withheld'))
    payload=dict(checked_at=now.isoformat(),election_date=ELECTION.isoformat(),model_version=VERSION,races=races,source_checks=checks,method='Poll-only prototype: latest observation per pollster and current candidate pair; 14-day recency half-life; square-root sample weight capped at 1500; partisan/internal polls half weight. Normal margin model with assumed 4-point shared error floor, poll disagreement, sampling, undecided and time terms. These assumptions have NOT been fitted or validated against historical outcomes. Poll percentages are not win probabilities. No chamber-control odds: complete race roster and correlated seat model not implemented. States without usable polls are unknown, not necessarily states without elections.',attribution='PollResults.org; poll data from The New York Times, CC BY 4.0. Adapted into American Recon poll averages and experimental estimates. Candidate and poll details remain attributed to original pollsters.',license='https://creativecommons.org/licenses/by/4.0/',data_source='https://pollresults.org/')
    output.parent.mkdir(parents=True,exist_ok=True);tmp=output.with_suffix('.tmp');tmp.write_text(json.dumps(payload,indent=2),encoding='utf-8');tmp.replace(output)
    print('ELECTION WATCH:',len(races),'race snapshots;',sum(r.get('dem_win') is not None for r in races),'experimental forecasts')
    for c in checks:print(c)
if __name__=='__main__':main()
