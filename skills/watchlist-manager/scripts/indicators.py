"""Pure-Python technical indicators. Input lists are oldest -> newest."""
from __future__ import annotations


def sma(values, n):
    if len(values) < n or n <= 0:
        return None
    return sum(values[-n:]) / n


def rsi(closes, n=14):
    """Wilder's RSI."""
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for a, b in zip(closes[:-1], closes[1:]):
        ch = b - a
        gains.append(max(ch, 0)); losses.append(max(-ch, 0))
    ag = sum(gains[:n]) / n; al = sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag = (ag * (n - 1) + g) / n; al = (al * (n - 1) + l) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def ma_cross(closes, fast=50, slow=200):
    """'golden' / 'death' if fast crossed slow on the latest bar, else None."""
    if len(closes) < slow + 1:
        return None
    pf, ps = sma(closes[:-1], fast), sma(closes[:-1], slow)
    cf, cs = sma(closes, fast), sma(closes, slow)
    if pf <= ps and cf > cs:
        return "golden"
    if pf >= ps and cf < cs:
        return "death"
    return None


def price_cross_ma(closes, n):
    """'above'/'below' if the last close crossed its n-day SMA, else None."""
    if len(closes) < n + 1:
        return None
    prev_ma, cur_ma = sma(closes[:-1], n), sma(closes, n)
    if closes[-2] <= prev_ma and closes[-1] > cur_ma:
        return "above"
    if closes[-2] >= prev_ma and closes[-1] < cur_ma:
        return "below"
    return None
