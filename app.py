import os, time, threading, csv, io
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict, deque
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()
app = FastAPI(title="Phase10 Crypto Intelligence", version="2.0.0")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
COINS = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "binancecoin": "BNB", "ripple": "XRP"}
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_rate_log: dict[str, deque] = defaultdict(deque)
HEADERS = {"User-Agent": "Phase10-Crypto-Intelligence/2.0"}


def _cache_get(key: str):
    with _cache_lock:
        return _cache.get(key)


def _cache_set(key: str, value: Any):
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)


def cached_json(key: str, url: str, params: dict | None = None, ttl: int = 300, timeout: int = 15):
    now = time.monotonic()
    hit = _cache_get(key)
    if hit and now - hit[0] < ttl:
        return hit[1], False
    try:
        r = requests.get(url, params=params, timeout=timeout, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        _cache_set(key, data)
        return data, False
    except (requests.RequestException, ValueError):
        if hit:
            return hit[1], True
        raise


def cached_text(key: str, url: str, ttl: int = 21600, timeout: int = 8):
    now = time.monotonic()
    hit = _cache_get(key)
    if hit and now - hit[0] < ttl:
        return hit[1], False
    try:
        r = requests.get(url, timeout=timeout, headers=HEADERS)
        r.raise_for_status()
        value = r.text
        _cache_set(key, value)
        return value, False
    except requests.RequestException:
        if hit:
            return hit[1], True
        raise


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https:; connect-src 'self' https://api.coingecko.com https://cryptocurrency.cv https://community-api.coinmetrics.io https://mempool.space https://fred.stlouisfed.org;"
    return response


@app.get("/")
def home():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "phase10-crypto-intelligence", "version": "2.0.0"}


@app.get("/api/markets")
def markets():
    params = {"ids": ",".join(COINS), "vs_currencies": "usd", "include_24hr_change": "true", "include_24hr_vol": "true", "include_market_cap": "true"}
    try:
        raw, stale = cached_json("markets", "https://api.coingecko.com/api/v3/simple/price", params, 300)
        result = []
        for coin_id, symbol in COINS.items():
            d = raw.get(coin_id, {})
            result.append({"id": coin_id, "symbol": symbol, "price": d.get("usd"), "change_24h": d.get("usd_24h_change"), "volume_24h": d.get("usd_24h_vol"), "market_cap": d.get("usd_market_cap")})
        return {"markets": result, "source": "CoinGecko" + (" · cached fallback" if stale else ""), "updated_at": int(time.time()), "cached": stale}
    except requests.RequestException as e:
        raise HTTPException(502, f"Market data provider unavailable: {e}")


@app.get("/api/overview")
def overview():
    try:
        data, stale = cached_json("global", "https://api.coingecko.com/api/v3/global", ttl=600)
        d = data.get("data", {})
        return {"total_market_cap_usd": d.get("total_market_cap", {}).get("usd"), "total_volume_24h_usd": d.get("total_volume", {}).get("usd"), "btc_dominance_pct": d.get("market_cap_percentage", {}).get("btc"), "market_cap_change_24h_pct": d.get("market_cap_change_percentage_24h_usd"), "active_cryptocurrencies": d.get("active_cryptocurrencies"), "source": "CoinGecko Global" + (" · cached fallback" if stale else ""), "updated_at": int(time.time())}
    except requests.RequestException as e:
        raise HTTPException(502, f"Global market overview unavailable: {e}")


@app.get("/api/news")
def news():
    try:
        data, stale = cached_json("news", "https://cryptocurrency.cv/api/news", {"limit": 10}, 600)
        articles = data if isinstance(data, list) else data.get("articles", data.get("data", []))
        cleaned = []
        for a in articles[:10]:
            cleaned.append({"title": str(a.get("title", "Untitled")), "source": str(a.get("source", "Unknown")), "url": a.get("url") or a.get("link"), "published_at": a.get("published_at") or a.get("publishedAt") or a.get("date"), "summary": str(a.get("description", a.get("summary", "")))})
        return {"articles": cleaned, "source": "cryptocurrency.cv" + (" · cached fallback" if stale else ""), "updated_at": int(time.time())}
    except (requests.RequestException, ValueError) as e:
        raise HTTPException(502, f"News provider unavailable: {e}")


