import eventlet
eventlet.monkey_patch()
import threading

import socketio
from collections import defaultdict
import time
from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS
from flask_socketio import SocketIO

from flask import Flask, jsonify, request

import numpy as np # for realized vol tracking
from utils import binary_call_price, implied_vol_binary_call

sio = socketio.Client()

# Store last known bid/ask per contract
previous_quotes = {}
our_quotes = {} # current quotes we are proposing
new_quotes = {} # new quotes we are proposing this round
mid_prices = {} 
estiamted_mid_prices = {}

brti_window = [] # List to store last 60 seconds of BRTI prices

# Global dictionary to track seen trades by contract
seen_trades = {}

trade_log = []  # List of trade events with per-trade realized pnl
finalized_trades = []  # List of finalized trades with realized pnl
cumulative_pnl = defaultdict(float)  # Running realized + unrealized pnl per contract

# === Config ===
SIZING = 10
MIN_SPREAD = 4  # Minimum spread in cents
total_trades = 0
expected_spread_pnl = defaultdict(float)  # per ticker
total_expected_spread_pnl = 0.0
strikes = {}

# === State ===
positions = defaultdict(int)              # ticker -> net qty
avg_prices = defaultdict(float)           # ticker -> avg entry price
realized_pnl = defaultdict(float)         # ticker -> realized pnl
unrealized_pnl = defaultdict(float)
real_unrealized_pnl = defaultdict(float)  # ticker -> unrealized pnl


@sio.event
def connect():
    print("✅ Connected to WebSocket server.")

@sio.event
def disconnect():
    print("❌ Disconnected from WebSocket server.")

# Websocket Logic
app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')
# socketio.run(app, host="127.0.0.1", port=5052)

@app.route('/')
def index():
    return "WebSocket server is running."

