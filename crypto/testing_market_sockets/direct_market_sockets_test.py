
import asyncio
import websockets
import json
import time
from utils import sign_pss_text, private_key_obj, KALSHI_API_KEY_ID, get_current_event, get_markets_from_event

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO

mm = None  # Global market maker instance

# === Configuration ===
DEBUG = False
def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

# Simulated market maker class
class MarketMaker:
    def __init__(self, tickers):
        self.tickers = tickers
        self.orderbooks = {t: {'yes': {}, 'no': {}} for t in tickers}
        self.our_quotes = {t: {'bid': None, 'ask': None} for t in tickers}
        self.positions = {t: 0 for t in tickers}
        self.avg_prices = {t: 0.0 for t in tickers}
        self.realized_pnl = {t: 0.0 for t in tickers}
        self.unrealized_pnl = {t: 0.0 for t in tickers}
        self.trade_log = {t: [] for t in tickers}

        self.total_trades = 0


        # mm config
        self.mm_threshold = 1000    # position threshold to trigger market making
        self.mm_min_spread = 5      # minimum spread for improving market 
        self.mm_size = 10           # size of each market making order
    
    def update_quote(self, ticker):
        # TODO: Definetly a better way to do this by checking the DELTA of the orderbook, rather than 2 for loops. 
        # TODO: The speedup gain of implementing such a method is not worth the time right now, but it is a good idea for the future
    
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

        debug_print("Updating quotes for ticker:", ticker)
        debug_print("Orderbook YES side:", self.orderbooks[ticker]['yes'])
        debug_print("Orderbook NO side:", self.orderbooks[ticker]['no'])
        debug_print("Market Maker Bid:", mm_bid, "Market Maker Ask:", mm_ask)
        
        # If we have a valid market maker bid and ask, update our quotes
        if mm_bid > 0 and mm_ask < 100:
            spread = abs(mm_ask - mm_bid)
            if spread >= self.mm_min_spread:
                self.our_quotes[ticker]['bid'] = mm_bid + 1
                self.our_quotes[ticker]['ask'] = mm_ask - 1
                debug_print(f"💰 Updated quotes for {ticker}: Bid {mm_bid}, Ask {mm_ask}")
            else:
                debug_print(f"❌ Spread too narrow for {ticker}: {spread} < {self.mm_min_spread}")
                # set our_quotes for this ticker to None
                self.our_quotes[ticker]['bid'] = None
                self.our_quotes[ticker]['ask'] = None
        else:
            debug_print(f"❌ No valid market maker quotes for {ticker}.")
            # set our_quotes for this ticker to None
            self.our_quotes[ticker]['bid'] = None
            self.our_quotes[ticker]['ask'] = None
        
    def update_orderbook_delta(self, ticker, msg):
        side = msg["side"]
        price = msg["price"]
        if side == 'NO':
            price = 100 - price  # Convert NO side price to YES side price
            
        change = msg["delta"]
        qty = self.orderbooks[ticker][side].get(price, 0) + change
        if qty <= 0:
            self.orderbooks[ticker][side].pop(price, None)
        else:
            self.orderbooks[ticker][side][price] = qty

        debug_print(f"📈 New Orderbook Delta for {ticker}")

        # trigger quote updating
        self.update_quote(ticker)

    def update_orderbook_snapshot(self, ticker, msg):
        self.orderbooks[ticker]['yes'] = {p: q for p, q in msg.get('yes', [])}
        self.orderbooks[ticker]['no'] = {100-p: q for p, q in msg.get('no', [])}

        # trigger quote updating
        self.update_quote(ticker)

    def process_trade(self, ticker, msg):
        self.trade_log[ticker].append(msg)
        yes_price = msg.get("yes_price", None)
        count = min(msg.get("count", None), self.mm_size) # Limit to mm_size
        side = "Sell" if msg["taker_side"] == "yes" else "Buy"

        our_bid = self.our_quotes[ticker]['bid']
        our_ask = self.our_quotes[ticker]['ask']

        if our_bid is None or our_ask is None:
            debug_print(f"❌ No valid quotes for {ticker}, cannot process trade.")
            return
        
        self.total_trades += abs(count)
        current_avg = self.avg_prices.get(ticker, 0.0)
        current_pos = self.positions.get(ticker, 0)
        realized = 0
        filled = 0


        if side == "Buy":
            # Person bought from market, check if our ask was hit
            if yes_price > our_bid:
                if current_pos < 0:
                    # We are short, close our position
                    closing_size = min(count, -current_pos)
                    pnl = (current_avg - our_bid)
                   




                debug_print(f"💹 {ticker} Buy trade: {count} contracts at {yes_price}, Avg Price: {self.avg_prices[ticker]}, Realized PnL: {self.realized_pnl[ticker]}")
            else:
                debug_print(f"❌ {ticker} Buy trade did not hit our ask: {yes_price} < {our_ask}")



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
        async with websockets.connect(ws_url, extra_headers=headers, ping_interval=10, ping_timeout=5) as ws:
            print("✅ WebSocket connected!")

            # Subscribe to orderbook_delta
            await ws.send(json.dumps({ "id": 1, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"],"market_tickers": market_tickers}}))
            print("📡 Subscribed to orderbook_delta.")

            # 5Subscribe to trade ( ALL TRADES )
            await ws.send(json.dumps({ "id": 2, "cmd": "subscribe", "params": { "channels": ["trade"], "market_tickers": market_tickers}}))
            print("📡 Subscribed to trade.")

            # 6️Subscribe to fill ( JUST OUR ORDERS )
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

                if msg_type == "orderbook_snapshot":
                    # Update orderbook snapshot
                    mm.update_orderbook_snapshot(ticker, msg)

                elif msg_type == "orderbook_delta":
                    # Update orderbook delta
                    mm.update_orderbook_delta(ticker, msg)

                elif msg_type == "trade":
                    # Process trade message
                    mm.process_trade(ticker, msg)

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
            print("🔄 Attempting to reconnect in 3 seconds...")
            await asyncio.sleep(3)

if __name__ == "__main__":
    event = get_current_event()
    markets = get_markets_from_event(event)
    print(f"Found {len(markets)} markets.")
    for market in markets:
        print(f"Market: {market}")
    market_ticker = markets # ["KXBTC-25JUN0610-B103875"]  # example ticker
    mm = MarketMaker(market_ticker)  # Initialize market maker with tickers
    asyncio.run(start_ws_client(market_ticker))