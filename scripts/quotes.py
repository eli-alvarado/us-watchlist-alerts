"""Quote + history fetcher for US equities/ETFs.

Fallback order for ``provider=auto`` (first success wins):

1. ``--fixture`` / ``fixture=`` path, if given (tests and demos; not a live feed)
2. Alpaca snapshot + daily bars, if ``ALPACA_API_KEY_ID`` + ``ALPACA_API_SECRET_KEY``
   (official US feed; history included when bars succeed)
3. ``yfinance`` if the package is importable
4. Yahoo public chart API (stdlib, unofficial, best-effort) — ``query1`` then ``query2``.
   Do not use ``chartPreviousClose`` as yesterday's close (it is the print before the
   chart range). Prior session comes from ``previousClose`` or the previous daily bar.
5. Finnhub quote + candles, if ``FINNHUB_API_KEY`` is set
6. Alpha Vantage daily, if ``ALPHAVANTAGE_API_KEY`` is set

ATM implied volatility is **not** part of the quote fallback. ``attach_iv`` (or
``quotes.py --iv``) hits Yahoo's unofficial ``v7/finance/options`` chain and averages
the nearest-expiration ATM call/put IV. Missing/zero IV is left unset so alert
rules skip rather than guess. No IV rank, unusual-options flow, or Black-Scholes.

Earnings dates are filled independently of the quote provider (first hit):

1. Already on the quote (yfinance, or a fixture)
2. Yahoo ``quoteSummary`` ``calendarEvents`` (stdlib, unofficial)
3. Finnhub earnings calendar, if ``FINNHUB_API_KEY`` is set
4. Alpha Vantage ``EARNINGS_CALENDAR``, if ``ALPHAVANTAGE_API_KEY`` is set

Normalized quote dict: see ``QUOTE_FIELDS``.

CLI: python scripts/quotes.py AAPL MSFT [--fixture tests/fixtures/quotes.json] [--provider yahoo]
"""
from __future__ import annotations
import argparse, datetime as dt, http.cookiejar, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

UA = {
    "User-Agent": "us-watchlist-alerts/0.3 (+https://github.com/eli-alvarado/us-watchlist-alerts)"
}
YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
_ET = ZoneInfo("America/New_York")
_yahoo_jar = None
_yahoo_crumb = None
QUOTE_FIELDS = (
    "symbol", "price", "prev_close", "open", "day_high", "day_low", "volume",
    "avg_volume_20d", "high_52w", "low_52w", "closes", "earnings_date",
    "earnings_source", "source", "as_of",
    "atm_iv", "iv_expiry", "iv_source",
)


class QuoteError(RuntimeError):
    """Provider-tagged failure with optional HTTP status and a next-step hint."""

    def __init__(self, provider, message, status=None, hint=None):
        self.provider = provider
        self.status = status
        self.hint = hint
        parts = [f"{provider}: {message}"]
        if status is not None:
            parts.append(f"HTTP {status}")
        if hint:
            parts.append(hint)
        super().__init__(" — ".join(parts))


def _timeout():
    try:
        return float(os.environ.get("WATCHLIST_HTTP_TIMEOUT") or 15)
    except ValueError:
        return 15.0


def _sleep(seconds):
    time.sleep(seconds)


def _encode_body(data, headers):
    """Return ``(bytes_or_None, headers)``. Adds Content-Type when we JSON-encode a dict."""
    if data is None:
        return None, headers
    if isinstance(data, (bytes, bytearray)):
        return bytes(data), headers
    if isinstance(data, str):
        if not any(k.lower() == "content-type" for k in headers):
            headers = {**headers, "Content-Type": "text/plain; charset=utf-8"}
        return data.encode(), headers
    if not any(k.lower() == "content-type" for k in headers):
        headers = {**headers, "Content-Type": "application/json"}
    return json.dumps(data).encode(), headers


