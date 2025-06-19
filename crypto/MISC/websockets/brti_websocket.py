import eventlet
eventlet.monkey_patch()

from flask import Flask, jsonify, request
from flask_socketio import SocketIO
from playwright.sync_api import sync_playwright
from datetime import datetime
import numpy as np
import threading
import time
from flask_cors import CORS


app = Flask(__name__)
CORS(app, supports_credentials=True)

socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')  # ✅ Allow all origins

latest_price = {'value': None, 'timestamp': None, 'simple_average': []}
active_clients = set()

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    active_clients.add(sid)
    print("🔗 A client connected.")
    print(f"   📎 Session ID:   {sid}")
    print(f"   👥 Active clients: {list(active_clients)}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    active_clients.discard(sid)
    print("❌ A client disconnected.")
    print(f"   👥 Active clients: {list(active_clients)}")

def poll_brti():
    print("🌀 Starting Playwright polling loop...")
    with sync_playwright() as p:
        print("🚀 Launching browser...")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.cfbenchmarks.com/data/indices/BRTI", timeout=20000)
        page.wait_for_selector('div.leading-6 span')
        print("📡 Connected to BRTI page.")

        last_logged_price = None
        time.sleep(2)  # wait for clients to connect

        while True:
            try:
                price_text = page.locator('div.leading-6 span').first.text_content()
                price = float(price_text.replace('$', '').replace(',', ''))
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                if price != last_logged_price:
                    last_logged_price = price
                    latest_price['simple_average'].append(price)
                    if len(latest_price['simple_average']) > 60:
                        latest_price['simple_average'].pop(0)

                    latest_price['value'] = price
                    latest_price['timestamp'] = timestamp

                    update_payload = {
                        'brti': price,
                        'simple_average': np.mean(latest_price['simple_average']),
                        'timestamp': timestamp
                    }

                    print(f"📢 Emitting price_update: {price}")
                    # print(f"👥 Active connected clients: {list(active_clients)}")

                    # Emit to all clients (for debugging)
                    socketio.emit('price_update', update_payload)

            except Exception as e:
                print(f"[{datetime.now()}] ⚠️ Error while fetching price:", e)

            time.sleep(0.3)

@app.route('/price', methods=['GET'])
def get_price():
    if latest_price['value'] is None:
        return jsonify({'status': 'waiting for data'}), 503
    return jsonify({
        'brti': latest_price['value'],
        'simple_average': np.mean(latest_price['simple_average']),
        'timestamp': latest_price['timestamp']
    })

if __name__ == "__main__":
    threading.Thread(target=poll_brti, daemon=True).start()
    print("🌐 Starting WebSocket server on http://localhost:5000 ...")
    socketio.run(app, port=5000)
