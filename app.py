"""
Currency Converter — FastAPI + SQLite backend (serves index.html too).

Run:  uvicorn app:app --reload
Open: http://127.0.0.1:8000
"""
import json
import logging
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "currency.db"

load_dotenv(BASE_DIR / ".env")  # reads EXCHANGE_API_KEY from the .env file next to app.py

# ExchangeRate-API: uses your key if EXCHANGE_API_KEY is set, otherwise the open-access endpoint
API_KEY = os.getenv("EXCHANGE_API_KEY", "").strip()
LIVE_URL = (
    f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/USD"
    if API_KEY
    else "https://open.er-api.com/v6/latest/USD"
)
SOURCE = "keyed" if API_KEY else "open"
CACHE_KEY = f"USD:{SOURCE}"   # cached rates are tagged by source, so adding a key forces a fresh fetch

log = logging.getLogger("uvicorn.error")   # shows up in the uvicorn terminal


def masked_key() -> str:
    return f"...{API_KEY[-4:]}" if len(API_KEY) >= 4 else ("(set)" if API_KEY else "(none)")
TREND_URL = "https://api.frankfurter.app"            # free 30-day history (ECB data)
CACHE_TTL = 3600                                     # refresh live rates every hour

TRAVEL_DEFAULT = ["USD", "EUR", "GBP", "JPY", "AUD"]
TRAVEL_FALLBACK = ["CHF", "CAD"]

_rate_cache = {"rates": None, "fetched": 0.0, "updated": ""}
_trend_cache: dict = {}
_lock = threading.Lock()