def _request(url, method="GET", data=None, headers=None, timeout=None, retries=2, provider="http", raw=False):
    """HTTP JSON (or raw bytes if ``raw``). Retries 429/5xx with exponential backoff."""
    last = None
    hdrs = {**UA, **(headers or {})}
    timeout = _timeout() if timeout is None else timeout
    body, hdrs = _encode_body(data, hdrs)
    opener = None
    if method == "GET" and any(h in url for h in YAHOO_HOSTS) and any(
        p in url for p in ("quoteSummary", "/v7/finance/options")
    ):
        try:
            opener, crumb = _yahoo_session()
            url = _yahoo_url(url, crumb)
        except Exception:
            opener = None
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
            with open_fn(req, timeout=timeout) as r:
                resp = r.read()
            if raw:
                return resp
            if not resp:
                return {}
            try:
                return json.loads(resp.decode())
            except json.JSONDecodeError as e:
                if method == "POST":
                    return {"ok": True, "body": resp.decode()[:240]}
                raise QuoteError(provider, f"invalid JSON: {e}", hint=url.split("?", 1)[0])
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                err_body = e.read().decode()[:240]
            except Exception:
                err_body = ""
            retry_after = e.headers.get("Retry-After") if e.headers else None
            try:
                e.close()
            except Exception:
                pass
            last = QuoteError(provider, err_body or e.reason or "request failed", status=status,
                              hint=_hint_for_status(status, provider))
            if status in (429, 500, 502, 503, 504) and attempt < retries:
                delay = min(2 ** attempt, 8)
                try:
                    if retry_after:
                        delay = max(delay, min(float(retry_after), 30))
                except ValueError:
                    pass
                _sleep(delay)
                continue
            raise last
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = QuoteError(provider, str(e) or e.__class__.__name__,
                              hint="network/timeout; raise WATCHLIST_HTTP_TIMEOUT or try another provider")
            if attempt < retries:
                _sleep(min(2 ** attempt, 8))
                continue
            raise last
    raise last


def _get(url, headers=None, timeout=None, retries=2, provider="http", raw=False):
    """GET JSON (or raw bytes if ``raw``). Retries 429/5xx with exponential backoff."""
    return _request(url, method="GET", headers=headers, timeout=timeout, retries=retries,
                    provider=provider, raw=raw)


def _post(url, data, headers=None, timeout=None, retries=1, provider="http", raw=False):
    """POST JSON/text. Retries 429/5xx once. Slack/ntfy often return non-JSON bodies."""
    return _request(url, method="POST", data=data, headers=headers, timeout=timeout,
                    retries=retries, provider=provider, raw=raw)


def _hint_for_status(status, provider):
    if status == 401:
        return f"check {provider} API credentials"
    if status == 403:
        return f"{provider} refused the request (plan/feed permissions?)"
    if status == 404:
        return "unknown symbol or endpoint"
    if status == 429:
        return "rate limited; wait, or set WATCHLIST_PROVIDER to another source"
    if status and status >= 500:
        return f"{provider} is down; auto fallback will try the next source"
    return None


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def quote_age_seconds(q, now=None):
    """Age of ``as_of`` in seconds, or None if missing/unparseable."""
    raw = (q or {}).get("as_of")
    if not raw:
        return None
    try:
        t = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return (now.astimezone(dt.timezone.utc) - t.astimezone(dt.timezone.utc)).total_seconds()


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
    q.setdefault("earnings_source", None)
    q.setdefault("atm_iv", None)
    q.setdefault("iv_expiry", None)
    q.setdefault("iv_source", None)
    q.setdefault("as_of", _now())
    if q.get("price") is None:
        raise QuoteError(q.get("source") or "quote", f"{q.get('symbol')} has no price")
    return q


def from_fixture(symbol, path):
    with open(path) as f:
        data = json.load(f)
    key = symbol.upper()
    if key not in data:
        raise QuoteError("fixture", f"{key} not in fixture {path}")
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


