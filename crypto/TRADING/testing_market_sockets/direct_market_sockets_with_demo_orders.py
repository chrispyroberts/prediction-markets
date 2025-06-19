import asyncio
import websockets
import json
import time
import math

import atexit # Shutdown handler
import signal
import sys

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO

from utils import sign_pss_text, private_key_obj, KALSHI_API_KEY_ID, get_current_event, get_markets_from_event, test_authentication, cancel_all_orders
from order_handling import OrderManager

mm = None  # Global market maker instance
shutdown_event = asyncio.Event()  # Global shutdown event

# === Configuration ===
DEBUG = True
def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

# Global cleanup handler
def cleanup_and_exit():
    """Cancel all orders before exiting"""
    global mm, shutdown_event
    print("\n🛑 Program shutting down, cancelling all orders...")
    
    try:
        if mm is not None:
            # Use the demo setting from the market maker
            demo_mode = getattr(mm, 'demo', True)  # Default to True if not set
            result = cancel_all_orders(demo=demo_mode)
            
            if result['success']:
                print(f"✅ Successfully cancelled {result['cancelled_count']} orders")
                if result['failed_count'] > 0:
                    print(f"⚠️ Failed to cancel {result['failed_count']} orders")
            else:
                print(f"❌ Error cancelling orders: {result.get('error', 'Unknown error')}")
        else:
            print("ℹ️ No market maker instance found, nothing to clean up")
            
    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
    
    # Signal all async tasks to stop
    if shutdown_event and not shutdown_event.is_set():
        shutdown_event.set()
    
    print("👋 Cleanup complete, exiting...")

# Register cleanup handlers
atexit.register(cleanup_and_exit)

def signal_handler(signum, frame):
    """Handle interrupt signals (Ctrl+C, etc.)"""
    print(f"\n🛑 Received signal {signum}")
    cleanup_and_exit()
    sys.exit(0)

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Termination signal
if hasattr(signal, 'SIGHUP'):  # Unix only
    signal.signal(signal.SIGHUP, signal_handler)

