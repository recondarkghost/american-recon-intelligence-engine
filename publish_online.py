import json, sqlite3, sys, shutil
from pathlib import Path
import server as engine
import intelligence_upgrade
intelligence_upgrade.install(engine)
import global_sources
global_sources.install(engine)

root = Path(__file__).resolve().parent
ledger = root / "state" / "ledger.json"
ledger.parent.mkdir(exist_ok=True)
columns = "id,issued_at,category,horizon_days,probability,due_at,outcome,brier"

if "--seed" in sys.argv:
    with sqlite3.connect(engine.DB_PATH) as db:
        rows = db.execute("SELECT " + columns + " FROM forecasts ORDER BY id").fetchall()
    ledger.write_text(json.dumps(rows), encoding="utf-8")
    print("Saved existing forecast history:", len(rows))
    sys.exit(0)

engine.init_db()
if ledger.exists():
    with sqlite3.connect(engine.DB_PATH) as db:
        db.executemany(
            "INSERT OR IGNORE INTO forecasts(" + columns + ") VALUES(?,?,?,?,?,?,?,?)",
            json.loads(ledger.read_text(encoding="utf-8-sig"))
        )

data = engine.refresh()
if not any(s["ok"] for s in data["sources"]):
    raise RuntimeError("All feeds failed; keeping previous published dashboard.")

with sqlite3.connect(engine.DB_PATH) as db:
    rows = db.execute("SELECT " + columns + " FROM forecasts ORDER BY id").fetchall()
ledger.write_text(json.dumps(rows), encoding="utf-8")

out = root / ".site"
if out.exists():
    shutil.rmtree(out)
shutil.copytree(root / "static", out, ignore=shutil.ignore_patterns("*backup*"))
(out / "dashboard.json").write_text(json.dumps(data), encoding="utf-8")

page = out / "index.html"
html = page.read_text(encoding="utf-8")
html = html.replace("/api/dashboard", "./dashboard.json")
html = html.replace("/api/refresh", "./dashboard.json")
html = html.replace("Collect new data now", "Load latest published data")
html = html.replace("Could not reach local engine", "Could not load published data")
html = html.replace(
    '<div class="notice">',
    '<div class="notice">Online collection is scheduled every 15 minutes; runs may be delayed. This button loads the latest published collection.<br>'
)
html = html.replace(
    "Math.round((1-data.metrics.brier_score)*100)+'%'",
    "'Brier '+data.metrics.brier_score"
)
html = html.replace(
    "$('#dot').className='dot ok';",
    "$('#dot').className=Date.now()-Date.parse(data.updated_at)>3600000?'dot':'dot ok';"
)
page.write_text(html, encoding="utf-8")
print("Published collection:", data["updated_at"])
