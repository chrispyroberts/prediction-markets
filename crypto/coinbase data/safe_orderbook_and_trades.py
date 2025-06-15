import asyncio
import websockets
import json
import time
import requests
from typing import Dict, Any, List, Optional
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
import pytz
import signal
import sys
import traceback
from contextlib import asynccontextmanager
import os 

# Import the OrderBook class from testing_utils
try:
    from testing_utils import OrderBook
except ImportError:
    print("❌ CRITICAL: testing_utils.py not found. Exiting.")
    sys.exit(1)

async def bulletproof_runner():
    """Bulletproof runner that restarts no matter what"""
    restart_count = 0
    
    while True:
        restart_count += 1
        logger.info(f"Bulletproof restart #{restart_count}")  # FIXED: Removed emoji
        
        try:
            # Your existing main function
            await run_production_client()
            
            # If we get here, main function exited unexpectedly
            logger.warning("Main client function exited - this should not happen!")  # FIXED: Removed emoji
            
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt - stopping bulletproof runner")  # FIXED: Removed emoji
            break
            
        except SystemExit:
            logger.info("System exit called - stopping bulletproof runner")  # FIXED: Removed emoji
            break
            
        except Exception as e:
            logger.error(f"Bulletproof runner caught exception: {e}")  # FIXED: Removed emoji
            logger.debug(traceback.format_exc())
        
        # Always restart after a delay
        delay = min(60, restart_count * 5)
        logger.info(f"Bulletproof restart in {delay} seconds...")  # FIXED: Removed emoji
        await asyncio.sleep(delay)  # FIXED: Changed to async sleep

# Production logging setup
def setup_production_logging():
    """Set up production-grade logging with rotation and error handling"""
    import logging.handlers
    
    # Create logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # Prevent duplicate handlers
    if logger.handlers:
        logger.handlers.clear()
    
    # Console handler for immediate feedback
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler with rotation for persistence
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            'coinbase_websocket.log', 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.INFO)
        file_format = logging.Formatter('%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s')
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not set up file logging: {e}")
    
    return logger

logger = setup_production_logging()

class ProductionTradeAggregator:
    """Production-grade trade aggregator with error handling"""
    
    def __init__(self):
        self.reset_data()
        
    def reset_data(self):
        """Reset all aggregation data safely"""
        try:
            self.trades_since_print = []
            self.buy_volume = 0.0
            self.sell_volume = 0.0
            self.buy_value = 0.0
            self.sell_value = 0.0
            self.buy_count = 0
            self.sell_count = 0
            self.total_trades = 0
        except Exception as e:
            logger.error(f"Error resetting trade aggregator: {e}")
    
    def add_trade(self, price: float, size: float, side: str, timestamp: str) -> bool:
        """Add a trade to the aggregator with comprehensive error handling"""
        try:
            # Validate inputs
            if not isinstance(price, (int, float)) or price <= 0:
                logger.warning(f"Invalid price: {price}")
                return False
                
            if not isinstance(size, (int, float)) or size <= 0:
                logger.warning(f"Invalid size: {size}")
                return False
                
            if not isinstance(side, str) or side.upper() not in ['BUY', 'SELL']:
                logger.warning(f"Invalid side: {side}")
                return False
            
            # Calculate value safely
            value = float(price) * float(size)
            if value <= 0:
                logger.warning(f"Invalid trade value: {value}")
                return False
            
            # Add to trades list
            trade_data = {
                'price': float(price),
                'size': float(size),
                'side': side.upper(),
                'value': value,
                'timestamp': str(timestamp)
            }
            self.trades_since_print.append(trade_data)
            
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
            return True
            
        except Exception as e:
            logger.error(f"Error adding trade to aggregator: {e}")
            return False
    
    def get_summary_and_reset(self) -> Optional[Dict]:
        """Get current trade summary and reset all data safely"""
        try:
            if self.total_trades == 0:
                return None
            
            # Calculate ratios safely
            total_volume = self.buy_volume + self.sell_volume
            buy_ratio = 0.0
            if total_volume > 0:
                buy_ratio = self.buy_volume / total_volume
            
            summary = {
                'total_trades': self.total_trades,
                'buy_volume': self.buy_volume,
                'sell_volume': self.sell_volume,
                'buy_value': self.buy_value,
                'sell_value': self.sell_value,
                'buy_count': self.buy_count,
                'sell_count': self.sell_count,
                'total_volume': total_volume,
                'net_volume': self.buy_volume - self.sell_volume,
                'buy_ratio': buy_ratio
            }
            
            # Reset all data
            self.reset_data()
            return summary
            
        except Exception as e:
            logger.error(f"Error getting trade summary: {e}")
            self.reset_data()  # Reset anyway to prevent corruption
            return None