active_clients = set()
@socketio.on('connect')
def handle_connect():
    sid = request.sid
    active_clients.add(sid)
    print(f"🔗 Client connected: {sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    active_clients.discard(sid)
    print(f"❌ Client disconnected: {sid}")

def emit_data(event, data):
    # Emit data to all connected clients.
    socketio.emit(event, data)
    print(f"🔊 Emitted event '{event}' with data")

# error bands on estimated fair price
def compute_error_band_quotes(P_fair, absolute_uncertainty=0.05):
    bid = max(0.0, P_fair - absolute_uncertainty)
    ask = min(1.0, P_fair + absolute_uncertainty)
    return bid, ask



@sio.on('brti_and_options_update')
def handle_update(data):
    global total_trades, unrealized_pnl, real_unrealized_pnl, expected_spread_pnl, total_expected_spread_pnl, our_quotes, new_quotes, mid_prices, brti_window, estiamted_mid_prices

    brti_window.append(data['brti'])
    if len(brti_window) > 60:
        brti_window.pop(0)

    # Compute realized volatility if enough data
    if len(brti_window) > 1:
        log_returns = np.diff(np.log(brti_window))
        brti_60s_realized_volatility = np.std(log_returns) # convert to years

        # Annualize (31,536,000 seconds in a year)
        volatility_annualized = brti_60s_realized_volatility * np.sqrt(31_536_000)

    else:
        volatility_annualized = 0.0
        
    print(f"\n📈 New update @ {data['timestamp']} | BRTI: {data['brti']:.2f} | Avg: {data['simple_average']:.2f}")
    total_realized = 0.0
    market_quotes = {}
    for contract in data.get('contracts', []):

        ticker = contract.get('ticker', 'N/A')
        mm_bid = contract.get('mm_bid')
        mm_ask = contract.get('mm_ask')
        
        best_bid = contract.get('best_bid', mm_bid)
        best_ask = contract.get('best_ask', mm_ask)

        orderbook = contract.get('orderbook', (None, None))

        spread = contract.get('spread')
        mid_price = contract.get('mid_price')
        trades = contract.get('trades')
        trade_market = contract.get('trade_market', False)
        strike = contract.get('strike', 'N/A')

        strikes[ticker] = strike
        mid_prices[ticker] = mid_price

        time = contract.get("time_left_sec")
        # time left in seconds, i need float of hours
        if time is None:
            time = 0
        else:           
            time = time / 3600  # convert to hours 

        bottom_strike, top_strike = list(map(float, strike.split("-")))
        top_price = binary_call_price(data['simple_average'], top_strike, time, volatility_annualized)
        bot_price = binary_call_price(data['simple_average'], bottom_strike, time, volatility_annualized)
        estimated_price = bot_price - top_price
        estiamted_mid_prices[ticker] = estimated_price

        trades = trades.get('trades', [])

        market_quotes[ticker] = {
            'mm_bid': mm_bid,
            'mm_ask': mm_ask,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'spread': spread,
            'time_left': time,
            'all_bids': orderbook[0],
            'all_asks' : orderbook[1],
        }

        print(f"🟩 {ticker} | Bid: {mm_bid} | Ask: {mm_ask} | Spread: {spread:.2f}")

        # Initialize trade tracking
        if ticker not in seen_trades:
            seen_trades[ticker] = {t['trade_id'] for t in trades}
            print(f"    🗃️ Registered {len(trades)} historical trades for {ticker}.")
            trades = []

        new_trades = [t for t in trades if t['trade_id'] not in seen_trades[ticker]]

        total_traded = 0
        for trade in new_trades:
            if not(trade_market):
                continue
            
            elif total_trades >= SIZING:
                print(f"    ⏹️ Max trades reached for {ticker}. Skipping further trades.")
                # add trade to seen trades to avoid processing again
                trade_id = trade['trade_id']
                seen_trades[ticker].add(trade_id)
                continue

            print(f"    🟢 New trade: {trade['count']} contracts @ {trade['yes_price']}  [TAKER: {trade['taker_side']}]")
            trade_id = trade['trade_id']
            seen_trades[ticker].add(trade_id)

            price = trade['yes_price']
            taker_side = trade['taker_side']
            count = min(trade['count'], SIZING)

            # Use our previously stored quotes
            our_quote = our_quotes.get(ticker)

            if not our_quote or our_quote['bid'] is None or our_quote['ask'] is None: # counter to ensure we made a quote last round
                continue  # skip if we didn't quote previously
            
            our_bid = our_quote['bid'] 
            our_ask = our_quote['ask'] 

            print(f"    🟢 Our quote: Bid: {our_bid}, Ask: {our_ask}")

            if taker_side == 'yes':
                side = 'sell'
                filled = price > our_ask

            else:
                side = 'buy'
                filled = price < our_bid

            current_pos = positions[ticker]
            current_avg = avg_prices[ticker]
            

            if filled:
                total_traded += abs(count)
                if side == 'buy':
                    realized = 0.0
                    filled = 0

                    if current_pos < 0:
                        closing_size = min(count, -current_pos)
                        pnl = (current_avg - our_bid) * closing_size
                        realized_pnl[ticker] += pnl
                        realized += pnl
                        positions[ticker] += closing_size
                        count -= closing_size
                        filled += closing_size

                        if positions[ticker] == 0:
                            avg_prices[ticker] = 0.0
                            current_avg = 0.0

                    if count > 0:
                        new_qty = positions[ticker] + count
                        new_avg = (
                            (current_avg * positions[ticker] + our_bid * count) / new_qty
                        ) if new_qty != 0 else 0.0
                        positions[ticker] = new_qty
                        avg_prices[ticker] = new_avg
                        filled += count

                     # === Track trade statistics ===
                    spread = our_ask - our_bid if our_bid is not None and our_ask is not None else 0
                    spread_edge = (spread / 100.0) / 2 * filled  # convert cents to dollars

                    total_trades += filled
                    expected_spread_pnl[ticker] += spread_edge
                    total_expected_spread_pnl += spread_edge

                    trade_log.append({
                        'trade_id': trade_id,
                        'ticker': ticker,
                        'side': 'buy',
                        'price': our_bid,
                        'size': filled,
                        'realized_pnl': realized,
                        'position_after': positions[ticker],
                        'avg_entry_price_after': avg_prices[ticker]
                    })
                    print(f"    🟩 FILLED BUY {filled} @ {our_bid:.2f}")

                elif side == 'sell':
                    realized = 0.0
                    filled = 0

                    if current_pos > 0:
                        closing_size = min(count, current_pos)
                        pnl = (our_ask - current_avg) * closing_size
                        realized_pnl[ticker] += pnl
                        realized += pnl
                        positions[ticker] -= closing_size
                        count -= closing_size
                        filled += closing_size

                        if positions[ticker] == 0:
                            avg_prices[ticker] = 0.0
                            current_avg = 0.0

                    if count > 0:
                        new_qty = positions[ticker] - count
                        new_avg = (
                            (current_avg * positions[ticker] - our_ask * count) / new_qty
                        ) if new_qty != 0 else 0.0
                        positions[ticker] = new_qty
                        avg_prices[ticker] = new_avg
                        filled += count
                    
                    # Track trade statitics
                    our_spread = our_ask - our_bid if our_bid is not None and our_ask is not None else 0
                    spread_edge = (our_spread / 100.0) / 2 * filled  # convert cents to dollars

                    total_trades += filled
                    expected_spread_pnl[ticker] += spread_edge
                    total_expected_spread_pnl += spread_edge

                    trade_log.append({
                        'trade_id': trade_id,
                        'ticker': ticker,
                        'side': 'sell',
                        'price': our_ask,
                        'size': filled,
                        'realized_pnl': realized,
                        'position_after': positions[ticker],
                        'avg_entry_price_after': avg_prices[ticker]
                    })
                    print(f"    🟥 FILLED SELL {filled} @ {price:.2f}")
            else:
                print(f"    🔍 TRADE @ {price:.2f} not inside our market.")

        # Save latest quote to compare next round
        if int(spread) <= MIN_SPREAD:
            new_bid = None
            new_ask = None 
        else:
            new_bid = mm_bid + 1 if mm_bid + 1 < best_ask else None
            new_ask = mm_ask - 1 if mm_ask - 1 > best_bid else None

        our_quotes[ticker] = {
            'bid': new_bid,
            'ask': new_ask,
        }

        new_quotes[ticker] = {
            'bid': new_bid,
            'ask': new_ask,
        }

        if not(trade_market) or best_bid == 0 or best_ask == 100:
            print(f"    ⛔ Too think for {ticker}. Skipping.")
        elif new_bid is not None and new_ask is not None:
            print(f"    ✏️ Propose tighter quote")
        else:
            print(f"    ⛔ Cannot tighten spread without crossing.")

        # === Compute PnL with fallback to estimated mid price
        pos = positions[ticker]
        avg = avg_prices[ticker]

        # Always prefer estimated mid price if available
        estimated_mid = estiamted_mid_prices.get(ticker) * 100 # convert to cents
        if estimated_mid is not None:
            mid = estimated_mid
        else:
            mid = mid_price  # fallback to market mid price

        if pos != 0 and avg is not None and mid is not None:
            unreal = (mid - avg) * pos
            # print ticker unrealized stats
            unrealized_pnl[ticker] = unreal

        pos = positions[ticker]
        if pos != 0:
            print(f"  {ticker.split("-")[-1]}: {pos} @ {avg_prices[ticker]:.2f}")

    total_unrealized = sum(unrealized_pnl.values())
    print(f"💰 Realized PnL:   ${total_realized/100:.2f}")
    print(f"📈 Unrealized PnL: ${sum(unrealized_pnl.values())/100:.2f}")
    print(f"📊 Total Trades:         {total_trades}")
    print(f"💸 Expected Spread PnL:  ${total_expected_spread_pnl:.2f}")
    for ticker in expected_spread_pnl:
        print(f"    {ticker.split('-')[-1]}: ${expected_spread_pnl[ticker]:.2f}")
    print("=" * 50)

    our_quotes = new_quotes.copy()
    new_quotes = {}

    # === Emit structured state ===
    emit_data("dashboard_update", {
        "timestamp": data["timestamp"],
        "market_quotes": market_quotes,
        "estimated_mid_prices": {k: float(v)*100 for k, v in estiamted_mid_prices.items()},
        "our_quotes": our_quotes,
        "positions": dict(positions),
        "avg_prices": dict(avg_prices),
        "mid_prices": dict(mid_prices),
        "brti_60s_price" : data["simple_average"],
        "brti_60s_realized_volatility": volatility_annualized,
        "strikes": strikes,
        "realized_pnl": {k: v / 100 for k, v in realized_pnl.items()},
        "unrealized_pnl": {k: v / 100 for k, v in unrealized_pnl.items()},  # in dollars
        "cumulative_pnl": total_unrealized/100 + total_realized/100,
        "total_trades": total_trades,
        "expected_spread_pnl": dict(expected_spread_pnl),
        "total_expected_spread_pnl": total_expected_spread_pnl,
        "quotes": our_quotes,
        "trade_log": trade_log[-100:]
    })
    
@sio.on('final_itm_market')
def handle_finalized_outcomes(data):
    global finalized_trades, trade_log, positions, avg_prices, realized_pnl, cumulative_pnl, unrealized_pnl, global_total_cumulative_pnl
    timestamp = data.get('timestamp', time.time())
    yes_market = data.get('yes_market', None)

    print("🔄 Market Finalized. Processing outcomes.")
    print(f"📊 Final ITM Contract: {yes_market} at {timestamp}")

    for ticker, pos in positions.items():
        if pos == 0:
            continue

        # Outcome is 1 (100 payout) if it is the yes_market
        result = 100 if ticker == yes_market else 0
        avg_entry = avg_prices.get(ticker, 0.0)

        final_pnl = (result - avg_entry) * pos
        realized_pnl[ticker] += final_pnl
        cumulative_pnl[ticker] += final_pnl

        print(f"🔚 {ticker}: Closed position {pos} @ avg {avg_entry:.2f} -> Outcome: {result} | Final PnL: {final_pnl/100:.2f}")
    
    # Emit final summary
    cumulative_total_pnl = sum(realized_pnl.values()) / 100
    expected_edge = sum(expected_spread_pnl.values())    

    # Update trade log with final outcomes and move to finalized_trades
    for trade in trade_log:
        ticker = trade['ticker']
        trade['expired'] = True
        trade['outcome'] = 1 if ticker == yes_market else 0
        finalized_trades.append(trade)

    print(f"📈 Total Cumulative PnL: ${cumulative_total_pnl:.2f} | Expected Edge: ${expected_edge:.2f}")
    print(f"📊 Finalized Trades: {len(finalized_trades)}")
    print(f"📊 Expected Spread PnL: {total_expected_spread_pnl:.2f}")
    print("=" * 50)

    # TODO: Implement logic to SAVE this information somewhere in like a CSV, then restart the test_trading file the dashboard. 
    # then can just make another dashboard for visualizing results

    return finalized_trades, cumulative_total_pnl, expected_edge

def start_sio_client():
    sio.connect("http://localhost:5050", transports=["websocket"])
    sio.wait()

if __name__ == "__main__":
    # Start the client in a background thread
    threading.Thread(target=start_sio_client, daemon=True).start()

    # Start the Flask-SocketIO server
    socketio.run(app, host="127.0.0.1", port=5052)