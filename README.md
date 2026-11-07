# Crypto Intelligence Platform

A responsive web dashboard expanded from the uploaded `BTC Analysis.txt` source.

## Original multi-agent architecture preserved

- **Market Data Agent** — fetches BTC, ETH, SOL, BNB and XRP price, 24-hour change, volume and market cap.
- **News Agent** — retrieves crypto headlines and can research additional developments.
- **Narrative Agent** — investigates BTC dominance, ETF flows, regulation, institutional activity, macro links and sentiment.
- **Chief Analyst** — delegates to the three specialists and produces a structured intelligence briefing.

## Dashboard features

- Live snapshot cards for five major crypto assets.
- Asset table with price, 24-hour movement and market capitalization.
- BTC 7-day historical price chart.
- Latest crypto headlines.
- BTC share of the tracked five-asset market-cap basket (not total crypto-market dominance).
- AI-generated intelligence briefing through the four-agent workflow.
- Local browser-only price alert rules (alerts run while the dashboard is open).
- Responsive desktop/mobile interface.

## Run locally

Python 3.10+ recommended.

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
.venv\\Scripts\\Activate.ps1

pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then set `OPENAI_API_KEY` to a **new, rotated key**. The app loads `.env` on the server using `python-dotenv`. Do not put the key into HTML, JavaScript, source control, or chat. Production deployments should set the environment variable in their hosting provider's secret manager:

```bash
export OPENAI_API_KEY="your_new_key"
# Windows PowerShell:
$env:OPENAI_API_KEY="your_new_key"
```

Start:

```bash
uvicorn app:app --reload
```

Open http://127.0.0.1:8000

## API routes

- `GET /api/health`
- `GET /api/market`
- `GET /api/news?limit=10`
- `GET /api/history/btc?days=7`
- `POST /api/analyze` with `{"focus":"Bitcoin and major cryptocurrencies","include_news":true}`

## Important boundaries

- This application is an intelligence and monitoring dashboard, not a brokerage or exchange integration. It does not execute trades.
- Alert rules are stored in the browser and trigger only while the dashboard tab is open; they are not push notifications or a hosted monitoring service.
- The displayed BTC share is BTC market cap divided by the combined market cap of the five tracked assets, not Bitcoin's share of the entire crypto market.
- Data provider availability, rate limits and response formats can change.
- AI analysis requires a valid OpenAI API key, an account with API access/billing configured, and a compatible installed Agents SDK. Keep keys server-side.
- No historical backtest or validated trading strategy is included. Signals should be treated as informational watch conditions, not financial advice.
