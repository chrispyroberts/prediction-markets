import socketio
from collections import defaultdict

sio = socketio.Client()

# Store last known bid/ask per contract
previous_quotes = {}
our_quotes = {} # current quotes we are proposing

# Global dictionary to track seen trades by contract
seen_trades = {}

trade_log = []  # List of trade events with per-trade realized pnl
cumulative_pnl = defaultdict(float)  # Running realized + unrealized pnl per contract

# === Config ===
SIZING = 10
total_trades = 0
expected_spread_pnl = defaultdict(float)  # per ticker
total_expected_spread_pnl = 0.0

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

@sio.on('brti_and_options_update')
def handle_update(data):
    global total_trades, expected_spread_pnl, total_expected_spread_pnl

    print(f"\n📈 New update @ {data['timestamp']} | BRTI: {data['brti']:.2f} | Avg: {data['simple_average']:.2f}")
    total_unrealized = 0.0
    total_realized = 0.0

    for contract in data.get('contracts', []):
        ticker = contract.get('ticker', 'N/A')
        mm_bid = contract.get('mm_bid')
        mm_ask = contract.get('mm_ask')
        
        best_bid = contract.get('best_bid', mm_bid)
        best_ask = contract.get('best_ask', mm_ask)

        spread = contract.get('spread')
        mid_price = contract.get('mid_price')
        trades = contract.get('trades')

        trades = trades.get('trades', [])

        tick = ticker.split('-')[-1]

        print(f"🟩 {tick} | Bid: {mm_bid} | Ask: {mm_ask} | Spread: {spread:.2f}")

        # Initialize trade tracking
        if ticker not in seen_trades:
            seen_trades[ticker] = {t['trade_id'] for t in trades}
            print(f"    🗃️ Registered {len(trades)} historical trades for {ticker}.")
            trades = []

        new_trades = [t for t in trades if t['trade_id'] not in seen_trades[ticker]]

        for trade in new_trades:
            print(f"    🟢 New trade: {trade['count']} contracts @ {trade['yes_price']}  [TAKER: {trade['taker_side']}]")
            trade_id = trade['trade_id']
            seen_trades[ticker].add(trade_id)

            price = trade['yes_price']
            taker_side = trade['taker_side']
            count = min(trade['count'], SIZING)

            # Use our previously stored quotes
            our_quote = our_quotes.get(ticker)

            if not our_quote or our_quote['bid'] is None or our_quote['ask'] is None:
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
                    spread = our_ask - our_bid if our_bid is not None and our_ask is not None else 0
                    spread_edge = (spread / 100.0) / 2 * filled  # convert cents to dollars

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
            'ask': new_ask
        }
        if new_bid is not None and new_ask is not None:
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

sio.connect("http://localhost:5050", transports=["websocket"])
sio.wait()


@app.route('/')
def hello():
    return "Live trading server running."

if __name__ == '__main__':
    socketio.run(app, host="127.0.0.1", port=5052)