class ProductionCoinbaseWebSocket:
    """Production-ready Coinbase WebSocket client with full error handling"""
    
    def __init__(self, product_id: str = "BTC-INTX-PERP"):
        self.ws_url = "wss://advanced-trade-ws.coinbase.com"
        self.websocket = None
        self.is_connected = False
        self.product_id = product_id
        self.should_run = True  # Global shutdown flag
        
        # Connection management
        self.max_reconnect_attempts = 50  # Increased for production
        self.reconnect_delay = 5.0  # Start with 5 seconds
        self.max_reconnect_delay = 300.0  # Max 5 minutes
        self.connection_timeout = 30.0
        
        # Initialize components with error handling
        try:
            self.orderbook = OrderBook(product_id)
            self.trade_aggregator = ProductionTradeAggregator()
        except Exception as e:
            logger.critical(f"Failed to initialize components: {e}")
            raise
        
        # Statistics and timing
        self.message_count = 0
        self.error_count = 0
        self.last_print = 0
        self.print_interval = 0.9
        self.last_loop_time = time.time()
        self.last_successful_message = time.time()
        self.heartbeat_timeout = 60.0  # Consider connection dead after 60s silence
        
        # Setup signal handlers for graceful shutdown
        self.setup_signal_handlers()
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
            self.should_run = False
        
        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            # FIXED: Added SIGHUP ignore as per requirements
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
        except Exception as e:
            logger.warning(f"Could not setup signal handlers: {e}")
    
    async def connect_with_retry(self) -> bool:
        """Connect with exponential backoff retry logic"""
        attempt = 0
        delay = self.reconnect_delay
        
        while self.should_run and attempt < self.max_reconnect_attempts:
            try:
                attempt += 1
                logger.info(f"Connection attempt {attempt}/{self.max_reconnect_attempts} to {self.ws_url}")
                
                # Close existing connection if any
                if self.websocket:
                    try:
                        await self.websocket.close()
                    except:
                        pass
                    self.websocket = None
                    self.is_connected = False
                
                # Attempt connection with timeout
                self.websocket = await asyncio.wait_for(
                    websockets.connect(
                        self.ws_url,
                        ping_interval=20,  # Send ping every 20 seconds
                        ping_timeout=10,   # Wait 10 seconds for pong
                        close_timeout=10,  # Wait 10 seconds for close
                        max_size=2**20,    # 1MB max message size
                        compression=None   # Disable compression for reliability
                    ),
                    timeout=self.connection_timeout
                )
                
                self.is_connected = True
                self.last_successful_message = time.time()
                logger.info("WebSocket connected successfully")
                return True
                
            except asyncio.TimeoutError:
                logger.warning(f"Connection attempt {attempt} timed out after {self.connection_timeout}s")
            except Exception as e:
                logger.warning(f"Connection attempt {attempt} failed: {e}")
            
            if attempt < self.max_reconnect_attempts and self.should_run:
                logger.info(f"Retrying in {delay:.1f} seconds...")
                await asyncio.sleep(delay)
                # Exponential backoff with jitter
                delay = min(delay * 1.5 + (time.time() % 1), self.max_reconnect_delay)
        
        logger.error(f"Failed to connect after {self.max_reconnect_attempts} attempts")
        return False
    
    async def subscribe_to_market_data(self) -> bool:
        """Subscribe with comprehensive error handling"""
        if not self.is_connected:
            logger.error("Cannot subscribe: not connected")
            return False
        
        channels = ["level2", "market_trades"]
        successful_subscriptions = 0
        
        for channel in channels:
            try:
                subscribe_msg = {
                    "type": "subscribe",
                    "product_ids": [self.product_id],
                    "channel": channel
                }
                
                logger.info(f"Subscribing to {channel} for {self.product_id}")  # FIXED: Removed emoji
                
                # Send subscription with timeout
                await asyncio.wait_for(
                    self.websocket.send(json.dumps(subscribe_msg)),
                    timeout=10.0
                )
                
                # Wait for confirmation or timeout
                await asyncio.sleep(1.0)
                successful_subscriptions += 1
                
            except asyncio.TimeoutError:
                logger.error(f"Subscription to {channel} timed out")
            except Exception as e:
                logger.error(f"Failed to subscribe to {channel}: {e}")
        
        success = successful_subscriptions > 0
        if success:
            logger.info(f"Successfully subscribed to {successful_subscriptions}/{len(channels)} channels")
        else:
            logger.error("No successful subscriptions")
        
        return success
    
    async def listen_for_messages(self):
        """Main message listening loop with comprehensive error handling"""
        if not self.is_connected:
            logger.error("Cannot listen: not connected")
            return
        
        logger.info(f"PRODUCTION MODE: Tracking {self.product_id} order book with trade aggregation...")
        logger.info("   Robust error handling enabled. Will continue running indefinitely.")
        
        message_buffer = []
        last_heartbeat_check = time.time()
        
        try:
            while self.should_run and self.is_connected:
                try:
                    # Check for heartbeat timeout
                    current_time = time.time()
                    if current_time - self.last_successful_message > self.heartbeat_timeout:
                        logger.warning(f"No messages received for {self.heartbeat_timeout}s. Connection may be dead.")
                        break
                    
                    # Listen for message with timeout
                    try:
                        message = await asyncio.wait_for(
                            self.websocket.recv(),
                            timeout=5.0  # 5 second timeout for individual messages
                        )
                        
                        self.last_successful_message = current_time
                        
                        # Parse and handle message
                        try:
                            data = json.loads(message)
                            self.message_count += 1
                            self._handle_message_safe(data)
                            
                        except json.JSONDecodeError as e:
                            self.error_count += 1
                            logger.warning(f"JSON parse error (count: {self.error_count}): {e}")
                            if self.error_count > 100:  # Too many parse errors
                                logger.error("Too many JSON parse errors. Reconnecting...")
                                break
                        
                        except Exception as e:
                            self.error_count += 1
                            logger.error(f"Message handling error (count: {self.error_count}): {e}")
                            logger.debug(f"Problematic message: {message[:500]}...")
                            
                            if self.error_count > 50:  # Too many handling errors
                                logger.error("Too many message handling errors. Reconnecting...")
                                break
                    
                    except asyncio.TimeoutError:
                        # Timeout is normal, continue loop
                        continue
                        
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning(f"WebSocket connection closed: {e}")
                    break
                    
                except websockets.exceptions.ConnectionClosedError as e:
                    logger.warning(f"WebSocket connection closed with error: {e}")
                    break
                    
                except Exception as e:
                    logger.error(f"Unexpected error in message loop: {e}")
                    logger.debug(traceback.format_exc())
                    break
        
        finally:
            self.is_connected = False
            if self.websocket:
                try:
                    await self.websocket.close()
                except:
                    pass
                self.websocket = None
    
    def _handle_message_safe(self, data: Dict[str, Any]):
        """Handle messages with complete error isolation"""
        try:
            channel = data.get("channel", "unknown")
            
            # Handle different message types
            if channel in ["level2", "l2_data"]:
                self._handle_l2_update_safe(data)
            elif channel == "market_trades":
                self._handle_trade_update_safe(data)
            elif channel == "ticker":
                pass  # Silent
            elif data.get("type") == "subscriptions":
                self._handle_subscription_confirmation_safe(data)
            elif channel == "subscriptions":
                self._handle_subscription_confirmation_safe(data)
            
        except Exception as e:
            logger.error(f"Error in message handler: {e}")
            logger.debug(f"Problematic data: {str(data)[:200]}...")
    
    def _handle_subscription_confirmation_safe(self, data: Dict[str, Any]):
        """Handle subscription confirmations safely"""
        try:
            events = data.get("events", [])
            for event in events:
                subscriptions = event.get("subscriptions", {})
                for channel, products in subscriptions.items():
                    logger.info(f"Confirmed subscription - {channel}: {products}")  # FIXED: Removed emoji
        except Exception as e:
            logger.error(f"Error handling subscription confirmation: {e}")
    
    def _handle_l2_update_safe(self, data: Dict[str, Any]):
        """Handle L2 updates with complete error isolation"""
        try:
            events = data.get("events", [])
            
            for event in events:
                try:
                    event_type = event.get("type", "unknown")
                    
                    if event_type == "snapshot":
                        success = self.orderbook.process_snapshot(data)
                        if success:
                            try:
                                spread_info = self.orderbook.get_spread_info()
                                if spread_info:
                                    logger.info(f"Order book initialized - Spread: ${spread_info.get('spread', 0):.2f}")  # FIXED: Removed emoji
                            except:
                                logger.info("Order book initialized")  # FIXED: Removed emoji
                        
                    elif event_type == "update":
                        success = self.orderbook.process_update(data)
                        if success:
                            current_time = time.time()
                            if current_time - self.last_print >= self.print_interval:
                                loop_time = current_time - self.last_loop_time
                                self._print_orderbook_with_trades_safe(loop_time)
                                self.last_print = current_time
                                self.last_loop_time = current_time
                
                except Exception as e:
                    logger.error(f"Error processing L2 event: {e}")
                    continue  # Continue with next event
                    
        except Exception as e:
            logger.error(f"Error in L2 update handler: {e}")
    
    def _handle_trade_update_safe(self, data: Dict[str, Any]):
        """Handle trade updates with complete error isolation"""
        try:
            events = data.get("events", [])
            
            for event in events:
                try:
                    trades = event.get("trades", [])
                    
                    for trade in trades:
                        try:
                            # Extract trade data safely
                            price = float(trade.get("price", 0))
                            size = float(trade.get("size", 0))
                            side = str(trade.get("side", "unknown"))
                            timestamp = str(trade.get("time", ""))
                            
                            # Validate trade data
                            if price <= 0 or size <= 0:
                                continue
                            
                            # Add to aggregator
                            if not self.trade_aggregator.add_trade(price, size, side, timestamp):
                                logger.debug(f"Failed to add trade: {price}, {size}, {side}")
                                continue
                            
                            # Show large trades
                            value = price * size
                            if value > 1000000:  # Only show trades > $1M
                                try:
                                    spread_info = self.orderbook.get_spread_info()
                                    deviation_str = ""
                                    if spread_info and spread_info.get('mid_price'):
                                        deviation = ((price - spread_info['mid_price']) / spread_info['mid_price']) * 100
                                        deviation_str = f" ({deviation:+.3f}% from mid)"
                                    
                                    side_name = "SELL" if side == "SELL" else "BUY"  # FIXED: Removed emoji
                                    logger.info(f"{side_name} HUGE TRADE: {size:.4f} BTC @ ${price:,.2f}{deviation_str} | ${value:,.0f}")
                                except:
                                    logger.info(f"HUGE TRADE: {size:.4f} BTC @ ${price:,.2f} | ${value:,.0f}")
                        
                        except Exception as e:
                            logger.debug(f"Error processing individual trade: {e}")
                            continue
                
                except Exception as e:
                    logger.error(f"Error processing trade event: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error in trade update handler: {e}")
    
    def _print_orderbook_with_trades_safe(self, loop_time: float):
        """Print orderbook with comprehensive error handling"""
        try:
            if not self.orderbook.is_initialized:
                logger.debug("Order book not initialized yet")
                return
            
            # Get current EST time safely
            try:
                est = pytz.timezone('US/Eastern')
                current_time_est = datetime.now(est)
                timestamp_str = current_time_est.strftime('%Y-%m-%d %H:%M:%S EST')
                print(f"🕐 {timestamp_str}")
            except Exception as e:
                print(f"🕐 {datetime.now()}")
                logger.debug(f"Timezone error: {e}")
            
            # Print orderbook safely
            try:
                self.orderbook.print_top_orderbook()
            except Exception as e:
                logger.error(f"Error printing orderbook: {e}")
                print("📊 Order book display error")
            
            # Get raw data safely
            raw_data = None
            try:
                raw_data = self.get_raw_data_payload_safe()
            except Exception as e:
                logger.error(f"Error getting raw data: {e}")
            
            # Print trade summary safely
            try:
                if raw_data and raw_data.get('total_volume_btc', 0) > 0:
                    net_vol = raw_data.get('net_volume_btc', 0)
                    total_vol = raw_data.get('total_volume_btc', 0)
                    
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
            except Exception as e:
                logger.error(f"Error printing trade summary: {e}")
                print("📊 Trade summary display error")
            
            # Print timing safely
            try:
                print(f"⏱️  Loop Time: {loop_time:.3f}s")
            except:
                print("⏱️  Loop Time: N/A")
            
            # Process raw data safely
            if raw_data:
                try:
                    feature_count = len(raw_data) - 1  # -1 for timestamp
                    print(f"💾 Raw Data Collected: {feature_count} features")
                    
                    # Print key statistics safely
                    bid_l1 = raw_data.get('bid_l1_price', 0)
                    ask_l1 = raw_data.get('ask_l1_price', 0)
                    if bid_l1 > 0 and ask_l1 > 0:
                        spread = ask_l1 - bid_l1
                        print(f"   Spread: ${spread:.2f}")
                    
                    # Print imbalance safely
                    ask_l5_vol = raw_data.get('ask_l5_vol', 0)
                    bid_l5_vol = raw_data.get('bid_l5_vol', 0)
                    if ask_l5_vol > 0 or bid_l5_vol > 0:
                        imbalance = (ask_l5_vol - bid_l5_vol) / (ask_l5_vol + bid_l5_vol + 1e-8)
                        print(f"   L5 Imbalance: {imbalance:.3f}")
                    
                    # Print liquidity depths safely
                    liquidity_levels = [20, 30, 40, 50]
                    print(f"   📊 Liquidity Depths:")
                    
                    for level in liquidity_levels:
                        try:
                            bid_key = f'bid_l{level}_vol'
                            ask_key = f'ask_l{level}_vol'
                            bid_vol = raw_data.get(bid_key, 0)
                            ask_vol = raw_data.get(ask_key, 0)
                            total_liquidity = bid_vol + ask_vol
                            print(f"      L{level}: {total_liquidity:.2f} BTC")
                        except:
                            print(f"      L{level}: N/A")
                    
                    # Print trade stats safely
                    total_vol = raw_data.get('total_volume_btc', 0)
                    net_vol = raw_data.get('net_volume_btc', 0)
                    print(f"   Trade Data: Vol: {total_vol:.4f}BTC | Net {net_vol:.4f}BTC")
                    
                except Exception as e:
                    logger.error(f"Error processing raw data display: {e}")
                    print("   Raw data processing error")
            
            print("-" * 80)
            
        except Exception as e:
            logger.error(f"Critical error in print function: {e}")
            logger.debug(traceback.format_exc())
            print("❌ Display error - continuing...")
    
    def get_raw_data_payload_safe(self) -> Optional[Dict]:
        """Generate raw data payload with comprehensive error handling"""
        if not self.orderbook.is_initialized:
            return None
        
        try:
            # Get order book data safely
            bids = []
            asks = []
            
            try:
                bids = list(self.orderbook.bids.items())[:50]
                asks = list(self.orderbook.asks.items())[:50]
            except Exception as e:
                logger.error(f"Error getting orderbook data: {e}")
                return None
            
            # Pad with zeros if not enough levels
            while len(bids) < 50:
                bids.append((0.0, 0.0))
            while len(asks) < 50:
                asks.append((0.0, 0.0))
            
            # Get trade summary safely
            trade_summary = None
            try:
                trade_summary = self.trade_aggregator.get_summary_and_reset()
            except Exception as e:
                logger.error(f"Error getting trade summary: {e}")
            
            payload = {}
            
            # Calculate volumes safely
            try:
                bid_volumes = [float(vol) if vol else 0.0 for price, vol in bids]
                ask_volumes = [float(vol) if vol else 0.0 for price, vol in asks]
                
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
                payload.update({
                    'ask_l5_vol': sum(ask_volumes[:5]),
                    'ask_l10_vol': sum(ask_volumes[:10]),
                    'ask_l15_vol': sum(ask_volumes[:15]),
                    'ask_l20_vol': sum(ask_volumes[:20]),
                    'ask_l30_vol': sum(ask_volumes[:30]),
                    'ask_l40_vol': sum(ask_volumes[:40]),
                    'ask_l50_vol': sum(ask_volumes[:50])
                })
                
            except Exception as e:
                logger.error(f"Error calculating volumes: {e}")
                # Set default values
                for level in [1, 5, 10, 15, 20, 30, 40, 50]:
                    payload[f'bid_l{level}_vol'] = 0.0
                    payload[f'ask_l{level}_vol'] = 0.0
            
            # Calculate VWAPs safely
            try:
                # Bid side VWAPs
                payload['bid_l1_price'] = float(bids[0][0]) if bids[0][1] > 0 else 0.0
                
                # Calculate VWAPs for different levels
                for level in [5, 10, 15, 20, 30, 40, 50]:
                    try:
                        # Bid VWAP
                        bid_value = sum(float(price) * float(vol) for price, vol in bids[:level] if vol > 0)
                        bid_vol_key = f'bid_l{level}_vol'
                        if payload.get(bid_vol_key, 0) > 0:
                            payload[f'bid_l{level}_vwap'] = bid_value / payload[bid_vol_key]
                        else:
                            payload[f'bid_l{level}_vwap'] = 0.0
                    except:
                        payload[f'bid_l{level}_vwap'] = 0.0
                
                # Ask side VWAPs
                payload['ask_l1_price'] = float(asks[0][0]) if asks[0][1] > 0 else 0.0
                
                for level in [5, 10, 15, 20, 30, 40, 50]:
                    try:
                        # Ask VWAP
                        ask_value = sum(float(price) * float(vol) for price, vol in asks[:level] if vol > 0)
                        ask_vol_key = f'ask_l{level}_vol'
                        if payload.get(ask_vol_key, 0) > 0:
                            payload[f'ask_l{level}_vwap'] = ask_value / payload[ask_vol_key]
                        else:
                            payload[f'ask_l{level}_vwap'] = 0.0
                    except:
                        payload[f'ask_l{level}_vwap'] = 0.0
                
            except Exception as e:
                logger.error(f"Error calculating VWAPs: {e}")
                # Set default VWAP values
                payload['bid_l1_price'] = 0.0
                payload['ask_l1_price'] = 0.0
                for level in [5, 10, 15, 20, 30, 40, 50]:
                    payload[f'bid_l{level}_vwap'] = 0.0
                    payload[f'ask_l{level}_vwap'] = 0.0
            
            # Add trade data safely
            try:
                if trade_summary:
                    payload['net_volume_btc'] = trade_summary.get('net_volume', 0.0)
                    payload['total_volume_btc'] = trade_summary.get('total_volume', 0.0)
                else:
                    payload['net_volume_btc'] = 0.0
                    payload['total_volume_btc'] = 0.0
            except Exception as e:
                logger.error(f"Error adding trade data: {e}")
                payload['net_volume_btc'] = 0.0
                payload['total_volume_btc'] = 0.0
            
            # Add timestamp safely
            try:
                est = pytz.timezone('US/Eastern')
                payload['timestamp'] = datetime.now(est)
            except Exception as e:
                logger.error(f"Error adding timestamp: {e}")
                payload['timestamp'] = datetime.now()
            
            return payload
            
        except Exception as e:
            logger.error(f"Critical error generating raw data payload: {e}")
            logger.debug(traceback.format_exc())
            return None
    
    async def close_safe(self):
        """Safely close WebSocket connection"""
        try:
            self.should_run = False
            if self.websocket and self.is_connected:
                await asyncio.wait_for(self.websocket.close(), timeout=5.0)
                logger.info("WebSocket connection closed safely")
        except Exception as e:
            logger.warning(f"Error closing WebSocket: {e}")
        finally:
            self.is_connected = False
            self.websocket = None