def _chart_prev_close(meta, closes, timestamps=None, price=None, now=None):
    """Yesterday's session close.

    Yahoo's ``chartPreviousClose`` is the close *before the requested range*
    (so a 1y chart returns a year-ago print). Prefer an explicit previousClose,
    then the daily bar before today's session.
    """
    meta = meta or {}
    for key in ("previousClose", "regularMarketPreviousClose"):
        if meta.get(key) is not None:
            return meta[key]
    if not closes:
        return meta.get("chartPreviousClose")
    last_is_today = False
    if timestamps:
        try:
            last = dt.datetime.fromtimestamp(int(timestamps[-1]), dt.timezone.utc).astimezone(_ET)
            today = (now or dt.datetime.now(_ET)).astimezone(_ET).date()
            last_is_today = last.date() == today
        except (TypeError, ValueError, OSError, OverflowError):
            last_is_today = False
    if not last_is_today and price is not None and len(closes) > 1:
        # No usable timestamp: last bar matching last price is almost always today's developing close.
        try:
            last_is_today = abs(float(closes[-1]) - float(price)) <= max(0.01, abs(float(price)) * 1e-4)
        except (TypeError, ValueError):
            last_is_today = False
    if last_is_today and len(closes) > 1:
        return closes[-2]
    return closes[-1]


def _as_of_from_meta(meta):
    ts = (meta or {}).get("regularMarketTime")
    if ts is None:
        return None
    try:
        return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _reset_yahoo_session():
    global _yahoo_jar, _yahoo_crumb
    _yahoo_jar = None
    _yahoo_crumb = None


def _yahoo_session():
    """Cookie jar + crumb for unofficial Yahoo endpoints that 401 without them.

    Chart works without this. quoteSummary and options often do not.
    Failures return ``(opener, None)`` so callers can still try unauthenticated.
    """
    global _yahoo_jar, _yahoo_crumb
    if _yahoo_jar is None:
        _yahoo_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_yahoo_jar))
    if _yahoo_crumb:
        return opener, _yahoo_crumb
    try:
        req = urllib.request.Request("https://finance.yahoo.com", headers=UA)
        with opener.open(req, timeout=_timeout()) as r:
            r.read()
    except Exception:
        pass
    for host in YAHOO_HOSTS:
        url = f"https://{host}/v1/test/getcrumb"
        try:
            req = urllib.request.Request(url, headers={**UA, "Accept": "text/plain,*/*"})
            with opener.open(req, timeout=_timeout()) as r:
                crumb = r.read().decode().strip()
            if crumb and "html" not in crumb.lower() and len(crumb) < 80:
                _yahoo_crumb = crumb
                return opener, _yahoo_crumb
        except Exception:
            continue
    return opener, None


def _yahoo_url(url, crumb=None):
    if not crumb or "crumb=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + "crumb=" + urllib.parse.quote(crumb)


def from_yahoo(symbol):
    s = urllib.parse.quote(symbol.upper())
    errors = []
    d = None
    for host in YAHOO_HOSTS:
        url = f"https://{host}/v8/finance/chart/{s}?range=1y&interval=1d&includePrePost=false"
        try:
            d = _get(url, provider="yahoo")
            break
        except Exception as e:
            errors.append(f"{host}: {e}")
    if d is None:
        raise QuoteError("yahoo", "chart failed: " + "; ".join(errors),
                         hint="unofficial endpoint; install yfinance or set Alpaca/Finnhub keys")
    results = (d.get("chart") or {}).get("result") or []
    if not results:
        err = ((d.get("chart") or {}).get("error") or {}).get("description") or "no result"
        raise QuoteError("yahoo", f"chart: {err}", hint="unknown symbol, or Yahoo is blocking this UA")
    r = results[0]
    m = r.get("meta") or {}
    ind = (r.get("indicators") or {}).get("quote") or [{}]
    closes, vols, opens, _ = _aligned_ohlcv(ind[0] if ind else {})
    price = m.get("regularMarketPrice")
    if price is None and closes:
        price = closes[-1]
    prev = _chart_prev_close(m, closes, timestamps=r.get("timestamp"), price=price)
    opn = m.get("regularMarketOpen")
    if opn is None:
        opn = opens[-1] if opens else None
    q = {"symbol": symbol.upper(), "price": price,
         "prev_close": prev,
         "open": opn, "day_high": m.get("regularMarketDayHigh"),
         "day_low": m.get("regularMarketDayLow"), "volume": m.get("regularMarketVolume"),
         "high_52w": m.get("fiftyTwoWeekHigh"), "low_52w": m.get("fiftyTwoWeekLow"),
         "closes": closes, "_volumes": vols, "source": "yahoo-chart"}
    as_of = _as_of_from_meta(m)
    if as_of:
        q["as_of"] = as_of
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
    if isinstance(raw, dict):
        if raw.get("fmt"):
            return _first_iso_date(raw["fmt"])
        if raw.get("raw") is not None:
            try:
                return dt.datetime.fromtimestamp(int(raw["raw"]), dt.timezone.utc).date().isoformat()
            except (TypeError, ValueError, OSError):
                pass
        return _first_iso_date(raw.get("date") or raw.get("earningsDate"))
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
        raise QuoteError("yfinance", f"no history for {symbol}")
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
         "earnings_date": _yfinance_earnings_date(t), "earnings_source": "yfinance",
         "source": "yfinance"}
    if not q["earnings_date"]:
        q["earnings_source"] = None
    return _finish(q)


