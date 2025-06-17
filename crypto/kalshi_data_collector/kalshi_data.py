import asyncio
import websockets
import json
import time
import os
import pandas as pd
import pytz
import threading
from datetime import datetime
import traceback
import logging

import atexit # Shutdown handler
import signal
import sys

from utils import sign_pss_text, private_key_obj, KALSHI_API_KEY_ID, get_current_event, get_markets_from_event, test_authentication

# === Configuration ===
DEBUG = False
def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

class KalshiDataCollector:
    def __init__(self, market_tickers, demo=True):
        self.tickers = market_tickers
        self.demo = demo
        
        # Current orderbook states
        self.orderbooks = {t: {'yes': {}, 'no': {}} for t in market_tickers}
        
        # Track last top-of-book state to detect changes
        self.last_top_of_book = {t: {'bid': None, 'bid_qty': None, 'ask': None, 'ask_qty': None} for t in market_tickers}
        
        # Parquet storage setup
        self.orderbook_batch = []
        self.trade_batch = []
        self.orderbook_batch_lock = threading.Lock()
        self.trade_batch_lock = threading.Lock()
        
        # Batch sizes for efficient writing
        self.orderbook_batch_size = 500  # Write every 500 orderbook updates
        self.trade_batch_size = 200      # Write every 200 trade records
        
        # Data collection stats
        self.total_orderbook_updates = 0
        self.total_trades = 0
        self.updates_written = 0
        self.trades_written = 0
        
        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)
        os.makedirs('logs', exist_ok=True)
        
        # Parquet file paths
        self.orderbook_parquet = 'data/kalshi_orderbook_data.parquet'
        self.trade_parquet = 'data/kalshi_trade_data.parquet'
        
        # EST timezone
        self.est_tz = pytz.timezone('US/Eastern')
        
        # Setup logging
        self.setup_logging()
        
        self.logger.info(f"Kalshi Data Collector initialized with {len(market_tickers)} markets")
        self.logger.info(f"Orderbook file: {self.orderbook_parquet}")
        self.logger.info(f"Trade file: {self.trade_parquet}")
        self.logger.info(f"Batch sizes - Orderbook: {self.orderbook_batch_size}, Trade: {self.trade_batch_size}")
        
    def setup_logging(self):
        """Setup comprehensive logging for the data collector"""
        # Create logger
        self.logger = logging.getLogger('KalshiDataCollector')
        self.logger.setLevel(logging.INFO)
        
        # Create file handler
        log_file = 'logs/kalshi_data_collector.log'
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        
        # Create console handler for important events only
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # Log startup
        self.logger.info("="*80)
        self.logger.info("KALSHI DATA COLLECTOR STARTED")
        self.logger.info("="*80)
        
    def timestamp_to_est(self, timestamp_ms):
        """Convert timestamp to EST string"""
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
        est_time = dt.astimezone(self.est_tz)
        return est_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
    def write_orderbook_batch_to_parquet(self, batch_data):
        """Write orderbook batch to Parquet file"""
        if not batch_data:
            return
            
        try:
            df = pd.DataFrame(batch_data, columns=[
                'timestamp_est', 'timestamp_ms', 'ticker', 'best_bid', 'best_bid_qty', 
                'best_ask', 'best_ask_qty', 'spread', 'mid_price'
            ])
            
            # Convert timestamp columns to appropriate types
            df['timestamp_est'] = pd.to_datetime(df['timestamp_est'])
            df['timestamp_ms'] = df['timestamp_ms'].astype('int64')
            
            # Append to existing parquet file or create new one
            if os.path.exists(self.orderbook_parquet):
                existing_df = pd.read_parquet(self.orderbook_parquet)
                combined_df = pd.concat([existing_df, df], ignore_index=True)
                combined_df.to_parquet(self.orderbook_parquet, compression='snappy', index=False)
            else:
                df.to_parquet(self.orderbook_parquet, compression='snappy', index=False)
                
            self.updates_written += len(batch_data)
            self.logger.info(f"ORDERBOOK_BATCH_WRITTEN | Records: {len(batch_data)} | Total written: {self.updates_written}")
            
        except Exception as e:
            self.logger.error(f"ORDERBOOK_BATCH_WRITE_ERROR | Error: {str(e)} | Batch size: {len(batch_data)}")
        
    def write_trade_batch_to_parquet(self, batch_data):
        """Write trade batch to Parquet file"""
        if not batch_data:
            return
            
        try:
            df = pd.DataFrame(batch_data, columns=[
                'timestamp_est', 'timestamp_ms', 'ticker', 'yes_price', 'no_price',
                'count', 'taker_side', 'trade_value'
            ])
            
            # Convert timestamp columns to appropriate types
            df['timestamp_est'] = pd.to_datetime(df['timestamp_est'])
            df['timestamp_ms'] = df['timestamp_ms'].astype('int64')
            
            # Append to existing parquet file or create new one
            if os.path.exists(self.trade_parquet):
                existing_df = pd.read_parquet(self.trade_parquet)
                combined_df = pd.concat([existing_df, df], ignore_index=True)
                combined_df.to_parquet(self.trade_parquet, compression='snappy', index=False)
            else:
                df.to_parquet(self.trade_parquet, compression='snappy', index=False)
                
            self.trades_written += len(batch_data)
            self.logger.info(f"TRADE_BATCH_WRITTEN | Records: {len(batch_data)} | Total written: {self.trades_written}")
            
        except Exception as e:
            self.logger.error(f"TRADE_BATCH_WRITE_ERROR | Error: {str(e)} | Batch size: {len(batch_data)}")
        
    def get_current_top_of_book(self, ticker):
        """Get current top of book with defaults for empty sides"""
        yes_book = self.orderbooks[ticker]['yes']
        no_book = self.orderbooks[ticker]['no']
        
        # Best bid (highest YES price) - defaults to 0 if no bids
        best_bid = max(yes_book.keys()) if yes_book else 0
        best_bid_qty = yes_book.get(best_bid, 0) if yes_book else 0
        
        # Best ask (lowest NO price converted to YES equivalent) - defaults to 100 if no asks
        best_ask = min(no_book.keys()) if no_book else 100
        best_ask_qty = no_book.get(best_ask, 0) if no_book else 0
        
        return {
            'bid': best_bid,
            'bid_qty': best_bid_qty,
            'ask': best_ask,
            'ask_qty': best_ask_qty
        }
        
    def has_top_of_book_changed(self, ticker, current_tob):
        """Check if top of book has changed from last known state"""
        last_tob = self.last_top_of_book[ticker]
        
        # Check if any of the top of book values have changed
        changed = (
            last_tob['bid'] != current_tob['bid'] or
            last_tob['bid_qty'] != current_tob['bid_qty'] or
            last_tob['ask'] != current_tob['ask'] or
            last_tob['ask_qty'] != current_tob['ask_qty']
        )
        
        return changed
        
    def add_orderbook_to_batch(self, ticker, receipt_timestamp_ms, current_tob):
        """Add orderbook data to batch for Parquet writing"""
        timestamp_est = self.timestamp_to_est(receipt_timestamp_ms)
        
        # Calculate derived metrics
        spread = current_tob['ask'] - current_tob['bid']
        mid_price = (current_tob['bid'] + current_tob['ask']) / 2
        
        row = [
            timestamp_est,
            int(receipt_timestamp_ms),
            ticker,
            current_tob['bid'],
            current_tob['bid_qty'],
            current_tob['ask'],
            current_tob['ask_qty'],
            spread,
            mid_price
        ]
        
        self.total_orderbook_updates += 1
        
        with self.orderbook_batch_lock:
            self.orderbook_batch.append(row)
            
            # Write batch when it reaches batch size
            if len(self.orderbook_batch) >= self.orderbook_batch_size:
                batch_to_write = self.orderbook_batch.copy()
                self.orderbook_batch.clear()
                
                # Write in background thread
                threading.Thread(
                    target=self.write_orderbook_batch_to_parquet,
                    args=(batch_to_write,),
                    daemon=True
                ).start()
        
        debug_print(f"TOB CHANGE {ticker.split('-')[-1]}: {current_tob['bid']}/{current_tob['ask']} | Mid: {mid_price:.1f}")
        
    def add_trade_to_batch(self, ticker, receipt_timestamp_ms, trade_data):
        """Add trade data to batch for Parquet writing"""
        timestamp_est = self.timestamp_to_est(receipt_timestamp_ms)
        
        yes_price = trade_data.get('yes_price', 0)
        no_price = 100 - yes_price if yes_price > 0 else 0
        count = trade_data.get('count', 0)
        taker_side = trade_data.get('taker_side', '')
        trade_value = yes_price * count  # Value in cents
        
        row = [
            timestamp_est,
            int(receipt_timestamp_ms),
            ticker,
            yes_price,
            no_price,
            count,
            taker_side,
            trade_value
        ]
        
        self.total_trades += 1
        
        with self.trade_batch_lock:
            self.trade_batch.append(row)
            
            # Write batch when it reaches batch size
            if len(self.trade_batch) >= self.trade_batch_size:
                batch_to_write = self.trade_batch.copy()
                self.trade_batch.clear()
                
                # Write in background thread
                threading.Thread(
                    target=self.write_trade_batch_to_parquet,
                    args=(batch_to_write,),
                    daemon=True
                ).start()
        
        debug_print(f"TRADE {ticker.split('-')[-1]}: {yes_price} x {count} ({taker_side})")

    async def update_orderbook_delta(self, ticker, msg, receipt_timestamp_ms):
        """Update orderbook from delta message and store data if top-of-book changed"""
        try:
            side = msg["side"]
            price = msg["price"]
            change = msg["delta"]
            
            if side.lower() == 'no':
                price = 100 - price  # Convert NO side price to YES side price
                
            qty = self.orderbooks[ticker][side].get(price, 0) + change
            if qty <= 0:
                self.orderbooks[ticker][side].pop(price, None)
            else:
                self.orderbooks[ticker][side][price] = qty

            # Get current top of book
            current_tob = self.get_current_top_of_book(ticker)
            
            # Check if top of book has changed
            if self.has_top_of_book_changed(ticker, current_tob):
                # Store the change
                self.add_orderbook_to_batch(ticker, receipt_timestamp_ms, current_tob)
                
                # Update our last known state
                self.last_top_of_book[ticker] = current_tob.copy()
                
        except Exception as e:
            self.logger.error(f"ORDERBOOK_DELTA_ERROR | Ticker: {ticker} | Error: {str(e)} | Message: {msg}")

    async def update_orderbook_snapshot(self, ticker, msg, receipt_timestamp_ms):
        """Update orderbook from snapshot message and store data if top-of-book changed"""
        try:
            self.orderbooks[ticker]['yes'] = {p: q for p, q in msg.get('yes', [])}
            self.orderbooks[ticker]['no'] = {100-p: q for p, q in msg.get('no', [])}

            # Get current top of book
            current_tob = self.get_current_top_of_book(ticker)
            
            # Check if top of book has changed
            if self.has_top_of_book_changed(ticker, current_tob):
                # Store the change
                self.add_orderbook_to_batch(ticker, receipt_timestamp_ms, current_tob)
                
                # Update our last known state
                self.last_top_of_book[ticker] = current_tob.copy()
                
        except Exception as e:
            self.logger.error(f"ORDERBOOK_SNAPSHOT_ERROR | Ticker: {ticker} | Error: {str(e)} | Message: {msg}")

    def process_trade(self, ticker, msg, receipt_timestamp_ms):
        """Process a trade message and store data"""
        try:
            self.add_trade_to_batch(ticker, receipt_timestamp_ms, msg)
        except Exception as e:
            self.logger.error(f"TRADE_PROCESSING_ERROR | Ticker: {ticker} | Error: {str(e)} | Message: {msg}")
        
    def flush_remaining_batches(self):
        """Flush any remaining data in batches before shutdown"""
        self.logger.info("FLUSH_BATCHES_START | Flushing remaining data")
        
        try:
            with self.orderbook_batch_lock:
                if self.orderbook_batch:
                    self.write_orderbook_batch_to_parquet(self.orderbook_batch)
                    self.orderbook_batch.clear()
                    
            with self.trade_batch_lock:
                if self.trade_batch:
                    self.write_trade_batch_to_parquet(self.trade_batch)
                    self.trade_batch.clear()
                    
            self.logger.info("FLUSH_BATCHES_COMPLETE | All batches successfully flushed")
            
        except Exception as e:
            self.logger.error(f"FLUSH_BATCHES_ERROR | Error during flush: {str(e)}")
            
    def get_stats(self):
        """Get current collection statistics"""
        return {
            'total_orderbook_updates': self.total_orderbook_updates,
            'total_trades': self.total_trades,
            'updates_written': self.updates_written,
            'trades_written': self.trades_written,
            'pending_orderbook': len(self.orderbook_batch),
            'pending_trades': len(self.trade_batch)
        }

