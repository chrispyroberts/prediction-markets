import asyncio
import time
import json
import websockets
import redis.asyncio as aioredis
import sys
import os

# Add the backend directory to the path for direct execution
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models import KalshiTradeData, KalshiFullOrderbookData, Heartbeat
from utils.kalshi_utils import (
    get_current_event, get_markets_from_event, test_authentication,
    sign_pss_text, private_key_obj, KALSHI_API_KEY_ID
)
from feeds import KALSHI_REDIS_URL, KALSHI_REDIS_CHANNEL, KALSHI_HEARTBEAT_INTERVAL

FEED_NAME = "kalshi"
DATA_CHANNEL = KALSHI_REDIS_CHANNEL

def extract_strike_from_ticker(ticker: str) -> float:
    # Example ticker: KXBTCD-25JUN2616-T97249.99
    try:
        return float(ticker.split('-')[-1][1:])
    except Exception:
        return 0.0

class KalshiDataCollector:
    def __init__(self):
        self.orderbooks = {}  # Current orderbook states
        self.last_top_of_book = {}  # Track last top-of-book state
        self.last_full_orderbook = {}  # Track last full orderbook state
        self.active_markets = set()  # Track markets with recent activity
        self.last_activity = {}  # Track last activity time per market
        self.full_orderbook_interval = 5.0  # Send full orderbook every 5 seconds for active markets
        
    def get_current_top_of_book(self, ticker):
        """Get current top of book with defaults for empty sides"""
        if ticker not in self.orderbooks:
            return {'bid': 0, 'bid_qty': 0, 'ask': 100, 'ask_qty': 0}
            
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
    
    def calculate_spread_and_mid(self, best_bid, best_ask):
        """Calculate spread and mid price"""
        if best_bid > 0 and best_ask < 100:
            spread = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2
        else:
            spread = 0
            mid_price = 0
        return spread, mid_price
    
    def get_full_orderbook_data(self, ticker):
        """Get full orderbook data for a ticker"""
        if ticker not in self.orderbooks:
            return None
        yes_book = self.orderbooks[ticker]['yes']
        no_book = self.orderbooks[ticker]['no']
        bids = {str(k): v for k, v in yes_book.items()}
        asks = {str(k): v for k, v in no_book.items()}
        tob = self.get_current_top_of_book(ticker)
        spread, mid_price = self.calculate_spread_and_mid(tob['bid'], tob['ask'])
        strike = extract_strike_from_ticker(ticker)
        return {
            'ticker': ticker,
            'strike': strike,
            'bids': bids,
            'asks': asks,
            'best_bid': tob['bid'],
            'best_bid_qty': tob['bid_qty'],
            'best_ask': tob['ask'],
            'best_ask_qty': tob['ask_qty'],
            'spread': spread,
            'mid_price': mid_price
        }
        
    def has_top_of_book_changed(self, ticker, current_tob):
        """Check if top of book has changed from last known state"""
        if ticker not in self.last_top_of_book:
            self.last_top_of_book[ticker] = {'bid': None, 'bid_qty': None, 'ask': None, 'ask_qty': None}
            
        last_tob = self.last_top_of_book[ticker]
        
        # Check if any of the top of book values have changed
        changed = (
            last_tob['bid'] != current_tob['bid'] or
            last_tob['bid_qty'] != current_tob['bid_qty'] or
            last_tob['ask'] != current_tob['ask'] or
            last_tob['ask_qty'] != current_tob['ask_qty']
        )
        
        return changed
    
    def has_orderbook_changed_significantly(self, ticker, threshold=0.01):
        """Check if orderbook has changed significantly (for full orderbook updates)"""
        if ticker not in self.last_full_orderbook:
            return True
            
        current_tob = self.get_current_top_of_book(ticker)
        last_tob = self.last_full_orderbook[ticker]
        
        # Check if spread or mid price has changed significantly
        current_spread, current_mid = self.calculate_spread_and_mid(current_tob['bid'], current_tob['ask'])
        last_spread, last_mid = self.calculate_spread_and_mid(last_tob['bid'], last_tob['ask'])
        
        spread_change = abs(current_spread - last_spread)
        mid_change = abs(current_mid - last_mid)
        
        return spread_change > threshold or mid_change > threshold

    async def update_orderbook_delta(self, ticker, msg):
        """Update orderbook from delta message"""
        try:
            side = msg["side"]
            price = msg["price"]
            change = msg["delta"]
            
            if ticker not in self.orderbooks:
                self.orderbooks[ticker] = {'yes': {}, 'no': {}}
                
            if side.lower() == 'no':
                price = 100 - price  # Convert NO side price to YES side price
                
            qty = self.orderbooks[ticker][side].get(price, 0) + change
            if qty <= 0:
                self.orderbooks[ticker][side].pop(price, None)
            else:
                self.orderbooks[ticker][side][price] = qty

            # Send full orderbook data
            full_data = self.get_full_orderbook_data(ticker)
            if full_data:
                return full_data
                
        except Exception as e:
            print(f"Error updating orderbook delta for {ticker}: {e}")
        return None

    async def update_orderbook_snapshot(self, ticker, msg):
        """Update orderbook from snapshot message"""
        try:
            if ticker not in self.orderbooks:
                self.orderbooks[ticker] = {'yes': {}, 'no': {}}
                
            self.orderbooks[ticker]['yes'] = {p: q for p, q in msg.get('yes', [])}
            self.orderbooks[ticker]['no'] = {100-p: q for p, q in msg.get('no', [])}

            # Send full orderbook data
            full_data = self.get_full_orderbook_data(ticker)
            if full_data:
                return full_data
                
        except Exception as e:
            print(f"Error updating orderbook snapshot for {ticker}: {e}")
        return None
    
    def should_send_full_orderbook(self, ticker):
        """Determine if we should send full orderbook update"""
        current_time = time.time()
        
        # Send if significant change
        if self.has_orderbook_changed_significantly(ticker, threshold=0.01):
            return True
        
        # Send periodically for active markets
        if ticker in self.active_markets:
            last_full = self.last_full_orderbook.get(ticker, {}).get('timestamp', 0)
            if current_time - last_full > self.full_orderbook_interval:
                return True
        
        return False

    def mark_market_active(self, ticker):
        """Mark a market as active"""
        self.active_markets.add(ticker)
        self.last_activity[ticker] = time.time()
        
    def cleanup_inactive_markets(self, timeout=60.0):
        """Remove markets that haven't had activity recently"""
        current_time = time.time()
        inactive = []
        for ticker in self.active_markets:
            if current_time - self.last_activity.get(ticker, 0) > timeout:
                inactive.append(ticker)
        
        for ticker in inactive:
            self.active_markets.discard(ticker)
            # Keep orderbook data but mark as inactive