def _finnhub_key():
    k = os.environ.get("FINNHUB_API_KEY")
    if not k:
        raise QuoteError("finnhub", "FINNHUB_API_KEY is not set")
    return k


def from_finnhub(symbol):
    k = _finnhub_key()
    d = _get(f"https://finnhub.io/api/v1/quote?symbol={symbol.upper()}&token={k}", provider="finnhub")
    if d.get("c") is None:
        raise QuoteError("finnhub", f"empty quote for {symbol}", hint="unknown symbol or key plan")
    closes, vols = [], []
    try:
        now = int(dt.datetime.now(dt.timezone.utc).timestamp())
        start = now - 400 * 86400
        c = _get(
            f"https://finnhub.io/api/v1/stock/candle?symbol={symbol.upper()}&resolution=D&from={start}&to={now}&token={k}",
            provider="finnhub",
        )
        if c.get("s") == "ok":
            closes = [float(x) for x in (c.get("c") or [])]
            vols = [float(x) for x in (c.get("v") or [])]
    except Exception:
        pass
    q = {"symbol": symbol.upper(), "price": d["c"], "prev_close": d.get("pc"), "open": d.get("o"),
         "day_high": d.get("h"), "day_low": d.get("l"), "closes": closes, "_volumes": vols,
         "source": "finnhub"}
    return _finish(q)


def from_alphavantage(symbol):
    k = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not k:
        raise QuoteError("alphavantage", "ALPHAVANTAGE_API_KEY is not set")
    d = _get(
        f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&outputsize=full&symbol={symbol.upper()}&apikey={k}",
        provider="alphavantage",
    )
    ts = d.get("Time Series (Daily)")
    if not ts:
        msg = d.get("Note") or d.get("Information") or d.get("Error Message") or "no time series"
        raise QuoteError("alphavantage", msg, hint="daily cap or invalid symbol")
    days = sorted(ts)[-260:]
    closes = [float(ts[x]["4. close"]) for x in days]; vols = [float(ts[x]["5. volume"]) for x in days]
    last = ts[days[-1]]
    q = {"symbol": symbol.upper(), "price": closes[-1], "prev_close": closes[-2], "open": float(last["1. open"]),
         "day_high": float(last["2. high"]), "day_low": float(last["3. low"]), "volume": vols[-1],
         "closes": closes, "_volumes": vols, "source": "alphavantage"}
    return _finish(q)


def _alpaca_headers():
    kid, sec = os.environ.get("ALPACA_API_KEY_ID"), os.environ.get("ALPACA_API_SECRET_KEY")
    if not (kid and sec):
        raise QuoteError("alpaca", "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY are not set")
    return {"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": sec}