# Global instance
collector = None
shutdown_event = asyncio.Event()

def cleanup_and_exit():
    """Cleanup data collector on exit"""
    global collector, shutdown_event
    
    try:
        if collector is not None:
            collector.logger.info("SHUTDOWN_START | Beginning cleanup process")
            collector.flush_remaining_batches()
            
            # Log final stats
            stats = collector.get_stats()
            collector.logger.info(f"SHUTDOWN_STATS | {stats}")
        else:
            print("ℹ️ No data collector instance found")
            
    except Exception as e:
        if collector:
            collector.logger.error(f"CLEANUP_ERROR | Error during cleanup: {str(e)}")
        else:
            print(f"❌ Error during cleanup: {e}")
    
    # Signal all async tasks to stop
    if shutdown_event and not shutdown_event.is_set():
        shutdown_event.set()

# Register cleanup handlers
atexit.register(cleanup_and_exit)

def signal_handler(signum, frame):
    """Handle interrupt signals (Ctrl+C, etc.)"""
    if collector:
        collector.logger.info(f"SIGNAL_RECEIVED | Signal: {signum}")
    cleanup_and_exit()
    sys.exit(0)

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
if hasattr(signal, 'SIGHUP'):
    signal.signal(signal.SIGHUP, signal_handler)

async def kalshi_ws_stream(market_tickers):
    global collector
    ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"

    # Generate timestamp & signature
    timestamp_ms = str(int(time.time() * 1000))
    msg_string = timestamp_ms + "GET" + "/trade-api/ws/v2"
    signature = sign_pss_text(private_key_obj, msg_string)

    # Build headers
    headers = {
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature
    }

    # Maintain separate last_seq for each channel
    last_seq = {
        "orderbook_delta": 0,
        "trade": 0
    }

    try:
        async with websockets.connect(ws_url, extra_headers=headers, ping_interval=10, ping_timeout=5) as ws:
            collector.logger.info("WEBSOCKET_CONNECTED | Successfully connected to Kalshi WebSocket")

            # Subscribe to orderbook_delta
            await ws.send(json.dumps({
                "id": 1, 
                "cmd": "subscribe", 
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": market_tickers
                }
            }))
            collector.logger.info("SUBSCRIPTION_SENT | Orderbook delta subscription sent")

            # Subscribe to trades
            await ws.send(json.dumps({
                "id": 2, 
                "cmd": "subscribe", 
                "params": {
                    "channels": ["trade"], 
                    "market_tickers": market_tickers
                }
            }))
            collector.logger.info("SUBSCRIPTION_SENT | Trade subscription sent")

            async for message in ws:
                # Timestamp immediately upon receiving message
                receipt_timestamp_ms = time.time() * 1000
                
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    seq = data.get("seq")
                    msg = data.get("msg", {})

                    if msg_type == "subscribed":
                        collector.logger.info(f"SUBSCRIPTION_CONFIRMED | Channel: {msg['channel']} | SID: {msg['sid']}")
                        continue

                    # Determine channel by message type
                    if msg_type == "orderbook_snapshot" or msg_type == "orderbook_delta":
                        channel = "orderbook_delta"
                    elif msg_type == "trade":
                        channel = "trade"
                    else:
                        debug_print("Other message:", data)
                        continue

                    ticker = msg.get("market_ticker")
                    if not ticker:
                        continue

                    # Check sequence gaps per channel
                    if channel in last_seq:
                        prev_seq = last_seq[channel]
                        if prev_seq != 0 and seq != prev_seq + 1:
                            collector.logger.warning(f"SEQUENCE_GAP | Channel: {channel} | Got: {seq} | Expected: {prev_seq+1}")
                            raise Exception("Sequence gap")
                        last_seq[channel] = seq

                    # Process messages with receipt timestamp
                    if msg_type == "orderbook_snapshot":
                        await collector.update_orderbook_snapshot(ticker, msg, receipt_timestamp_ms)
                    elif msg_type == "orderbook_delta":
                        await collector.update_orderbook_delta(ticker, msg, receipt_timestamp_ms)
                    elif msg_type == "trade":
                        collector.process_trade(ticker, msg, receipt_timestamp_ms)
                        
                except json.JSONDecodeError as e:
                    collector.logger.error(f"JSON_DECODE_ERROR | Error: {str(e)} | Message: {message[:200]}")
                except Exception as e:
                    collector.logger.error(f"MESSAGE_PROCESSING_ERROR | Error: {str(e)} | Message type: {msg_type}")

    except Exception as e:
        collector.logger.error(f"WEBSOCKET_ERROR | Error: {str(e)}")
        raise

