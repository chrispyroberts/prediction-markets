import asyncio
import websockets
import json
import time
import os
from datetime import datetime
import pytz
import pandas as pd
import threading
from collections import deque

class BinanceFuturesStreamer:
    def __init__(self):
        self.ws_url = "wss://fstream.binance.com/stream"
        self.ws = None
        
        # Track last book state to detect changes
        self.last_bid_price = None
        self.last_ask_price = None
        self.last_book_save_time = 0
        self.last_orderbook_save_timestamp = None
        
        # Current orderbook state with timestamp
        self.current_orderbook = None
        self.orderbook_lock = asyncio.Lock()
        
        # Trade aggregation buffers
        self.trade_buffer = []
        self.trade_buffer_lock = asyncio.Lock()
        self.last_trade_save_time = 0
        
        # Parquet buffers and batch sizes
        self.orderbook_batch = []
        self.trade_batch = []
        self.orderbook_batch_lock = threading.Lock()
        self.trade_batch_lock = threading.Lock()
        
        # Batch sizes for efficient writing
        self.orderbook_batch_size = 100  # Write every 500 orderbook updates
        self.trade_batch_size = 100      # Write every 100 trade aggregations
        
        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)
        
        # Parquet file paths
        self.orderbook_parquet = 'data/hft_perp_orderbook_data.parquet'
        self.trade_parquet = 'data/hft_perp_trade_data.parquet'
        
        # EST timezone
        self.est_tz = pytz.timezone('US/Eastern')
        
        print(f"📝 Parquet files configured:")
        print(f"   - {self.orderbook_parquet}")
        print(f"   - {self.trade_parquet}")
        print(f"   - Orderbook batch size: {self.orderbook_batch_size}")
        print(f"   - Trade batch size: {self.trade_batch_size}")
        
    def timestamp_to_est(self, timestamp_ms):
        """Convert timestamp to EST string"""
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
        est_time = dt.astimezone(self.est_tz)
        return est_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
    def write_orderbook_batch_to_parquet(self, batch_data):
        """Write orderbook batch to Parquet file"""
        if not batch_data:
            return
            
        df = pd.DataFrame(batch_data, columns=[
            'timestamp_est', 'timestamp_ms', 'bid_price', 'bid_qty', 
            'ask_price', 'ask_qty', 'spread', 'mid_price'
        ])
        
        # Convert timestamp columns to appropriate types
        df['timestamp_est'] = pd.to_datetime(df['timestamp_est'])
        df['timestamp_ms'] = df['timestamp_ms'].astype('int64')
        
        # Append to existing parquet file or create new one
        if os.path.exists(self.orderbook_parquet):
            # Read existing data and append
            existing_df = pd.read_parquet(self.orderbook_parquet)
            combined_df = pd.concat([existing_df, df], ignore_index=True)
            combined_df.to_parquet(self.orderbook_parquet, compression='snappy', index=False)
        else:
            # Create new file
            df.to_parquet(self.orderbook_parquet, compression='snappy', index=False)
            
        print(f"💾 ORDERBOOK BATCH: Wrote {len(batch_data)} records to Parquet")
        
    def write_trade_batch_to_parquet(self, batch_data):
        """Write trade batch to Parquet file"""
        if not batch_data:
            return
            
        df = pd.DataFrame(batch_data, columns=[
            'timestamp_est', 'timestamp_ms', 'sell_volume', 'buy_volume',
            'vwap_sell_price', 'vwap_buy_price', 'total_volume', 'trade_count'
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
            
        print(f"💰 TRADE BATCH: Wrote {len(batch_data)} records to Parquet")
        
    async def update_orderbook_state(self, data, receipt_timestamp):
        """Update current orderbook state with receipt timestamp"""


        print(list(data.keys()))
        print(data)

        async with self.orderbook_lock:
            self.current_orderbook = {
                'bid_price': float(data['b']),
                'ask_price': float(data['a']),
                'bid_qty': float(data['B']),
                'ask_qty': float(data['A']),
                'receipt_timestamp': receipt_timestamp
            }
        
        # Quick print without blocking
        bid_price = float(data['b'])
        ask_price = float(data['a'])
        mid_price = (bid_price + ask_price) / 2
        print(f"📊 BOOK UPDATE: Mid ${mid_price:,.2f}")
        
    async def add_trade_to_buffer(self, data, receipt_timestamp):
        """Add trade to aggregation buffer with receipt timestamp"""
        trade_info = {
            'price': float(data['p']),
            'quantity': float(data['q']),
            'is_buyer_maker': data['m'],
            'trade_count': data['l'] - data['f'] + 1,
            'receipt_timestamp': receipt_timestamp
        }
        
        async with self.trade_buffer_lock:
            self.trade_buffer.append(trade_info)
            
    async def orderbook_saver_task(self):
        """Background task to save orderbook data every 10ms"""
        while True:
            try:
                current_time = time.time() * 1000
                
                if current_time - self.last_book_save_time >= 10:
                    async with self.orderbook_lock:
                        if self.current_orderbook is not None:
                            bid_price = self.current_orderbook['bid_price']
                            ask_price = self.current_orderbook['ask_price']
                            
                            if (self.last_bid_price != bid_price or self.last_ask_price != ask_price):
                                time_since_last_save = None
                                if self.last_orderbook_save_timestamp is not None:
                                    time_since_last_save = self.current_orderbook['receipt_timestamp'] - self.last_orderbook_save_timestamp
                                
                                self.add_orderbook_to_batch(self.current_orderbook, time_since_last_save)
                                self.last_bid_price = bid_price
                                self.last_ask_price = ask_price
                                self.last_orderbook_save_timestamp = self.current_orderbook['receipt_timestamp']
                                
                    self.last_book_save_time = current_time
                
                await asyncio.sleep(0.001)
                
            except Exception as e:
                print(f"❌ Error in orderbook saver: {e}")
                await asyncio.sleep(0.01)
                
    def add_orderbook_to_batch(self, orderbook_data, time_since_last_save):
        """Add orderbook data to batch for Parquet writing"""
        spread = orderbook_data['ask_price'] - orderbook_data['bid_price']
        mid_price = (orderbook_data['bid_price'] + orderbook_data['ask_price']) / 2
        timestamp_est = self.timestamp_to_est(orderbook_data['receipt_timestamp'])
        
        row = [
            timestamp_est,
            int(orderbook_data['receipt_timestamp']),  # Keep original timestamp as int
            orderbook_data['bid_price'],
            orderbook_data['bid_qty'],
            orderbook_data['ask_price'], 
            orderbook_data['ask_qty'],
            spread,
            mid_price
        ]
        
        with self.orderbook_batch_lock:
            self.orderbook_batch.append(row)
            
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
        
        timing_info = ""
        if time_since_last_save is not None:
            timing_info = f" | ⏱️  {time_since_last_save:.1f}ms since last"
            
        # print(f"💾 BOOK QUEUED [{timestamp_est}] Mid: ${mid_price:,.2f} | Spread: ${spread:.2f}{timing_info}")
        
    async def trade_aggregator_task(self):
        """Background task to aggregate and save trade data every 100ms"""
        while True:
            try:
                current_time = time.time() * 1000
                
                if current_time - self.last_trade_save_time >= 100:
                    async with self.trade_buffer_lock:
                        if self.trade_buffer:
                            self.aggregate_and_add_to_batch()
                            self.trade_buffer.clear()
                            
                    self.last_trade_save_time = current_time
                
                await asyncio.sleep(0.01)
                
            except Exception as e:
                print(f"❌ Error in trade aggregator: {e}")
                await asyncio.sleep(0.01)
                
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
            print(f"🚨 LARGE VOLUME PERIOD: {total_volume:.3f} BTC total {timestamp_est}")
            
    async def listen_for_messages(self):
        """Listen for incoming WebSocket messages and timestamp immediately"""
        try:
            async for message in self.ws:
                receipt_timestamp = time.time() * 1000
                data = json.loads(message)
                await self.process_message(data, receipt_timestamp)
                
        except websockets.exceptions.ConnectionClosed:
            print("🔌 WebSocket connection closed")
        except Exception as e:
            print(f"❌ Error listening for messages: {e}")
            
    async def process_message(self, data, receipt_timestamp):
        """Process incoming messages with receipt timestamp"""
        if 'stream' in data and 'data' in data:
            stream_name = data['stream']
            stream_data = data['data']
            
            if stream_name == 'btcusdt@bookTicker':
                await self.update_orderbook_state(stream_data, receipt_timestamp)
            elif stream_name == 'btcusdt@aggTrade':
                await self.add_trade_to_buffer(stream_data, receipt_timestamp)
                
    async def connect_and_subscribe(self):
        """Connect to Binance Futures WebSocket and subscribe to streams"""
        try:
            stream_url = f"{self.ws_url}?streams=btcusdt@bookTicker/btcusdt@aggTrade"
            self.ws = await websockets.connect(stream_url)
            print(f"✅ Connected to Binance Futures WebSocket at {datetime.now()}")
            
            await self.listen_for_messages()
            
        except Exception as e:
            print(f"❌ Connection error: {e}")
            
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
            
    async def run(self):
        """Main run loop with all background tasks"""
        while True:
            try:
                orderbook_task = asyncio.create_task(self.orderbook_saver_task())
                trade_task = asyncio.create_task(self.trade_aggregator_task())
                
                await self.connect_and_subscribe()
                
            except Exception as e:
                print(f"Connection failed: {e}")
                print("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

async def main():
    streamer = BinanceFuturesStreamer()
    try:
        await streamer.run()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        streamer.flush_remaining_batches()

if __name__ == "__main__":
    print("🚀 Starting High-Frequency Binance Futures Data Collector...")
    print("📊 BTCUSDT Perpetual Futures")
    print("💾 Storage: Parquet files with Snappy compression")
    print("⚡ Timestamps at WebSocket receipt")
    print("🔄 Batched writes for efficiency")
    print("📍 Timezone: EST")
    print("Press Ctrl+C to stop\n")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Final shutdown...")