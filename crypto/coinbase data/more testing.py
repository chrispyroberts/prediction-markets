import asyncio
import websockets
import json
import time
import requests
from typing import Dict, Any, List
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
import pytz

# Import the OrderBook class from testing_utils
from testing_utils import OrderBook

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TradeAggregator:
    """Aggregates trade data since last print"""
    
    def __init__(self):
        # Simple aggregation since last print
        self.trades_since_print = []
        self.buy_volume = 0.0
        self.sell_volume = 0.0
        self.buy_value = 0.0
        self.sell_value = 0.0
        self.buy_count = 0
        self.sell_count = 0
        self.total_trades = 0
        
    def add_trade(self, price: float, size: float, side: str, timestamp: str):
        """Add a trade to the aggregator"""
        try:
            value = price * size
            
            # Add to trades list
            self.trades_since_print.append({
                'price': price,
                'size': size,
                'side': side.upper(),
                'value': value,
                'timestamp': timestamp
            })
            
            # Update aggregated totals
            if side.upper() == 'BUY':
                self.buy_volume += size
                self.buy_value += value
                self.buy_count += 1
            else:  # SELL
                self.sell_volume += size
                self.sell_value += value
                self.sell_count += 1
            
            self.total_trades += 1
            
        except Exception as e:
            logger.error(f"Error adding trade to aggregator: {e}")
    
    def get_summary_and_reset(self) -> Dict:
        """Get current trade summary and reset all data"""
        if self.total_trades == 0:
            return None
        
        summary = {
            'total_trades': self.total_trades,
            'buy_volume': self.buy_volume,
            'sell_volume': self.sell_volume,
            'buy_value': self.buy_value,
            'sell_value': self.sell_value,
            'buy_count': self.buy_count,
            'sell_count': self.sell_count,
            'total_volume': self.buy_volume + self.sell_volume,
            'net_volume': self.buy_volume - self.sell_volume,
            'buy_ratio': self.buy_volume / (self.buy_volume + self.sell_volume) if (self.buy_volume + self.sell_volume) > 0 else 0
        }
        
        # Reset all data
        self.trades_since_print = []
        self.buy_volume = 0.0
        self.sell_volume = 0.0
        self.buy_value = 0.0
        self.sell_value = 0.0
        self.buy_count = 0
        self.sell_count = 0
        self.total_trades = 0
        
        return summary

