import asyncio
import websockets
import json
import time
import os
import sys
import threading
from datetime import datetime
import pytz
import pandas as pd
from collections import deque

class LiveOrderBookDisplay:
    """Handles live updating display in terminal"""
    
    def __init__(self):
        self.clear_screen()
        # Hide cursor for cleaner display
        print('\033[?25l', end='')
        
    def clear_screen(self):
        """Clear the terminal screen"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def move_cursor_home(self):
        """Move cursor to top-left corner"""
        print('\033[H', end='')
    
    def clear_line(self, line_num):
        """Clear a specific line"""
        print(f'\033[{line_num};1H\033[K', end='')
    
    def cleanup(self):
        """Restore cursor visibility on exit"""
        print('\033[?25h', end='')

class BinanceBTCPerpetualDataCollector:
    def __init__(self, symbol: str = "btcusdt", display_mode: str = "full"):
        self.symbol = symbol.lower()
        self.ws_url = "wss://fstream.binance.com/stream"
        self.display_mode = display_mode
        self.display = LiveOrderBookDisplay() if display_mode != "silent" else None
        
        # Data collection setup
        self.update_count = 0
        self.start_time = time.time()
        self.ws = None
        
        # Current orderbook state with timestamp
        self.current_orderbook = None
        self.orderbook_lock = asyncio.Lock()
        
        # Trade aggregation buffers (copied from new script)
        self.trade_buffer = []
        self.trade_buffer_lock = asyncio.Lock()
        self.last_trade_save_time = 0
        
        # Feature generation for L1, L5, L10, L20
        self.orderbook_levels = [1, 5, 10, 20]
        
        # Parquet batching
        self.orderbook_batch = []
        self.trade_batch = []
        self.orderbook_batch_lock = threading.Lock()
        self.trade_batch_lock = threading.Lock()
        self.orderbook_batch_size = 100
        self.trade_batch_size = 100
        
        # Ensure data directory exists
        os.makedirs('better_data', exist_ok=True)
        self.orderbook_parquet = 'better_data/btc_orderbook_features.parquet'
        self.trade_parquet = 'better_data/perp_trade_raw_data.parquet'
        
        # EST timezone
        self.est_tz = pytz.timezone('US/Eastern')
        
        # Recent trade tracking
        self.recent_trade = None
        self.last_large_trade = None
        self.large_trade_threshold = 50.0  # BTC
        
        # Restart logic
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5
        
        print(f"📊 BTC Perpetual Data Collector initialized")
        print(f"💾 Orderbook: {self.orderbook_parquet}")
        print(f"💰 Trade data: {self.trade_parquet}")
        print(f"📈 Tracking levels: {self.orderbook_levels}")
        print(f"🔄 Batch sizes: OB={self.orderbook_batch_size}, Trade={self.trade_batch_size}")
        
    def timestamp_to_est(self, timestamp_ms):
        """Convert timestamp to EST string"""
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
        est_time = dt.astimezone(self.est_tz)
        return est_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    
    def generate_orderbook_features(self, bids, asks, receipt_timestamp):
        """Generate comprehensive orderbook features for L1, L5, L10, L20"""
        features = {
            'timestamp_est': self.timestamp_to_est(receipt_timestamp),
            'timestamp_ms': int(receipt_timestamp),
        }
        
        # Generate features for each level
        for level in self.orderbook_levels:
            # Ensure we have enough levels
            max_level = min(level, len(bids), len(asks))
            
            # Bid side features
            bid_prices = [float(bids[i][0]) for i in range(max_level)]
            bid_quantities = [float(bids[i][1]) for i in range(max_level)]
            bid_cumulative_qty = sum(bid_quantities)
            bid_weighted_price = sum(p * q for p, q in zip(bid_prices, bid_quantities)) / bid_cumulative_qty if bid_cumulative_qty > 0 else 0
            
            # Ask side features
            ask_prices = [float(asks[i][0]) for i in range(max_level)]
            ask_quantities = [float(asks[i][1]) for i in range(max_level)]
            ask_cumulative_qty = sum(ask_quantities)
            ask_weighted_price = sum(p * q for p, q in zip(ask_prices, ask_quantities)) / ask_cumulative_qty if ask_cumulative_qty > 0 else 0
            
            # Store features with level prefix
            features.update({
                f'bid_L{level}_price': bid_prices[level-1],
                f'bid_L{level}_cumulative_qty': bid_cumulative_qty,
                f'bid_L{level}_weighted_price': bid_weighted_price,
                f'ask_L{level}_price': ask_prices[level-1],
                f'ask_L{level}_cumulative_qty': ask_cumulative_qty,
                f'ask_L{level}_weighted_price': ask_weighted_price,
            })
            
            # Calculate spreads
            if bid_prices and ask_prices:                
                features.update({
                    f'spread_L{level}': ask_prices[level-1]-bid_prices[level-1],
                })
        
        return features
    
    def write_orderbook_batch_to_parquet(self, batch_data):
        """Write orderbook feature batch to Parquet file"""
        if not batch_data:
            return
            
        df = pd.DataFrame(batch_data)
        
        # Convert timestamp columns
        df['timestamp_est'] = pd.to_datetime(df['timestamp_est'])
        df['timestamp_ms'] = df['timestamp_ms'].astype('int64')
        
        # Append to existing parquet file or create new one
        if os.path.exists(self.orderbook_parquet):
            existing_df = pd.read_parquet(self.orderbook_parquet)
            combined_df = pd.concat([existing_df, df], ignore_index=True)
            combined_df.to_parquet(self.orderbook_parquet, compression='snappy', index=False)
        else:
            df.to_parquet(self.orderbook_parquet, compression='snappy', index=False)
            
        if self.display_mode != "silent":
            print(f"💾 FEATURES BATCH: Wrote {len(batch_data)} records to Parquet")
        """Write orderbook feature batch to Parquet file"""
        if not batch_data:
            return
            
        df = pd.DataFrame(batch_data)
        
        # Convert timestamp columns
        df['timestamp_est'] = pd.to_datetime(df['timestamp_est'])
        df['timestamp_ms'] = df['timestamp_ms'].astype('int64')
        
        # Append to existing parquet file or create new one
        if os.path.exists(self.orderbook_parquet):
            existing_df = pd.read_parquet(self.orderbook_parquet)
            combined_df = pd.concat([existing_df, df], ignore_index=True)
            combined_df.to_parquet(self.orderbook_parquet, compression='snappy', index=False)
        else:
            df.to_parquet(self.orderbook_parquet, compression='snappy', index=False)
            
        if self.display_mode != "silent":
            print(f"💾 FEATURES BATCH: Wrote {len(batch_data)} records to Parquet")
    
    def add_orderbook_to_batch(self, features):
        """Add orderbook features to batch for Parquet writing"""
        with self.orderbook_batch_lock:
            self.orderbook_batch.append(features)
            
            # Write batch when it reaches batch size
            if len(self.orderbook_batch) >= self.orderbook_batch_size:
                batch_to_write = self.orderbook_batch.copy()
                self.orderbook_batch.clear()
                
                # Write in background thread to avoid blocking
                threading.Thread(
                    target=self.write_orderbook_batch_to_parquet,
                    args=(batch_to_write,),
                    daemon=True
                ).start()
        """Add orderbook features to batch for Parquet writing"""
        with self.orderbook_batch_lock:
            self.orderbook_batch.append(features)
            
            # Write batch when it reaches batch size
            if len(self.orderbook_batch) >= self.orderbook_batch_size:
                batch_to_write = self.orderbook_batch.copy()
                self.orderbook_batch.clear()
                
                # Write in background thread to avoid blocking
                threading.Thread(
                    target=self.write_orderbook_batch_to_parquet,
                    args=(batch_to_write,),
                    daemon=True
                ).start()
    
    async def connect_and_subscribe(self):
        """Connect to Binance Futures WebSocket and subscribe to depth20@100ms + aggTrade streams"""
        stream_url = f"{self.ws_url}?streams={self.symbol}@depth20@100ms/{self.symbol}@aggTrade"
        
        for attempt in range(self.max_reconnect_attempts):
            try:
                self.ws = await websockets.connect(stream_url)
                
                if self.display_mode != "silent":
                    await self.print_static_header()
                
                if self.display_mode != "silent":
                    print(f"✅ Connected (attempt {attempt + 1})")
                
                async for message in self.ws:
                    receipt_timestamp = time.time() * 1000
                    await self.handle_message(message, receipt_timestamp)
                    
            except websockets.exceptions.ConnectionClosed:
                if self.display and self.display_mode != "silent":
                    self.display.cleanup()
                print(f"🔌 WebSocket connection closed (attempt {attempt + 1})")
                
            except Exception as e:
                if self.display and self.display_mode != "silent":
                    self.display.cleanup()
                print(f"❌ Connection Error (attempt {attempt + 1}): {e}")
            
            if attempt < self.max_reconnect_attempts - 1:
                print(f"🔄 Reconnecting in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)
            else:
                print("❌ Max reconnection attempts reached")
                break
    
    async def print_static_header(self):
        """Print the static header information once"""
        if self.display_mode == "silent":
            return
        
        # Just print initial connection message
        print(f"✅ Connected to Binance Futures WebSocket")
        print(f"📊 Listening for {self.symbol.upper()} Perpetual Contract Order Book...")
        print(f"🔄 Stream: {self.symbol}@depth20@100ms (20 levels, 100ms updates)")
        print(f"💾 Collecting features: L1, L5, L10, L20")
        print("=" * 80)
    
    async def add_trade_to_buffer(self, data, receipt_timestamp):
        """Add trade to aggregation buffer with receipt timestamp"""
        trade_info = {
            'price': float(data['p']),
            'quantity': float(data['q']),
            'is_buyer_maker': data['m'],
            'trade_count': data['l'] - data['f'] + 1,
            'receipt_timestamp': receipt_timestamp
        }

        self.recent_trade = trade_info

        # Check for large trades
        if trade_info['quantity'] >= self.large_trade_threshold:
            self.last_large_trade = trade_info

        async with self.trade_buffer_lock:
            self.trade_buffer.append(trade_info)

    async def handle_message(self, message, receipt_timestamp):
        """Process incoming messages (both orderbook and trade data)"""
        try:
            data = json.loads(message)
            

            
            if 'stream' in data and 'data' in data:
                stream_name = data['stream']
                stream_data = data['data']
                
                if stream_name == f"btcusdt@depth20@100ms":
                    await self.process_orderbook_update(stream_data, receipt_timestamp)
                elif stream_name == f"btcusdt@aggTrade":
                    await self.add_trade_to_buffer(stream_data, receipt_timestamp)
            else:
                # Fallback for direct data
                if 'b' in data and 'a' in data:
                    await self.process_orderbook_update(data, receipt_timestamp)
                elif 'bids' in data and 'asks' in data:
                    await self.process_orderbook_update(data, receipt_timestamp)
                    
        except json.JSONDecodeError:
            pass  # Skip malformed messages
        except Exception as e:
            if self.display_mode != "silent":
                print(f"❌ Error handling message: {e}")
    
    async def process_orderbook_update(self, data, receipt_timestamp):
        """Process orderbook update and generate features"""
        bids = data.get('b', data.get('bids', []))
        asks = data.get('a', data.get('asks', []))
        
        if not bids or not asks:
            return
        
        self.update_count += 1
        
        # Generate features for all levels
        features = self.generate_orderbook_features(bids, asks, receipt_timestamp)
        
        # Add to batch for storage
        self.add_orderbook_to_batch(features)
        
        # Update display if enabled
        if self.display_mode == "full":
            await self.update_live_display(data, receipt_timestamp, features)
        elif self.display_mode == "compact":
            await self.update_compact_display(features)
    
    async def update_live_display(self, data, receipt_timestamp, features):
        """Update the live display with new order book data - clear screen method"""
        if self.display_mode != "full":
            return
            
        # Clear the entire screen
        os.system('cls' if os.name == 'nt' else 'clear')
        
        current_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        uptime = int(time.time() - self.start_time)
        
        bids = data.get('b', data.get('bids', []))
        asks = data.get('a', data.get('asks', []))
        
        # Get key metrics from features
        mid_price = (features['ask_L1_price'] + features['bid_L1_price']) / 2
        spread = features['spread_L1']
        
        # Print header with update info
        print(f"\n[{current_time}] 📊 {self.symbol.upper()} PERPETUAL ORDER BOOK & FEATURES")
        print(f"🔄 Updates: {self.update_count:,} | Uptime: {uptime}s | Event Time: {data.get('E', 'N/A')}")
        print(f"💰 Mid Price: ${mid_price:>10,.2f} | Spread: ${spread:>6.2f}")
        print(f"📊 Cumulative Bid Volumes - L1: {features['bid_L1_cumulative_qty']:.3f} | L5: {features['bid_L5_cumulative_qty']:.3f} | L10: {features['bid_L10_cumulative_qty']:.3f} | L20: {features['bid_L20_cumulative_qty']:.3f} BTC")
        print("-" * 80)
        
        # Display order book in a formatted table
        print(f"{'BIDS':<40} | {'ASKS':<40}")
        print(f"{'Price':<12} {'Quantity':<12} {'Total':<12} | {'Price':<12} {'Quantity':<12} {'Total':<12}")
        print("-" * 80)
        
        # Calculate cumulative quantities for depth visualization
        bid_total = 0
        ask_total = 0
        max_levels = min(20, len(bids), len(asks))
        
        for i in range(max_levels):
            # Bid data
            bid_price = float(bids[i][0])
            bid_qty = float(bids[i][1])
            bid_total += bid_qty
            
            # Ask data  
            ask_price = float(asks[i][0])
            ask_qty = float(asks[i][1])
            ask_total += ask_qty
            
            # Format and display
            bid_str = f"${bid_price:>10,.2f} {bid_qty:>8.4f} {bid_total:>8.2f}"
            ask_str = f"${ask_price:>10,.2f} {ask_qty:>8.4f} {ask_total:>8.2f}"
            
            print(f"{bid_str:<40} | {ask_str:<40}")
        
        # Display summary statistics with features
        print("-" * 80)
        print(f"📊 SUMMARY:")
        print(f"   Best Bid: ${features['bid_L1_best_price']:>10,.2f} | Best Ask: ${features['ask_L1_best_price']:>10,.2f}")
        print(f"   Total Bid Volume: {bid_total:>8.2f} BTC | Total Ask Volume: {ask_total:>8.2f} BTC")
        print(f"   Bid-Ask Spread: ${spread_abs:.2f} ({spread_bps:.1f} bps)")
        print(f"   Levels Displayed: {max_levels}")
        
        # Feature summary
        print(f"💾 FEATURES:")
        print(f"   L1 VWAP: Bid ${features['bid_L1_weighted_price']:,.2f} | Ask ${features['ask_L1_weighted_price']:,.2f}")
        print(f"   L5 VWAP: Bid ${features['bid_L5_weighted_price']:,.2f} | Ask ${features['ask_L5_weighted_price']:,.2f}")
        print(f"   L10 VWAP: Bid ${features['bid_L10_weighted_price']:,.2f} | Ask ${features['ask_L10_weighted_price']:,.2f}")
        print(f"   L20 VWAP: Bid ${features['bid_L20_weighted_price']:,.2f} | Ask ${features['ask_L20_weighted_price']:,.2f}")
        print(f"   Batch Status: {len(self.orderbook_batch)}/{self.orderbook_batch_size} records")
        print(f"   Trade Batch: {len(self.trade_batch)}/{self.trade_batch_size} trades")
        print("=" * 80)
    

    async def update_compact_display(self, features):
        """Update compact display showing L1, L5, L10, L20 data for both bids and asks"""
        current_time = datetime.now().strftime("%H:%M:%S")
        uptime = int(time.time() - self.start_time)
        
        mid_price = (features['ask_L1_price'] + features['bid_L1_price']) / 2
        spread_abs = features['spread_L1']
        
        # Clear screen for compact mode too
        os.system('cls' if os.name == 'nt' else 'clear')
        
        print(f"\n🚀 BTC PERPETUAL - COMPACT LIVE VIEW WITH FEATURES")
        print("=" * 80)
        print(f"🕐 {current_time} | Updates: {self.update_count:,} | Uptime: {uptime}s")
        print(f"💰 Mid: ${mid_price:,.2f} | Spread: ${spread_abs:.2f}")
        print("=" * 80)
        
        # L1, L5, L10, L20 Data Table
        print(f"\n📊 ORDER BOOK LEVELS - CUMULATIVE QUANTITIES & VWAP")
        print("-" * 80)
        print(f"{'Level':<8} {'Bid Qty':<12} {'Bid VWAP':<12} {'Ask Qty':<12} {'Ask VWAP':<12} {'Spread':<10}")
        print("-" * 80)
        
        for level in [1, 5, 10, 20]:
            bid_qty = features[f'bid_L{level}_cumulative_qty']
            bid_vwap = features[f'bid_L{level}_weighted_price']
            ask_qty = features[f'ask_L{level}_cumulative_qty']
            ask_vwap = features[f'ask_L{level}_weighted_price']
            level_spread = features[f'spread_L{level}']
            
            print(f"L{level:<7} {bid_qty:<12.3f} ${bid_vwap:<11,.2f} {ask_qty:<12.3f} ${ask_vwap:<11,.2f} ${level_spread:<9.2f}")
        
        print("-" * 80)
        
        # Best prices for each level
        print(f"\n📈 BEST PRICES BY LEVEL")
        print("-" * 80)
        print(f"{'Level':<8} {'Best Bid':<12} {'Best Ask':<12} {'Mid Price':<12} {'Spread':<12}")
        print("-" * 80)
        
        for level in [1, 5, 10, 20]:
            best_bid = features[f'bid_L{level}_price']
            best_ask = features[f'ask_L{level}_price']
            spread = features[f'spread_L{level}']
            
            print(f"L{level:<7} ${best_bid:<11,.2f} ${best_ask:<11,.2f} ${(best_ask - best_bid):<11,.2f} {spread:.1f}")
        
        print("-" * 80)
        
        # Volume analysis
        print(f"\n📊 VOLUME ANALYSIS")
        print("-" * 40)
        total_bid_l1 = features['bid_L1_cumulative_qty']
        total_bid_l20 = features['bid_L20_cumulative_qty']
        total_ask_l1 = features['ask_L1_cumulative_qty']
        total_ask_l20 = features['ask_L20_cumulative_qty']
        
        bid_depth_ratio = (total_bid_l20 / total_bid_l1) if total_bid_l1 > 0 else 0
        ask_depth_ratio = (total_ask_l20 / total_ask_l1) if total_ask_l1 > 0 else 0
        
        print(f"Bid L1 vs L20: {total_bid_l1:.3f} → {total_bid_l20:.3f} BTC (ratio: {bid_depth_ratio:.1f}x)")
        print(f"Ask L1 vs L20: {total_ask_l1:.3f} → {total_ask_l20:.3f} BTC (ratio: {ask_depth_ratio:.1f}x)")
        
        # Order book imbalance
        l1_imbalance = total_bid_l1 - total_ask_l1
        l20_imbalance = total_bid_l20 - total_ask_l20
        
        l1_emoji = "🟢" if l1_imbalance > 0 else "🔴" if l1_imbalance < 0 else "⚪"
        l20_emoji = "🟢" if l20_imbalance > 0 else "🔴" if l20_imbalance < 0 else "⚪"
        
        print(f"L1 Imbalance: {l1_emoji} {l1_imbalance:+.3f} BTC")
        print(f"L20 Imbalance: {l20_emoji} {l20_imbalance:+.3f} BTC")
        
        # Recent trade info
        print(f"\n💰 RECENT TRADE")
        print("-" * 25)
        if self.recent_trade:
            trade_type = "SELL" if self.recent_trade['is_buyer_maker'] else "BUY"
            trade_emoji = "🔴" if self.recent_trade['is_buyer_maker'] else "🟢"
            print(f"{trade_emoji} {trade_type}: {self.recent_trade['quantity']:.3f} BTC @ ${self.recent_trade['price']:,.2f}")
            print(f"Time: {self.recent_trade['receipt_timestamp']}")
        else:
            print("No trades yet")
        
        # Last large trade info
        print(f"\n🚨 LAST LARGE TRADE (>{self.large_trade_threshold} BTC)")
        print("-" * 35)
        if self.last_large_trade:
            large_type = "SELL" if self.last_large_trade['is_buyer_maker'] else "BUY"
            large_emoji = "🔴" if self.last_large_trade['is_buyer_maker'] else "🟢"
            print(f"{large_emoji} {large_type}: {self.last_large_trade['quantity']:.3f} BTC @ ${self.last_large_trade['price']:,.2f}")
            print(f"Time: {self.last_large_trade['receipt_timestamp']}")
        else:
            print(f"No large trades (>{self.large_trade_threshold} BTC) yet")
        
        # Data collection status
        print(f"\n💾 DATA COLLECTION")
        print("-" * 30)
        print(f"Batch Status: {len(self.orderbook_batch)}/{self.orderbook_batch_size} records")
        print(f"Trade Buffer: {len(self.trade_batch)}/{self.trade_batch_size} trades")
        
        print("=" * 80)
        
        sys.stdout.flush()
    
    def flush_remaining_batches(self):
        """Flush any remaining data in batches before shutdown"""
        print("🔄 Flushing remaining batches...")
        
        with self.orderbook_batch_lock:
            if self.orderbook_batch:
                self.write_orderbook_batch_to_parquet(self.orderbook_batch)
                self.orderbook_batch.clear()
                
        with self.trade_batch_lock:
            if self.trade_batch:
                self.write_trade_batch_to_parquet(self.trade_batch)
                self.trade_batch.clear()
                
        print("✅ All batches flushed")
        
    def aggregate_and_add_to_batch(self):
        """Aggregate trades and add to batch for Parquet writing"""
        if not self.trade_buffer:
            return
            
        sell_volume = 0
        buy_volume = 0
        sell_value = 0
        buy_value = 0
        total_trade_count = 0
        earliest_timestamp = min(trade['receipt_timestamp'] for trade in self.trade_buffer)
        
        for trade in self.trade_buffer:
            volume = trade['quantity']
            price = trade['price']
            value = volume * price
            
            total_trade_count += trade['trade_count']
            
            if trade['is_buyer_maker']:
                sell_volume += volume
                sell_value += value
            else:
                buy_volume += volume
                buy_value += value
        
        vwap_sell_price = sell_value / sell_volume if sell_volume > 0 else 0
        vwap_buy_price = buy_value / buy_volume if buy_volume > 0 else 0
        total_volume = sell_volume + buy_volume
        
        timestamp_est = self.timestamp_to_est(earliest_timestamp)
        
        row = [
            timestamp_est,
            int(earliest_timestamp),
            sell_volume,
            buy_volume,
            vwap_sell_price,
            vwap_buy_price,
            total_volume,
            total_trade_count
        ]
        
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
        
        imbalance = buy_volume - sell_volume
        imbalance_emoji = "🟢" if imbalance > 0 else "🔴" if imbalance < 0 else "⚪"
        
        # print(f"💰 TRADE QUEUED [{timestamp_est}] {imbalance_emoji} | "
        #       f"Buy: {buy_volume:.3f} BTC @ ${vwap_buy_price:.2f} | "
        #       f"Sell: {sell_volume:.3f} BTC @ ${vwap_sell_price:.2f} | "
        #       f"Total: {total_trade_count} trades")
              
        if total_volume > 50:
            pass
            # print(f"🚨 LARGE VOLUME PERIOD: {total_volume:.3f} BTC total {timestamp_est}")
         

    async def trade_aggregator_task(self):
        """Background task to aggregate and save trade data every 25ms"""
        while True:
            try:
                current_time = time.time() * 1000
                
                if current_time - self.last_trade_save_time >= 100:
                    async with self.trade_buffer_lock:
                        if self.trade_buffer:
                            self.aggregate_and_add_to_batch()
                            self.trade_buffer.clear()
                            
                    self.last_trade_save_time = current_time
                
                await asyncio.sleep(0.005) # Sleep for 5ms to avoid busy waiting
                
            except Exception as e:
                print(f"❌ Error in trade aggregator: {e}")
                await asyncio.sleep(0.500)
     
    async def run_with_restart(self):
        """Main run loop with automatic restart logic and background tasks"""
        while True:
            try:
                # Start background trade aggregation task
                trade_task = asyncio.create_task(self.trade_aggregator_task())
                
                await self.connect_and_subscribe()
            except KeyboardInterrupt:
                print("\n👋 Shutting down...")
                self.flush_remaining_batches()
                if self.display:
                    self.display.cleanup()
                break
            except Exception as e:
                print(f"❌ Unexpected error: {e}")
                print(f"🔄 Restarting in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)

async def main():
    """Main function with display options"""
    print("🚀 Binance BTC Perpetual Live Order Book & Data Collector")
    print("=" * 60)
    print()
    
    choice = "2"
    
    mode_map = {
        "1": "full",
        "2": "compact", 
        "3": "silent"
    }
    
    display_mode = mode_map.get(choice, "full")
    
    print(f"🔄 Starting {display_mode} mode...")
    await asyncio.sleep(1)
    
    collector = BinanceBTCPerpetualDataCollector("btcusdt", display_mode)
    await collector.run_with_restart()

if __name__ == "__main__":
    asyncio.run(main())