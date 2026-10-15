"""Quote + history fetcher for US equities/ETFs.

Fallback order for ``provider=auto`` (first success wins):

1. ``--fixture`` / ``fixture=`` path, if given (tests and demos; not a live feed)
2. ``yfinance`` if the package is importable — daily history **and** earnings dates
3. Yahoo public chart API (stdlib, unofficial, best-effort) — ``query1`` then ``query2``
4. Alpaca snapshot, if ``ALPACA_API_KEY_ID`` + ``ALPACA_API_SECRET_KEY`` are set
   (latest trade / daily bar; **no** history, so MA / RSI / 52-week / earnings alerts
   will not fire)
5. Finnhub quote, if ``FINNHUB_API_KEY`` is set (same history limitation as Alpaca)
6. Alpha Vantage daily, if ``ALPHAVANTAGE_API_KEY`` is set (history, no earnings date)

Force one provider with ``--provider`` / ``WATCHLIST_PROVIDER``. Earnings dates are
only populated by yfinance today; other providers leave ``earnings_date`` as null.

Normalized quote dict:
  symbol, price, prev_close, open, day_high, day_low, volume, avg_volume_20d,
  high_52w, low_52w, closes (list, oldest->newest, daily), earnings_date (ISO or None),
  source, as_of (ISO UTC)

CLI: python scripts/quotes.py AAPL MSFT [--fixture tests/fixtures/quotes.json] [--provider yahoo]
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, sys, urllib.error, urllib.parse, urllib.request

UA = {
    "User-Agent": "us-watchlist-alerts/0.1 (+https://github.com/eli-alvarado/us-watchlist-alerts)"
}
YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")


def _get(url, headers=None, timeout=15, retries=1):
    last = None
    hdrs = {**UA, **(headers or {})}
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            last = e
            if attempt >= retries:
                break
    raise last


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _finish(q):
    closes = q.get("closes") or []
    vols = q.pop("_volumes", None) or []
    if vols and not q.get("avg_volume_20d"):
        past = vols[-21:-1] if len(vols) > 20 else vols[:-1]
        q["avg_volume_20d"] = sum(past) / len(past) if past else None
    if closes:
        yr = closes[-252:]
        q.setdefault("high_52w", max(yr)); q.setdefault("low_52w", min(yr))
        if q.get("high_52w") is None: q["high_52w"] = max(yr)
        if q.get("low_52w") is None: q["low_52w"] = min(yr)
    q.setdefault("earnings_date", None)
    q.setdefault("as_of", _now())
    if q.get("price") is None:
        raise RuntimeError(f"quote for {q.get('symbol')} has no price (source={q.get('source')})")
    return q


def from_fixture(symbol, path):
    with open(path) as f:
        data = json.load(f)
    key = symbol.upper()
    if key not in data:
        raise KeyError(f"{key} not in fixture {path}")
    q = dict(data[key]); q["symbol"] = key; q.setdefault("source", "fixture")
    return _finish(q)


def _aligned_ohlcv(quote_ind):
    """Zip daily bars and drop sessions whose close is missing, keeping volume aligned."""
    closes_raw = quote_ind.get("close") or []
    vols_raw = quote_ind.get("volume") or []
    opens_raw = quote_ind.get("open") or []
    n = len(closes_raw)
    closes, vols, opens = [], [], []
    for i, c in enumerate(closes_raw):
        if c is None:
            continue
        closes.append(c)
        vols.append((vols_raw[i] if i < len(vols_raw) and vols_raw[i] is not None else 0))
        o = opens_raw[i] if i < len(opens_raw) else None
        if o is not None:
            opens.append(o)
    return closes, vols, opens, n


def from_yahoo(symbol):
    s = urllib.parse.quote(symbol.upper())
    errors = []
    d = None
    for host in YAHOO_HOSTS:
        url = f"https://{host}/v8/finance/chart/{s}?range=1y&interval=1d&includePrePost=false"
        try:
            d = _get(url)
            break
        except Exception as e:
            errors.append(f"{host}: {e}")
    if d is None:
        raise RuntimeError("yahoo chart failed: " + "; ".join(errors))
    results = (d.get("chart") or {}).get("result") or []
    if not results:
        err = ((d.get("chart") or {}).get("error") or {}).get("description") or "no result"
        raise RuntimeError(f"yahoo chart: {err}")
    r = results[0]
    m = r.get("meta") or {}
    ind = (r.get("indicators") or {}).get("quote") or [{}]
    closes, vols, opens, _ = _aligned_ohlcv(ind[0] if ind else {})
    prev = m.get("chartPreviousClose") or m.get("previousClose")
    if prev is None and len(closes) > 1:
        prev = closes[-2]
    price = m.get("regularMarketPrice")
    if price is None and closes:
        price = closes[-1]
    opn = m.get("regularMarketOpen")
    if opn is None:
        opn = opens[-1] if opens else None
    q = {"symbol": symbol.upper(), "price": price,
         "prev_close": prev,
         "open": opn, "day_high": m.get("regularMarketDayHigh"),
         "day_low": m.get("regularMarketDayLow"), "volume": m.get("regularMarketVolume"),
         "high_52w": m.get("fiftyTwoWeekHigh"), "low_52w": m.get("fiftyTwoWeekLow"),
         "closes": closes, "_volumes": vols, "source": "yahoo-chart"}
    return _finish(q)


def _first_iso_date(raw):
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if raw is None:
        return None
    if hasattr(raw, "to_pydatetime"):
        try:
            raw = raw.to_pydatetime()
        except Exception:
            pass
    if isinstance(raw, dt.datetime):
        return raw.date().isoformat()
    if isinstance(raw, dt.date):
        return raw.isoformat()
    if hasattr(raw, "date") and callable(raw.date):
        try:
            return raw.date().isoformat()
        except Exception:
            pass
    s = str(raw).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _yfinance_earnings_date(ticker):
    """Best-effort next earnings date. yfinance calendar shape varies by version."""
    try:
        cal = ticker.calendar
        raw = None
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date") or cal.get("earningsDate")
        elif cal is not None:
            idx = list(getattr(cal, "index", []) or [])
            cols = list(getattr(cal, "columns", []) or [])
            loc = getattr(cal, "loc", None)
            if "Earnings Date" in idx and loc is not None:
                raw = loc("Earnings Date") if callable(loc) else loc["Earnings Date"]
            elif "Earnings Date" in cols:
                series = cal["Earnings Date"]
                raw = series.iloc[0] if hasattr(series, "iloc") else series
        ed = _first_iso_date(raw)
        if ed:
            return ed
    except Exception:
        pass
    try:
        edf = ticker.earnings_dates
        if edf is None or not len(edf):
            return None
        today = dt.date.today()
        future = []
        for idx in edf.index:
            d = None
            if hasattr(idx, "date") and callable(idx.date):
                try:
                    d = idx.date()
                except Exception:
                    d = None
            if d is None:
                d = _first_iso_date(idx)
                if d:
                    d = dt.date.fromisoformat(d)
            if d and d >= today:
                future.append(d)
        if future:
            return min(future).isoformat()
        last = edf.index[-1]
        return _first_iso_date(last)
    except Exception:
        return None


def from_yfinance(symbol):
    import yfinance as yf  # optional dependency
    t = yf.Ticker(symbol)
    h = t.history(period="1y", interval="1d")
    if h is None or getattr(h, "empty", False):
        raise RuntimeError(f"yfinance returned no history for {symbol}")
    closes = [float(x) for x in h["Close"].tolist()]
    vols = [float(x) for x in h["Volume"].tolist()]
    fi = t.fast_info
    price = None
    try:
        price = fi["last_price"]
    except Exception:
        price = getattr(fi, "last_price", None)
    if price is None:
        price = float(h["Close"].iloc[-1])
    q = {"symbol": symbol.upper(), "price": float(price),
         "prev_close": closes[-2] if len(closes) > 1 else None,
         "open": float(h["Open"].iloc[-1]), "day_high": float(h["High"].iloc[-1]),
         "day_low": float(h["Low"].iloc[-1]), "volume": vols[-1] if vols else None,
         "closes": closes, "_volumes": vols,
         "earnings_date": _yfinance_earnings_date(t), "source": "yfinance"}
    return _finish(q)


def from_finnhub(symbol):
    k = os.environ["FINNHUB_API_KEY"]
    d = _get(f"https://finnhub.io/api/v1/quote?symbol={symbol.upper()}&token={k}")
    q = {"symbol": symbol.upper(), "price": d["c"], "prev_close": d["pc"], "open": d["o"],
         "day_high": d["h"], "day_low": d["l"], "closes": [], "source": "finnhub"}
    return _finish(q)


def from_alphavantage(symbol):
    k = os.environ["ALPHAVANTAGE_API_KEY"]
    d = _get(f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&outputsize=full&symbol={symbol.upper()}&apikey={k}")
    ts = d["Time Series (Daily)"]; days = sorted(ts)[-260:]
    closes = [float(ts[x]["4. close"]) for x in days]; vols = [float(ts[x]["5. volume"]) for x in days]
    last = ts[days[-1]]
    q = {"symbol": symbol.upper(), "price": closes[-1], "prev_close": closes[-2], "open": float(last["1. open"]),
         "day_high": float(last["2. high"]), "day_low": float(last["3. low"]), "volume": vols[-1],
         "closes": closes, "_volumes": vols, "source": "alphavantage"}
    return _finish(q)


def from_alpaca(symbol):
    h = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY_ID"], "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET_KEY"]}
    d = _get(f"https://data.alpaca.markets/v2/stocks/{symbol.upper()}/snapshot", headers=h)
    q = {"symbol": symbol.upper(), "price": d["latestTrade"]["p"], "prev_close": d["prevDailyBar"]["c"],
         "open": d["dailyBar"]["o"], "day_high": d["dailyBar"]["h"], "day_low": d["dailyBar"]["l"],
         "volume": d["dailyBar"]["v"], "closes": [], "source": "alpaca"}
    return _finish(q)


PROVIDERS = {"yfinance": from_yfinance, "yahoo": from_yahoo, "finnhub": from_finnhub,
             "alphavantage": from_alphavantage, "alpaca": from_alpaca}


def auto_order():
    order = []
    try:
        import yfinance  # noqa: F401
        order.append("yfinance")
    except ImportError:
        pass
    order.append("yahoo")
    if os.environ.get("ALPACA_API_KEY_ID") and os.environ.get("ALPACA_API_SECRET_KEY"):
        order.append("alpaca")
    if os.environ.get("FINNHUB_API_KEY"): order.append("finnhub")
    if os.environ.get("ALPHAVANTAGE_API_KEY"): order.append("alphavantage")
    return order


def get_quote(symbol, provider="auto", fixture=None):
    if fixture:
        return from_fixture(symbol, fixture)
    errors = []
    wanted = [provider] if provider != "auto" else auto_order()
    for p in wanted:
        fn = PROVIDERS.get(p)
        if fn is None:
            errors.append(f"{p}: unknown provider")
            continue
        try:
            return fn(symbol)
        except Exception as e:  # try next provider
            errors.append(f"{p}: {e}")
    raise RuntimeError(f"all providers failed for {symbol}: " + "; ".join(errors))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--provider", default=os.environ.get("WATCHLIST_PROVIDER", "auto"))
    ap.add_argument("--fixture")
    ap.add_argument("--full", action="store_true", help="include closes history")
    a = ap.parse_args(argv)
    out = {}
    for s in a.symbols:
        try:
            q = get_quote(s, a.provider, a.fixture)
            if not a.full: q.pop("closes", None)
            out[s.upper()] = q
        except Exception as e:
            out[s.upper()] = {"error": str(e)}
    print(json.dumps(out, indent=2, default=str))
    return 1 if any("error" in v for v in out.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