class CoinbaseAdvancedWebSocket:
    def __init__(self, product_id: str = "BTC-INTX-PERP"):
        """
        Coinbase Advanced Trade WebSocket client with OrderBook tracking
        
        Args:
            product_id: Product to track (default: BTC-INTX-PERP)
        """
        self.ws_url = "wss://advanced-trade-ws.coinbase.com"
        self.websocket = None
        self.is_connected = False
        self.product_id = product_id
        
        # Initialize OrderBook tracker
        self.orderbook = OrderBook(product_id)
        
        # Initialize Trade Aggregator
        self.trade_aggregator = TradeAggregator()
        
        # Statistics
        self.message_count = 0
        self.last_print = 0
        self.print_interval = 0.9  # Print spread every 0.9 seconds
        self.last_loop_time = time.time()  # Track loop timing
        
    async def connect(self):
        """Connect to Coinbase Advanced Trade WebSocket"""
        try:
            logger.info(f"Connecting to {self.ws_url}")
            self.websocket = await websockets.connect(self.ws_url)
            self.is_connected = True
            logger.info("✅ WebSocket connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            raise
    
    async def subscribe_to_market_data(self):
        """
        Subscribe to L2 order book and market trades for the configured product
        """
        if not self.is_connected:
            await self.connect()
        
        # Subscribe to both level2 and market_trades
        channels = ["level2", "market_trades"]
        
        for channel in channels:
            subscribe_msg = {
                "type": "subscribe",
                "product_ids": [self.product_id],
                "channel": channel
            }
            
            print(f"🔄 Subscribing to {channel} for {self.product_id}")
            
            try:
                await self.websocket.send(json.dumps(subscribe_msg))
                await asyncio.sleep(0.5)  # Small delay between subscriptions
                
            except Exception as e:
                print(f"❌ {channel} subscription failed: {e}")
        
        print(f"✅ Subscribed to channels")
        return True
        
    async def listen_for_messages(self):
        """Listen for market data messages and update orderbook - QUIET MODE"""
        if not self.is_connected:
            logger.error("Not connected to WebSocket")
            return
        
        print(f"🔇 QUIET MODE: Tracking {self.product_id} order book with trade aggregation...")
        print("   Showing: initialization, spread + trade summary (every 1s), and errors")
        
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    self.message_count += 1
                    self._handle_message(data)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"JSON parse error: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection closed")
            self.is_connected = False
        except Exception as e:
            logger.error(f"Listen error: {e}")
    
    def _handle_message(self, data: Dict[str, Any]):
        """Handle messages - MINIMAL OUTPUT"""
        channel = data.get("channel", "unknown")
        
        # Handle L2 data regardless of channel name
        if channel in ["level2", "l2_data"]:
            self._handle_l2_update(data)
        elif channel == "market_trades":
            self._handle_trade_update(data)
        elif channel == "ticker":
            pass  # Silent
        elif data.get("type") == "subscriptions":
            self._handle_subscription_confirmation(data)
        elif channel == "subscriptions":
            self._handle_subscription_confirmation(data)
    
    def _handle_subscription_confirmation(self, data: Dict[str, Any]):
        """Handle subscription confirmations - MINIMAL"""
        events = data.get("events", [])
        for event in events:
            subscriptions = event.get("subscriptions", {})
            for channel, products in subscriptions.items():
                print(f"✅ {channel}: {products}")
    
    def _handle_l2_update(self, data: Dict[str, Any]):
        """Handle L2 updates - WITH TRADE SUMMARY"""
        events = data.get("events", [])
        
        for event in events:
            event_type = event.get("type", "unknown")
            
            if event_type == "snapshot":
                success = self.orderbook.process_snapshot(data)
                if success:
                    spread_info = self.orderbook.get_spread_info()
                    print(f"📸 Order book initialized - Spread: ${spread_info['spread']:.2f}")
                
            elif event_type == "update":
                success = self.orderbook.process_update(data)
                if success:
                    current_time = time.time()
                    if current_time - self.last_print >= self.print_interval:
                        # Calculate loop time since last print
                        loop_time = current_time - self.last_loop_time
                        self._print_orderbook_with_trades(loop_time)
                        self.last_print = current_time
                        self.last_loop_time = current_time

    def _handle_trade_update(self, data: Dict[str, Any]):
        """Handle market trade updates and add to aggregator"""
        events = data.get("events", [])
        
        for event in events:
            trades = event.get("trades", [])
            
            for trade in trades:
                trade_id = trade.get("trade_id", "")
                price = float(trade.get("price", 0))
                size = float(trade.get("size", 0))
                side = trade.get("side", "unknown")
                timestamp = trade.get("time", "")
                
                # Add trade to aggregator
                self.trade_aggregator.add_trade(price, size, side, timestamp)
                
                # Optional: Still show individual large trades
                value = price * size
                if value > 1000000:  # Only show trades > $1M
                    spread_info = self.orderbook.get_spread_info()
                    if spread_info and spread_info['mid_price']:
                        deviation = ((price - spread_info['mid_price']) / spread_info['mid_price']) * 100
                        deviation_str = f" ({deviation:+.3f}% from mid)"
                    else:
                        deviation_str = ""
                    
                    side_emoji = "🔴" if side == "SELL" else "🟢"
                    print(f"{side_emoji} HUGE TRADE: {size:.4f} BTC @ ${price:,.2f}{deviation_str} | ${value:,.0f}")

    def _print_orderbook_with_trades(self, loop_time: float):
        """Print orderbook summary with trade aggregation data and collect raw data"""
        if not self.orderbook.is_initialized:
            print("❌ Order book not initialized yet")
            return
        
        # Get current EST time
        est = pytz.timezone('US/Eastern')
        current_time_est = datetime.now(est)
        timestamp_str = current_time_est.strftime('%Y-%m-%d %H:%M:%S EST')
        
        # Print timestamp
        print(f"🕐 {timestamp_str}")
        
        # Print orderbook
        self.orderbook.print_top_orderbook()
        
        # **COLLECT RAW DATA BEFORE RESETTING TRADE AGGREGATOR**
        raw_data = self.get_raw_data_payload()
        
        # Print trade summary - show zeros if no trades
        if raw_data and raw_data['total_volume_btc'] > 0:
            net_vol = raw_data['net_volume_btc']
            total_vol = raw_data['total_volume_btc']
            
            # Get detailed trade info for display (need to access aggregator before it was reset)
            # Since we already reset in get_raw_data_payload, we'll reconstruct for display
            buy_volume = (total_vol + net_vol) / 2
            sell_volume = (total_vol - net_vol) / 2
            
            net_direction = "🟢" if net_vol > 0 else "🔴" if net_vol < 0 else "⚪"
            
            print(f"📊 Trades Since Last Print: "
                f"Vol: {total_vol:.4f} BTC | "
                f"Net: {net_direction}{net_vol:+.4f} BTC | "
                f"Buy: {buy_volume:.4f} BTC | "
                f"Sell: {sell_volume:.4f} BTC")
        else:
            print("📊 Trades Since Last Print: "
                f"Vol: 0.0000 BTC | "
                f"Net: ⚪+0.0000 BTC | "
                f"Buy: 0.0000 BTC | "
                f"Sell: 0.0000 BTC")
        
        # Print loop timing
        print(f"⏱️  Loop Time: {loop_time:.3f}s")
        
        # **STORE/PROCESS RAW DATA HERE**
        if raw_data:
            print(f"💾 Raw Data Collected: {len(raw_data)-1} features") # -1 for timestamp
            # TODO: Add your database storage logic here
            # Example: database.store_raw_data(raw_data)
            
            # For debugging, print key features including liquidity depths
            print(f"   Spread: ${raw_data['ask_l1_price'] - raw_data['bid_l1_price']:.2f}")
            print(f"   L5 Imbalance: {(raw_data['ask_l5_vol'] - raw_data['bid_l5_vol']) / (raw_data['ask_l5_vol'] + raw_data['bid_l5_vol'] + 1e-8):.3f}")
            
            # Print liquidity at different depths
            l20_liquidity = raw_data['bid_l20_vol'] + raw_data['ask_l20_vol']
            l30_liquidity = raw_data['bid_l30_vol'] + raw_data['ask_l30_vol']
            l40_liquidity = raw_data['bid_l40_vol'] + raw_data['ask_l40_vol']
            l50_liquidity = raw_data['bid_l50_vol'] + raw_data['ask_l50_vol']
            
            print(f"   📊 Liquidity Depths:")
            print(f"      L20: {l20_liquidity:.2f} BTC")
            print(f"      L30: {l30_liquidity:.2f} BTC")
            print(f"      L40: {l40_liquidity:.2f} BTC")
            print(f"      L50: {l50_liquidity:.2f} BTC")

            # Print trade stats
            print(f"   Trade Data: Vol: {raw_data['total_volume_btc']:.4f}BTC  | Net {raw_data['net_volume_btc']:.4f}BTC")
        
        print("-" * 80)

    def _print_minimal_spread(self):
        """Print minimal spread info"""
        if not self.orderbook.is_initialized:
            return
            
        spread_info = self.orderbook.get_spread_info()
        print(f"💰 Spread: ${spread_info['spread']:.2f} ({spread_info['spread_percentage']:.3f}%) | Mid: ${spread_info['mid_price']:,.2f}")

    def _print_orderbook(self):
        """Print current order book snapshot - QUIET MODE"""
        if not self.orderbook.is_initialized:
            print("❌ Order book not initialized yet")
            return
        
        self.orderbook.print_order_book(levels=5)
       
    def get_current_orderbook_snapshot(self) -> Dict:
        """Get current order book state"""
        return self.orderbook.get_top_levels(levels=10)
    
    def get_spread_history(self) -> Dict:
        """Get current spread and statistics"""
        return {
            "spread_info": self.orderbook.get_spread_info(),
            "stats": self.orderbook.get_stats(),
            "message_count": self.message_count
        }

    def get_raw_data_payload(self) -> Dict:
        """
        Generate raw data payload containing 32 essential features for ML model training.
        This captures complete order book state and trade flows for volatility prediction.
        Extended to L50 depth for deeper liquidity analysis.
        
        Returns:
            Dict: Raw data payload with 32 features
        """
        if not self.orderbook.is_initialized:
            return None
        
        try:
            # Get order book data (top 50 levels each side)
            bids = list(self.orderbook.bids.items())[:50]  # (price, volume) tuples
            asks = list(self.orderbook.asks.items())[:50]
            
            # Pad with zeros if not enough levels
            while len(bids) < 50:
                bids.append((0.0, 0.0))
            while len(asks) < 50:
                asks.append((0.0, 0.0))
            
            # Get trade summary without resetting (we'll reset separately)
            trade_summary = self.trade_aggregator.get_summary_and_reset()
            
            # Calculate cumulative volumes and VWAPs for each level
            payload = {}
            
            # Order Book Volume Features (16 features) - Convert Decimal to float
            bid_volumes = [float(vol) for price, vol in bids]
            ask_volumes = [float(vol) for price, vol in asks]
            
            # Bid volumes
            payload['bid_l1_vol'] = bid_volumes[0]
            payload['bid_l5_vol'] = sum(bid_volumes[:5])
            payload['bid_l10_vol'] = sum(bid_volumes[:10])
            payload['bid_l15_vol'] = sum(bid_volumes[:15])
            payload['bid_l20_vol'] = sum(bid_volumes[:20])
            payload['bid_l30_vol'] = sum(bid_volumes[:30])
            payload['bid_l40_vol'] = sum(bid_volumes[:40])
            payload['bid_l50_vol'] = sum(bid_volumes[:50])
            
            # Ask volumes
            payload['ask_l1_vol'] = ask_volumes[0]
            payload['ask_l5_vol'] = sum(ask_volumes[:5])
            payload['ask_l10_vol'] = sum(ask_volumes[:10])
            payload['ask_l15_vol'] = sum(ask_volumes[:15])
            payload['ask_l20_vol'] = sum(ask_volumes[:20])
            payload['ask_l30_vol'] = sum(ask_volumes[:30])
            payload['ask_l40_vol'] = sum(ask_volumes[:40])
            payload['ask_l50_vol'] = sum(ask_volumes[:50])
            
            # Order Book Price Features (16 features) - Convert Decimal to float
            # Calculate volume-weighted average prices for each cumulative level
            
            # Bid side VWAPs
            payload['bid_l1_price'] = float(bids[0][0]) if bids[0][1] > 0 else 0.0
            
            # L5 VWAP
            l5_bid_value = sum(float(price) * float(vol) for price, vol in bids[:5])
            payload['bid_l5_vwap'] = l5_bid_value / payload['bid_l5_vol'] if payload['bid_l5_vol'] > 0 else 0.0
            
            # L10 VWAP
            l10_bid_value = sum(float(price) * float(vol) for price, vol in bids[:10])
            payload['bid_l10_vwap'] = l10_bid_value / payload['bid_l10_vol'] if payload['bid_l10_vol'] > 0 else 0.0
            
            # L15 VWAP
            l15_bid_value = sum(float(price) * float(vol) for price, vol in bids[:15])
            payload['bid_l15_vwap'] = l15_bid_value / payload['bid_l15_vol'] if payload['bid_l15_vol'] > 0 else 0.0
            
            # L20 VWAP
            l20_bid_value = sum(float(price) * float(vol) for price, vol in bids[:20])
            payload['bid_l20_vwap'] = l20_bid_value / payload['bid_l20_vol'] if payload['bid_l20_vol'] > 0 else 0.0
            
            # L30 VWAP
            l30_bid_value = sum(float(price) * float(vol) for price, vol in bids[:30])
            payload['bid_l30_vwap'] = l30_bid_value / payload['bid_l30_vol'] if payload['bid_l30_vol'] > 0 else 0.0
            
            # L40 VWAP
            l40_bid_value = sum(float(price) * float(vol) for price, vol in bids[:40])
            payload['bid_l40_vwap'] = l40_bid_value / payload['bid_l40_vol'] if payload['bid_l40_vol'] > 0 else 0.0
            
            # L50 VWAP
            l50_bid_value = sum(float(price) * float(vol) for price, vol in bids[:50])
            payload['bid_l50_vwap'] = l50_bid_value / payload['bid_l50_vol'] if payload['bid_l50_vol'] > 0 else 0.0
            
            # Ask side VWAPs
            payload['ask_l1_price'] = float(asks[0][0]) if asks[0][1] > 0 else 0.0
            
            # L5 VWAP
            l5_ask_value = sum(float(price) * float(vol) for price, vol in asks[:5])
            payload['ask_l5_vwap'] = l5_ask_value / payload['ask_l5_vol'] if payload['ask_l5_vol'] > 0 else 0.0
            
            # L10 VWAP
            l10_ask_value = sum(float(price) * float(vol) for price, vol in asks[:10])
            payload['ask_l10_vwap'] = l10_ask_value / payload['ask_l10_vol'] if payload['ask_l10_vol'] > 0 else 0.0
            
            # L15 VWAP
            l15_ask_value = sum(float(price) * float(vol) for price, vol in asks[:15])
            payload['ask_l15_vwap'] = l15_ask_value / payload['ask_l15_vol'] if payload['ask_l15_vol'] > 0 else 0.0
            
            # L20 VWAP
            l20_ask_value = sum(float(price) * float(vol) for price, vol in asks[:20])
            payload['ask_l20_vwap'] = l20_ask_value / payload['ask_l20_vol'] if payload['ask_l20_vol'] > 0 else 0.0
            
            # L30 VWAP
            l30_ask_value = sum(float(price) * float(vol) for price, vol in asks[:30])
            payload['ask_l30_vwap'] = l30_ask_value / payload['ask_l30_vol'] if payload['ask_l30_vol'] > 0 else 0.0
            
            # L40 VWAP
            l40_ask_value = sum(float(price) * float(vol) for price, vol in asks[:40])
            payload['ask_l40_vwap'] = l40_ask_value / payload['ask_l40_vol'] if payload['ask_l40_vol'] > 0 else 0.0
            
            # L50 VWAP
            l50_ask_value = sum(float(price) * float(vol) for price, vol in asks[:50])
            payload['ask_l50_vwap'] = l50_ask_value / payload['ask_l50_vol'] if payload['ask_l50_vol'] > 0 else 0.0
            
            # Trade Flow Features (2 features)
            if trade_summary:
                payload['net_volume_btc'] = trade_summary['net_volume']
                payload['total_volume_btc'] = trade_summary['total_volume']
            else:
                payload['net_volume_btc'] = 0.0
                payload['total_volume_btc'] = 0.0
            
            # Add timestamp as EST datetime object
            est = pytz.timezone('US/Eastern')
            payload['timestamp'] = datetime.now(est)
            
            return payload
            
        except Exception as e:
            logger.error(f"Error generating raw data payload: {e}")
            return None

    async def close(self):
        """Close WebSocket connection"""
        if self.websocket and self.is_connected:
            await self.websocket.close()
            self.is_connected = False
            logger.info("WebSocket connection closed")

