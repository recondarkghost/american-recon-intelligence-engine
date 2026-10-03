"""American Recon Intelligence Engine - local, standard-library edition."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = ROOT / "american_recon_intelligence.db"
PORT = int(os.environ.get("AR_INTEL_PORT", "8765"))
REFRESH_SECONDS = 15 * 60
LOCK = threading.Lock()
CACHE = {"updated_at": None, "sources": [], "signals": {}, "forecasts": []}

UA = "AmericanReconIntelligence/1.0 (local research prototype)"


def utc_now():
    return datetime.now(timezone.utc)


def request_json(url, *, method="GET", body=None, timeout=18):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json, application/geo+json")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def request_text(url, timeout=18):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", errors="replace")


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots(
          id INTEGER PRIMARY KEY, collected_at TEXT NOT NULL, source TEXT NOT NULL,
          ok INTEGER NOT NULL, signal REAL, payload TEXT, error TEXT
        );
        CREATE TABLE IF NOT EXISTS forecasts(
          id INTEGER PRIMARY KEY, issued_at TEXT NOT NULL, category TEXT NOT NULL,
          horizon_days INTEGER NOT NULL, probability REAL NOT NULL, due_at TEXT NOT NULL,
          outcome INTEGER, brier REAL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS forecast_daily_unique
          ON forecasts(date(issued_at), category, horizon_days);
        """)


def store_snapshot(source, ok, signal=None, payload=None, error=None):
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "INSERT INTO snapshots(collected_at,source,ok,signal,payload,error) VALUES(?,?,?,?,?,?)",
            (utc_now().isoformat(), source, int(ok), signal,
             json.dumps(payload)[:50000] if payload is not None else None, str(error)[:1000] if error else None),
        )


def collect_source(name, fn):
    started = time.time()
    try:
        signal, details = fn()
        store_snapshot(name, True, signal, details)
        return {"name": name, "ok": True, "signal": signal, "details": details,
                "latency_ms": round((time.time() - started) * 1000)}
    except Exception as exc:
        store_snapshot(name, False, error=exc)
        return {"name": name, "ok": False, "signal": None, "error": str(exc),
                "latency_ms": round((time.time() - started) * 1000)}


def nws_alerts():
    data = request_json("https://api.weather.gov/alerts/active?status=actual&message_type=alert")
    features = data.get("features", [])
    severe_words = ("Tornado", "Hurricane", "Extreme Wind", "Flash Flood", "Blizzard", "Storm Surge")
    severe = sum(1 for f in features if any(w in (f.get("properties", {}).get("event") or "") for w in severe_words))
    signal = min(1.0, severe / 18 + len(features) / 600)
    return signal, {"active_alerts": len(features), "high_impact_alerts": severe}


def usgs_quakes():
    data = request_json("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson")
    mags = [float(f.get("properties", {}).get("mag") or 0) for f in data.get("features", [])]
    m6 = sum(1 for m in mags if m >= 6)
    signal = min(1.0, m6 / 5 + len(mags) / 180)
    return signal, {"magnitude_4_5_week": len(mags), "magnitude_6_week": m6,
                    "largest_magnitude": max(mags, default=0)}


def swpc_space_weather():
    rows = request_json("https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json")
    vals = []
    for row in rows[1:]:
        try:
            vals.append(float(row[1]))
        except (ValueError, TypeError, IndexError):
            pass
    kp = max(vals[-24:], default=0)
    return min(1.0, kp / 9), {"recent_max_kp": round(kp, 1), "scale": "0 quiet to 9 extreme"}


