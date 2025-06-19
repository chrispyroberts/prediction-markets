import eventlet
eventlet.monkey_patch()

import ccxt
import time
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

# === Flask Setup ===
app = Flask(__name__)
CORS(app, supports_credentials=True)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')

# === Globals ===
order_book = {'bids': [], 'asks': []}
recent_trades = []
exchange = ccxt.coinbase()
symbol = 'BTC/USD'
active_clients = set()

# === WebSocket Events ===
@socketio.on('connect')
def handle_connect():
    sid = request.sid
    active_clients.add(sid)
    print(f"🔗 Market client connected: {sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    active_clients.discard(sid)
    print(f"❌ Market client disconnected: {sid}")

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "running", "symbol": symbol})

# === Background Data Thread ===
def update_data():
    global order_book, recent_trades
    while True:
        try:
            ob = exchange.fetch_order_book(symbol, limit=200)
            order_book = ob
            recent_trades[:] = exchange.fetch_trades(symbol, limit=20)

            payload = {
                "order_book": order_book,
                "recent_trades": recent_trades
            }
            socketio.emit("market_data_update", payload)
            print("📈 Market data updated")
        except Exception as e:
            print("❌ Market data update error:", e)
        time.sleep(1)

# === Main Entry ===
if __name__ == "__main__":
    print("🚀 Starting Coinbase market WebSocket server on http://localhost:5051 ...")
    threading.Thread(target=update_data, daemon=True).start()
    socketio.run(app,  host="127.0.0.1", port=5051)