def alpaca_calendar(year):
    """Official trading-day list from Alpaca Trading API (paper host by default)."""
    h = _alpaca_headers()
    import market_calendar as mc
    url = mc.alpaca_calendar_url(year)
    rows = _get(url, headers=h, provider="alpaca")
    if not isinstance(rows, list):
        raise QuoteError("alpaca", "calendar response was not a list")
    return rows


def from_alpaca(symbol):
    h = _alpaca_headers()
    d = _get(f"https://data.alpaca.markets/v2/stocks/{symbol.upper()}/snapshot", headers=h, provider="alpaca")
    trade = d.get("latestTrade") or {}
    daily = d.get("dailyBar") or {}
    prev = d.get("prevDailyBar") or {}
    price = trade.get("p")
    if price is None:
        price = (daily or {}).get("c")
    if price is None:
        raise QuoteError("alpaca", f"snapshot missing last price for {symbol}",
                         hint="symbol not on the US Alpaca feed, or market not yet open")
    closes, vols = [], []
    try:
        end = dt.date.today()
        start = end - dt.timedelta(days=420)
        bars = _get(
            f"https://data.alpaca.markets/v2/stocks/{symbol.upper()}/bars"
            f"?timeframe=1Day&start={start.isoformat()}&end={end.isoformat()}&limit=10000&adjustment=split",
            headers=h, provider="alpaca",
        )
        rows = bars.get("bars") or []
        closes = [float(b["c"]) for b in rows if b.get("c") is not None]
        vols = [float(b.get("v") or 0) for b in rows if b.get("c") is not None]
    except Exception:
        pass
    q = {"symbol": symbol.upper(), "price": price, "prev_close": prev.get("c"),
         "open": daily.get("o"), "day_high": daily.get("h"), "day_low": daily.get("l"),
         "volume": daily.get("v"), "closes": closes, "_volumes": vols, "source": "alpaca"}
    return _finish(q)


def earnings_from_yahoo(symbol, as_of_date=None):
    s = urllib.parse.quote(symbol.upper())
    errors = []
    d = None
    for host in YAHOO_HOSTS:
        url = f"https://{host}/v10/finance/quoteSummary/{s}?modules=calendarEvents"
        try:
            d = _get(url, provider="yahoo-earnings")
            break
        except Exception as e:
            errors.append(str(e))
    if d is None:
        raise QuoteError("yahoo-earnings", "; ".join(errors) or "no response")
    result = ((d.get("quoteSummary") or {}).get("result") or [{}])[0]
    earnings = ((result.get("calendarEvents") or {}).get("earnings") or {})
    dates = earnings.get("earningsDate") or earnings.get("earningsDateStart") or []
    today = as_of_date or dt.date.today()
    parsed = []
    for item in dates if isinstance(dates, list) else [dates]:
        iso = _first_iso_date(item)
        if iso:
            parsed.append(dt.date.fromisoformat(iso))
    future = [x for x in parsed if x >= today]
    pick = min(future) if future else (max(parsed) if parsed else None)
    return pick.isoformat() if pick else None


def earnings_from_finnhub(symbol, as_of_date=None):
    k = _finnhub_key()
    today = as_of_date or dt.date.today()
    start = today - dt.timedelta(days=5)
    end = today + dt.timedelta(days=120)
    d = _get(
        f"https://finnhub.io/api/v1/calendar/earnings?from={start.isoformat()}&to={end.isoformat()}"
        f"&symbol={symbol.upper()}&token={k}",
        provider="finnhub",
    )
    rows = d.get("earningsCalendar") or d.get("earnings") or []
    future = []
    for row in rows:
        iso = _first_iso_date((row or {}).get("date") or (row or {}).get("reportDate"))
        if not iso:
            continue
        day = dt.date.fromisoformat(iso)
        if day >= today:
            future.append(day)
    return min(future).isoformat() if future else None