async def start_ws_client(market_tickers):
    """WebSocket client with automatic reconnection"""
    global collector
    reconnect_count = 0
    
    while not shutdown_event.is_set():
        try:
            await kalshi_ws_stream(market_tickers)
        except Exception as e:
            if shutdown_event.is_set():
                break
            reconnect_count += 1
            collector.logger.warning(f"WEBSOCKET_RECONNECT | Attempt: {reconnect_count} | Error: {str(e)}")
            await asyncio.sleep(3)

async def periodic_status_report():
    """Print data collection status every 5 minutes and log every minute"""
    global collector
    minute_counter = 0
    
    while not shutdown_event.is_set():
        await asyncio.sleep(60)  # Check every minute
        if collector is None:
            continue
            
        minute_counter += 1
        
        # Get current stats
        stats = collector.get_stats()
        
        # Log stats every minute
        collector.logger.info(f"STATUS_REPORT | {stats}")
        
        # Print summary every 5 minutes
        if minute_counter % 5 == 0:
            # Count markets with non-default top of book
            active_markets = 0
            for ticker in collector.tickers:
                tob = collector.last_top_of_book[ticker]
                if tob['bid'] != None or tob['ask'] != None:
                    if not (tob['bid'] == 0 and tob['ask'] == 100):
                        active_markets += 1
            
            print(f"\n📊 STATUS [{time.strftime('%H:%M:%S')}]")
            print(f"Markets: {len(collector.tickers)} total, {active_markets} active")
            print(f"Updates: {stats['total_orderbook_updates']} collected, {stats['updates_written']} written")
            print(f"Trades: {stats['total_trades']} collected, {stats['trades_written']} written")
            print(f"Pending: {stats['pending_orderbook']} orderbook, {stats['pending_trades']} trades\n")

