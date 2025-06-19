import http.client
import json
import time
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

# HTTPS connection (reused)
def get_connection():
    try:
        return http.client.HTTPSConnection("api.coinbase.com")
    except Exception as e:
        print(f"[ERROR] Failed to create HTTPS connection: {e}")
        return None

conn = get_connection()

# Candle granularities in seconds
granularities = {
    'ONE_MINUTE': 60,
    'FIVE_MINUTE': 300,
    'FIFTEEN_MINUTE': 900,
    'THIRTY_MINUTE': 1800,
    'ONE_HOUR': 3600,
    'TWO_HOUR': 7200,
    'SIX_HOUR': 21600,
    'ONE_DAY': 86400,
}

# Stores latest candle data
candle_store = defaultdict(list)

def fetch_candles(granularity, now):
    global conn
    seconds = granularities[granularity]

    start = now - seconds
    end = now

    path = f"/api/v3/brokerage/market/products/BTC-PERP-INTX/candles?start={start}&end={end}&granularity={granularity}"
    headers = {'Content-Type': 'application/json'}

    try:
        conn.request("GET", path, '', headers)
        res = conn.getresponse()

        if res.status != 200:
            raise Exception(f"HTTP {res.status}: {res.reason}")

        data = json.loads(res.read().decode("utf-8"))

        latest = data.get('candles', [])
        if latest:
            c = latest[0]
            ts = datetime.fromtimestamp(int(c['start']), tz=ZoneInfo("UTC")).astimezone(ZoneInfo("US/Eastern"))
            print(f"[{granularity}] {ts.strftime('%Y-%m-%d %H:%M:%S')} | Open: {c['open']} Close: {c['close']} High: {c['high']} Low: {c['low']} Volume: {c['volume']}")
            candle_store[granularity].append(c)

    except Exception as e:
        print(f"[ERROR] {granularity} fetch failed: {e}")
        # Try reconnecting
        try:
            conn.close()
        except:
            pass
        time.sleep(1)
        conn = get_connection()

def aligned_candle_updater():
    print("[START] Entering main update loop...\n")

    backoff = 1
    while True:
        try:
            now = int(time.time())
            for granularity, seconds in granularities.items():
                if now % seconds == 0:
                    fetch_candles(granularity, now)
            time.sleep(1)
            backoff = 1  # Reset on success

        except Exception as e:
            print(f"[FATAL LOOP ERROR] {e}")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)  # Exponential backoff with cap

if __name__ == "__main__":
    try:
        aligned_candle_updater()
    except KeyboardInterrupt:
        print("Exiting gracefully...")
