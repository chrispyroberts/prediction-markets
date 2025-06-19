import eventlet
eventlet.monkey_patch()

import sys
import time
import threading
import numpy as np
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor

from utils import (
    get_current_contract_ticker, get_options_chain_for_event, get_moneyness,
    implied_vol_binary_call, implied_vol_one_touch, get_top_orderbook,
    binary_call_delta
)

# CONTROLS HOW NEAR THE MONEY WE SEE CONTRACTS
THRESHOLD = 750


EVENT = sys.argv[1] if len(sys.argv) > 1 else None
RUNTIME_SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 600
USE_ONE_TOUCH = False
IV_FN = implied_vol_one_touch if USE_ONE_TOUCH else implied_vol_binary_call

# === Flask App Setup ===
app = Flask(__name__)
CORS(app, supports_credentials=True)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')

latest_price = {'value': None, 'timestamp': None, 'simple_average': []}
active_clients = set()

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    active_clients.add(sid)
    print(f"🔗 Client connected: {sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    active_clients.discard(sid)
    print(f"❌ Client disconnected: {sid}")

@app.route('/price', methods=['GET'])
def get_price():
    if latest_price['value'] is None:
        return jsonify({'status': 'waiting for data'}), 503
    return jsonify({
        'brti': latest_price['value'],
        'simple_average': np.mean(latest_price['simple_average']),
        'timestamp': latest_price['timestamp']
    })

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "running", "event": EVENT})

def process_contract(contract, brti_price, now_utc):
    try:
        ticker = contract['ticker']
        strike = int(round(contract['floor_strike'], 0))
        best_bid = contract['yes_bid']
        best_ask = 100 - contract['no_bid']
        expiration_time = datetime.fromisoformat(contract['close_time'].replace('Z', '+00:00'))

        total_seconds = int((expiration_time - now_utc).total_seconds())
        if total_seconds <= 0:
            return None

        hours_left = max(total_seconds / 3600, 0.001)
        moneyness = get_moneyness(brti_price, strike, hours_left)
        bid_iv = IV_FN(brti_price, strike, hours_left, best_bid / 100)
        ask_iv = IV_FN(brti_price, strike, hours_left, best_ask / 100)
        # check if best bid greater than 0 and best ask less than 100
        if best_bid <= 0 or best_ask >= 100:
            mid_iv = np.nan
        else:
            mid_iv = IV_FN(brti_price, strike, hours_left, (best_bid + best_ask) / 200)
     
        bid_value, ask_value = get_top_orderbook(ticker)
        bid_delta = binary_call_delta(brti_price, strike, hours_left, bid_iv) if np.isfinite(bid_iv) else None
        ask_delta = binary_call_delta(brti_price, strike, hours_left, ask_iv) if np.isfinite(ask_iv) else None


        return {
            'ticker': ticker,
            'strike': strike,
            'time_left_sec': total_seconds,
            'moneyness': round(moneyness, 2),
            'interest': contract['open_interest'],
            'bid_iv': round(bid_iv, 2) if np.isfinite(bid_iv) else None,
            'ask_iv': round(ask_iv, 2) if np.isfinite(ask_iv) else None,
            'mid_iv': round(mid_iv, 2) if np.isfinite(mid_iv) else None,
            'best_bid': int(best_bid),
            'best_ask': int(best_ask),
            'bid_value': bid_value,
            'ask_value': ask_value,
            'bid_delta': round(bid_delta, 5) if bid_delta is not None else None,
            'ask_delta': round(ask_delta, 5) if ask_delta is not None else None
        }

    except Exception as e:
        print(f"⛔ Skipped contract {contract.get('ticker', '')}: {e}")
        return None

def poll_brti():
    print("🌀 Starting Playwright polling loop...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.cfbenchmarks.com/data/indices/BRTI", timeout=20000)
        page.wait_for_selector('div.leading-6 span')
        print("📡 Connected to BRTI page.")

        last_logged_price = None
        time.sleep(2)

        while True:
            try:
                price_text = page.locator('div.leading-6 span').first.text_content()
                price = float(price_text.replace('$', '').replace(',', ''))
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

                if price != last_logged_price:
                    last_logged_price = price
                    latest_price['simple_average'].append(price)
                    if len(latest_price['simple_average']) > 60:
                        latest_price['simple_average'].pop(0)

                    average = np.mean(latest_price['simple_average'])
                    latest_price['value'] = price
                    latest_price['timestamp'] = timestamp

                    # Build combined payload
                    combined_payload = build_options_payload(price, average, timestamp)

                    brti_data = {
                        'brti': price,
                        'simple_average': average,
                        'timestamp': timestamp
                    }
                    combined_payload.update(brti_data)
                    
                    socketio.emit("brti_and_options_update", combined_payload)
                    print(f"📢 Emitting price_update {brti_data['timestamp']} @ {brti_data['brti']} with {len(combined_payload['contracts'])} contracts")

            except Exception as e:
                print(f"[{datetime.now()}] ⚠️ Error during BRTI polling or options processing: {e}")

            time.sleep(0.1)


def build_options_payload(brti_price, average, timestamp):

    if EVENT is None:
        event_ticker = get_current_contract_ticker()
    else:
        event_ticker = EVENT

    chain_data = get_options_chain_for_event(event_ticker, average, threshold=THRESHOLD)
    output = []
    now_utc = datetime.now().astimezone().astimezone(timezone.utc)

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(lambda c: process_contract(c, brti_price, now_utc), chain_data)

    output = [r for r in results if r is not None]

    return {
        'contracts': output
    }

def shutdown_after(seconds):
    time.sleep(seconds)
    print(f"\n🕒 Runtime limit of {seconds} seconds reached. Shutting down...")
    socketio.stop()
    sys.exit(0)

if __name__ == "__main__":
    threading.Thread(target=poll_brti, daemon=True).start()
    threading.Thread(target=shutdown_after, args=(RUNTIME_SECONDS,), daemon=True).start()
    print(f"🌐 Serving brti_and_options_update on http://localhost:5050 for {EVENT}...")
    socketio.run(app, host="127.0.0.1", port=5050)