def earnings_from_alphavantage(symbol, as_of_date=None):
    k = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not k:
        raise QuoteError("alphavantage", "ALPHAVANTAGE_API_KEY is not set")
    body = _get(
        f"https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&symbol={symbol.upper()}&horizon=3month&apikey={k}",
        provider="alphavantage", raw=True,
    )
    text = body.decode() if isinstance(body, (bytes, bytearray)) else str(body)
    if text.lstrip().startswith("{"):
        d = json.loads(text)
        msg = d.get("Note") or d.get("Information") or d.get("Error Message") or "unexpected JSON"
        raise QuoteError("alphavantage", msg, hint="daily cap or invalid key")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    header = [c.strip() for c in lines[0].split(",")]
    try:
        idx = header.index("reportDate")
    except ValueError:
        idx = 2 if len(header) > 2 else 0
    today = as_of_date or dt.date.today()
    future = []
    for ln in lines[1:]:
        cols = [c.strip() for c in ln.split(",")]
        if idx >= len(cols):
            continue
        iso = _first_iso_date(cols[idx])
        if iso:
            day = dt.date.fromisoformat(iso)
            if day >= today:
                future.append(day)
    return min(future).isoformat() if future else None


def lookup_earnings(symbol, existing=None, as_of_date=None):
    """Return (iso_date, source) using the first source that yields a date."""
    if existing:
        return existing, "existing"
    steps = [("yahoo-calendar", earnings_from_yahoo)]
    if os.environ.get("FINNHUB_API_KEY"):
        steps.append(("finnhub", earnings_from_finnhub))
    if os.environ.get("ALPHAVANTAGE_API_KEY"):
        steps.append(("alphavantage", earnings_from_alphavantage))
    for name, fn in steps:
        try:
            ed = fn(symbol, as_of_date=as_of_date)
            if ed:
                return ed, name
        except Exception:
            continue
    return None, None


def _iv_to_percent(iv):
    """Yahoo chain IV is usually a decimal (0.25 = 25%). Values already in percent pass through."""
    if iv is None:
        return None
    try:
        iv = float(iv)
    except (TypeError, ValueError):
        return None
    if iv <= 0:
        return None
    return iv * 100.0 if iv <= 4.0 else iv


