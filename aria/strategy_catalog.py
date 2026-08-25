"""WickSense strategy knowledge base for ARIA explain/validate tools.

Authoritative certified engines (Strategy Certification Standard v1):
  - S001: Bearish Rejection Snipe S001 Certified V1
  - S002: Bullish Wick Rejection Sniper S002
  - S003: RETIRED (Failed Certification v1) — archived; NOT active
  - S005: EMA Pullback Continuation — live catalog id strategy_005_ema_pullback (EMA20, NOT 9/21/50 V2)
Do NOT invent min_wick_ratio % of range or V3 flags for these — use parameters below.
Do NOT describe S003/S004 as Active / scanning / Top Trade eligible.
Do NOT describe S005 as EMA 9/21/50 V2 — that is S105 lab, not S005.
"""

from __future__ import annotations

import json
from typing import Any

STRATEGY_CATALOG: dict[str, dict[str, Any]] = {
    "strategy_001": {
        "id": "strategy_001",
        "name": "Bearish Wick Rejection Sniper",
        "certified_name": "Bearish Rejection Snipe S001 Certified V1",
        "certified_version": "S001-CERTIFIED-V1",
        "code": "S001",
        "direction": "bearish",
        "status": "CERTIFIED",
        "aliases": [
            "s001",
            "bearish wick rejection sniper",
            "bearish rejection snipe",
            "bearish rejection snipe s001 certified v1",
            "strategy_001_bearish",
        ],
        "certification": {
            "grade": "A",
            "verdict": "Pass",
            "standard": "wicksense-strategy-certification-standard-v1",
            "locked": True,
            "window": "2025-09-05 → 2026-03-05 1h UTC",
        },
        "description": (
            "Bearish Rejection Snipe S001 Certified V1 — body≥20% of range, "
            "wick floor medium (upperWick/body ≥ 0.7; strong ≥ 1.2), next-candle "
            "close below signal low (3-candle timeout), London/NY/overlap session. "
            "MA50 + below-VWAP = confidence only. Markets via matrix only. Grade A / Pass."
        ),
        "entry_logic": [
            "Body ≥ 20% of candle range (blocks doji / inflated wick ratios)",
            "Upper wick / body ≥ 0.7 (medium floor); strong ≥ 1.2× — weak/micro DISABLED",
            "Bearish close below midpoint of the candle range",
            "Next candle must close below rejection candle low (expires after 3 candles)",
            "Medium tier requires resistance proximity; strong may fire without it",
            "MA50 and below-VWAP inflate confidence only — never hard rejects",
            "Session gate: London, New York, or overlap only (Asia/off-hours blocked)",
            "Markets: strategy × market matrix only — no hardcoded Gold/NASDAQ list",
            "Entry at rejection/confirmation close; SL above wick high; RR floors strong 1.5 / medium 1.2",
            "LOCKED certified build — do not change gates without a new certification",
        ],
        "parameters": {
            "min_body_pct_of_range": 0.20,
            "wick_metric": "upper_wick / body (NOT % of range)",
            "wick_tier_strong": 1.2,
            "wick_tier_medium_floor": 0.7,
            "weak_micro_tiers": False,
            "confirmation": "next_close_below_signal_low",
            "confirmation_timeout_candles": 3,
            "ma50": "confidence_only",
            "vwap": "confidence_bonus_when_below",
            "session": "london_ny_overlap",
            "markets": "strategy_market_matrix",
        },
        "common_myths": [
            "NOT min_wick_ratio 0.6 as % of candle range — that catalog value was wrong",
            "Micro/weak wick tiers are disabled on the certified build",
        ],
    },
    "strategy_001_bullish": {
        "id": "strategy_001_bullish",
        "name": "S001 Bullish Support Bounce Sniper",
        "code": "S001 Bullish",
        "direction": "bullish",
        "status": "ACTIVE",
        "description": (
            "Optional bullish counterpart path inside the S001 module. "
            "NOT the same as certified S002 (Bullish Wick Rejection Sniper S002). "
            "Prefer S002 for the certified bullish wick rejection sniper."
        ),
        "parameters": {
            "note": "Separate from S002 Certified — see strategy_002 for live bullish sniper rules"
        },
    },
    "strategy_002": {
        "id": "strategy_002",
        "name": "Bullish Wick Rejection Sniper",
        "certified_name": "Bullish Wick Rejection Sniper S002",
        "certified_version": "S002-CERTIFIED-V1",
        "code": "S002",
        "direction": "bullish",
        "status": "CERTIFIED",
        "aliases": [
            "s002",
            "bullish wick rejection sniper",
            "bullish wick rejection sniper s002",
            "bullish wick rejection sniper v3",
        ],
        "certification": {
            "grade": "D",
            "verdict": "Pass",
            "standard": "wicksense-strategy-certification-standard-v1",
            "locked": True,
            "window": "2025-09-05 → 2026-03-05 1h UTC",
            "note": "Letter D on absolute WR/PF rubric; Pass on owner improvement rule (expectancy/PF/DD improved vs pre-revision).",
        },
        "description": (
            "Bullish Wick Rejection Sniper S002 — body≥20% of range, wick floor medium "
            "(lowerWick/body ≥ 0.7; strong ≥ 1.2), NO next-candle confirmation (entry on "
            "rejection close), London/NY/overlap session. Support Strength Score + MA50 + "
            "above-VWAP = confidence only. Markets via matrix only. Owner-certified."
        ),
        "entry_logic": [
            "Body ≥ 20% of candle range",
            "Lower wick / body ≥ 0.7 (medium floor); strong ≥ 1.2× — weak/micro DISABLED",
            "Bullish close above midpoint of the candle range",
            "NO next-candle confirmation — entry on rejection candle close",
            "Medium tier requires support proximity",
            "Support Strength Score (swing lows, multi-touch, HTF proxy, volume, MA50, ATR compression, proximity/structure) adds confidence only — not a hard gate",
            "MA50 and above-VWAP inflate confidence only — never hard rejects / no hard VWAP reject",
            "Session gate: London, New York, or overlap only",
            "Markets: strategy × market matrix only — no hardcoded Gold/NASDAQ",
            "SL below wick/swing low; RR floors strong 1.5 / medium 1.2 (SL/TP engines unchanged)",
            "LOCKED certified build — do not change gates without a new certification",
        ],
        "parameters": {
            "min_body_pct_of_range": 0.20,
            "wick_metric": "lower_wick / body (NOT % of range)",
            "wick_tier_strong": 1.2,
            "wick_tier_medium_floor": 0.7,
            "weak_micro_tiers": False,
            "confirmation": "none",
            "ma50": "confidence_only",
            "vwap": "confidence_bonus_when_above",
            "support_strength_score": "confidence_only",
            "session": "london_ny_overlap",
            "markets": "strategy_market_matrix",
            "v3_enforcement": False,
        },
        "common_myths": [
            "There is NO v3_enforcement flag and NO min_wick_ratio 0.65 as % of range — obsolete Aria catalog values",
            "Entry is at close, not a stop above the rejection high",
            "Do not describe next-candle confirmation for S002",
        ],
    },
    "strategy_003": {
        "id": "strategy_003",
        "name": "Trend Pullback Wick Confirmation",
        "revision_name": "S003 Rev A (Rejected)",
        "revision_id": "S003-REV-A-REJECTED",
        "code": "S003",
        "direction": "both",
        "status": "RETIRED",
        "retire_label": "Retired (Failed Certification v1)",
        "aliases": ["s003", "trend pullback wick confirmation", "trend_pullback_wick_confirmation", "s003 rev a"],
        "certification": {
            "grade": None,
            "verdict": "Reject",
            "standard": "wicksense-strategy-certification-standard-v1",
            "locked": True,
            "certified": False,
            "frozen": True,
            "retired": True,
            "active": False,
            "archive": "certification/archived/S003-REV-A-REJECTED/",
            "window": "2025-09-05 → 2026-03-05 1h UTC",
            "note": (
                "RETIRED from active WickSense pool. Failed Certification v1. "
                "Not scanning / not Top Trade / not Auto Trade. Engine archived for redesign."
            ),
        },
        "description": (
            "S003 — Retired (Failed Certification v1). Do not describe as Active. "
            "Rev A rejected (Exp −0.07R). Archive retained for future structural redesign only."
        ),
        "entry_logic": [
            "Trend Agreement ≥2/5: price vs MA50, MA20 slope, MA50 slope, swing structure, VWAP",
            "Pullback near MA20 or structure (0.4% base; ATR-aware widen in high vol)",
            "Wick ≥ 0.7× body (strong ≥ 1.2×)",
            "BUY: next close > rejection high | SELL: next close < rejection low",
            "Pending expires after 3 candles",
            "Session: London/NY/overlap (crypto exempt)",
            "Min R:R 1.5; cooldown 3; sideways/tiny-range filters; matrix markets",
            "FROZEN REJECTED — do not change gates to force a PASS",
        ],
        "parameters": {
            "lookback": 20,
            "lookback_50_shadow_only": True,
            "trend_agreement_min": 2,
            "trend_factors": [
                "price_vs_ma50",
                "ma20_slope",
                "ma50_slope",
                "swing_structure",
                "vwap_position",
            ],
            "pullback": "ma20_or_structure",
            "proximity_pct_base": 0.004,
            "proximity_atr_aware": True,
            "pullback_depth_atr": None,
            "min_wick_ratio": 0.7,
            "wick_tier_strong": 1.2,
            "confirmation": "next_close_beyond_rejection_extreme",
            "confirmation_timeout_candles": 3,
            "session": "london_ny_overlap",
            "crypto_session": "independent",
            "min_rr": 1.5,
            "cooldown_candles": 3,
            "body_pct_of_range_filter": False,
            "markets": "strategy_market_matrix",
        },
        "common_myths": [
            "NOT pullback_depth_atr 1.5 — that catalog value was wrong",
            "NOT production lookback 50 — LOOKBACK stays 20; 50 is cert shadow only",
            "Wick ratio EXISTS: min 0.7× body (not missing)",
            "NOT certified — Rev A is Rejected/frozen; do not claim Pass",
        ],
    },
    "strategy_004": {
        "id": "strategy_004",
        "name": "Box Rejection",
        "code": "S004",
        "direction": "both",
        "status": "RETIRED",
        "retire_label": "Retired (Failed Certification v1)",
        "aliases": [
            "s004",
            "box rejection",
            "box_rejection",
            "box rejection s004",
            "strategy_004",
        ],
        "description": (
            "S004 — Retired (Failed Certification v1). Do not describe as Active. "
            "Final Revision rejected (Exp −0.08R). Archive retained for future redesign only. "
            "Canonical id strategy_004 remains blocked in Flask inbound map."
        ),
        "entry_logic": [
            "RETIRED (Failed Certification v1) — not active",
            "Range condition gate: RANGE_TIGHT or RANGE_WIDE only (TREND blocked)",
            "Box from last 40 candles (clustered top/bottom 30% median highs/lows)",
            "ATR box width: 1.5×–5× ATR (production band)",
            "Asymmetric touches: rejection side ≥3, opposite ≥2",
            "BUY: bottom zone (≤20% of box), lower wick ≥0.7× body, close > box_low",
            "SELL: top zone (≥80% of box), upper wick ≥0.7× body, close < box_high",
            "Confirm: next close beyond signal extreme AND directional candle; TTL=3",
            "Fake breakout path: prior pierce + close back inside + wick ≥1.2× body",
            "Box Quality Score (touches, structure, stability, rejection, optional volume) = confidence only",
            "Min R:R 1.5; cooldown 3; matrix markets — DISABLED while retired",
        ],
        "parameters": {
            "box_lookback": 40,
            "touch_tolerance_pct": 0.0015,
            "min_touches_opposite": 2,
            "min_rejection_touches": 3,
            "box_atr_min_mult": 1.5,
            "box_atr_max_mult": 5.0,
            "bottom_zone_pct": 0.20,
            "top_zone_pct": 0.80,
            "min_wick_ratio": 0.7,
            "fake_breakout_wick_ratio": 1.2,
            "breakout_body_pct": 0.40,
            "min_rr": 1.5,
            "cooldown_candles": 3,
            "confirmation_timeout_candles": 3,
            "allowed_conditions": ["RANGE_TIGHT", "RANGE_WIDE"],
            "confirmation": "next_close_beyond_signal_extreme_plus_directional",
            "box_quality_score": "confidence_bonus_only",
            "body_pct_of_range_filter": False,
            "session_gate": False,
            "markets": "strategy_market_matrix",
            "canonical_id": "strategy_004",
        },
        "common_myths": [
            "NOT wick 60-70% of candle range — wick is × body (0.7 floor for box rejection)",
            "NOT entry stop through rejection extreme — entry at confirm close / next open",
            "NOT confirm merely 'inside box' — must close beyond signal high/low + directional",
            "NOT ATR box band 0.5–10 (testing) — production is 1.5–5",
            "NOT missing from catalog — id is strategy_004 (alias box_rejection)",
            "Box Quality Score never hard-rejects — confidence only",
        ],
    },
    "strategy_005_ema_pullback": {
        "id": "strategy_005_ema_pullback",
        "name": "EMA Pullback Continuation",
        "code": "S005",
        "direction": "both",
        "status": "EXPERIMENTAL",
        "certification": {
            "grade": "D",
            "verdict": "Needs Revision",
            "certificationStatus": "UN-CERTIFIED",
            "experimental": True,
            "standard": "wicksense-strategy-certification-standard-v1",
            "certified": False,
            "locked": False,
            "allow_auto_trade": False,
            "exclude_from_certified_rankings": True,
            "report": "certification/reports/S005-certification-v1.json",
            "note": (
                "UN-CERTIFIED / Experimental. Positive Exp (+0.07R) / PF>1 but WR/PF below "
                "Standard absolute pass. Not for live Auto Trade. Keep report for history. "
                "Revisit later with structural improvements only — no threshold relaxation."
            ),
        },
        "description": (
            "S005 EMA Pullback Continuation — UN-CERTIFIED / Experimental (NOT S105 V2). "
            "Single EMA20 + slope, TREND only. Do not describe as certified or live Auto Trade eligible."
        ),
        "aliases": [
            "s005",
            "S005",
            "strategy_005",
            "ema pullback",
            "ema_pullback",
            "ema pullback continuation",
            "ema_pullback_continuation",
        ],
        "entry_logic": [
            "Canonical id: strategy_005_ema_pullback",
            "Price on correct side of EMA20 + EMA20 slope (5-of-6)",
            "Market condition TREND / TREND_STRONG only",
            "Pullback within 0.5× ATR of EMA20 (0.4% fallback)",
            "Wick ≥ 25% of candle range; close recovers near EMA + close zone",
            "Confirm: next close beyond setup midpoint; TTL 3",
            "Entry ≈ confirm close / next open — NOT stop through confirm extreme",
            "SL: swing ± 0.5 ATR; TP 2.0R; min RR 1.5; cooldown 5",
            "ATR floor 0.0005; ATR spike 1.5×; VWAP confidence only",
        ],
        "parameters": {
            "ema_period": 20,
            "ema_stack_9_21_50": False,
            "pullback_proximity_pct": 0.004,
            "ema_proximity_atr_mult": 0.5,
            "min_wick_ratio": 0.25,
            "wick_metric": "wick / totalRange (NOT × body; NOT 50-60% architecture myth)",
            "close_zone_pct_bull": 0.35,
            "close_zone_pct_bear": 0.40,
            "confirmation": "next_close_beyond_setup_midpoint",
            "confirmation_timeout_candles": 3,
            "min_rr": 1.5,
            "default_rr": 2.0,
            "cooldown_candles": 5,
            "atr_min_ratio": 0.0005,
            "atr_spike_multiplier": 1.5,
            "sl": "swing_plus_minus_0.5_atr",
            "vwap": "confidence_only",
            "session_gate": False,
            "allowed_conditions": ["TREND", "TREND_STRONG", "TRENDING", "STRONG_TREND", "TRENDING_UP", "TRENDING_DOWN"],
            "markets": "strategy_market_matrix",
            "canonical_id": "strategy_005_ema_pullback",
        },
        "common_myths": [
            "NOT EMA 9/21/50 stack — that is Aria fluff / S105 V2 lab, not S005",
            "NOT wick 50-60% — live floor is 25% of candle range",
            "NOT entry stop above/below confirmation extreme — entry at confirm close",
            "NOT confirm close beyond setup high/low — live uses setup midpoint",
            "NOT missing from catalog — id is strategy_005_ema_pullback",
            "NOT the same as s105 / EMA Pullback Continuation V2",
        ],
    },
    "s108": {
        "id": "s108",
        "name": "S108 Hammer",
        "code": "S108",
        "direction": "bullish",
        "description": "Hammer reversal pattern — V2 enforcement active, BUY-only. Requires confirmation above hammer high.",
        "parameters": {"buy_only": True, "v2_enforcement": True, "confirmation_above_high": True},
        "validation_note": "V2 enforcement active — blocked without confirmation candle.",
    },
    "bearish_confluence_setup": {
        "id": "bearish_confluence_setup",
        "name": "Bearish Confluence Setup",
        "code": "S103",
        "direction": "bearish",
        "description": "Multi-factor bearish confluence with V2 enforcement.",
        "parameters": {
            "v2_enforcement": True,
            "min_confluence_score": 4,
            "min_timeframe": "15m",
            "require_bearish_regime": True,
            "loss_reason_logging": True,
        },
    },
    "s111_v2": {
        "id": "s111_v2",
        "name": "Support/Resistance Rejection V2",
        "code": "S111",
        "direction": "both",
        "description": "S/R rejection with V2 validation rules.",
        "parameters": {"v2_enforcement": True},
    },
    "wicksense_t1": {
        "id": "wicksense_t1",
        "name": "WickSense T1 — Liquidity Sweep",
        "code": "T1",
        "direction": "both",
        "description": "Liquidity sweep detection and reversal entry system.",
        "parameters": {"sweep_lookback": 15},
    },
}