# Simulated market maker class
class MarketMaker:
    def __init__(self, tickers, demo=True):
        self.tickers = tickers
        self.orderbooks = {t: {'yes': {}, 'no': {}} for t in tickers}
        self.our_quotes = {t: {'bid': None, 'ask': None} for t in tickers}
        self.positions = {t: 0 for t in tickers}
        self.avg_prices = {t: 0.0 for t in tickers}
        self.realized_pnl = {t: 0.0 for t in tickers}
        self.unrealized_pnl = {t: 0.0 for t in tickers}
        self.trade_log = {t: [] for t in tickers}
        self.fill_log = []

        self.total_trades = 0

        # mm config
        self.mm_threshold = 80
        self.mm_min_spread = 8      
        self.mm_size = 100   
        self.search = True # Enable searching for viable quotes rather than just top market maker quotes
        
        # Initialize order manager
        self.order_manager = OrderManager(self, demo=demo)
    
    async def get_top_quote(self, ticker):
        """
        Legacy quote calculation - undercuts top market maker only.
        """
        # find market makers in the orderbook
        mm_bid = 0 
        for price, qty in sorted(self.orderbooks[ticker]['yes'].items(), reverse=True):
            if qty >= self.mm_size:
                mm_bid = price
                break
        
        mm_ask = 100 
        for price, qty in sorted(self.orderbooks[ticker]['no'].items()):
            if qty >= self.mm_size:
                mm_ask = price
                break

        # If we have a valid market maker bid and ask, update our quotes
        if mm_bid > 0 and mm_ask < 100:
            spread = abs(mm_ask - mm_bid)
            if spread >= self.mm_min_spread:
                self.our_quotes[ticker]['bid'] = mm_bid + 1
                self.our_quotes[ticker]['ask'] = mm_ask - 1
                # debug_print(f"💰 [LEGACY] Updated quotes for {ticker}: Bid {mm_bid + 1}, Ask {mm_ask - 1}")
            else:
                self.our_quotes[ticker]['bid'] = None
                self.our_quotes[ticker]['ask'] = None
                # debug_print(f"❌ [LEGACY] Spread too narrow for {ticker}: {spread} < {self.mm_min_spread}")
        else:
            self.our_quotes[ticker]['bid'] = None
            self.our_quotes[ticker]['ask'] = None
            # debug_print(f"❌ [LEGACY] No valid market maker quotes for {ticker}")
        
        # Trigger order management after updating quotes
        await self.order_manager.handle_quote_update(ticker)

    def search_viable_quotes_efficient(self, ticker):
        """
        Algorithmically efficient O(n log n) search for viable quotes using two-pointer technique.
        """
        
        yes_book = self.orderbooks[ticker]['yes']
        no_book = self.orderbooks[ticker]['no']
        
        # Extract viable bid levels - O(n)
        viable_bids = []
        for price, qty in yes_book.items():
            if qty >= self.mm_threshold:
                viable_bid_price = price + 1
                if 1 <= viable_bid_price <= 99:
                    viable_bids.append(viable_bid_price)
        
        # Extract viable ask levels - O(m)  
        viable_asks = []
        for price, qty in no_book.items():
            if qty >= self.mm_threshold:
                viable_ask_price = price - 1
                if 1 <= viable_ask_price <= 99:
                    viable_asks.append(viable_ask_price)
        
        if not viable_bids or not viable_asks:
            return None, None
        
        # Sort once - O(n log n) + O(m log m)
        viable_bids.sort(reverse=True)  # Highest first
        viable_asks.sort()              # Lowest first
        
        # Two-pointer approach to find best spread - O(n + m)
        best_bid, best_ask = None, None
        
        bid_idx = 0
        ask_idx = 0
        move_bid = True 
        
        while bid_idx < len(viable_bids) and ask_idx < len(viable_asks):
            bid_price = viable_bids[bid_idx]
            ask_price = viable_asks[ask_idx]
            
            spread = ask_price - bid_price
            
            if spread > self.mm_min_spread:
                # valid spread found
                best_bid, best_ask = bid_price, ask_price

                 # if first idxs are a solution, return
                if bid_idx == 0 and ask_idx == 0:
                    return best_bid, best_ask
                else:
                    # undo previous pointer movement and check in opposite direction
                    if move_bid:
                        if ask_idx -1 < 0 or bid_idx + 1 >= len(viable_bids):
                            # no more solutions in this direction
                            return best_bid, best_ask
                        
                        ask_idx -= 1
                        bid_idx += 1

                    elif not move_bid:
                        if bid_idx - 1 < 0 or ask_idx + 1 >= len(viable_asks):
                            # no more solutions in this direction
                            return best_bid, best_ask
                        
                        bid_idx -= 1
                        ask_idx += 1

                    bid_price = viable_bids[bid_idx]
                    ask_price = viable_asks[ask_idx]
                    spread = ask_price - bid_price
                    if spread > self.mm_min_spread:
                        # found another solution, take the average of both and round down if ask and up if bid

                        ask_diff = abs(ask_price - best_ask)
                        bid_diff = abs(bid_price - best_bid)
                        if ask_diff == 1: # we can round down to give better price 
                            avg_ask = int(math.floor((best_ask + ask_price) / 2))
                        else: # round up for the extra 1c bc we greedy
                            avg_ask = int(math.ceil((best_ask + ask_price) / 2))

                        if bid_diff == 1: # we can round up to give better price
                            avg_bid = int(math.ceil((best_bid + bid_price) / 2)) # maybe use floor if the markets are wide enough, we could get another 1c per contract
                        else: # round down for the extra 1c bc we greedy
                            avg_bid = int(math.floor((best_bid + bid_price) / 2)) # maybe use floor if the markets are wide enough, we could get another 1c per contract

                        # we wont be top of orderbook here, but we will be inbetween two orders, so we can quote safely
                        return avg_bid, avg_ask 

                    else:
                        # no more solutions
                        return best_bid, best_ask
            else:
                if move_bid:
                    # Move bid pointer to find a higher bid
                    bid_idx += 1
                    move_bid = False
                else:
                    # Move ask pointer to find a lower ask
                    ask_idx += 1
                    move_bid = True

        return None, None

    async def get_viable_quote(self, ticker):
        """
        Updated quote function using efficient two-pointer search algorithm.
        """
        
        # Use the efficient search algorithm
        viable_bid, viable_ask = self.search_viable_quotes_efficient(ticker)
        
        if viable_bid is not None and viable_ask is not None:
            # We found a viable market - set our quotes
            self.our_quotes[ticker]['bid'] = viable_bid
            self.our_quotes[ticker]['ask'] = viable_ask
            # debug_print(f"💰 {ticker} - Setting quotes: Bid {viable_bid}, Ask {viable_ask}")
        else:
            # No viable market found - don't quote
            self.our_quotes[ticker]['bid'] = None
            self.our_quotes[ticker]['ask'] = None
            # debug_print(f"🚫 {ticker} - No quotes set (no viable market)")
        
        # Trigger order management after updating quotes
        await self.order_manager.handle_quote_update(ticker)

    async def update_quote(self, ticker):
        """
        Main quote update method - toggles between legacy and efficient search modes.
        """
        if self.search:
            await self.get_viable_quote(ticker)
        else:
            await self.get_top_quote(ticker)

    async def update_orderbook_delta(self, ticker, msg): 
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

        # debug_print(f"📈 New Orderbook Delta for {ticker}")

        # trigger quote updating (now async)
        await self.update_quote(ticker)

    async def update_orderbook_snapshot(self, ticker, msg): 
        self.orderbooks[ticker]['yes'] = {p: q for p, q in msg.get('yes', [])}
        self.orderbooks[ticker]['no'] = {100-p: q for p, q in msg.get('no', [])}

        # trigger quote updating (now async)
        await self.update_quote(ticker)

    def process_trade(self, ticker, msg):
        """Process a trade message to determine if we got filled and update positions accordingly."""
        self.trade_log[ticker].append(msg)
        
        yes_price = msg.get("yes_price", None)
        count = min(msg.get("count", 0), self.mm_size)  # Limit to mm_size
        taker_side = msg.get("taker_side")  # "yes" or "no"
        
        if yes_price is None or count <= 0:
            print(f"❌ Invalid trade data for {ticker}: price={yes_price}, count={count}")
            return
        
        our_bid = self.our_quotes[ticker]['bid']
        our_ask = self.our_quotes[ticker]['ask']
        
        if our_bid is None or our_ask is None:
            print(f"❌ No valid quotes for {ticker}, cannot process trade.")
            return
        
        # Print the trade details
        print(f"🔄 Processing trade for {ticker}: YES price={yes_price}, count={count}, taker_side={taker_side}")

        # Determine if we got filled based on trade price vs our quotes
        filled = False
        fill_side = None
        fill_price = None
        fill_size = count
        
        if taker_side == "yes":
            # Someone bought YES, check if they hit our ASK (we sold)
            if yes_price > our_ask:
                filled = True
                fill_side = "sell"
                fill_price = our_ask
                print(f"💰 {ticker} FILLED SELL: {fill_size} @ {fill_price} (market price: {yes_price})")
            else:
                print(f"❌ {ticker} YES trade at {yes_price} did not hit our ask {our_ask}")
        
        elif taker_side == "no":
            # Someone bought NO (equivalent to selling YES), check if we bought at our BID
            if yes_price < our_bid:
                filled = True
                fill_side = "buy"
                fill_price = our_bid
                print(f"💰 {ticker} FILLED BUY: {fill_size} @ {fill_price} (market price: {yes_price})")
            else:
                print(f"❌ {ticker} YES trade at {yes_price} did not hit our bid {our_bid}")
        
        if filled:
            self.total_trades += fill_size
            self._process_fill(ticker, fill_side, fill_price, fill_size)

    def _process_fill(self, ticker, side, price, size):
        """Process a fill by updating positions, average prices, and calculating PnL."""
        current_pos = self.positions[ticker]
        current_avg = self.avg_prices[ticker]
        realized_pnl = 0.0
        
        print(f"📊 Processing {side} fill: {size} @ {price} | Current pos: {current_pos} @ {current_avg}")
        
        if side == "buy":
            # We bought shares
            realized_pnl = 0.0
            remaining_size = size
            
            # First, close any short position (realize PnL)
            if current_pos < 0:
                closing_size = min(remaining_size, -current_pos)
                # PnL = (avg_entry_price - fill_price) * quantity for short closing
                pnl_per_share = current_avg - price
                realized_pnl = pnl_per_share * closing_size
                
                # Update position
                self.positions[ticker] += closing_size
                remaining_size -= closing_size
                
                # debug_print(f"    🔄 Closed {closing_size} short @ {current_avg} vs {price} = ${realized_pnl/100:.2f} PnL")
                
                # If position is now flat, reset average price
                if self.positions[ticker] == 0:
                    self.avg_prices[ticker] = 0.0
                    current_avg = 0.0
            
            # Then, open new long position with remaining size
            if remaining_size > 0:
                if self.positions[ticker] == 0:
                    # Starting fresh long position
                    self.positions[ticker] = remaining_size
                    self.avg_prices[ticker] = price
                else:
                    # Adding to existing long position
                    total_shares = self.positions[ticker] + remaining_size
                    total_cost = (self.positions[ticker] * self.avg_prices[ticker]) + (remaining_size * price)
                    self.avg_prices[ticker] = total_cost / total_shares
                    self.positions[ticker] = total_shares
                
                print(f"    📈 New long position: {self.positions[ticker]} @ {self.avg_prices[ticker]:.2f}")
        
        elif side == "sell":
            # We sold shares
            realized_pnl = 0.0
            remaining_size = size
            
            # First, close any long position (realize PnL)
            if current_pos > 0:
                closing_size = min(remaining_size, current_pos)
                # PnL = (fill_price - avg_entry_price) * quantity for long closing
                pnl_per_share = price - current_avg
                realized_pnl = pnl_per_share * closing_size
                
                # Update position
                self.positions[ticker] -= closing_size
                remaining_size -= closing_size
                
                print(f"    🔄 Closed {closing_size} long @ {current_avg} vs {price} = ${realized_pnl/100:.2f} PnL")
                
                # If position is now flat, reset average price
                if self.positions[ticker] == 0:
                    self.avg_prices[ticker] = 0.0
                    current_avg = 0.0
            
            # Then, open new short position with remaining size
            if remaining_size > 0:
                if self.positions[ticker] == 0:
                    # Starting fresh short position
                    self.positions[ticker] = -remaining_size
                    self.avg_prices[ticker] = price
                else:
                    # Adding to existing short position
                    total_shares = abs(self.positions[ticker]) + remaining_size
                    total_proceeds = (abs(self.positions[ticker]) * self.avg_prices[ticker]) + (remaining_size * price)
                    self.avg_prices[ticker] = total_proceeds / total_shares
                    self.positions[ticker] = -total_shares
                
                print(f"    📉 New short position: {self.positions[ticker]} @ {self.avg_prices[ticker]:.2f}")
        
        # Update realized PnL
        if realized_pnl != 0:
            self.realized_pnl[ticker] += realized_pnl
            print(f"    💰 Realized PnL for {ticker}: ${realized_pnl/100:.2f} (Total: ${self.realized_pnl[ticker]/100:.2f})")
        
        # Log the trade
        trade_entry = {
            'timestamp': time.time(),
            'ticker': ticker,
            'side': side,
            'price': price,
            'size': size,
            'realized_pnl': realized_pnl,
            'position_after': self.positions[ticker],
            'avg_price_after': self.avg_prices[ticker]
        }
        
        self.fill_log.append(trade_entry)
        
        # Print summary
        total_realized = sum(self.realized_pnl.values())
        # debug_print(f"📊 Position Summary for {ticker}: {self.positions[ticker]} @ {self.avg_prices[ticker]:.2f}")
        # debug_print(f"💰 Total Realized PnL: ${total_realized/100:.2f}")

    def calculate_unrealized_pnl(self, ticker, current_market_price):
        """Calculate unrealized PnL for a position given current market price."""
        position = self.positions[ticker]
        avg_price = self.avg_prices[ticker]
        
        if position == 0:
            return 0.0
        
        if position > 0:
            # Long position: PnL = (current_price - avg_entry) * quantity
            unrealized = (current_market_price - avg_price) * position
        else:
            # Short position: PnL = (avg_entry - current_price) * abs(quantity)
            unrealized = (avg_price - current_market_price) * abs(position)
        
        self.unrealized_pnl[ticker] = unrealized
        return unrealized

    def get_portfolio_summary(self):
        """Get a complete portfolio summary including all positions and PnL."""
        total_realized = sum(self.realized_pnl.values())
        total_unrealized = sum(self.unrealized_pnl.values())
        
        summary = {
            'total_trades': self.total_trades,
            'total_realized_pnl': total_realized / 100,  # Convert cents to dollars
            'total_unrealized_pnl': total_unrealized / 100,
            'total_pnl': (total_realized + total_unrealized) / 100,
            'positions': {},
            'realized_pnl_by_ticker': {k: v/100 for k, v in self.realized_pnl.items()},
            'unrealized_pnl_by_ticker': {k: v/100 for k, v in self.unrealized_pnl.items()}
        }
        
        for ticker in self.tickers:
            if self.positions[ticker] != 0:
                summary['positions'][ticker] = {
                    'quantity': self.positions[ticker],
                    'avg_price': self.avg_prices[ticker],
                    'realized_pnl': self.realized_pnl[ticker] / 100,
                    'unrealized_pnl': self.unrealized_pnl[ticker] / 100
                }
        
        return summary

