import socketio
import sys
import random
import time
import threading
import os

# === Parse command line arguments ===
if len(sys.argv) != 3:
    print("Usage: python contract_ws_client.py <TICKER> <DURATION_SECONDS>")
    sys.exit(1)

ticker = sys.argv[1]
try:
    duration = int(sys.argv[2])
except ValueError:
    print("❌ Duration must be an integer (seconds).")
    sys.exit(1)

print(f"🔧 Using ticker: {ticker}")
print(f"⏱ Running for {duration} seconds...")

# === Set up SocketIO client ===
sio = socketio.Client()

@sio.event
def connect():
    print("✅ Connected to BRTI WebSocket server.")

@sio.event
def disconnect():
    print("❌ Disconnected from BRTI WebSocket server.")
    os._exit(-1)

@sio.on("price_update")
def on_price_update(data):
    print("📈 PRICE UPDATED")
    poll_contract_data(ticker)

def poll_contract_data(ticker):
    mock_price = round(0.5 + random.random(), 3)
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"   → Polled {ticker} contract at {timestamp}: ${mock_price}")

# === Auto shutdown thread ===
def shutdown_after(seconds):
    time.sleep(seconds)
    print(f"\n⏹️ Time limit reached. Shutting down gracefully...")
    sio.disconnect()
    sys.exit(0)

# === Connect and run ===
try:
    threading.Thread(target=shutdown_after, args=(duration,), daemon=True).start()
    sio.connect("http://localhost:5000")
    sio.wait()
except Exception as e:
    print("❌ Could not connect to WebSocket server:", e)
    sys.exit(-1)
