import os
import numpy as np
import pytz
import time
import json
from datetime import datetime
from playwright.sync_api import sync_playwright
from .logging_utils import setup_logging
from .parquet_writer import ParquetWriter
from .browser import create_new_browser_session, test_connection
from .shadowban import ShadowBanDetector, wait_for_retry

class BRTIDataCollector:
    def __init__(self):
        self.est_tz = pytz.timezone('US/Eastern')
        self.logger = setup_logging()
        self.price_parquet = 'data/brti_price_data.parquet'
        self.batch_size = 30
        self.shadow_ban_timeout = 20
        self.retry_wait_time = 300
        self.max_consecutive_retries = 5
        self.writer = ParquetWriter(self.price_parquet, self.batch_size, self.logger)
        self.shadowban = ShadowBanDetector(self.shadow_ban_timeout)
        self.latest_price = {'value': None, 'timestamp': None, 'simple_average': []}
        self.session_start_time = None
        self.session_price_updates = 0
        self.total_sessions = 0
        os.makedirs('data', exist_ok=True)
        os.makedirs('logs', exist_ok=True)
        self.logger.info(f"BRTI Parquet file configured:")
        self.logger.info(f"   - {self.price_parquet}")
        self.logger.info(f"   - Price batch size: {self.batch_size}")
        self.logger.info(f"   - Shadow ban timeout: {self.shadow_ban_timeout}s")
        self.logger.info(f"   - Retry wait time: {self.retry_wait_time}s")
        self.logger.info(f"   - Log file: logs/brti_backoff_analysis.log")

    def timestamp_to_est(self, timestamp_ms):
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
        est_time = dt.astimezone(self.est_tz)
        return est_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    def log_session_start(self):
        self.session_start_time = time.time()
        self.session_price_updates = 0
        self.total_sessions += 1
        self.logger.info(f"SESSION_START | Session #{self.total_sessions} | Time: {datetime.now()}")

    def log_session_end(self, reason, retry_count=None):
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
        self.logger.info(f"SESSION_SUMMARY | Session #{self.total_sessions} lasted {session_duration_minutes:.1f} minutes with {self.session_price_updates} updates | Reason: {reason}")

    def log_shadow_ban_detection(self, time_since_last_update):
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

    def log_consecutive_failures(self, failure_count, failure_type, max_failures=5):
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
        self.session_price_updates += 1
        if self.session_price_updates <= 5 or self.session_price_updates % 100 == 0:
            update_data = {
                'update_time': datetime.now().isoformat(),
                'price': price,
                'session_update_count': self.session_price_updates,
                'session_duration_minutes': round((time.time() - self.session_start_time) / 60, 2) if self.session_start_time else None
            }
            log_message = f"PRICE_UPDATE | {json.dumps(update_data, indent=None)}"
            self.logger.info(log_message)

    def poll_brti(self):
        self.logger.info("Starting Playwright polling loop...")
        retry_count = 0
        with sync_playwright() as p:
            while retry_count < self.max_consecutive_retries:
                try:
                    browser, page = create_new_browser_session(p, self.logger)
                    if not browser or not page:
                        retry_count += 1
                        if retry_count < self.max_consecutive_retries:
                            wait_for_retry(retry_count, self.retry_wait_time, self.logger)
                        continue
                    if not test_connection(page, self.logger):
                        self.logger.warning("Initial connection test failed - possible shadow ban")
                        browser.close()
                        retry_count += 1
                        if retry_count < self.max_consecutive_retries:
                            wait_for_retry(retry_count, self.retry_wait_time, self.logger)
                        continue
                    self.logger.info("Connected to BRTI page successfully")
                    self.log_session_start()
                    last_logged_price = None
                    self.shadowban.update()
                    consecutive_failures = 0
                    retry_count = 0
                    while True:
                        try:
                            receipt_timestamp_ms = time.time() * 1000
                            price_text = page.locator('div.leading-6 span').first.text_content()
                            if not price_text or price_text.strip() == '':
                                consecutive_failures += 1
                                self.logger.warning(f"Empty price text (failure #{consecutive_failures})")
                                if consecutive_failures >= 5:
                                    self.log_consecutive_failures(consecutive_failures, "empty_price_text")
                                    self.logger.warning("Too many consecutive failures - possible shadow ban")
                                    break
                                time.sleep(1)
                                continue
                            price = float(price_text.replace('$', '').replace(',', ''))
                            if price <= 0:
                                consecutive_failures += 1
                                self.logger.warning(f"Invalid price: {price} (failure #{consecutive_failures})")
                                if consecutive_failures >= 5:
                                    self.log_consecutive_failures(consecutive_failures, "invalid_price")
                                    self.logger.warning("Too many invalid prices - possible shadow ban")
                                    break
                                time.sleep(1)
                                continue
                            consecutive_failures = 0
                            if price != last_logged_price:
                                last_logged_price = price
                                self.shadowban.update()
                                self.latest_price['value'] = price
                                self.latest_price['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                self.latest_price['simple_average'].append(price)
                                if len(self.latest_price['simple_average']) > 60:
                                    self.latest_price['simple_average'].pop(0)
                                simple_avg = np.mean(self.latest_price['simple_average']) if self.latest_price['simple_average'] else price
                                timestamp_est = self.timestamp_to_est(receipt_timestamp_ms)
                                self.writer.add_price(price, receipt_timestamp_ms, timestamp_est, simple_avg)
                                self.log_price_update(price)
                            if self.shadowban.is_shadow_banned():
                                time_since_last_update = time.time() - self.shadowban.last_price_update_time
                                self.log_shadow_ban_detection(time_since_last_update)
                                self.logger.warning(f"Shadow ban detected - no price updates for {self.shadow_ban_timeout} seconds")
                                break
                        except Exception as e:
                            consecutive_failures += 1
                            self.logger.error(f"Error while fetching price (failure #{consecutive_failures}): {e}")
                            if consecutive_failures >= 5:
                                self.log_consecutive_failures(consecutive_failures, "fetch_error")
                                self.logger.warning("Too many consecutive errors - possible shadow ban")
                                break
                        time.sleep(0.3)
                    self.log_session_end("shadow_ban_detected", retry_count)
                    browser.close()
                    retry_count += 1
                    if retry_count < self.max_consecutive_retries:
                        self.logger.info(f"Attempting reconnection (retry #{retry_count}/{self.max_consecutive_retries})")
                        wait_for_retry(retry_count, self.retry_wait_time, self.logger)
                    else:
                        self.logger.error(f"Maximum retries ({self.max_consecutive_retries}) reached. Giving up.")
                        break
                except KeyboardInterrupt:
                    self.log_session_end("user_interrupt")
                    raise
                except Exception as e:
                    self.log_session_end("unexpected_error")
                    self.logger.error(f"Unexpected error in polling loop: {e}")
                    retry_count += 1
                    if retry_count < self.max_consecutive_retries:
                        wait_for_retry(retry_count, self.retry_wait_time, self.logger)
    def flush_remaining_batches(self):
        self.logger.info("Flushing remaining batches...")
        self.writer.flush()
        self.logger.info("SHUTDOWN | All remaining batches flushed")
    def run(self):
        try:
            self.poll_brti()
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            self.flush_remaining_batches() 