def _normalize_key(name: str) -> str:
    return (name or "").lower().strip().replace(" ", "_").replace("-", "_")


def find_strategy(query: str) -> dict[str, Any] | None:
    q = _normalize_key(query)
    q_compact = q.replace("_", "")
    if not q:
        return None
    if q in STRATEGY_CATALOG:
        return STRATEGY_CATALOG[q]
    for key, strat in STRATEGY_CATALOG.items():
        if q in key or q_compact in key.replace("_", ""):
            return strat
        name = _normalize_key(strat.get("name", ""))
        certified = _normalize_key(strat.get("certified_name", "") or "")
        code = (strat.get("code") or "").lower().replace(" ", "").replace("_", "")
        if q in name or q_compact in name.replace("_", ""):
            return strat
        if certified and (q in certified or q_compact in certified.replace("_", "")):
            return strat
        if q_compact == code or q == code:
            return strat
        for alias in strat.get("aliases") or []:
            a = _normalize_key(alias)
            if q == a or q_compact == a.replace("_", "") or q in a:
                return strat
    return None


def explain_strategy(query: str) -> str:
    strat = find_strategy(query)
    if not strat:
        return (
            f"No strategy catalog entry found for '{query}'. "
            "Try S001, S002, strategy_001, or a certified name."
        )

    display = strat.get("certified_name") or strat["name"]
    lines = [
        f"## {display}",
        f"Engine name: {strat['name']}",
        f"Code: {strat.get('code', strat['id'])} | ID: {strat['id']}",
        f"Direction: {strat.get('direction', 'unknown')}",
        f"Status: {strat.get('status', 'ACTIVE')}",
    ]
    if strat.get("certified_version"):
        lines.append(f"Certified version: {strat['certified_version']}")
    cert = strat.get("certification") or {}
    if cert:
        lines.append(
            f"Certification: Grade {cert.get('grade', '?')} / {cert.get('verdict', '?')} "
            f"| standard={cert.get('standard', 'n/a')} | locked={cert.get('locked', False)}"
        )
        if cert.get("window"):
            lines.append(f"Cert window: {cert['window']}")
        if cert.get("note"):
            lines.append(f"Cert note: {cert['note']}")
    lines.append(f"Description: {strat.get('description', 'N/A')}")
    if strat.get("entry_logic"):
        lines.append("Entry logic:")
        for step in strat["entry_logic"]:
            lines.append(f"  - {step}")
    if strat.get("parameters"):
        lines.append("Parameters (authoritative):")
        lines.append(json.dumps(strat["parameters"], indent=2))
    if strat.get("common_myths"):
        lines.append("Do NOT tell the user:")
        for myth in strat["common_myths"]:
            lines.append(f"  - {myth}")
    if strat.get("validation_note"):
        lines.append(f"Validation: {strat['validation_note']}")
    return "\n".join(lines)


