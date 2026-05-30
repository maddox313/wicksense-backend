from flask import Flask, jsonify, request
from flask_cors import CORS
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

import pandas as pd
import os
import requests
import json
import uuid
from datetime import datetime
import stripe
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import threading
import time
import random
try:
    import websocket
except ImportError:
    websocket = None


stripe.api_key = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

PRESETS_FILE = "presets.json"
SIGNAL_HISTORY_FILE = "signal_history.json"
TRADEPLAN_HISTORY_FILE = "tradeplan_history.json"
SCAN_HISTORY_FILE = "scan_history.json"
TRADE_JOURNAL_FILE = "trade_journal.json"
ALERT_RULES_FILE = "alert_rules.json"
ALERT_LOG_FILE = "alert_log.json"
NOTIFICATION_FILE = "notifications.json"
RISK_SETTINGS_FILE = "risk_settings.json"

MARKET_SYMBOLS = {
    "FOREX": "EUR/USD",
    "GOLD": "XAU/USD",

    # 🔥 CRITICAL FIX (THIS IS THE BIG ONE)
    "NATURALGAS": "NG",

    "NASDAQ": "NDX",
    "DOWJONES": "DIA",

    # Optional (keep if you want futures)
    "FUTURES": "ES"
}


INTERVAL_MAP = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "45m": "45min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "8h": "8h",
    "1d": "1day",
    "1w": "1week"
}


LIVE_SCAN_CACHE = {
    "last_updated": None,
    "status": "idle",
    "results": None
}

LIVE_MARKET_STATE = {
    "market_count": 0,
    "markets": {
        "NASDAQ": {},
        "Gold": {},
        "Forex": {},
        "NaturalGas": {},
        "DowJones": {},
        "Futures": {}
    }
}


# -----------------------------
# TRADE RANKING SYSTEM
# -----------------------------
TRADE_RANKINGS = {
    "all_ranked": [],
    "top_trade": None,
    "next_best": [],
    "last_updated": None
}


STREAM_STATUS = {
    "status": "disconnected",
    "provider": None,
    "last_tick": None
}

LIVE_TOP_TRADE_STATE = {
    "market": None,
    "signal": None,
    "setup_type": None,
    "confidence": 0
}

LIVE_NOTIFICATION_COOLDOWNS = {}
LIVE_ENGINE_STARTED = False
LIVE_ENGINE_LOCK = threading.Lock()

POLLING_INTERVAL = 7
WS_RECONNECT_INTERVAL = 30

POLLING_ACTIVE = False
WS_ACTIVE = False
POLLING_THREAD_STARTED = False


# -----------------------------
# BASIC ROUTES
# -----------------------------
@app.route("/")
def home():
    ensure_live_engine_started()
    return jsonify({"status": "ok"})



@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "alive"}), 200

@app.route("/markets")
def markets():
    return jsonify([
        "Futures",
        "NASDAQ",
        "DowJones",
        "Gold",
        "NaturalGas",
        "Forex"
    ])

from flask import request, jsonify
import time

@app.route("/resolve-outcomes", methods=["POST"])
def resolve_outcomes():
    data = request.get_json(silent=True) or {}
    signals = data.get("signals", [])

    results = []

    for signal in signals:
        try:
            print("SIGNAL RECEIVED:", signal)

            # -----------------------------
            # EXTRACT SIGNAL DATA
            # -----------------------------
            market = signal.get("market")

            entry = signal.get("entry")

            # 🔥 FIXED: Accept ALL possible stop loss keys
            sl = (
                signal.get("stop_loss") or
                signal.get("sl") or
                signal.get("stop")
            )

            # 🔥 FIXED: Accept ALL possible take profit keys
            tp = (
                signal.get("take_profit") or
                signal.get("tp") or
                signal.get("target")
            )

            direction = signal.get("direction") or signal.get("signal")
            created_at = signal.get("created_at")

            # -----------------------------
            # VALIDATION
            # -----------------------------
            if not market:
                results.append({
                    "id": signal.get("id"),
                    "status": "error",
                    "error": "Missing market"
                })
                continue

            if entry is None:
                results.append({
                    "id": signal.get("id"),
                    "status": "error",
                    "error": "Missing entry"
                })
                continue

            if sl is None:
                results.append({
                    "id": signal.get("id"),
                    "status": "error",
                    "error": "Missing stop_loss"
                })
                continue

            if tp is None:
                results.append({
                    "id": signal.get("id"),
                    "status": "error",
                    "error": "Missing take_profit"
                })
                continue

            if not direction:
                results.append({
                    "id": signal.get("id"),
                    "status": "error",
                    "error": "Missing direction"
                })
                continue

            # -----------------------------
            # TYPE CONVERSION
            # -----------------------------
            entry = float(entry)
            sl = float(sl)
            tp = float(tp)
            direction = str(direction).upper()

            # -----------------------------
            # FETCH MARKET DATA
            # -----------------------------
            df = fetch_live_market_data(
                market,
                interval="1min",
                outputsize=500
            )

            if df is None or df.empty:
                results.append({
                    "id": signal.get("id"),
                    "status": "error",
                    "error": "No market data returned"
                })
                continue

            # -----------------------------
            # OUTCOME LOGIC
            # -----------------------------
            outcome = "expired"
            exit_reason = "timeout"
            exit_price = None
            pnl = 0
            last_close = None

            for _, row in df.iterrows():
                high = float(row["High"])
                low = float(row["Low"])
                close = float(row["Close"])

                last_close = close

                if direction in ["BUY", "BULLISH"]:
                    if high >= tp:
                        outcome = "win"
                        exit_reason = "tp_hit"
                        exit_price = tp
                        break

                    if low <= sl:
                        outcome = "loss"
                        exit_reason = "sl_hit"
                        exit_price = sl
                        break

                elif direction in ["SELL", "BEARISH"]:
                    if low <= tp:
                        outcome = "win"
                        exit_reason = "tp_hit"
                        exit_price = tp
                        break

                    if high >= sl:
                        outcome = "loss"
                        exit_reason = "sl_hit"
                        exit_price = sl
                        break

            # -----------------------------
            # FINALIZE EXIT
            # -----------------------------
            if exit_price is None and last_close is not None:
                exit_price = last_close

            if exit_price is not None:
                if direction in ["BUY", "BULLISH"]:
                    pnl = exit_price - entry
                else:
                    pnl = entry - exit_price

            results.append({
                "id": signal.get("id"),
                "status": "resolved",
                "outcome": outcome,
                "exit_reason": exit_reason,
                "exit_price": exit_price,
                "pnl_pts": pnl
            })

            # 🔥 Prevent rate limiting
            time.sleep(0.2)

        except Exception as e:
            results.append({
                "id": signal.get("id") if isinstance(signal, dict) else None,
                "status": "error",
                "error": str(e)
            })

    return jsonify({
        "status": "success",
        "processed": len(results),
        "resolved": len([r for r in results if r.get("status") == "resolved"]),
        "errors": len([r for r in results if r.get("status") == "error"]),
        "results": results
    })


@app.route("/run-outcome-engine", methods=["POST"])
def run_outcome_engine():
    try:
        print("🔥 Outcome Engine Triggered")

        # For now just return success (we will connect it next)
        return jsonify({
            "status": "success",
            "message": "Outcome Engine trigger endpoint working"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# -----------------------------
# OPENAPI
# -----------------------------
@app.route("/openapi.json")
def openapi():
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "WickSense API",
            "version": "3.0.0"
        },
        "servers": [
            {
                "url": "https://wicksense-backend.onrender.com"
            }
        ],
        "paths": {
            "/markets": {
                "get": {
                    "summary": "Get supported markets",
                    "responses": {
                        "200": {
                            "description": "List of markets"
                        }
                    }
                }
            },
            "/signal": {
                "post": {
                    "summary": "Generate a signal",
                    "responses": {
                        "200": {
                            "description": "Signal result"
                        }
                    }
                }
            },
            "/": {
                "post": {
                    "summary": "Run a ",
                    "responses": {
                        "200": {
                            "description": " results"
                        }
                    }
                }
            },
            "/tradeplan": {
                "post": {
                    "summary": "Generate a trade plan",
                    "responses": {
                        "200": {
                            "description": "Trade plan result"
                        }
                    }
                }
            },
            "/live-scan": {
                "get": {
                    "summary": "Get latest cached market scan results",
                    "responses": {
                        "200": {
                            "description": "Cached market scan results with status and last updated timestamp"
                        }
                    }
                }
            },
            "/refresh-live-scan": {
                "post": {
                    "summary": "Force refresh the market scanner cache",
                    "responses": {
                        "200": {
                            "description": "Live scan refreshed and cache updated"
                        }
                    }
                }
            },
            "/scanner-status": {
                "get": {
                    "summary": "Get current scanner status and cache state",
                    "responses": {
                        "200": {
                            "description": "Scanner status including last update time and cache availability"
                        }
                    }
                }
            },
            "/market-intelligence": {
                "get": {
                    "summary": "Get AI market intelligence summary",
                    "responses": {
                        "200": {
                            "description": "Market intelligence summary including bias, conviction, and strongest opportunity"
                        }
                    }
                }
            },
            "/market-script": {
                "get": {
                    "summary": "Get AI-generated market content script",
                    "responses": {
                        "200": {
                            "description": "AI-generated market scripts for YouTube, shorts, and voiceover"
                        }
                    }
                }
            },
            "/signal-history": {
                "get": {
                    "summary": "Get recent signal history",
                    "responses": {
                        "200": {
                            "description": "Recent saved signal results"
                        }
                    }
                }
            },
            "/tradeplan-history": {
                "get": {
                    "summary": "Get recent trade plan history",
                    "responses": {
                        "200": {
                            "description": "Recent saved trade plan results"
                        }
                    }
                }
            },
            "/scan-history": {
                "get": {
                    "summary": "Get recent scanner history",
                    "responses": {
                        "200": {
                            "description": "Recent saved live scanner snapshots"
                        }
                    }
                }
            },
            "/trade-journal": {
                "get": {
                    "summary": "Get trade journal entries",
                    "responses": {
                        "200": {
                            "description": "List of trade journal entries"
                        }
                    }
                },
                "post": {
                    "summary": "Create a trade journal entry",
                    "responses": {
                        "200": {
                            "description": "Trade journal entry created"
                        }
                    }
                }
            },
            "/trade-journal/{entry_id}": {
                "put": {
                    "summary": "Update a trade journal entry",
                    "responses": {
                        "200": {
                            "description": "Trade journal entry updated"
                        }
                    }
                },
                "delete": {
                    "summary": "Delete a trade journal entry",
                    "responses": {
                        "200": {
                            "description": "Trade journal entry deleted"
                        }
                    }
                }
            },
            "/journal-analytics": {
                "get": {
                    "summary": "Get performance analytics from the trade journal",
                    "responses": {
                        "200": {
                            "description": "Trade journal analytics including win rate, pnl, and grouped performance breakdowns"
                        }
                    }
                }
            },
            "/journal-review": {
                "get": {
                    "summary": "Get AI coaching review based on trade journal analytics",
                    "responses": {
                        "200": {
                            "description": "AI-style journal review including strengths, weaknesses, emotional patterns, and coaching advice"
                        }
                    }
                }
            },
            "/alert-rules": {
                "get": {
                    "summary": "Get alert rules",
                    "responses": {
                        "200": {
                            "description": "List of alert rules"
                        }
                    }
                },
                "post": {
                    "summary": "Create an alert rule",
                    "responses": {
                        "200": {
                            "description": "Alert rule created"
                        }
                    }
                }
            },
            "/alert-rules/{rule_id}": {
                "put": {
                    "summary": "Update an alert rule",
                    "responses": {
                        "200": {
                            "description": "Alert rule updated"
                        }
                    }
                },
                "delete": {
                    "summary": "Delete an alert rule",
                    "responses": {
                        "200": {
                            "description": "Alert rule deleted"
                        }
                    }
                }
            },
            "/notifications": {
                "get": {
                    "summary": "Get user notifications",
                    "responses": {
                        "200": {
                            "description": "List of notifications"
                        }
                    }
                }
            },
            "/notifications/{notification_id}/read": {
                "put": {
                    "summary": "Mark notification as read",
                    "responses": {
                        "200": {
                            "description": "Notification updated"
                        }
                    }
                }
            },
            "/notifications/{notification_id}": {
                "delete": {
                    "summary": "Delete notification",
                    "responses": {
                        "200": {
                            "description": "Notification deleted"
                        }
                    }
                }
            },
            "/risk-settings": {
                "get": {
                    "summary": "Get account-level risk settings",
                    "responses": {
                        "200": {
                            "description": "Current risk settings"
                        }
                    }
                },
                "put": {
                    "summary": "Update account-level risk settings",
                    "responses": {
                        "200": {
                            "description": "Updated risk settings"
                        }
                    }
                }
            },
            "/daily-loss-status": {
                "get": {
                    "summary": "Get current daily loss guardrail status",
                    "responses": {
                        "200": {
                            "description": "Daily realized pnl, remaining loss capacity, and blocked status"
                        }
                    }
                }
            },
            "/scan-markets": {
                "get": {
                    "summary": "Scan all markets",
                    "responses": {
                        "200": {
                            "description": "Market scan results"
                        }
                    }
                }
            },
            "/presets": {
                "get": {
                    "summary": "Get all presets",
                    "responses": {
                        "200": {
                            "description": "Preset list"
                        }
                    }
                },
                "post": {
                    "summary": "Create a preset",
                    "responses": {
                        "200": {
                            "description": "Preset created"
                        }
                    }
                }
            },
            "/presets/{id}": {
                "put": {
                    "summary": "Update a preset",
                    "responses": {
                        "200": {
                            "description": "Preset updated"
                        }
                    }
                },
                "delete": {
                    "summary": "Delete a preset",
                    "responses": {
                        "200": {
                            "description": "Preset deleted"
                        }
                    }
                }
            },
            "/presets/{id}/duplicate": {
                "post": {
                    "summary": "Duplicate a preset",
                    "responses": {
                        "200": {
                            "description": "Preset duplicated"
                        }
                    }
                }
            },
            "/create-checkout-session": {
                "post": {
                    "summary": "Create a Stripe checkout session",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "price_id": {"type": "string"},
                                        "user_id": {"type": "string"},
                                        "plan": {"type": "string"},
                                        "success_url": {"type": "string"},
                                        "cancel_url": {"type": "string"}
                                    },
                                    "required": ["price_id", "user_id", "success_url", "cancel_url"]
                                }
                            },
                            "application/x-www-form-urlencoded": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "price_id": {"type": "string"},
                                        "user_id": {"type": "string"},
                                        "plan": {"type": "string"},
                                        "success_url": {"type": "string"},
                                        "cancel_url": {"type": "string"}
                                    },
                                    "required": ["price_id", "user_id", "success_url", "cancel_url"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Stripe checkout session created",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        }
                    }
                }
            }
        }
    }


# -----------------------------
# HELPERS
# -----------------------------
def get_request_body():
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict()


def get_market_from_request():
    try:
        # 1. Try JSON body (POST)
        if request.is_json:
            data = request.get_json()
            if data and "market" in data:
                return data.get("market")

        # 2. Try query params (GET)
        market = request.args.get("market")
        if market:
            return market

        # 3. Try form data (fallback)
        return request.form.get("market")

    except Exception as e:
        print(f"❌ get_market_from_request error: {e}", flush=True)
        return None


def normalize_interval(interval: str) -> str:
    interval_map = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "45m": "45min",
        "1h": "1h",
        "2h": "2h",
        "4h": "4h",
        "8h": "8h",
        "1d": "1day",
        "1w": "1week",
        "1mo": "1month",
        "1day": "1day",
        "1week": "1week",
        "1month": "1month"
    }
    return interval_map.get(interval, interval)


def get_current_utc_hour():
    return datetime.utcnow().hour


def get_market_session():
    hour = get_current_utc_hour()

    tokyo = 0 <= hour < 9
    london = 7 <= hour < 16
    nyse = 13 <= hour < 22
    sydney = hour >= 21 or hour < 6

    active_sessions = []

    if tokyo:
        active_sessions.append("Tokyo")
    if london:
        active_sessions.append("London")
    if nyse:
        active_sessions.append("NYSE")
    if sydney:
        active_sessions.append("Sydney")

    if london and nyse:
        session_label = "London/NYSE Overlap"
    elif tokyo and london:
        session_label = "Tokyo/London Overlap"
    elif sydney and tokyo:
        session_label = "Sydney/Tokyo Overlap"
    elif active_sessions:
        session_label = active_sessions[0]
    else:
        session_label = "Closed / Low Liquidity"

    if "Overlap" in session_label:
        liquidity_profile = "High"
    elif session_label in ["London", "NYSE", "Tokyo"]:
        liquidity_profile = "Moderate"
    elif session_label == "Sydney":
        liquidity_profile = "Low to Moderate"
    else:
        liquidity_profile = "Low"

    return {
        "session_label": session_label,
        "active_sessions": active_sessions,
        "liquidity_profile": liquidity_profile,
        "utc_hour": hour
    }

def get_session_score():
    session_data = get_market_session()
    session_label = session_data.get("session_label", "")

    if session_label == "London/NYSE Overlap":
        return 15
    elif session_label in ["NYSE", "London"]:
        return 10
    elif session_label in ["Tokyo", "Sydney/Tokyo Overlap", "Tokyo/London Overlap"]:
        return 6
    elif session_label == "Sydney":
        return 3
    else:
        return -5


def get_float_from_request(key, default_value):
    body = get_request_body()
    value = body.get(key, default_value)
    try:
        return float(value)
    except Exception:
        return float(default_value)


def safe_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default

def update_live_candle(market, price):
    global LIVE_MARKET_STATE

    # Ensure markets structure exists
    if "markets" not in LIVE_MARKET_STATE:
        return

    markets = LIVE_MARKET_STATE["markets"]

    # Ensure this specific market exists
    if market not in markets:
        return

    state = markets.get(market, {})
    now = datetime.utcnow()
    minute_key = now.strftime("%Y-%m-%d %H:%M")

    current_candle = state.get("current_candle")

    if not current_candle or current_candle.get("minute") != minute_key:
        if current_candle:
            completed = state.get("completed_candles", [])
            completed.append(current_candle)
            state["completed_candles"] = completed[-50:]

        current_candle = {
            "minute": minute_key,
            "Open": float(price),
            "High": float(price),
            "Low": float(price),
            "Close": float(price)
        }
    else:
        current_candle["High"] = max(float(current_candle["High"]), float(price))
        current_candle["Low"] = min(float(current_candle["Low"]), float(price))
        current_candle["Close"] = float(price)

    state["current_candle"] = current_candle
    state["last_updated"] = now.isoformat() + "Z"

    # 🔥 CRITICAL FIX: write back into markets layer
    LIVE_MARKET_STATE["markets"][market] = state


def calculate_live_wicks(candle):
    open_price = safe_float(candle.get("Open"))
    high_price = safe_float(candle.get("High"))
    low_price = safe_float(candle.get("Low"))
    close_price = safe_float(candle.get("Close"))

    upper_wick = high_price - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low_price

    return {
        "upper_wick": round(upper_wick, 4),
        "lower_wick": round(lower_wick, 4)
    }

def has_live_signal_changed(previous_state, new_payload):
    if not previous_state:
        return False

    previous_signal = previous_state.get("signal")
    new_signal = new_payload.get("signal")

    previous_setup = previous_state.get("setup_type")
    new_setup = new_payload.get("setup_type")

    previous_breakout = previous_state.get("breakout")
    new_breakout = new_payload.get("breakout")

    previous_liquidity = previous_state.get("liquidity_event")
    new_liquidity = new_payload.get("liquidity_event")

    previous_confidence = safe_float(previous_state.get("confidence"), 0.0)
    new_confidence = safe_float(new_payload.get("confidence"), 0.0)

    if previous_signal != new_signal:
        return True

    if previous_setup != new_setup:
        return True

    if previous_breakout != new_breakout and new_breakout is not None:
        return True

    if previous_liquidity != new_liquidity and new_liquidity is not None:
        return True

    if abs(new_confidence - previous_confidence) >= 10:
        return True

    return False


def handle_live_signal_change(market, previous_state, new_payload):
    title = f"Live signal update: {market}"
    signal = new_payload.get("signal", "Unknown")
    setup_type = new_payload.get("setup_type", "Unknown setup")
    confidence = new_payload.get("confidence", 0)

    if previous_state.get("signal") != new_payload.get("signal"):
        title = f"{market} signal changed to {signal}"
    elif previous_state.get("setup_type") != new_payload.get("setup_type"):
        title = f"{market} setup changed to {setup_type}"
    elif previous_state.get("breakout") != new_payload.get("breakout") and new_payload.get("breakout"):
        title = f"{market} breakout detected"
    elif previous_state.get("liquidity_event") != new_payload.get("liquidity_event") and new_payload.get("liquidity_event"):
        title = f"{market} liquidity event detected"
    elif abs(
        safe_float(new_payload.get("confidence"), 0.0) -
        safe_float(previous_state.get("confidence"), 0.0)
    ) >= 10:
        title = f"{market} confidence changed to {confidence}%"

    cooldown_key = f"signal:{market}"

    if can_send_live_notification(cooldown_key, 60):
        create_notification({
            "type": "live_signal_change",
            "title": title,
            "market": market,
            "signal": signal,
            "setup_type": setup_type,
            "confidence": confidence,
            "breakout": new_payload.get("breakout"),
            "liquidity_event": new_payload.get("liquidity_event"),
            "trendline": new_payload.get("trendline")
        })

def get_current_live_top_trade(target_market=None):
    best_trade = None
    best_score = -999

    # Support both possible LIVE_MARKET_STATE shapes
    if isinstance(LIVE_MARKET_STATE.get("markets"), dict):
        live_markets = LIVE_MARKET_STATE.get("markets", {})
    else:
        live_markets = LIVE_MARKET_STATE

    normalized_target_market = None
    if target_market:
        normalized_target_market = str(target_market).strip().upper()

    print("LIVE TOP TRADE TARGET:", normalized_target_market)
    print("LIVE MARKET STATE KEYS:", list(live_markets.keys()))

    for market_name, data in live_markets.items():
        if not isinstance(data, dict):
            continue

        normalized_market_name = str(market_name).strip().upper()

        if normalized_target_market and normalized_market_name != normalized_target_market:
            print("TOP TRADE SKIP MARKET:", market_name, "TARGET:", normalized_target_market)
            continue

        signal_raw = str(data.get("signal", "")).strip().upper()
        if not signal_raw:
            signal_raw = "BUY"

        confidence = safe_float(data.get("confidence"), 0.0)
        entry_timing = str(data.get("entry_timing", "")).strip().upper()
        readiness = safe_float(data.get("trade_readiness_score"), 0.0)

        if signal_raw in ["BULLISH", "BUY"]:
            normalized_signal = "BUY"
        elif signal_raw in ["BEARISH", "SELL"]:
            normalized_signal = "SELL"
        else:
            print("TOP TRADE SKIP BAD SIGNAL:", market_name, signal_raw)
            continue

        score = compute_trade_score(data)
        score += readiness * 0.2

        print(
            "TOP TRADE CHECK:",
            market_name,
            normalized_signal,
            confidence,
            entry_timing,
            readiness,
            score,
            "TARGET:",
            normalized_target_market
        )

        if score > best_score:
            best_score = score
            candle = data.get("current_candle", {}) if isinstance(data.get("current_candle"), dict) else {}

            best_trade = {
                "market": market_name,
                "last_updated": data.get("last_updated"),
                "open": candle.get("Open", data.get("open")),
                "high": candle.get("High", data.get("high")),
                "low": candle.get("Low", data.get("low")),
                "close": candle.get("Close", data.get("close")),
                "upper_wick": data.get("upper_wick"),
                "lower_wick": data.get("lower_wick"),
                "signal": normalized_signal,
                "confidence": confidence,
                "pattern": data.get("pattern"),
                "breakout": data.get("breakout"),
                "liquidity_event": data.get("liquidity_event"),
                "trendline": data.get("trendline"),
                "setup_type": data.get("setup_type"),
                "ai_summary": data.get("ai_summary"),
                "trade_thesis": data.get("trade_thesis"),
                "risk_note": data.get("risk_note"),
                "strategy_recommendation": data.get("strategy_recommendation"),
                "strategy_reason": data.get("strategy_reason"),
                "suggested_action": data.get("suggested_action"),
                "support_levels": data.get("support_levels"),
                "resistance_levels": data.get("resistance_levels"),
                "trendline_points": data.get("trendline_points"),
                "breakout_zone": data.get("breakout_zone"),
                "entry_zone": data.get("entry_zone"),
                "strategy_visual_bias": data.get("strategy_visual_bias"),
                "entry_timing": data.get("entry_timing"),
                "confirmation_state": data.get("confirmation_state"),
                "trade_readiness_score": readiness,
                "execution_guidance": data.get("execution_guidance"),
                "session_label": data.get("session_label"),
                "active_sessions": data.get("active_sessions"),
                "liquidity_profile": data.get("liquidity_profile"),
                "utc_hour": data.get("utc_hour"),
                "trade_quality_score": round(score, 2)
            }

    print("FINAL LIVE TOP TRADE:", best_trade)
    return best_trade

# ============================
# CHART SYMBOL MAPPING
# ============================
def get_chart_symbol(market):
    chart_map = {
        "NASDAQ": "OANDA:NAS100USD",
        "Gold": "OANDA:XAUUSD",
        "Forex": "OANDA:EURUSD",
        "NaturalGas": "TVC:NATGAS",
        "DowJones": "OANDA:US30USD",
        "Futures": "CME_MINI:ES1!"
    }
    return chart_map.get(market, "")

# =========================================================
# LIVE BEST TRADES LOGIC (FIXED + STABLE)
# =========================================================

def get_live_best_trades_logic():
    try:
        live_markets = LIVE_MARKET_STATE.get("markets", {})

        ranked = []

        if not isinstance(live_markets, dict):
            return {
                "top_trade": None,
                "next_best": [],
                "all_ranked": [],
                "count": 0
            }

        for market_name, data in live_markets.items():
            try:
                if not isinstance(data, dict):
                    continue

                # --- SAFE SIGNAL EXTRACTION ---
                signal = str(data.get("signal", "")).upper()

                if not signal:
                    continue

                # --- SCORES ---
                confidence = float(data.get("confidence", 0) or 0)
                readiness = float(get_trade_readiness(data))
                quality = float(data.get("trade_quality_score", 0) or 0)

                # --- FINAL SCORE ---
                total_score = round(
                    (confidence * 0.4) +
                    (readiness * 0.3) +
                    (quality * 0.3),
                    2
                )

                enriched = dict(data)

                # ✅ FORCE THESE FIELDS TO EXIST (THIS FIXES YOUR ISSUE)
                enriched["market"] = market_name
                enriched["confidence"] = confidence
                enriched["trade_readiness_score"] = readiness
                enriched["trade_quality_score"] = quality
                enriched["top_trade_score"] = total_score

                # --- NORMALIZE SIGNAL ---
                if signal in ["BULLISH", "BUY"]:
                    enriched["signal"] = "BUY"
                elif signal in ["BEARISH", "SELL"]:
                    enriched["signal"] = "SELL"
                else:
                    enriched["signal"] = "NEUTRAL"

                ranked.append(enriched)

            except Exception as e:
                print(f"Ranking error for {market_name}: {e}", flush=True)

        # --- SORT BEST TO WORST ---
        ranked.sort(key=lambda x: x.get("top_trade_score", 0), reverse=True)

        return {
            "top_trade": ranked[0] if ranked else None,
            "next_best": ranked[1:3] if len(ranked) > 1 else [],
            "all_ranked": ranked,
            "count": len(ranked)
        }

    except Exception as e:
        print(f"CRITICAL ranking error: {e}", flush=True)
        return {
            "top_trade": None,
            "next_best": [],
            "all_ranked": [],
            "count": 0
        }