def bls_economy():
    end = utc_now().year
    data = request_json("https://api.bls.gov/publicAPI/v2/timeseries/data/", method="POST",
                        body={"seriesid": ["LNS14000000", "CUUR0000SA0"], "startyear": str(end-2), "endyear": str(end)})
    series = {x["seriesID"]: x.get("data", []) for x in data.get("Results", {}).get("series", [])}
    unemployment = next((float(x["value"]) for x in series.get("LNS14000000", []) if x.get("period", "").startswith("M")), None)
    cpi_rows = [x for x in series.get("CUUR0000SA0", []) if x.get("period", "").startswith("M")]
    cpi = [float(x["value"]) for x in cpi_rows]
    yoy = ((cpi[0] / cpi[12] - 1) * 100) if len(cpi) > 12 else None
    signal = 0.25
    if unemployment is not None:
        signal += max(0, unemployment - 3.5) / 8
    if yoy is not None:
        signal += max(0, abs(yoy - 2) - 1) / 10
    return min(1.0, signal), {"unemployment_percent": unemployment, "cpi_yoy_percent": round(yoy, 2) if yoy is not None else None}


def world_bank():
    url = "https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=8"
    data = request_json(url)
    points = [x for x in (data[1] if isinstance(data, list) and len(data) > 1 else []) if x.get("value") is not None]
    latest = points[0] if points else {}
    growth = float(latest.get("value", 0))
    signal = min(1.0, max(0.0, (3.0 - growth) / 6.0))
    return signal, {"latest_gdp_growth_percent": round(growth, 2), "year": latest.get("date")}


def gdacs_disasters():
    xml = request_text("https://www.gdacs.org/xml/rss.xml")
    root = ET.fromstring(xml)
    items = root.findall(".//item")
    titles = [(x.findtext("title") or "").strip() for x in items]
    signal = min(1.0, len(items) / 35)
    return signal, {"active_global_items": len(items), "examples": titles[:5]}


def gdelt_behavior():
    query = urllib.parse.quote('(protest OR riot OR "civil unrest" OR coup OR "military escalation")')
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={query}&mode=timelinevolraw&format=json&timespan=7d"
    data = request_json(url)
    timeline = data.get("timeline", [])
    values = []
    for block in timeline:
        for point in block.get("data", []):
            try:
                values.append(float(point.get("value", 0)))
            except (TypeError, ValueError):
                pass
    recent = sum(values[-24:]) / max(1, len(values[-24:]))
    historic = sum(values) / max(1, len(values))
    ratio = recent / historic if historic else 1
    return min(1.0, max(0.0, (ratio - .7) / 1.3)), {"recent_to_week_average": round(ratio, 2), "note": "media-volume signal, not verified events"}


COLLECTORS = [
    ("NWS weather alerts", nws_alerts),
    ("USGS earthquakes", usgs_quakes),
    ("NOAA space weather", swpc_space_weather),
    ("BLS economy", bls_economy),
    ("World Bank economy", world_bank),
    ("GDACS global disasters", gdacs_disasters),
    ("GDELT behavior signal", gdelt_behavior),
]


CATEGORIES = [
    {"id": "weather", "name": "Extreme weather & disasters", "annual": .29, "signals": {"NWS weather alerts": .55, "GDACS global disasters": .15, "NOAA space weather": .05}},
    {"id": "economy", "name": "Recession, jobs & housing stress", "annual": .11, "signals": {"BLS economy": .55, "World Bank economy": .25}},
    {"id": "infrastructure", "name": "Power, internet or cyber outage", "annual": .09, "signals": {"NOAA space weather": .25, "NWS weather alerts": .20, "GDELT behavior signal": .10}},
    {"id": "conflict", "name": "War involving the United States", "annual": .025, "signals": {"GDELT behavior signal": .35}},
    {"id": "unrest", "name": "Political unrest or violence", "annual": .07, "signals": {"GDELT behavior signal": .45, "BLS economy": .15}},
    {"id": "health", "name": "Disease outbreak", "annual": .045, "signals": {}},
    {"id": "solar", "name": "Damaging solar or geomagnetic storm", "annual": .035, "signals": {"NOAA space weather": .60}},
]