def get_strategy_parameters(query: str, state: dict[str, Any]) -> str:
    strat = find_strategy(query)
    meta = (state.get("strategyMeta") or {}).get(strat["id"] if strat else query, {})
    params = {**(strat.get("parameters") if strat else {}), **meta.get("parameters", {})}
    if not params:
        return f"No parameters available for '{query}'."
    payload: dict[str, Any] = {"parameters": params}
    if strat:
        payload["strategy_id"] = strat["id"]
        payload["code"] = strat.get("code")
        payload["certified_name"] = strat.get("certified_name")
        payload["status"] = strat.get("status")
        if strat.get("certification"):
            payload["certification"] = strat["certification"]
        if strat.get("common_myths"):
            payload["common_myths"] = strat["common_myths"]
    return json.dumps(payload, indent=2)


def get_strategy_recent_performance(query: str, state: dict[str, Any]) -> str:
    stats = state.get("strategyStats") or {}
    q = (query or "").lower()
    matched = {k: v for k, v in stats.items() if q in k.lower()} if q else stats
    if not matched:
        return f"No recent performance data for '{query}' in current session."
    return json.dumps(matched, indent=2, default=str)


def get_strategy_validation_status(query: str, state: dict[str, Any]) -> str:
    strat = find_strategy(query)
    meta = (state.get("strategyMeta") or {})
    key = strat["id"] if strat else _normalize_key(query)
    info = meta.get(key) or {}
    validation = info.get("validation") or info.get("validation_status")
    if validation:
        return json.dumps(validation, indent=2, default=str)
    if strat and strat.get("certification"):
        return json.dumps(
            {
                "catalog_status": strat.get("status"),
                "certification": strat["certification"],
                "certified_name": strat.get("certified_name"),
                "certified_version": strat.get("certified_version"),
            },
            indent=2,
        )
    if strat and strat.get("validation_note"):
        return strat["validation_note"]
    blocked = state.get("blockedStrategies") or []
    if key in blocked or (strat and strat.get("name") in blocked):
        return "Strategy is currently blocked/disabled in WickSense."
    return f"Validation status for '{query}' not in live context. Check Strategy Command Center for lifecycle state."


