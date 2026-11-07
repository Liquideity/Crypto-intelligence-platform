import os, time
from collections import defaultdict, deque
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()
app = FastAPI(title="Crypto Intelligence Platform", version="1.0.0")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

COINS = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "binancecoin": "BNB", "ripple": "XRP"}
_rate_log: dict[str, deque] = defaultdict(deque)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https:; connect-src 'self' https://api.coingecko.com https://cryptocurrency.cv;"
    return response

@app.get("/")
def home():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "crypto-intelligence-platform"}

@app.get("/api/markets")
def markets():
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ",".join(COINS), "vs_currencies": "usd", "include_24hr_change": "true", "include_24hr_vol": "true", "include_market_cap": "true"}
    try:
        r = requests.get(url, params=params, timeout=15, headers={"User-Agent": "CryptoIntelligencePlatform/1.0"})
        r.raise_for_status()
        raw = r.json()
        result = []
        for coin_id, symbol in COINS.items():
            d = raw.get(coin_id, {})
            result.append({"id": coin_id, "symbol": symbol, "price": d.get("usd"), "change_24h": d.get("usd_24h_change"), "volume_24h": d.get("usd_24h_vol"), "market_cap": d.get("usd_market_cap")})
        return {"markets": result, "source": "CoinGecko", "updated_at": int(time.time())}
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Market data provider unavailable: {e}")

@app.get("/api/news")
def news():
    try:
        r = requests.get("https://cryptocurrency.cv/api/news", params={"limit": 8}, timeout=15, headers={"User-Agent": "CryptoIntelligencePlatform/1.0"})
        r.raise_for_status()
        data = r.json()
        articles = data if isinstance(data, list) else data.get("articles", data.get("data", []))
        cleaned = []
        for a in articles[:8]:
            cleaned.append({"title": str(a.get("title", "Untitled")), "source": str(a.get("source", "Unknown")), "url": a.get("url") or a.get("link"), "published_at": a.get("published_at") or a.get("publishedAt") or a.get("date"), "summary": str(a.get("description", a.get("summary", "")))})
        return {"articles": cleaned, "source": "cryptocurrency.cv", "updated_at": int(time.time())}
    except (requests.RequestException, ValueError) as e:
        raise HTTPException(status_code=502, detail=f"News provider unavailable: {e}")

@app.get("/api/history/btc")
def btc_history():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart", params={"vs_currency": "usd", "days": "7", "interval": "hourly"}, timeout=20, headers={"User-Agent": "CryptoIntelligencePlatform/1.0"})
        r.raise_for_status()
        prices = r.json().get("prices", [])
        return {"prices": [{"time": p[0], "price": p[1]} for p in prices], "source": "CoinGecko"}
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Historical data unavailable: {e}")

@app.post("/api/analysis")
async def analysis(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time(); q = _rate_log[ip]
    while q and now - q[0] > 600: q.popleft()
    if len(q) >= 3: raise HTTPException(status_code=429, detail="Analysis limit reached. Try again in 10 minutes.")
    q.append(now)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key: raise HTTPException(status_code=503, detail="AI analysis is not configured. Add OPENAI_API_KEY in your hosting environment.")
    try:
        from agents import Agent, Runner, WebSearchTool, function_tool
        @function_tool
        def get_major_crypto_prices() -> str:
            """Fetch current BTC, ETH, SOL, BNB and XRP prices and market metrics."""
            r = requests.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": ",".join(COINS), "vs_currencies": "usd", "include_24hr_change": "true", "include_24hr_vol": "true", "include_market_cap": "true"}, timeout=15)
            r.raise_for_status(); return str(r.json())
        @function_tool
        def get_crypto_news(limit: int = 8) -> str:
            """Fetch recent cryptocurrency headlines."""
            r = requests.get("https://cryptocurrency.cv/api/news", params={"limit": limit}, timeout=15); r.raise_for_status()
            items = r.json(); items = items if isinstance(items, list) else items.get("articles", [])
            return "\n".join(f"- {x.get('title','Untitled')} ({x.get('source','Unknown')}) {x.get('url','')}" for x in items[:limit])
        market_agent = Agent(name="Market Data Agent", instructions="Report current market data accurately. Always use the market data tool.", tools=[get_major_crypto_prices])
        news_agent = Agent(name="News Agent", instructions="Summarize high-impact recent crypto news with sources and dates where available.", tools=[get_crypto_news, WebSearchTool()])
        narrative_agent = Agent(name="Narrative Agent", instructions="Analyze current crypto narratives, ETF flows, regulation, macro, liquidity and sentiment. Distinguish evidence from inference.", tools=[WebSearchTool()])
        chief = Agent(name="Chief Analyst", instructions="Produce a professional neutral crypto intelligence report with market snapshot, top news, narratives, bullish/base/bearish scenarios, risks and watchlist. State uncertainty. No personalized financial advice or trade instructions.", tools=[market_agent.as_tool(tool_name="get_market_data", tool_description="Fetch major crypto market data"), news_agent.as_tool(tool_name="get_news", tool_description="Fetch recent crypto news"), narrative_agent.as_tool(tool_name="analyze_narratives", tool_description="Analyze current crypto narratives"), WebSearchTool()])
        result = await Runner.run(chief, "Prepare a current intelligence briefing on BTC and major cryptocurrencies. Include BTC, ETH, SOL, BNB and XRP; source-backed news; dominant narratives; risks; and bullish, base and bearish scenarios with invalidation conditions.")
        return {"report": result.final_output, "generated_at": int(time.time())}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {e}")

@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred."})
