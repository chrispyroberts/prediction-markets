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


sio = socketio.Client()

# Store last known bid/ask per contract
previous_quotes = {}
our_quotes = {} # current quotes we are proposing
new_quotes = {} # new quotes we are proposing this round
mid_prices = {}

# Global dictionary to track seen trades by contract
seen_trades = {}

trade_log = []  # List of trade events with per-trade realized pnl
cumulative_pnl = defaultdict(float)  # Running realized + unrealized pnl per contract

# === Config ===
SIZING = 10
total_trades = 0
expected_spread_pnl = defaultdict(float)  # per ticker
total_expected_spread_pnl = 0.0
strikes = {}

# === State ===
positions = defaultdict(int)              # ticker -> net qty
avg_prices = defaultdict(float)           # ticker -> avg entry price
realized_pnl = defaultdict(float)         # ticker -> realized pnl

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


@sio.on('brti_and_options_update')
def handle_update(data):
    global total_trades, expected_spread_pnl, total_expected_spread_pnl, our_quotes, new_quotes, mid_prices

    print(f"\n📈 New update @ {data['timestamp']} | BRTI: {data['brti']:.2f} | Avg: {data['simple_average']:.2f}")
    total_unrealized = 0.0
    total_realized = 0.0
    market_quotes = {}
    for contract in data.get('contracts', []):

        ticker = contract.get('ticker', 'N/A')
        mm_bid = contract.get('mm_bid')
        mm_ask = contract.get('mm_ask')
        
        best_bid = contract.get('best_bid', mm_bid)
        best_ask = contract.get('best_ask', mm_ask)

        spread = contract.get('spread')
        mid_price = contract.get('mid_price')
        trades = contract.get('trades')
        trade_market = contract.get('trade_market', False)
        strike = contract.get('strike', 'N/A')

        strikes[ticker] = strike

        mid_prices[ticker] = mid_price

        time = contract.get("time_left_sec")
        # time in hours using datetime
        if time is not None:
            hours = time // 3600
            minutes = (time % 3600) // 60
            seconds = time % 60
            time_left = f"{hours:02}:{minutes:02}:{seconds:02}"
        else:
            time = None


        trades = trades.get('trades', [])

        market_quotes[ticker] = {
            'mm_bid': mm_bid,
            'mm_ask': mm_ask,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'spread': spread,
            'time_left': time_left,
        }

        print(f"🟩 {ticker} | Bid: {mm_bid} | Ask: {mm_ask} | Spread: {spread:.2f}")

        # Initialize trade tracking
        if ticker not in seen_trades:
            seen_trades[ticker] = {t['trade_id'] for t in trades}
            print(f"    🗃️ Registered {len(trades)} historical trades for {ticker}.")
            trades = []

        new_trades = [t for t in trades if t['trade_id'] not in seen_trades[ticker]]

        for trade in new_trades:
            if not(trade_market):
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
        if int(spread) <= 2:
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

        # === Compute PnL
        pos = positions[ticker]
        avg = avg_prices[ticker]
        if pos != 0:
            unreal = (mid_price - avg) * pos
            total_unrealized += unreal
        total_realized += realized_pnl[ticker]

    # print(f"\n📊 Positions:")
    for ticker in positions:
        pos = positions[ticker]
        if pos != 0:
            print(f"  {ticker.split("-")[-1]}: {pos} @ {avg_prices[ticker]:.2f}")

    print(f"💰 Realized PnL:   ${total_realized/100:.2f}")
    print(f"📈 Unrealized PnL: ${total_unrealized/100:.2f}")
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
        "our_quotes": our_quotes,
        "positions": dict(positions),
        "avg_prices": dict(avg_prices),
        "mid_prices": dict(mid_prices),
        "brti_60s_price" : data["simple_average"],
        "strikes": strikes,
        "realized_pnl": {k: v / 100 for k, v in realized_pnl.items()},
        "unrealized_pnl": total_unrealized,
        "cumulative_pnl": total_unrealized/100 + total_realized/100,
        "total_trades": total_trades,
        "expected_spread_pnl": dict(expected_spread_pnl),
        "total_expected_spread_pnl": total_expected_spread_pnl,
        "quotes": our_quotes,
        "trade_log": trade_log[-100:]
    })

def start_sio_client():
    sio.connect("http://localhost:5050", transports=["websocket"])
    sio.wait()

if __name__ == "__main__":
    # Start the client in a background thread
    threading.Thread(target=start_sio_client, daemon=True).start()

    # Start the Flask-SocketIO server
    socketio.run(app, host="127.0.0.1", port=5052)