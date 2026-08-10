"""
Step A local proof — /live-candles honors outputsize.
Uses Flask test client + mocked fetch_live_market_data (no live provider / no deploy).
Run from backend root:
  python scripts_local_verify_live_candles_outputsize.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import app as backend_app  # noqa: E402


def _fake_df(n: int) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append(
            {
                "Datetime": f"2026-01-01T00:{i % 60:02d}:00Z",
                "Open": 100.0 + i,
                "High": 101.0 + i,
                "Low": 99.0 + i,
                "Close": 100.5 + i,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    calls = []

    def fake_fetch(market, interval="1h", outputsize=100, start_date=None, end_date=None):
        calls.append(
            {
                "market": market,
                "interval": interval,
                "outputsize": outputsize,
            }
        )
        return _fake_df(int(outputsize))

    backend_app.fetch_live_market_data = fake_fetch
    client = backend_app.app.test_client()

    results = []

    def check(label, url, expect_min, expect_exact=None):
        calls.clear()
        res = client.get(url)
        body = res.get_json() or {}
        count = int(body.get("count") or 0)
        candles = body.get("candles") or []
        echoed = body.get("outputsize")
        call = calls[0] if calls else None
        ok = res.status_code == 200 and count >= expect_min and len(candles) >= expect_min
        if expect_exact is not None:
            ok = ok and count == expect_exact and len(candles) == expect_exact
        if call is not None and expect_exact is not None:
            ok = ok and int(call["outputsize"]) == expect_exact
        results.append(
            {
                "label": label,
                "ok": ok,
                "status": res.status_code,
                "count": count,
                "candles_len": len(candles),
                "echo_outputsize": echoed,
                "upstream_call": call,
                "sample_keys": list((candles[0] or {}).keys()) if candles else [],
            }
        )

    check("out80", "/live-candles?market=Gold&interval=1h&outputsize=80", 80, 80)
    check("out110", "/live-candles?market=Gold&interval=1h&outputsize=110", 110, 110)
    check("out300", "/live-candles?market=Gold&interval=1h&outputsize=300", 300, 300)

    for market in ("Gold", "NASDAQ", "NaturalGas", "DowJones", "Forex", "Futures"):
        check(
            f"map_{market}",
            f"/live-candles?market={market}&interval=15m&outputsize=110",
            110,
            110,
        )

    # Default when omitted → LIVE_CANDLES_OUTPUTSIZE (100)
    calls.clear()
    res = client.get("/live-candles?market=Gold&interval=1h")
    body = res.get_json() or {}
    default_ok = (
        res.status_code == 200
        and int(body.get("count") or 0) == 100
        and calls
        and int(calls[0]["outputsize"]) == 100
    )
    results.append(
        {
            "label": "default_omitted",
            "ok": default_ok,
            "status": res.status_code,
            "count": body.get("count"),
            "upstream_call": calls[0] if calls else None,
        }
    )

    failed = [r for r in results if not r["ok"]]
    report = {
        "ok": len(failed) == 0,
        "fail_count": len(failed),
        "LIVE_CANDLES_OUTPUTSIZE_default": backend_app.LIVE_CANDLES_OUTPUTSIZE,
        "LIVE_CANDLES_OUTPUTSIZE_MAX": backend_app.LIVE_CANDLES_OUTPUTSIZE_MAX,
        "results": results,
    }
    import json

    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
