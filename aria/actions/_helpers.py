"""Shared helpers for action handlers."""

from __future__ import annotations

import json
import os
from typing import Any

import requests

PERPLEXITY_API_KEY = (os.environ.get("PERPLEXITY_API_KEY") or "").strip()
PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"


def json_result(data: Any) -> str:
    return json.dumps(data, default=str, indent=2)


def format_news_items(news: dict[str, Any], market: str | None = None) -> str:
    if not news:
        return "No market news loaded yet. Ask the user to refresh the Daily Market News Brief."

    if market and market.upper() != "ALL":
        items = news.get(market)
        if not items:
            for key in news:
                if key.lower() == market.lower():
                    items = news[key]
                    break
        if not items:
            return f"No news available for {market}."
        lines = [f"News for {market}:"]
        for i, item in enumerate(items[:5], 1):
            if not isinstance(item, dict):
                continue
            sentiment = item.get("sentiment") or "neutral"
            impact = " HIGH IMPACT" if item.get("high_impact_warning") else ""
            lines.append(f"{i}. {item.get('headline', 'No headline')} [{sentiment}{impact}]")
            if item.get("trader_relevance"):
                lines.append(f"   Trader note: {item['trader_relevance']}")
        return "\n".join(lines)

    lines = ["Today's WickSense market briefing:"]
    for mkt, items in news.items():
        if not items or not isinstance(items, list):
            continue
        top = items[0]
        if isinstance(top, dict):
            sentiment = top.get("sentiment") or "neutral"
            impact = " ⚠️" if top.get("high_impact_warning") else ""
            lines.append(f"- {mkt}: {top.get('headline', 'No headline')} [{sentiment}{impact}]")
    return "\n".join(lines) if len(lines) > 1 else "No market news loaded yet."


def fetch_perplexity_news(query: str) -> str:
    if not PERPLEXITY_API_KEY or "your-" in PERPLEXITY_API_KEY:
        return "Market news refresh unavailable — Perplexity API key not configured on backend."
    payload = {
        "model": "sonar-pro",
        "messages": [
            {"role": "system", "content": "Concise market news for day traders."},
            {"role": "user", "content": query},
        ],
        "temperature": 0.3,
        "max_tokens": 800,
    }
    try:
        resp = requests.post(
            PERPLEXITY_API_URL,
            headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
        if not resp.ok:
            return f"News refresh failed: HTTP {resp.status_code}"
        return resp.json().get("choices", [{}])[0].get("message", {}).get("content") or "No content."
    except Exception as exc:
        return f"News refresh error: {exc}"


def compute_unrealized_pnl(open_trades: list) -> float:
    total = 0.0
    for t in open_trades or []:
        total += float(t.get("unrealizedPnl") or t.get("pnl") or t.get("unrealized_pnl") or 0)
    return round(total, 2)


def compute_realized_pnl(closed_trades: list) -> float:
    total = 0.0
    for t in closed_trades or []:
        total += float(t.get("pnl") or t.get("realizedPnl") or t.get("realized_pnl") or 0)
    return round(total, 2)