@app.get("/api/history/btc")
def btc_history():
    try:
        data, stale = cached_json("btc_history_7d", "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart", {"vs_currency": "usd", "days": "7", "interval": "hourly"}, 1800, 20)
        return {"prices": [{"time": p[0], "price": p[1]} for p in data.get("prices", [])], "source": "CoinGecko" + (" · cached fallback" if stale else ""), "cached": stale}
    except requests.RequestException as e:
        raise HTTPException(502, f"Historical data unavailable: {e}")


@app.get("/api/onchain")
def onchain():
    result = {"metrics": [], "source_notes": [], "updated_at": int(time.time())}
    # Coin Metrics Community API: public network metrics, where available.
    for metric, label in [("AdrActSentCnt", "BTC active addresses (sending)"), ("TxTfrCnt", "BTC transfer count")]:
        try:
            data, stale = cached_json(f"cm_{metric}", "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics", {"assets": "btc", "metrics": metric, "frequency": "1d", "limit_per_asset": 2}, 3600, 15)
            rows = data.get("data", [])
            if rows:
                row = rows[-1]
                result["metrics"].append({"label": label, "value": row.get(metric), "time": row.get("time"), "unit": "addresses" if "addresses" in label else "transfers", "source": "Coin Metrics Community" + (" · cached" if stale else "")})
        except Exception as e:
            result["source_notes"].append(f"{label} unavailable: provider did not return a community metric")
    # Bitcoin mempool and network indicators from mempool.space.
    for key, url, ttl in [
        ("mempool", "https://mempool.space/api/mempool", 120),
        ("fees", "https://mempool.space/api/v1/fees/recommended", 120),
        ("hashrate", "https://mempool.space/api/v1/mining/hashrate/1m", 3600),
    ]:
        try:
            data, stale = cached_json(f"mempool_{key}", url, ttl=ttl, timeout=15)
            if key == "mempool":
                result["metrics"].append({"label": "Unconfirmed BTC transactions", "value": data.get("count"), "unit": "transactions", "source": "mempool.space" + (" · cached" if stale else "")})
                result["metrics"].append({"label": "Mempool size", "value": data.get("vsize"), "unit": "virtual bytes", "source": "mempool.space" + (" · cached" if stale else "")})
            elif key == "fees":
                result["metrics"].append({"label": "Fast BTC fee estimate", "value": data.get("fastestFee"), "unit": "sat/vB", "source": "mempool.space" + (" · cached" if stale else "")})
            else:
                latest = data.get("currentHashrate")
                if latest is None and data.get("hashrates"):
                    latest = data["hashrates"][-1].get("avgHashrate")
                result["metrics"].append({"label": "BTC network hashrate", "value": latest, "unit": "H/s", "source": "mempool.space" + (" · cached" if stale else "")})
        except Exception:
            result["source_notes"].append(f"{key.title()} indicator temporarily unavailable")
    result["coverage_note"] = "Public endpoints do not provide a complete, consistent exchange-inflow/outflow dataset. Those flows are not estimated or fabricated. Network activity and mempool indicators are shown instead."
    return result


@app.get("/api/macro")
def macro():
    # FRED graph CSV is public; these are published observations, not intraday quotes.
    series = {"DFF": "Effective federal funds rate", "DGS10": "US 10-year Treasury yield", "DTWEXBGS": "Trade-weighted US dollar index", "CPIAUCSL": "US CPI inflation (12-month)"}

    def fetch_series(item):
        sid, label = item
        try:
            csv_text, stale = cached_text(
                f"fred_{sid}",
                f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}",
                ttl=21600,
                timeout=8,
            )
            rows = list(csv.DictReader(io.StringIO(csv_text)))
            valid = [(r.get("observation_date") or r.get("DATE"), r.get(sid))
                     for r in rows if r.get(sid) not in (None, "", ".")]
            if not valid:
                raise ValueError("FRED returned no usable observations")
            date, value = valid[-1]
            numeric_value = float(value)
            if sid == "CPIAUCSL" and len(valid) >= 13:
                prior = float(valid[-13][1])
                numeric_value = (numeric_value / prior - 1) * 100 if prior else None
            return {"id": sid, "label": label, "value": numeric_value, "date": date,
                    "source": "FRED" + (" · cached fallback" if stale else "")}
        except Exception as exc:
            print(f"FRED {sid} unavailable: {type(exc).__name__}: {exc}")
            return {"id": sid, "label": label, "value": None, "date": None,
                    "source": "Temporarily unavailable"}

    # Fetch independently and concurrently: one slow series cannot block the other three.
    with ThreadPoolExecutor(max_workers=4) as pool:
        indicators = list(pool.map(fetch_series, series.items()))
    return {
        "indicators": indicators,
        "source": "Federal Reserve Bank of St. Louis FRED",
        "updated_at": int(time.time()),
        "note": "Daily series are generally previous-business-day observations; CPI is monthly. Latest release dates are shown.",
    }

