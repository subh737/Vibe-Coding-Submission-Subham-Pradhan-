# Currency Converter

A fast currency converter with live rates, a 30-day trend chart, favorite pairs, conversion history, and a Travel Budgeting mode.

**🔗 Live demo: [https://currency-converter-e7wi.onrender.com/](https://currency-converter-e7wi.onrender.com/)**

> Hosted on Render's free tier: the first visit after a period of inactivity can take 30–60 seconds while the server wakes up.

## Features
- **Dual converter**: source and target dropdowns side by side with an amount input, plus a swap button
- **Live rates** from ExchangeRate-API, cached for 1 hour
- **30-day trend chart** (Chart.js) for any currency pair
- **Favorites**: save currency pairs and load them with one click (stored in SQLite)
- **History**: recent conversions stored in SQLite
- **Travel Budgeting mode**: enter a budget in any currency and see it in 5 major currencies at once (USD, EUR, GBP, JPY, AUD; CHF fills in if your base is one of them)

## Backend logic & state management
- **Exchange rates**: live data is fetched from **ExchangeRate-API** using the `EXCHANGE_API_KEY` environment variable (`v6.exchangerate-api.com`). Without a key, the app falls back to ExchangeRate-API's open endpoint (`open.er-api.com`).
- **Local persistence (SQLite, `currency.db`)**:
  - `history`: recent conversions (latest 50 kept)
  - `favorites`: user-defined currency pairs
  - `rate_cache`: the last fetched rate table, so the app works right after a restart even if the API is down
  - `hist_usd`: daily historical rate tables used by the trend chart

## Tech stack
FastAPI · SQLite · httpx · vanilla JS · Chart.js · deployed on Render

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# copy .env.example to .env and put your ExchangeRate-API key in it
uvicorn app:app --reload
```
Open http://127.0.0.1:8000. API docs are at http://127.0.0.1:8000/docs.

## Deployment (Render)
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
- **Environment variable:** `EXCHANGE_API_KEY` (set in the Render dashboard; `.env` is never committed)
- On the free tier, the SQLite file resets when the service restarts or redeploys. Locally, data persists.

## API
| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/currencies` | Supported currency codes |
| GET | `/api/convert?from=USD&to=INR&amount=100` | Convert and save to history |
| GET | `/api/trend?from=USD&to=INR` | 30-day rate series |
| GET / DELETE | `/api/history` | List or clear recent conversions |
| GET / POST | `/api/favorites` | List or add favorite pairs |
| DELETE | `/api/favorites/{id}` | Remove a favorite |
| GET | `/api/travel?base=INR&amount=50000` | Travel budget in 5 currencies |
| GET | `/api/status` | Which rate source is in use and cache age |

## Design decisions
- **One upstream call for all pairs**: the app fetches a single USD-based rate table and computes any pair as `usd[to] / usd[from]`, which keeps API usage low.
- **Stale fallback**: if the rate API is down, the last cached rates are served.
- **History source**: ExchangeRate-API's free tier has no historical endpoint. The trend chart uses Frankfurter (ECB) for major currencies and a free daily rate dataset for all others, cached in SQLite after the first load.

## Next steps
Auth and per-user data, persistent hosted storage, Docker, automated tests.