async def kalshi_ws_stream(market_tickers):
    global mm  # Use the global market maker instance
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
        "trade": 0,
        "fill": 0
    }

    try:
        async with websockets.connect(ws_url, extra_headers=headers, ping_interval=20, ping_timeout=10) as ws:
            print("✅ WebSocket connected!")

            # Subscribe to orderbook_delta
            await ws.send(json.dumps({ "id": 1, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"],"market_tickers": market_tickers}}))
            print("📡 Subscribed to orderbook_delta.")

            # Subscribe to trade ( ALL TRADES )
            await ws.send(json.dumps({ "id": 2, "cmd": "subscribe", "params": { "channels": ["trade"], "market_tickers": market_tickers}}))
            print("📡 Subscribed to trade.")

            # Subscribe to fill ( JUST OUR ORDERS )
            await ws.send(json.dumps({ "id": 3, "cmd": "subscribe", "params": {"channels": ["fill"],"market_tickers": market_tickers}}))
            print("📡 Subscribed to fill.")

            async for message in ws:
                data = json.loads(message)
                msg_type = data.get("type")
                seq = data.get("seq")
                msg = data.get("msg", {})

                # Determine channel by sid (this works if only one sid per channel)
                if msg_type == "subscribed":
                    debug_print(f"✅ Subscribed to channel {msg['channel']} (sid: {msg['sid']})")
                    continue

                # Determine channel by message type
                if msg_type == "orderbook_snapshot" or msg_type == "orderbook_delta":
                    channel = "orderbook_delta"
                
                elif msg_type == "trade":
                    channel = "trade"
                
                elif msg_type == "fill":
                    channel = "fill"
                
                else:
                    debug_print("Other message:", data)
                    continue

                ticker = msg.get("market_ticker")

                # Check sequence gaps per channel per market
                if ticker:
                    prev_seq = last_seq[channel]
                    if prev_seq != 0 and seq != prev_seq + 1:
                        print(f"⚠️ Sequence gap on {channel}! Got {seq}, expected {prev_seq+1}. Reconnecting.")
                        raise Exception("Sequence gap")
                    last_seq[channel] = seq

                if msg_type == "trade":
                    # Process trade message (keep this sync for now)
                    mm.process_trade(ticker, msg)

                elif msg_type == "orderbook_snapshot":
                    # Update orderbook snapshot (now async)
                    await mm.update_orderbook_snapshot(ticker, msg)

                elif msg_type == "orderbook_delta":
                    # Update orderbook delta (now async)
                    await mm.update_orderbook_delta(ticker, msg)



    except Exception as e:
        print("❌ WebSocket error or disconnection:", e)
        raise  # Trigger reconnect automatically

async def subscription_confirmation_watchdog(ws, confirmed_set, timeout):
    await asyncio.sleep(timeout)
    if not confirmed_set:
        print("⚠️ Subscription not confirmed in time. Triggering reconnect.")
        await ws.close()

async def start_ws_client(market_tickers):
    while True:
        try:
            await kalshi_ws_stream(market_tickers)
        except Exception as e:
            # cancel orders first
            cancel_all_orders(demo=True)
            print("🔄 Attempting to reconnect in 3 seconds...")
            await asyncio.sleep(5)

async def periodic_status_report():
    """Print portfolio summary and market status every 5 seconds."""
    global mm
    while True:
        await asyncio.sleep(5)
        if mm is None:
            continue
            
        print("\n" + "="*80)
        print(f"📊 PORTFOLIO STATUS - {time.strftime('%H:%M:%S')}")
        print("="*80)
        
        # Get portfolio summary
        summary = mm.get_portfolio_summary()
        
        # Print overall PnL
        print(f"💰 Total Trades: {summary['total_trades']}")
        print(f"💰 Total Realized PnL: ${summary['total_realized_pnl']:.2f}")
        print(f"📈 Total Unrealized PnL: ${summary['total_unrealized_pnl']:.2f}")
        print(f"🎯 Total PnL: ${summary['total_pnl']:.2f}")
        
        # NEW: Print order status
        order_status = mm.order_manager.get_order_status()
        print(f"📋 Active Orders: {order_status['active_orders_count']}")
        print(f"⏳ Pending Fill Checks: {order_status['pending_fills_count']}")
        
        # Print positions if any
        if summary['positions']:
            print("\n📋 OPEN POSITIONS:")
            for ticker, pos_info in summary['positions'].items():
                print(f"  {ticker}: {pos_info['quantity']} @ {pos_info['avg_price']:.2f} "
                      f"(R: ${pos_info['realized_pnl']:.2f}, U: ${pos_info['unrealized_pnl']:.2f})")
        else:
            print("\n📋 No open positions")
        
        # Print current market status
        print("\n📈 CURRENT MARKETS & QUOTES:")
        for ticker in mm.tickers:
            try:
                # Our calculated quotes
                our_bid = mm.our_quotes[ticker]['bid']
                our_ask = mm.our_quotes[ticker]['ask']
                
                # Our live quotes (actually in market)
                live_bid = mm.order_manager.safe_get(mm.order_manager.live_quotes, ticker, 'bid')
                live_ask = mm.order_manager.safe_get(mm.order_manager.live_quotes, ticker, 'ask')
                
                if not(live_bid is None or live_ask is None):
                    # Get best market prices from orderbook
                    yes_book = mm.orderbooks[ticker]['yes']
                    no_book = mm.orderbooks[ticker]['no']
                    
                    market_bid = max(yes_book.keys()) if yes_book else 0
                    market_ask = min(no_book.keys()) if no_book else 100
                    
                    # Get just the last part of the ticker for cleaner display
                    ticker_short = ticker.split('-')[-1] if '-' in ticker else ticker
                    
                    print(f"  {ticker_short}:")
                    print(f"    Market: {market_bid}/{market_ask}")
                    print(f"    Calculated: {our_bid or 'None'}/{our_ask or 'None'}")
                    print(f"    Live Orders: {live_bid or 'None'}/{live_ask or 'None'}")
                
            except Exception as e:
                print(f"  {ticker}: Error displaying market data - {e}")
        
        print("="*80 + "\n")

async def start_ws_client_with_monitoring(market_tickers):
    """Start WebSocket client alongside periodic monitoring and fill checking."""
    global mm
    
    # Start all tasks concurrently
    await asyncio.gather(
        start_ws_client(market_tickers),
        periodic_status_report(),
        mm.order_manager.check_fills_periodically()  # NEW: Add fill checking
    )

if __name__ == "__main__":
    # Test authentication first
    print("Testing authentication...")
    if not test_authentication(demo=True):
        print("❌ Authentication failed. Please check your credentials.")
        exit(1)
        
    event = get_current_event()
    markets = get_markets_from_event(event)
    print(f"Found {len(markets)} markets.")
    for market in markets:
        print(f"Market: {market}")
    market_ticker = markets # ["KXBTC-25JUN0610-B103875"]  # example ticker
    
    # Initialize market maker with demo=True for testing
    mm = MarketMaker(market_ticker, demo=True)  # Set demo=False for production
    
    asyncio.run(start_ws_client_with_monitoring(market_ticker))