"""Quick bar-level replay of XAUUSD_Exness_Bot rules on 5-minute gold data.

Mirrors the EA: M15 EMA50/200 trend filter, M5 entry (RSI / EMA pullback /
Donchian), ATR stop capped in USD, 1.5R target, breakeven at 1R + ATR trail,
daily loss budget, max trades/day, losing-streak stop, 07-20 UTC session.

Data: Yahoo Finance GC=F (gold futures, last 60 days of 5m bars) - close to
Exness spot XAUUSD but not identical. Pessimistic fills: if SL and TP are both
inside one bar, the SL is assumed hit first. This is a sanity check, not a
replacement for the MT5 Strategy Tester on real Exness ticks.

    pip install yfinance pandas numpy
    python research/gold_backtest.py
"""
import numpy as np
import pandas as pd
import yfinance as yf

SPREAD = 0.30   # Exness Standard gold spread, $ price
VPP = 2.0       # $ per $1 gold move at 0.02 lot (2 oz)


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(c, n=14):
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def atr(df, n=14):
    tr = np.maximum(df.High - df.Low,
                    np.maximum(abs(df.High - df.Close.shift()), abs(df.Low - df.Close.shift())))
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def load():
    d = yf.download("GC=F", period="60d", interval="5m", progress=False)
    d.columns = [c[0] for c in d.columns]
    d.index = d.index.tz_convert("UTC")
    d = d[["Open", "High", "Low", "Close"]].dropna()
    d["atr"] = atr(d)
    d["rsi"] = rsi(d.Close)
    return d


def signals(d):
    m15 = d.resample("15min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    m15["f"], m15["s"] = ema(m15.Close, 50), ema(m15.Close, 200)

    def to5(series):  # M15 value known at bar close, aligned to the 5m bar closes
        s = series.copy()
        s.index = s.index + pd.Timedelta("15min")
        return s.reindex(d.index + pd.Timedelta("5min"), method="ffill").values

    up = to5((m15.f > m15.s) & (m15.Close > m15.f) & (m15.f > m15.f.shift(2))).astype(bool)
    dn = to5((m15.f < m15.s) & (m15.Close < m15.f) & (m15.f < m15.f.shift(2))).astype(bool)
    c = d.Close.values
    pc = np.r_[np.nan, c[:-1]]
    r = d.rsi.values
    pr = np.r_[np.nan, r[:-1]]
    e = ema(d.Close, 20).values
    pe = np.r_[np.nan, e[:-1]]
    dh = to5(m15.High.rolling(20).max())
    dl = to5(m15.Low.rolling(20).min())

    def pick(buy, sell):
        return np.where(up & buy, 1, np.where(dn & sell, -1, 0))

    return {
        "RSI pullback": pick((pr < 40) & (r >= 40), (pr > 60) & (r <= 60)),
        "EMA pullback": pick((pc <= pe) & (c > e), (pc >= pe) & (c < e)),
        "Donchian":     pick((pc <= dh) & (c > dh), (pc >= dl) & (c < dl)),
    }


def run(d, sig, sl_mult=1.0, rr=1.5, max_loss=10, daily=20, max_trades=3, max_streak=2,
        be_r=1.0, trail=1.0, start=7, end=20, lo=None, hi=None):
    O, H, L, C, A = d.Open.values, d.High.values, d.Low.values, d.Close.values, d.atr.values
    idx = d.index
    pos, trades, day = None, [], None
    for i in range(210, len(d) - 1):
        t = idx[i]
        if lo is not None and t < lo:
            continue
        if hi is not None and t >= hi:
            break
        if t.date() != day:
            day, dpnl, n, streak = t.date(), 0.0, 0, 0
        if pos:
            side, entry, sl, tp, R = pos
            px = None
            if t.weekday() == 4 and t.hour >= 20:
                px = O[i] if side > 0 else O[i] + SPREAD
            elif side > 0:
                px = min(sl, O[i]) if L[i] <= sl else (tp if H[i] >= tp else None)
            else:
                px = max(sl, O[i] + SPREAD) if H[i] + SPREAD >= sl else (tp if L[i] + SPREAD <= tp else None)
            if px is not None:
                p = (px - entry) * side * VPP
                trades.append(p)
                dpnl += p
                streak = streak + 1 if p < 0 else 0
                pos = None
            else:
                mk = C[i] if side > 0 else C[i] + SPREAD
                nsl = sl
                if be_r > 0 and (mk - entry) * side >= R * be_r:
                    be = entry + 0.10 * side
                    nsl = max(nsl, be) if side > 0 else min(nsl, be)
                if trail > 0 and ((nsl >= entry) if side > 0 else (nsl <= entry)):
                    tl = mk - A[i] * trail * side
                    nsl = max(nsl, tl) if side > 0 else min(nsl, tl)
                pos = (side, entry, nsl, tp, R)
        if pos:
            continue
        tn = idx[i + 1]
        if tn.weekday() >= 5 or not (start <= tn.hour < end) or (tn.weekday() == 4 and tn.hour >= 18):
            continue
        if n >= max_trades or streak >= max_streak or dpnl - max_loss < -daily:
            continue
        s = sig[i]
        if not s:
            continue
        sld = max(A[i] * sl_mult, 1.0, SPREAD)
        if sld * VPP > max_loss:
            continue
        entry = O[i + 1] + SPREAD if s > 0 else O[i + 1]
        pos = (s, entry, entry - sld * s, entry + sld * rr * s, sld)
        n += 1
    if not trades:
        return "no trades"
    p = np.array(trades)
    eq = np.r_[100, 100 + np.cumsum(p)]
    dd = (np.maximum.accumulate(eq) - eq).max()
    pf = p[p > 0].sum() / -p[p < 0].sum() if (p < 0).any() else float("inf")
    return f"trades={len(p):3d} win={100 * (p > 0).mean():3.0f}% net={p.sum():+7.1f}$ PF={pf:4.2f} maxDD={dd:5.1f}$"


if __name__ == "__main__":
    d = load()
    mid = d.index[0] + (d.index[-1] - d.index[0]) / 2
    med_atr = d.atr[(d.index.hour >= 7) & (d.index.hour < 20)].median()
    print(f"{d.index[0].date()} -> {d.index[-1].date()} | gold {d.Close.iloc[-1]:.0f} | median M5 ATR {med_atr:.2f}")
    for name, sig in signals(d).items():
        print(f"{name:13s} all: {run(d, sig)}")
        print(f"{'':13s} 1st half: {run(d, sig, hi=mid)} | 2nd half: {run(d, sig, lo=mid)}")
