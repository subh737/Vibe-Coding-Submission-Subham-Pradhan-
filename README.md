# Currency Converter

A fast currency converter with live rates, a 30-day trend chart, favorite pairs, conversion history, and a Travel Budgeting mode.

## Features
- **Dual converter**: source and target dropdowns side by side, with a swap button
- **Live rates** from ExchangeRate-API (open endpoint), cached in memory for 1 hour
- **30-day trend chart** (Chart.js) using Frankfurter/ECB historical data
- **Favorites**: save currency pairs and load them with one click (stored in SQLite)
- **History**: recent conversions stored in SQLite
- **Travel Budgeting mode**: enter a budget in any currency and see it in 5 major currencies (USD, EUR, GBP, JPY, AUD; CHF fills in if your base is one of them)

## Backend logic & state management
- **Exchange rates**: live data is fetched from **ExchangeRate-API**. Set `EXCHANGE_API_KEY` to use your key (`v6.exchangerate-api.com`); without it, the app uses ExchangeRate-API's open endpoint (`open.er-api.com`).
- **Local persistence (SQLite, `currency.db`)**:
  - `history`: recent conversions (latest 50 kept)
  - `favorites`: user-defined currency pairs
  - `rate_cache`: the last fetched rate table, so the app works right after a restart even if the API is down

## Tech stack
FastAPI · SQLite · httpx · vanilla JS · Chart.js

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# copy .env.example to .env and put your ExchangeRate-API key in it
uvicorn app:app --reload
```
Open http://127.0.0.1:8000. API docs are at http://127.0.0.1:8000/docs.

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

## Design decisions
- **One upstream call for all pairs**: the app fetches a single USD-based rate table and computes any pair as `usd[to] / usd[from]`, which keeps API usage low.
- **Stale fallback**: if the rate API is down, the last cached rates are served.
- **History source**: ExchangeRate-API's free tier has no historical endpoint, so the trend chart uses Frankfurter (ECB). Some exotic currencies show "trend unavailable".

## Next steps
Auth and per-user data, Docker, automated tests, a scheduled daily rate snapshot.