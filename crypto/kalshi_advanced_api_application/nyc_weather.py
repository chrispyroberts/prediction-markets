from utils import get_orderbook, get_nyc_weather_market, submit_order, check_order_fill_status, cancel_order
import time

# Get the ticker of the market with the last trade closest to 50c
ticker = get_nyc_weather_market()

# Get the order book for this market
orderbook = get_orderbook(ticker)

if orderbook:
    bids = orderbook["bids"]
    asks = orderbook["asks"]
    
    print("\n=== Top Order Book ===")
    print("Ticker:", ticker)
    print(f"Bid $0.{bids[0]['price']} x {bids[0]['quantity']}")
    print(f"Ask $0.{asks[0]['price']} x {asks[0]['quantity']}")

    my_bid = min(bids[0]['price'] - 5, 1)
    my_ask = max(asks[0]['price'] + 5, 99)

    print(f"\nPlacing order: Bid $0.{my_bid} x 1", end=" ")
    response = submit_order(ticker, "buy", my_bid, 1)

    if response is None:
        print("❌ Failed to place order.", end = "")
    else:
        response = response['order']

        if response['status'] != 'resting':
            print("❌ Order was not placed successfully. Status:")
        else:
            print("✅ Order placed successfully!")

            # Print order id
            order_id = response.get("order_id", "N/A")

            print("Order ID:", order_id)
            print("Order Status:", response.get("status", "N/A"))
            print("Created at :", response.get("created_time", "N/A"))

            # wait for a few seconds to see if the order is filled, and then cancel if it isn't
            print("\nWaiting for 10 seconds to check order status...")
            time.sleep(10)
            print("Checking order status...", end=" ")

            is_filled, response = check_order_fill_status(order_id)
            if response is None:
                print("❌ Failed to check order status.")
            else:
                if is_filled:
                    print("✅ Order is filled!")
                else:
                    print("❌ Order is not filled, cancelling...", end =" ")
                    cancel_response = cancel_order(order_id)
                    if cancel_response is None:
                        print("❌ Failed to cancel order.")
                    else:
                        cancel_response = cancel_response['order']
                        if cancel_response['status'] != 'canceled':
                            print("❌ Order was not cancelled successfully. Status:", cancel_response['status'])
                        else:
                            print("✅ Order cancelled successfully!")
                    








    