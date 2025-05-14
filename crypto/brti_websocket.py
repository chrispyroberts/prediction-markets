from flask import Flask, jsonify
from flask_socketio import SocketIO
from flask import request
import asyncio
import threading
from playwright.async_api import async_playwright
from datetime import datetime
import numpy as np


app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet')

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

# Playwright polling loop
async def poll_brti():
    print("🌀 Starting Playwright polling loop...")
    async with async_playwright() as p:
        print("🚀 Launching browser...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.cfbenchmarks.com/data/indices/BRTI", timeout=20000)
        await page.wait_for_selector('div.leading-6 span')
        print("📡 Connected to BRTI page.")

        last_logged_price = None

        print("⏳ Waiting 2 seconds for clients to connect...")
        await asyncio.sleep(2)

        while True:
            try:
                price_text = await page.locator('div.leading-6 span').first.text_content()
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

                    print(f"📢 Emitting price_update: {update_payload}")
                    print(f"👥 Active connected clients: {list(active_clients)}")

                    for sid in list(active_clients):
                        socketio.emit('price_update', update_payload, room=sid, namespace='/', broadcast=True)

            except Exception as e:
                print(f"[{datetime.now()}] ⚠️ Error while fetching price:", e)

            await asyncio.sleep(0.3)

def start_polling():
    asyncio.run(poll_brti())

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
    threading.Thread(target=start_polling, daemon=True).start()    
    print("🌐 Starting WebSocket server on http://localhost:5000 ...")
    socketio.run(app, port=5000)

