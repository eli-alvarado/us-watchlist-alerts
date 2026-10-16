"""NYSE trading calendar and session helpers (US/Eastern). Stdlib only.

Regular holidays and early closes are rule-based. Unscheduled closures come from:

1. ``data/holidays_overrides.json`` (known mourning / weather days; incomplete)
2. ``NYSE_EXTRA_CLOSURES`` (comma-separated ``YYYY-MM-DD``)
3. watchlist ``settings.extra_closures``
4. Optional Alpaca Trading API calendar overlay when API keys are set
   (official weekdays-with-no-session; see ``refresh_official_calendar``)
"""
from __future__ import annotations
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    ET = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError as e:
    raise RuntimeError(
        "America/New_York timezone data is missing. On Windows run: pip install tzdata"
    ) from e


def _data_file(name):
    """Resolve bundled data next to a git clone (`repo/data`) or a skill copy (`skill/data`)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        os.path.join(os.path.dirname(here), "data", name),
        os.path.join(here, "data", name),
    ):
        if os.path.exists(cand):
            return cand
    return os.path.join(os.path.dirname(here), "data", name)


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OVERRIDE_PATH = _data_file("holidays_overrides.json")
_OFFICIAL_CLOSED: dict[dt.date, str] = {}
_OVERRIDE_CACHE: dict[dt.date, str] | None = None


def _nth_weekday(year, month, weekday, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    d = dt.date(year, month + 1, 1) - dt.timedelta(days=1) if month < 12 else dt.date(year, 12, 31)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year):
    a = year % 19; b = year // 100; c = year % 100
    d = b // 4; e = b % 4; f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i = c // 4; k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7; m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31; day = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def _observed(d):
    if d.weekday() == 5:
        return d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


def parse_dates(values):
    """Coerce an iterable of ISO strings or dates into a set of ``date`` objects."""
    out = set()
    for v in values or []:
        if isinstance(v, dt.datetime):
            out.add(v.date())
        elif isinstance(v, dt.date):
            out.add(v)
        else:
            s = str(v).strip()
            if s:
                out.add(dt.date.fromisoformat(s[:10]))
    return out


def bundled_overrides(path=None):
    """Named unscheduled closures shipped in data/holidays_overrides.json."""
    global _OVERRIDE_CACHE
    if path is None and _OVERRIDE_CACHE is not None:
        return dict(_OVERRIDE_CACHE)
    p = path or _OVERRIDE_PATH
    out: dict[dt.date, str] = {}
    if os.path.exists(p):
        with open(p) as f:
            data = json.load(f)
        for row in data.get("closures") or []:
            d = dt.date.fromisoformat(str(row["date"])[:10])
            out[d] = row.get("name") or "unscheduled closure"
    if path is None:
        _OVERRIDE_CACHE = dict(out)
    return out


def extra_closures(extra=None):
    """All additive full-day closures: bundled file + env + extra + official overlay."""
    out = set(bundled_overrides())
    out |= parse_dates(extra)
    raw = os.environ.get("NYSE_EXTRA_CLOSURES") or ""
    for part in raw.split(","):
        part = part.strip()
        if part:
            out.add(dt.date.fromisoformat(part[:10]))
    out |= set(_OFFICIAL_CLOSED)
    return out


def nyse_holidays(year):
    """Full-day NYSE closures for a year (rule-based; excludes ad-hoc closures)."""
    h = {
        _nth_weekday(year, 1, 0, 3): "Martin Luther King Jr. Day",
        _nth_weekday(year, 2, 0, 3): "Washington's Birthday",
        _easter(year) - dt.timedelta(days=2): "Good Friday",
        _last_weekday(year, 5, 0): "Memorial Day",
        _nth_weekday(year, 9, 0, 1): "Labor Day",
        _nth_weekday(year, 11, 3, 4): "Thanksgiving Day",
    }
    ny = dt.date(year, 1, 1)
    if ny.weekday() != 5:  # NYSE does not observe Sat New Year's on the prior Friday
        h[_observed(ny)] = "New Year's Day"
    if year >= 2022:
        h[_observed(dt.date(year, 6, 19))] = "Juneteenth"
    h[_observed(dt.date(year, 7, 4))] = "Independence Day"
    h[_observed(dt.date(year, 12, 25))] = "Christmas Day"
    return h


def holiday_name(d: dt.date, extra=None) -> str | None:
    named = bundled_overrides().get(d) or _OFFICIAL_CLOSED.get(d)
    if named:
        return named
    if extra is not None and d in parse_dates(extra):
        return "unscheduled closure"
    raw = os.environ.get("NYSE_EXTRA_CLOSURES") or ""
    env_dates = parse_dates(p.strip() for p in raw.split(",") if p.strip())
    if d in env_dates:
        return "unscheduled closure"
    return nyse_holidays(d.year).get(d)


def early_closes(year):
    """Days the market closes at 1:00 PM ET."""
    out = set()
    tg = _nth_weekday(year, 11, 3, 4)
    out.add(tg + dt.timedelta(days=1))
    ce = dt.date(year, 12, 24)
    if ce.weekday() < 5:
        out.add(ce)
    j3 = dt.date(year, 7, 3)
    if j3.weekday() < 4:
        out.add(j3)
    hol = nyse_holidays(year)
    return {d for d in out if d.weekday() < 5 and d not in hol}


def is_trading_day(d: dt.date, extra=None) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year) and d not in extra_closures(extra)


def session(now: dt.datetime | None = None, extra=None) -> str:
    """Return one of: closed, pre, regular, after."""
    now = (now or dt.datetime.now(ET)).astimezone(ET)
    if not is_trading_day(now.date(), extra=extra):
        return "closed"
    t = now.time()
    close = dt.time(13, 0) if now.date() in early_closes(now.year) else dt.time(16, 0)
    after_end = dt.time(17, 0) if close == dt.time(13, 0) else dt.time(20, 0)
    if dt.time(4, 0) <= t < dt.time(9, 30):
        return "pre"
    if dt.time(9, 30) <= t < close:
        return "regular"
    if close <= t < after_end:
        return "after"
    return "closed"


def next_trading_day(d: dt.date, extra=None) -> dt.date:
    d += dt.timedelta(days=1)
    while not is_trading_day(d, extra=extra):
        d += dt.timedelta(days=1)
    return d


def closures_from_trading_days(year, open_dates):
    """Weekdays in ``year`` that are missing from an official set of session dates."""
    open_dates = set(open_dates)
    closed = {}
    d = dt.date(year, 1, 1)
    last = dt.date(year, 12, 31)
    while d <= last:
        if d.weekday() < 5 and d not in open_dates:
            closed[d] = "official calendar (market closed)"
        d += dt.timedelta(days=1)
    return closed


def set_official_closures(mapping):
    """Install a date->name map from an official calendar overlay (tests / live fetch)."""
    _OFFICIAL_CLOSED.clear()
    for d, name in (mapping or {}).items():
        if not isinstance(d, dt.date):
            d = dt.date.fromisoformat(str(d)[:10])
        _OFFICIAL_CLOSED[d] = name or "official calendar (market closed)"
    return dict(_OFFICIAL_CLOSED)


def clear_official_closures():
    _OFFICIAL_CLOSED.clear()


def alpaca_calendar_url(year):
    base = (os.environ.get("ALPACA_API_BASE") or "https://paper-api.alpaca.markets").rstrip("/")
    return f"{base}/v2/calendar?start={year}-01-01&end={year}-12-31"


def calendar_cache_path():
    return os.environ.get("NYSE_CALENDAR_CACHE") or os.path.join(os.getcwd(), ".nyse_calendar_cache.json")


def load_calendar_cache(year, path=None, today=None, allow_stale=False):
    """Return a date->name map if the on-disk cache matches ``year``.

    Fresh cache: ``fetched`` date equals ``today`` (ET). ``allow_stale`` keeps a
    same-year file when today's fetch failed so HEARTBEAT still has an overlay.
    """
    path = path or calendar_cache_path()
    today = today or dt.datetime.now(ET).date()
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or data.get("year") != year:
        return None
    fetched = str(data.get("fetched") or "")[:10]
    if fetched != today.isoformat() and not allow_stale:
        return None
    mapping = {}
    for row in data.get("closures") or []:
        try:
            d = dt.date.fromisoformat(str(row["date"])[:10])
        except (KeyError, TypeError, ValueError):
            continue
        mapping[d] = row.get("name") or "official calendar (market closed)"
    return mapping


def save_calendar_cache(year, mapping, path=None, today=None):
    path = path or calendar_cache_path()
    today = today or dt.datetime.now(ET).date()
    payload = {
        "year": year,
        "fetched": today.isoformat(),
        "closures": [{"date": d.isoformat(), "name": name} for d, name in sorted(mapping.items())],
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return path


def refresh_official_calendar(year, fetch=None, cache_path=None, today=None):
    """Pull Alpaca's trading calendar and treat missing weekdays as closures.

    No-op (returns {}) when keys are missing. ``fetch`` is injected in tests.
    Live fetches are disk-cached for the ET calendar day (``NYSE_CALENDAR_CACHE``,
    default ``.nyse_calendar_cache.json``) so HEARTBEAT ticks skip ``/v2/calendar``.
    Injected ``fetch`` does not read the default cache unless ``cache_path`` is set.
    """
    today = today or dt.datetime.now(ET).date()
    if fetch is None and not (os.environ.get("ALPACA_API_KEY_ID") and os.environ.get("ALPACA_API_SECRET_KEY")):
        return {}
    path = cache_path if cache_path is not None else (calendar_cache_path() if fetch is None else None)
    if path:
        cached = load_calendar_cache(year, path=path, today=today)
        if cached is not None:
            return set_official_closures(cached)
    try:
        if fetch is None:
            import quotes as qt
            rows = qt.alpaca_calendar(year)
        else:
            rows = fetch(year)
    except Exception:
        if path:
            stale = load_calendar_cache(year, path=path, today=today, allow_stale=True)
            if stale is not None:
                return set_official_closures(stale)
        raise
    open_dates = set()
    for row in rows or []:
        raw = row.get("date") if isinstance(row, dict) else row
        if raw:
            open_dates.add(dt.date.fromisoformat(str(raw)[:10]))
    mapping = closures_from_trading_days(year, open_dates)
    if path:
        try:
            save_calendar_cache(year, mapping, path=path, today=today)
        except OSError:
            pass
    return set_official_closures(mapping)


if __name__ == "__main__":
    n = dt.datetime.now(ET)
    try:
        refresh_official_calendar(n.year)
    except Exception as e:
        print(f"official calendar skipped: {e}", flush=True)
    why = holiday_name(n.date()) or ""
    extra = f" holiday={why}" if why else ""
    print(f"{n:%Y-%m-%d %H:%M %Z} session={session(n)} trading_day={is_trading_day(n.date())}{extra}")
