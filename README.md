# Daily market snapshot (free GitHub Actions)

A daily job that fetches A-share and overseas index closes and writes one
`market_snapshot.json`, so Muse and the spaces (hedge-fund morning briefing,
跟踪汇金， 股市看板） can read fresh market data instead of Muse fetching
live data on every run — which is what burns the token budget.

## What it fetches

All from **akshare** (free Eastmoney/Sina quote endpoints). No API key, no
paid source, no secrets.

| Group | Index | Code |
|---|---|---|
| Huijin (the 4 broad ETFs Central Huijin buys) | 沪深300 | 000300 |
| Huijin | 上证50 | 000016 |
| Huijin | 科创50 | 000688 |
| Huijin | 创业板指 | 399006 |
| Major (stock-market dashboard) | 上证指数 | 000001 |
| Major | 深证成指 | 399001 |
| Major | 恒生指数 | HSI |
| Major | 标普500 | .INX |
| Major | 纳斯达克 | .IXIC |
| Major | 道琼斯 | .DJI |

## Schedule

- **Cron:** `30 8 * * *` — 08:30 UTC = 16:30 CST, daily, after the 15:00
  A-share close. (GitHub cron is UTC; runs may lag a few minutes.)
- **Manual:** the workflow also has `workflow_dispatch`, so you can press
  "Run workflow" any time for testing.
- Runs on `ubuntu-latest` (free tier). It commits `market_snapshot.json`
  back to the repo with the built-in `GITHUB_TOKEN` — no extra secret needed.

## Output: `market_snapshot.json`

```json
{
  "generated_at": "2026-11-08T08:30:00Z",
  "indices": [
    {
      "code": "000300",
      "name": "沪深300",
      "group": "huijin",
      "close": 4054.28,
      "date": "2026-11-06",
      "high_250d": 5060.0,
      "drawdown_pct": -19.88,
      "zone": "buy",
      "status": "ok"
    }
  ],
  "summary": { "total": 10, "ok": 10, "error": 0 },
  "source": "akshare (Eastmoney/Sina quote endpoints); free, no API key. ..."
}
```

Field notes:

- `close` / `date` — latest close and its trading date. On weekends/holidays
  this is the last trading day's close (data is not "live" intraday).
- `high_250d` — highest CLOSE over the trailing 250 trading days.
- `drawdown_pct` — `(close - high_250d) / high_250d * 100`. Same definition as
  the 跟踪汇金 space's drawdown gauge.
- `zone` — buy / watch / neutral, from the drawdown:
  `buy` ≤ −15%, `watch` −15%…−10%, `neutral` > −10%.
  (Same thresholds as the 跟踪汇金 space.)
- `status` — `"ok"`, or `"error"` with an `error` message if that index's
  fetch failed. A single failure never kills the run; the other indices
  still land in the file.

## Reliability

- Each index fetch retries once (2 attempts, 8 s apart) for transient
  failures. Eastmoney has rate-limited a shared-IP host before, so the
  script never aborts on one index.
- The JSON is written atomically (temp file + rename) so a half-written
  file is never committed.

## Run it locally

```bash
pip install akshare
python fetch_market.py   # writes market_snapshot.json next to the script
```

## How Muse / the spaces use it

Read `market_snapshot.json` from the repo (raw file or a checkout) instead
of calling a live quote API. For the 07:30 morning briefing, read the file
committed the previous afternoon (16:30 run) — it holds Friday's close on a
Monday morning, which is exactly the "latest close" the briefing needs.