# =========================================================
# LIVE BEST TRADES ROUTE
# =========================================================

@app.route('/live-best-trades', methods=['GET'])
def live_best_trades():
    try:
        return jsonify(get_live_best_trades_logic())
    except Exception as e:
        return jsonify({
            "error": "Failed to load live best trades",
            "details": str(e)
        }), 500


# =========================================================
# LIVE TOP TRADE ROUTE
# =========================================================

@app.route('/live-top-trade', methods=['GET'])
def live_top_trade():
    try:
        market = request.args.get("market")
        top_trade = get_current_live_top_trade(market)

        if not top_trade:
            return jsonify({})

        return jsonify(top_trade)

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500

def get_current_setup_forming_trade():
    best_trade = None
    best_score = -1

    for market_name, data in LIVE_MARKET_STATE.items():
        signal = data.get("signal")
        confidence = safe_float(data.get("confidence"), 0.0)
        readiness = safe_float(data.get("trade_readiness_score"), 0.0)
        entry_timing = (data.get("entry_timing") or "").upper()

        # Setup forming = directional, strong confidence, but still waiting
        if signal in [None, "Neutral", "HOLD"]:
            continue

        if confidence < 80:
            continue

        if entry_timing != "WAIT":
            continue

        high = safe_float(data.get("high"), 0.0)
        low = safe_float(data.get("low"), 0.0)
        volatility = abs(high - low)

        score = confidence + (volatility * 10) + readiness

        if score > best_score:
            best_score = score
            best_trade = {
                "market": market_name,
                "last_updated": data.get("last_updated"),
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "close": data.get("close"),
                "upper_wick": data.get("upper_wick"),
                "lower_wick": data.get("lower_wick"),
                "signal": data.get("signal"),
                "confidence": data.get("confidence"),
                "pattern": data.get("pattern"),
                "breakout": data.get("breakout"),
                "liquidity_event": data.get("liquidity_event"),
                "trendline": data.get("trendline"),
                "setup_type": data.get("setup_type"),
                "ai_summary": data.get("ai_summary"),
                "trade_thesis": data.get("trade_thesis"),
                "risk_note": data.get("risk_note"),
                "strategy_recommendation": data.get("strategy_recommendation"),
                "strategy_reason": data.get("strategy_reason"),
                "suggested_action": data.get("suggested_action"),
                "support_levels": data.get("support_levels"),
                "resistance_levels": data.get("resistance_levels"),
                "trendline_points": data.get("trendline_points"),
                "breakout_zone": data.get("breakout_zone"),
                "entry_zone": data.get("entry_zone"),
                "strategy_visual_bias": data.get("strategy_visual_bias"),
                "entry_timing": data.get("entry_timing"),
                "confirmation_state": data.get("confirmation_state"),
                "trade_readiness_score": data.get("trade_readiness_score"),
                "execution_guidance": data.get("execution_guidance"),
                "session_label": data.get("session_label"),
                "active_sessions": data.get("active_sessions"),
                "liquidity_profile": data.get("liquidity_profile"),
                "utc_hour": data.get("utc_hour"),
                "setup_forming_score": round(score, 2)
            }

    return best_trade

def compute_trade_score(state):
    try:
        confidence = safe_float(state.get("confidence"), 0)
        readiness = safe_float(state.get("trade_readiness_score"), 0)
        entry_timing = str(state.get("entry_timing", "")).upper()

        breakout = str(state.get("breakout", "")).lower()
        liquidity = str(state.get("liquidity_event", "")).lower()
        trendline = str(state.get("trendline", "")).lower()
        pattern = str(state.get("pattern", "")).lower()
        session = str(state.get("session_label", "")).upper()

        high = safe_float(state.get("high"), 0)
        low = safe_float(state.get("low"), 0)

        # -----------------------------
        # BASE SCORE
        # -----------------------------
        score = confidence

        # -----------------------------
        # ENTRY TIMING (VERY IMPORTANT)
        # -----------------------------
        if entry_timing == "ENTER NOW":
            score += 30
        elif entry_timing == "WAIT":
            score += 10
        elif entry_timing == "AVOID":
            score -= 20

        # -----------------------------
        # READINESS
        # -----------------------------
        score += readiness * 0.25

        # -----------------------------
        # BREAKOUT LOGIC
        # -----------------------------
        if "failed" in breakout:
            score += 15   # failed breakout = reversal opportunity
        elif "breakout" in breakout:
            score += 10

        # -----------------------------
        # LIQUIDITY EVENTS (BIG EDGE)
        # -----------------------------
        if "liquidity sweep" in liquidity:
            score += 20
        elif "liquidity grab" in liquidity:
            score += 15

        # -----------------------------
        # TRENDLINE CONFLUENCE
        # -----------------------------
        if "support" in trendline or "resistance" in trendline:
            score += 10

        # -----------------------------
        # PATTERN STRENGTH
        # -----------------------------
        if "engulfing" in pattern:
            score += 12
        elif "pin bar" in pattern:
            score += 10
        elif "doji" in pattern:
            score -= 5   # indecision

        # -----------------------------
        # SESSION POWER
        # -----------------------------
        if session == "NYSE":
            score += 10
        elif session == "LONDON":
            score += 7
        elif session == "ASIA":
            score += 3

        # -----------------------------
        # VOLATILITY BOOST
        # -----------------------------
        volatility = abs(high - low)

        if volatility > 0:
            score += min(volatility * 10, 15)  # cap boost

        return round(score, 2)

    except Exception as e:
        print(f"❌ compute_trade_score error: {e}", flush=True)
        return 0


def get_all_live_ranked_trades():
    ranked = []

    live_markets = LIVE_MARKET_STATE.get("markets", {})

    if not isinstance(live_markets, dict):
        return ranked

    for market_name, data in live_markets.items():
        try:
            if not isinstance(data, dict):
                continue

            raw_signal = data.get("signal")
            signal = str(raw_signal).upper().strip() if raw_signal else "NEUTRAL"

            if signal == "BULLISH":
                signal = "BUY"
            elif signal == "BEARISH":
                signal = "SELL"

            confidence = safe_float(data.get("confidence"), 0.0)
            readiness = safe_float(data.get("trade_readiness_score"), 0.0)
            score = safe_float(data.get("trade_quality_score"), 0.0)

            # TEMP TESTING MODE
            # Allow developing trades through
            if signal in ["NEUTRAL", ""]:
                if confidence < 55 and readiness < 35 and score < 35:
                    continue

            candle = data.get("current_candle", {}) if isinstance(data.get("current_candle"), dict) else {}

            trade = {
                "market": market_name,
                "signal": signal,
                "confidence": confidence,
                "setup_type": data.get("setup_type"),
                "entry_timing": data.get("entry_timing"),
                "trade_readiness_score": readiness,
                "trade_quality_score": round(score, 2),
                "top_trade_score": round(score, 2),

                "chart_symbol": get_chart_symbol(market_name),

                "ai_summary": data.get("ai_summary"),
                "trade_thesis": data.get("trade_thesis"),
                "risk_note": data.get("risk_note"),
                "strategy_recommendation": data.get("strategy_recommendation"),
                "strategy_reason": data.get("strategy_reason"),
                "execution_guidance": data.get("execution_guidance"),

                "session_label": data.get("session_label"),
                "active_sessions": data.get("active_sessions"),
                "liquidity_profile": data.get("liquidity_profile"),
                "utc_hour": data.get("utc_hour"),

                "breakout": data.get("breakout"),
                "liquidity_event": data.get("liquidity_event"),
                "trendline": data.get("trendline"),
                "pattern": data.get("pattern"),

                "breakout_zone": data.get("breakout_zone"),
                "entry_zone": data.get("entry_zone"),
                "support_levels": data.get("support_levels"),
                "resistance_levels": data.get("resistance_levels"),
                "trendline_points": data.get("trendline_points"),
                "strategy_visual_bias": data.get("strategy_visual_bias"),
                "confirmation_state": data.get("confirmation_state"),

                "open": candle.get("Open", data.get("open")),
                "high": candle.get("High", data.get("high")),
                "low": candle.get("Low", data.get("low")),
                "close": candle.get("Close", data.get("close")),
                "upper_wick": data.get("upper_wick"),
                "lower_wick": data.get("lower_wick"),

                "last_updated": data.get("last_updated")
            }

            ranked.append(trade)

        except Exception as e:
            print(f"⚠️ Skipping {market_name}: {e}", flush=True)
            continue

    ranked.sort(
        key=lambda x: x.get("trade_quality_score", 0),
        reverse=True
    )

    return ranked


def detect_auto_trigger_candidates():
    triggered_trades = []

    for market_name, data in LIVE_MARKET_STATE.items():
        signal = data.get("signal")
        confidence = safe_float(data.get("confidence"), 0.0)
        readiness = safe_float(data.get("trade_readiness_score"), 0.0)
        entry_timing = (data.get("entry_timing") or "").upper()

        if signal in [None, "HOLD", "Neutral"]:
            continue

        if confidence < 80:
            continue

        if entry_timing != "ENTER NOW":
            continue

        if readiness < 70:
            continue

        triggered_trades.append({
            "market": market_name,
            "signal": signal,
            "confidence": confidence,
            "entry_timing": entry_timing,
            "trade_readiness_score": readiness,
            "setup_type": data.get("setup_type"),
            "ai_summary": data.get("ai_summary"),
            "trade_thesis": data.get("trade_thesis"),
            "last_updated": data.get("last_updated")
        })

    return triggered_trades



def check_for_live_top_trade_change():
    global LIVE_TOP_TRADE_STATE

    current_top_trade = get_current_live_top_trade()

    if not current_top_trade:
        return

    previous_top_trade = LIVE_TOP_TRADE_STATE.copy()

    if previous_top_trade.get("market") is None:
        LIVE_TOP_TRADE_STATE = current_top_trade
        return

    changed = False

    if previous_top_trade.get("market") != current_top_trade.get("market"):
        changed = True
    elif previous_top_trade.get("signal") != current_top_trade.get("signal"):
        changed = True
    elif previous_top_trade.get("setup_type") != current_top_trade.get("setup_type"):
        changed = True
    elif abs(
        safe_float(previous_top_trade.get("confidence"), 0.0) -
        safe_float(current_top_trade.get("confidence"), 0.0)
    ) >= 10:
        changed = True

    if changed:
        cooldown_key = "top_trade"

        if can_send_live_notification(cooldown_key, 90):
            create_notification({
                "type": "live_top_trade_change",
                "title": f"Top trade changed: {current_top_trade.get('market')}",
                "market": current_top_trade.get("market"),
                "signal": current_top_trade.get("signal"),
                "setup_type": current_top_trade.get("setup_type"),
                "confidence": current_top_trade.get("confidence")
            })

    LIVE_TOP_TRADE_STATE = current_top_trade
        
def can_send_live_notification(key, cooldown_seconds=60):
    global LIVE_NOTIFICATION_COOLDOWNS

    now = datetime.utcnow()

    last_sent = LIVE_NOTIFICATION_COOLDOWNS.get(key)

    if last_sent:
        elapsed = (now - last_sent).total_seconds()
        if elapsed < cooldown_seconds:
            return False

    LIVE_NOTIFICATION_COOLDOWNS[key] = now
    return True

def process_auto_triggers():
    candidates = detect_auto_trigger_candidates()

    for trade in candidates:
        market = trade.get("market")
        cooldown_key = f"auto_trigger:{market}"

        if can_send_live_notification(cooldown_key, 120):
            create_notification({
                "type": "auto_trigger",
                "title": f"{market} trigger ready",
                "market": market,
                "signal": trade.get("signal"),
                "confidence": trade.get("confidence"),
                "setup_type": trade.get("setup_type"),
                "entry_timing": trade.get("entry_timing"),
                "trade_readiness_score": trade.get("trade_readiness_score"),
                "ai_summary": trade.get("ai_summary")
            })

def clamp_score(value, min_value=0.0, max_value=100.0):
    try:
        value = float(value)
    except Exception:
        value = 0.0
    return max(min_value, min(max_value, value))


def get_trade_quality_score(confidence, trade_readiness, confluence_bonus=0):
    confidence = safe_float(confidence, 0.0)
    trade_readiness = safe_float(trade_readiness, 0.0)
    confluence_bonus = safe_float(confluence_bonus, 0.0)

    score = (
        confidence * 0.5 +
        trade_readiness * 0.35 +
        min(confluence_bonus * 5.0, 15.0)
    )

    return round(clamp_score(score), 2)


def get_entry_timing_from_quality(score):
    score = safe_float(score, 0.0)

    if score < 40:
        return "AVOID"
    elif score < 65:
        return "WAIT"
    return "ENTER NOW"


def get_trade_status_label(score):
    score = safe_float(score, 0.0)

    if score < 40:
        return "WAIT"
    elif score < 65:
        return "DEVELOPING"
    elif score < 85:
        return "READY"
    return "HOT"

    

def update_live_signal(market):
    global LIVE_MARKET_STATE

    try:
        if "markets" not in LIVE_MARKET_STATE or not isinstance(LIVE_MARKET_STATE["markets"], dict):
            return

        markets = LIVE_MARKET_STATE["markets"]

        if market not in markets:
            return

        state = markets.get(market, {})
        previous_state = dict(state) if isinstance(state, dict) else {}

        current_candle = state.get("current_candle")
        completed_candles = state.get("completed_candles", [])

        if not isinstance(current_candle, dict) or not current_candle:
            return

        if not isinstance(completed_candles, list):
            completed_candles = []

        candles = completed_candles + [current_candle]

        # -----------------------------
        # MINIMUM DATA CHECK
        # -----------------------------
        if len(candles) < 3:
            wick_data = calculate_live_wicks(current_candle) or {}
            state["upper_wick"] = safe_float(wick_data.get("upper_wick"))
            state["lower_wick"] = safe_float(wick_data.get("lower_wick"))
            state["last_updated"] = datetime.utcnow().isoformat() + "Z"
            LIVE_MARKET_STATE["markets"][market] = state
            return

        df = pd.DataFrame(candles)

        if df is None or df.empty:
            return

        required_cols = ["Open", "High", "Low", "Close"]

        for col in required_cols:
            if col not in df.columns:
                print(f"❌ Missing column {col} for {market}", flush=True)
                return
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=required_cols).copy()

        if df.empty:
            print(f"❌ DataFrame empty after cleaning for {market}", flush=True)
            return

        # -----------------------------
        # RUN SIGNAL ENGINE
        # -----------------------------
        try:
            signal_data = evaluate_signal(df)
            if not isinstance(signal_data, dict):
                signal_data = {}
        except Exception as e:
            print(f"❌ evaluate_signal failed for {market}: {e}", flush=True)
            return

        # -----------------------------
        # CORE METRICS
        # -----------------------------
        confidence = safe_float(signal_data.get("confidence"), 50)
        trade_readiness = safe_float(get_trade_readiness(signal_data), 0)
        print("DEBUG READINESS:", trade_readiness, flush=True)
        confluence_bonus = safe_float(signal_data.get("confluence_bonus"), 0)

        trade_quality_score = (
            confidence * 0.5 +
            trade_readiness * 0.35 +
            min(confluence_bonus * 5, 15)
        )

        trade_quality_score = max(0, min(100, trade_quality_score))
        trade_quality_score = round(trade_quality_score, 2)

        # -----------------------------
        # ENTRY LOGIC
        # -----------------------------
        if trade_quality_score < 30:
            entry_timing = "AVOID"
            trade_status = "WAIT"
        elif trade_quality_score < 50:
            entry_timing = "WAIT"
            trade_status = "DEVELOPING"
        elif trade_quality_score < 70:
            entry_timing = "EARLY ENTRY"
            trade_status = "FORMING"
        elif trade_quality_score < 85:
            entry_timing = "ENTER NOW"
            trade_status = "READY"
        else:
            entry_timing = "ENTER NOW"
            trade_status = "HOT"

        signal = str(signal_data.get("signal", "")).upper()

        if signal == "BULLISH":
            display_signal = "BUY"
        elif signal == "BEARISH":
            display_signal = "SELL"
        elif signal in ["BUY", "SELL", "NEUTRAL"]:
            display_signal = signal
        else:
            display_signal = "NEUTRAL"

        wick_data = calculate_live_wicks(current_candle) or {}
        session_data = get_market_session() or {}

        try:
            execution_guidance = get_execution_guidance(entry_timing, display_signal)
        except Exception:
            execution_guidance = None

        ai_summary = signal_data.get("ai_summary") or (
            f"{display_signal} setup detected on {market}. "
            f"Confidence is {round(confidence, 2)}% with a trade quality score of {round(trade_quality_score, 2)}."
        )

        trade_thesis = signal_data.get("trade_thesis") or (
            f"WickSense is reading {market} as {display_signal}. "
            f"The system is comparing wick behavior, candle structure, support, resistance, trendline behavior, "
            f"and current session conditions before confirming the setup."
        )

        risk_note = signal_data.get("risk_note") or (
            "Use paper trading only while testing. Confirm entry, stop loss, target, and market direction before taking any real trade."
        )

        new_payload = {
            "market": market,
            "completed_candles": completed_candles,
            "current_candle": current_candle,

            "open": safe_float(current_candle.get("Open")),
            "high": safe_float(current_candle.get("High")),
            "low": safe_float(current_candle.get("Low")),
            "close": safe_float(current_candle.get("Close")),

            "upper_wick": safe_float(wick_data.get("upper_wick")),
            "lower_wick": safe_float(wick_data.get("lower_wick")),

            "signal": display_signal,
            "confidence": confidence,
            "trade_readiness_score": trade_readiness,
            "trade_quality_score": trade_quality_score,
            "top_trade_score": trade_quality_score,
            "trade_status": trade_status,
            "entry_timing": entry_timing,
            "execution_guidance": execution_guidance,

            "pattern": signal_data.get("pattern"),
            "breakout": signal_data.get("breakout"),
            "liquidity_event": signal_data.get("liquidity_event"),
            "trendline": signal_data.get("trendline"),

            "setup_type": signal_data.get("setup_type"),
            "ai_summary": ai_summary,
            "trade_thesis": trade_thesis,
            "risk_note": risk_note,

            "support_levels": signal_data.get("support"),
            "resistance_levels": signal_data.get("resistance"),

            "session_label": session_data.get("session_label"),
            "active_sessions": session_data.get("active_sessions"),
            "liquidity_profile": session_data.get("liquidity_profile"),
            "utc_hour": session_data.get("utc_hour"),

            "last_updated": datetime.utcnow().isoformat() + "Z"
        }

        state.update(new_payload)
        LIVE_MARKET_STATE["markets"][market] = state

        try:
            changed = has_live_signal_changed(previous_state, new_payload)
            if changed:
                handle_live_signal_change(market, previous_state, new_payload)
                save_live_signal_history_entry(market, new_payload)
        except Exception as e:
            print(f"⚠️ post-update hooks failed: {e}", flush=True)

    except Exception as e:
        print(f"❌ update_live_signal fatal error for {market}: {e}", flush=True)


def update_trade_ranking(market):
    global TRADE_RANKINGS, LIVE_MARKET_STATE

    try:
        if "markets" not in LIVE_MARKET_STATE or not isinstance(LIVE_MARKET_STATE["markets"], dict):
            return

        state = LIVE_MARKET_STATE["markets"].get(market, {})

        if not isinstance(state, dict) or not state:
            return

        signal = str(state.get("signal", "")).upper()
        score = safe_float(state.get("trade_quality_score"), 0)

        if signal == "BULLISH":
            signal = "BUY"
        elif signal == "BEARISH":
            signal = "SELL"

        if signal not in ["BUY", "SELL"]:
            return

        if score <= 0:
            return

        trade = dict(state)
        trade["market"] = market
        trade["signal"] = signal
        trade["chart_symbol"] = get_chart_symbol(market)

        if "all_ranked" not in TRADE_RANKINGS or not isinstance(TRADE_RANKINGS["all_ranked"], list):
            TRADE_RANKINGS["all_ranked"] = []

        TRADE_RANKINGS["all_ranked"] = [
            t for t in TRADE_RANKINGS["all_ranked"]
            if t.get("market") != market
        ]

        TRADE_RANKINGS["all_ranked"].append(trade)

        TRADE_RANKINGS["all_ranked"].sort(
            key=lambda x: safe_float(x.get("trade_quality_score"), 0),
            reverse=True
        )

        ranked = TRADE_RANKINGS["all_ranked"]

        TRADE_RANKINGS["top_trade"] = ranked[0] if ranked else None
        TRADE_RANKINGS["next_best"] = ranked[1:5] if len(ranked) > 1 else []
        TRADE_RANKINGS["last_updated"] = datetime.utcnow().isoformat() + "Z"

    except Exception as e:
        print(f"❌ Ranking error for {market}: {e}", flush=True)


def run_polling_fallback():
    print("🔥 run_polling_fallback entered", flush=True)

    global POLLING_ACTIVE, STREAM_STATUS, LIVE_MARKET_STATE

    POLLING_ACTIVE = True

    STREAM_STATUS["status"] = "connected"
    STREAM_STATUS["provider"] = "polling"
    STREAM_STATUS["last_error"] = None
    STREAM_STATUS["polling_active"] = True
    STREAM_STATUS["websocket_active"] = False

    # 🧠 ENSURE MARKETS EXIST (CRITICAL FIX)
    if "markets" not in LIVE_MARKET_STATE or not isinstance(LIVE_MARKET_STATE["markets"], dict):
        LIVE_MARKET_STATE["markets"] = {}

    DEFAULT_MARKETS = ["Forex", "Gold", "NASDAQ", "DowJones", "NaturalGas", "Futures"]

    for m in DEFAULT_MARKETS:
        if m not in LIVE_MARKET_STATE["markets"]:
            LIVE_MARKET_STATE["markets"][m] = {}

    print(f"✅ Markets initialized: {list(LIVE_MARKET_STATE['markets'].keys())}", flush=True)

    while POLLING_ACTIVE:
        try:
            print("🔄 polling loop tick", flush=True)

            for market in list(LIVE_MARKET_STATE["markets"].keys()):
                try:
                    df = fetch_live_market_data(
                        market,
                        interval="1min",
                        outputsize=10
                    )

                    if df is None or df.empty:
                        print(f"⚠️ No data for {market}", flush=True)
                        continue

                    latest = df.iloc[-1]

                    try:
                        open_p = float(latest["Open"])
                        high_p = float(latest["High"])
                        low_p = float(latest["Low"])
                        close_p = float(latest["Close"])
                    except Exception as parse_error:
                        print(f"❌ Parse error for {market}: {parse_error}", flush=True)
                        continue

                    # SCALE GUARDS
                    if market == "Forex" and (close_p <= 0 or close_p > 5):
                        print(f"🚫 REJECTED Forex bad scale: {close_p}", flush=True)
                        continue

                    if market == "Gold" and (close_p < 1000 or close_p > 5000):
                        print(f"🚫 REJECTED Gold bad scale: {close_p}", flush=True)
                        continue

                    existing = LIVE_MARKET_STATE["markets"].get(market, {})
                    if not isinstance(existing, dict):
                        existing = {}

                    existing_completed = existing.get("completed_candles", [])
                    if not isinstance(existing_completed, list):
                        existing_completed = []

                    completed_candles = existing_completed.copy()

                    # 🧠 BUILD HISTORY WITHOUT RESETTING
                    if len(df) > 1:
                        historical_rows = df.iloc[:-1].copy()

                        for _, row in historical_rows.iterrows():
                            try:
                                new_candle = {
                                    "minute": str(row.get("Datetime", "")),
                                    "Open": float(row["Open"]),
                                    "High": float(row["High"]),
                                    "Low": float(row["Low"]),
                                    "Close": float(row["Close"])
                                }

                                if not any(c.get("minute") == new_candle["minute"] for c in completed_candles):
                                    completed_candles.append(new_candle)

                            except Exception as candle_error:
                                print(f"⚠️ Skipping candle for {market}: {candle_error}", flush=True)
                                continue

                    completed_candles = completed_candles[-50:]

                    existing.update({
                        "current_candle": {
                            "minute": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                            "Open": open_p,
                            "High": high_p,
                            "Low": low_p,
                            "Close": close_p
                        },
                        "completed_candles": completed_candles,
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "close": close_p,
                        "last_updated": datetime.utcnow().isoformat() + "Z"
                    })

                    LIVE_MARKET_STATE["markets"][market] = existing

                    # 🚀 SIGNAL ENGINE
                    try:
                        update_live_signal(market)
                        update_trade_ranking(market)
                    except Exception as signal_error:
                        print(f"❌ Signal error for {market}: {signal_error}", flush=True)

                except Exception as market_error:
                    print(f"❌ Market loop error for {market}: {market_error}", flush=True)
                    continue

            STREAM_STATUS["last_tick"] = datetime.utcnow().isoformat() + "Z"

            time.sleep(10)

        except Exception as e:
            STREAM_STATUS["last_error"] = str(e)
            STREAM_STATUS["status"] = "disconnected"

            print(f"❌ polling error: {e}", flush=True)

            time.sleep(5)


def get_simulated_base_price(market):
    base_prices = {
        "NASDAQ": 450.0,
        "DowJones": 390.0,
        "Gold": 2300.0,
        "NaturalGas": 2.5,
        "Forex": 1.08,
        "Futures": 520.0
    }
    return base_prices.get(market, 100.0)