async def start_data_collection(market_tickers):
    """Start data collection with monitoring"""
    global collector
    
    # Start all tasks concurrently
    await asyncio.gather(
        start_ws_client(market_tickers),
        periodic_status_report(),
        return_exceptions=True
    )

def main():
    """Main function with error recovery"""
    global collector
    restart_count = 0
    
    while True:
        try:
            restart_count += 1
            
            # Test authentication first
            if not test_authentication(demo=True):
                print("❌ Authentication failed. Please check your credentials.")
                return
                
            # Get current markets
            event = get_current_event()
            markets = get_markets_from_event(event)
            
            # Initialize data collector
            collector = KalshiDataCollector(markets, demo=False)
            
            if restart_count == 1:
                print("🚀 Starting Kalshi Data Collection")
                print(f"📊 Tracking {len(markets)} election markets")
                for market in markets:
                    print(f"  - {market}")
                print("💾 Parquet storage with top-of-book change detection")
                print("📝 Detailed logging: logs/kalshi_data_collector.log")
                print("Press Ctrl+C to stop\n")
            else:
                print(f"🔄 Restarting data collection (attempt #{restart_count})")
            
            collector.logger.info(f"MAIN_START | Restart count: {restart_count} | Markets: {len(markets)}")
            
            # Start data collection
            asyncio.run(start_data_collection(markets))
            
        except KeyboardInterrupt:
            if collector:
                collector.logger.info("KEYBOARD_INTERRUPT | Received interrupt signal")
            print("\n👋 Shutting down...")
            break
            
        except Exception as e:
            error_msg = f"MAIN_ERROR | Restart: {restart_count} | Error: {str(e)}"
            if collector:
                collector.logger.error(error_msg)
                collector.logger.error(f"TRACEBACK | {traceback.format_exc()}")
            else:
                print(f"❌ {error_msg}")
            
            # Flush any remaining data before restart
            if collector is not None:
                try:
                    collector.flush_remaining_batches()
                except Exception as flush_error:
                    if collector:
                        collector.logger.error(f"EMERGENCY_FLUSH_ERROR | Error: {str(flush_error)}")
            
            print(f"🔄 Restarting in 5 seconds... (restart #{restart_count})")
            time.sleep(5)
            
            # Reset collector for fresh start
            collector = None
            
    # Final cleanup
    cleanup_and_exit()

if __name__ == "__main__":
    main()