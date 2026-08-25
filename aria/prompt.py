"""Build ARIA system prompt from client-supplied WickSense context."""

from __future__ import annotations

from typing import Any


STRATEGY_DIRECTORY = """
WICKSENSE STRATEGY DIRECTORY (use these exact names when referencing strategies):

CERTIFIED (Strategy Certification Standard v1 — frozen OHLC 2025-09-05→2026-03-05 1h):
- strategy_001 → "Bearish Rejection Snipe S001 Certified V1" (S001) — CERTIFIED Grade A/Pass
  Authoritative gates: body≥20% of range; wick = upperWick/body (strong≥1.2, medium floor 0.7); weak/micro OFF;
  next-candle close < signal low (3-bar timeout); MA50+below-VWAP confidence only; London/NY/overlap session;
  markets = matrix only. NEVER say min_wick_ratio 0.6 as % of range.
- strategy_002 → "Bullish Wick Rejection Sniper S002" (S002) — CERTIFIED Grade D/Pass
  Authoritative gates: body≥20% of range; wick = lowerWick/body (strong≥1.2, medium floor 0.7); weak/micro OFF;
  NO next-candle confirmation (entry on close); Support Strength Score + MA50 + above-VWAP = confidence only;
  London/NY/overlap; markets = matrix only. NEVER say min_wick_ratio 0.65, v3_enforcement, or entry above high.

OTHER:
- strategy_001_bullish → "S001 Bullish Support Bounce Sniper" (NOT the same as certified S002)
- strategy_003 / trend_pullback_wick_confirmation → "Trend Pullback Wick Confirmation" (S003) — Final Revision:
  LOOKBACK=20; 2-of-5 Trend Agreement; MA20/structure pullback 0.4% ATR-aware (NOT 1.5 ATR);
  wick ≥0.7× body (strong ≥1.2); next-candle confirm 3-bar timeout; London/NY (crypto independent).
  NEVER say missing wick ratio, pullback_depth_atr=1.5, or production lookback 50.
- strategy_004 / box_rejection → "Box Rejection" (S004)
- s105 / strategy_005_ema_pullback → "EMA Pullback Continuation V2" (S005)
- bull_bear_180_reversal → "Bull/Bear 180 Reversal" (S006)
- S101 / pin_bar → "S101 Pin Bar V2" (S101)
- s102 / doji_reversal_pro → "Doji Reversal Pro" (S102)
- bearish_confluence_setup → "Bearish Confluence Setup" (S103) — Aria gates: min confluence 4/4, ≥15M TF, bearish regime required, loss reason logging
- bearish_breakdown_continuation → "Bearish Breakdown Continuation" (S104)
- s111_v2 → "Support/Resistance Rejection V2" (S111)
- bearish_momentum_setup → "Bearish Momentum Setup"
- shooting_star → "Shooting Star" (S107) — bearish reversal
- s108 → "S108 Hammer" (S108) — V2 enforcement active, BUY-only
- bearish_trendline_rejection → "Bearish Trendline Rejection"
- bear_elephant_continuation → "WickSense T3 — Bear Elephant Continuation"
- wicksense_t1 → "WickSense T1 — Liquidity Sweep"
- doji_v2 → "Doji V2"
- bullish_confluence_setup → "Bullish Confluence Setup"

When the user asks for a full logic printout of S001 or S002, call explain_strategy / get_strategy_parameters
and quote the catalog parameters + entry_logic — do not invent V3 or % of range wick rules.
""".strip()


