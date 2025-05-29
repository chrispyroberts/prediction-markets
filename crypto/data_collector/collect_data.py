from websockets.utils import *
from datetime import datetime, timezone
import pandas as pd
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.async_api import async_playwright
import asyncio


class dataCollector:
    def __init__(self):
        middle_contract = 'KXBTCD-25MAY1417-T103499.99'
        event_name = '-'.join(middle_contract.split('-')[:2])
        middle_strike = float(middle_contract.split('-')[2][1:])

        num_each_side = 3
        self.contracts_to_track = []
        for i in range(-num_each_side, num_each_side + 1):
            strike = middle_strike + i * 500
            contract = f'{event_name}-T{strike:.2f}'
            self.contracts_to_track.append(contract)

        self.depth_level = 5
        print(f"[INIT] Tracking {len(self.contracts_to_track)} contracts:")
        for c in self.contracts_to_track:
            print(f" - {c}")
        print(f"[INIT] Order book depth: {self.depth_level}")

    def collect_one_contract(self, ticker, timestamp, depth_level):
        try:
            print(f"[CONTRACT] Collecting {ticker}")
            data = get_market_data(ticker)
            strike = data['strike']
            expiration_time = datetime.fromisoformat(data['expiration_time'].replace('Z', '+00:00'))

            bids, asks = get_orderbook(ticker)
            top_bids = sorted(bids, key=lambda x: -x["price"])[:depth_level]
            top_asks = sorted(asks, key=lambda x: x["price"])[:depth_level]

            ticker_row = dataRow(
                timestamp,
                ticker,
                strike=strike,
                expiration_time=expiration_time,
                bids=top_bids,
                asks=top_asks
            )

            return ticker_row.make_data_row()
        
        except Exception as e:
            print(f"[ERROR] Failed to collect data for {ticker}: {e}")
            return None

    def parallel_collect_data(self, brti_price, timestamp):
        data_rows = []
        brti_row = dataRow(timestamp, "BRTI", price=brti_price)
        data_rows.append(brti_row.make_data_row())

        with ThreadPoolExecutor(max_workers=len(self.contracts_to_track)) as executor:
            futures = [
                executor.submit(self.collect_one_contract, ticker, timestamp, self.depth_level)
                for ticker in self.contracts_to_track
            ]

            for future in as_completed(futures):
                result = future.result()
                if result:
                    data_rows.append(result)
        
        return data_rows

def append_rows_to_csv(rows, filename='data/data_log.csv'):
    df = pd.DataFrame(rows)
    file_exists = os.path.exists(filename)
    df.to_csv(filename, mode='a', index=False, header=not file_exists)
    print(f"[CSV] Wrote {len(df)} rows to {filename}")

async def poll_brti_and_collect():
    collector = dataCollector()
    print("🌀 Starting Playwright polling loop...")
    async with async_playwright() as p:
        print("🚀 Launching browser...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.cfbenchmarks.com/data/indices/BRTI", timeout=20000)
        await page.wait_for_selector('div.leading-6 span')
        print("📡 Connected to BRTI page.")

        last_logged_time = None
        last_logged_price = None
        while True:
            try:
                price_text = await page.locator('div.leading-6 span').first.text_content()
                price = float(price_text.replace('$', '').replace(',', ''))
                timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

                if timestamp != last_logged_time and price != last_logged_price:
                    last_logged_time = timestamp
                    last_logged_price = price
                    print(f"[BRTI] New price: {price} at {timestamp}")
                    rows = collector.parallel_collect_data(price, timestamp)
                    append_rows_to_csv(rows)

            except Exception as e:
                print(f"[{datetime.now()}] ⚠️ Error while fetching price:", e)

            await asyncio.sleep(0.1)

if __name__ == "__main__":
    asyncio.run(poll_brti_and_collect())