def seed_live_market_state():
    global LIVE_MARKET_STATE

    print("🌱 Seeding live market state...", flush=True)

    # Ensure correct structure
    if not isinstance(LIVE_MARKET_STATE, dict):
        LIVE_MARKET_STATE = {}

    LIVE_MARKET_STATE["markets"] = {
        "Forex": {},
        "Gold": {},
        "NaturalGas": {},
        "NASDAQ": {},
        "DowJones": {},
        "Futures": {}
    }

    for market in LIVE_MARKET_STATE["markets"].keys():
        try:
            print(f"🌱 Seeding {market}", flush=True)

            base_price = get_simulated_base_price(market)
            completed_candles = []

            for i in range(25):
                if market == "Forex":
                    drift = random.uniform(-0.003, 0.003)
                    spread = random.uniform(0.0005, 0.002)
                elif market == "NaturalGas":
                    drift = random.uniform(-0.08, 0.08)
                    spread = random.uniform(0.02, 0.08)
                elif market == "Gold":
                    drift = random.uniform(-8.0, 8.0)
                    spread = random.uniform(1.5, 5.0)
                else:
                    drift = random.uniform(-2.0, 2.0)
                    spread = random.uniform(0.5, 2.5)

                open_price = max(base_price + drift, 0.0001)
                close_price = max(open_price + random.uniform(-spread, spread), 0.0001)
                high_price = max(open_price, close_price) + abs(random.uniform(0, spread))
                low_price = min(open_price, close_price) - abs(random.uniform(0, spread))
                low_price = max(low_price, 0.0001)

                completed_candles.append({
                    "minute": f"seed-{i}",
                    "Open": round(open_price, 6),
                    "High": round(high_price, 6),
                    "Low": round(low_price, 6),
                    "Close": round(close_price, 6)
                })

                base_price = close_price

            current_candle = completed_candles[-1].copy()

            LIVE_MARKET_STATE["markets"][market] = {
                "market": market,
                "completed_candles": completed_candles,
                "current_candle": current_candle,
                "open": current_candle.get("Open"),
                "high": current_candle.get("High"),
                "low": current_candle.get("Low"),
                "close": current_candle.get("Close"),
                "signal": "NEUTRAL",
                "confidence": 0,
                "trade_quality_score": 0,
                "trade_readiness_score": 0,
                "top_trade_score": 0,
                "last_updated": datetime.utcnow().isoformat() + "Z"
            }

            update_live_signal(market)

        except Exception as e:
            print(f"❌ Seed error for {market}: {e}", flush=True)


def run_live_signal_engine():
    global STREAM_STATUS

    STREAM_STATUS["status"] = "connected"
    STREAM_STATUS["provider"] = "simulated"

    while True:
        try:
            for market in LIVE_MARKET_STATE["markets"].keys():
                state = LIVE_MARKET_STATE["markets"].get(market, {})
                current_candle = state.get("current_candle")

                if current_candle:
                    base_price = safe_float(
                        current_candle.get("Close"),
                        get_simulated_base_price(market)
                    )
                else:
                    base_price = get_simulated_base_price(market)

                movement = random.uniform(-0.5, 0.5)

                if market == "Forex":
                    movement = random.uniform(-0.002, 0.002)
                elif market == "NaturalGas":
                    movement = random.uniform(-0.05, 0.05)
                elif market == "Gold":
                    movement = random.uniform(-3.0, 3.0)

                new_price = max(base_price + movement, 0.0001)

                update_live_candle(market, new_price)
                update_live_signal(market)
                check_for_live_top_trade_change()
                process_auto_triggers()

            time.sleep(10)

        except Exception as e:
            print(f"❌ Live signal engine error: {e}", flush=True)
            time.sleep(10)


def start_twelvedata_stream():
    global STREAM_STATUS, WS_ACTIVE, POLLING_ACTIVE

    def on_message(ws, message):
        try:
            data = json.loads(message)

            if "event" in data and data["event"] == "price":
                symbol = data.get("symbol")
                price = safe_float(data.get("price"))

                market_map = {
                    "QQQ": "NASDAQ",
                    "DIA": "DowJones",
                    "XAU/USD": "Gold",
                    "UNG": "NaturalGas",
                    "EUR/USD": "Forex",
                    "SPY": "Futures"
                }

                market = market_map.get(symbol)

                if market and price:
                    update_live_candle(market, price)
                    update_live_signal(market)

                    STREAM_STATUS["last_tick"] = datetime.utcnow().isoformat() + "Z"
                    STREAM_STATUS["status"] = "connected"
                    STREAM_STATUS["provider"] = "twelvedata"

        except Exception as e:
            print(f"WebSocket error: {e}")

    def on_open(ws):
        global WS_ACTIVE, POLLING_ACTIVE

        WS_ACTIVE = True
        POLLING_ACTIVE = False

        STREAM_STATUS["status"] = "connected"
        STREAM_STATUS["provider"] = "twelvedata"

        ws.send(json.dumps({
            "action": "subscribe",
            "params": {
                "symbols": "QQQ,DIA,XAU/USD,NG,EUR/USD,SPY"
            }
        }))

    def on_close(ws, *args):
        global WS_ACTIVE
        WS_ACTIVE = False
        STREAM_STATUS["status"] = "disconnected"

    ws = websocket.WebSocketApp(
        f"wss://ws.twelvedata.com/v1/quotes/price?apikey={TWELVE_DATA_API_KEY}",
        on_message=on_message,
        on_open=on_open,
        on_close=on_close
    )

    ws.run_forever()

def start_twelvedata_stream_with_reconnect():
    while True:
        try:
            start_twelvedata_stream()
        except Exception as e:
            STREAM_STATUS["status"] = "disconnected"
            STREAM_STATUS["last_error"] = str(e)
            print(f"❌ TwelveData websocket error: {e}", flush=True)
            time.sleep(30)


def ensure_live_engine_started():
    global LIVE_ENGINE_STARTED, LIVE_MARKET_STATE

    if LIVE_ENGINE_STARTED:
        return

    with LIVE_ENGINE_LOCK:
        if LIVE_ENGINE_STARTED:
            return

        print("🚀 Starting live engine in POLLING ONLY mode", flush=True)

        if "markets" not in LIVE_MARKET_STATE or not isinstance(LIVE_MARKET_STATE["markets"], dict):
            LIVE_MARKET_STATE["markets"] = {}

        DEFAULT_MARKETS = ["Forex", "Gold", "NASDAQ", "DowJones", "NaturalGas", "Futures"]

        for market in DEFAULT_MARKETS:
            if market not in LIVE_MARKET_STATE["markets"]:
                LIVE_MARKET_STATE["markets"][market] = {}

            LIVE_MARKET_STATE["markets"][market].update({
                "completed_candles": [],
                "current_candle": None,
                "signal": "NEUTRAL",
                "confidence": 0,
                "trade_quality_score": 0,
                "trade_readiness_score": 0,
                "top_trade_score": 0,
                "last_updated": datetime.utcnow().isoformat() + "Z"
            })

        def start_engine():
            print("🔥 Using polling fallback only", flush=True)
            run_polling_fallback()

        threading.Thread(target=start_engine, daemon=True).start()
        LIVE_ENGINE_STARTED = True



def get_string_from_request(key, default_value):
    body = get_request_body()
    return body.get(key, default_value)


def validate_market_df(df: pd.DataFrame):
    required_cols = ["Open", "High", "Low", "Close"]
    missing = [c for c in required_cols if c not in df.columns]
    return missing


def fetch_live_market_data(market: str, interval: str = "1h", outputsize: int = 50):
    try:
        import pandas as pd
        import requests

        # -----------------------------
        # NORMALIZE INPUTS
        # -----------------------------
        market = str(market).strip().upper().replace(" ", "")
        interval = str(interval).strip().lower()

        # -----------------------------
        # SYMBOL MAPPING
        # -----------------------------
        symbol = MARKET_SYMBOLS.get(market)

        print(f"📡 FETCH SYMBOL: {market} -> {symbol}", flush=True)

        if not symbol:
            print(f"❌ No symbol mapping for market: {market}", flush=True)
            return None

        # -----------------------------
        # INTERVAL HANDLING (FIXED)
        # -----------------------------
        VALID_TWELVEDATA_INTERVALS = {
            "1min", "5min", "15min", "30min", "45min",
            "1h", "2h", "4h", "8h",
            "1day", "1week"
        }

        if interval in VALID_TWELVEDATA_INTERVALS:
            mapped_interval = interval
        else:
            mapped_interval = INTERVAL_MAP.get(interval)

        if not mapped_interval:
            print(f"❌ Invalid interval mapping: {interval}", flush=True)
            return None

        print(
            f"📊 Requesting TwelveData: symbol={symbol}, interval={mapped_interval}, outputsize={outputsize}",
            flush=True
        )

        # -----------------------------
        # API REQUEST
        # -----------------------------
        url = "https://api.twelvedata.com/time_series"

        params = {
            "symbol": symbol,
            "interval": mapped_interval,
            "outputsize": outputsize,
            "apikey": TWELVE_DATA_API_KEY
        }

        response = requests.get(url, params=params)
        data = response.json()

        # -----------------------------
        # ERROR HANDLING
        # -----------------------------
        if "values" not in data:
            print(f"❌ TwelveData ERROR: {data}", flush=True)
            return None

        # -----------------------------
        # DATAFRAME CREATION
        # -----------------------------
        df = pd.DataFrame(data["values"])

        df.rename(columns={
            "datetime": "Datetime",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close"
        }, inplace=True)

        # -----------------------------
        # CLEAN NUMERIC DATA
        # -----------------------------
        required_cols = ["Open", "High", "Low", "Close"]

        for col in required_cols:
            if col not in df.columns:
                print(f"❌ Missing column: {col}", flush=True)
                return None

            df[col] = df[col].astype(str).str.replace(",", "", regex=False).str.strip()
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=required_cols).copy()

        if df.empty:
            print("❌ No valid numeric rows after cleaning", flush=True)
            return None

        # -----------------------------
        # SORT DATA
        # -----------------------------
        df = df.sort_values("Datetime").reset_index(drop=True)

        print(f"✅ Data fetched: {len(df)} rows", flush=True)

        return df

    except Exception as e:
        print(f"❌ fetch_live_market_data ERROR: {e}", flush=True)
        return None



# -----------------------------
# FETCH CANDLES FOR ROCKET PROXY
# -----------------------------
@app.route("/fetch-candles", methods=["POST", "OPTIONS"])
def fetch_candles():
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200

    try:
        import time

        data = request.get_json(silent=True) or {}

        market = data.get("market")
        timeframe = data.get("timeframe", "1h")
        start_date = data.get("start_date")
        outputsize = int(data.get("outputsize", 1000))

        if not market:
            return jsonify({
                "ok": False,
                "error": "Missing required field: market"
            }), 400

        interval_map = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "15min": "15min",
            "30m": "30min",
            "30min": "30min",
            "45m": "45min",
            "45min": "45min",
            "1h": "1h",
            "2h": "2h",
            "4h": "4h",
            "8h": "8h",
            "1d": "1day",
            "1day": "1day",
            "1w": "1week",
            "1week": "1week",
            "1mo": "1month",
            "1month": "1month",
        }

        interval = interval_map.get(str(timeframe).strip().lower(), "1h")

        print("\n========== FETCH CANDLES ROUTE ==========", flush=True)
        print("MARKET:", market, flush=True)
        print("TIMEFRAME:", timeframe, flush=True)
        print("INTERVAL USED:", interval, flush=True)
        print("START_DATE:", start_date, flush=True)
        print("OUTPUTSIZE:", outputsize, flush=True)

        # Small throttle to reduce rate-limit pressure
        time.sleep(0.2)

        df = fetch_live_market_data(
            market=market,
            interval=interval,
            outputsize=outputsize
        )

        # Handle completely missing fetch result
        if df is None:
            print(f"⚠️ fetch_live_market_data returned None for {market}", flush=True)
            return jsonify({
                "ok": True,
                "market": market,
                "timeframe": timeframe,
                "interval_used": interval,
                "start_date": start_date,
                "count": 0,
                "candles": []
            }), 200

        # Handle empty dataframe
        if df.empty:
            print(f"⚠️ Empty dataframe returned for {market}", flush=True)
            return jsonify({
                "ok": True,
                "market": market,
                "timeframe": timeframe,
                "interval_used": interval,
                "start_date": start_date,
                "count": 0,
                "candles": []
            }), 200

        if "Datetime" not in df.columns:
            print(f"❌ Datetime column missing for {market}. Columns: {list(df.columns)}", flush=True)
            return jsonify({
                "ok": False,
                "error": "Datetime column missing from fetched candle data"
            }), 500

        # Normalize Datetime column
        df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True, errors="coerce")
        df = df.dropna(subset=["Datetime"]).copy()

        print("TOTAL CANDLES BEFORE FILTER:", len(df), flush=True)
        if not df.empty:
            print("FIRST CANDLE BEFORE FILTER:", df["Datetime"].iloc[0], flush=True)
            print("LAST CANDLE BEFORE FILTER:", df["Datetime"].iloc[-1], flush=True)

        # Apply start_date filter
        if start_date:
            try:
                start_dt = pd.to_datetime(start_date, utc=True, errors="coerce")

                if pd.isna(start_dt):
                    return jsonify({
                        "ok": False,
                        "error": f"Invalid start_date received: {start_date}"
                    }), 400

                print("START_DT NORMALIZED:", start_dt, flush=True)
                print("DF Datetime dtype:", df["Datetime"].dtype, flush=True)

                df = df[df["Datetime"] >= start_dt].copy()

                print("TOTAL CANDLES AFTER FILTER:", len(df), flush=True)
                if not df.empty:
                    print("FIRST CANDLE AFTER FILTER:", df["Datetime"].iloc[0], flush=True)
                    print("LAST CANDLE AFTER FILTER:", df["Datetime"].iloc[-1], flush=True)
                else:
                    print("ALL CANDLES FILTERED OUT", flush=True)

            except Exception as e:
                print("START DATE FILTER ERROR:", str(e), flush=True)
                return jsonify({
                    "ok": False,
                    "error": f"Failed to apply start_date filter: {str(e)}"
                }), 500

        # If everything got filtered out, return empty cleanly
        if df.empty:
            print(f"⚠️ No candles remaining after filtering for {market}", flush=True)
            return jsonify({
                "ok": True,
                "market": market,
                "timeframe": timeframe,
                "interval_used": interval,
                "start_date": start_date,
                "count": 0,
                "candles": []
            }), 200

        candles = []
        for _, row in df.iterrows():
            candles.append({
                "Datetime": row["Datetime"].isoformat(),
                "Open": float(row["Open"]),
                "High": float(row["High"]),
                "Low": float(row["Low"]),
                "Close": float(row["Close"])
            })

        print("CANDLES RETURNED:", len(candles), flush=True)
        if candles:
            print("FIRST RETURNED CANDLE:", candles[0], flush=True)
            print("LAST RETURNED CANDLE:", candles[-1], flush=True)

        print("========== FETCH CANDLES COMPLETE ==========\n", flush=True)

        return jsonify({
            "ok": True,
            "market": market,
            "timeframe": timeframe,
            "interval_used": interval,
            "start_date": start_date,
            "count": len(candles),
            "candles": candles
        }), 200

    except Exception as e:
        print("FETCH CANDLES ERROR:", str(e), flush=True)
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


def ensure_presets_file():
    if not os.path.exists(PRESETS_FILE):
        with open(PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)


def load_presets():
    ensure_presets_file()
    with open(PRESETS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_presets(presets):
    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2)


def find_preset(preset_id):
    presets = load_presets()
    for preset in presets:
        if preset["id"] == preset_id:
            return preset
    return None


def ensure_history_file(filepath):
    if not os.path.exists(filepath):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([], f)


def load_history(file_path):
    try:
        if not os.path.exists(file_path):
            return []

        with open(file_path, "r") as f:
            content = f.read().strip()

            if not content:
                return []

            return json.loads(content)

    except Exception as e:
        print("🔥 HISTORY LOAD FAILED:", str(e))
        return []



def save_history(filepath, items):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def append_history(filepath, item, max_items=100):
    history = load_history(filepath)
    history.insert(0, item)
    history = history[:max_items]
    save_history(filepath, history)


def ensure_risk_settings_file():
    if not os.path.exists(RISK_SETTINGS_FILE):
        default_settings = {
            "max_daily_loss": 500.0,
            "min_confidence_threshold": 70.0,
            "max_risk_percent_per_trade": 2.0,
            "block_low_quality_setups": False,
            "updated_at": datetime.utcnow().isoformat() + "Z"
        }
        with open(RISK_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(default_settings, f, indent=2)


def load_risk_settings():
    ensure_risk_settings_file()
    with open(RISK_SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_risk_settings(settings):
    settings["updated_at"] = datetime.utcnow().isoformat() + "Z"
    with open(RISK_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)



def is_pro_user(user_id):
    if not user_id:
        return False

    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/subscriptions",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}"
            },
            params={
                "user_id": f"eq.{user_id}",
                "status": "eq.active"
            },
            timeout=20
        )
        response.raise_for_status()
        data = response.json()
        return isinstance(data, list) and len(data) > 0
    except Exception as e:
        print("Error checking pro status:", str(e))
        return False


def send_sms_alert(message_text):
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")
    to_number = os.environ.get("TWILIO_TO_NUMBER")

    if not account_sid or not auth_token or not from_number or not to_number:
        print("SMS skipped: missing Twilio environment variables")
        return

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=message_text,
            from_=from_number,
            to=to_number
        )
        print(f"SMS sent: {message.sid}")
    except Exception as e:
        print(f"SMS failed: {e}")

def load_notifications():
    ensure_history_file(NOTIFICATION_FILE)
    return load_history(NOTIFICATION_FILE)


def save_notifications(items):
    save_history(NOTIFICATION_FILE, items)


def create_notification(notification):
    notification["id"] = str(uuid.uuid4())
    notification["created_at"] = datetime.utcnow().isoformat() + "Z"
    notification["is_read"] = False
    append_history(NOTIFICATION_FILE, notification, max_items=1000)

def save_live_signal_history_entry(market, payload):
    try:
        history_item = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "market": market,
            "signal": payload.get("signal"),
            "setup_type": payload.get("setup_type"),
            "confidence": payload.get("confidence"),
            "pattern": payload.get("pattern"),
            "entry": payload.get("close"),
            "open": payload.get("open"),
            "high": payload.get("high"),
            "low": payload.get("low"),
            "close": payload.get("close"),
            "upper_wick": payload.get("upper_wick"),
            "lower_wick": payload.get("lower_wick"),
            "breakout": payload.get("breakout"),
            "liquidity_event": payload.get("liquidity_event"),
            "trendline": payload.get("trendline"),
            "reason": payload.get("ai_summary"),
            "ai_summary": payload.get("ai_summary"),
            "trade_thesis": payload.get("trade_thesis"),
            "risk_note": payload.get("risk_note"),
            "strategy_recommendation": payload.get("strategy_recommendation"),
            "strategy_reason": payload.get("strategy_reason"),
            "suggested_action": payload.get("suggested_action"),
            "entry_timing": payload.get("entry_timing"),
            "confirmation_state": payload.get("confirmation_state"),
            "trade_readiness_score": payload.get("trade_readiness_score"),
            "execution_guidance": payload.get("execution_guidance")
        }

        append_history(SIGNAL_HISTORY_FILE, history_item, max_items=500)

    except Exception as e:
        print(f"Failed to save live signal history for {market}: {e}")


def find_journal_entry(entry_id):
    journal = load_history(TRADE_JOURNAL_FILE)
    for entry in journal:
        if entry["id"] == entry_id:
            return entry
    return None


def update_journal_entry(entry_id, updates):
    journal = load_history(TRADE_JOURNAL_FILE)
    updated_entry = None

    for entry in journal:
        if entry["id"] == entry_id:
            entry.update(updates)
            entry["updated_at"] = datetime.utcnow().isoformat() + "Z"
            updated_entry = entry
            break

    if updated_entry is None:
        return None

    save_history(TRADE_JOURNAL_FILE, journal)
    return updated_entry


def delete_journal_entry_by_id(entry_id):
    journal = load_history(TRADE_JOURNAL_FILE)
    filtered = [entry for entry in journal if entry["id"] != entry_id]

    if len(filtered) == len(journal):
        return False

    save_history(TRADE_JOURNAL_FILE, filtered)
    return True


def load_alert_rules():
    ensure_history_file(ALERT_RULES_FILE)
    return load_history(ALERT_RULES_FILE)


def save_alert_rules(rules):
    save_history(ALERT_RULES_FILE, rules)


def find_alert_rule(rule_id):
    rules = load_alert_rules()
    for rule in rules:
        if rule["id"] == rule_id:
            return rule
    return None


def load_alert_log():
    ensure_history_file(ALERT_LOG_FILE)
    return load_history(ALERT_LOG_FILE)


def save_alert_log(log_items):
    save_history(ALERT_LOG_FILE, log_items)


def build_alert_signature(rule, result):
    return "|".join([
        str(rule.get("id", "")),
        str(result.get("market", "")),
        str(result.get("signal", "")),
        str(result.get("setup_type", ""))
    ])


def should_send_alert(rule, result):
    cooldown_minutes = rule.get("cooldown_minutes", 60)

    try:
        cooldown_minutes = int(cooldown_minutes)
    except Exception:
        cooldown_minutes = 60

    signature = build_alert_signature(rule, result)
    alert_log = load_alert_log()

    for log_item in alert_log:
        if log_item.get("signature") == signature:
            last_sent = log_item.get("sent_at")
            if not last_sent:
                continue

            try:
                last_sent_dt = datetime.fromisoformat(last_sent.replace("Z", ""))
                now_dt = datetime.utcnow()
                minutes_since = (now_dt - last_sent_dt).total_seconds() / 60.0

                if minutes_since < cooldown_minutes:
                    return False
            except Exception:
                continue

    return True


def record_alert_sent(rule, result):
    log_item = {
        "id": str(uuid.uuid4()),
        "rule_id": rule.get("id"),
        "rule_name": rule.get("name"),
        "signature": build_alert_signature(rule, result),
        "market": result.get("market"),
        "signal": result.get("signal"),
        "setup_type": result.get("setup_type"),
        "sent_at": datetime.utcnow().isoformat() + "Z"
    }

    append_history(ALERT_LOG_FILE, log_item, max_items=2000)

def get_today_utc_date_string():
    return datetime.utcnow().strftime("%Y-%m-%d")


def calculate_today_realized_pnl():
    journal = load_history(TRADE_JOURNAL_FILE)
    today_str = get_today_utc_date_string()
    total_pnl = 0.0
    matched_entries = 0

    for entry in journal:
        created_at = entry.get("created_at", "")
        outcome = (entry.get("outcome") or "").lower()

        if not created_at.startswith(today_str):
            continue

        if outcome not in ["win", "loss", "breakeven"]:
            continue

        total_pnl += safe_float(entry.get("pnl"), 0.0)
        matched_entries += 1

    return {
        "date": today_str,
        "realized_pnl": round(total_pnl, 2),
        "closed_trade_count": matched_entries
    }


def get_daily_loss_status():
    settings = load_risk_settings()
    today_stats = calculate_today_realized_pnl()

    max_daily_loss = float(settings.get("max_daily_loss", 500.0))
    realized_pnl = float(today_stats.get("realized_pnl", 0.0))

    loss_used = abs(realized_pnl) if realized_pnl < 0 else 0.0
    remaining_loss_capacity = max(max_daily_loss - loss_used, 0.0)
    blocked = loss_used >= max_daily_loss

    return {
        "date": today_stats["date"],
        "max_daily_loss": round(max_daily_loss, 2),
        "realized_pnl": round(realized_pnl, 2),
        "closed_trade_count": today_stats["closed_trade_count"],
        "loss_used": round(loss_used, 2),
        "remaining_loss_capacity": round(remaining_loss_capacity, 2),
        "blocked": blocked
    }


def add_indicators(df: pd.DataFrame):
    df = df.copy()

    df["UpperWick"] = df["High"] - df[["Open", "Close"]].max(axis=1)
    df["LowerWick"] = df[["Open", "Close"]].min(axis=1) - df["Low"]
    df["BodySize"] = (df["Close"] - df["Open"]).abs()
    df["Range"] = df["High"] - df["Low"]

    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()

    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    df["VWAP"] = typical_price.expanding().mean()

    df["Support"] = df["Low"].rolling(10).min()
    df["Resistance"] = df["High"].rolling(10).max()

    df["PrevResistance"] = df["Resistance"].shift(1)
    df["PrevSupport"] = df["Support"].shift(1)

    df["SwingHigh"] = df["High"][
        (df["High"] > df["High"].shift(1)) &
        (df["High"] > df["High"].shift(-1))
    ]
    df["SwingLow"] = df["Low"][
        (df["Low"] < df["Low"].shift(1)) &
        (df["Low"] < df["Low"].shift(-1))
    ]

    return df


def detect_wick_pattern(df):
    try:
        if df is None or df.empty:
            return None

        # Always work on the LAST ROW safely
        row = df.iloc[-1]

        # Safe numeric extraction
        open_price = float(row.get("Open", 0))
        high_price = float(row.get("High", 0))
        low_price = float(row.get("Low", 0))
        close_price = float(row.get("Close", 0))

        candle_range = high_price - low_price
        if candle_range == 0:
            candle_range = 1  # prevent division crash

        body = abs(close_price - open_price)
        upper_wick = high_price - max(open_price, close_price)
        lower_wick = min(open_price, close_price) - low_price

        # Pattern logic
        if body < candle_range * 0.2:
            return "Doji"

        if lower_wick > body * 2 and upper_wick < body:
            return "Hammer"

        if upper_wick > body * 2 and lower_wick < body:
            return "Shooting Star"

        if lower_wick > body * 2 or upper_wick > body * 2:
            return "Pin Bar"

        return None

    except Exception as e:
        print(f"❌ detect_wick_pattern error: {e}", flush=True)
        return None


def should_take_trade(row, avg_range=None):
    try:
        close_price = float(row["Close"])
        ma50 = float(row["MA50"])
        vwap = float(row["VWAP"])
        body_size = float(row["BodySize"])
        candle_range = float(row["Range"])

        # Safety check
        if candle_range <= 0:
            return False, ["Invalid candle range"]

        reasons = []

        # 1. Trend filter
        trend_ok = close_price > ma50
        reasons.append(f"Trend filter: {'PASS' if trend_ok else 'FAIL'} (Close vs MA50)")

        # 2. VWAP confirmation
        vwap_ok = close_price > vwap
        reasons.append(f"VWAP filter: {'PASS' if vwap_ok else 'FAIL'} (Close vs VWAP)")

        # 3. Candle body strength
        body_ok = body_size > (candle_range * 0.4)
        reasons.append(f"Body strength: {'PASS' if body_ok else 'FAIL'} (Body > 40% of range)")

        # 4. Volatility filter
        volatility_ok = True
        if avg_range is not None:
            volatility_ok = candle_range > avg_range
            reasons.append(
                f"Volatility filter: {'PASS' if volatility_ok else 'FAIL'} "
                f"(Range {candle_range:.5f} vs AvgRange {avg_range:.5f})"
            )
        else:
            reasons.append("Volatility filter: SKIPPED (avg_range not provided)")

        all_ok = trend_ok and vwap_ok and body_ok and volatility_ok
        return all_ok, reasons

    except Exception as e:
        return False, [f"Trade filter error: {str(e)}"]


def wick_strategy(row, pattern):
    bullish = 0
    bearish = 0
    reasons = []

    if row["LowerWick"] > row["UpperWick"] * 1.2:
        bullish += 1
        reasons.append("Lower wick dominant")
    elif row["UpperWick"] > row["LowerWick"] * 1.2:
        bearish += 1
        reasons.append("Upper wick dominant")

    if pattern == "Hammer":
        bullish += 2
        reasons.append("Hammer pattern detected")

    elif pattern == "Shooting Star":
        bearish += 2
        reasons.append("Shooting Star pattern detected")

    elif pattern == "Doji":
        reasons.append("Doji pattern detected")

    elif pattern == "Pin Bar":
        if row["LowerWick"] > row["UpperWick"]:
            bullish += 1
            reasons.append("Bullish Pin Bar detected")
        elif row["UpperWick"] > row["LowerWick"]:
            bearish += 1
            reasons.append("Bearish Pin Bar detected")

    elif pattern == "Bullish Engulfing":
        bullish += 3
        reasons.append("Bullish engulfing pattern detected")

    elif pattern == "Bearish Engulfing":
        bearish += 3
        reasons.append("Bearish engulfing pattern detected")

    return {
        "bullish": bullish,
        "bearish": bearish,
        "reasons": reasons
    }