def get_rest_api_data(product_id: str = "BTC-INTX-PERP"):
    """
    Get current market data using REST API - MINIMAL OUTPUT
    """
    base_url = "https://api.coinbase.com/api/v3/brokerage"
    
    # Just test if product exists
    try:
        product_url = f"{base_url}/market/products/{product_id}"
        response = requests.get(product_url, timeout=10)
        
        if response.status_code == 200:
            print(f"✅ Product {product_id} exists")
            return True
        else:
            print(f"❌ Product {product_id} not found: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ REST API error: {e}")
        return False

async def main():
    """Main function - MINIMAL OUTPUT"""
    product_variants = ["BTC-PERP-INTX", "BTC-INTX-PERP", "BTC-PERP"]
    
    print("🔇 QUIET MODE - Order Book + Trade Tracker")
    print("Finding product...")

    # Test which product ID works
    working_product_id = None
    
    for product_id in product_variants:
        if get_rest_api_data(product_id):
            working_product_id = product_id
            break
    
    if not working_product_id:
        working_product_id = "BTC-PERP-INTX"
        print(f"Using fallback: {working_product_id}")
    
    client = CoinbaseAdvancedWebSocket(working_product_id)
    
    try:
        await client.connect()
        success = await client.subscribe_to_market_data()
        
        if success:
            await client.listen_for_messages()
        else:
            print("❌ No successful subscriptions")
        
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
        
        if client.orderbook.is_initialized:
            stats = client.get_spread_history()
            spread_info = stats['spread_info']
            
            print(f"Final: {stats['message_count']} msgs, {stats['stats']['update_count']} updates")
            print(f"Spread: ${spread_info['spread']:.2f} ({spread_info['spread_percentage']:.3f}%)")
            
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        await client.close()

if __name__ == "__main__":
    print("🔇 QUIET MODE - Order book + Trade aggregation")
    
    try:
        from testing_utils import OrderBook
    except ImportError:
        print("❌ Missing testing_utils.py")
        exit(1)
    
    asyncio.run(main())