from flask import Flask, jsonify, request
from flask_cors import CORS
import pandas as pd
import os
import requests

app = Flask(__name__)
CORS(app)

DATA_FOLDER = "data"

MARKET_SYMBOLS = {
    "Forex": "EUR/USD",
    "Gold": "XAU/USD",
    "NaturalGas": "NG/USD",
    "NASDAQ": "IXIC",
    "DowJones": "DJI",
    "Futures": "ES"
}


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


@app.route("/openapi.json")
def openapi():
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "WickSense API",
            "version": "2.0.0"
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
                            "description": "List of markets",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/backtest": {
                "post": {
                    "summary": "Run a backtest",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "market": {"type": "string"}
                                    },
                                    "required": ["market"]
                                }
                            },
                            "application/x-www-form-urlencoded": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "market": {"type": "string"}
                                    },
                                    "required": ["market"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Backtest results",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        }
                    }
                }
            },
            "/signal": {
                "post": {
                    "summary": "Generate a market signal",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "market": {"type": "string"}
                                    },
                                    "required": ["market"]
                                }
                            },
                            "application/x-www-form-urlencoded": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "market": {"type": "string"}
                                    },
                                    "required": ["market"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Signal result",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        }
                    }
                }
            },
            "/tradeplan": {
                "post": {
                    "summary": "Generate a trade plan",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "market": {"type": "string"},
                                        "risk_percent": {"type": "number"},
                                        "account_size": {"type": "number"}
                                    },
                                    "required": ["market"]
                                }
                            },
                            "application/x-www-form-urlencoded": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "market": {"type": "string"},
                                        "risk_percent": {"type": "number"},
                                        "account_size": {"type": "number"}
                                    },
                                    "required": ["market"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Trade plan result",
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


def get_market_from_request():
    market = request.form.get("market")

    if not market and request.is_json:
        body = request.get_json(silent=True) or {}
        market = body.get("market")

    return market


def get_float_from_request(key, default_value):
    value = request.form.get(key)

    if value is None and request.is_json:
        body = request.get_json(silent=True) or {}
        value = body.get(key)

    if value is None:
        return default_value

    return float(value)


def validate_market_csv(df: pd.DataFrame):
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

    missing = validate_market_csv(df)
    if missing:
        raise ValueError(f"Live data missing required columns: {missing}")

    return df


@app.route("/backtest", methods=["POST"])
def backtest():
    try:
        market = get_market_from_request()

        if not market:
            return jsonify({"error": "No market was provided"}), 400

        df = fetch_live_market_data(market, interval="1day", outputsize=50)

        results = []

        for i, row in df.iterrows():
            action = "Buy" if row["Close"] > row["Open"] else "Sell"
            results.append({
                "index": int(i),
                "action": action,
                "price": float(row["Close"])
            })

        return jsonify({"results": results})

    except Exception as e:
        return jsonify({
            "error": "Backtest failed",
            "details": str(e)
        }), 500


@app.route("/signal", methods=["POST"])
def signal():
    try:
        market = get_market_from_request()

        if not market:
            return jsonify({"error": "No market was provided"}), 400

        df = fetch_live_market_data(market, interval="1day", outputsize=20)
        last_row = df.iloc[-1]

        open_price = float(last_row["Open"])
        high_price = float(last_row["High"])
        low_price = float(last_row["Low"])
        close_price = float(last_row["Close"])

        upper_wick = high_price - max(open_price, close_price)
        lower_wick = min(open_price, close_price) - low_price
        candle_range = high_price - low_price if high_price != low_price else 1

        if close_price > open_price:
            signal_type = "Bullish"
        elif close_price < open_price:
            signal_type = "Bearish"
        else:
            signal_type = "Neutral"

        wick_bias = "Lower wick dominant" if lower_wick > upper_wick else "Upper wick dominant"

        confidence = round(
            50 + (max(upper_wick, lower_wick) / candle_range) * 40,
            2
        )

        return jsonify({
            "market": market,
            "signal": signal_type,
            "confidence": confidence,
            "entry": close_price,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "upper_wick": round(upper_wick, 4),
            "lower_wick": round(lower_wick, 4),
            "reason": f"{wick_bias}; latest candle closed {'above' if close_price > open_price else 'below' if close_price < open_price else 'at'} open."
        })

    except Exception as e:
        return jsonify({
            "error": "Signal generation failed",
            "details": str(e)
        }), 500


@app.route("/tradeplan", methods=["POST"])
def tradeplan():
    try:
        market = get_market_from_request()

        if not market:
            return jsonify({"error": "No market was provided"}), 400

        risk_percent = get_float_from_request("risk_percent", 1.0)
        account_size = get_float_from_request("account_size", 10000.0)

        df = fetch_live_market_data(market, interval="1day", outputsize=30)
        last_row = df.iloc[-1]
        recent_rows = df.tail(14)

        entry = float(last_row["Close"])

        atr = (recent_rows["High"] - recent_rows["Low"]).mean()
        if atr <= 0:
            atr = entry * 0.01

        signal_type = "Buy" if last_row["Close"] > last_row["Open"] else "Sell"

        if signal_type == "Buy":
            stop_loss = entry - atr * 1.5
            take_profit = entry + atr * 3.0
        else:
            stop_loss = entry + atr * 1.5
            take_profit = entry - atr * 3.0

        risk_amount = account_size * (risk_percent / 100.0)
        stop_distance = abs(entry - stop_loss)

        if stop_distance == 0:
            return jsonify({"error": "Stop distance was zero"}), 400

        position_size = risk_amount / stop_distance
        expected_rr = abs(take_profit - entry) / abs(entry - stop_loss)

        return jsonify({
            "market": market,
            "signal": signal_type,
            "entry_price": round(entry, 4),
            "stop_loss": round(stop_loss, 4),
            "take_profit": round(take_profit, 4),
            "risk_percent": round(risk_percent, 2),
            "risk_amount": round(risk_amount, 2),
            "position_size": round(position_size, 4),
            "expected_rr": round(expected_rr, 2),
            "reason": "ATR-based trade generator using latest live candle direction"
        })

    except Exception as e:
        return jsonify({
            "error": "Trade plan generation failed",
            "details": str(e)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