def probability(category, years, signals):
    base = 1 - math.pow(1 - category["annual"], years)
    adjustment = 0.0
    evidence = []
    for source, weight in category["signals"].items():
        if source in signals:
            centered = signals[source] - .35
            adjustment += centered * weight * (0.12 if years <= 1 else 0.05)
            evidence.append(source)
    value = max(.01, min(.97, base + adjustment))
    uncertainty = min(.28, .07 + .025 * years + (.05 if len(evidence) < 2 else 0))
    return round(value * 100), round(uncertainty * 100), evidence


def build_forecasts(sources):
    signals = {x["name"]: x["signal"] for x in sources if x.get("ok") and x.get("signal") is not None}
    result = []
    for category in CATEGORIES:
        horizons = {}
        for years in (1, 2, 3, 5, 10):
            pct, margin, evidence = probability(category, years, signals)
            horizons[str(years)] = {"probability": pct, "margin": margin, "evidence": evidence}
        result.append({"id": category["id"], "name": category["name"], "horizons": horizons})
    return result, signals


def ledger_forecasts(forecasts):
    now = utc_now()
    with sqlite3.connect(DB_PATH) as db:
        for forecast in forecasts:
            for years, item in forecast["horizons"].items():
                days = int(years) * 365
                db.execute("INSERT OR IGNORE INTO forecasts(issued_at,category,horizon_days,probability,due_at) VALUES(?,?,?,?,?)",
                           (now.isoformat(), forecast["id"], days, item["probability"] / 100, (now + timedelta(days=days)).isoformat()))


def metrics():
    with sqlite3.connect(DB_PATH) as db:
        issued = db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
        scored, avg = db.execute("SELECT COUNT(*), AVG(brier) FROM forecasts WHERE outcome IS NOT NULL").fetchone()
    return {"forecast_records": issued, "scored_records": scored,
            "brier_score": round(avg, 4) if avg is not None else None,
            "accuracy_claim": "Not yet proven" if not scored else "Measured from completed forecasts",
            "target": "Average probability error below 20 percentage points"}


def refresh():
    with LOCK:
        with ThreadPoolExecutor(max_workers=len(COLLECTORS)) as pool:
            sources = list(pool.map(lambda item: collect_source(*item), COLLECTORS))
        forecasts, signals = build_forecasts(sources)
        ledger_forecasts(forecasts)
        CACHE.update({"updated_at": utc_now().isoformat(), "sources": sources, "signals": signals,
                      "forecasts": forecasts, "metrics": metrics(),
                      "disclaimer": "Research prototype. Probabilities are estimates, not exact-event predictions or official warnings."})
        return dict(CACHE)


def background_loop():
    while True:
        time.sleep(REFRESH_SECONDS)
        try:
            refresh()
        except Exception as exc:
            print("Background refresh failed:", exc)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/dashboard"):
            if not CACHE.get("updated_at"):
                refresh()
            self.send_json(CACHE)
            return
        if self.path.startswith("/api/refresh"):
            self.send_json(refresh())
            return
        if self.path.startswith("/api/history"):
            with sqlite3.connect(DB_PATH) as db:
                rows = db.execute("SELECT collected_at,source,ok,signal,error FROM snapshots ORDER BY id DESC LIMIT 100").fetchall()
            self.send_json({"rows": [{"time": r[0], "source": r[1], "ok": bool(r[2]), "signal": r[3], "error": r[4]} for r in rows]})
            return
        super().do_GET()

    def send_json(self, value):
        body = json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/dashboard"):
            super().log_message(fmt, *args)


def main():
    init_db()
    refresh()
    threading.Thread(target=background_loop, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}"
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("\nAmerican Recon Intelligence Engine is running.")
    print("Open:", url)
    print("It refreshes official data every 15 minutes.")
    print("Keep this window open. Press Ctrl+C to stop.\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEngine stopped.")


if __name__ == "__main__":
    main()
