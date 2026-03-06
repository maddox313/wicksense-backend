from flask import Flask, jsonify, request
from flask_cors import CORS
import pandas as pd
import os

app = Flask(__name__)
CORS(app)

DATA_FOLDER = "data"


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
            "version": "1.0.0"
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
                                        "items": {
                                            "type": "string"
                                        }
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
                            "application/x-www-form-urlencoded": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "market": {
                                            "type": "string"
                                        }
                                    },
                                    "required": ["market"]
                                }
                            },
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "market": {
                                            "type": "string"
                                        }
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
                                    "schema": {
                                        "type": "object"
                                    }
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
                            "application/x-www-form-urlencoded": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "market": {
                                            "type": "string"
                                        }
                                    },
                                    "required": ["market"]
                                }
                            },
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "market": {
                                            "type": "string"
                                        }
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
                                    "schema": {
                                        "type": "object"
                                    }
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


def get_market_file_path(market: str):
    return os.path.join(DATA_FOLDER, f"{market}_historical.csv")


def validate_market_csv(df: pd.DataFrame):
    required_cols = ["Open", "High", "Low", "Close"]
    missing = [c for c in required_cols if c not in df.columns]
    return missing


@app.route("/backtest", methods=["POST"])
def backtest():
    try:
        market = get_market_from_request()

        if not market:
            return jsonify({"error": "No market was provided"}), 400

        file_path = get_market_file_path(market)

        if not os.path.exists(file_path):
            return jsonify({
                "error": f"Market data not found for {market}",
                "expected_file": file_path
            }), 404

        df = pd.read_csv(file_path)

        missing = validate_market_csv(df)
        if missing:
            return jsonify({
                "error": "CSV is missing required columns",
                "missing_columns": missing
            }), 400

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

        file_path = get_market_file_path(market)

        if not os.path.exists(file_path):
            return jsonify({
                "error": f"Market data not found for {market}",
                "expected_file": file_path
            }), 404

        df = pd.read_csv(file_path)

        missing = validate_market_csv(df)
        if missing:
            return jsonify({
                "error": "CSV is missing required columns",
                "missing_columns": missing
            }), 400

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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
