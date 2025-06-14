import os
import sys
import time
import threading
import logging
from datetime import datetime
from pytz import timezone
from playwright.sync_api import sync_playwright
import numpy as np
import psutil
import psycopg2
from psycopg2 import OperationalError
from dotenv import load_dotenv

# === Load environment variables ===
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "brti")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))

# === Logging setup ===
logging.basicConfig(
    filename="brti_tracker.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# === Shared state ===
watchdog_enabled = threading.Event()
latest_price = {
    'value': None,
    'timestamp': None,
    'simple_average': [],
    'last_update_time': time.time()
}
script_start_time = time.time()
est = timezone('US/Eastern')

conn = None


def connect_to_db():
    global conn
    while True:
        try:
            logging.info("📡 Attempting PostgreSQL connection...")
            conn = psycopg2.connect(
                host="localhost",
                dbname="brti",
                user="ubuntu"
            )
            conn.autocommit = True
            logging.info("✅ Connected to PostgreSQL.")
            break
        except OperationalError as e:
            logging.warning(f"⏳ PostgreSQL connection failed. Retrying in 5s... Error: {e}")
            time.sleep(5)


def insert_to_db(price, sma, timestamp):
    global conn
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO brti_prices (price, simple_average, timestamp) VALUES (%s, %s, %s)",
                (float(price), float(sma), timestamp)  # <-- fix here
            )
    except (Exception, OperationalError) as e:
        logging.error(f"❌ Database error during insert: {e}")
        connect_to_db()



def safe_restart():
    try:
        logging.warning("🔁 Restarting script due to inactivity.")
        os.execv(sys.executable, ['python'] + sys.argv)
    except Exception as e:
        logging.critical(f"💥 Failed to restart script: {e}")
        sys.exit(1)


def poll_brti():
    logging.info("🌀 Starting BRTI polling loop...")
    connect_to_db()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto("https://www.cfbenchmarks.com/data/indices/BRTI", timeout=20000)
            page.wait_for_selector('div.leading-6 span')
            logging.info("📡 Connected to BRTI page.")
        except Exception as e:
            logging.error(f"❌ Failed to load BRTI page: {e}")
            browser.close()
            return

        last_logged_price = None

        while True:
            try:
                price_text = page.locator('div.leading-6 span').first.text_content()
                price = float(price_text.replace('$', '').replace(',', ''))
                timestamp_dt = datetime.now().astimezone(est)
                timestamp = timestamp_dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

                latest_price['last_update_time'] = time.time()

                if not watchdog_enabled.is_set():
                    logging.info("✅ First price update received. Watchdog enabled.")
                    watchdog_enabled.set()

                if price != last_logged_price:
                    last_logged_price = price
                    latest_price['simple_average'].append(price)
                    if len(latest_price['simple_average']) > 60:
                        latest_price['simple_average'].pop(0)

                    sma = np.mean(latest_price['simple_average'])
                    latest_price['value'] = price
                    latest_price['timestamp'] = timestamp

                    process = psutil.Process(os.getpid())
                    mem_total = process.memory_info().rss
                    for child in process.children(recursive=True):
                        try:
                            mem_total += child.memory_info().rss
                        except psutil.NoSuchProcess:
                            pass
                    mem_mb = mem_total / 1024 / 1024    

                    logging.info(f"📈 BRTI: {price:.2f} | SMA(60): {sma:.2f} | Mem: {mem_mb:.2f}MB ")
                    insert_to_db(price, sma, timestamp)
         
            except Exception as e:
                logging.error(f"⚠️ Error in polling loop: {e}")

            time.sleep(0.3)


def watchdog(timeout_seconds=5):
    logging.info("⏳ Watchdog waiting for first price update...")
    watchdog_enabled.wait()
    logging.info("👀 Watchdog started.")

    while True:
        elapsed = time.time() - latest_price.get('last_update_time', 0)
        if elapsed > timeout_seconds:
            logging.error(f"⏱️ No price update in {elapsed:.2f}s. Restarting...")
            safe_restart()
        time.sleep(1)


if __name__ == "__main__":
    threading.Thread(target=watchdog, daemon=True).start()
    poll_brti()
