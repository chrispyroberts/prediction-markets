from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import numpy as np
import threading
import time
import os
import pandas as pd
import pytz
import logging
import json
import atexit # Shutdown handler
import signal
import sys
import psycopg2
import psycopg2.extras
import urllib.request
import urllib.parse
from zoneinfo import ZoneInfo

# Increase recursion limit to handle deep function calls
sys.setrecursionlimit(100000)  # Increase from default ~1000 to 10000

# === WebSocket Imports ===
import eventlet
eventlet.monkey_patch()
from flask import Flask, jsonify, request
from flask_socketio import SocketIO
from flask_cors import CORS

# === WebSocket Setup ===
app = Flask(__name__)
CORS(app, supports_credentials=True)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')

# === Configuration ===
DEBUG = False
def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

# === Database Configuration ===
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "chris_db"
DB_USER = "postgres"
DB_PASS = "password" # The password you set when starting the Docker container


class BRTIDataCollector:
    def __init__(self, disable_terminal_output=False):
        self.latest_price = {'value': None, 'timestamp': None, 'simple_average': []}
        
        # Terminal output toggle
        self.disable_terminal_output = disable_terminal_output
        
        # WebSocket client tracking
        self.active_clients = set()
        
        # Database batching setup
        self.price_batch = []
        self.price_batch_lock = threading.Lock()
        self.price_batch_size = 30  # Write every 30 price updates
        
        # Binance option price cache
        self.binance_option_cache = {'price': None, 'timestamp': None, 'cache_duration': 30}  # Cache for 30 seconds
        
        # Shadow ban detection
        self.last_price_update_time = None
        self.shadow_ban_timeout = 20  # If no price update for 20 seconds, assume shadow banned
        self.retry_wait_time = 300  # Wait before retrying
        self.max_consecutive_retries = 5  # Maximum retries before giving up
        
        # Connection session tracking
        self.session_start_time = None
        self.session_price_updates = 0
        self.total_sessions = 0
        
        # Ensure log directory exists
        os.makedirs(r'C:\Users\chris\OneDrive\Desktop\Programming\Trading\prediction markets\crypto\DATA\data_collection_2\logs', exist_ok=True)
        
        # EST timezone
        self.est_tz = pytz.timezone('US/Eastern')
        
        # Setup logging
        self.setup_logging()
        
        # Establish database connection
        self.conn = self.connect_to_db()
        
        if not self.disable_terminal_output:
            print(f"BRTI Database configuration:")
            print(f"   - Host: {DB_HOST}, DB: {DB_NAME}")
            print(f"   - Price batch size: {self.price_batch_size}")
            print(f"   - Shadow ban timeout: {self.shadow_ban_timeout}s")
            print(f"   - Retry wait time: {self.retry_wait_time}s")
            print(f"   - Log file: logs/data_logs_2.log")
        
        # Register exit handlers for ANY exit scenario
        self.register_exit_handlers()
        
        # Setup WebSocket event handlers
        self.setup_websocket_handlers()
        
    
    def get_binance_option_mark_price(self, brti_price):
        """Get Binance option mark price for near-the-money options expiring soon"""        
        base_url = "https://eapi.binance.com/eapi/v1/mark"
        
        try:            
            # Create request with custom headers
            req = urllib.request.Request(
                base_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            
            # Make the request
            with urllib.request.urlopen(req, timeout=10) as response:
                received_data = json.loads(response.read().decode('utf-8'))

            nearest_expiry_ATM = []
            expiry_string = None
            est = ZoneInfo("America/New_York")
            current_time = datetime.now(est)
            
            for option in received_data:
                full_symbol = option['symbol']
                symbol_parts = full_symbol.split('-')
                
                if len(symbol_parts) < 3:
                    continue
                    
                symbol = symbol_parts[0]

                if symbol != 'BTC':
                    continue

                expiration = symbol_parts[1]
                strike = int(symbol_parts[2])
                markIV = float(option['markIV'])

                # Parse expiration date (format: YYMMDD)
                if len(expiration) != 6:
                    continue
                    
                year = int(expiration[:2]) + 2000
                month = int(expiration[2:4])
                day = int(expiration[4:6])

                # Convert to a datetime object
                expiration_date = datetime(year, month, day, 4, 0, 0, tzinfo=est)

                # Calculate time delta
                delta = expiration_date - current_time

                if delta.total_seconds() <= 0:
                    return None, None  # Already expired

                hours, remainder = divmod(int(delta.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)

                # Find all options expiring soon (within 1 day)
                if expiration_date < current_time + timedelta(days=1):
                    # Check they are near the money (within $1000 of BRTI price)
                    if abs(strike - brti_price) < 600:
                        nearest_expiry_ATM.append(markIV)
                        expiry_string = f"{hours} hours {minutes} minutes {seconds} seconds"
            
            try:
                return np.mean(nearest_expiry_ATM) if nearest_expiry_ATM else None, expiry_string
            except Exception as e:
                print("Error calculating mean")
                return None, None
        except Exception as e:
            print(f"Error processing Binance option data: {e}")
            return None, None


    def register_exit_handlers(self):
        """Register comprehensive exit handlers to ensure data flushing on ANY exit"""
        # Register atexit handler (runs on normal exit)
        atexit.register(self.cleanup_and_exit)
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, self.signal_handler)
        
        self.logger.info("EXIT_HANDLERS_REGISTERED | atexit, SIGINT, SIGTERM, SIGHUP handlers installed")
        
    def signal_handler(self, signum, frame):
        """Handle interrupt signals (Ctrl+C, SIGTERM, etc.)"""
        signal_name = {
            signal.SIGINT: "SIGINT",
            signal.SIGTERM: "SIGTERM",
            signal.SIGHUP: "SIGHUP" if hasattr(signal, 'SIGHUP') else "UNKNOWN"
        }.get(signum, f"Signal {signum}")
        
        self.logger.info(f"SIGNAL_RECEIVED | {signal_name} - initiating graceful shutdown")
        self.cleanup_and_exit()
        sys.exit(0)
        
    def cleanup_and_exit(self):
        """Comprehensive cleanup function that runs on ANY exit"""
        try:
            self.logger.info("CLEANUP_STARTED | Flushing all remaining data...")
            
            # Flush any remaining batches
            self.flush_remaining_batches()
            
            # Close the database connection
            if self.conn:
                self.conn.close()
                self.logger.info("DATABASE_CONNECTION_CLOSED | Connection closed successfully.")
            
            # Log final stats
            stats = self.get_stats()
            self.logger.info(f"SHUTDOWN_STATS | {stats}")
            
            self.logger.info("CLEANUP_COMPLETED | All data flushed, exiting cleanly")
            
        except Exception as e:
            self.logger.error(f"CLEANUP_ERROR | Error during cleanup: {str(e)}")
            if not self.disable_terminal_output:
                print(f"ERROR: {e}")
        
    def get_stats(self):
        """Get current collection statistics"""
        return {
            'total_sessions': self.total_sessions,
            'current_session_updates': self.session_price_updates,
            'pending_batch_size': len(self.price_batch),
            'last_price': self.latest_price.get('value'),
            'last_price_time': self.latest_price.get('timestamp')
        }
        
    def print_if_enabled(self, *args, **kwargs):
        """Print only if terminal output is enabled"""
        if not self.disable_terminal_output:
            print(*args, **kwargs)
        
    def setup_logging(self):
        """Setup comprehensive logging for backoff analysis"""
        # Create logger
        self.logger = logging.getLogger('BRTIBackoffAnalysis')
        self.logger.setLevel(logging.INFO)
        
        # Create file handler
        log_file = r'C:\Users\chris\OneDrive\Desktop\Programming\Trading\prediction markets\crypto\DATA\data_collection_2\logs\data_logs_2.log'
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        
        # Create console handler for important events (only if terminal output is enabled)
        if not self.disable_terminal_output:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.WARNING)
            console_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
            self.logger.addHandler(console_handler)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
        file_handler.setFormatter(formatter)
        
        # Add file handler
        self.logger.addHandler(file_handler)
        
        # Log startup
        self.logger.info("="*80)
        self.logger.info("BRTI DATA COLLECTOR STARTED")
        self.logger.info("="*80)
        
    def connect_to_db(self):
        """Establishes and returns a connection to the PostgreSQL database."""
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASS
            )
            self.logger.info(f"DATABASE_CONNECTED | Successfully connected to '{DB_NAME}' on {DB_HOST}:{DB_PORT}")
            return conn
        except psycopg2.OperationalError as e:
            self.logger.error(f"DATABASE_CONNECTION_ERROR | Could not connect to database: {e}")
            self.print_if_enabled(f"FATAL: Could not connect to the database. Please check credentials and that the Docker container is running. Error: {e}")
            sys.exit(1) # Exit if we can't connect at startup
        
    def log_session_start(self):
        """Log the start of a new session"""
        self.session_start_time = time.time()
        self.session_price_updates = 0
        self.total_sessions += 1
        
        self.logger.info(f"SESSION_START | Session #{self.total_sessions} | Time: {datetime.now()}")
        
    def log_session_end(self, reason, retry_count=None):
        """Log the end of a session with detailed metrics"""
        if self.session_start_time is None:
            return
            
        session_duration = time.time() - self.session_start_time
        session_duration_minutes = session_duration / 60
        
        session_data = {
            'session_number': self.total_sessions,
            'start_time': datetime.fromtimestamp(self.session_start_time).isoformat(),
            'end_time': datetime.now().isoformat(),
            'duration_seconds': round(session_duration, 2),
            'duration_minutes': round(session_duration_minutes, 2),
            'price_updates_received': self.session_price_updates,
            'end_reason': reason,
            'retry_count': retry_count
        }
        
        if session_duration > 0:
            updates_per_minute = self.session_price_updates / session_duration_minutes
            session_data['updates_per_minute'] = round(updates_per_minute, 2)
        
        log_message = f"SESSION_END | {json.dumps(session_data, indent=None)}"
        self.logger.info(log_message)
        
        # Also log a human-readable summary
        self.logger.info(f"SESSION_SUMMARY | Session #{self.total_sessions} lasted {session_duration_minutes:.1f} minutes with {self.session_price_updates} updates | Reason: {reason}")
        
    def log_shadow_ban_detection(self, time_since_last_update):
        """Log shadow ban detection with detailed timing"""
        ban_data = {
            'detection_time': datetime.now().isoformat(),
            'time_since_last_update_seconds': round(time_since_last_update, 2),
            'time_since_last_update_minutes': round(time_since_last_update / 60, 2),
            'threshold_seconds': self.shadow_ban_timeout,
            'session_updates_before_ban': self.session_price_updates,
            'session_duration_before_ban': round(time.time() - self.session_start_time, 2) if self.session_start_time else None
        }
        
        log_message = f"SHADOW_BAN_DETECTED | {json.dumps(ban_data, indent=None)}"
        self.logger.warning(log_message)
        
    def log_retry_attempt(self, retry_count, wait_time):
        """Log retry attempt with timing"""
        retry_data = {
            'retry_number': retry_count,
            'max_retries': self.max_consecutive_retries,
            'wait_time_seconds': wait_time,
            'wait_time_minutes': round(wait_time / 60, 2),
            'retry_start_time': datetime.now().isoformat()
        }
        
        log_message = f"RETRY_ATTEMPT | {json.dumps(retry_data, indent=None)}"
        self.logger.warning(log_message)
        
    def log_connection_test(self, success, error_message=None):
        """Log connection test results"""
        test_data = {
            'test_time': datetime.now().isoformat(),
            'success': success,
            'error_message': error_message
        }
        
        log_message = f"CONNECTION_TEST | {json.dumps(test_data, indent=None)}"
        
        if success:
            self.logger.info(log_message)
        else:
            self.logger.warning(log_message)
            
    def log_consecutive_failures(self, failure_count, failure_type, max_failures=5):
        """Log consecutive failure patterns"""
        failure_data = {
            'failure_time': datetime.now().isoformat(),
            'failure_type': failure_type,
            'consecutive_count': failure_count,
            'max_threshold': max_failures,
            'session_updates_before_failure': self.session_price_updates
        }
        
        log_message = f"CONSECUTIVE_FAILURES | {json.dumps(failure_data, indent=None)}"
        self.logger.warning(log_message)
        
    def log_price_update(self, price):
        """Log successful price updates (for session tracking)"""
        self.session_price_updates += 1
        
        # Log every 100 updates or first few updates
        if self.session_price_updates <= 5 or self.session_price_updates % 100 == 0:
            update_data = {
                'update_time': datetime.now().isoformat(),
                'price': price,
                'session_update_count': self.session_price_updates,
                'session_duration_minutes': round((time.time() - self.session_start_time) / 60, 2) if self.session_start_time else None
            }
            
            log_message = f"PRICE_UPDATE | {json.dumps(update_data, indent=None)}"
            self.logger.info(log_message)
        
    def timestamp_to_est(self, timestamp_ms):
        """Convert timestamp to EST string"""
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
        est_time = dt.astimezone(self.est_tz)
        return est_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
    def write_price_batch_to_db(self, batch_data):
        """Write price batch to the TimescaleDB database."""
        if not batch_data:
            return

        if not self.conn:
            self.logger.error("DB_WRITE_ERROR | No database connection available.")
            return

        try:
            with self.conn.cursor() as cur:
                # Use execute_values for efficient bulk insertion
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO brti_prices (timestamp_ms, brti_price, simple_average, binance_option_price) VALUES %s",
                    batch_data,
                    page_size=len(batch_data)
                )
                self.conn.commit()
                self.print_if_enabled(f"💾 BRTI BATCH: Wrote {len(batch_data)} records to Database")
                self.logger.info(f"DB_BATCH_WRITE_SUCCESS | Wrote {len(batch_data)} records to brti_prices")
        except (Exception, psycopg2.Error) as e:
            self.logger.error(f"DB_WRITE_ERROR | Failed to write batch to database: {e}")
            self.print_if_enabled(f"ERROR: Failed to write to database: {e}")
            # Attempt to rollback the faulty transaction
            self.conn.rollback()

    def add_price_to_batch(self, price, binance_option_price, receipt_timestamp_ms, expiry_time):
        """Add price data to batch for DB writing"""
        # Update simple average
        self.latest_price['simple_average'].append(price)
        if len(self.latest_price['simple_average']) > 60:
            self.latest_price['simple_average'].pop(0)
            
        simple_avg = np.mean(self.latest_price['simple_average']) if self.latest_price['simple_average'] else price
        
        # Get Binance option mark price
        # binance_option_price = self.get_binance_option_mark_price(price)
        
        # The row format must match the database table schema
        row = [
            int(receipt_timestamp_ms),
            float(price),
            float(simple_avg),
            float(binance_option_price) if binance_option_price is not None else None
        ]
        
        with self.price_batch_lock:
            self.price_batch.append(row)
            
            # Write batch when it reaches batch size
            if len(self.price_batch) >= self.price_batch_size:
                batch_to_write = self.price_batch.copy()
                self.price_batch.clear()
                
                # Write directly, no need for a new thread for this
                self.write_price_batch_to_db(batch_to_write)
        
        timestamp_est = self.timestamp_to_est(receipt_timestamp_ms)
        
        # Log the prices
        log_message = f"💰 BRTI QUEUED [{timestamp_est}] Price: ${price:,.2f}"
        if binance_option_price is not None:
            log_message += f" | Binance Option: {binance_option_price*100:,.4f}% | Expiry: {expiry_time}"
        else:
            log_message += " | Binance Option: N/A"
            
        self.print_if_enabled(log_message)
        
        # Emit WebSocket update
        self.emit_price_update(price, simple_avg, timestamp_est, binance_option_price)
        
    def emit_price_update(self, price, simple_avg, timestamp_est, binance_option_price):
        """Emit price update to all connected WebSocket clients"""
        if self.active_clients:
            update_payload = {
                'brti': price,
                'simple_average': simple_avg,
                'timestamp': timestamp_est,
                'active_clients': len(self.active_clients),
                'binance_option_price': binance_option_price
            }
            
            try:
                socketio.emit('price_update', update_payload)
                self.print_if_enabled(f"📡 WebSocket: Emitted price update to {len(self.active_clients)} clients")
            except Exception as e:
                self.logger.error(f"WEBSOCKET_EMIT_ERROR | Failed to emit price update: {e}")
        
    def is_shadow_banned(self):
        """Check if we're potentially shadow banned (no price updates for too long)"""
        if self.last_price_update_time is None:
            return False
            
        time_since_last_update = time.time() - self.last_price_update_time
        return time_since_last_update > self.shadow_ban_timeout
        
    def test_connection(self, page):
        """Test if we can successfully get price data from the page"""
        try:
            # Try to get the price element
            price_element = page.locator('div.leading-6 span').first
            
            # Wait for element to be present (with timeout)
            price_element.wait_for(state='visible', timeout=10000)
            
            # Try to get the text content
            price_text = price_element.text_content()
            
            if not price_text or price_text.strip() == '':
                self.log_connection_test(False, "Price element found but empty content")
                self.print_if_enabled("⚠️ Price element found but empty content - possible shadow ban")
                return False
                
            # Try to parse as float
            price = float(price_text.replace('$', '').replace(',', ''))
            
            if price <= 0:
                self.log_connection_test(False, f"Invalid price value: {price}")
                self.print_if_enabled("⚠️ Invalid price value - possible shadow ban")
                return False
                
            self.log_connection_test(True)
            self.print_if_enabled(f"Connection test successful - Price: ${price:,.2f}")
            return True
            
        except Exception as e:
            self.print_if_enabled(f"Connection test failed: {e}")
            return False
            
    def wait_for_retry(self, retry_count):
        """Wait before retrying with countdown"""
        wait_time = self.retry_wait_time
        self.log_retry_attempt(retry_count, wait_time)
        self.print_if_enabled(f"⏳ Waiting {wait_time} seconds before retry #{retry_count}...")
        
        for remaining in range(wait_time, 0, -1):
            if remaining % 30 == 0 or remaining <= 10:  # Log every 30s or last 10s
                self.print_if_enabled(f"⏳ Retrying in {remaining} seconds...")
            time.sleep(1)
            
    def create_new_browser_session(self, p):
        """Create a fresh browser session"""
        try:
            self.print_if_enabled("Creating new browser session...")
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Set a realistic user agent
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            })
            
            self.print_if_enabled("Navigating to BRTI page...")
            page.goto("https://www.cfbenchmarks.com/data/indices/BRTI", timeout=20000)
            
            return browser, page
            
        except Exception as e:
            self.print_if_enabled(f"Failed to create browser session: {e}")
            return None, None
        
    def poll_brti(self):
        """Poll BRTI price data using Playwright with shadow ban detection"""
        self.print_if_enabled("🌀 Starting Playwright polling loop...")
        
        retry_count = 0
        
        with sync_playwright() as p:
            while retry_count < self.max_consecutive_retries:
                try:
                    # Create new browser session
                    browser, page = self.create_new_browser_session(p)
                    if not browser or not page:
                        retry_count += 1
                        if retry_count < self.max_consecutive_retries:
                            self.wait_for_retry(retry_count)
                        continue
                    
                    # Test initial connection
                    if not self.test_connection(page):
                        self.print_if_enabled("🚫 Initial connection test failed - possible shadow ban")
                        browser.close()
                        retry_count += 1
                        if retry_count < self.max_consecutive_retries:
                            self.wait_for_retry(retry_count)
                        continue
                    
                    self.print_if_enabled("📡 Connected to BRTI page successfully")
                    self.log_session_start()
                    
                    last_logged_price = None
                    self.last_price_update_time = time.time()
                    consecutive_failures = 0
                    
                    # Reset retry count on successful connection
                    retry_count = 0
                    
                    # Main polling loop
                    while True:
                        try:
                            # Get timestamp immediately when we check the page
                            receipt_timestamp_ms = time.time() * 1000
                            
                            price_text = page.locator('div.leading-6 span').first.text_content()
                            
                            if not price_text or price_text.strip() == '':
                                consecutive_failures += 1
                                self.print_if_enabled(f"⚠️ Empty price text (failure #{consecutive_failures})")
                                
                                if consecutive_failures >= 5:
                                    self.log_consecutive_failures(consecutive_failures, "empty_price_text")
                                    self.print_if_enabled("🚫 Too many consecutive failures - possible shadow ban")
                                    break
                                    
                                time.sleep(1)
                                continue
                            
                            price = float(price_text.replace('$', '').replace(',', ''))
                            
                            if price <= 0:
                                consecutive_failures += 1
                                self.print_if_enabled(f"⚠️ Invalid price: {price} (failure #{consecutive_failures})")
                                
                                if consecutive_failures >= 5:
                                    self.log_consecutive_failures(consecutive_failures, "invalid_price")
                                    self.print_if_enabled("🚫 Too many invalid prices - possible shadow ban")
                                    break
                                    
                                time.sleep(1)
                                continue

                            # Reset failure counter on successful price fetch
                            consecutive_failures = 0

                            if price != last_logged_price:
                                last_logged_price = price
                                self.last_price_update_time = time.time()
                                
                                # Update latest_price state
                                self.latest_price['value'] = price
                                self.latest_price['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                                binance_option_price, expiry_time = self.get_binance_option_mark_price(price)
                                
                                # Add to batch for DB writing
                                self.add_price_to_batch(price, binance_option_price, receipt_timestamp_ms, expiry_time)
                                
                                # Log price update for session tracking
                                self.log_price_update(price)
                                
                            # Check for shadow ban
                            if self.is_shadow_banned():
                                time_since_last_update = time.time() - self.last_price_update_time
                                self.log_shadow_ban_detection(time_since_last_update)
                                self.print_if_enabled(f"🚫 Shadow ban detected - no price updates for {self.shadow_ban_timeout} seconds")
                                break

                        except Exception as e:
                            consecutive_failures += 1
                            self.print_if_enabled(f"⚠️ Error while fetching price (failure #{consecutive_failures}): {e}")
                            
                            if consecutive_failures >= 5:
                                self.log_consecutive_failures(consecutive_failures, "fetch_error", e)
                                self.print_if_enabled("🚫 Too many consecutive errors - possible shadow ban")
                                break

                        time.sleep(0.3)  # Poll every 300ms
                    
                    # Log session end
                    self.log_session_end("shadow_ban_detected", retry_count)
                    
                    # Close browser before retry
                    browser.close()
                    
                    # If we got here, we detected a shadow ban
                    retry_count += 1
                    if retry_count < self.max_consecutive_retries:
                        self.print_if_enabled(f"Attempting reconnection (retry #{retry_count}/{self.max_consecutive_retries})")
                        self.wait_for_retry(retry_count)
                    else:
                        self.logger.error(f"MAXIMUM_RETRIES_REACHED | Gave up after {self.max_consecutive_retries} attempts")
                        self.print_if_enabled(f"Maximum retries ({self.max_consecutive_retries}) reached. Giving up.")
                        break
                        
                except KeyboardInterrupt:
                    self.log_session_end("user_interrupt")
                    raise
                except Exception as e:
                    self.log_session_end("unexpected_error")
                    self.print_if_enabled(f"Unexpected error in polling loop: {e}")
                    retry_count += 1
                    if retry_count < self.max_consecutive_retries:
                        self.wait_for_retry(retry_count)
                    
    def flush_remaining_batches(self):
        """Flush any remaining data in batches before shutdown"""
        self.print_if_enabled("Flushing remaining batches...")
        
        with self.price_batch_lock:
            if self.price_batch:
                self.write_price_batch_to_db(self.price_batch)
                self.price_batch.clear()
                
        self.print_if_enabled("All batches flushed")
        self.logger.info("SHUTDOWN | All remaining batches flushed")
        
    def run(self):
        """Main run loop"""
        try:
            # Start WebSocket server in a separate thread
            websocket_thread = threading.Thread(target=self.start_websocket_server, daemon=True)
            websocket_thread.start()
            
            # Start the main polling loop
            self.poll_brti()
        except Exception as e:
            self.logger.error(f"RUN_ERROR | Unexpected error in main loop: {str(e)}")
            self.print_if_enabled(f"Unexpected error: {e}")
            # cleanup_and_exit will be called by atexit handler
            
    def start_websocket_server(self):
        """Start the WebSocket server"""
        try:
            self.print_if_enabled("🌐 Starting WebSocket server on http://localhost:5001...")
            self.logger.info("WEBSOCKET_SERVER_STARTING | Port: 5001")
            socketio.run(app, host="127.0.0.1", port=5001)
        except Exception as e:
            self.logger.error(f"WEBSOCKET_SERVER_ERROR | Failed to start WebSocket server: {e}")
            self.print_if_enabled(f"WebSocket server error: {e}")

    def setup_websocket_handlers(self):
        """Setup WebSocket event handlers"""
        @socketio.on('connect')
        def handle_connect():
            sid = request.sid
            self.active_clients.add(sid)
            self.print_if_enabled(f"🔗 WebSocket client connected: {sid}")
            self.logger.info(f"WEBSOCKET_CLIENT_CONNECTED | Session ID: {sid}")
        
        @socketio.on('disconnect')
        def handle_disconnect():
            sid = request.sid
            self.active_clients.discard(sid)
            self.print_if_enabled(f"❌ WebSocket client disconnected: {sid}")
            self.logger.info(f"WEBSOCKET_CLIENT_DISCONNECTED | Session ID: {sid}")
        
        # Store handlers as instance methods for access
        self.handle_connect = handle_connect
        self.handle_disconnect = handle_disconnect

# === Flask Routes ===
@app.route('/price', methods=['GET'])
def get_price():
    """REST endpoint to get current BRTI price"""
    collector = getattr(app, 'collector_instance', None)
    if not collector or collector.latest_price['value'] is None:
        return jsonify({'status': 'waiting for data'}), 503
    
    simple_avg = np.mean(collector.latest_price['simple_average']) if collector.latest_price['simple_average'] else collector.latest_price['value']
    
    # TEMPORARILY DISABLE BINANCE OPTION PRICE TO DEBUG RECURSION
    # Get current Binance option price
    # current_brti = collector.latest_price['value']
    # binance_option_price = collector.get_cached_binance_option_price(current_brti)
    binance_option_price = None  # Temporarily disabled
    
    return jsonify({
        'brti': collector.latest_price['value'],
        'simple_average': simple_avg,
        'timestamp': collector.latest_price['timestamp'],
        'active_clients': len(collector.active_clients),
        'binance_option_price': binance_option_price
    })

def main():
    # Check if running in unified mode (disable terminal output)
    disable_terminal_output = os.environ.get('BRTI_DISABLE_TERMINAL', 'false').lower() == 'true'
    
    collector = BRTIDataCollector(disable_terminal_output=disable_terminal_output)
    
    # Store collector instance in Flask app for REST endpoint access
    app.collector_instance = collector
    
    try:
        collector.run()
    except Exception as e:
        collector.logger.error(f"MAIN_ERROR | Error in main: {str(e)}")
        collector.print_if_enabled(f"Main error: {e}")
        # cleanup_and_exit will be called by atexit handler

if __name__ == "__main__":
    if not os.environ.get('BRTI_DISABLE_TERMINAL', 'false').lower() == 'true':
        print("Starting BRTI Data Collector...")
        print("Bitcoin Real Time Index (BRTI)")
        print("Storage: TimescaleDB")
        print("WebSocket: http://localhost:5001")
        print("REST API: http://localhost:5001/price")
        print("Timestamps at data receipt")
        print("Batched writes for efficiency")
        print("Timezone: EST")
        print("Shadow ban detection enabled")
        print("Detailed logging enabled: logs/data_logs_2.log")
        print("Press Ctrl+C to stop\n")
    
    try:
        main()
    except Exception as e:
        print(f"Fatal error: {e}")
        # cleanup_and_exit will be called by atexit handler
    except Exception as e:
        print(f"Fatal error: {e}")
        # cleanup_and_exit will be called by atexit handler