def get_rest_api_data_safe(product_id: str = "BTC-INTX-PERP") -> bool:
    """Test REST API connectivity with robust error handling"""
    base_url = "https://api.coinbase.com/api/v3/brokerage"
    
    try:
        product_url = f"{base_url}/market/products/{product_id}"
        
        # Use session for connection pooling and retries
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=3)
        session.mount('https://', adapter)
        
        response = session.get(
            product_url, 
            timeout=(10, 30),  # (connect, read) timeouts
            headers={'User-Agent': 'ProductionWebSocketClient/1.0'}
        )
        
        if response.status_code == 200:
            logger.info(f"Product {product_id} exists and is accessible")  # FIXED: Removed emoji
            return True
        else:
            logger.warning(f"Product {product_id} returned status {response.status_code}")  # FIXED: Removed emoji
            return False
            
    except requests.exceptions.Timeout:
        logger.warning(f"REST API timeout for {product_id}")  # FIXED: Removed emoji
        return False
    except requests.exceptions.ConnectionError:
        logger.warning(f"REST API connection error for {product_id}")  # FIXED: Removed emoji
        return False
    except Exception as e:
        logger.warning(f"REST API error for {product_id}: {e}")  # FIXED: Removed emoji
        return False

async def run_production_client():
    """Main production client with infinite retry logic"""
    product_variants = ["BTC-PERP-INTX", "BTC-INTX-PERP", "BTC-PERP"]
    
    logger.info("PRODUCTION MODE - Order Book + Trade Tracker Starting...")  # FIXED: Removed emoji
    logger.info("   - Infinite retry logic enabled")
    logger.info("   - Comprehensive error handling active")
    logger.info("   - Graceful shutdown on SIGINT/SIGTERM")
    
    # Find working product ID
    working_product_id = None
    
    logger.info("Testing product connectivity...")  # FIXED: Removed emoji
    for product_id in product_variants:
        if get_rest_api_data_safe(product_id):
            working_product_id = product_id
            break
        await asyncio.sleep(1)  # Brief delay between tests
    
    if not working_product_id:
        working_product_id = "BTC-PERP-INTX"  # Fallback
        logger.warning(f"Using fallback product: {working_product_id}")  # FIXED: Removed emoji
    else:
        logger.info(f"Using confirmed product: {working_product_id}")  # FIXED: Removed emoji
    
    # Main infinite retry loop
    session_count = 0
    total_uptime = 0
    start_time = time.time()
    
    while True:  # Infinite retry loop
        session_count += 1
        session_start = time.time()
        
        logger.info(f"Starting session #{session_count}")  # FIXED: Removed emoji
        
        client = None
        try:
            client = ProductionCoinbaseWebSocket(working_product_id)
            
            # Connection phase with retry
            if not await client.connect_with_retry():
                logger.error("Failed to establish connection. Retrying in 30 seconds...")  # FIXED: Removed emoji
                await asyncio.sleep(30)
                continue
            
            # Subscription phase
            if not await client.subscribe_to_market_data():
                logger.error("Failed to subscribe to market data. Retrying in 15 seconds...")  # FIXED: Removed emoji
                await asyncio.sleep(15)
                continue
            
            logger.info("Session started successfully. Beginning data collection...")  # FIXED: Removed emoji
            
            # Data collection phase
            await client.listen_for_messages()
            
            # If we get here, connection was lost
            session_duration = time.time() - session_start
            total_uptime += session_duration
            
            logger.warning(f"Session #{session_count} ended after {session_duration:.1f}s")  # FIXED: Removed emoji
            logger.info(f"Total uptime: {total_uptime/3600:.1f} hours across {session_count} sessions")  # FIXED: Removed emoji
            
            # Don't retry immediately if we should stop
            if not client.should_run:
                logger.info("Graceful shutdown requested")  # FIXED: Removed emoji
                break
            
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received")  # FIXED: Removed emoji
            break
            
        except Exception as e:
            session_duration = time.time() - session_start
            total_uptime += session_duration
            
            logger.error(f"Session #{session_count} crashed after {session_duration:.1f}s: {e}")
            logger.debug(traceback.format_exc())
            
        finally:
            # Clean up current session
            if client:
                try:
                    await client.close_safe()
                except Exception as e:
                    logger.warning(f"Error during cleanup: {e}")
        
        # Brief pause before retry (unless shutdown requested)
        if client and client.should_run:
            retry_delay = min(30, session_count * 5)  # Progressive delay up to 30s
            logger.info(f"Retrying in {retry_delay} seconds...")  # FIXED: Removed emoji
            await asyncio.sleep(retry_delay)
        else:
            break
    
    # Final statistics
    total_runtime = time.time() - start_time
    logger.info(f"FINAL STATISTICS:")  # FIXED: Removed emoji
    logger.info(f"   Total runtime: {total_runtime/3600:.1f} hours")
    logger.info(f"   Active uptime: {total_uptime/3600:.1f} hours ({100*total_uptime/total_runtime:.1f}%)")
    logger.info(f"   Sessions: {session_count}")
    logger.info(f"   Average session duration: {total_uptime/max(1,session_count)/60:.1f} minutes")
    logger.info("Production client shutdown complete")  # FIXED: Removed emoji

