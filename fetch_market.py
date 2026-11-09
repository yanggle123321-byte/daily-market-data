#!/usr/bin/env python3
"""Fetch daily market closes for the hedge-fund briefing and the Track-Huijin space.

Free data only (akshare, no API keys, no paid endpoints). Writes a single
market_snapshot.json that Muse / the spaces read instead of fetching live data.

Indices covered:
  - The 4 broad indices Central Huijin buys: CSI 300, SSE 50, STAR 50, ChiNext.
  - The 6 major indices of the stock-market dashboard: SSE Composite, SZSE
    Component, Hang Seng, S&P 500, Nasdaq, Dow Jones.

For every index we record the latest close, its date, and the drawdown vs the
250-trading-day highest CLOSE (the same "buy zone" logic as the Track-Huijin
space). A single failing index never kills the run: it is recorded as an
error entry and the rest still land in the file.
"""

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import akshare as ak

# ---------------------------------------------------------------------------
# Index catalogue
#   code : short identifier used in the JSON
#   name : display name (zh)
#   kind : "zh" (A-share, stock_zh_index_daily), "hk" (stock_hk_index_daily_sina),
#          "us" (index_us_stock_sina)
#   symbol : the symbol akshare expects
#   group : "huijin" (the 4 broad ETFs Huijin buys) or "major" (dashboard indices)
# ---------------------------------------------------------------------------
INDICES = [
    # --- Huijin broad indices ---
    {"code": "000300", "name": "沪深300", "kind": "zh", "symbol": "sh000300", "group": "huijin"},
    {"code": "000016", "name": "上证50", "kind": "zh", "symbol": "sh000016", "group": "huijin"},
    {"code": "000688", "name": "科创50", "kind": "zh", "symbol": "sh000688", "group": "huijin"},
    {"code": "399006", "name": "创业板指", "kind": "zh", "symbol": "sz399006", "group": "huijin"},
    # --- Major dashboard indices ---
    {"code": "000001", "name": "上证指数", "kind": "zh", "symbol": "sh000001", "group": "major"},
    {"code": "399001", "name": "深证成指", "kind": "zh", "symbol": "sz399001", "group": "major"},
    {"code": "HSI", "name": "恒生指数", "kind": "hk", "symbol": "HSI", "group": "major"},
    {"code": ".INX", "name": "标普500", "kind": "us", "symbol": ".INX", "group": "major"},
    {"code": ".IXIC", "name": "纳斯达克", "kind": "us", "symbol": ".IXIC", "group": "major"},
    {"code": ".DJI", "name": "道琼斯", "kind": "us", "symbol": ".DJI", "group": "major"},
]

LOOKBACK_DAYS = 250          # trailing window for the "250-day high" drawdown
MAX_ATTEMPTS = 2             # attempts per index before recording an error
RETRY_SLEEP_S = 8            # seconds between attempts (Eastmoney rate-limits)
OUTPUT = Path(__file__).resolve().parent / "market_snapshot.json"

# Buy-zone thresholds (same as the Track-Huijin space).
BUY_ZONE_PCT = -15.0        # drawdown <= -15%  -> "buy"
WATCH_ZONE_PCT = -10.0      # -15% < drawdown <= -10% -> "watch"; else "neutral"


def fetch_daily(kind, symbol):
    """Return a DataFrame with at least `date` and `close` columns."""
    if kind == "zh":
        return ak.stock_zh_index_daily(symbol=symbol)
    if kind == "hk":
        return ak.stock_hk_index_daily_sina(symbol=symbol)
    if kind == "us":
        return ak.index_us_stock_sina(symbol=symbol)
    raise ValueError(f"unknown kind {kind!r}")


def fetch_one(spec):
    """Fetch one index with retries. Returns an entry dict (ok or error)."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            df = fetch_daily(spec["kind"], spec["symbol"])
            if df is None or len(df) < 2 or "close" not in df.columns:
                raise ValueError("empty or malformed response")
            df = df.dropna(subset=["close"])
            closes = df["close"].astype(float)
            last_close = float(closes.iloc[-1])
            last_date = str(df["date"].iloc[-1])[:10]
            window = closes.tail(LOOKBACK_DAYS)
            high_250 = float(window.max())
            drawdown = (last_close - high_250) / high_250 * 100.0
            if drawdown <= BUY_ZONE_PCT:
                zone = "buy"
            elif drawdown <= WATCH_ZONE_PCT:
                zone = "watch"
            else:
                zone = "neutral"
            return {
                "code": spec["code"],
                "name": spec["name"],
                "group": spec["group"],
                "close": round(last_close, 2),
                "date": last_date,
                "high_250d": round(high_250, 2),
                "drawdown_pct": round(drawdown, 2),
                "zone": zone,
                "status": "ok",
            }
        except Exception as exc:  # noqa: BLE001 - record and retry / continue
            last_error = f"{type(exc).__name__}: {exc}"
            print(f"  [{spec['code']}] attempt {attempt}/{MAX_ATTEMPTS} failed: {last_error}", flush=True)
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_SLEEP_S)
    return {
        "code": spec["code"],
        "name": spec["name"],
        "group": spec["group"],
        "close": None,
        "date": None,
        "high_250d": None,
        "drawdown_pct": None,
        "zone": None,
        "status": "error",
        "error": (last_error or "unknown error")[:300],
    }


def main():
    out_path = Path(os.environ.get("OUTPUT_PATH", OUTPUT))
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    entries = []
    for spec in INDICES:
        print(f"fetching {spec['code']} {spec['name']} ...", flush=True)
        entry = fetch_one(spec)
        if entry["status"] == "ok":
            print(f"  ok: close={entry['close']} date={entry['date']} "
                  f"drawdown={entry['drawdown_pct']}% zone={entry['zone']}", flush=True)
        else:
            print(f"  ERROR: {entry.get('error')}", flush=True)
        entries.append(entry)

    ok_count = sum(1 for e in entries if e["status"] == "ok")
    snapshot = {
        "generated_at": generated_at,
        "indices": entries,
        "summary": {"total": len(entries), "ok": ok_count, "error": len(entries) - ok_count},
        "source": "akshare (Eastmoney/Sina quote endpoints); free, no API key. "
                  "Drawdown is vs the trailing 250-trading-day highest CLOSE. "
                  "Zones: buy <= -15%, watch -15%..-10%, neutral > -10%.",
    }
    # Atomic write: temp file + replace, so a half-written file is never committed.
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(out_path)
    print(f"wrote {out_path} ({ok_count}/{len(entries)} ok)", flush=True)
    return 0 if ok_count == len(entries) else 0  # partial success is still a snapshot


if __name__ == "__main__":
    raise SystemExit(main())