def detect_engulfing_pattern(df):
    if len(df) < 2:
        return None, 0

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    prev_open = float(prev["Open"])
    prev_close = float(prev["Close"])
    curr_open = float(curr["Open"])
    curr_close = float(curr["Close"])

    prev_body = abs(prev_close - prev_open)
    curr_body = abs(curr_close - curr_open)

    # Avoid division issues
    if prev_body == 0:
        prev_body = 0.0001

    strength = curr_body / prev_body

    prev_bearish = prev_close < prev_open
    prev_bullish = prev_close > prev_open
    curr_bullish = curr_close > curr_open
    curr_bearish = curr_close < curr_open

    prev_low = min(prev_open, prev_close)
    prev_high = max(prev_open, prev_close)
    curr_low = min(curr_open, curr_close)
    curr_high = max(curr_open, curr_close)

    # Weak filter (ignore tiny engulfing)
    if strength < 1.2:
        return None, 0

    # Bullish engulfing
    if prev_bearish and curr_bullish:
        if curr_low <= prev_low and curr_high >= prev_high:
            return "Bullish Engulfing", strength

    # Bearish engulfing
    if prev_bullish and curr_bearish:
        if curr_low <= prev_low and curr_high >= prev_high:
            return "Bearish Engulfing", strength

    return None, 0



def ma_trend_strategy(row):
    bullish = 0
    bearish = 0
    reasons = []

    close_price = float(row["Close"])
    ma20 = float(row["MA20"]) if pd.notna(row["MA20"]) else close_price
    ma50 = float(row["MA50"]) if pd.notna(row["MA50"]) else close_price

    if close_price > ma20:
        bullish += 1
        reasons.append("Price above MA20")
    elif close_price < ma20:
        bearish += 1
        reasons.append("Price below MA20")

    if close_price > ma50:
        bullish += 1
        reasons.append("Price above MA50")
    elif close_price < ma50:
        bearish += 1
        reasons.append("Price below MA50")

    if ma20 > ma50:
        bullish += 1
        reasons.append("MA20 above MA50")
    elif ma20 < ma50:
        bearish += 1
        reasons.append("MA20 below MA50")

    return {"bullish": bullish, "bearish": bearish, "reasons": reasons}


def vwap_strategy(row):
    bullish = 0
    bearish = 0
    reasons = []

    close_price = float(row["Close"])
    vwap = float(row["VWAP"]) if pd.notna(row["VWAP"]) else close_price

    if close_price > vwap:
        bullish += 1
        reasons.append("Price above VWAP")
    elif close_price < vwap:
        bearish += 1
        reasons.append("Price below VWAP")

    return {"bullish": bullish, "bearish": bearish, "reasons": reasons}


def support_resistance_strategy(row):
    bullish = 0
    bearish = 0
    reasons = []

    close_price = float(row["Close"])
    support = float(row["Support"]) if pd.notna(row["Support"]) else float(row["Low"])
    resistance = float(row["Resistance"]) if pd.notna(row["Resistance"]) else float(row["High"])

    support_distance = abs(close_price - support)
    resistance_distance = abs(resistance - close_price)

    if support_distance < resistance_distance:
        bullish += 1
        reasons.append("Closer to support than resistance")
    elif resistance_distance < support_distance:
        bearish += 1
        reasons.append("Closer to resistance than support")

    return {"bullish": bullish, "bearish": bearish, "reasons": reasons}


def breakout_strategy(row):
    bullish = 0
    bearish = 0
    reasons = []
    breakout_label = None

    prev_resistance = row["PrevResistance"]
    prev_support = row["PrevSupport"]
    close_price = float(row["Close"])
    open_price = float(row["Open"])

    if pd.notna(prev_resistance) and close_price > float(prev_resistance) and close_price > open_price:
        bullish += 2
        breakout_label = "Bullish Breakout"
        reasons.append("Closed above previous resistance")

    if pd.notna(prev_support) and close_price < float(prev_support) and close_price < open_price:
        bearish += 2
        breakout_label = "Bearish Breakdown"
        reasons.append("Closed below previous support")

    if pd.notna(prev_resistance) and breakout_label is None:
        if float(row["High"]) > float(prev_resistance) and close_price < float(prev_resistance):
            bearish += 1
            breakout_label = "Failed Bullish Breakout"
            reasons.append("Wick swept above resistance but closed below")

    if pd.notna(prev_support) and breakout_label is None:
        if float(row["Low"]) < float(prev_support) and close_price > float(prev_support):
            bullish += 1
            breakout_label = "Failed Bearish Breakdown"
            reasons.append("Wick swept below support but closed above")

    return {
        "bullish": bullish,
        "bearish": bearish,
        "reasons": reasons,
        "breakout": breakout_label
    }


def liquidity_sweep_strategy(row):
    bullish = 0
    bearish = 0
    reasons = []
    liquidity_event = None

    prev_resistance = row["PrevResistance"]
    prev_support = row["PrevSupport"]
    high_price = float(row["High"])
    low_price = float(row["Low"])
    close_price = float(row["Close"])
    open_price = float(row["Open"])

    if pd.notna(prev_resistance):
        prev_resistance = float(prev_resistance)

        if high_price > prev_resistance and close_price < prev_resistance:
            bearish += 2
            liquidity_event = "Bearish Liquidity Sweep"
            reasons.append("Price swept above resistance and closed back below")
        elif high_price > prev_resistance and close_price > prev_resistance and close_price > open_price:
            bullish += 1
            reasons.append("Resistance sweep held into breakout")

    if pd.notna(prev_support):
        prev_support = float(prev_support)

        if low_price < prev_support and close_price > prev_support:
            bullish += 2
            liquidity_event = "Bullish Liquidity Sweep"
            reasons.append("Price swept below support and closed back above")
        elif low_price < prev_support and close_price < prev_support and close_price < open_price:
            bearish += 1
            reasons.append("Support sweep held into breakdown")

    return {
        "bullish": bullish,
        "bearish": bearish,
        "reasons": reasons,
        "liquidity_event": liquidity_event
    }


def trendline_strategy(df: pd.DataFrame):
    bullish = 0
    bearish = 0
    reasons = []
    trendline_label = None

    recent = df.tail(20)
    swing_lows = recent["SwingLow"].dropna()
    swing_highs = recent["SwingHigh"].dropna()
    last_close = float(recent.iloc[-1]["Close"])

    if len(swing_lows) >= 2:
        last_two_lows = swing_lows.tail(2).values
        if last_two_lows[-1] > last_two_lows[-2]:
            bullish += 1
            trendline_label = "Rising Trendline Support"
            reasons.append("Recent swing lows are rising")
            if abs(last_close - last_two_lows[-1]) / max(last_close, 1) < 0.01:
                bullish += 1
                reasons.append("Price is near rising trendline support")

    if len(swing_highs) >= 2:
        last_two_highs = swing_highs.tail(2).values
        if last_two_highs[-1] < last_two_highs[-2]:
            bearish += 1
            trendline_label = "Falling Trendline Resistance"
            reasons.append("Recent swing highs are falling")
            if abs(last_two_highs[-1] - last_close) / max(last_close, 1) < 0.01:
                bearish += 1
                reasons.append("Price is near falling trendline resistance")

    return {
        "bullish": bullish,
        "bearish": bearish,
        "reasons": reasons,
        "trendline": trendline_label
    }


def evaluate_signal(df):
    df = add_indicators(df)
    latest = df.iloc[-1]

    bullish = 0.0
    bearish = 0.0
    reasons = []

    breakout_label = None
    liquidity_event = None
    trendline_label = None
    confluence_bonus = 0
    strategy_breakdown = {}

    # --- CORE VALUES ---
    upper_wick = float(latest["UpperWick"]) if "UpperWick" in latest and pd.notna(latest["UpperWick"]) else None
    lower_wick = float(latest["LowerWick"]) if "LowerWick" in latest and pd.notna(latest["LowerWick"]) else None
    ma20 = float(latest["MA20"]) if "MA20" in latest and pd.notna(latest["MA20"]) else None
    ma50 = float(latest["MA50"]) if "MA50" in latest and pd.notna(latest["MA50"]) else None
    vwap = float(latest["VWAP"]) if "VWAP" in latest and pd.notna(latest["VWAP"]) else None
    support = float(latest["Support"]) if "Support" in latest and pd.notna(latest["Support"]) else None
    resistance = float(latest["Resistance"]) if "Resistance" in latest and pd.notna(latest["Resistance"]) else None

    # --- PATTERN ---
    pattern_result = detect_wick_pattern(df)
    pattern = pattern_result[0] if isinstance(pattern_result, tuple) else pattern_result

    # -----------------------------
    # STRATEGY EXECUTION
    # -----------------------------
    strategy_functions = [
        ("wick_strategy", wick_strategy, (latest, pattern)),
        ("ma_trend_strategy", ma_trend_strategy, latest),
        ("vwap_strategy", vwap_strategy, latest),
        ("support_resistance_strategy", support_resistance_strategy, latest),
        ("breakout_strategy", breakout_strategy, latest),
        ("liquidity_sweep_strategy", liquidity_sweep_strategy, latest),
        ("trendline_strategy", trendline_strategy, df),
    ]

    for strategy_name, strategy_func, strategy_input in strategy_functions:
        try:
            if isinstance(strategy_input, tuple):
                result = strategy_func(*strategy_input)
            else:
                result = strategy_func(strategy_input)

            if not isinstance(result, dict):
                result = {}

            bullish_points = float(result.get("bullish", 0) or 0)
            bearish_points = float(result.get("bearish", 0) or 0)

            strategy_reasons = result.get("reasons", [])
            if not isinstance(strategy_reasons, list):
                strategy_reasons = [str(strategy_reasons)]

            bullish += bullish_points
            bearish += bearish_points

            if strategy_reasons:
                reasons.extend(strategy_reasons)

            strategy_breakdown[strategy_name] = {
                "bullish": bullish_points,
                "bearish": bearish_points,
                "reasons": strategy_reasons
            }

            if strategy_name == "breakout_strategy":
                breakout_label = result.get("breakout")

            if strategy_name == "liquidity_sweep_strategy":
                liquidity_event = result.get("liquidity_event")

            if strategy_name == "trendline_strategy":
                trendline_label = result.get("trendline")

        except Exception as e:
            error_msg = f"{strategy_name} error: {str(e)}"
            reasons.append(error_msg)
            strategy_breakdown[strategy_name] = {
                "bullish": 0,
                "bearish": 0,
                "reasons": [error_msg]
            }

    # -----------------------------
    # DOJI / INDECISION PENALTY
    # -----------------------------
    if pattern == "Doji":
        bullish *= 0.6
        bearish *= 0.6
        reasons.append("Doji detected - reduced confidence due to market indecision")

    # -----------------------------
    # CONFLUENCE BONUS
    # -----------------------------
    bullish_agreement = 0
    bearish_agreement = 0

    for breakdown in strategy_breakdown.values():
        b = float(breakdown.get("bullish", 0) or 0)
        s = float(breakdown.get("bearish", 0) or 0)

        if b > s and b > 0:
            bullish_agreement += 1
        elif s > b and s > 0:
            bearish_agreement += 1

    if bullish_agreement >= 3 and bullish > bearish:
        bullish += 2
        confluence_bonus = 2
        reasons.append("Bullish confluence bonus applied")

    elif bearish_agreement >= 3 and bearish > bullish:
        bearish += 2
        confluence_bonus = 2
        reasons.append("Bearish confluence bonus applied")

    # -----------------------------
    # MOMENTUM PUSH (ANTI-NEUTRAL BOOST)
    # -----------------------------
    if bullish > bearish:
        bullish += 0.5
    elif bearish > bullish:
        bearish += 0.5

    # -----------------------------
    # SCORE CAP
    # -----------------------------
    bullish = min(bullish, 100)
    bearish = min(bearish, 100)

    # -----------------------------
    # FINAL SIGNAL (UPGRADED)
    # -----------------------------
    total_points = bullish + bearish
    difference = abs(bullish - bearish)

    MIN_DIFFERENCE = 1.5
    MIN_CONFIDENCE = 52

    if bullish > bearish and difference >= MIN_DIFFERENCE:
        confidence = round((bullish / total_points) * 100, 2) if total_points > 0 else 0.0
        signal = "Bullish" if confidence >= MIN_CONFIDENCE else "Neutral"

    elif bearish > bullish and difference >= MIN_DIFFERENCE:
        confidence = round((bearish / total_points) * 100, 2) if total_points > 0 else 0.0
        signal = "Bearish" if confidence >= MIN_CONFIDENCE else "Neutral"

    else:
        signal = "Neutral"
        confidence = 50.0

    return {
        "signal": signal,
        "confidence": confidence,
        "pattern": pattern,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "ma20": ma20,
        "ma50": ma50,
        "vwap": vwap,
        "support": support,
        "resistance": resistance,
        "breakout": breakout_label,
        "liquidity_event": liquidity_event,
        "trendline": trendline_label,
        "strategy_breakdown": strategy_breakdown,
        "confluence_bonus": confluence_bonus,
        "bullish_points": bullish,
        "bearish_points": bearish,
        "reasons": reasons
    }



def evaluate_signal_from_market(market: str, timeframe: str, outputsize: int = 30, user_id: str = None):
    normalized_timeframe = normalize_interval(timeframe)
    df = fetch_live_market_data(market, interval=normalized_timeframe, outputsize=outputsize)
    signal_data = evaluate_signal(df)
    last_row = df.iloc[-1]

    final_signal = {
        "market": market,
        "timeframe": normalized_timeframe,
        "signal": signal_data["signal"],
        "confidence": signal_data["confidence"],
        "pattern": signal_data["pattern"],
        "entry": float(last_row["Close"]),
        "open": float(last_row["Open"]),
        "high": float(last_row["High"]),
        "low": float(last_row["Low"]),
        "close": float(last_row["Close"]),
        "upper_wick": signal_data["upper_wick"],
        "lower_wick": signal_data["lower_wick"],
        "ma20": signal_data["ma20"],
        "ma50": signal_data["ma50"],
        "vwap": signal_data["vwap"],
        "support": signal_data["support"],
        "resistance": signal_data["resistance"],
        "breakout": signal_data["breakout"],
        "liquidity_event": signal_data["liquidity_event"],
        "trendline": signal_data["trendline"],
        "strategy_breakdown": signal_data["strategy_breakdown"],
        "confluence_bonus": signal_data["confluence_bonus"],
        "reason": ", ".join(signal_data["reasons"])
    }

    if user_id:
        store_signal(user_id, final_signal)

    return final_signal



def get_multi_timeframe_confirmation(market, base_timeframe):
    try:
        timeframes = ["1h", "4h"]
        results = {}

        for tf in timeframes:
            try:
                df = fetch_live_market_data(
                    market,
                    interval=tf,
                    outputsize=50
                )

                if df is None or df.empty:
                    results[tf] = {"error": "No data returned"}
                    continue

                # -----------------------------
                # FORCE CLEAN NUMERIC DATA
                # -----------------------------
                required_cols = ["Open", "High", "Low", "Close"]

                for col in required_cols:
                    if col not in df.columns:
                        results[tf] = {"error": f"Missing column: {col}"}
                        continue

                    df[col] = df[col].astype(str).str.replace(",", "", regex=False).str.strip()
                    df[col] = pd.to_numeric(df[col], errors="coerce")

                df = df.dropna(subset=required_cols).copy()

                if df.empty:
                    results[tf] = {"error": "No valid numeric data after cleaning"}
                    continue

                # -----------------------------
                # RUN SIGNAL ENGINE
                # -----------------------------
                signal_data = evaluate_signal(df)

                results[tf] = {
                    "signal": signal_data.get("signal"),
                    "confidence": signal_data.get("confidence"),
                    "bias": signal_data.get("signal")
                }

            except Exception as tf_error:
                results[tf] = {"error": str(tf_error)}

        # -----------------------------
        # DETERMINE ALIGNMENT
        # -----------------------------
        valid_signals = [
            v.get("signal") for v in results.values()
            if isinstance(v, dict) and v.get("signal")
        ]

        if len(valid_signals) >= 2:
            if all(s == "Bullish" for s in valid_signals):
                alignment = "Strong Bullish Alignment"
            elif all(s == "Bearish" for s in valid_signals):
                alignment = "Strong Bearish Alignment"
            else:
                alignment = "Mixed / Neutral"
        else:
            alignment = "Insufficient Data"

        # -----------------------------
        # HIGHER TIMEFRAME BIAS
        # -----------------------------
        higher_bias = results.get("4h", {}).get("signal", "Neutral")

        return {
            "multi_timeframe": results,
            "higher_timeframe_bias": higher_bias,
            "timeframe_alignment": alignment
        }

    except Exception as e:
        return {
            "multi_timeframe": {},
            "higher_timeframe_bias": "Unknown",
            "timeframe_alignment": "Error",
            "error": str(e)
        }


def build_ai_summary(signal_data):
    signal = signal_data.get("signal")
    confidence = safe_float(signal_data.get("confidence"), 0)
    pattern = signal_data.get("pattern")
    breakout = signal_data.get("breakout")
    liquidity = signal_data.get("liquidity_event")
    trendline = signal_data.get("trendline")

    bias = "bullish" if signal in ["BUY", "Bullish"] else "bearish" if signal in ["SELL", "Bearish"] else "neutral"

    drivers = []
    if pattern:
        drivers.append(pattern)
    if breakout:
        drivers.append("breakout")
    if liquidity:
        drivers.append("liquidity sweep")
    if trendline:
        drivers.append("trendline respect")

    if not drivers:
        drivers.append("price structure")

    if confidence >= 85:
        strength = "strong"
    elif confidence >= 70:
        strength = "moderate"
    else:
        strength = "developing"

    if signal in ["BUY", "Bullish"]:
        expectation = "upside continuation"
    elif signal in ["SELL", "Bearish"]:
        expectation = "downside continuation"
    else:
        expectation = "range-bound movement"

    summary = f"{strength.capitalize()} {bias} pressure driven by {', '.join(drivers)}. Expect {expectation}."
    return summary


def build_trade_thesis(signal_data):
    signal = signal_data.get("signal")

    if signal in ["BUY", "Bullish"]:
        return "Buyers are defending key levels and pushing price higher. Momentum favors continuation."
    elif signal in ["SELL", "Bearish"]:
        return "Sellers are controlling price action with repeated rejection. Momentum favors downside."
    else:
        return "Market lacks clear directional control. Waiting for confirmation is preferred."


def get_entry_timing(signal_data):
    signal = str(signal_data.get("signal", "")).upper()
    confidence = safe_float(signal_data.get("confidence"), 0)
    breakout = signal_data.get("breakout")
    liquidity = signal_data.get("liquidity_event")
    trendline = signal_data.get("trendline")
    pattern = signal_data.get("pattern")
    readiness = safe_float(signal_data.get("trade_readiness_score"), 0)

    close_price = safe_float(signal_data.get("close"), 0)
    support = safe_float(signal_data.get("support"), 0)
    resistance = safe_float(signal_data.get("resistance"), 0)

    # Distance checks (~1% proximity)
    near_support = support > 0 and abs(close_price - support) / max(close_price, 1) < 0.01
    near_resistance = resistance > 0 and abs(close_price - resistance) / max(close_price, 1) < 0.01

    # =========================
    # BULLISH LOGIC
    # =========================
    if signal in ["BUY", "BULLISH"]:
        # Strong actionable conditions
        if confidence >= 80 and readiness >= 60:
            if breakout == "Bullish Breakout":
                return "ENTER NOW"

            if trendline == "Rising Trendline Support" and near_support:
                return "ENTER NOW"

            if pattern in ["Hammer", "Pin Bar", "Bullish Engulfing"] and near_support:
                return "ENTER NOW"

            if liquidity == "Bullish Liquidity Sweep":
                return "ENTER NOW"

        # Medium readiness setup
        if confidence >= 65 or readiness >= 40:
            return "WAIT"

        return "AVOID"

    # =========================
    # BEARISH LOGIC
    # =========================
    if signal in ["SELL", "BEARISH"]:
        # Strong actionable conditions
        if confidence >= 80 and readiness >= 60:
            if breakout == "Bearish Breakdown":
                return "ENTER NOW"

            if trendline == "Falling Trendline Resistance" and near_resistance:
                return "ENTER NOW"

            if pattern in ["Shooting Star", "Pin Bar", "Bearish Engulfing"] and near_resistance:
                return "ENTER NOW"

            if liquidity == "Bearish Liquidity Sweep":
                return "ENTER NOW"

        # Medium readiness setup
        if confidence >= 65 or readiness >= 40:
            return "WAIT"

        return "AVOID"

    # =========================
    # DEFAULT
    # =========================
    return "AVOID"


def get_trade_readiness(signal_data):
    try:
        if not isinstance(signal_data, dict):
            return 0

        score = 0

        signal = str(signal_data.get("signal", "")).upper()
        confidence = safe_float(signal_data.get("confidence"), 0)

        pattern = signal_data.get("pattern")
        breakout = signal_data.get("breakout")
        liquidity_event = signal_data.get("liquidity_event")
        trendline = signal_data.get("trendline")
        setup_type = signal_data.get("setup_type")

        support = signal_data.get("support")
        resistance = signal_data.get("resistance")

        # Directional signal
        if signal in ["BUY", "SELL", "BULLISH", "BEARISH"]:
            score += 20

        # Confidence strength
        if confidence >= 90:
            score += 25
        elif confidence >= 80:
            score += 20
        elif confidence >= 70:
            score += 15
        elif confidence >= 60:
            score += 10
        elif confidence >= 50:
            score += 5

        # Strategy confirmations
        if pattern:
            score += 10

        if breakout:
            score += 15

        if liquidity_event:
            score += 15

        if trendline:
            score += 10

        if setup_type:
            score += 10

        # Market structure
        if support:
            score += 5

        if resistance:
            score += 5

        return round(max(0, min(score, 100)), 2)

    except Exception as e:
        print(f"❌ get_trade_readiness error: {e}", flush=True)
        return 0



def get_execution_guidance(entry_timing, signal):
    signal_text = str(signal).upper() if signal else "TRADE"

    if entry_timing == "ENTER NOW":
        return f"{signal_text} conditions are aligned. Consider entering with proper risk management."
    elif entry_timing == "WAIT":
        return f"Wait for stronger confirmation before acting on this {signal_text.lower()} setup."
    elif entry_timing == "AVOID":
        return f"Avoid this setup for now. Conditions are not aligned."
    else:
        return "Wait for clearer confirmation before acting."


def build_ai_explanation(signal):
    signal_type = signal.get("signal", "Neutral")
    confidence = signal.get("confidence", 0)
    pattern = signal.get("pattern")
    breakout = signal.get("breakout")
    liquidity_event = signal.get("liquidity_event")
    trendline = signal.get("trendline")
    support = signal.get("support")
    resistance = signal.get("resistance")
    confluence_bonus = signal.get("confluence_bonus", 0)

    summary_parts = []

    if signal_type == "Bullish":
        summary_parts.append("market conditions lean bullish")
    elif signal_type == "Bearish":
        summary_parts.append("market conditions lean bearish")
    else:
        summary_parts.append("market conditions are neutral")

    if confidence >= 85:
        summary_parts.append("with very strong conviction")
    elif confidence >= 70:
        summary_parts.append("with solid confirmation")
    else:
        summary_parts.append("with moderate confirmation")

    if pattern:
        summary_parts.append(f"while printing a {pattern} pattern")

    if breakout:
        summary_parts.append(f"and showing {breakout.lower()} behavior")

    ai_summary = " ".join(summary_parts) + "."

    thesis_parts = []

    if signal_type == "Bullish":
        thesis_parts.append("Buyers appear to be in control of the current structure")
    elif signal_type == "Bearish":
        thesis_parts.append("Sellers appear to be in control of the current structure")
    else:
        thesis_parts.append("The market is still waiting for clearer directional control")

    if pattern == "Hammer":
        thesis_parts.append("The hammer suggests buyers stepped in aggressively after lower prices were rejected")
    elif pattern == "Shooting Star":
        thesis_parts.append("The shooting star suggests higher prices were rejected and sellers responded near the highs")
    elif pattern == "Doji":
        thesis_parts.append("The doji reflects hesitation and temporary balance between buyers and sellers")
    elif pattern == "Pin Bar":
        thesis_parts.append("The pin bar suggests rejection from an important price area and may signal reversal or continuation")

    if breakout == "Bullish Breakout":
        thesis_parts.append("A bullish breakout suggests momentum is expanding above resistance")
    elif breakout == "Bearish Breakdown":
        thesis_parts.append("A bearish breakdown suggests momentum is expanding below support")
    elif breakout == "Failed Bullish Breakout":
        thesis_parts.append("The failed breakout above resistance suggests a possible bull trap and downside pressure")
    elif breakout == "Failed Bearish Breakdown":
        thesis_parts.append("The failed breakdown below support suggests a possible bear trap and upside recovery")

    if liquidity_event == "Bullish Liquidity Sweep":
        thesis_parts.append("The bullish liquidity sweep suggests stops below support were taken before buyers reclaimed control")
    elif liquidity_event == "Bearish Liquidity Sweep":
        thesis_parts.append("The bearish liquidity sweep suggests stops above resistance were taken before sellers regained control")

    if trendline == "Rising Trendline Support":
        thesis_parts.append("Price is reacting near rising trendline support, which may act as a continuation zone for buyers")
    elif trendline == "Falling Trendline Resistance":
        thesis_parts.append("Price is reacting near falling trendline resistance, which may act as a rejection zone for sellers")

    if confluence_bonus >= 4:
        thesis_parts.append("Multiple technical factors are aligned, which strengthens the overall setup quality")
    elif confluence_bonus >= 2:
        thesis_parts.append("There is meaningful confluence supporting the setup")
    else:
        thesis_parts.append("The setup is present, but broader confluence is still limited")

    trade_thesis = " ".join(thesis_parts) + "."

    if signal_type == "Bullish":
        risk_note = (
            f"Main risk: if price loses support near {support} and fails to hold the bullish structure, the setup may weaken quickly."
        )
    elif signal_type == "Bearish":
        risk_note = (
            f"Main risk: if price reclaims resistance near {resistance} and invalidates the bearish structure, downside momentum may fade."
        )
    else:
        risk_note = (
            "Main risk: the market is still mixed, so waiting for stronger confirmation may reduce false signals."
        )

    return {
        "ai_summary": ai_summary,
        "trade_thesis": trade_thesis,
        "risk_note": risk_note
    }


