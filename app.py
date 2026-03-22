from flask import Flask, jsonify, request
from flask_cors import CORS
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
import websocket


stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

app = Flask(__name__)
CORS(app)

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
    "Forex": "EUR/USD",
    "Gold": "XAU/USD",
    "NaturalGas": "UNG",
    "NASDAQ": "QQQ",
    "DowJones": "DIA",
    "Futures": "SPY"
}

LIVE_SCAN_CACHE = {
    "last_updated": None,
    "status": "idle",
    "results": None
}

LIVE_MARKET_STATE = {
    "NASDAQ": {},
    "Gold": {},
    "Forex": {},
    "NaturalGas": {},
    "DowJones": {},
    "Futures": {}
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


# -----------------------------
# BASIC ROUTES
# -----------------------------
@app.route("/")
def home():
    ensure_live_engine_started()
    return "WickSense API is running!"

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
            "/backtest": {
                "post": {
                    "summary": "Run a backtest",
                    "responses": {
                        "200": {
                            "description": "Backtest results"
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
    body = get_request_body()
    return body.get("market")


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


def get_float_from_request(key, default_value):
body = get_request_body()
value = body.get(key, default_value)
try:
return float(value)
except Exception:
return float(default_value)

def get_float_from_request(key, default=None):
    try:
        return float(request.args.get(key, default))
    except:
        return default


def safe_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default

def update_live_candle(market, price):
    global LIVE_MARKET_STATE

    state = LIVE_MARKET_STATE.get(market, {})
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

    LIVE_MARKET_STATE[market] = state

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

def get_current_live_top_trade():
    best_trade = None
    best_score = -1

    for market_name, data in LIVE_MARKET_STATE.items():
        confidence = safe_float(data.get("confidence"), 0.0)

        if confidence > best_score and data.get("signal") not in [None, "Neutral"]:
            best_score = confidence
            best_trade = {
                "market": market_name,
                "signal": data.get("signal"),
                "setup_type": data.get("setup_type"),
                "confidence": confidence
            }

    return best_trade


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
    
def update_live_signal(market):
    global LIVE_MARKET_STATE

    state = LIVE_MARKET_STATE.get(market, {})
    previous_state = state.copy()
    current_candle = state.get("current_candle")
    completed_candles = state.get("completed_candles", [])

    if not current_candle:
        return

    candles = completed_candles + [current_candle]

    if len(candles) < 20:
        wick_data = calculate_live_wicks(current_candle)
        state["upper_wick"] = wick_data["upper_wick"]
        state["lower_wick"] = wick_data["lower_wick"]
        LIVE_MARKET_STATE[market] = state
        return

    df = pd.DataFrame(candles)

    signal_data = evaluate_signal(df)
    ai_text = build_ai_explanation(signal_data)
    setup_type = get_setup_type(signal_data)
    wick_data = calculate_live_wicks(current_candle)

    new_payload = {
        "market": market,
        "open": safe_float(current_candle.get("Open")),
        "high": safe_float(current_candle.get("High")),
        "low": safe_float(current_candle.get("Low")),
        "close": safe_float(current_candle.get("Close")),
        "upper_wick": wick_data["upper_wick"],
        "lower_wick": wick_data["lower_wick"],
        "signal": signal_data.get("signal"),
        "confidence": signal_data.get("confidence"),
        "pattern": signal_data.get("pattern"),
        "breakout": signal_data.get("breakout"),
        "liquidity_event": signal_data.get("liquidity_event"),
        "trendline": signal_data.get("trendline"),
        "strategy_breakdown": signal_data.get("strategy_breakdown"),
        "confluence_bonus": signal_data.get("confluence_bonus"),
        "setup_type": setup_type,
        "ai_summary": ai_text.get("ai_summary"),
        "trade_thesis": ai_text.get("trade_thesis"),
        "risk_note": ai_text.get("risk_note")
    }

    state.update(new_payload)
    LIVE_MARKET_STATE[market] = state

    if has_live_signal_changed(previous_state, new_payload):
        handle_live_signal_change(market, previous_state, new_payload)

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

    for market in LIVE_MARKET_STATE.keys():
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

        LIVE_MARKET_STATE[market] = {
            "completed_candles": completed_candles,
            "current_candle": completed_candles[-1].copy(),
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }

        update_live_signal(market)

def run_live_signal_engine():
    global STREAM_STATUS

    STREAM_STATUS["status"] = "connected"
    STREAM_STATUS["provider"] = "simulated"

    while True:
        try:
            for market in LIVE_MARKET_STATE.keys():
                state = LIVE_MARKET_STATE.get(market, {})
                current_candle = state.get("current_candle")

                if current_candle:
                    base_price = safe_float(current_candle.get("Close"), get_simulated_base_price(market))
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

            STREAM_STATUS["last_tick"] = datetime.utcnow().isoformat() + "Z"
            time.sleep(2)

        except Exception as e:
            STREAM_STATUS["status"] = "error"
            STREAM_STATUS["last_error"] = str(e)
            time.sleep(5)

def get_twelvedata_symbol(market):
    mapping = {
        "NASDAQ": "QQQ",
        "DowJones": "DIA",
        "Gold": "XAU/USD",
        "NaturalGas": "NG",
        "Forex": "EUR/USD",
        "Futures": "ES"
    }
    return mapping.get(market)

def start_twelvedata_stream():
    global STREAM_STATUS

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
                    "NG": "NaturalGas",
                    "EUR/USD": "Forex",
                    "ES": "Futures"
                }

                market = market_map.get(symbol)

                if market and price:
                    update_live_candle(market, price)
                    update_live_signal(market)
                    check_for_live_top_trade_change()

                    STREAM_STATUS["last_tick"] = datetime.utcnow().isoformat() + "Z"

        except Exception as e:
            print(f"WebSocket message error: {e}")

    def on_open(ws):
        STREAM_STATUS["status"] = "connected"
        STREAM_STATUS["provider"] = "twelvedata"

        symbols = ["QQQ", "DIA", "XAU/USD", "NG", "EUR/USD", "ES"]

        subscribe_message = {
            "action": "subscribe",
            "params": {
                "symbols": ",".join(symbols)
            }
        }

        ws.send(json.dumps(subscribe_message))

    def on_error(ws, error):
        STREAM_STATUS["status"] = "error"
        print(f"WebSocket error: {error}")

    def on_close(ws, close_status_code, close_msg):
        STREAM_STATUS["status"] = "disconnected"
        print("WebSocket closed")

    ws_url = f"wss://ws.twelvedata.com/v1/quotes/price?apikey={TWELVE_DATA_API_KEY}"

    ws = websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_open=on_open,
        on_error=on_error,
        on_close=on_close
    )

    ws.run_forever()

def ensure_live_engine_started():
    global LIVE_ENGINE_STARTED

    if LIVE_ENGINE_STARTED:
        return

    with LIVE_ENGINE_LOCK:
        if LIVE_ENGINE_STARTED:
            return

        seed_live_market_state()

        if TWELVE_DATA_API_KEY:
            live_signal_thread = threading.Thread(
                target=start_twelvedata_stream,
                daemon=True
            )
        else:
            live_signal_thread = threading.Thread(
                target=run_live_signal_engine,
                daemon=True
            )

        live_signal_thread.start()
        LIVE_ENGINE_STARTED = True

def get_string_from_request(key, default_value):
    body = get_request_body()
    return body.get(key, default_value)


def validate_market_df(df: pd.DataFrame):
    required_cols = ["Open", "High", "Low", "Close"]
    missing = [c for c in required_cols if c not in df.columns]
    return missing


def fetch_live_market_data(market: str, interval: str = "1day", outputsize: int = 50):
    api_key = os.environ.get("TWELVE_DATA_API_KEY")
    if not api_key:
        raise ValueError("TWELVE_DATA_API_KEY is missing in Render environment variables")

    symbol = MARKET_SYMBOLS.get(market)
    if not symbol:
        raise ValueError(f"No live symbol mapping found for market: {market}")

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": api_key
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    if "values" not in data:
        raise ValueError(f"Twelve Data returned no values for {market}: {data}")

    rows = []
    for row in reversed(data["values"]):
        rows.append({
            "Open": float(row["open"]),
            "High": float(row["high"]),
            "Low": float(row["low"]),
            "Close": float(row["close"])
        })

    df = pd.DataFrame(rows)

    missing = validate_market_df(df)
    if missing:
        raise ValueError(f"Live data missing required columns: {missing}")

    return df


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


def load_history(filepath):
    ensure_history_file(filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


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


def detect_wick_pattern(row):
    body = abs(row["Close"] - row["Open"])
    upper_wick = row["UpperWick"]
    lower_wick = row["LowerWick"]
    candle_range = row["Range"] if row["Range"] != 0 else 1

    if body <= candle_range * 0.15:
        return "Doji"

    if lower_wick > body * 2 and upper_wick <= body * 0.5:
        return "Hammer"

    if upper_wick > body * 2 and lower_wick <= body * 0.5:
        return "Shooting Star"

    if (lower_wick > body * 1.5 or upper_wick > body * 1.5) and body <= candle_range * 0.35:
        return "Pin Bar"

    return None


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

    return {"bullish": bullish, "bearish": bearish, "reasons": reasons}


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


def evaluate_signal(df: pd.DataFrame):
    df = add_indicators(df)
    row = df.iloc[-1]

    close_price = float(row["Close"])
    open_price = float(row["Open"])
    upper_wick = float(row["UpperWick"])
    lower_wick = float(row["LowerWick"])
    ma20 = float(row["MA20"]) if pd.notna(row["MA20"]) else close_price
    ma50 = float(row["MA50"]) if pd.notna(row["MA50"]) else close_price
    vwap = float(row["VWAP"]) if pd.notna(row["VWAP"]) else close_price
    support = float(row["Support"]) if pd.notna(row["Support"]) else float(row["Low"])
    resistance = float(row["Resistance"]) if pd.notna(row["Resistance"]) else float(row["High"])

    pattern = detect_wick_pattern(row)

    strategies = {
        "wick_strategy": wick_strategy(row, pattern),
        "ma_trend_strategy": ma_trend_strategy(row),
        "vwap_strategy": vwap_strategy(row),
        "support_resistance_strategy": support_resistance_strategy(row),
        "breakout_strategy": breakout_strategy(row),
        "liquidity_sweep_strategy": liquidity_sweep_strategy(row),
        "trendline_strategy": trendline_strategy(df)
    }

    bullish_points = sum(s["bullish"] for s in strategies.values())
    bearish_points = sum(s["bearish"] for s in strategies.values())

    reasons = []
    for s in strategies.values():
        reasons.extend(s["reasons"])

    confluence_bonus = 0

    trend_dir = strategies["ma_trend_strategy"]["bullish"] - strategies["ma_trend_strategy"]["bearish"]
    vwap_dir = strategies["vwap_strategy"]["bullish"] - strategies["vwap_strategy"]["bearish"]
    sr_dir = strategies["support_resistance_strategy"]["bullish"] - strategies["support_resistance_strategy"]["bearish"]
    wick_dir = strategies["wick_strategy"]["bullish"] - strategies["wick_strategy"]["bearish"]
    breakout = strategies["breakout_strategy"]["breakout"]
    liquidity_event = strategies["liquidity_sweep_strategy"]["liquidity_event"]
    trendline = strategies["trendline_strategy"]["trendline"]

    if trend_dir > 0 and vwap_dir > 0:
        bullish_points += 2
        confluence_bonus += 2
        reasons.append("Trend + VWAP bullish confluence")

    if trend_dir < 0 and vwap_dir < 0:
        bearish_points += 2
        confluence_bonus += 2
        reasons.append("Trend + VWAP bearish confluence")

    if sr_dir > 0 and wick_dir > 0:
        bullish_points += 2
        confluence_bonus += 2
        reasons.append("Support + wick reversal confluence")

    if sr_dir < 0 and wick_dir < 0:
        bearish_points += 2
        confluence_bonus += 2
        reasons.append("Resistance + wick rejection confluence")

    if breakout == "Bullish Breakout" and trend_dir > 0:
        bullish_points += 2
        confluence_bonus += 2
        reasons.append("Breakout + trend continuation")

    if breakout == "Bearish Breakdown" and trend_dir < 0:
        bearish_points += 2
        confluence_bonus += 2
        reasons.append("Breakout + trend continuation")

    if liquidity_event == "Bullish Liquidity Sweep" and sr_dir > 0:
        bullish_points += 2
        confluence_bonus += 2
        reasons.append("Liquidity sweep + support confluence")

    if liquidity_event == "Bearish Liquidity Sweep" and sr_dir < 0:
        bearish_points += 2
        confluence_bonus += 2
        reasons.append("Liquidity sweep + resistance confluence")

    if trendline == "Rising Trendline Support":
        bullish_points += 1
        reasons.append("Trendline support bounce")

    if trendline == "Falling Trendline Resistance":
        bearish_points += 1
        reasons.append("Trendline resistance rejection")

    if close_price > open_price:
        bullish_points += 1
        reasons.append("Bullish candle close")
    elif close_price < open_price:
        bearish_points += 1
        reasons.append("Bearish candle close")

    if bullish_points > bearish_points:
        signal_type = "Bullish"
    elif bearish_points > bullish_points:
        signal_type = "Bearish"
    else:
        signal_type = "Neutral"

    total_points = bullish_points + bearish_points
    confidence = 50 if total_points == 0 else round((max(bullish_points, bearish_points) / total_points) * 100, 2)

    strategy_breakdown = {}
    for name, s in strategies.items():
        if s["bullish"] > s["bearish"]:
            direction = "Bullish"
        elif s["bearish"] > s["bullish"]:
            direction = "Bearish"
        else:
            direction = "Neutral"

        strategy_breakdown[name] = {
            "direction": direction,
            "bullish_score": s["bullish"],
            "bearish_score": s["bearish"],
            "reasons": s["reasons"]
        }

    return {
        "signal": signal_type,
        "confidence": confidence,
        "reasons": reasons,
        "pattern": pattern,
        "ma20": round(ma20, 4),
        "ma50": round(ma50, 4),
        "vwap": round(vwap, 4),
        "support": round(support, 4),
        "resistance": round(resistance, 4),
        "upper_wick": round(upper_wick, 4),
        "lower_wick": round(lower_wick, 4),
        "breakout": breakout,
        "liquidity_event": liquidity_event,
        "trendline": trendline,
        "strategy_breakdown": strategy_breakdown,
        "confluence_bonus": confluence_bonus
    }


def evaluate_signal_from_market(market: str, timeframe: str, outputsize: int = 30):
    normalized_timeframe = normalize_interval(timeframe)
    df = fetch_live_market_data(market, interval=normalized_timeframe, outputsize=outputsize)
    signal_data = evaluate_signal(df)
    last_row = df.iloc[-1]

    return {
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


def get_multi_timeframe_confirmation(market: str, base_timeframe: str):
    normalized = normalize_interval(base_timeframe)

    timeframe_map = {
        "15min": ["15min", "1h"],
        "1h": ["1h", "4h"],
        "4h": ["4h", "1day"],
        "1day": ["1day"]
    }

    timeframes = timeframe_map.get(normalized, [normalized])

    multi_timeframe = {}
    bullish_count = 0
    bearish_count = 0

    for tf in timeframes:
        try:
            tf_signal = evaluate_signal_from_market(market, tf)

            multi_timeframe[tf] = {
                "signal": tf_signal["signal"],
                "confidence": tf_signal["confidence"],
                "pattern": tf_signal["pattern"]
            }

            if tf_signal["signal"] == "Bullish":
                bullish_count += 1
            elif tf_signal["signal"] == "Bearish":
                bearish_count += 1

        except Exception as e:
            multi_timeframe[tf] = {"error": str(e)}

    if bullish_count > bearish_count and bullish_count >= 2:
        alignment = "Strong Bullish Alignment"
        bias = "Bullish"
    elif bearish_count > bullish_count and bearish_count >= 2:
        alignment = "Strong Bearish Alignment"
        bias = "Bearish"
    elif bullish_count > bearish_count:
        alignment = "Mild Bullish Alignment"
        bias = "Bullish"
    elif bearish_count > bullish_count:
        alignment = "Mild Bearish Alignment"
        bias = "Bearish"
    else:
        alignment = "Mixed / Neutral"
        bias = "Neutral"

    return {
        "multi_timeframe": multi_timeframe,
        "higher_timeframe_bias": bias,
        "timeframe_alignment": alignment
    }


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

    if signal_type == "Bullish":
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
        elif signal_data.get("liquidity_event") == "Bullish Liquidity Sweep":
            return "Bullish Liquidity Sweep Reversal"
        else:
            return "Bullish Confluence Setup"

    if signal_type == "Bearish":
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
        elif signal_data.get("liquidity_event") == "Bearish Liquidity Sweep":
            return "Bearish Liquidity Sweep Reversal"
        else:
            return "Bearish Confluence Setup"

    return "Neutral / No Clear Setup"


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
    session_data = get_market_session()

    for market in markets:
        try:
            df = fetch_live_market_data(market, "15min", 15)
            signal_data = evaluate_signal(df)
            ai_text = build_ai_explanation(signal_data)
            setup_type = get_setup_type(signal_data)
            last_row = df.iloc[-1]

            reason_text = ", ".join(signal_data["reasons"])
            entry_price = float(last_row["Close"])

            opportunity_score = (
                signal_data["confidence"]
                + signal_data["confluence_bonus"] * 5
                + (10 if signal_data["breakout"] else 0)
                + (5 if signal_data["trendline"] else 0)
                + (5 if signal_data["liquidity_event"] else 0)
            )

            result = {
                "market": market,
                "signal": signal_data["signal"],
                "setup_type": setup_type,
                "confidence": signal_data["confidence"],
                "opportunity_score": opportunity_score,
                "entry": entry_price,
                "reason": reason_text,
                "pattern": signal_data["pattern"],
                "breakout": signal_data["breakout"],
                "liquidity_event": signal_data["liquidity_event"],
                "trendline": signal_data["trendline"],
                "strategy_breakdown": signal_data["strategy_breakdown"],
                "ai_summary": ai_text["ai_summary"],
                "trade_thesis": ai_text["trade_thesis"],
                "risk_note": ai_text["risk_note"],
                "session_label": session_data["session_label"],
                "active_sessions": session_data["active_sessions"],
                "liquidity_profile": session_data["liquidity_profile"]
            }

            scan_results.append(result)

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
                        signal=signal_data["signal"],
                        confidence=signal_data["confidence"],
                        reason=reason_text,
                        entry=entry_price,
                        pattern=signal_data["pattern"],
                        setup_type=setup_type,
                        ai_summary=ai_text["ai_summary"],
                        trade_thesis=ai_text["trade_thesis"],
                        risk_note=ai_text["risk_note"]
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
            print(f"Scan error: {e}")
            scan_results.append({
                "market": market,
                "error": str(e)
            })

    valid_results = [r for r in scan_results if "error" not in r]

    bullish_results = [r for r in valid_results if r["signal"] == "Bullish"]
    bearish_results = [r for r in valid_results if r["signal"] == "Bearish"]
    breakout_results = [r for r in valid_results if r.get("breakout") is not None]
    trendline_results = [r for r in valid_results if r.get("trendline") is not None]

    bullish_results = sorted(bullish_results, key=lambda x: x["opportunity_score"], reverse=True)
    bearish_results = sorted(bearish_results, key=lambda x: x["opportunity_score"], reverse=True)
    breakout_results = sorted(breakout_results, key=lambda x: x["opportunity_score"], reverse=True)
    trendline_results = sorted(trendline_results, key=lambda x: x["opportunity_score"], reverse=True)
    all_results_sorted = sorted(valid_results, key=lambda x: x["opportunity_score"], reverse=True)

    return {
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
    try:
        ensure_live_engine_started()
        return jsonify(STREAM_STATUS)
    except Exception as e:
        return jsonify({
            "error": "Failed to load stream status",
            "details": str(e)
        }), 500


@app.route("/live-signals", methods=["GET"])
def live_signals():
    try:
        ensure_live_engine_started()

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
                "risk_note": data.get("risk_note")
            }
            markets.append(market_payload)

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


@app.route("/live-top-trade", methods=["GET"])
def live_top_trade():
    try:
        ensure_live_engine_started()

        best_trade = None
        best_score = -1

        for market_name, data in LIVE_MARKET_STATE.items():
            confidence = safe_float(data.get("confidence"), 0.0)

            if confidence > best_score:
                best_score = confidence
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
                    "risk_note": data.get("risk_note")
                }

        return jsonify(best_trade or {})

    except Exception as e:
        return jsonify({
            "error": "Failed to load live top trade",
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
@app.route("/signal", methods=["POST"])
def signal():
    try:
        market = get_market_from_request()
        timeframe = normalize_interval(get_string_from_request("timeframe", "1day"))

        if not market:
            return jsonify({"error": "No market was provided"}), 400

        df = fetch_live_market_data(market, interval=timeframe, outputsize=30)
        signal_data = evaluate_signal(df)
        ai_text = build_ai_explanation(signal_data)
        setup_type = get_setup_type(signal_data)
        mtf_data = get_multi_timeframe_confirmation(market, timeframe)
        session_data = get_market_session()
        last_row = df.iloc[-1]

        response_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "market": market,
            "timeframe": timeframe,
            "signal": signal_data["signal"],
            "setup_type": setup_type,
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
            "higher_timeframe_bias": mtf_data["higher_timeframe_bias"],
            "timeframe_alignment": mtf_data["timeframe_alignment"],
            "multi_timeframe": mtf_data["multi_timeframe"],
            "reason": ", ".join(signal_data["reasons"]),
            "ai_summary": ai_text["ai_summary"],
            "trade_thesis": ai_text["trade_thesis"],
            "risk_note": ai_text["risk_note"],
            "session_label": session_data["session_label"],
            "active_sessions": session_data["active_sessions"],
            "liquidity_profile": session_data["liquidity_profile"],
            "utc_hour": session_data["utc_hour"]
        }

        append_history(SIGNAL_HISTORY_FILE, response_data, max_items=200)
        return jsonify(response_data)

    except Exception as e:
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
        timeframe = normalize_interval(get_string_from_request("timeframe", "1day"))
        _ = get_string_from_request("start_date", "")
        _ = get_string_from_request("end_date", "")

        if not market:
            return jsonify({"error": "No market was provided"}), 400

        df = fetch_live_market_data(market, interval=timeframe, outputsize=50)
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

        return jsonify({
            "market": market,
            "timeframe": timeframe,
            "results": results,
            "equity_curve": equity_curve,
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


# -----------------------------
# TRADE PLAN
# -----------------------------
@app.route("/tradeplan", methods=["POST"])
def tradeplan():
    try:
        market = get_market_from_request()
        timeframe = normalize_interval(get_string_from_request("timeframe", "1day"))

        settings = load_risk_settings()
        risk_percent = get_float_from_request(
            "risk_percent",
            settings.get("max_risk_percent_per_trade", 1.0)
        )
        account_size = get_float_from_request("account_size", 10000.0)

        max_allowed_risk = float(settings.get("max_risk_percent_per_trade", 2.0))
        if risk_percent > max_allowed_risk:
            risk_percent = max_allowed_risk

        if not market:
            return jsonify({"error": "No market was provided"}), 400

        daily_loss = get_daily_loss_status()
        if daily_loss["blocked"]:
            return jsonify({
                "error": "Daily loss limit reached",
                "details": "New trade plans are blocked because the max daily loss has been exceeded.",
                "daily_loss_status": daily_loss
            }), 403

        df = fetch_live_market_data(market, interval=timeframe, outputsize=30)
        signal_data = evaluate_signal(df)
        ai_text = build_ai_explanation(signal_data)
        mtf_data = get_multi_timeframe_confirmation(market, timeframe)
        session_data = get_market_session()
        last_row = df.iloc[-1]
        recent_rows = df.tail(14)

        entry = float(last_row["Close"])
        atr = (recent_rows["High"] - recent_rows["Low"]).mean()
        if atr <= 0:
            atr = entry * 0.01

        signal_type = signal_data["signal"]
        breakout = signal_data["breakout"]
        trendline = signal_data["trendline"]
        pattern = signal_data["pattern"]

        if signal_type == "Bullish":
            stop_loss = min(float(signal_data["support"]), entry - atr * 1.5)
            take_profit_1 = entry + (entry - stop_loss) * 1.5
            take_profit_2 = entry + (entry - stop_loss) * 3.0
            trade_side = "Buy"

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

        elif signal_type == "Bearish":
            stop_loss = max(float(signal_data["resistance"]), entry + atr * 1.5)
            take_profit_1 = entry - (stop_loss - entry) * 1.5
            take_profit_2 = entry - (stop_loss - entry) * 3.0
            trade_side = "Sell"

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

        else:
            return jsonify({
                "error": "No strong trade setup found",
                "details": "Signal is neutral"
            }), 400

        risk_amount = account_size * (risk_percent / 100.0)
        stop_distance = abs(entry - stop_loss)

        if stop_distance == 0:
            return jsonify({"error": "Stop distance was zero"}), 400

        position_size = risk_amount / stop_distance
        expected_rr = abs(take_profit_2 - entry) / abs(entry - stop_loss)

        if signal_data["confidence"] >= 85 and signal_data["confluence_bonus"] >= 4:
            setup_quality = "A"
        elif signal_data["confidence"] >= 75 and signal_data["confluence_bonus"] >= 2:
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
            "pattern": signal_data["pattern"],
            "entry_price": round(entry, 4),
            "stop_loss": round(stop_loss, 4),
            "take_profit_1": round(take_profit_1, 4),
            "take_profit_2": round(take_profit_2, 4),
            "risk_percent": round(risk_percent, 2),
            "risk_amount": round(risk_amount, 2),
            "position_size": round(position_size, 4),
            "expected_rr": round(expected_rr, 2),
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
            "higher_timeframe_bias": mtf_data["higher_timeframe_bias"],
            "timeframe_alignment": mtf_data["timeframe_alignment"],
            "multi_timeframe": mtf_data["multi_timeframe"],
            "reason": ", ".join(signal_data["reasons"]),
            "ai_summary": ai_text["ai_summary"],
            "trade_thesis": ai_text["trade_thesis"],
            "risk_note": ai_text["risk_note"],
            "session_label": session_data["session_label"],
            "active_sessions": session_data["active_sessions"],
            "liquidity_profile": session_data["liquidity_profile"],
            "utc_hour": session_data["utc_hour"],
            "daily_loss_status": daily_loss
        }

        append_history(TRADEPLAN_HISTORY_FILE, response_data, max_items=200)
        return jsonify(response_data)

    except Exception as e:
        return jsonify({
            "error": "Trade plan generation failed",
            "details": str(e)
        }), 500


# -----------------------------
# PRESETS
# -----------------------------
@app.route("/presets", methods=["GET"])
def get_presets():
    try:
        presets = load_presets()
        return jsonify(presets)
    except Exception as e:
        return jsonify({
            "error": "Failed to fetch presets",
            "details": str(e)
        }), 500


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


@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            os.environ.get("STRIPE_WEBHOOK_SECRET")
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    try:
        if event["type"] == "checkout.session.completed":
            session_obj = event["data"]["object"]

            customer_id = session_obj.get("customer")
            subscription_id = session_obj.get("subscription")

            metadata = session_obj.get("metadata", {}) or {}
            user_id = metadata.get("user_id")
            plan = metadata.get("plan", "pro")

            data = {
                "user_id": user_id,
                "plan": plan,
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription_id,
                "status": "active"
            }

            headers = {
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            }

            resp = requests.post(
                f"{SUPABASE_URL}/rest/v1/subscriptions",
                json=data,
                headers=headers,
                timeout=20
            )

            if resp.status_code >= 400:
                return jsonify({
                    "error": "Failed to save subscription to Supabase",
                    "details": resp.text
                }), 500

        elif event["type"] == "customer.subscription.updated":
            sub = event["data"]["object"]

            subscription_id = sub.get("id")
            status = sub.get("status")
            current_period_end = sub.get("current_period_end")

            headers = {
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            }

            update_data = {
                "status": status,
                "current_period_end": datetime.utcfromtimestamp(current_period_end).isoformat() + "Z" if current_period_end else None
            }

            resp = requests.patch(
                f"{SUPABASE_URL}/rest/v1/subscriptions?stripe_subscription_id=eq.{subscription_id}",
                json=update_data,
                headers=headers,
                timeout=20
            )

            if resp.status_code >= 400:
                return jsonify({
                    "error": "Failed to update subscription in Supabase",
                    "details": resp.text
                }), 500

        elif event["type"] == "customer.subscription.deleted":
            sub = event["data"]["object"]
            subscription_id = sub.get("id")

            headers = {
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            }

            update_data = {
                "status": "canceled"
            }

            resp = requests.patch(
                f"{SUPABASE_URL}/rest/v1/subscriptions?stripe_subscription_id=eq.{subscription_id}",
                json=update_data,
                headers=headers,
                timeout=20
            )

            if resp.status_code >= 400:
                return jsonify({
                    "error": "Failed to cancel subscription in Supabase",
                    "details": resp.text
                }), 500

        return jsonify({"status": "success"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    try:
        body = get_request_body()

        price_id = body.get("price_id")
        user_id = body.get("user_id")
        plan = body.get("plan", "pro")
        success_url = body.get("success_url")
        cancel_url = body.get("cancel_url")

        if not price_id:
            return jsonify({"error": "price_id is required"}), 400

        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        if not success_url:
            return jsonify({"error": "success_url is required"}), 400

        if not cancel_url:
            return jsonify({"error": "cancel_url is required"}), 400

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": user_id,
                "plan": plan
            }
        )

        return jsonify({
            "url": checkout_session.url,
            "session_id": checkout_session.id
        })

    except Exception as e:
        return jsonify({
            "error": "Failed to create checkout session",
            "details": str(e)
        }), 500

if __name__ == "__main__":
    ensure_live_engine_started()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)






