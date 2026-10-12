import csv,io,json,urllib.request
from pathlib import Path
from decimal import Decimal
from datetime import datetime,timezone
URL='https://foreignassistance.gov/static/us_foreign_aid_country.csv' 
req=urllib.request.Request(URL,headers={'User-Agent':'Mozilla/5.0'})
with urllib.request.urlopen(req,timeout=60) as response:
    modified=response.headers.get('Last-Modified');reader=csv.DictReader(io.TextIOWrapper(response,encoding='utf-8-sig',newline=''))
    required={'Country Code','Country Name','Transaction Type Name','Fiscal Year','current_amount'}
    assert required.issubset(set(reader.fieldnames or [])),'Official data columns changed; output not saved' 
    rows=list(reader)
years={};recipients={};seen=set();types=set()
for row in rows:
    transaction=row['Transaction Type Name'].strip();types.add(transaction)
    if transaction not in ['Disbursements','Obligations']:continue
    if not row['Fiscal Year'].strip().isdigit():continue
    year=int(row['Fiscal Year']);code=row['Country Code'].strip();name=row['Country Name'].strip()
    assert name, 'Missing recipient name; output not saved'
    if code.upper() in ('NULL','N/A',''):code='NAME:'+name
    key=(year,code,transaction)
    assert key not in seen,'Duplicate country/year/type summary; inspect source before totaling' 
    seen.add(key);amount=Decimal(row['current_amount'].replace(',','').strip())
    assert amount.is_finite(),'Invalid amount; output not saved' 
    cents=amount*100;assert cents==cents.to_integral_value(),'Unexpected currency precision; output not saved' 
    recipients[code]={'code':code,'name':name,'region':row.get('Region Name','')}
    entry=years.setdefault(str(year),{}).setdefault(code,{'code':code,'name':name,'region':row.get('Region Name',''),'disbursements_cents':None,'obligations_cents':None})
    entry['disbursements_cents' if transaction=='Disbursements' else 'obligations_cents']=int(cents)
assert years and any(x['disbursements_cents'] is not None for y in years.values() for x in y.values()),'No disbursement data; output not saved' 
latest=max(int(y) for y in years if any(x['disbursements_cents'] is not None for x in years[y].values()))
payload={'checked_at':datetime.now(timezone.utc).isoformat(),'source_url':URL,'source_file_last_modified':modified,'currency':'USD','amount_basis':'Current dollars, not inflation adjusted','latest_reported_fiscal_year':latest,'recipients':list(recipients.values()),'years':{y:list(entries.values()) for y,entries in years.items()},'incoming':{'status':'not_connected','amount':None,'note':'Foreign-government receipts require a separate verified dataset.'}}
output=Path('static/money-watch.json');output.parent.mkdir(parents=True,exist_ok=True);text=json.dumps(payload,ensure_ascii=False,indent=2);temporary=output.with_suffix('.tmp');temporary.write_text(text,encoding='utf-8');temporary.replace(output)
if Path('.site').is_dir():Path('.site/money-watch.json').write_text(text,encoding='utf-8')
print('SOURCE TRANSACTION TYPES:',sorted(types))
print('LATEST REPORTED FISCAL YEAR:',latest)
print('RECIPIENT / REGIONAL CATEGORIES:',len(recipients))
print('SOURCE FILE LAST MODIFIED:',modified or 'Not supplied')
for year in sorted(years,key=int,reverse=True)[:3]:
    entries=list(years[year].values());paid=sum(x['disbursements_cents'] or 0 for x in entries);committed=sum(x['obligations_cents'] or 0 for x in entries)
    print('FY',year,'| Reported disbursements USD',Decimal(paid)/100,'| Reported obligations USD',Decimal(committed)/100,'| Categories',len(entries))
print('Money Watch data saved. Missing amounts remain unknown, not zero.')
