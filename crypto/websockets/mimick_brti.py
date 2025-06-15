"""
BRTI-like Index via WebSocket order book subscriptions (ccxt.pro):
1. Use ccxt.pro to subscribe to top-of-book updates from each venue.
2. Maintain in-memory best bid/ask for each exchange.
3. Every POLL_INTERVAL, compute mid and weight from stored book.
4. Compute volume-weighted index without HTTP fetch overhead.
"""
import asyncio
import ccxt.pro as ccxt
import time

# Exchanges used in BRTI
EXCHANGES = [
    'gemini',
    'kraken',
    'coinbase',
    'cryptocom'
]
SYMBOL = 'BTC/USD'
POLL_INTERVAL = 0.5   # seconds between index updates

# Shared state for top-of-book
order_books: dict[str, dict[str, float]] = {}

async def subscribe_order_book(exchange_id: str, symbol: str):
    exchange = getattr(ccxt, exchange_id)({
        'enableRateLimit': True,
    })
    try:
        while True:
            book = await exchange.watch_order_book(symbol, limit=10)
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            if bids and asks:
                order_books[exchange_id] = {
                    'bid_price': bids[0][0],
                    'bid_qty': bids[0][1],
                    'ask_price': asks[0][0],
                    'ask_qty': asks[0][1],
                }
    except Exception as e:
        print(f"{exchange_id} WebSocket error: {e}")
    finally:
        await exchange.close()

async def compute_index():
    while True:
        start = time.perf_counter()
        weighted = []
        for ex_id, data in order_books.items():
            mid = (data['bid_price'] + data['ask_price']) / 2
            weight = data['bid_qty'] + data['ask_qty']
            weighted.append((mid, weight))
        if weighted:
            total_w = sum(w for _, w in weighted)
            index = sum(mid * w for mid, w in weighted) / total_w
            print(f"BRTI-like Index: {index:.2f}")
        elapsed = (time.perf_counter() - start) * 1000
        print(f"Loop duration: {elapsed:.1f}ms\n")
        await asyncio.sleep(max(0, POLL_INTERVAL - elapsed/1000))

async def main():
    # Launch all subscriptions
    tasks = [asyncio.create_task(subscribe_order_book(ex, SYMBOL)) for ex in EXCHANGES]
    # Launch index computation
    tasks.append(asyncio.create_task(compute_index()))
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    asyncio.run(main())