def get_setup_type(signal_data):
    signal_type = signal_data.get("signal", "Neutral")
    breakout = signal_data.get("breakout")
    trendline = signal_data.get("trendline")
    pattern = signal_data.get("pattern")
    confidence = safe_float(signal_data.get("confidence"), 0.0)
    liquidity_event = signal_data.get("liquidity_event")

    if signal_type in ["BUY", "Bullish"]:
        if breakout == "Bullish Breakout":
            return "Bullish Breakout Continuation"
        elif breakout == "Failed Bearish Breakdown":
            return "Bullish Failed Breakdown Reversal"
        elif trendline == "Rising Trendline Support":
            return "Bullish Trendline Bounce"
        elif pattern == "Hammer":
            return "Bullish Hammer Reversal"
        elif pattern == "Pin Bar":
            return "Bullish Pin Bar Setup"
        elif liquidity_event == "Bullish Liquidity Sweep":
            return "Bullish Liquidity Sweep Reversal"
        elif confidence >= 80:
            return "Bullish Momentum Setup"
        else:
            return "Bullish Confluence Setup"

    if signal_type in ["SELL", "Bearish"]:
        if breakout == "Bearish Breakdown":
            return "Bearish Breakdown Continuation"
        elif breakout == "Failed Bullish Breakout":
            return "Bearish Failed Breakout Reversal"
        elif trendline == "Falling Trendline Resistance":
            return "Bearish Trendline Rejection"
        elif pattern == "Shooting Star":
            return "Bearish Shooting Star Reversal"
        elif pattern == "Pin Bar":
            return "Bearish Pin Bar Setup"
        elif liquidity_event == "Bearish Liquidity Sweep":
            return "Bearish Liquidity Sweep Reversal"
        elif confidence >= 80:
            return "Bearish Momentum Setup"
        else:
            return "Bearish Confluence Setup"

    return "Neutral / No Clear Setup"




def build_strategy_engine_output(df: pd.DataFrame, signal_data: dict):
    df = add_indicators(df.copy())
    recent = df.tail(20)

    support_candidates = recent["Low"].nsmallest(3).tolist()
    resistance_candidates = recent["High"].nlargest(3).tolist()

    support_levels = sorted(list({round(float(x), 4) for x in support_candidates}))
    resistance_levels = sorted(list({round(float(x), 4) for x in resistance_candidates}), reverse=True)

    signal = signal_data.get("signal", "Neutral")
    breakout = signal_data.get("breakout")
    liquidity_event = signal_data.get("liquidity_event")
    trendline = signal_data.get("trendline")
    pattern = signal_data.get("pattern")
    confidence = safe_float(signal_data.get("confidence"), 0.0)

    strategy_recommendation = "No Clear Setup"
    strategy_reason = "Market conditions are mixed."
    suggested_action = "Wait for stronger confirmation."

    if breakout == "Bullish Breakout":
        strategy_recommendation = "Breakout"
        strategy_reason = "Price is breaking above resistance with bullish confirmation."
        suggested_action = "Wait for a breakout hold or retest above resistance, then look for a long entry."
    elif breakout == "Bearish Breakdown":
        strategy_recommendation = "Breakout"
        strategy_reason = "Price is breaking below support with bearish confirmation."
        suggested_action = "Wait for a breakdown hold or retest below support, then look for a short entry."
    elif trendline == "Rising Trendline Support" and signal == "Bullish":
        strategy_recommendation = "Trend Continuation"
        strategy_reason = "Bullish structure is holding near rising trendline support."
        suggested_action = "Look for continuation entries on trendline support reactions."
    elif trendline == "Falling Trendline Resistance" and signal == "Bearish":
        strategy_recommendation = "Trend Continuation"
        strategy_reason = "Bearish structure is holding near falling trendline resistance."
        suggested_action = "Look for continuation entries on trendline resistance rejection."
    elif liquidity_event == "Bullish Liquidity Sweep":
        strategy_recommendation = "Reversal"
        strategy_reason = "Liquidity below support was swept and buyers reclaimed price."
        suggested_action = "Look for long entries if reclaimed support continues to hold."
    elif liquidity_event == "Bearish Liquidity Sweep":
        strategy_recommendation = "Reversal"
        strategy_reason = "Liquidity above resistance was swept and sellers pushed price back down."
        suggested_action = "Look for short entries if reclaimed resistance continues to reject price."
    elif pattern in ["Hammer", "Shooting Star", "Pin Bar"] and confidence >= 70:
        strategy_recommendation = "Reversal"
        strategy_reason = f"{pattern} pattern suggests rejection from an important price area."
        suggested_action = "Wait for confirmation on the next candle before entering."
    elif signal in ["Bullish", "Bearish", "BUY", "SELL"] and confidence >= 65:
        strategy_recommendation = "Range Trade"
        strategy_reason = "Market is showing directional bias near a key support/resistance region."
        suggested_action = "Trade toward the next key level with defined risk."

    return {
        "support_levels": support_levels,
        "resistance_levels": resistance_levels,
        "strategy_recommendation": strategy_recommendation,
        "strategy_reason": strategy_reason,
        "suggested_action": suggested_action
    }


def build_strategy_visual_output(df: pd.DataFrame, signal_data: dict):
    df = add_indicators(df.copy())
    recent = df.tail(20).reset_index(drop=True)

    trendline_points = []
    breakout_zone = None
    entry_zone = None
    strategy_visual_bias = "neutral"

    swing_lows = []
    swing_highs = []

    for idx, row in recent.iterrows():
        if pd.notna(row.get("SwingLow")):
            swing_lows.append({
                "x": int(idx),
                "y": round(float(row["SwingLow"]), 4)
            })
        if pd.notna(row.get("SwingHigh")):
            swing_highs.append({
                "x": int(idx),
                "y": round(float(row["SwingHigh"]), 4)
            })

    trendline = signal_data.get("trendline")
    breakout = signal_data.get("breakout")
    signal = signal_data.get("signal", "Neutral")

    if trendline == "Rising Trendline Support" and len(swing_lows) >= 2:
        trendline_points = [swing_lows[-2], swing_lows[-1]]
        strategy_visual_bias = "bullish"
    elif trendline == "Falling Trendline Resistance" and len(swing_highs) >= 2:
        trendline_points = [swing_highs[-2], swing_highs[-1]]
        strategy_visual_bias = "bearish"

    latest_close = round(float(recent.iloc[-1]["Close"]), 4)
    latest_support = round(float(recent.iloc[-1]["Support"]), 4) if pd.notna(recent.iloc[-1]["Support"]) else latest_close
    latest_resistance = round(float(recent.iloc[-1]["Resistance"]), 4) if pd.notna(recent.iloc[-1]["Resistance"]) else latest_close

    if breakout == "Bullish Breakout":
        breakout_zone = {
            "type": "bullish_breakout",
            "price": latest_resistance,
            "top": round(latest_resistance * 1.002, 4),
            "bottom": round(latest_resistance * 0.998, 4)
        }
        entry_zone = {
            "type": "bullish_retest_zone",
            "top": round(latest_resistance * 1.001, 4),
            "bottom": round(latest_resistance * 0.999, 4)
        }
        strategy_visual_bias = "bullish"
    elif breakout == "Bearish Breakdown":
        breakout_zone = {
            "type": "bearish_breakdown",
            "price": latest_support,
            "top": round(latest_support * 1.002, 4),
            "bottom": round(latest_support * 0.998, 4)
        }
        entry_zone = {
            "type": "bearish_retest_zone",
            "top": round(latest_support * 1.001, 4),
            "bottom": round(latest_support * 0.999, 4)
        }
        strategy_visual_bias = "bearish"
    else:
        if signal in ["Bullish", "BUY"]:
            entry_zone = {
                "type": "bullish_entry_zone",
                "top": round(latest_support * 1.003, 4),
                "bottom": round(latest_support * 0.999, 4)
            }
            strategy_visual_bias = "bullish"
        elif signal in ["Bearish", "SELL"]:
            entry_zone = {
                "type": "bearish_entry_zone",
                "top": round(latest_resistance * 1.001, 4),
                "bottom": round(latest_resistance * 0.997, 4)
            }
            strategy_visual_bias = "bearish"

    return {
        "trendline_points": trendline_points,
        "breakout_zone": breakout_zone,
        "entry_zone": entry_zone,
        "strategy_visual_bias": strategy_visual_bias
    }


def build_strategy_timing_output(df: pd.DataFrame, signal_data: dict):
    df = add_indicators(df.copy())
    recent = df.tail(5)

    signal = signal_data.get("signal", "Neutral")
    confidence = safe_float(signal_data.get("confidence"), 0.0)
    breakout = signal_data.get("breakout")
    liquidity_event = signal_data.get("liquidity_event")

    last = recent.iloc[-1]
    prev = recent.iloc[-2] if len(recent) > 1 else last

    close = safe_float(last.get("Close"))
    prev_close = safe_float(prev.get("Close"))

    entry_timing = "Wait"
    confirmation_state = "Weak"
    execution_guidance = "Wait for a clearer setup."
    trade_readiness_score = 50

    if confidence >= 80:
        confirmation_state = "Confirmed"
        trade_readiness_score += 25
    elif confidence >= 65:
        confirmation_state = "Partial"
        trade_readiness_score += 10

    if signal in ["BUY", "Bullish"] and close > prev_close:
        trade_readiness_score += 10
    elif signal in ["SELL", "Bearish"] and close < prev_close:
        trade_readiness_score += 10

    if breakout == "Bullish Breakout":
        entry_timing = "Wait for Retest"
        execution_guidance = "Wait for price to retest breakout level before entering long."
        trade_readiness_score += 10
    elif breakout == "Bearish Breakdown":
        entry_timing = "Wait for Retest"
        execution_guidance = "Wait for price to retest breakdown level before entering short."
        trade_readiness_score += 10
    elif liquidity_event == "Bullish Liquidity Sweep":
        entry_timing = "Wait for Confirmation"
        execution_guidance = "Wait for bullish confirmation after liquidity sweep before entering."
    elif liquidity_event == "Bearish Liquidity Sweep":
        entry_timing = "Wait for Confirmation"
        execution_guidance = "Wait for bearish confirmation after liquidity sweep before entering."
    elif confidence >= 85 and signal in ["BUY", "SELL", "Bullish", "Bearish"]:
        entry_timing = "Enter Now"
        execution_guidance = "Conditions are strong. Consider entering with proper risk management."
        trade_readiness_score += 15

    if confidence < 55:
        entry_timing = "Avoid Trade"
        execution_guidance = "Low confidence setup. Avoid trading."
        trade_readiness_score -= 20

    trade_readiness_score = max(0, min(100, trade_readiness_score))

    return {
        "entry_timing": entry_timing,
        "confirmation_state": confirmation_state,
        "trade_readiness_score": trade_readiness_score,
        "execution_guidance": execution_guidance
    }

def send_signal_email(
    market,
    signal,
    confidence,
    reason,
    entry,
    pattern=None,
    setup_type=None,
    ai_summary=None,
    trade_thesis=None,
    risk_note=None
):
    sender_email = os.environ.get("ALERT_FROM_EMAIL")
    recipient_email = os.environ.get("ALERT_TO_EMAIL")
    sendgrid_api_key = os.environ.get("SENDGRID_API_KEY")

    print("DEBUG EMAIL CONFIG:")
    print("ALERT_FROM_EMAIL =", sender_email)
    print("ALERT_TO_EMAIL =", recipient_email)
    print("SENDGRID_API_KEY exists =", bool(sendgrid_api_key))

    if not sender_email or not recipient_email or not sendgrid_api_key:
        print("Email alert skipped: missing ALERT_FROM_EMAIL, ALERT_TO_EMAIL, or SENDGRID_API_KEY")
        return

    subject = f"WickSense Alert: {market} {signal}"

    html_content = f"""
    <html>
      <body>
        <h2>WickSense Signal Alert</h2>
        <p><strong>Market:</strong> {market}</p>
        <p><strong>Signal:</strong> {signal}</p>
        <p><strong>Setup Type:</strong> {setup_type or 'N/A'}</p>
        <p><strong>Confidence:</strong> {confidence}%</p>
        <p><strong>Entry:</strong> {entry}</p>
        <p><strong>Pattern:</strong> {pattern or 'None'}</p>
        <p><strong>Reason:</strong> {reason}</p>
        <hr>
        <p><strong>AI Summary:</strong> {ai_summary or 'N/A'}</p>
        <p><strong>Trade Thesis:</strong> {trade_thesis or 'N/A'}</p>
        <p><strong>Risk Note:</strong> {risk_note or 'N/A'}</p>
      </body>
    </html>
    """

    message = Mail(
        from_email=sender_email,
        to_emails=recipient_email,
        subject=subject,
        html_content=html_content
    )

    try:
        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        print(f"Email sent: status={response.status_code}")
    except Exception as e:
        print("Email failed:", str(e))


def does_result_match_rule(result, rule):
    if not rule.get("is_enabled", True):
        return False

    if rule.get("market") and result.get("market") != rule.get("market"):
        return False

    if rule.get("signal") and result.get("signal") != rule.get("signal"):
        return False

    if rule.get("setup_type") and result.get("setup_type") != rule.get("setup_type"):
        return False

    minimum_confidence = rule.get("minimum_confidence")
    if minimum_confidence is not None:
        try:
            if float(result.get("confidence", 0)) < float(minimum_confidence):
                return False
        except Exception:
            return False

    if rule.get("require_breakout") and not result.get("breakout"):
        return False

    if rule.get("require_liquidity_event") and not result.get("liquidity_event"):
        return False

    if rule.get("require_trendline") and not result.get("trendline"):
        return False

    return True


def scan_markets():
    markets = [
        "NASDAQ",
        "Gold",
        "Forex"
    ]

    scan_results = []
    approved_trades = []
    signals = []
    session_data = get_market_session()

    for market in markets:
        try:
            df = fetch_live_market_data(market, "15min", 15)
            signal_data = evaluate_signal(df)
            ai_text = build_ai_explanation(signal_data)
            setup_type = get_setup_type(signal_data)
            last_row = df.iloc[-1]

            reason_text = ", ".join(signal_data.get("reasons", []))
            entry_price = float(last_row["Close"])
            signal_direction = signal_data.get("signal", "Neutral")

            if signal_direction == "Bullish":
                direction = "BUY"
                stop_loss = round(entry_price * 0.9975, 5)
                take_profit = round(entry_price * 1.0050, 5)
            elif signal_direction == "Bearish":
                direction = "SELL"
                stop_loss = round(entry_price * 1.0025, 5)
                take_profit = round(entry_price * 0.9950, 5)
            else:
                direction = "WAIT"
                stop_loss = None
                take_profit = None

            approved = (
                direction in ["BUY", "SELL"]
                and entry_price > 0
                and stop_loss is not None
                and take_profit is not None
            )

            opportunity_score = (
                float(signal_data.get("confidence", 0))
                + float(signal_data.get("confluence_bonus", 0)) * 5
                + (10 if signal_data.get("breakout") else 0)
                + (5 if signal_data.get("trendline") else 0)
                + (5 if signal_data.get("liquidity_event") else 0)
            )

            result = {
                "market": market,
                "signal": signal_direction,
                "direction": direction,
                "setup_type": setup_type,
                "confidence": float(signal_data.get("confidence", 0)),
                "opportunity_score": opportunity_score,

                "entry": entry_price,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,

                "approved": approved,
                "trade_status": "READY" if approved else "SIGNAL_ONLY",
                "block_reason": None if approved else "MISSING_RISK_LEVELS",

                "strategy_id": "backend_original_v1",
                "strategy_name": "Backend Original Strategy",
                "strategy_version": "1.0.0",
                "timeframe": "15min",

                "reason": reason_text,
                "entry_reason": reason_text,
                "pattern": signal_data.get("pattern"),
                "breakout": signal_data.get("breakout"),
                "liquidity_event": signal_data.get("liquidity_event"),
                "trendline": signal_data.get("trendline"),
                "strategy_breakdown": signal_data.get("strategy_breakdown"),

                "ai_summary": ai_text.get("ai_summary"),
                "trade_thesis": ai_text.get("trade_thesis"),
                "risk_note": ai_text.get("risk_note"),

                "session_label": session_data.get("session_label"),
                "active_sessions": session_data.get("active_sessions"),
                "liquidity_profile": session_data.get("liquidity_profile")
            }

            scan_results.append(result)
            signals.append(result)

            if approved:
                approved_trades.append(result)

            risk_settings = load_risk_settings()
            rules = load_alert_rules()

            minimum_confidence_threshold = float(
                risk_settings.get("min_confidence_threshold", 70.0)
            )

            block_low_quality_setups = bool(
                risk_settings.get("block_low_quality_setups", False)
            )

            if float(result.get("confidence", 0)) < minimum_confidence_threshold:
                matching_rules = []
            else:
                matching_rules = [
                    rule for rule in rules
                    if does_result_match_rule(result, rule)
                ]

            if block_low_quality_setups and result.get("setup_type") in [
                "Bullish Confluence Setup",
                "Bearish Confluence Setup"
            ]:
                matching_rules = []

            for rule in matching_rules:
                if not should_send_alert(rule, result):
                    print(f"Cooldown active for rule {rule.get('name')} on {market}")
                    continue

                print(f"Alert rule matched for {market}: {rule.get('name')}")

                try:
                    send_signal_email(
                        market=market,
                        signal=signal_direction,
                        confidence=result.get("confidence"),
                        reason=reason_text,
                        entry=entry_price,
                        pattern=result.get("pattern"),
                        setup_type=setup_type,
                        ai_summary=result.get("ai_summary"),
                        trade_thesis=result.get("trade_thesis"),
                        risk_note=result.get("risk_note")
                    )

                    record_alert_sent(rule, result)

                    create_notification({
                        "type": "alert_triggered",
                        "market": result.get("market"),
                        "signal": result.get("signal"),
                        "setup_type": result.get("setup_type"),
                        "confidence": result.get("confidence"),
                        "rule_name": rule.get("name")
                    })

                except Exception as email_error:
                    print(f"Email error for {market}: {email_error}")

        except Exception as e:
            print(f"Scan error for {market}: {e}")
            scan_results.append({
                "market": market,
                "error": str(e)
            })

    valid_results = [r for r in scan_results if "error" not in r]

    bullish_results = [r for r in valid_results if r.get("signal") == "Bullish"]
    bearish_results = [r for r in valid_results if r.get("signal") == "Bearish"]
    breakout_results = [r for r in valid_results if r.get("breakout") is not None]
    trendline_results = [r for r in valid_results if r.get("trendline") is not None]

    bullish_results = sorted(
        bullish_results,
        key=lambda x: x.get("opportunity_score", 0),
        reverse=True
    )

    bearish_results = sorted(
        bearish_results,
        key=lambda x: x.get("opportunity_score", 0),
        reverse=True
    )

    breakout_results = sorted(
        breakout_results,
        key=lambda x: x.get("opportunity_score", 0),
        reverse=True
    )

    trendline_results = sorted(
        trendline_results,
        key=lambda x: x.get("opportunity_score", 0),
        reverse=True
    )

    all_results_sorted = sorted(
        valid_results,
        key=lambda x: x.get("opportunity_score", 0),
        reverse=True
    )

    return {
        "status": "scan completed",
        "signals": signals,
        "approved_trades": approved_trades,
        "top_overall": all_results_sorted[0] if all_results_sorted else None,
        "top_bullish": bullish_results[0] if bullish_results else None,
        "top_bearish": bearish_results[0] if bearish_results else None,
        "top_breakout": breakout_results[0] if breakout_results else None,
        "top_trendline": trendline_results[0] if trendline_results else None,
        "all_results_sorted": all_results_sorted,
        "raw_results": scan_results
    }


def build_market_intelligence(scan_results):
    all_results = scan_results.get("all_results_sorted", []) or []
    session_data = get_market_session()

    if not all_results:
        return {
            "market_bias": "Neutral",
            "risk_environment": "Unknown",
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "top_opportunity": None,
            "ai_market_summary": "No scanner results are available yet.",
            "what_matters_now": "Run a market scan to generate intelligence.",
            "session_label": session_data["session_label"],
            "active_sessions": session_data["active_sessions"],
            "liquidity_profile": session_data["liquidity_profile"],
            "utc_hour": session_data["utc_hour"]
        }

    bullish_count = len([r for r in all_results if r.get("signal") == "Bullish"])
    bearish_count = len([r for r in all_results if r.get("signal") == "Bearish"])
    neutral_count = len([r for r in all_results if r.get("signal") == "Neutral"])

    avg_confidence = round(
        sum(float(r.get("confidence", 0)) for r in all_results) / len(all_results),
        2
    ) if all_results else 0.0

    if bullish_count > bearish_count:
        market_bias = "Bullish"
    elif bearish_count > bullish_count:
        market_bias = "Bearish"
    else:
        market_bias = "Neutral"

    if avg_confidence >= 80:
        risk_environment = "High Conviction"
    elif avg_confidence >= 65:
        risk_environment = "Moderate Conviction"
    else:
        risk_environment = "Low Conviction"

    top_opportunity = all_results[0] if all_results else None

    summary_parts = []

    if market_bias == "Bullish":
        summary_parts.append("Scanner conditions currently lean bullish across tracked markets")
    elif market_bias == "Bearish":
        summary_parts.append("Scanner conditions currently lean bearish across tracked markets")
    else:
        summary_parts.append("Scanner conditions are currently mixed with no dominant directional bias")

    summary_parts.append(
        f"with an average confidence of {avg_confidence}% across {len(all_results)} scanned opportunities"
    )

    if top_opportunity:
        top_market = top_opportunity.get("market", "Unknown")
        top_signal = top_opportunity.get("signal", "Unknown")
        top_setup = top_opportunity.get("setup_type", "Unknown setup")
        top_conf = top_opportunity.get("confidence", 0)

        summary_parts.append(
            f"The strongest current opportunity is {top_market} with a {top_signal} signal on a {top_setup} at {top_conf}% confidence"
        )

    ai_market_summary = ". ".join(summary_parts) + "."

    if top_opportunity:
        what_matters_now = (
            f"Focus on {top_opportunity.get('market', 'the top market')} because it currently has the strongest "
            f"{top_opportunity.get('signal', 'directional')} setup, labeled as "
            f"{top_opportunity.get('setup_type', 'a key setup')}, with "
            f"{top_opportunity.get('confidence', 0)}% confidence."
        )
    else:
        what_matters_now = "No standout opportunity is available yet."

    return {
        "market_bias": market_bias,
        "risk_environment": risk_environment,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": neutral_count,
        "average_confidence": avg_confidence,
        "top_opportunity": top_opportunity,
        "ai_market_summary": ai_market_summary,
        "what_matters_now": what_matters_now,
        "session_label": session_data["session_label"],
        "active_sessions": session_data["active_sessions"],
        "liquidity_profile": session_data["liquidity_profile"],
        "utc_hour": session_data["utc_hour"]
    }


def build_market_script(intelligence):
    market_bias = intelligence.get("market_bias", "Neutral")
    risk_environment = intelligence.get("risk_environment", "Unknown")
    avg_confidence = intelligence.get("average_confidence", 0)
    top_opportunity = intelligence.get("top_opportunity") or {}
    ai_market_summary = intelligence.get("ai_market_summary", "")
    what_matters_now = intelligence.get("what_matters_now", "")

    top_market = top_opportunity.get("market", "the market")
    top_signal = top_opportunity.get("signal", "Neutral")
    top_setup = top_opportunity.get("setup_type", "key setup")
    top_confidence = top_opportunity.get("confidence", 0)

    youtube_script = (
        f"Today WickSense is showing a {market_bias.lower()} market bias with a {risk_environment.lower()} environment. "
        f"Average scanner confidence is currently {avg_confidence} percent. "
        f"The strongest setup right now is {top_market}, showing a {top_signal.lower()} signal on a {top_setup.lower()} at {top_confidence} percent confidence. "
        f"{ai_market_summary} {what_matters_now}"
    )

    short_hook = (
        f"WickSense just found a {top_signal.lower()} {top_setup.lower()} on {top_market} at {top_confidence}% confidence."
    )

    voiceover_script = (
        f"Market update. WickSense currently shows a {market_bias.lower()} bias. "
        f"Top opportunity is {top_market}. "
        f"Signal: {top_signal}. Setup: {top_setup}. Confidence: {top_confidence} percent. "
        f"{what_matters_now}"
    )

    cta_line = (
        "Follow WickSense for daily AI-driven market intelligence, trade ideas, and real-time setup analysis."
    )

    viral_hooks = [
        f"WickSense just detected a {top_signal.lower()} setup on {top_market} at {top_confidence}% confidence.",
        f"This may be the most important {top_market} setup on the board right now.",
        f"AI just flagged {top_market} as the top opportunity in the market right now.",
        f"Traders should be watching {top_market} closely right now.",
        f"A {top_setup.lower()} just appeared on {top_market}, and WickSense is paying attention."
    ]

    youtube_titles = [
        f"AI Just Flagged {top_market} for a {top_signal} Move",
        f"This {top_market} Setup Could Be Huge",
        f"WickSense Found the Best Trade on the Board",
        f"Top Market Opportunity Right Now: {top_market}",
        f"AI Market Alert: {top_market} {top_setup}",
        f"Is {top_market} About to Make a Major Move?",
        f"The Strongest Setup in the Market Right Now",
        f"AI Says Watch {top_market} Right Now",
        f"{top_market} Just Printed a {top_setup}",
        f"Today’s Best AI Trade Setup Revealed"
    ]

    short_captions = [
        f"AI found a {top_signal.lower()} setup on {top_market}.",
        f"{top_market} is the top setup on WickSense right now.",
        f"Watching this {top_setup.lower()} very closely.",
        f"This is why traders are watching {top_market}.",
        f"Top opportunity today: {top_market}.",
        f"WickSense just flagged this move.",
        f"{top_market} just jumped to the top of the scanner.",
        f"Strong setup. Clean signal. {top_market}.",
        f"The AI scanner likes this one a lot.",
        f"This setup could be the one traders watch today."
    ]

    thumbnail_texts = [
        f"{top_market} ALERT",
        f"{top_signal.upper()} SETUP",
        f"TOP TRADE NOW",
        f"AI FOUND THIS",
        f"{int(top_confidence)}% CONFIDENCE"
    ]

    return {
        "youtube_script": youtube_script,
        "short_hook": short_hook,
        "voiceover_script": voiceover_script,
        "cta_line": cta_line,
        "viral_hooks": viral_hooks,
        "youtube_titles": youtube_titles,
        "short_captions": short_captions,
        "thumbnail_texts": thumbnail_texts
    }


def summarize_group(entries, key_name):
    grouped = {}

    for entry in entries:
        key = entry.get(key_name) or "Unknown"
        if key not in grouped:
            grouped[key] = {
                "label": key,
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "breakevens": 0,
                "open_trades": 0,
                "total_pnl": 0.0,
                "average_pnl": 0.0,
                "win_rate": 0.0
            }

        grouped[key]["total_trades"] += 1

        outcome = (entry.get("outcome") or "").lower()
        pnl = safe_float(entry.get("pnl"), 0.0)

        if outcome == "win":
            grouped[key]["wins"] += 1
        elif outcome == "loss":
            grouped[key]["losses"] += 1
        elif outcome == "breakeven":
            grouped[key]["breakevens"] += 1
        else:
            grouped[key]["open_trades"] += 1

        grouped[key]["total_pnl"] += pnl

    results = []
    for item in grouped.values():
        closed_count = item["wins"] + item["losses"] + item["breakevens"]
        if item["total_trades"] > 0:
            item["average_pnl"] = round(item["total_pnl"] / item["total_trades"], 2)
        if closed_count > 0:
            item["win_rate"] = round((item["wins"] / closed_count) * 100, 2)
        item["total_pnl"] = round(item["total_pnl"], 2)
        results.append(item)

    results.sort(key=lambda x: (x["win_rate"], x["total_pnl"]), reverse=True)
    return results