async def main():
    """Production entry point with top-level error handling"""
    try:
        await bulletproof_runner()
    except KeyboardInterrupt:
        logger.info("Main KeyboardInterrupt - shutting down")  # FIXED: Removed emoji
    except Exception as e:
        logger.critical(f"CRITICAL ERROR in main: {e}")  # FIXED: Removed emoji
        logger.critical(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    # Verify dependencies
    try:
        from testing_utils import OrderBook
        logger.info("Dependencies verified")  # FIXED: Removed emoji
    except ImportError as e:
        logger.critical(f"CRITICAL: Missing dependency - {e}")  # FIXED: Removed emoji
        print("❌ CRITICAL: testing_utils.py not found. Exiting.")
        sys.exit(1)
    
    # System info
    logger.info("PRODUCTION COINBASE WEBSOCKET CLIENT")
    logger.info("=" * 50)
    logger.info(f"Python: {sys.version}")
    logger.info(f"Platform: {sys.platform}")
    logger.info(f"PID: {os.getpid()}")
    logger.info("=" * 50)
    
    try:
        # Set event loop policy for better Windows compatibility
        if sys.platform.startswith('win'):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        # Run the production client
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.info("Top-level KeyboardInterrupt")  # FIXED: Removed emoji
    except Exception as e:
        logger.critical(f"FATAL ERROR: {e}")  # FIXED: Removed emoji
        logger.critical(traceback.format_exc())
        sys.exit(1)
    finally:
        logger.info("Application terminated")  # FIXED: Removed emoji