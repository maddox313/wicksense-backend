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
    return jsonify(["Futures","NASDAQ","DowJones","Gold","NaturalGas","Forex"])


@app.route("/openapi.json")
def openapi():
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "WickSense API",
            "version": "1.0"
        },
        "paths": {
            "/markets": {
                "get": {
                    "summary": "Get supported markets"
                }
            },
            "/backtest": {
                "post": {
                    "summary": "Run a backtest"
                }
            }
        }
    }

@app.route("/backtest", methods=["POST"])
def backtest():
    try:
        # Accept either form data or JSON
        market = request.form.get("market")

        if not market and request.is_json:
            body = request.get_json(silent=True) or {}
            market = body.get("market")

        if not market:
            return jsonify({"error": "No market was provided"}), 400

        file_path = os.path.join(DATA_FOLDER, f"{market}_historical.csv")

        if not os.path.exists(file_path):
            return jsonify({
                "error": f"Market data not found for {market}",
                "expected_file": file_path
            }), 404

        df = pd.read_csv(file_path)

        required_cols = ["Open", "High", "Low", "Close"]
        missing = [c for c in required_cols if c not in df.columns]
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
