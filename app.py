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

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

app = Flask(__name__)
CORS(app)

PRESETS_FILE = "presets.json"

MARKET_SYMBOLS = {
    "Forex": "EUR/USD",
    "Gold": "XAU/USD",
    "NaturalGas": "UNG",
    "NASDAQ": "QQQ",
    "DowJones": "DIA",
    "Futures": "SPY"
}


# -----------------------------
# BASIC ROUTES
# -----------------------------
@app.route("/")
def home():
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


def get_float_from_request(key, default_value):
    body = get_request_body()
    value = body.get(key, default_value)
    try:
        return float(value)
    except Exception:
        return float(default_value)


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

    if breakout_label is None and pd.notna(prev_resistance) and float(row["High"]) > float(prev_resistance) and close_price < float(prev_resistance):
        bearish += 1
        breakout_label = "Failed Bullish Breakout"
        reasons.append("Wick swept above resistance but closed below")

    if breakout_label is None and pd.notna(prev_support) and float(row["Low"]) < float(prev_support) and close_price > float(prev_support):
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

    # Sweeps above resistance but fails to hold
    if pd.notna(prev_resistance):
        prev_resistance = float(prev_resistance)

        if high_price > prev_resistance and close_price < prev_resistance:
            bearish += 2
            liquidity_event = "Bearish Liquidity Sweep"
            reasons.append("Price swept above resistance and closed back below")

        elif high_price > prev_resistance and close_price > prev_resistance and close_price > open_price:
            bullish += 1
            reasons.append("Resistance sweep held into breakout")

    # Sweeps below support but fails to hold
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

    # --------------------------------
    # Confluence scoring
    # --------------------------------
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
        "breakout": strategies["breakout_strategy"]["breakout"],
        "liquidity_event": strategies["liquidity_sweep_strategy"]["liquidity_event"],
        "trendline": strategies["trendline_strategy"]["trendline"],
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

def send_signal_email(market, signal, confidence, reason, entry, pattern=None):
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
        <p><strong>Confidence:</strong> {confidence}%</p>
        <p><strong>Entry:</strong> {entry}</p>
        <p><strong>Reason:</strong> {reason}</p>
        <p><strong>Pattern:</strong> {pattern or 'None'}</p>
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


def scan_markets():
    markets = [
        "NASDAQ",
        "Gold",
        "Forex"
    ]

    scan_results = []

    for market in markets:
        try:
            df = fetch_live_market_data(market, "15min", 15)
            signal_data = evaluate_signal(df)
            last_row = df.iloc[-1]

            reason_text = ", ".join(signal_data["reasons"])
            entry_price = float(last_row["Close"])

            opportunity_score = (
                signal_data["confidence"]
                + signal_data["confluence_bonus"] * 5
                + (10 if signal_data["breakout"] else 0)
                + (5 if signal_data["trendline"] else 0)
            )

            result = {
                "market": market,
                "signal": signal_data["signal"],
                "confidence": signal_data["confidence"],
                "opportunity_score": opportunity_score,
                "entry": entry_price,
                "reason": reason_text,
                "pattern": signal_data["pattern"],
                "breakout": signal_data["breakout"],
                "trendline": signal_data["trendline"],
                "strategy_breakdown": signal_data["strategy_breakdown"]
            }

            scan_results.append(result)

            should_alert = (
                (signal_data["confidence"] >= 80 and signal_data["signal"] != "Neutral")
                or signal_data["breakout"] is not None
                or signal_data["trendline"] is not None
            )

            if should_alert:
                print(f"Strong signal detected: {market}")

                try:
                    send_signal_email(
                        market=market,
                        signal=signal_data["signal"],
                        confidence=signal_data["confidence"],
                        reason=reason_text,
                        entry=entry_price,
                        pattern=signal_data["pattern"]
                    )
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
        mtf_data = get_multi_timeframe_confirmation(market, timeframe)
        last_row = df.iloc[-1]

        return jsonify({
            "market": market,
            "timeframe": timeframe,
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
            "trendline": signal_data["trendline"],
            "strategy_breakdown": signal_data["strategy_breakdown"],
            "confluence_bonus": signal_data["confluence_bonus"],
            "higher_timeframe_bias": mtf_data["higher_timeframe_bias"],
            "timeframe_alignment": mtf_data["timeframe_alignment"],
            "multi_timeframe": mtf_data["multi_timeframe"],
            "reason": ", ".join(signal_data["reasons"])
        })

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
        cash = 0.0
        pos = 0.0

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
                pos += 1
                cash -= price
            elif action == "Sell" and pos > 0:
                pos -= 1
                cash += price

            equity = cash + pos * price
            equity_curve.append(round(equity, 4))

            results.append({
                "index": int(i),
                "action": action,
                "price": price
            })

        return jsonify({
            "market": market,
            "timeframe": timeframe,
            "results": results,
            "equity_curve": equity_curve
        })

    except Exception as e:
        return jsonify({
            "error": "Backtest failed",
            "details": str(e)
        }), 500


# -----------------------------
# TRADE PLAN
# -----------------------------
# -----------------------------
# TRADE PLAN
# -----------------------------
@app.route("/tradeplan", methods=["POST"])
def tradeplan():
    try:
        market = get_market_from_request()
        timeframe = normalize_interval(get_string_from_request("timeframe", "1day"))
        risk_percent = get_float_from_request("risk_percent", 1.0)
        account_size = get_float_from_request("account_size", 10000.0)

        if not market:
            return jsonify({"error": "No market was provided"}), 400

        df = fetch_live_market_data(market, interval=timeframe, outputsize=30)
        df = add_indicators(df)
        signal_data = evaluate_signal(df)
        mtf_data = get_multi_timeframe_confirmation(market, timeframe)
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
            stop_loss = min(float(last_row["Support"]), entry - atr * 1.5)
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
            stop_loss = max(float(last_row["Resistance"]), entry + atr * 1.5)
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

        return jsonify({
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
            "trendline": signal_data["trendline"],
            "strategy_breakdown": signal_data["strategy_breakdown"],
            "confluence_bonus": signal_data["confluence_bonus"],
            "higher_timeframe_bias": mtf_data["higher_timeframe_bias"],
            "timeframe_alignment": mtf_data["timeframe_alignment"],
            "multi_timeframe": mtf_data["multi_timeframe"],
            "reason": ", ".join(signal_data["reasons"])
        })

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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)













































