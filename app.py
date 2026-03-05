from flask import Flask, jsonify, request
import pandas as pd
import os

app = Flask(__name__)

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
                    "summary": "Get supported markets",
                    "responses": {
                        "200": {
                            "description": "List of markets"
                        }
                    }
                }
            },
            "/backtest": {
                "post": {
                    "summary": "Run a backtest",
                    "requestBody": {
                        "content": {
                            "application/x-www-form-urlencoded": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "market": {"type": "string"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Backtest results"
                        }
                    }
                }
            }
        }
    }

@app.route("/backtest", methods=["POST"])
def backtest():

    market = request.form.get("market")

    file_path = os.path.join(DATA_FOLDER, f"{market}_historical.csv")

    if not os.path.exists(file_path):
        return jsonify({"error":"market data not found"})

    df = pd.read_csv(file_path)

    results = []

    for i,row in df.iterrows():

        action = "Buy" if row["Close"] > row["Open"] else "Sell"

        results.append({
            "index": i,
            "action": action,
            "price": row["Close"]
        })

    return jsonify({"results":results})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(host="0.0.0.0", port=port)