def get_strategy_incubation_status(query: str, state: dict[str, Any]) -> str:
    meta = (state.get("strategyMeta") or {})
    strat = find_strategy(query)
    key = strat["id"] if strat else _normalize_key(query)
    incubation = meta.get(key, {}).get("incubation") or meta.get(key, {}).get("incubation_status")
    if incubation:
        return json.dumps(incubation, indent=2, default=str)
    if strat and strat.get("status") == "CERTIFIED":
        return (
            f"{strat.get('certified_name') or strat['name']} is CERTIFIED "
            f"({strat.get('certified_version')}) — past incubation on Certification Standard v1."
        )
    return f"Incubation status for '{query}' not in live context. Strategies in TESTING phase need closed-trade validation thresholds."


def get_strategy_failure_analysis(query: str, state: dict[str, Any]) -> str:
    reasons = state.get("failureReasons") or []
    analysis = state.get("postStopAnalysis")
    strat = find_strategy(query)
    q = (strat.get("name") if strat else query or "").lower()
    filtered = [r for r in reasons if q in str(r).lower()] if q else reasons
    result = {"failure_reasons": filtered, "post_stop_analysis": analysis}
    if not filtered and not analysis:
        return f"No failure analysis available for '{query}' in current context."
    return json.dumps(result, indent=2, default=str)