def get_most_common_value(entries, key_name):
    counts = {}
    for entry in entries:
        value = entry.get(key_name)
        if value is None or value == "":
            continue
        counts[value] = counts.get(value, 0) + 1

    if not counts:
        return None

    return max(counts.items(), key=lambda x: x[1])[0]


def calculate_journal_analytics():
    journal = load_history(TRADE_JOURNAL_FILE)

    total_trades = len(journal)
    wins = 0
    losses = 0
    breakevens = 0
    open_trades = 0
    total_pnl = 0.0

    for entry in journal:
        outcome = (entry.get("outcome") or "").lower()
        pnl = safe_float(entry.get("pnl"), 0.0)

        if outcome == "win":
            wins += 1
        elif outcome == "loss":
            losses += 1
        elif outcome == "breakeven":
            breakevens += 1
        else:
            open_trades += 1

        total_pnl += pnl

    closed_trades = wins + losses + breakevens
    win_rate = round((wins / closed_trades) * 100, 2) if closed_trades > 0 else 0.0
    average_pnl = round((total_pnl / total_trades), 2) if total_trades > 0 else 0.0

    setup_breakdown = summarize_group(journal, "setup_type")
    market_breakdown = summarize_group(journal, "market")
    timeframe_breakdown = summarize_group(journal, "timeframe")

    best_setup_type = setup_breakdown[0]["label"] if setup_breakdown else None
    best_market = market_breakdown[0]["label"] if market_breakdown else None
    best_timeframe = timeframe_breakdown[0]["label"] if timeframe_breakdown else None

    most_common_mistake_tag = get_most_common_value(journal, "mistake_tag")
    most_common_emotion = get_most_common_value(journal, "emotion")

    return {
        "total_trades": total_trades,
        "closed_trades": closed_trades,
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "open_trades": open_trades,
        "win_rate": win_rate,
        "total_pnl": round(total_pnl, 2),
        "average_pnl": average_pnl,
        "best_setup_type": best_setup_type,
        "best_market": best_market,
        "best_timeframe": best_timeframe,
        "most_common_mistake_tag": most_common_mistake_tag,
        "most_common_emotion": most_common_emotion,
        "setup_breakdown": setup_breakdown,
        "market_breakdown": market_breakdown,
        "timeframe_breakdown": timeframe_breakdown
    }


def build_journal_review():
    analytics = calculate_journal_analytics()

    total_trades = analytics.get("total_trades", 0)
    win_rate = analytics.get("win_rate", 0.0)
    average_pnl = analytics.get("average_pnl", 0.0)
    best_setup_type = analytics.get("best_setup_type")
    best_market = analytics.get("best_market")
    best_timeframe = analytics.get("best_timeframe")
    most_common_mistake_tag = analytics.get("most_common_mistake_tag")
    most_common_emotion = analytics.get("most_common_emotion")

    strengths = []
    weaknesses = []

    if total_trades == 0:
        performance_summary = (
            "No journal data is available yet. Start logging trades to unlock coaching insights."
        )
        emotional_pattern = "No emotional pattern detected yet because there are no journal entries."
        mistake_pattern = "No mistake pattern detected yet because there are no journal entries."
        coaching_advice = (
            "Your next step is to journal each trade consistently, including outcome, notes, emotion, and mistakes."
        )
        next_focus = "Log at least 5 to 10 real trades so WickSense can identify useful patterns."

        return {
            "performance_summary": performance_summary,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "emotional_pattern": emotional_pattern,
            "mistake_pattern": mistake_pattern,
            "coaching_advice": coaching_advice,
            "next_focus": next_focus
        }

    if win_rate >= 60:
        strengths.append("Your win rate shows strong decision quality and improving trade selection.")
    elif win_rate >= 45:
        strengths.append("Your win rate is reasonably competitive and shows a workable trading foundation.")
    else:
        weaknesses.append("Your win rate suggests trade selection or execution discipline still needs tightening.")

    if average_pnl > 0:
        strengths.append("Your average pnl is positive, which suggests your winners are offsetting your weaker trades.")
    elif average_pnl < 0:
        weaknesses.append("Your average pnl is negative, which suggests losses or weak exits are dragging performance.")
    else:
        weaknesses.append("Your average pnl is flat, which suggests you may need better trade filtering or stronger execution.")

    if best_setup_type:
        strengths.append(f"Your strongest setup appears to be {best_setup_type}.")
    else:
        weaknesses.append("No setup type strength is visible yet because journal labeling is still limited.")

    if best_market:
        strengths.append(f"Your performance is strongest in {best_market}.")
    if best_timeframe:
        strengths.append(f"Your best timeframe currently appears to be {best_timeframe}.")

    if most_common_mistake_tag:
        weaknesses.append(f"Your most common mistake pattern is tagged as {most_common_mistake_tag}.")
        mistake_pattern = (
            f"The most repeated mistake in your journal is {most_common_mistake_tag}, suggesting a recurring execution or discipline issue."
        )
    else:
        mistake_pattern = (
            "No dominant mistake pattern is visible yet because mistake tagging is still sparse."
        )

    if most_common_emotion:
        emotional_pattern = (
            f"The most common emotional state logged in your journal is {most_common_emotion}, which may be influencing execution quality."
        )
        if most_common_emotion.lower() in ["fear", "hesitation", "revenge", "frustration", "anxiety"]:
            weaknesses.append(f"Emotionally, {most_common_emotion} appears frequently and may be affecting trade quality.")
    else:
        emotional_pattern = (
            "No dominant emotional pattern is visible yet because emotion tracking is still limited."
        )

    if win_rate >= 60 and average_pnl > 0:
        performance_summary = (
            f"You have logged {total_trades} trades with a win rate of {win_rate}%. "
            f"Performance is currently constructive, with your edge appearing strongest in {best_setup_type or 'your best setup category'}."
        )
        coaching_advice = (
            "Focus on repeating the conditions behind your best trades. Reduce experimentation and prioritize the setup, market, and timeframe combinations already producing your strongest results."
        )
        next_focus = (
            f"Double down on {best_setup_type or 'your best setup'}, especially in {best_market or 'your strongest market'} on {best_timeframe or 'your strongest timeframe'}."
        )
    elif win_rate >= 45:
        performance_summary = (
            f"You have logged {total_trades} trades with a win rate of {win_rate}%. "
            "Your results show potential, but consistency still depends on sharpening execution and reducing avoidable mistakes."
        )
        coaching_advice = (
            "Keep journaling carefully, reduce lower-quality trades, and focus on the setups already showing evidence of edge."
        )
        next_focus = (
            f"Prioritize cleaner entries in {best_setup_type or 'your better-performing setups'} and actively reduce mistakes linked to {most_common_mistake_tag or 'your most repeated journal issue'}."
        )
    else:
        performance_summary = (
            f"You have logged {total_trades} trades with a win rate of {win_rate}%. "
            "Current results suggest that selectivity, discipline, and emotional control need improvement before scaling further."
        )
        coaching_advice = (
            "Trade less, filter harder, and focus only on your clearest setups. Review losing trades for repeated errors in timing, discipline, or emotional execution."
        )
        next_focus = (
            f"Reduce frequency and concentrate on {best_setup_type or 'your cleanest setup types'} while eliminating recurring issues tied to {most_common_mistake_tag or 'your main mistake pattern'}."
        )

    return {
        "performance_summary": performance_summary,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "emotional_pattern": emotional_pattern,
        "mistake_pattern": mistake_pattern,
        "coaching_advice": coaching_advice,
        "next_focus": next_focus
    }

def build_performance_summary():
    history = load_history(SIGNAL_HISTORY_FILE)

    total_signals = len(history)
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
    confidence_total = 0.0
    confidence_count = 0

    setup_type_stats = {}
    market_stats = {}

    recent_signals = []

    for item in history:
        signal = (item.get("signal") or "").upper()
        confidence = safe_float(item.get("confidence"), None)
        setup_type = item.get("setup_type") or "Unknown"
        market = item.get("market") or "Unknown"

        if signal in ["BULLISH", "BUY"]:
            bullish_count += 1
        elif signal in ["BEARISH", "SELL"]:
            bearish_count += 1
        else:
            neutral_count += 1

        if confidence is not None:
            confidence_total += confidence
            confidence_count += 1

        if setup_type not in setup_type_stats:
            setup_type_stats[setup_type] = {
                "count": 0,
                "confidence_total": 0.0
            }

        setup_type_stats[setup_type]["count"] += 1
        if confidence is not None:
            setup_type_stats[setup_type]["confidence_total"] += confidence

        if market not in market_stats:
            market_stats[market] = {
                "count": 0,
                "confidence_total": 0.0
            }

        market_stats[market]["count"] += 1
        if confidence is not None:
            market_stats[market]["confidence_total"] += confidence

    average_confidence = round(confidence_total / confidence_count, 2) if confidence_count > 0 else 0.0

    best_setup_type = None
    best_setup_score = -1

    for setup_type, stats in setup_type_stats.items():
        avg_conf = stats["confidence_total"] / stats["count"] if stats["count"] > 0 else 0.0
        score = (stats["count"] * 0.4) + (avg_conf * 0.6)
        if score > best_setup_score:
            best_setup_score = score
            best_setup_type = setup_type

    best_market = None
    best_market_score = -1

    for market, stats in market_stats.items():
        avg_conf = stats["confidence_total"] / stats["count"] if stats["count"] > 0 else 0.0
        score = (stats["count"] * 0.4) + (avg_conf * 0.6)
        if score > best_market_score:
            best_market_score = score
            best_market = market

    for item in history[:10]:
        recent_signals.append({
            "timestamp": item.get("timestamp"),
            "market": item.get("market"),
            "signal": item.get("signal"),
            "setup_type": item.get("setup_type"),
            "confidence": item.get("confidence"),
            "entry": item.get("entry"),
            "reason": item.get("reason")
        })

    total_directional = bullish_count + bearish_count
    win_rate_proxy = round((max(bullish_count, bearish_count) / total_directional) * 100, 2) if total_directional > 0 else 0.0

    return {
        "total_signals": total_signals,
        "win_rate_proxy": win_rate_proxy,
        "average_confidence": average_confidence,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": neutral_count,
        "best_setup_type": best_setup_type,
        "best_market": best_market,
        "recent_signals": recent_signals
    }


def refresh_live_scan():
    global LIVE_SCAN_CACHE

    try:
        LIVE_SCAN_CACHE["status"] = "updating"
        results = scan_markets()
        timestamp = datetime.utcnow().isoformat() + "Z"

        LIVE_SCAN_CACHE["results"] = results
        LIVE_SCAN_CACHE["last_updated"] = timestamp
        LIVE_SCAN_CACHE["status"] = "ready"

        history_item = {
            "timestamp": timestamp,
            "status": "ready",
            "results": results
        }
        append_history(SCAN_HISTORY_FILE, history_item, max_items=100)

    except Exception as e:
        LIVE_SCAN_CACHE["status"] = f"error: {str(e)}"

def get_trade_readiness(signal_data):
    score = 0

    confidence = float(signal_data.get("confidence") or 0)
    pattern = signal_data.get("pattern")
    breakout = signal_data.get("breakout")
    liquidity = signal_data.get("liquidity_event")
    trendline = signal_data.get("trendline")
    reasons = signal_data.get("reasons", [])

    # -----------------------------
    # Confidence base
    # -----------------------------
    if confidence >= 80:
        score += 30
    elif confidence >= 70:
        score += 20
    elif confidence >= 60:
        score += 10

    # -----------------------------
    # Pattern strength
    # -----------------------------
    if pattern in ["Bullish Engulfing", "Bearish Engulfing"]:
        score += 15

    if pattern in ["Hammer", "Shooting Star"]:
        score += 10

    # -----------------------------
    # Breakout / liquidity
    # -----------------------------
    if breakout in ["Bullish Breakout", "Bearish Breakdown"]:
        score += 20

    if liquidity in ["Bullish Liquidity Sweep", "Bearish Liquidity Sweep"]:
        score += 15

    # -----------------------------
    # Trendline reaction
    # -----------------------------
    if trendline in ["Rising Trendline Support", "Falling Trendline Resistance"]:
        score += 10

    # -----------------------------
    # Location (from reasons)
    # -----------------------------
    if any("support" in r.lower() for r in reasons):
        score += 10

    if any("resistance" in r.lower() for r in reasons):
        score += 10

    # Cap at 100
    return min(score, 100)



# -----------------------------
# ROUTES
# -----------------------------
@app.route("/live-scan", methods=["GET"])
def live_scan():
    try:
        if LIVE_SCAN_CACHE["results"] is None:
            refresh_live_scan()

        return jsonify({
            "status": LIVE_SCAN_CACHE["status"],
            "last_updated": LIVE_SCAN_CACHE["last_updated"],
            "results": LIVE_SCAN_CACHE["results"]
        })
    except Exception as e:
        return jsonify({
            "error": "Live scan failed",
            "details": str(e)
        }), 500


@app.route("/refresh-live-scan", methods=["POST"])
def refresh_live_scan_route():
    try:
        refresh_live_scan()
        return jsonify({
            "status": "live scan refreshed",
            "last_updated": LIVE_SCAN_CACHE["last_updated"],
            "results": LIVE_SCAN_CACHE["results"]
        })
    except Exception as e:
        return jsonify({
            "error": "Live scan refresh failed",
            "details": str(e)
        }), 500


@app.route("/scanner-status", methods=["GET"])
def scanner_status():
    return jsonify({
        "status": LIVE_SCAN_CACHE["status"],
        "last_updated": LIVE_SCAN_CACHE["last_updated"],
        "has_results": LIVE_SCAN_CACHE["results"] is not None
    })


@app.route("/market-intelligence", methods=["GET"])
def market_intelligence():
    try:
        if LIVE_SCAN_CACHE["results"] is None:
            refresh_live_scan()

        intelligence = build_market_intelligence(LIVE_SCAN_CACHE["results"] or {})
        return jsonify(intelligence)

    except Exception as e:
        return jsonify({
            "error": "Failed to build market intelligence",
            "details": str(e)
        }), 500


@app.route("/market-script", methods=["GET"])
def market_script():
    try:
        if LIVE_SCAN_CACHE["results"] is None:
            refresh_live_scan()

        intelligence = build_market_intelligence(LIVE_SCAN_CACHE["results"] or {})
        script_data = build_market_script(intelligence)

        return jsonify({
            "intelligence": intelligence,
            "script": script_data
        })

    except Exception as e:
        return jsonify({
            "error": "Failed to build market script",
            "details": str(e)
        }), 500

@app.route("/stream-status", methods=["GET"])
def stream_status():
    return jsonify({
        "status": STREAM_STATUS.get("status"),
        "provider": STREAM_STATUS.get("provider"),
        "last_tick": STREAM_STATUS.get("last_tick"),
        "last_error": STREAM_STATUS.get("last_error"),
        "polling_active": POLLING_ACTIVE,
        "websocket_active": WS_ACTIVE
    })



@app.route("/live-signals", methods=["GET"])
def live_signals():
    try:
        ensure_live_engine_started()

        user_id = request.args.get("user_id")
        is_pro = is_pro_user(user_id) if user_id else False

        markets = []

        for market_name, data in LIVE_MARKET_STATE.items():
            market_payload = {
                "market": market_name,
                "last_updated": data.get("last_updated"),
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "close": data.get("close"),
                "upper_wick": data.get("upper_wick"),
                "lower_wick": data.get("lower_wick"),
                "signal": data.get("signal"),
                "confidence": data.get("confidence"),
                "pattern": data.get("pattern"),
                "breakout": data.get("breakout"),
                "liquidity_event": data.get("liquidity_event"),
                "trendline": data.get("trendline"),
                "setup_type": data.get("setup_type"),
                "ai_summary": data.get("ai_summary"),
                "trade_thesis": data.get("trade_thesis"),
                "risk_note": data.get("risk_note"),
                "strategy_recommendation": data.get("strategy_recommendation"),
                "strategy_reason": data.get("strategy_reason"),
                "suggested_action": data.get("suggested_action"),
                "support_levels": data.get("support_levels"),
                "resistance_levels": data.get("resistance_levels"),
                "trendline_points": data.get("trendline_points"),
                "breakout_zone": data.get("breakout_zone"),
                "entry_zone": data.get("entry_zone"),
                "strategy_visual_bias": data.get("strategy_visual_bias"),
                "entry_timing": data.get("entry_timing"),
                "confirmation_state": data.get("confirmation_state"),
                "trade_readiness_score": data.get("trade_readiness_score"),
                "execution_guidance": data.get("execution_guidance"),
                "session_label": data.get("session_label"),
                "active_sessions": data.get("active_sessions"),
                "liquidity_profile": data.get("liquidity_profile"),
                "utc_hour": data.get("utc_hour")
            }
            markets.append(market_payload)

        if not is_pro:
            for m in markets:
                m["confidence"] = None
                m["execution_guidance"] = "Upgrade to Pro for real-time insights"
                m["trade_readiness_score"] = None
                m["entry_timing"] = "Upgrade Required"
                m["confirmation_state"] = "Upgrade Required"
            markets = markets[:2]

        return jsonify({
            "status": STREAM_STATUS.get("status"),
            "provider": STREAM_STATUS.get("provider"),
            "last_tick": STREAM_STATUS.get("last_tick"),
            "count": len(markets),
            "markets": markets
        })

    except Exception as e:
        return jsonify({
            "error": "Failed to load live signals",
            "details": str(e)
        }), 500


@app.route("/debug-live-state", methods=["GET"])
def debug_live_state():
    try:
        ensure_live_engine_started()

        markets = LIVE_MARKET_STATE.get("markets", {})

        return jsonify({
            "market_count": len(markets),
            "markets": markets
        })

    except Exception as e:
        return jsonify({
            "error": "Failed to load debug live state",
            "details": str(e)
        }), 500


@app.route("/live-setup-forming", methods=["GET"])
def live_setup_forming():
    try:
        ensure_live_engine_started()
        setup_forming = get_current_setup_forming_trade()
        return jsonify(setup_forming or {})
    except Exception as e:
        return jsonify({
            "error": "Failed to load setup forming trade",
            "details": str(e)
        }), 500



@app.route("/signal-history", methods=["GET"])
def signal_history():
    try:
        history = load_history(SIGNAL_HISTORY_FILE)
        return jsonify({
            "count": len(history),
            "items": history
        })
    except Exception as e:
        return jsonify({
            "error": "Failed to load signal history",
            "details": str(e)
        }), 500


@app.route("/tradeplan-history", methods=["GET"])
def tradeplan_history():
    try:
        history = load_history(TRADEPLAN_HISTORY_FILE)
        return jsonify({
            "count": len(history),
            "items": history
        })
    except Exception as e:
        return jsonify({
            "error": "Failed to load trade plan history",
            "details": str(e)
        }), 500


@app.route("/scan-history", methods=["GET"])
def scan_history():
    try:
        history = load_history(SCAN_HISTORY_FILE)
        return jsonify({
            "count": len(history),
            "items": history
        })
    except Exception as e:
        return jsonify({
            "error": "Failed to load scan history",
            "details": str(e)
        }), 500


@app.route("/trade-journal", methods=["GET"])
def get_trade_journal():
    try:
        journal = load_history(TRADE_JOURNAL_FILE)
        return jsonify({
            "count": len(journal),
            "items": journal
        })
    except Exception as e:
        return jsonify({
            "error": "Failed to load trade journal",
            "details": str(e)
        }), 500


@app.route("/trade-journal", methods=["POST"])
def create_trade_journal_entry():
    try:
        body = get_request_body()

        entry = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "market": body.get("market"),
            "timeframe": body.get("timeframe"),
            "side": body.get("side"),
            "setup_type": body.get("setup_type"),
            "entry_price": body.get("entry_price"),
            "stop_loss": body.get("stop_loss"),
            "take_profit": body.get("take_profit"),
            "outcome": body.get("outcome", "open"),
            "pnl": body.get("pnl"),
            "rating": body.get("rating"),
            "status": body.get("status", "planned"),
            "notes": body.get("notes", ""),
            "emotion": body.get("emotion", ""),
            "mistake_tag": body.get("mistake_tag", "")
        }

        append_history(TRADE_JOURNAL_FILE, entry, max_items=500)
        return jsonify(entry)
    except Exception as e:
        return jsonify({
            "error": "Failed to create trade journal entry",
            "details": str(e)
        }), 500


@app.route("/trade-journal/<entry_id>", methods=["PUT"])
def update_trade_journal_entry(entry_id):
    try:
        body = get_request_body()
        updated_entry = update_journal_entry(entry_id, body)

        if not updated_entry:
            return jsonify({"error": "Trade journal entry not found"}), 404

        return jsonify(updated_entry)
    except Exception as e:
        return jsonify({
            "error": "Failed to update trade journal entry",
            "details": str(e)
        }), 500


@app.route("/trade-journal/<entry_id>", methods=["DELETE"])
def delete_trade_journal_entry(entry_id):
    try:
        deleted = delete_journal_entry_by_id(entry_id)

        if not deleted:
            return jsonify({"error": "Trade journal entry not found"}), 404

        return jsonify({
            "success": True,
            "deleted_id": entry_id
        })
    except Exception as e:
        return jsonify({
            "error": "Failed to delete trade journal entry",
            "details": str(e)
        }), 500


@app.route("/journal-analytics", methods=["GET"])
def journal_analytics():
    try:
        analytics = calculate_journal_analytics()
        return jsonify(analytics)
    except Exception as e:
        return jsonify({
            "error": "Failed to calculate journal analytics",
            "details": str(e)
        }), 500

@app.route("/performance-summary", methods=["GET"])
def performance_summary():
    try:
        summary = build_performance_summary()
        return jsonify(summary)
    except Exception as e:
        return jsonify({
            "error": "Failed to build performance summary",
            "details": str(e)
        }), 500


@app.route("/journal-review", methods=["GET"])
def journal_review():
    try:
        review = build_journal_review()
        return jsonify(review)
    except Exception as e:
        return jsonify({
            "error": "Failed to build journal review",
            "details": str(e)
        }), 500


@app.route("/alert-rules", methods=["GET"])
def get_alert_rules():
    try:
        rules = load_alert_rules()
        return jsonify({
            "count": len(rules),
            "items": rules
        })
    except Exception as e:
        return jsonify({
            "error": "Failed to load alert rules",
            "details": str(e)
        }), 500


@app.route("/alert-rules", methods=["POST"])
def create_alert_rule():
    try:
        body = get_request_body()

        rule = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "name": body.get("name", "New Alert Rule"),
            "is_enabled": body.get("is_enabled", True),
            "market": body.get("market"),
            "signal": body.get("signal"),
            "setup_type": body.get("setup_type"),
            "minimum_confidence": body.get("minimum_confidence"),
            "timeframe": body.get("timeframe"),
            "require_breakout": body.get("require_breakout", False),
            "require_liquidity_event": body.get("require_liquidity_event", False),
            "require_trendline": body.get("require_trendline", False),
            "delivery_type": body.get("delivery_type", "email"),
            "cooldown_minutes": body.get("cooldown_minutes", 60)
        }

        append_history(ALERT_RULES_FILE, rule, max_items=500)
        return jsonify(rule)
    except Exception as e:
        return jsonify({
            "error": "Failed to create alert rule",
            "details": str(e)
        }), 500


@app.route("/alert-rules/<rule_id>", methods=["PUT"])
def update_alert_rule(rule_id):
    try:
        body = get_request_body()
        rules = load_alert_rules()

        updated_rule = None
        for rule in rules:
            if rule["id"] == rule_id:
                rule.update(body)
                rule["updated_at"] = datetime.utcnow().isoformat() + "Z"
                updated_rule = rule
                break

        if not updated_rule:
            return jsonify({"error": "Alert rule not found"}), 404

        save_alert_rules(rules)
        return jsonify(updated_rule)
    except Exception as e:
        return jsonify({
            "error": "Failed to update alert rule",
            "details": str(e)
        }), 500


@app.route("/alert-rules/<rule_id>", methods=["DELETE"])
def delete_alert_rule(rule_id):
    try:
        rules = load_alert_rules()
        filtered = [rule for rule in rules if rule["id"] != rule_id]

        if len(filtered) == len(rules):
            return jsonify({"error": "Alert rule not found"}), 404

        save_alert_rules(filtered)
        return jsonify({
            "success": True,
            "deleted_id": rule_id
        })
    except Exception as e:
        return jsonify({
            "error": "Failed to delete alert rule",
            "details": str(e)
        }), 500


@app.route("/notifications", methods=["GET"])
def get_notifications():
    try:
        items = load_notifications()
        unread_count = sum(1 for n in items if not n.get("is_read", False))

        return jsonify({
            "count": len(items),
            "unread_count": unread_count,
            "items": items
        })
    except Exception as e:
        return jsonify({
            "error": "Failed to load notifications",
            "details": str(e)
        }), 500


@app.route("/notifications/<notification_id>/read", methods=["PUT"])
def mark_notification_read(notification_id):
    try:
        items = load_notifications()

        for n in items:
            if n["id"] == notification_id:
                n["is_read"] = True

        save_notifications(items)

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({
            "error": "Failed to update notification",
            "details": str(e)
        }), 500


@app.route("/notifications/<notification_id>", methods=["DELETE"])
def delete_notification(notification_id):
    try:
        items = load_notifications()
        filtered = [n for n in items if n["id"] != notification_id]

        save_notifications(filtered)

        return jsonify({
            "success": True,
            "deleted_id": notification_id
        })

    except Exception as e:
        return jsonify({
            "error": "Failed to delete notification",
            "details": str(e)
        }), 500


@app.route("/risk-settings", methods=["GET"])
def get_risk_settings():
    try:
        settings = load_risk_settings()
        return jsonify(settings)
    except Exception as e:
        return jsonify({
            "error": "Failed to load risk settings",
            "details": str(e)
        }), 500


@app.route("/risk-settings", methods=["PUT"])
def update_risk_settings():
    try:
        body = get_request_body()
        settings = load_risk_settings()

        settings["max_daily_loss"] = float(
            body.get("max_daily_loss", settings.get("max_daily_loss", 500.0))
        )
        settings["min_confidence_threshold"] = float(
            body.get("min_confidence_threshold", settings.get("min_confidence_threshold", 70.0))
        )
        settings["max_risk_percent_per_trade"] = float(
            body.get("max_risk_percent_per_trade", settings.get("max_risk_percent_per_trade", 2.0))
        )
        settings["block_low_quality_setups"] = bool(
            body.get("block_low_quality_setups", settings.get("block_low_quality_setups", False))
        )

        save_risk_settings(settings)
        return jsonify(settings)

    except Exception as e:
        return jsonify({
            "error": "Failed to update risk settings",
            "details": str(e)
        }), 500


@app.route("/daily-loss-status", methods=["GET"])
def daily_loss_status():
    try:
        status = get_daily_loss_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({
            "error": "Failed to calculate daily loss status",
            "details": str(e)
        }), 500


