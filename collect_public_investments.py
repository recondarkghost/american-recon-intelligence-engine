import calendar, hashlib, io, json, re, urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent
OHIO = 'https://www.tos.ohio.gov/monthly-portfolio-review/'
PALM = 'https://www.mypalmbeachclerk.com/departments/finance/county-financial-information/investments'

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15) as response:
        return response.read(20000000)

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(v for k,v in attrs if k == 'href' and v)

def ohio_value(pages):
    found = []
    for text in pages:
        if not re.search(r'Board\s+of\s+Deposit\s+Summary', text, re.I):
            continue
        dates = re.findall(r'As\s+of\s+(\d{2}-\d{2}-\d{4})', text, re.I)
        scope = re.search(r'(?s)\bState\s+Investments\b(.*?)\bState\s+Investments\s+Total\b', text)
        if not scope:
            continue
        blocks = re.findall(r'Israel\s+Bonds([\s\S]*?)Money\s+Market\s+Funds', scope.group())
        for block in blocks:
            amounts = re.findall(r'(?<![\d.])\d[\d,]*\.\d{2}(?!\d)', block)
            # The observed multiline row has beginning and ending balances,
            # with all intervening transactions shown as dashes. Other layouts
            # require review rather than guessing which number is the balance.
            if len(amounts) != 2 or '(' in block or re.search(r'-\s*\d', block):
                raise ValueError('Ohio bond row needs manual review; previous figure retained')
            if len(dates) != 1:
                raise ValueError('Missing or ambiguous Ohio summary date')
            stamp = datetime.strptime(dates[0], '%m-%d-%Y').date()
            if stamp > date.today():
                raise ValueError('Future reporting date rejected')
            found.append((int(Decimal(amounts[-1].replace(',', '')) * 100), stamp.isoformat()))
    if len(found) != 1:
        raise ValueError('Missing or ambiguous Ohio summary: previous figure retained')
    return found[0]

def main():
    from pypdf import PdfReader
    output = ROOT/'static/public-investments.json'
    try:
        previous = json.loads(output.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    seeds = [dict(government='Palm Beach County',state='Florida',level='County',country='Israel',amount=1000000000,date='2026-01',basis='Historical announced bond holdings; current balance unverified',source='https://www.wlrn.org/government-politics/2026-07-30/palm-beach-county-israeli-bonds-lawsuit-ruling',publisher='WLRN reporting county announcement',update_status='Manual review required; no automated amount adapter'), dict(government='Ohio state investment accounts',state='Ohio',level='State',country='Israel',amount=262500000,date='2026-06-30',basis='Reported bond holdings',source='https://www.tos.ohio.gov/files/Pdfs/BOD/2026/June2026_MonthlyPortfolioReview.pdf',publisher='Ohio Treasurer monthly portfolio report',update_status='Historical record; checking for newer official reports')]
    records = previous.get('records') or seeds
    records = [dict(r) for r in records]
    now = datetime.now(timezone.utc).isoformat(); checks = []; urls = []
    try:
        raw = get(OHIO); links = Links(); links.feed(raw.decode('utf-8',errors='replace'))
        urls = [urljoin(OHIO,u) for u in links.links if 'monthlyportfolioreview' in u.lower() and '.pdf' in u.lower()]
    except Exception as error:
        checks.append(dict(source='Ohio report index',ok=False,error=str(error)[:180]))
    today = date.today()
    for offset in range(1,5):
        month_index = today.year*12 + today.month-1-offset
        year, month = divmod(month_index,12); month += 1
        urls.append('https://www.tos.ohio.gov/files/Pdfs/BOD/'+str(year)+'/'+calendar.month_name[month]+str(year)+'_MonthlyPortfolioReview.pdf')
    def rank(url):
        name = url.rsplit('/',1)[-1].lower(); years = re.findall(r'20\d{2}',name)
        month = next((i for i in range(1,13) if calendar.month_name[i].lower() in name),0)
        return (int(years[-1]) if years else 0,month)
    urls = sorted(set(u for u in urls if urlparse(u).hostname in ('tos.ohio.gov','www.tos.ohio.gov') and urlparse(u).scheme=='https'),key=rank,reverse=True)
    row = next(r for r in records if r['government']=='Ohio state investment accounts')
    row['update_status']='No newer machine-verified amount obtained; previous dated figure retained'
    for url in urls[:4]:
        try:
            raw = get(url); assert raw.startswith(b'%PDF'),'Not a PDF report'
            pdf = PdfReader(io.BytesIO(raw))
            cents, stamp = ohio_value(page.extract_text(extraction_mode='layout') or '' for page in pdf.pages)
            assert stamp >= row['date'],'Report is older than retained record'
            row.update(amount=cents/100,date=stamp,source=url,source_sha256=hashlib.sha256(raw).hexdigest(),update_status='Amount extracted from official closing-balance summary',basis='Official monthly closing bond balance',last_verified_at=now)
            checks.append(dict(source='Ohio monthly report',ok=True,url=url,report_date=stamp)); break
        except Exception as error:
            checks.append(dict(source='Ohio monthly report',ok=False,url=url,error=str(error)[:180]))
    try:
        raw = get(PALM); digest=hashlib.sha256(raw).hexdigest()
        old_hash=previous.get('palm_index_sha256')
        checks.append(dict(source='Palm Beach County report index',ok=True,amount_verified=False,note='Index checked; amount extraction still requires manual review',content_changed=old_hash!=digest if old_hash else None))
    except Exception as error:
        digest=previous.get('palm_index_sha256'); checks.append(dict(source='Palm Beach County report index',ok=False,amount_verified=False,error=str(error)[:180]))
    payload=dict(checked_at=now,records=records,source_checks=checks,palm_index_sha256=digest,coverage='Partial inventory. Ohio has a guarded amount adapter; Palm Beach County requires manual amount review. Other governments and countries are not covered. Checks are not real-time transfers.')
    text=json.dumps(payload,ensure_ascii=False,indent=2); output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix('.tmp'); temporary.write_text(text,encoding='utf-8'); temporary.replace(output)
    print('PUBLIC INVESTMENT CHECK:',now)
    for r in records: print(r['government'],r['date'],r['amount'],r.get('update_status'))
    for c in checks: print(c)

if __name__=='__main__':
    main()
