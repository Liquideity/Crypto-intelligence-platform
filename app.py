import json
import os
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()  # Loads a local .env file; production should use server environment variables.

COINGECKO = "https://api.coingecko.com/api/v3"
NEWS_URL = "https://cryptocurrency.cv/api/news"
COINS = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple"]
ASSETS = {
    "bitcoin": ("BTC", "Bitcoin"),
    "ethereum": ("ETH", "Ethereum"),
    "solana": ("SOL", "Solana"),
    "binancecoin": ("BNB", "BNB"),
    "ripple": ("XRP", "XRP"),
}
TIMEOUT = 15

app = FastAPI(title="Crypto Intelligence Platform", version="1.1.0")
app.mount("/static", StaticFiles(directory="static"), name="static")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_json(url: str, *, params: dict | None = None) -> Any:
    response = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": "CryptoIntelligenceDashboard/1.1"})
    response.raise_for_status()
    return response.json()


def fetch_market() -> dict[str, Any]:
    raw = request_json(
        f"{COINGECKO}/simple/price",
        params={
            "ids": ",".join(COINS),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
            "include_market_cap": "true",
        },
    )
    rows = []
    for coin_id in COINS:
        values = raw.get(coin_id, {})
        symbol, name = ASSETS[coin_id]
        rows.append({
            "id": coin_id,
            "symbol": symbol,
            "name": name,
            "price_usd": values.get("usd"),
            "change_24h_pct": values.get("usd_24h_change"),
            "volume_24h_usd": values.get("usd_24h_vol"),
            "market_cap_usd": values.get("usd_market_cap"),
        })
    total_cap = sum(a["market_cap_usd"] or 0 for a in rows)
    btc_cap = next((a["market_cap_usd"] for a in rows if a["symbol"] == "BTC"), None)
    return {
        "updated_at": utc_now(),
        "assets": rows,
        "btc_share_of_tracked_market_pct": round(btc_cap / total_cap * 100, 2) if btc_cap and total_cap else None,
        "provider": "CoinGecko",
    }


def fetch_news(limit: int = 10) -> list[dict[str, str]]:
    raw = request_json(NEWS_URL, params={"limit": limit})
    items = raw if isinstance(raw, list) else raw.get("articles", raw.get("data", []))
    return [{
        "title": str(a.get("title") or "Untitled"),
        "source": str(a.get("source") or "Unknown"),
        "url": str(a.get("url") or a.get("link") or ""),
        "published_at": str(a.get("published_at") or a.get("publishedAt") or ""),
    } for a in items[:limit]]


def fetch_btc_history(days: int = 7) -> dict[str, Any]:
    raw = request_json(
        f"{COINGECKO}/coins/bitcoin/market_chart",
        params={"vs_currency": "usd", "days": days, "interval": "hourly" if days <= 7 else "daily"},
    )
    prices = raw.get("prices", [])
    return {
        "coin": "BTC",
        "currency": "USD",
        "days": days,
        "updated_at": utc_now(),
        "points": [{"time": int(p[0]), "price": p[1]} for p in prices if len(p) >= 2],
        "provider": "CoinGecko",
    }


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/api/health")
def health():
    try:
        import agents  # noqa: F401
        sdk_installed = True
    except Exception:
        sdk_installed = False
    return {
        "status": "ok",
        "openai_key_configured": bool(os.getenv("OPENAI_API_KEY")),
        "agents_sdk_installed": sdk_installed,
        "server_time": utc_now(),
    }


@app.get("/api/market")
def market():
    try:
        return fetch_market()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Market data provider error: {exc}")


@app.get("/api/news")
def news(limit: int = 10):
    try:
        return {"updated_at": utc_now(), "articles": fetch_news(max(1, min(limit, 20)))}
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"News provider error: {exc}")


@app.get("/api/history/btc")
def btc_history(days: int = 7):
    try:
        return fetch_btc_history(max(1, min(days, 30)))
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Historical market data provider error: {exc}")


class AnalysisRequest(BaseModel):
    focus: str = Field(default="Bitcoin and major cryptocurrencies", max_length=300)
    include_news: bool = True


def build_multi_agent_system():
    """Expanded version of the user's original four-agent orchestration."""
    from agents import Agent, Runner, WebSearchTool, function_tool

    @function_tool
    def get_major_crypto_prices() -> str:
        """Retrieve current BTC, ETH, SOL, BNB and XRP prices, 24h change, volume and market cap."""
        return json.dumps(fetch_market())

    @function_tool
    def get_crypto_news(limit: int = 8) -> str:
        """Retrieve the latest crypto news headlines."""
        return json.dumps(fetch_news(max(1, min(limit, 20))))

    market_agent = Agent(
        name="Market Data Agent",
        instructions=(
            "You specialize in current market data for BTC, ETH, SOL, BNB and XRP. "
            "Always call get_major_crypto_prices. State the retrieval timestamp, currency and exact metrics. "
            "Never invent missing values."
        ),
        tools=[get_major_crypto_prices],
    )
    news_agent = Agent(
        name="News Agent",
        instructions=(
            "You gather and summarize material recent cryptocurrency developments, prioritizing Bitcoin "
            "and major assets. Use get_crypto_news and web search when useful. Separate confirmed reporting "
            "from commentary and include source names and dates when available."
        ),
        tools=[get_crypto_news, WebSearchTool()],
    )
    narrative_agent = Agent(
        name="Narrative Agent",
        instructions=(
            "Research market narratives including ETF flows, BTC dominance, regulation, institutional "
            "activity, macroeconomic links, liquidity and sentiment. Use web search. Distinguish evidence "
            "from inference, identify counter-signals and avoid unsupported price predictions."
        ),
        tools=[WebSearchTool()],
    )
    chief_analyst = Agent(
        name="Chief Analyst",
        instructions=(
            "Lead the crypto intelligence desk. Use specialist agents and return: 1) market snapshot, "
            "2) top news, 3) dominant narratives and sentiment, 4) bullish/base/bearish scenarios with "
            "conditions that would invalidate them, 5) risks and catalysts to watch next. Be neutral, "
            "evidence-based and concise. Never give personalized financial advice or promise returns."
        ),
        tools=[
            market_agent.as_tool(
                tool_name="get_market_data",
                tool_description="Delegate live price and market-metric retrieval to the Market Data Agent",
            ),
            news_agent.as_tool(
                tool_name="get_news",
                tool_description="Delegate crypto-news research to the News Agent",
            ),
            narrative_agent.as_tool(
                tool_name="analyze_narratives",
                tool_description="Delegate narrative, sentiment and catalyst research to the Narrative Agent",
            ),
            WebSearchTool(),
        ],
    )
    return Runner, chief_analyst


@app.post("/api/analyze")
def analyze(request: AnalysisRequest):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="AI analysis is not configured. Set OPENAI_API_KEY on the server; never enter it in the browser.",
        )
    try:
        Runner, chief_analyst = build_multi_agent_system()
        prompt = (
            f"Prepare a current crypto intelligence briefing focused on: {request.focus}. "
            f"Include news: {request.include_news}. Fetch current market data. Timestamp the briefing. "
            "For each conclusion, identify whether it is measured data, reported news or analytical inference. "
            "Include actionable watch conditions, not individualized trade instructions."
        )
        result = Runner.run_sync(chief_analyst, prompt)
        return {"generated_at": utc_now(), "report": result.final_output}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Multi-agent analysis failed: {exc}")
