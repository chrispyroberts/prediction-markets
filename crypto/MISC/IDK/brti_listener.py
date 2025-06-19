import asyncio
import threading
from flask import Flask, jsonify
from playwright.async_api import async_playwright
from datetime import datetime
import numpy as np

app = Flask(__name__)

# Shared price state and lock
latest_price = {'value': None, 'timestamp': None, 'simple_average': []}
price_lock = threading.Lock()

# Async polling loop
async def poll_brti():
    async with async_playwright() as p:
        print("🚀 Launching browser...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.cfbenchmarks.com/data/indices/BRTI", timeout=20000)
        await page.wait_for_selector('div.leading-6 span')
        print("📡 Connected to BRTI page.")

        last_logged_price = None
        while True:
            try:
                price_text = await page.locator('div.leading-6 span').first.text_content()
                price = float(price_text.replace('$', '').replace(',', ''))
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                if price != last_logged_price:
                    print(f"[{timestamp}] 💰 New BRTI Price: ${price}")
                    last_logged_price = price

                    with price_lock:
                        latest_price['simple_average'].append(price)
                        if len(latest_price['simple_average']) > 60:
                            latest_price['simple_average'].pop(0)

                        latest_price['value'] = price
                        latest_price['timestamp'] = timestamp

                else:
                    with price_lock:
                        latest_price['value'] = price
                        latest_price['timestamp'] = timestamp

            except Exception as e:
                print(f"[{datetime.now()}] ⚠️ Error while fetching price:", e)

            await asyncio.sleep(0.3)

# Thread wrapper for async loop
def start_polling():
    asyncio.run(poll_brti())

# API endpoint to retrieve latest price
@app.route('/price', methods=['GET'])
def get_price():
    with price_lock:
        if latest_price['value'] is None:
            return jsonify({'status': 'waiting for data'}), 503
        return jsonify({
            'brti': latest_price['value'],
            'simple_average': np.mean(latest_price['simple_average']),
            'timestamp': latest_price['timestamp']
        })

if __name__ == "__main__":
    # Start polling thread
    threading.Thread(target=start_polling, daemon=True).start()

    # Start Flask server
    print("🌐 Starting Flask server on http://localhost:5000 ...")
    app.run(port=5000)