async def kalshi_websocket_stream(redis, market_tickers):
    """WebSocket stream for Kalshi data"""
    ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    collector = KalshiDataCollector()

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

    try:
        async with websockets.connect(ws_url, extra_headers=headers, ping_interval=10, ping_timeout=5) as ws:
            print(f"Connected to Kalshi WebSocket for {len(market_tickers)} markets")

            # Subscribe to orderbook_delta
            await ws.send(json.dumps({
                "id": 1, 
                "cmd": "subscribe", 
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": market_tickers
                }
            }))

            # Subscribe to trades
            await ws.send(json.dumps({
                "id": 2, 
                "cmd": "subscribe", 
                "params": {
                    "channels": ["trade"], 
                    "market_tickers": market_tickers
                }
            }))

            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    receipt_timestamp_ms = time.time() * 1000
                    
                    data = json.loads(message)
                    msg_type = data.get("type")
                    msg = data.get("msg", {})

                    if msg_type == "subscribed":
                        print(f"Subscribed to channel: {msg['channel']}")
                        continue

                    ticker = msg.get("market_ticker")
                    if not ticker:
                        continue

                    # Process messages
                    if msg_type == "orderbook_snapshot":
                        full_orderbook_data = await collector.update_orderbook_snapshot(ticker, msg)
                        if full_orderbook_data:
                            orderbook_data = KalshiFullOrderbookData(
                                **full_orderbook_data,
                                timestamp=receipt_timestamp_ms / 1000
                            )
                            await redis.publish(DATA_CHANNEL, orderbook_data.model_dump_json())
                            
                    elif msg_type == "orderbook_delta":
                        full_orderbook_data = await collector.update_orderbook_delta(ticker, msg)
                        if full_orderbook_data:
                            orderbook_data = KalshiFullOrderbookData(
                                **full_orderbook_data,
                                timestamp=receipt_timestamp_ms / 1000
                            )
                            await redis.publish(DATA_CHANNEL, orderbook_data.model_dump_json())
                            
                    elif msg_type == "trade":
                        yes_price = msg.get('yes_price', 0)
                        count = msg.get('count', 0)
                        taker_side = msg.get('taker_side', '')
                        trade_value = yes_price * count
                        
                        trade_data = KalshiTradeData(
                            ticker=ticker,
                            yes_price=yes_price,
                            count=count,
                            taker_side=taker_side,
                            trade_value=trade_value,
                            timestamp=receipt_timestamp_ms / 1000
                        )
                        await redis.publish(DATA_CHANNEL, trade_data.model_dump_json())
                            
                except asyncio.TimeoutError:
                    continue
                except json.JSONDecodeError as e:
                    print(f"JSON decode error: {e}")
                except Exception as e:
                    print(f"Message processing error: {e}")

    except Exception as e:
        print(f"WebSocket error: {e}")
        raise

async def heartbeat_publisher(redis):
    """Publish heartbeat messages"""
    while True:
        heartbeat = Heartbeat(feed=FEED_NAME, timestamp=time.time())
        await redis.publish(DATA_CHANNEL, heartbeat.model_dump_json())
        await asyncio.sleep(KALSHI_HEARTBEAT_INTERVAL)

async def main():
    """Main function to start Kalshi data collection"""
    # Test authentication first
    if not test_authentication():
        print("ERROR: Authentication failed. Please check your credentials.")
        return
        
    # Get current markets
    event = get_current_event()
    markets = get_markets_from_event(event)
    
    if not markets:
        print("ERROR: Could not fetch markets")
        return
        
    print(f"Starting Kalshi data collection for {len(markets)} markets")
    for market in markets:
        print(f"  - {market}")
    
    # Connect to Redis
    redis = aioredis.from_url(KALSHI_REDIS_URL)
    
    # Start data collection
    await asyncio.gather(
        kalshi_websocket_stream(redis, markets),
        heartbeat_publisher(redis)
    )

if __name__ == "__main__":
    asyncio.run(main()) 