@app.route("/scan-markets", methods=["GET"])
def scan_markets_route():
    try:
        results = scan_markets()
        return jsonify({
            "status": "scan completed",
            "signals": results["signals"],
            "approved_trades": results["approved_trades"],
            "top_overall": results["top_overall"],
            "top_bullish": results["top_bullish"],
            "top_bearish": results["top_bearish"],
            "top_breakout": results["top_breakout"],
            "top_trendline": results["top_trendline"],
            "all_results_sorted": results["all_results_sorted"],
            "raw_results": results["raw_results"]
        })
    except Exception as e:
        return jsonify({
            "error": "Market scan failed",
            "details": str(e)
        }), 500




# -----------------------------
# SIGNAL
# -----------------------------
def store_signal(user_id, signal):
    try:
        if not user_id:
            print("📊 SIGNAL NOT STORED: missing user_id", flush=True)
            return

        payload = {
            "user_id": user_id,
            "market": signal.get("market"),
            "direction": signal.get("signal"),
            "confidence": signal.get("confidence"),
            "strategy": signal.get("setup_type") or signal.get("pattern"),
            "entry": signal.get("entry"),
            "stop_loss": signal.get("support"),
            "take_profit": signal.get("resistance"),
            "timeframe": signal.get("timeframe"),
            "created_at": datetime.utcnow().isoformat() + "Z"
        }

        print("🔥 store_signal running", flush=True)
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/signals_history",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            },
            json=payload,
            timeout=20
        )

        print("📊 SIGNAL STORED STATUS:", response.status_code, flush=True)
        print("📊 SIGNAL STORED RESPONSE:", response.text, flush=True)

    except Exception as e:
        print("❌ SIGNAL STORE ERROR:", str(e), flush=True)


def build_trade_levels(signal_data, last_row):
    signal = signal_data.get("signal", "Neutral")
    entry = float(last_row["Close"])
    candle_high = float(last_row["High"])
    candle_low = float(last_row["Low"])
    candle_range = max(candle_high - candle_low, 0.000001)

    support = signal_data.get("support")
    resistance = signal_data.get("resistance")

    try:
        support = float(support) if support is not None else None
    except Exception:
        support = None

    try:
        resistance = float(resistance) if resistance is not None else None
    except Exception:
        resistance = None

    stop_loss = None
    take_profit = None
    risk_per_unit = None
    reward_per_unit = None
    risk_reward = None

    # Bullish setup
    if signal == "Bullish":
        structural_stop = support if support is not None and support < entry else None
        fallback_stop = candle_low - (candle_range * 0.25)

        stop_loss = structural_stop if structural_stop is not None else fallback_stop

        # Make sure stop is actually below entry
        if stop_loss >= entry:
            stop_loss = entry - max(candle_range * 0.75, 0.000001)

        risk_per_unit = entry - stop_loss

        structural_target = resistance if resistance is not None and resistance > entry else None
        rr_target = entry + (risk_per_unit * 1.8)

        take_profit = structural_target if structural_target is not None else rr_target

        # Make sure TP is actually above entry
        if take_profit <= entry:
            take_profit = entry + (risk_per_unit * 1.8)

        reward_per_unit = take_profit - entry

    # Bearish setup
    elif signal == "Bearish":
        structural_stop = resistance if resistance is not None and resistance > entry else None
        fallback_stop = candle_high + (candle_range * 0.25)

        stop_loss = structural_stop if structural_stop is not None else fallback_stop

        # Make sure stop is actually above entry
        if stop_loss <= entry:
            stop_loss = entry + max(candle_range * 0.75, 0.000001)

        risk_per_unit = stop_loss - entry

        structural_target = support if support is not None and support < entry else None
        rr_target = entry - (risk_per_unit * 1.8)

        take_profit = structural_target if structural_target is not None else rr_target

        # Make sure TP is actually below entry
        if take_profit >= entry:
            take_profit = entry - (risk_per_unit * 1.8)

        reward_per_unit = entry - take_profit

    if risk_per_unit is not None and reward_per_unit is not None and risk_per_unit > 0:
        risk_reward = round(reward_per_unit / risk_per_unit, 2)

    return {
        "entry": round(entry, 6),
        "stop_loss": round(stop_loss, 6) if stop_loss is not None else None,
        "take_profit": round(take_profit, 6) if take_profit is not None else None,
        "risk_per_unit": round(risk_per_unit, 6) if risk_per_unit is not None else None,
        "reward_per_unit": round(reward_per_unit, 6) if reward_per_unit is not None else None,
        "risk_reward": risk_reward
    }
    

@app.route("/signal", methods=["GET", "POST"])
def signal():
    try:
        import pandas as pd
        from datetime import datetime

        # -----------------------------
        # GET MARKET / TIMEFRAME
        # -----------------------------
        market = get_market_from_request()

        if request.method == "GET":
            timeframe = request.args.get("timeframe", "1h")
        else:
            if request.is_json:
                body = request.get_json(silent=True) or {}
                timeframe = body.get("timeframe", "1h")
            else:
                timeframe = request.form.get("timeframe", "1h")

        if not market:
            return jsonify({"error": "No market provided"}), 400

        market = str(market).strip().upper().replace(" ", "")
        timeframe = str(timeframe).strip().lower()

        VALID_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
        if timeframe not in VALID_TIMEFRAMES:
            return jsonify({
                "error": f"Invalid timeframe: {timeframe}",
                "valid_options": VALID_TIMEFRAMES
            }), 400

        print(f"📡 FULL SIGNAL ROUTE | market={market} timeframe={timeframe}", flush=True)

        # -----------------------------
        # FETCH MARKET DATA
        # -----------------------------
        df = fetch_live_market_data(
            market=market,
            interval=timeframe,
            outputsize=50
        )

        if df is None or df.empty:
            print(f"❌ No data returned for {market}", flush=True)
            return jsonify({
                "error": f"No market data available for {market}"
            }), 500

        print(f"📊 Raw DF columns for {market}: {list(df.columns)}", flush=True)

        # -----------------------------
        # FORCE CLEAN NUMERIC CONVERSION
        # -----------------------------
        required_cols = ["Open", "High", "Low", "Close"]

        for col in required_cols:
            if col not in df.columns:
                print(f"❌ Missing column: {col}", flush=True)
                return jsonify({"error": f"Missing column: {col}"}), 500

            df[col] = df[col].astype(str).str.replace(",", "", regex=False).str.strip()
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=required_cols).copy()

        print("🧼 CLEANED DATA TYPES:", flush=True)
        print(df[required_cols].dtypes, flush=True)

        if df.empty:
            print(f"❌ No valid numeric rows remain for {market}", flush=True)
            return jsonify({
                "error": "No valid numeric data after cleaning"
            }), 500

        # -----------------------------
        # RUN REAL SIGNAL ENGINE
        # -----------------------------
        signal_data = evaluate_signal(df)

        try:
            ai_text = build_ai_explanation(signal_data)
        except Exception as ai_error:
            print(f"⚠️ build_ai_explanation failed: {ai_error}", flush=True)
            ai_text = {}

        try:
            mtf_data = get_multi_timeframe_confirmation(market, timeframe)
        except Exception as mtf_error:
            print(f"⚠️ get_multi_timeframe_confirmation failed: {mtf_error}", flush=True)
            mtf_data = {}

        try:
            session_data = get_market_session()
        except Exception as session_error:
            print(f"⚠️ get_market_session failed: {session_error}", flush=True)
            session_data = {}

        try:
            setup_type = get_setup_type(signal_data)
        except Exception as setup_error:
            print(f"⚠️ get_setup_type failed: {setup_error}", flush=True)
            setup_type = None

        last_row = df.iloc[-1]

        response = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "market": market,
            "timeframe": timeframe,

            "signal": signal_data.get("signal"),
            "confidence": signal_data.get("confidence"),
            "pattern": signal_data.get("pattern"),
            "setup_type": setup_type,

            "open": float(last_row["Open"]),
            "high": float(last_row["High"]),
            "low": float(last_row["Low"]),
            "close": float(last_row["Close"]),
            "entry": float(last_row["Close"]),

            "ma20": signal_data.get("ma20"),
            "ma50": signal_data.get("ma50"),
            "vwap": signal_data.get("vwap"),
            "support": signal_data.get("support"),
            "resistance": signal_data.get("resistance"),
            "upper_wick": signal_data.get("upper_wick"),
            "lower_wick": signal_data.get("lower_wick"),

            "breakout": signal_data.get("breakout"),
            "liquidity_event": signal_data.get("liquidity_event"),
            "trendline": signal_data.get("trendline"),

            "strategy_breakdown": signal_data.get("strategy_breakdown"),
            "bullish_points": signal_data.get("bullish_points"),
            "bearish_points": signal_data.get("bearish_points"),
            "confluence_bonus": signal_data.get("confluence_bonus"),
            "reason": ", ".join(signal_data.get("reasons", [])) if signal_data.get("reasons") else "",

            "multi_timeframe": mtf_data.get("multi_timeframe"),
            "higher_timeframe_bias": mtf_data.get("higher_timeframe_bias"),
            "timeframe_alignment": mtf_data.get("timeframe_alignment"),

            "ai_summary": ai_text.get("ai_summary"),
            "trade_thesis": ai_text.get("trade_thesis"),
            "risk_note": ai_text.get("risk_note"),

            "session_label": session_data.get("session_label"),
            "active_sessions": session_data.get("active_sessions"),
            "liquidity_profile": session_data.get("liquidity_profile"),
            "utc_hour": session_data.get("utc_hour"),

            "status": "ok"
        }

        print(f"✅ FULL SIGNAL GENERATED for {market}", flush=True)
        return jsonify(response)

    except Exception as e:
        import traceback
        print("\n========== SIGNAL ROUTE ERROR ==========", flush=True)
        print("ERROR:", str(e), flush=True)
        traceback.print_exc()
        print("========== END SIGNAL ROUTE ERROR ==========\n", flush=True)

        return jsonify({
            "error": "Signal generation failed",
            "details": str(e)
        }), 500


# -----------------------------
# BACKTEST
# -----------------------------
@app.route("/backtest", methods=["POST"])
def backtest():
    try:
        market = get_market_from_request()

        # --- MARKET ALIASES ---
        market_aliases = {
            # Forex
            "EURUSD": "FOREX",
            "EUR/USD": "FOREX",
            "FOREX": "FOREX",

            # NASDAQ
            "NASDAQ": "NASDAQ",
            "NDX": "NASDAQ",
            "US100": "NASDAQ",

            # Dow Jones
            "DOWJONES": "DOWJONES",
            "DOWJONES30": "DOWJONES",
            "DJI": "DOWJONES",
            "US30": "DOWJONES",

            # Gold
            "XAUUSD": "GOLD",
            "XAU/USD": "GOLD",
            "GOLD": "GOLD",

            # Natural Gas
            "NG": "NATURALGAS",
            "NATURALGAS": "NATURALGAS",

            # Futures
            "FUTURES": "FUTURES",
            "ES": "FUTURES"
        }

        requested_market = str(market).strip().upper() if market else ""
        if market:
            market = market_aliases.get(requested_market, requested_market)

        timeframe = normalize_interval(get_string_from_request("timeframe", "1day"))
        _ = get_string_from_request("start_date", "")
        _ = get_string_from_request("end_date", "")

        if not market:
            return jsonify({"error": "No market was provided"}), 400

        df = fetch_live_market_data(market, interval=timeframe, outputsize=50)

        if df is None or df.empty:
            return jsonify({
                "error": "No market data returned",
                "details": {
                    "requested_market": requested_market,
                    "mapped_market": market,
                    "timeframe": timeframe
                }
            }), 400

        # Ensure numeric OHLC data
        required_cols = ["Open", "High", "Low", "Close"]
        for col in required_cols:
            if col not in df.columns:
                return jsonify({
                    "error": f"Missing required column: {col}"
                }), 500

            df[col] = df[col].astype(str).str.replace(",", "", regex=False).str.strip()
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=required_cols).copy()

        if df.empty:
            return jsonify({
                "error": "No valid numeric market data after cleaning",
                "details": {
                    "requested_market": requested_market,
                    "mapped_market": market,
                    "timeframe": timeframe
                }
            }), 400

        df = add_indicators(df)

        results = []
        equity_curve = []
        trade_pnls = []

        cash = 0.0
        pos = 0.0
        last_buy_price = None

        buy_count = 0
        sell_count = 0
        hold_count = 0

        for i in range(len(df)):
            row = df.iloc[i]

            if (
                pd.isna(row["MA20"]) or
                pd.isna(row["VWAP"]) or
                pd.isna(row["Support"]) or
                pd.isna(row["Resistance"])
            ):
                continue

            bullish_points = 0
            bearish_points = 0

            if row["LowerWick"] > row["UpperWick"] * 1.2:
                bullish_points += 1
            elif row["UpperWick"] > row["LowerWick"] * 1.2:
                bearish_points += 1

            if row["Close"] > row["Open"]:
                bullish_points += 1
            elif row["Close"] < row["Open"]:
                bearish_points += 1

            if row["Close"] > row["MA20"]:
                bullish_points += 1
            elif row["Close"] < row["MA20"]:
                bearish_points += 1

            if row["Close"] > row["VWAP"]:
                bullish_points += 1
            elif row["Close"] < row["VWAP"]:
                bearish_points += 1

            support_distance = abs(row["Close"] - row["Support"])
            resistance_distance = abs(row["Resistance"] - row["Close"])

            if support_distance < resistance_distance:
                bullish_points += 1
            elif resistance_distance < support_distance:
                bearish_points += 1

            if bullish_points > bearish_points:
                action = "Buy"
            elif bearish_points > bullish_points:
                action = "Sell"
            else:
                action = "Hold"

            price = float(row["Close"])

            if action == "Buy":
                buy_count += 1
                pos += 1
                cash -= price
                last_buy_price = price

            elif action == "Sell":
                sell_count += 1
                if pos > 0:
                    pos -= 1
                    cash += price

                    if last_buy_price is not None:
                        pnl = round(price - last_buy_price, 4)
                        trade_pnls.append(pnl)
                        last_buy_price = None
            else:
                hold_count += 1

            equity = cash + pos * price
            equity_curve.append(round(equity, 4))

            results.append({
                "index": int(i),
                "action": action,
                "price": price,
                "equity": round(equity, 4)
            })

        total_trades = len(results)
        closed_trades = len(trade_pnls)
        winning_trades = len([p for p in trade_pnls if p > 0])
        losing_trades = len([p for p in trade_pnls if p < 0])
        breakeven_trades = len([p for p in trade_pnls if p == 0])

        win_rate = round((winning_trades / closed_trades) * 100, 2) if closed_trades > 0 else 0.0
        total_pnl = round(sum(trade_pnls), 4)
        average_trade_pnl = round(total_pnl / closed_trades, 4) if closed_trades > 0 else 0.0

        wins = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]

        average_win = round(sum(wins) / len(wins), 4) if wins else 0.0
        average_loss = round(sum(losses) / len(losses), 4) if losses else 0.0

        max_drawdown = 0.0
        peak = None
        for equity in equity_curve:
            if peak is None or equity > peak:
                peak = equity

            drawdown = peak - equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        ending_equity = round(equity_curve[-1], 4) if equity_curve else 0.0

        # --- RAW CANDLE DATA FOR FRONTEND / ROCKET COMPATIBILITY ---
        candles = []
        time_col = "Datetime" if "Datetime" in df.columns else None

        for i, row in df.iterrows():
            if (
                pd.isna(row.get("Open")) or
                pd.isna(row.get("High")) or
                pd.isna(row.get("Low")) or
                pd.isna(row.get("Close"))
            ):
                continue

            if time_col and pd.notna(row.get(time_col)):
                time_value = str(row.get(time_col))
            elif isinstance(i, pd.Timestamp):
                time_value = i.isoformat()
            else:
                time_value = str(i)

            candles.append({
                "time": time_value,
                "open": round(float(row["Open"]), 6),
                "high": round(float(row["High"]), 6),
                "low": round(float(row["Low"]), 6),
                "close": round(float(row["Close"]), 6),
                "volume": round(float(row["Volume"]), 6) if "Volume" in df.columns and pd.notna(row.get("Volume")) else 0.0
            })

        return jsonify({
            "market": market,
            "requested_market": requested_market,
            "timeframe": timeframe,
            "results": results,
            "equity_curve": equity_curve,

            # --- ROCKET COMPATIBILITY ---
            "candles": candles,
            "price_history": candles,
            "ohlcv": candles,

            "metrics": {
                "total_trades": total_trades,
                "buy_count": buy_count,
                "sell_count": sell_count,
                "hold_count": hold_count,
                "closed_trades": closed_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "breakeven_trades": breakeven_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "average_trade_pnl": average_trade_pnl,
                "average_win": average_win,
                "average_loss": average_loss,
                "max_drawdown": round(max_drawdown, 4),
                "ending_equity": ending_equity
            }
        })

    except Exception as e:
        return jsonify({
            "error": "Backtest failed",
            "details": str(e)
        }), 500


@app.route("/price-history", methods=["POST"])
def price_history():
    try:
        print("[price-history] route hit")

        market = get_market_from_request()
        timeframe = normalize_interval(get_string_from_request("timeframe", "1day"))
        outputsize = int(get_string_from_request("outputsize", "50"))
        start_date = get_string_from_request("start_date", "")
        end_date = get_string_from_request("end_date", "")

        print(f"[price-history] raw market={market}, timeframe={timeframe}, outputsize={outputsize}")

        if not market:
            return jsonify({"error": "No market was provided"}), 400

        market_aliases = {
            "EURUSD": "Forex",
            "EUR/USD": "Forex",
            "FOREX": "Forex",
            "QQQ": "NASDAQ",
            "NASDAQ": "NASDAQ",
            "DIA": "DowJones",
            "DOWJONES": "DowJones",
            "DOWJONES30": "DowJones",
            "XAUUSD": "Gold",
            "XAU/USD": "Gold",
            "GOLD": "Gold",
            "NG": "NaturalGas",
            "NATURALGAS": "NaturalGas",
            "SPY": "Futures",
            "FUTURES": "Futures"
        }

        market_key = str(market).strip().upper()
        market = market_aliases.get(market_key, market)

        print(f"[price-history] mapped market={market}")

        if outputsize < 20:
            outputsize = 20
        if outputsize > 100:
            outputsize = 100

        print("[price-history] calling fetch_live_market_data...")
        df = fetch_live_market_data(market, interval=timeframe, outputsize=outputsize)
        print("[price-history] fetch_live_market_data returned")

        if df is None or df.empty:
            return jsonify({
                "error": "No market data returned",
                "details": {
                    "market_requested": market_key,
                    "market_mapped": market,
                    "timeframe": timeframe,
                    "outputsize": outputsize,
                    "start_date": start_date,
                    "end_date": end_date
                }
            }), 400

        candles = []
        for i, row in df.iterrows():
            if (
                pd.isna(row.get("Open")) or
                pd.isna(row.get("High")) or
                pd.isna(row.get("Low")) or
                pd.isna(row.get("Close"))
            ):
                continue

            time_value = i.isoformat() if isinstance(i, pd.Timestamp) else str(i)

            candles.append({
                "time": time_value,
                "open": round(float(row["Open"]), 6),
                "high": round(float(row["High"]), 6),
                "low": round(float(row["Low"]), 6),
                "close": round(float(row["Close"]), 6),
                "volume": round(float(row["Volume"]), 6) if "Volume" in df.columns and pd.notna(row.get("Volume")) else 0.0
            })

        print(f"[price-history] returning {len(candles)} candles")

        return jsonify({
            "market": market,
            "requested_market": market_key,
            "timeframe": timeframe,
            "start_date": start_date,
            "end_date": end_date,
            "count": len(candles),
            "candles": candles
        })

    except Exception as e:
        print(f"[price-history] ERROR: {e}")
        return jsonify({
            "error": "Price history failed",
            "details": str(e)
        }), 500



# -----------------------------
# TRADE PLAN
# -----------------------------
@app.route('/execute-paper-trade', methods=['POST'])
def execute_paper_trade():
    try:
        data = request.get_json(silent=True) or {}

        # -----------------------------
        # SAFE INPUT PARSING (UNIFIED)
        # -----------------------------
        market = data.get('market', "")

        entry = safe_float(data.get('entry'), None)

        stop = safe_float(
            data.get('stop_loss') or
            data.get('stop') or
            data.get('sl'),
            None
        )

        target = safe_float(
            data.get('take_profit') or
            data.get('target') or
            data.get('tp'),
            None
        )

        risk_percent = safe_float(data.get('risk_percent'), 1.0)

        # -----------------------------
        # VALIDATION
        # -----------------------------
        if not market:
            return jsonify({"error": "Missing market"}), 400

        if entry is None or stop is None or target is None:
            return jsonify({
                "error": "Missing required trade values",
                "details": {
                    "entry": data.get("entry"),
                    "stop_loss": data.get("stop_loss") or data.get("stop"),
                    "take_profit": data.get("take_profit") or data.get("target"),
                    "risk_percent": data.get("risk_percent")
                }
            }), 400

        # -----------------------------
        # RISK MODEL
        # -----------------------------
        account_size = 10000  # placeholder (upgrade later)
        risk_amount = account_size * (risk_percent / 100)

        risk_per_unit = abs(entry - stop)

        if risk_per_unit == 0:
            return jsonify({"error": "Invalid stop loss (same as entry)"}), 400

        position_size = risk_amount / risk_per_unit

        # -----------------------------
        # BUILD TRADE (STANDARDIZED FIELDS)
        # -----------------------------
        trade = {
            "trade_id": str(uuid.uuid4()),
            "market": market,
            "entry": round(entry, 4),
            "stop_loss": round(stop, 4),
            "take_profit": round(target, 4),
            "risk_percent": risk_percent,
            "risk_amount": round(risk_amount, 2),
            "position_size": round(position_size, 2),
            "status": "OPEN"
        }

        return jsonify(trade)

    except Exception as e:
        return jsonify({
            "error": "Paper trade execution failed",
            "details": str(e)
        }), 500

@app.route('/close-paper-trade', methods=['POST'])
def close_paper_trade():
    try:
        data = request.get_json(silent=True) or {}

        trade_id = data.get("trade_id")
        market = data.get("market")
        direction = data.get("direction")
        outcome = data.get("outcome")
        exit_price = data.get("exit_price")
        pnl_pts = data.get("pnl_pts")

        if not trade_id:
            return jsonify({"error": "Missing trade_id"}), 400

        # --- BUILD PAYLOAD ---
        payload = {
            "trade_id": trade_id,
            "market": market,
            "direction": direction,
            "outcome": outcome,
            "exit_price": exit_price,
            "pnl_pts": pnl_pts,
            "user_id": "550e8400-e29b-41d4-a716-446655440000"
        }

        # --- SEND TO SUPABASE ---
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/closed_trades",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            json=payload
        )

        if response.status_code not in [200, 201, 204]:
            return jsonify({
                "error": "Supabase insert failed",
                "details": response.text,
                "payload": payload
            }), 500

        return jsonify({
            "message": "Trade closed and saved",
            "trade": payload
        })

    except Exception as e:
        return jsonify({
            "error": "Failed to close trade",
            "details": str(e)
        }), 500