def detect_risk_warnings(state: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    market = state.get("activeMarket") or ""

    if market in ("XAUUSD",) or "Gold" in market:
        regime = state.get("marketRegime")
        if regime in ("HIGH_VOLATILITY", "EXTREME_VOLATILITY"):
            warnings.append(
                {
                    "type": "HIGH_VOLATILITY",
                    "message": "Gold is in high volatility. Exercise extreme caution.",
                }
            )

    blocked = state.get("blockedStrategies") or []
    if blocked:
        warnings.append(
            {
                "type": "BLOCKED_STRATEGY",
                "message": f"Strategies blocked: {', '.join(blocked)}",
            }
        )

    readiness = state.get("tradeReadiness")
    if readiness is not None and readiness < 50:
        warnings.append(
            {
                "type": "LOW_READINESS",
                "message": f"Trade readiness is {readiness}% — below threshold.",
            }
        )

    grade = state.get("setupGrade")
    if grade in ("F", "D"):
        warnings.append(
            {
                "type": "LOW_QUALITY",
                "message": f"Setup grade is {grade} — low quality setup detected.",
            }
        )

    if state.get("lineOfLeastResistance") == "WAIT":
        warnings.append(
            {
                "type": "WAIT_STATE",
                "message": "Market is in WAIT state. No clear directional bias.",
            }
        )

    discipline = state.get("disciplineScore")
    if discipline is not None and discipline < 40:
        warnings.append(
            {
                "type": "LOW_DISCIPLINE",
                "message": f"Discipline score is {discipline}/100 — trade blocked.",
            }
        )

    return warnings


def format_news_context(news: dict[str, Any]) -> str:
    if not news:
        return "No news loaded yet — user can refresh the Daily Market News Brief"

    lines: list[str] = []
    for market, items in news.items():
        if not items:
            lines.append(f"{market}: No news")
            continue
        top = items[0] if isinstance(items, list) else items
        if not isinstance(top, dict):
            continue
        sentiment = top.get("sentiment") or "neutral"
        warning = " ⚠️ HIGH IMPACT" if top.get("high_impact_warning") else ""
        lines.append(f"{market}: {top.get('headline', 'No headline')} [{sentiment}{warning}]")

    return "\n".join(lines) if lines else "No news loaded yet"


def build_aria_system_prompt(context: dict[str, Any] | None) -> str:
    ctx = context or {}
    state = ctx.get("state") or {}
    preferences = ctx.get("preferences") or {}
    news = ctx.get("news") or {}
    warnings = detect_risk_warnings(state)

    coaching = state.get("ariaCoachingMessages") or []
    coaching_text = "\n".join(coaching) if coaching else "None"

    warning_text = (
        "\n".join(f"- [{w['type']}] {w['message']}" for w in warnings)
        if warnings
        else "No active warnings"
    )

    stats_json = __import__("json").dumps(state.get("strategyStats") or {}, indent=2)

    memory = ctx.get("memory") or {}
    rulebook = ctx.get("memoryRulebook") or memory.get("memoryRulebook") or ""
    if not isinstance(rulebook, str):
        rulebook = str(rulebook) if rulebook else ""
    rulebook = rulebook.strip()

    prompt = f"""You are ARIA — the WickSense AI Trading Intelligence Assistant (Executive v2).

IDENTITY & ROLE:
- You are a voice-first trading intelligence layer embedded inside WickSense
- You analyze trading data, explain signals, warn about risks, and summarize performance
- You NEVER execute trades unless the user has explicitly authorized trade execution AND you use the execute_trade tool
- You NEVER guarantee trade outcomes
- You ALWAYS phrase recommendations as analysis, not financial advice
- You speak concisely — short, clear trading summaries, not long paragraphs
- Always prefix insights with "Based on WickSense data..." or "I recommend..." or "This setup is high risk..."

SAFETY RULES:
- Never claim trades are guaranteed
- Never give financial advice — only analysis
- Use tools to fetch live WickSense data, market news, strategy performance, and navigation
- Trading execution is disabled by default — if asked to place trades, explain that execution requires explicit user authorization

CURRENT APP STATE:
- Active Market: {state.get('activeMarket') or 'Unknown'}
- Active Timeframe: {state.get('activeTimeframe') or 'Unknown'}
- Current Signal: {state.get('currentSignal') or 'None'}
- Confidence: {f"{state.get('confidence')}%" if state.get('confidence') is not None else 'Unknown'}
- Trade Readiness: {f"{state.get('tradeReadiness')}%" if state.get('tradeReadiness') is not None else 'Unknown'}
- Market Regime: {state.get('marketRegime') or 'Unknown'}
- Entry Timing: {state.get('entryTiming') or 'Unknown'}
- Market State: {state.get('marketState') or 'Unknown'}
- Dominant Bias: {state.get('dominantBias') or 'Unknown'}
- Line of Least Resistance: {state.get('lineOfLeastResistance') or 'Unknown'}
- Trade Quality Score: {f"{state.get('tradeQualityScore')}/100" if state.get('tradeQualityScore') is not None else 'Unknown'}
- Setup Grade: {state.get('setupGrade') or 'Unknown'}
- Discipline Score: {f"{state.get('disciplineScore')}/100" if state.get('disciplineScore') is not None else 'Unknown'}
- PnL: {state.get('pnl') if state.get('pnl') is not None else 'Unknown'}
- Win Rate: {f"{state.get('winRate')}%" if state.get('winRate') is not None else 'Unknown'}
- Open Trades: {len(state.get('openTrades') or [])}
- Closed Trades: {len(state.get('closedTrades') or [])}
- Blocked Strategies: {', '.join(state.get('blockedStrategies') or []) or 'None'}
- Core Wick Confirmation: {state.get('coreWickConfirmation') or 'Unknown'}
- Last Signal Data: {state.get('lastSignalData') or 'None'}
- Broker Status: {state.get('brokerStatus') or 'Not connected / unknown'}

STRATEGY STATS:
{stats_json}

ACTIVE RISK WARNINGS:
{warning_text}

USER PREFERENCES:
- Preferred Markets: {', '.join(preferences.get('preferredMarkets') or []) or 'Not set'}
- Risk Tolerance: {preferences.get('riskTolerance') or 'moderate'}
- Isolated Strategies: {', '.join(preferences.get('isolatedStrategies') or []) or 'None'}
- Preferred Timeframes: {', '.join(preferences.get('preferredTimeframes') or []) or 'Not set'}
- Warning Markets: {', '.join(preferences.get('warningMarkets') or []) or 'None'}
- Favorite Strategies: {', '.join(preferences.get('favoriteStrategies') or []) or 'Not set'}
- Preferred Layouts: {', '.join(preferences.get('preferredLayouts') or []) or 'Default'}
- Frequently Used Commands: {', '.join((preferences.get('frequentlyUsedCommands') or [])[:5]) or 'None yet'}

OPEN TRADES: {len(state.get('openTrades') or [])} | CLOSED: {len(state.get('closedTrades') or [])}
UNREALIZED P&L: {state.get('unrealizedPnl') if state.get('unrealizedPnl') is not None else 'Unknown'}
REALIZED P&L: {state.get('realizedPnl') if state.get('realizedPnl') is not None else state.get('pnl') if state.get('pnl') is not None else 'Unknown'}
ACTIVE ALERTS: {len(state.get('alerts') or [])}
ENABLED MARKETS: {', '.join(state.get('enabledMarkets') or []) or 'Unknown'}

DAILY MARKET NEWS (from Daily Market News Brief):
{format_news_context(news)}

ARIA COACHING MESSAGES:
{coaching_text}

{STRATEGY_DIRECTORY}

NAVIGATION:
Use the navigate_to_page tool when the user asks to open a WickSense page.

RESPONSE STYLE:
- Be concise and direct — 1-3 sentences max for most responses
- Use trading terminology naturally
- Lead with the most important insight
- End with a clear recommendation or next step"""

    if rulebook:
        prompt += (
            "\n\nPERSONAL / USER RECALL (user-saved memories from the Memory page. "
            "Use these for personal facts such as the user's name. "
            "Custom and Conversation Summary entries are personal recall, not trading rules):\n"
            f"{rulebook}"
        )
    return prompt


def build_context_summary_for_voice(context: dict[str, Any] | None) -> str:
    """Compact summary for ElevenLabs dynamicVariables / contextual updates."""
    ctx = context or {}
    state = ctx.get("state") or {}
    warnings = detect_risk_warnings(state)
    parts = [
        f"Market: {state.get('activeMarket') or 'Unknown'}",
        f"Signal: {state.get('currentSignal') or 'None'}",
        f"Readiness: {state.get('tradeReadiness') if state.get('tradeReadiness') is not None else 'Unknown'}%",
        f"Open: {len(state.get('openTrades') or [])}",
        f"PnL: {state.get('pnl') if state.get('pnl') is not None else 'Unknown'}",
        f"Warnings: {len(warnings)}",
    ]
    return " | ".join(parts)


def build_full_context_for_voice(context: dict[str, Any] | None) -> dict[str, Any]:
    """Structured context blob — voice and text use identical data."""
    ctx = context or {}
    state = ctx.get("state") or {}
    return {
        "market": state.get("activeMarket"),
        "timeframe": state.get("activeTimeframe"),
        "signal": state.get("currentSignal"),
        "confidence": state.get("confidence"),
        "readiness": state.get("tradeReadiness"),
        "openTrades": len(state.get("openTrades") or []),
        "closedTrades": len(state.get("closedTrades") or []),
        "pnl": state.get("pnl"),
        "unrealizedPnl": state.get("unrealizedPnl"),
        "realizedPnl": state.get("realizedPnl"),
        "winRate": state.get("winRate"),
        "brokerStatus": state.get("brokerStatus"),
        "topTrade": state.get("topTrade") or state.get("lastSignalData"),
        "alerts": len(state.get("alerts") or []),
        "enabledMarkets": state.get("enabledMarkets") or [],
        "strategyCount": len(state.get("strategyStats") or {}),
        "newsMarkets": list((ctx.get("news") or {}).keys()),
        "riskWarnings": detect_risk_warnings(state),
    }
