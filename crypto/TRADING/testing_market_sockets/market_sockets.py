import asyncio
import websockets
import json
import time
from testing_market_sockets.utils import sign_pss_text, private_key_obj, KALSHI_API_KEY_ID, get_current_event, get_markets_from_event

DEBUG = False

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

async def kalshi_ws_stream(market_tickers):
    ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"

    # 1️⃣ Generate timestamp & signature
    timestamp_ms = str(int(time.time() * 1000))
    msg_string = timestamp_ms + "GET" + "/trade-api/ws/v2"
    signature = sign_pss_text(private_key_obj, msg_string)

    # 2️⃣ Build headers
    headers = {
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature
    }

    # Initialize state
    orderbooks = {ticker: {"yes": {}, "no": {}} for ticker in market_tickers}
    trades = {ticker: [] for ticker in market_tickers}
    fills = {ticker: [] for ticker in market_tickers}

    # 3️⃣ Maintain separate last_seq for each channel
    last_seq = {
        "orderbook_delta": 0,
        "trade": 0,
        "fill": 0
    }

    try:
        async with websockets.connect(ws_url, extra_headers=headers, ping_interval=10, ping_timeout=5) as ws:
            print("✅ WebSocket connected!")

            # 4️⃣ Subscribe to orderbook_delta
            await ws.send(json.dumps({
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": market_tickers
                }
            }))
            print("📡 Subscribed to orderbook_delta.")

            # 5️⃣ Subscribe to trade
            await ws.send(json.dumps({
                "id": 2,
                "cmd": "subscribe",
                "params": {
                    "channels": ["trade"],
                    "market_tickers": market_tickers
                }
            }))
            print("📡 Subscribed to trade.")

            # 6️⃣ Subscribe to fill
            await ws.send(json.dumps({
                "id": 3,
                "cmd": "subscribe",
                "params": {
                    "channels": ["fill"],
                    "market_tickers": market_tickers
                }
            }))
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
                    debug_print("ℹ️ Other message:", data)
                    continue

                ticker = msg.get("market_ticker")

                # 🔴 Check sequence gaps per channel per market
                if ticker:
                    prev_seq = last_seq[channel]
                    if prev_seq != 0 and seq != prev_seq + 1:
                        print(f"⚠️ Sequence gap on {channel}! Got {seq}, expected {prev_seq+1}. Reconnecting.")
                        raise Exception("Sequence gap")
                    last_seq[channel] = seq

                if msg_type == "orderbook_snapshot":
                    orderbooks[ticker]["yes"] = {price: qty for price, qty in msg.get("yes", [])}
                    orderbooks[ticker]["no"] = {price: qty for price, qty in msg.get("no", [])}
                    debug_print(f"✅ Snapshot for {ticker}.")
                elif msg_type == "orderbook_delta":
                    side = msg["side"]
                    price = msg["price"]
                    change = msg["delta"]
                    qty = orderbooks[ticker][side].get(price, 0) + change
                    if qty <= 0:
                        orderbooks[ticker][side].pop(price, None)
                    else:
                        orderbooks[ticker][side][price] = qty
                    debug_print(f"📈 Delta for {ticker}: {msg}")
                elif msg_type == "trade":
                    trades[ticker].append(msg)
                    if msg["taker_side"] == "yes":
                        side = "Buy"
                    else:
                        side= "Sell"
                    print(f"💹 Trade on {ticker}: {side} {msg['count']} contracts at {msg['yes_price']} @ {msg['ts']}")

                elif msg_type == "fill":
                    fills[ticker].append(msg)
                    print(f"💰 Fill on {ticker}: {msg['count']} contracts at {msg['yes_price']} ({msg['side']}) by {msg['action']} @ {msg['ts']}")

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
    asyncio.run(start_ws_client(market_ticker))