@app.post("/api/analysis")
async def analysis(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time(); q = _rate_log[ip]
    while q and now - q[0] > 600: q.popleft()
    if len(q) >= 3:
        raise HTTPException(429, "Analysis limit reached. Try again in 10 minutes.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(503, "AI analysis is not configured. Add OPENAI_API_KEY in Render → Environment.")
    q.append(now)
    try:
        from agents import Agent, Runner, WebSearchTool, function_tool
        market_data = markets(); global_data = overview(); chain_data = onchain(); macro_data = macro(); news_data = news()
        evidence = {"market": market_data, "global": global_data, "on_chain": chain_data, "macro": macro_data, "news": news_data}
        @function_tool
        def get_dashboard_evidence() -> str:
            """Return current dashboard market, on-chain, macro and news data. Provider gaps are explicitly noted."""
            return str(evidence)
        market_agent = Agent(name="Market Structure Agent", instructions="Interpret prices, market capitalization, volume, BTC dominance and breadth. Cite the supplied observations; do not invent missing values.", tools=[get_dashboard_evidence])
        onchain_agent = Agent(name="On-chain Agent", instructions="Interpret active addresses, transfers, mempool congestion, fees and hashrate. Separate network health from price direction. Explicitly flag unavailable exchange flows.", tools=[get_dashboard_evidence])
        macro_agent = Agent(name="Macro Context Agent", instructions="Interpret Federal Funds Rate, Treasury yields, dollar index and CPI. Explain release-date limitations and avoid causal certainty.", tools=[get_dashboard_evidence, WebSearchTool()])
        news_agent = Agent(name="News and Narrative Agent", instructions="Identify high-impact crypto news and narratives; separate reported facts from inference. Use sources and dates where available.", tools=[get_dashboard_evidence, WebSearchTool()])
        chief = Agent(name="Phase10 Chief Analyst", instructions="You are the coordinating analyst for Phase10. Produce a concise but useful report with sections: Executive summary; Market regime and breadth; On-chain/network signals; Macro backdrop; News and dominant narratives; Bull/base/bear scenarios with evidence and invalidation conditions; Key risks and what to monitor. Explicitly identify stale, delayed, unavailable or contradictory data. No personalized financial advice, price targets, or trade instructions. Explain that scenarios are conditional, not predictions.", tools=[market_agent.as_tool(tool_name="analyze_market", tool_description="Analyze market structure"), onchain_agent.as_tool(tool_name="analyze_onchain", tool_description="Analyze blockchain/network indicators"), macro_agent.as_tool(tool_name="analyze_macro", tool_description="Analyze macroeconomic context"), news_agent.as_tool(tool_name="analyze_news", tool_description="Analyze crypto news and narratives"), get_dashboard_evidence, WebSearchTool()])
        result = await Runner.run(chief, "Create a current Phase10 multi-factor crypto intelligence briefing from the supplied dashboard evidence. Call all specialist analysts. Include clear source-aware interpretation and scenario invalidation conditions.")
        return {"report": result.final_output, "generated_at": int(time.time()), "coverage": {"market": True, "onchain": bool(chain_data.get("metrics")), "macro": bool([x for x in macro_data.get("indicators", []) if x.get("value") is not None]), "news": bool(news_data.get("articles"))}}
    except HTTPException:
        raise
    except Exception as e:
        # Keep details in server logs, not public error responses.
        print(f"AI analysis error: {type(e).__name__}: {e}")
        raise HTTPException(502, "AI briefing failed. Check that the OpenAI API key is valid, billing is enabled, and the latest deployment is healthy.")


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    print(f"Unhandled server error: {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred."})