# ---------------------------------------------------------------- database
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_cur TEXT NOT NULL,
                to_cur TEXT NOT NULL,
                amount REAL NOT NULL,
                result REAL NOT NULL,
                rate REAL NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_cur TEXT NOT NULL,
                to_cur TEXT NOT NULL,
                UNIQUE (from_cur, to_cur)
            );
            CREATE TABLE IF NOT EXISTS hist_usd (
                date TEXT PRIMARY KEY,
                rates_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rate_cache (
                base TEXT PRIMARY KEY,
                rates_json TEXT NOT NULL,
                updated TEXT,
                fetched_at REAL NOT NULL
            );
            """
        )


def save_rates_to_db(rates: dict, updated: str, fetched: float):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO rate_cache (base, rates_json, updated, fetched_at) VALUES (?, ?, ?, ?)",
            (CACHE_KEY, json.dumps(rates), updated, fetched),
        )


def load_rates_from_db():
    """Restore the last saved rates so the app works right after a restart (and offline).

    Rates saved by the same source count as fresh (within the TTL). Rates from a different
    source (e.g. saved before you added your key) are kept only as an offline fallback,
    so the first request still calls the API with your key.
    """
    with get_db() as conn:
        same = conn.execute("SELECT * FROM rate_cache WHERE base = ?", (CACHE_KEY,)).fetchone()
        row = same or conn.execute(
            "SELECT * FROM rate_cache ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
    if row:
        _rate_cache.update(
            rates=json.loads(row["rates_json"]),
            updated=row["updated"],
            fetched=row["fetched_at"] if same else 0.0,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    load_rates_from_db()
    if API_KEY:
        log.info("ExchangeRate-API: using your API key %s (v6.exchangerate-api.com)", masked_key())
    else:
        log.warning("ExchangeRate-API: no EXCHANGE_API_KEY found in %s, using open endpoint", BASE_DIR / ".env")
    yield


app = FastAPI(title="Currency Converter", lifespan=lifespan)


# ---------------------------------------------------------------- rates
def get_rates() -> dict:
    """USD-based rate table, cached in memory for CACHE_TTL seconds."""
    if _rate_cache["rates"] and time.time() - _rate_cache["fetched"] < CACHE_TTL:
        return _rate_cache["rates"]
    with _lock:
        # another request may have refreshed while we waited
        if _rate_cache["rates"] and time.time() - _rate_cache["fetched"] < CACHE_TTL:
            return _rate_cache["rates"]
        try:
            log.info("Fetching live rates from ExchangeRate-API (%s)...", SOURCE)
            resp = httpx.get(LIVE_URL, timeout=10)
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if resp.status_code != 200 or data.get("result") != "success":
                # e.g. invalid-key, inactive-account, quota-reached
                raise ValueError(f"HTTP {resp.status_code}, error-type: {data.get('error-type', 'unknown')}")
            log.info("Live rates fetched OK (%d currencies)", len(data.get("conversion_rates") or data.get("rates") or {}))
            # keyed endpoint returns "conversion_rates", open endpoint returns "rates"
            rates = data.get("conversion_rates") or data["rates"]
            _rate_cache.update(
                rates=rates,
                fetched=time.time(),
                updated=data.get("time_last_update_utc", ""),
            )
            save_rates_to_db(rates, _rate_cache["updated"], _rate_cache["fetched"])
        except Exception as exc:
            log.error("ExchangeRate-API request failed: %s", exc)
            if _rate_cache["rates"]:          # serve stale data rather than fail
                return _rate_cache["rates"]
            raise HTTPException(503, "Exchange rate service is unavailable. Try again shortly.")
    return _rate_cache["rates"]


def cross_rate(frm: str, to: str, rates: dict) -> float:
    if frm not in rates or to not in rates:
        raise HTTPException(400, f"Unsupported currency: {frm if frm not in rates else to}")
    return rates[to] / rates[frm]


def norm(code: str) -> str:
    return code.strip().upper()


# ---------------------------------------------------------------- routes
@app.get("/")
def index():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/status")
def status(refresh: bool = False):
    """Shows which ExchangeRate-API endpoint is used. Add ?refresh=true to force a live fetch."""
    if refresh:
        _rate_cache["fetched"] = 0.0
        get_rates()
    age = time.time() - _rate_cache["fetched"] if _rate_cache["fetched"] else None
    return {
        "source": SOURCE,
        "api_key_loaded": bool(API_KEY),
        "api_key": masked_key(),
        "env_file_found": (BASE_DIR / ".env").exists(),
        "rates_cached": bool(_rate_cache["rates"]),
        "cache_age_seconds": round(age) if age is not None else None,
        "rates_updated": _rate_cache["updated"],
    }


@app.get("/api/currencies")
def currencies():
    rates = get_rates()
    return {"currencies": sorted(rates.keys()), "updated": _rate_cache["updated"]}


@app.get("/api/convert")
def convert(
    from_cur: str = Query(..., alias="from"),
    to_cur: str = Query(..., alias="to"),
    amount: float = Query(..., gt=0, le=1e12),
):
    frm, to = norm(from_cur), norm(to_cur)
    rate = cross_rate(frm, to, get_rates())
    result = round(amount * rate, 2)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO history (from_cur, to_cur, amount, result, rate) VALUES (?, ?, ?, ?, ?)",
            (frm, to, amount, result, rate),
        )
        # keep only the latest 50 rows
        conn.execute(
            "DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 50)"
        )
    return {
        "from": frm,
        "to": to,
        "amount": amount,
        "rate": round(rate, 6),
        "result": result,
        "updated": _rate_cache["updated"],
    }


@app.get("/api/trend")
def trend(from_cur: str = Query(..., alias="from"), to_cur: str = Query(..., alias="to")):
    frm, to = norm(from_cur), norm(to_cur)
    end = date.today()
    start = end - timedelta(days=30)
    if frm == to:
        return {"available": True, "points": [{"date": start.isoformat(), "rate": 1}, {"date": end.isoformat(), "rate": 1}]}

    key = (frm, to, end.isoformat())
    if key in _trend_cache:
        return _trend_cache[key]

    # 1) Frankfurter (ECB): one request, but only ~30 major currencies
    points = frankfurter_series(frm, to, start, end)
    source = "frankfurter"

    # 2) Fallback for every other currency (VND, JOD, ...): daily USD tables cached in SQLite
    if not points:
        history = {d: {**r, "USD": 1.0} for d, r in usd_history(start, end).items()}  # base isn't listed in its own table
        points = [
            {"date": d, "rate": round(r[to] / r[frm], 6)}
            for d, r in sorted(history.items())
            if frm in r and to in r and r[frm]
        ]
        source = "currency-api"

    result = {"available": bool(points), "points": points, "source": source}
    if points:  # don't cache failures, so a later retry can succeed
        _trend_cache[key] = result
    return result


def frankfurter_series(frm: str, to: str, start: date, end: date) -> list:
    try:
        resp = httpx.get(
            f"{TREND_URL}/{start.isoformat()}..{end.isoformat()}",
            params={"from": frm, "to": to},
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return []
        data = resp.json().get("rates", {})
        return [{"date": d, "rate": v[to]} for d, v in sorted(data.items()) if to in v]
    except Exception:
        return []


HIST_URLS = [
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{d}/v1/currencies/usd.min.json",
    "https://{d}.currency-api.pages.dev/v1/currencies/usd.min.json",
]
_hist_lock = threading.Lock()


def fetch_usd_day(day: str):
    """One day's USD-based table (150+ currencies). Returns None if unavailable."""
    for tmpl in HIST_URLS:
        try:
            resp = httpx.get(tmpl.format(d=day), timeout=10, follow_redirects=True)
            if resp.status_code == 200:
                usd = resp.json().get("usd", {})
                if usd:
                    return {k.upper(): v for k, v in usd.items() if isinstance(v, (int, float))}
        except Exception:
            continue
    return None


def usd_history(start: date, end: date) -> dict:
    """{date: {CUR: rate}} for the range. Missing days are fetched once, in parallel, then kept in SQLite."""
    days = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    with _hist_lock:
        with get_db() as conn:
            rows = conn.execute(
                f"SELECT date, rates_json FROM hist_usd WHERE date IN ({','.join('?' * len(days))})", days
            ).fetchall()
        history = {r["date"]: json.loads(r["rates_json"]) for r in rows}
        missing = [d for d in days if d not in history]
        if missing:
            log.info("Fetching %d days of historical rates (one-time, then cached)...", len(missing))
            with ThreadPoolExecutor(max_workers=10) as pool:
                fetched = dict(zip(missing, pool.map(fetch_usd_day, missing)))
            with get_db() as conn:
                for d, rates in fetched.items():
                    if rates:  # today's table may not be published yet; it's retried next time
                        history[d] = rates
                        conn.execute(
                            "INSERT OR REPLACE INTO hist_usd (date, rates_json) VALUES (?, ?)",
                            (d, json.dumps(rates)),
                        )
                # keep ~90 days
                conn.execute("DELETE FROM hist_usd WHERE date < ?", ((end - timedelta(days=90)).isoformat(),))
    return history


@app.get("/api/history")
def history(limit: int = Query(10, ge=1, le=50)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/history")
def clear_history():
    with get_db() as conn:
        conn.execute("DELETE FROM history")
    return {"ok": True}


class FavoriteIn(BaseModel):
    from_cur: str
    to_cur: str


@app.get("/api/favorites")
def list_favorites():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM favorites ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/favorites")
def add_favorite(fav: FavoriteIn):
    frm, to = norm(fav.from_cur), norm(fav.to_cur)
    cross_rate(frm, to, get_rates())  # validates both codes
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO favorites (from_cur, to_cur) VALUES (?, ?)", (frm, to)
        )
    return {"ok": True}


@app.delete("/api/favorites/{fav_id}")
def delete_favorite(fav_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM favorites WHERE id = ?", (fav_id,))
    return {"ok": True}


@app.get("/api/travel")
def travel(base: str, amount: float = Query(..., gt=0, le=1e12)):
    base = norm(base)
    rates = get_rates()
    targets = [c for c in TRAVEL_DEFAULT if c != base]
    for c in TRAVEL_FALLBACK:
        if len(targets) >= 5:
            break
        if c != base:
            targets.append(c)

    rows = []
    for cur in targets:
        rate = cross_rate(base, cur, rates)
        rows.append({"currency": cur, "rate": round(rate, 6), "amount": round(amount * rate, 2)})
    return {"base": base, "amount": amount, "rows": rows, "updated": _rate_cache["updated"]}