@app.route("/tradeplan", methods=["POST"])
def tradeplan():
    try:
        def safe_float(value, default=0.0):
            try:
                if value is None:
                    return default
                return float(value)
            except Exception:
                return default

        body = request.get_json(silent=True) or {}

        market = get_market_from_request()
        timeframe = normalize_interval(
            get_string_from_request("timeframe", "1day")
        )

        settings = load_risk_settings()

        risk_percent = get_float_from_request(
            "risk_percent",
            settings.get("max_risk_percent_per_trade", 1.0)
        )

        account_size = get_float_from_request(
            "account_size",
            10000.0
        )

        max_allowed_risk = safe_float(
            settings.get("max_risk_percent_per_trade"),
            2.0
        )

        if risk_percent > max_allowed_risk:
            risk_percent = max_allowed_risk

        if not market:
            return jsonify({
                "error": "No market was provided"
            }), 400

        daily_loss = get_daily_loss_status()

        if daily_loss["blocked"]:
            return jsonify({
                "error": "Daily loss limit reached",
                "details": "New trade plans are blocked because the max daily loss has been exceeded.",
                "daily_loss_status": daily_loss
            }), 403

        df = fetch_live_market_data(
            market,
            interval=timeframe,
            outputsize=100
        )

        if df is None or df.empty:
            return jsonify({
                "error": "No market data available",
                "details": "Failed to fetch market data"
            }), 500

        incoming_signal = (
            body.get("signalPayload")
            or body.get("signal_payload")
            or body.get("signal_data")
        )

        if isinstance(incoming_signal, dict) and incoming_signal.get("signal"):
            signal_data = incoming_signal
            print("[TRADEPLAN_USING_FORWARDED_SIGNAL]", {
                "market": market,
                "timeframe": timeframe,
                "signal": signal_data.get("signal"),
                "confidence": signal_data.get("confidence"),
                "entry": signal_data.get("entry")
            })
        else:
            signal_data = evaluate_signal(df)
            print("[TRADEPLAN_USING_LOCAL_EVALUATION]", {
                "market": market,
                "timeframe": timeframe,
                "signal": signal_data.get("signal") if signal_data else None,
                "confidence": signal_data.get("confidence") if signal_data else None
            })

        if not signal_data:
            return jsonify({
                "error": "Signal evaluation failed"
            }), 500

        ai_text = build_ai_explanation(signal_data)
        mtf_data = get_multi_timeframe_confirmation(market, timeframe)
        session_data = get_market_session()

        last_row = df.iloc[-1]
        recent_rows = df.tail(14)

        close_price = safe_float(last_row.get("Close"), 0)

        if close_price <= 0:
            return jsonify({
                "error": "Invalid close price"
            }), 400

        support_price = safe_float(
            signal_data.get("support"),
            close_price
        )

        resistance_price = safe_float(
            signal_data.get("resistance"),
            close_price
        )

        try:
            atr_series = recent_rows["High"] - recent_rows["Low"]
            atr = safe_float(
                atr_series.mean(),
                close_price * 0.01
            )
        except Exception:
            atr = close_price * 0.01

        if atr <= 0:
            atr = close_price * 0.01

        raw_signal = str(
            signal_data.get("signal", "")
        ).strip().upper()

        if raw_signal in ["BUY", "BULLISH"]:
            normalized_signal = "BULLISH"
            trade_side = "Buy"
        elif raw_signal in ["SELL", "BEARISH"]:
            normalized_signal = "BEARISH"
            trade_side = "Sell"
        else:
            return jsonify({
                "error": "No strong trade setup found",
                "details": "Signal is neutral",
                "raw_signal": raw_signal
            }), 400

        breakout = signal_data.get("breakout")
        trendline = signal_data.get("trendline")
        pattern = signal_data.get("pattern")

        entry = safe_float(
            signal_data.get("entry") or signal_data.get("entry_price"),
            close_price
        )

        if entry <= 0:
            entry = close_price

        if normalized_signal == "BULLISH":
            if breakout == "Bullish Breakout":
                entry = max(entry, close_price, resistance_price)

            stop_loss = min(
                support_price,
                entry - atr * 1.5
            )

            take_profit_1 = entry + ((entry - stop_loss) * 1.5)
            take_profit_2 = entry + ((entry - stop_loss) * 3.0)

            if breakout == "Bullish Breakout":
                setup_type = "Bullish Breakout Continuation"
            elif trendline == "Rising Trendline Support":
                setup_type = "Bullish Trendline Bounce"
            elif pattern == "Hammer":
                setup_type = "Bullish Hammer Reversal"
            elif pattern == "Pin Bar":
                setup_type = "Bullish Pin Bar Setup"
            else:
                setup_type = "Bullish Confluence Setup"

        else:
            if breakout == "Bearish Breakdown":
                entry = min(entry, close_price, support_price)

            stop_loss = max(
                resistance_price,
                entry + atr * 1.5
            )

            take_profit_1 = entry - ((stop_loss - entry) * 1.5)
            take_profit_2 = entry - ((stop_loss - entry) * 3.0)

            if breakout == "Bearish Breakdown":
                setup_type = "Bearish Breakdown Continuation"
            elif trendline == "Falling Trendline Resistance":
                setup_type = "Bearish Trendline Rejection"
            elif pattern == "Shooting Star":
                setup_type = "Bearish Shooting Star Reversal"
            elif pattern == "Pin Bar":
                setup_type = "Bearish Pin Bar Setup"
            else:
                setup_type = "Bearish Confluence Setup"

        risk_amount = account_size * (risk_percent / 100.0)
        stop_distance = abs(entry - stop_loss)

        if stop_distance <= 0:
            return jsonify({
                "error": "Stop distance was zero"
            }), 400

        position_size = risk_amount / stop_distance

        expected_rr = abs(
            take_profit_2 - entry
        ) / abs(
            entry - stop_loss
        )

        confidence = safe_float(signal_data.get("confidence"), 0)
        confluence = safe_float(signal_data.get("confluence_bonus"), 0)

        if confidence >= 85 and confluence >= 4:
            setup_quality = "A"
        elif confidence >= 75 and confluence >= 2:
            setup_quality = "B"
        else:
            setup_quality = "C"

        response_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "market": market,
            "timeframe": timeframe,
            "signal": trade_side,
            "setup_type": setup_type,
            "setup_quality": setup_quality,
            "pattern": pattern,
            "entry_price": round(entry, 4),
            "stop_loss": round(stop_loss, 4),
            "take_profit_1": round(take_profit_1, 4),
            "take_profit_2": round(take_profit_2, 4),
            "risk_percent": round(risk_percent, 2),
            "risk_amount": round(risk_amount, 2),
            "position_size": round(position_size, 4),
            "expected_rr": round(expected_rr, 2),
            "ma20": signal_data.get("ma20"),
            "ma50": signal_data.get("ma50"),
            "vwap": signal_data.get("vwap"),
            "support": support_price,
            "resistance": resistance_price,
            "breakout": breakout,
            "liquidity_event": signal_data.get("liquidity_event"),
            "trendline": trendline,
            "strategy_breakdown": signal_data.get("strategy_breakdown"),
            "confluence_bonus": confluence,
            "higher_timeframe_bias": mtf_data.get("higher_timeframe_bias"),
            "timeframe_alignment": mtf_data.get("timeframe_alignment"),
            "multi_timeframe": mtf_data.get("multi_timeframe"),
            "reason": ", ".join(signal_data.get("reasons") or []),
            "ai_summary": ai_text.get("ai_summary"),
            "trade_thesis": ai_text.get("trade_thesis"),
            "risk_note": ai_text.get("risk_note"),
            "session_label": session_data.get("session_label"),
            "active_sessions": session_data.get("active_sessions"),
            "liquidity_profile": session_data.get("liquidity_profile"),
            "utc_hour": session_data.get("utc_hour"),
            "daily_loss_status": daily_loss
        }

        print("[TRADEPLAN_SUCCESS]", {
            "market": market,
            "timeframe": timeframe,
            "signal": trade_side,
            "entry_price": entry,
            "stop_loss": stop_loss,
            "take_profit_1": take_profit_1,
            "take_profit_2": take_profit_2,
            "setup_type": setup_type
        })

        append_history(
            TRADEPLAN_HISTORY_FILE,
            response_data,
            max_items=200
        )

        return jsonify(response_data)

    except Exception as e:
        import traceback

        print("\n========== TRADEPLAN ROUTE ERROR ==========")
        print("ERROR:", str(e))
        traceback.print_exc()
        print("========== END TRADEPLAN ROUTE ERROR ==========\n")

        return jsonify({
            "error": "Trade plan generation failed",
            "details": str(e)
        }), 500



@app.route("/live-candles", methods=["GET"])
def live_candles():
    try:
        market = request.args.get("market", "").strip()
        timeframe = request.args.get("interval", "1h").strip().lower()

        if not market:
            return jsonify({"error": "No market provided"}), 400

        market = market.upper()

        print(f"📡 LIVE CANDLES request | market={market} timeframe={timeframe}", flush=True)

        # ✅ Fix timeframe mapping
        interval = INTERVAL_MAP.get(timeframe, "1h")

        # ✅ Fetch data
        df = fetch_live_market_data(
            market,
            interval=interval,
            outputsize=50
        )

        if df is None or df.empty:
            print(f"❌ No data returned for {market}", flush=True)
            return jsonify({
                "candles": [],
                "count": 0,
                "market": market
            })

        print(f"✅ Data fetched: {len(df)} rows", flush=True)
        print(f"📊 Columns: {list(df.columns)}", flush=True)

        # ✅ Build candles safely
        candles = []

        for _, row in df.iterrows():
            try:
                candles.append({
                    "time": str(row.get("Datetime") or row.get("datetime")),
                    "open": float(str(row["Open"]).replace(",", "").strip()),
                    "high": float(str(row["High"]).replace(",", "").strip()),
                    "low": float(str(row["Low"]).replace(",", "").strip()),
                    "close": float(str(row["Close"]).replace(",", "").strip())
                })
            except Exception as e:
                print(f"⚠️ Skipping row: {e}", flush=True)
                continue

        print(f"🚀 Returning {len(candles)} candles", flush=True)

        return jsonify({
            "candles": candles,
            "count": len(candles),
            "market": market
        })

    except Exception as e:
        import traceback
        print("❌ LIVE CANDLES ERROR:", str(e), flush=True)
        traceback.print_exc()

        return jsonify({
            "candles": [],
            "count": 0,
            "market": request.args.get("market", "")
        }), 200



@app.route("/presets", methods=["POST"])
def create_preset():
    try:
        body = get_request_body()

        new_preset = {
            "id": str(uuid.uuid4()),
            "name": body.get("name", "New Preset"),
            "market": body.get("market", "NASDAQ"),
            "timeframe": body.get("timeframe", "1day"),
            "risk_percent": body.get("risk_percent", 1),
            "account_size": body.get("account_size", 10000),
            "ma_period": body.get("ma_period", 20),
            "vwap_enabled": body.get("vwap_enabled", True),
            "atr_multiplier": body.get("atr_multiplier", 1.5),
            "created_at": datetime.utcnow().isoformat() + "Z"
        }

        presets = load_presets()
        presets.append(new_preset)
        save_presets(presets)

        return jsonify(new_preset)

    except Exception as e:
        return jsonify({
            "error": "Failed to create preset",
            "details": str(e)
        }), 500


@app.route("/presets/<preset_id>", methods=["PUT"])
def update_preset(preset_id):
    try:
        body = get_request_body()
        presets = load_presets()

        updated = None
        for preset in presets:
            if preset["id"] == preset_id:
                preset.update(body)
                updated = preset
                break

        if not updated:
            return jsonify({"error": "Preset not found"}), 404

        save_presets(presets)
        return jsonify(updated)

    except Exception as e:
        return jsonify({
            "error": "Failed to update preset",
            "details": str(e)
        }), 500


@app.route("/presets/<preset_id>", methods=["DELETE"])
def delete_preset(preset_id):
    try:
        presets = load_presets()
        filtered = [p for p in presets if p["id"] != preset_id]

        if len(filtered) == len(presets):
            return jsonify({"error": "Preset not found"}), 404

        save_presets(filtered)
        return jsonify({"success": True, "deleted_id": preset_id})

    except Exception as e:
        return jsonify({
            "error": "Failed to delete preset",
            "details": str(e)
        }), 500


@app.route("/presets/<preset_id>/duplicate", methods=["POST"])
def duplicate_preset(preset_id):
    try:
        presets = load_presets()

        original = None
        for preset in presets:
            if preset["id"] == preset_id:
                original = preset
                break

        if not original:
            return jsonify({"error": "Preset not found"}), 404

        clone = original.copy()
        clone["id"] = str(uuid.uuid4())
        clone["name"] = f"{original.get('name', 'Preset')} Copy"
        clone["created_at"] = datetime.utcnow().isoformat() + "Z"

        presets.append(clone)
        save_presets(presets)

        return jsonify(clone)

    except Exception as e:
        return jsonify({
            "error": "Failed to duplicate preset",
            "details": str(e)
        }), 500


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    try:
        print("🔥 HIT /create-checkout-session")

        data = request.get_json(silent=True) or {}
        print("🔥 CHECKOUT PAYLOAD:", data)

        price_id = data.get("price_id")
        user_id = data.get("user_id")
        plan = data.get("plan", "pro")
        success_url = data.get("success_url")
        cancel_url = data.get("cancel_url")

        if not price_id:
            return jsonify({"error": "price_id is required"}), 400

        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        if not success_url:
            return jsonify({"error": "success_url is required"}), 400

        if not cancel_url:
            return jsonify({"error": "cancel_url is required"}), 400

        print("🔥 CREATING STRIPE SESSION WITH 7 DAY TRIAL")

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1
                }
            ],
            subscription_data={
                "trial_period_days": 7
            },
            allow_promotion_codes=True,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": user_id,
                "plan": plan
            }
        )

        print("🔥 STRIPE SESSION CREATED:", checkout_session.id)

        return jsonify({
            "checkout_url": checkout_session.url,
            "id": checkout_session.id
        })

    except Exception as e:
        print("🔥 CHECKOUT ERROR:", str(e))
        return jsonify({
            "error": "Failed to create checkout session",
            "details": str(e)
        }), 500

def map_price_id_to_plan(price_id):
    pro_price_id = (os.environ.get("STRIPE_PRO_PRICE_ID") or "").strip()
    elite_price_id = (os.environ.get("STRIPE_ELITE_PRICE_ID") or "").strip()

    if price_id == elite_price_id:
        return "elite"
    if price_id == pro_price_id:
        return "pro"
    return "free"


def get_user_by_stripe_customer_id(customer_id):
    # TEMP: replace later with database lookup
    print("🔥 LOOKUP USER BY CUSTOMER:", customer_id)
    return {"id": "test_user"}  # temporary fake user


def update_user_subscription_status(
    user_id,
    subscription_status,
    effective_plan,
    stripe_customer_id=None,
    stripe_subscription_id=None,
    trial_end=None
):
    print("🔥 USER UPDATED:", {
        "user_id": user_id,
        "subscription_status": subscription_status,
        "effective_plan": effective_plan,
        "trial_end": trial_end
    })

def get_user_by_stripe_customer_id(customer_id):
    try:
        if not customer_id:
            return None

        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/user_subscriptions",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            },
            params={
                "select": "id,plan,status,stripe_customer_id,stripe_subscription_id,current_period_end,updated_at",
                "stripe_customer_id": f"eq.{customer_id}",
                "limit": "1"
            },
            timeout=20
        )
        response.raise_for_status()

        rows = response.json()
        if isinstance(rows, list) and rows:
            return rows[0]

        return None

    except Exception as e:
        print("🔥 get_user_by_stripe_customer_id ERROR:", str(e), flush=True)
        return None


def update_user_subscription_status(
    user_id,
    subscription_status,
    effective_plan,
    stripe_customer_id=None,
    stripe_subscription_id=None,
    trial_end=None
):
    try:
        print("🔥 WRITING TO SUPABASE START", flush=True)

        payload = {
            "id": user_id,
            "user_id": user_id,  # IMPORTANT
            "plan": subscription_status,
            "status": "trialing" if "trial" in subscription_status else "active",
            "stripe_customer_id": stripe_customer_id,
            "stripe_subscription_id": stripe_subscription_id,
            "current_period_end": trial_end,
            "updated_at": datetime.utcnow().isoformat()
        }

        print("🔥 PAYLOAD:", payload, flush=True)

        response = requests.post(
            f"{os.environ.get('SUPABASE_URL')}/rest/v1/user_subscriptions",
            headers={
                "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
                "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY')}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates"
            },
            json=payload
        )

        print("🔥 SUPABASE STATUS:", response.status_code, flush=True)
        print("🔥 SUPABASE RESPONSE:", response.text, flush=True)

    except Exception as e:
        print("🔥 SUPABASE ERROR:", str(e), flush=True)


@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    try:
        print("🔥 WEBHOOK HIT", flush=True)

        event = request.get_json(force=True, silent=True)

        if not event:
            print("🔥 NO JSON", flush=True)
            return jsonify({"error": "No JSON"}), 400

        event_type = event.get("type")
        data = event.get("data", {}).get("object", {})

        print("🔥 EVENT:", event_type, flush=True)

        if event_type == "checkout.session.completed":
            print("🔥 CHECKOUT HIT", flush=True)

            metadata = data.get("metadata", {}) or {}
            user_id = metadata.get("user_id")
            plan = metadata.get("plan", "pro")

            customer_id = data.get("customer")
            subscription_id = data.get("subscription")

            print("🔥 USER:", user_id, flush=True)
            print("🔥 PLAN:", plan, flush=True)
            print("🔥 CUSTOMER:", customer_id, flush=True)
            print("🔥 SUB:", subscription_id, flush=True)

            if not user_id:
                print("🔥 ERROR: Missing user_id", flush=True)
                return jsonify({"error": "Missing user_id"}), 200

            trial_end_ts = None
            in_trial = True

            if subscription_id:
                try:
                    sub = stripe.Subscription.retrieve(subscription_id)
                    trial_end_ts = sub.get("trial_end")

                    now_ts = int(datetime.utcnow().timestamp())
                    in_trial = bool(trial_end_ts and trial_end_ts > now_ts)

                except Exception as sub_error:
                    print("🔥 SUB FETCH ERROR:", str(sub_error), flush=True)

            if plan == "elite":
                subscription_status = "trial_elite" if in_trial else "elite"
                effective_plan = "elite"
            else:
                subscription_status = "trial_pro" if in_trial else "pro"
                effective_plan = "pro"

            trial_end_iso = (
                datetime.utcfromtimestamp(trial_end_ts).isoformat() + "Z"
                if trial_end_ts else None
            )

            print("🔥 FINAL STATUS:", subscription_status, flush=True)

            try:
                update_user_subscription_status(
                    user_id=user_id,
                    subscription_status=subscription_status,
                    effective_plan=effective_plan,
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=subscription_id,
                    trial_end=trial_end_iso
                )
            except Exception as db_error:
                print("🔥 SUPABASE ERROR:", str(db_error), flush=True)

        return jsonify({"received": True}), 200

    except Exception as e:
        print("🔥 WEBHOOK CRASH:", str(e), flush=True)
        return jsonify({
            "error": "Webhook crashed",
            "details": str(e)
        }), 500

def run_strategy_backtest(df, strategy_name):
    df = add_indicators(df.copy())
    trades = []

    min_bars = 20
    lookahead_bars = 12
    rr_multiple = 2.0
    breakeven_trigger_r = 1.0
    trailing_trigger_r = 1.5
    trailing_buffer_r = 0.5

    if len(df) < (min_bars + lookahead_bars + 1):
        return trades

    for i in range(min_bars, len(df) - lookahead_bars):
        history = df.iloc[: i + 1].copy()
        row = history.iloc[-1]

        try:
            if strategy_name == "trendline":
                result = trendline_strategy(history)

            elif strategy_name == "breakout":
                result = breakout_strategy(row)

            elif strategy_name == "confluence":
                bullish = 0
                bearish = 0

                ma_result = ma_trend_strategy(row)
                vwap_result = vwap_strategy(row)
                sr_result = support_resistance_strategy(row)
                liq_result = liquidity_sweep_strategy(row)

                bullish += int(ma_result.get("bullish", 0) or 0) * 2
                bearish += int(ma_result.get("bearish", 0) or 0) * 2

                bullish += int(vwap_result.get("bullish", 0) or 0) * 2
                bearish += int(vwap_result.get("bearish", 0) or 0) * 2

                bullish += int(sr_result.get("bullish", 0) or 0) * 1
                bearish += int(sr_result.get("bearish", 0) or 0) * 1

                bullish += int(liq_result.get("bullish", 0) or 0) * 3
                bearish += int(liq_result.get("bearish", 0) or 0) * 3

                result = {
                    "bullish": bullish,
                    "bearish": bearish
                }

            else:
                continue

            if not isinstance(result, dict):
                continue

            bullish_points = int(result.get("bullish", 0) or 0)
            bearish_points = int(result.get("bearish", 0) or 0)

            total_strength = bullish_points + bearish_points

            if bullish_points == bearish_points:
                continue

            if total_strength < 3:
                continue

            direction = "buy" if bullish_points > bearish_points else "sell"
            entry_price = float(row["Close"])

            recent_rows = history.tail(14)
            atr_series = recent_rows["High"].astype(float) - recent_rows["Low"].astype(float)
            atr = float(atr_series.mean()) if len(atr_series) > 0 else 0.0

            if not pd.notna(atr) or atr <= 0:
                atr = abs(entry_price) * 0.01

            risk_per_unit = atr
            reward_per_unit = atr * rr_multiple

            if direction == "buy":
                stop_loss = entry_price - risk_per_unit
                take_profit = entry_price + reward_per_unit
            else:
                stop_loss = entry_price + risk_per_unit
                take_profit = entry_price - reward_per_unit

            initial_stop_loss = stop_loss
            future_rows = df.iloc[i + 1 : i + 1 + lookahead_bars].copy()

            if future_rows.empty:
                continue

            outcome = "expired"
            exit_reason = "time_expired"
            exit_price = float(future_rows.iloc[-1]["Close"])
            pnl = 0.0
            moved_to_breakeven = False
            trailing_active = False

            for _, future_row in future_rows.iterrows():
                high_price = float(future_row["High"])
                low_price = float(future_row["Low"])
                close_price = float(future_row["Close"])

                if direction == "buy":
                    max_favorable_move = high_price - entry_price

                    if (not moved_to_breakeven) and max_favorable_move >= (risk_per_unit * breakeven_trigger_r):
                        stop_loss = max(stop_loss, entry_price)
                        moved_to_breakeven = True

                    if max_favorable_move >= (risk_per_unit * trailing_trigger_r):
                        trailing_active = True
                        trailing_stop = high_price - (risk_per_unit * trailing_buffer_r)
                        stop_loss = max(stop_loss, trailing_stop)

                    if low_price <= stop_loss:
                        exit_price = stop_loss
                        if exit_price > entry_price:
                            outcome = "win"
                            exit_reason = "trailing_stop"
                        elif abs(exit_price - entry_price) < 1e-9:
                            outcome = "expired"
                            exit_reason = "breakeven_stop"
                        else:
                            outcome = "loss"
                            exit_reason = "stop_loss"
                        pnl = exit_price - entry_price
                        break

                    if high_price >= take_profit:
                        outcome = "win"
                        exit_reason = "take_profit"
                        exit_price = take_profit
                        pnl = reward_per_unit
                        break

                    # Early weakness exit on bearish reversal after some positive movement
                    if close_price < entry_price and moved_to_breakeven:
                        outcome = "expired"
                        exit_reason = "momentum_fade"
                        exit_price = close_price
                        pnl = exit_price - entry_price
                        break

                    exit_price = close_price
                    pnl = exit_price - entry_price

                else:
                    max_favorable_move = entry_price - low_price

                    if (not moved_to_breakeven) and max_favorable_move >= (risk_per_unit * breakeven_trigger_r):
                        stop_loss = min(stop_loss, entry_price)
                        moved_to_breakeven = True

                    if max_favorable_move >= (risk_per_unit * trailing_trigger_r):
                        trailing_active = True
                        trailing_stop = low_price + (risk_per_unit * trailing_buffer_r)
                        stop_loss = min(stop_loss, trailing_stop)

                    if high_price >= stop_loss:
                        exit_price = stop_loss
                        if exit_price < entry_price:
                            outcome = "win"
                            exit_reason = "trailing_stop"
                        elif abs(exit_price - entry_price) < 1e-9:
                            outcome = "expired"
                            exit_reason = "breakeven_stop"
                        else:
                            outcome = "loss"
                            exit_reason = "stop_loss"
                        pnl = entry_price - exit_price
                        break

                    if low_price <= take_profit:
                        outcome = "win"
                        exit_reason = "take_profit"
                        exit_price = take_profit
                        pnl = reward_per_unit
                        break

                    # Early weakness exit on bullish reversal after some positive movement
                    if close_price > entry_price and moved_to_breakeven:
                        outcome = "expired"
                        exit_reason = "momentum_fade"
                        exit_price = close_price
                        pnl = entry_price - exit_price
                        break

                    exit_price = close_price
                    pnl = entry_price - exit_price

            trades.append({
                "strategy": strategy_name,
                "direction": direction,
                "entry": round(entry_price, 4),
                "initial_stop_loss": round(initial_stop_loss, 4),
                "final_stop_loss": round(float(stop_loss), 4),
                "take_profit": round(take_profit, 4),
                "exit_price": round(float(exit_price), 4),
                "result": outcome,
                "exit_reason": exit_reason,
                "used_breakeven": moved_to_breakeven,
                "used_trailing": trailing_active,
                "pnl": round(float(pnl), 4)
            })

        except Exception as e:
            print(f"❌ run_strategy_backtest error ({strategy_name} @ {i}): {str(e)}", flush=True)
            continue

    return trades


@app.route("/run-full-backtest", methods=["POST"])
def run_full_backtest():
    try:
        results = []
        markets = ["Forex", "Gold", "NaturalGas", "NASDAQ", "DowJones", "Futures"]
        strategies = ["trendline", "breakout", "confluence"]

        for market in markets:
            try:
                df = fetch_live_market_data(market, interval="1h", outputsize=300)

                if df is None or df.empty:
                    print(f"❌ market error {market}: no data returned", flush=True)
                    continue

                for strategy in strategies:
                    try:
                        trades = run_strategy_backtest(df.copy(), strategy)

                        if not trades:
                            continue

                        wins = sum(1 for t in trades if t.get("result") == "win")
                        losses = sum(1 for t in trades if t.get("result") == "loss")
                        total_trades = len(trades)

                        resolved = wins + losses
                        win_rate = round((wins / resolved) * 100, 1) if resolved > 0 else 0.0

                        gross_profit = sum(float(t.get("pnl", 0)) for t in trades if float(t.get("pnl", 0)) > 0)
                        gross_loss = abs(sum(float(t.get("pnl", 0)) for t in trades if float(t.get("pnl", 0)) < 0))
                        net_profit = round(sum(float(t.get("pnl", 0)) for t in trades), 2)

                        if gross_loss > 0:
                            profit_factor = round(gross_profit / gross_loss, 2)
                        else:
                            profit_factor = round(gross_profit, 2) if gross_profit > 0 else 0.0

                        expectancy = round(net_profit / total_trades, 2) if total_trades > 0 else 0.0

                        results.append({
                            "market": market,
                            "strategy": strategy,
                            "trades": total_trades,
                            "wins": wins,
                            "losses": losses,
                            "win_rate": win_rate,
                            "profit_factor": profit_factor,
                            "expectancy": expectancy,
                            "net_profit": net_profit
                        })

                    except Exception as strat_error:
                        print(f"❌ strategy error {market}-{strategy}: {strat_error}", flush=True)

            except Exception as market_error:
                print(f"❌ market error {market}: {str(market_error)}", flush=True)

        # Filter out low sample-size results first
        filtered_results = []
        for r in results:
            if r.get("trades", 0) >= 20:
                filtered_results.append(r)

        # fallback if everything gets filtered out
        if len(filtered_results) == 0:
            filtered_results = results

        # Rank best strategies
        filtered_results = sorted(
            filtered_results,
            key=lambda x: (
                x.get("profit_factor", 0),
                x.get("win_rate", 0),
                x.get("net_profit", 0)
            ),
            reverse=True
        )

        return jsonify({
            "status": "success",
            "results": filtered_results[:20]
        })

    except Exception as e:
        print(f"❌ FULL BACKTEST CRASH: {str(e)}", flush=True)
        return jsonify({"error": str(e)}), 500

@app.route("/trade-thesis", methods=["POST"])
def trade_thesis():
    try:
        print("🔥 /trade-thesis HIT", flush=True)

        data = request.get_json(silent=True) or {}
        print(f"🔥 incoming data: {data}", flush=True)

        return jsonify({
            "status": "success",
            "analysis": "AI CONNECTED SUCCESSFULLY"
        })

    except Exception as e:
        print(f"❌ ERROR: {str(e)}", flush=True)
        return jsonify({"error": str(e)}), 500

@app.route("/api/video-health", methods=["GET"])
def video_health():
    return jsonify({
        "ok": True,
        "service": "video-backend",
        "youtube_ingest_route_available": True
    })

@app.route("/api/youtube-ingest", methods=["POST"])
def youtube_ingest():
    try:
        import os
        import requests
        from youtube_transcript_api import YouTubeTranscriptApi
        from urllib.parse import urlparse, parse_qs

        data = request.get_json(silent=True) or {}
        text = data.get("text")
        youtube_url = data.get("youtube_url") or data.get("url")

        def extract_video_id(url):
            parsed = urlparse(url)
            if "youtu.be" in parsed.netloc:
                return parsed.path.strip("/")
            if "youtube.com" in parsed.netloc:
                return parse_qs(parsed.query).get("v", [None])[0]
            return None

        if text:
            transcript_text = text
            source_type = "manual_text"
        elif youtube_url:
            video_id = extract_video_id(youtube_url)
            if not video_id:
                return jsonify({"ok": False, "error": "Invalid YouTube URL"}), 400

            transcript = YouTubeTranscriptApi.get_transcript(video_id)
            transcript_text = " ".join([item.get("text", "") for item in transcript])
            source_type = "youtube_transcript_api"
        else:
            return jsonify({"ok": False, "error": "Missing text or youtube_url"}), 400

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return jsonify({"ok": False, "error": "Missing ANTHROPIC_API_KEY"}), 500

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1600,
            "messages": [
                {
                    "role": "user",
                    "content": f"""
Analyze this trading transcript and extract a structured trading strategy.

Return:
- strategy name
- markets
- direction
- entry rules
- exit rules
- stop loss rules
- take profit rules
- risk rules
- conditions
- key insights
- parameter adjustments
- action items

Transcript:
{transcript_text}
"""
                }
            ]
        }

        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=60
        )

        if r.status_code >= 400:
            return jsonify({
                "ok": False,
                "error": r.text
            }), r.status_code

        return jsonify({
            "ok": True,
            "source_type": source_type,
            "transcript_char_count": len(transcript_text),
            "anthropic_response": r.json()
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
