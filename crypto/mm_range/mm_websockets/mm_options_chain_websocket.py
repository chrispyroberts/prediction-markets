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
    get_contract_trades
)

# CONTROLS HOW NEAR THE MONEY WE SEE CONTRACTS
THRESHOLD = 1000

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

        subtitle = contract['subtitle'].split(" ")

        bottom = float(subtitle[0][1:].replace(',', ''))
        top = float(subtitle[2].replace(',', ''))

        strike = f"{bottom}-{top}"
        trades = get_contract_trades(ticker)
        middle = (bottom + top) / 2

        top_bid = contract['yes_bid']
        top_ask = 100 - contract['no_bid']
        expiration_time = datetime.fromisoformat(contract['close_time'].replace('Z', '+00:00'))

        total_seconds = int((expiration_time - now_utc).total_seconds())
        if total_seconds <= 0:
            return None
        

        hours_left = max(total_seconds / 3600, 0.001)
        moneyness = get_moneyness(brti_price, middle, hours_left)
        # check if best bid greater than 0 and best ask less than 100

        mm_bid, mm_ask = get_top_orderbook(ticker)
        trade_market = True
        if top_bid is None or top_bid == 0:
            # no asks, only bids, 
            mid_price = (top_bid + 100) / 2
            spread = 0
            trade_market = False
        elif top_ask is None or top_ask == 100:
            # no bids, only asks
            mid_price = top_ask / 2
            spread = 0
            trade_market = False
        elif mm_ask is not None and mm_bid is not None:
            spread = mm_ask - mm_bid
            mid_price = (top_bid + top_ask) / 2
        else:
            raise ValueError("Invalid order book data for contract: " + ticker)
        
        return {
            'ticker': ticker,
            'strike': strike,
            'time_left_sec': total_seconds,
            'moneyness': round(moneyness, 2),
            'interest': contract['open_interest'],
            'strike' : strike,
            'best_bid': int(top_bid) if top_bid is not None else None, # convert to int if not none
            'best_ask': int(top_ask) if top_bid is not None else None,
            'mm_bid': int(mm_bid) if mm_bid is not None else None,
            'mm_ask': int(mm_ask) if mm_ask is not None else None,
            'spread': spread,
            'mid_price': mid_price,
            'trades' : trades,
            'trade_market' : trade_market
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

    if EVENT is None:
        print("🔍 No event ticker provided. Fetching current contract ticker...")
        EVENT = get_current_contract_ticker()

    print(f"🌐 Serving brti_and_options_update on http://localhost:5050 for {EVENT}...")
    socketio.run(app, host="127.0.0.1", port=5050)