def parse_yahoo_atm_iv(payload, price=None):
    """Nearest-expiry ATM call/put IV average (percent) from a Yahoo v7 options payload."""
    result = ((payload or {}).get("optionChain") or {}).get("result") or []
    if not result:
        return None
    result = result[0]
    if price is None:
        price = (result.get("quote") or {}).get("regularMarketPrice")
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    options = result.get("options") or []
    if not options:
        return None
    exp = options[0]
    calls, puts = {}, {}
    for c in exp.get("calls") or []:
        if c.get("strike") is not None:
            calls[float(c["strike"])] = c
    for p in exp.get("puts") or []:
        if p.get("strike") is not None:
            puts[float(p["strike"])] = p
    strikes = sorted(set(calls) | set(puts), key=lambda s: abs(s - price))
    picked = None
    for strike in strikes:
        ivs = []
        for opt in (calls.get(strike), puts.get(strike)):
            pct = _iv_to_percent((opt or {}).get("impliedVolatility"))
            if pct is not None:
                ivs.append(pct)
        if ivs:
            picked = {"atm_iv": sum(ivs) / len(ivs), "iv_strike": strike,
                      "iv_source": "yahoo-options"}
            break
    if not picked:
        return None
    raw = exp.get("expirationDate")
    expiry = None
    if raw is not None:
        try:
            expiry = dt.datetime.fromtimestamp(int(raw), dt.timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            expiry = str(raw)[:10]
    picked["iv_expiry"] = expiry
    return picked


def from_yahoo_options(symbol, price=None):
    """Unofficial Yahoo options chain; nearest expiration only."""
    s = urllib.parse.quote(symbol.upper())
    errors = []
    d = None
    for host in YAHOO_HOSTS:
        url = f"https://{host}/v7/finance/options/{s}"
        try:
            d = _get(url, provider="yahoo-options")
            break
        except Exception as e:
            errors.append(f"{host}: {e}")
    if d is None:
        raise QuoteError("yahoo-options", "options chain failed: " + "; ".join(errors),
                         hint="unofficial endpoint; IV alerts skip when the chain is empty")
    info = parse_yahoo_atm_iv(d, price=price)
    if not info:
        raise QuoteError("yahoo-options", f"no ATM IV for {symbol}",
                         hint="chain missing, or impliedVolatility was 0")
    return info


def attach_iv(q, fetch=None):
    """Fill ``atm_iv`` from Yahoo options if missing. Failures leave the field unset."""
    if q.get("atm_iv"):
        return q
    symbol = q.get("symbol")
    try:
        info = (fetch or from_yahoo_options)(symbol, q.get("price"))
    except Exception:
        info = None
    if info and info.get("atm_iv"):
        q["atm_iv"] = info["atm_iv"]
        q["iv_expiry"] = info.get("iv_expiry")
        q["iv_source"] = info.get("iv_source") or "yahoo-options"
        if info.get("iv_strike") is not None:
            q["iv_strike"] = info["iv_strike"]
    else:
        q.setdefault("atm_iv", None)
        q.setdefault("iv_expiry", None)
        q.setdefault("iv_source", None)
    return q


PROVIDERS = {"yfinance": from_yfinance, "yahoo": from_yahoo, "finnhub": from_finnhub,
             "alphavantage": from_alphavantage, "alpaca": from_alpaca}


def auto_order():
    order = []
    if os.environ.get("ALPACA_API_KEY_ID") and os.environ.get("ALPACA_API_SECRET_KEY"):
        order.append("alpaca")
    try:
        import yfinance  # noqa: F401
        order.append("yfinance")
    except ImportError:
        pass
    order.append("yahoo")
    if os.environ.get("FINNHUB_API_KEY"): order.append("finnhub")
    if os.environ.get("ALPHAVANTAGE_API_KEY"): order.append("alphavantage")
    return order


def get_quote(symbol, provider="auto", fixture=None, fetch_earnings=True):
    if fixture:
        return from_fixture(symbol, fixture)
    errors = []
    wanted = [provider] if provider != "auto" else auto_order()
    q = None
    for p in wanted:
        fn = PROVIDERS.get(p)
        if fn is None:
            errors.append(f"{p}: unknown provider")
            continue
        try:
            q = fn(symbol)
            break
        except Exception as e:
            errors.append(str(e) if str(e).startswith(f"{p}:") else f"{p}: {e}")
    if q is None:
        raise QuoteError("auto" if provider == "auto" else provider,
                         f"all providers failed for {symbol}: " + "; ".join(errors),
                         hint="set ALPACA_* keys for the official feed, or WATCHLIST_PROVIDER=yahoo")
    if fetch_earnings and not q.get("earnings_date"):
        ed, src = lookup_earnings(symbol)
        if ed:
            q["earnings_date"] = ed
            q["earnings_source"] = src
    return q


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--provider", default=os.environ.get("WATCHLIST_PROVIDER", "auto"))
    ap.add_argument("--fixture")
    ap.add_argument("--full", action="store_true", help="include closes history")
    ap.add_argument("--stale-after", type=int, default=int(os.environ.get("WATCHLIST_STALE_AFTER") or 900),
                    help="warn if as_of is older than N seconds (0=off)")
    ap.add_argument("--iv", action="store_true",
                    help="attach unofficial Yahoo ATM implied vol (skipped on --fixture unless already present)")
    a = ap.parse_args(argv)
    out = {}
    now = dt.datetime.now(dt.timezone.utc)
    for s in a.symbols:
        try:
            q = get_quote(s, a.provider, a.fixture)
            if a.iv and not a.fixture:
                attach_iv(q)
            if not a.full: q.pop("closes", None)
            if a.stale_after:
                age = quote_age_seconds(q, now)
                if age is not None and age > a.stale_after:
                    q["stale"] = True
                    q["age_seconds"] = int(age)
            out[s.upper()] = q
        except Exception as e:
            out[s.upper()] = {"error": str(e)}
    print(json.dumps(out, indent=2, default=str))
    return 1 if any("error" in v for v in out.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
