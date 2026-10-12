import json,re,hashlib
from datetime import datetime,timezone
def install(engine):
    original=engine.build_forecasts
    def read(name):
        path=engine.ROOT/'static'/name
        try:
            raw=path.read_bytes(); data=json.loads(raw)
            return data,{'file':name,'status':'Loaded','sha256':hashlib.sha256(raw).hexdigest()}
        except (OSError,ValueError) as error:
            return {},{'file':name,'status':'Unavailable','error':str(error)[:160]}
    def age(stamp):
        try:
            d=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if d.tzinfo is None: return None
            return (datetime.now(timezone.utc)-d).total_seconds()
        except (ValueError,TypeError,AttributeError): return None
    def build(sources):
        watch,watch_check=read('us-watch.json'); money,money_check=read('money-watch.json'); videos,video_check=read('video-feeds.json')
        forecasts,signals=original(sources)
        context_counts={}
        for forecast in forecasts:
            category=next((c for c in engine.CATEGORIES if c['id']==forecast['id']),{})
            configured=list(category.get('signals',{}))
            eligible=[n for n in configured if n in signals]
            if forecast['id']=='infrastructure' and 'CISA known-exploited vulnerabilities' in signals: eligible.append('CISA known-exploited vulnerabilities')
            if forecast['id']=='weather' and 'USGS earthquakes' in signals: eligible.append('USGS earthquakes')
            panel_key={'infrastructure':'cyber','unrest':'unrest'}.get(forecast['id'])
            panel=watch.get('panels',{}).get(panel_key,{}) if panel_key else {}
            seconds=age(panel.get('collected_at')); fresh=seconds is not None and 0<=seconds<=3600
            reports=[]; seen=set()
            for report in panel.get('reports',[]) if fresh else []:
                published_age=age(report.get('published_at'))
                if published_age is None or not 0<=published_age<=259200: continue
                title=report.get('title',''); key=re.sub('[^a-z0-9]','',title.lower())
                if not key or key in seen: continue
                seen.add(key); reports.append(dict(report,prediction_role='Context only; not a numerical probability input'))
            forecast['watch_context']=reports[:60]
            forecast['input_audit']={'model_status':'Experimental and not calibrated','numeric_inputs_available':eligible,'configured_inputs_missing':[n for n in configured if n not in signals],'watch_collection_fresh':fresh if panel_key else None,'watch_collection_status':panel.get('status') if panel_key else None,'context_report_count':len(reports),'context_role':'Unverified report matches do not change probabilities or reduce uncertainty','money_role':'Historical reported assistance context; no calibrated probability weight','video_role':'Viewing and source context; no calibrated probability weight'}
            for horizon in forecast['horizons'].values():
                horizon['evidence']=[n for n in horizon.get('evidence',[]) if n!='Worldwide reporting (limited weight)']
            context_counts[forecast['id']]=len(reports)
        info=engine.CACHE.setdefault('intelligence',{})
        info['prediction_integration']={'version':'1.0-input-audit','checked_at':datetime.now(timezone.utc).isoformat(),'datasets':[watch_check,money_check,video_check],'context_reports_by_category':context_counts,'money_latest_reported_fiscal_year':money.get('latest_reported_fiscal_year'),'money_source_file_modified':money.get('source_file_last_modified'),'video_collection_at':videos.get('updated_at'),'accuracy_improvement':'Not established; historical outcome testing required'}
        return forecasts,signals
    engine.build_forecasts=build
