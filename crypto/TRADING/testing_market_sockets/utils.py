import requests
import os
import time
import uuid
import json
import threading
import websocket
import ssl  
from typing import List, Dict

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import base64
from cryptography.exceptions import InvalidSignature

DEBUG = False  # Toggle this to False to disable all debug prints

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

def load_key_from_file(file_path):
    with open(file_path, "r") as f:
        key = f.read().strip()
    return key

USE_DEMO_API = True  # Set to False for production API 

# Load demo API key from .env
demo_private_key_path = ".private_key_demo"
demo_public_key_path = ".public_key_demo"
demo_url = 'https://demo-api.kalshi.co'

# Load production API key from .env
private_key_path = ".private_key"
public_key_path = ".public_key"
url = 'https://api.elections.kalshi.com'


# Comment out to make sure that we are using demo keys
# Load private key from .env
private_key_str = load_key_from_file(private_key_path.strip())
private_key_obj = serialization.load_pem_private_key(
    private_key_str.encode('utf-8'),
    password=None,
    backend=default_backend()
)

demo_private_key_str = load_key_from_file(demo_private_key_path.strip())
demo_private_key_obj = serialization.load_pem_private_key(
    demo_private_key_str.encode('utf-8'),
    password=None,
    backend=default_backend()
)

# Kalshi Public API Key ID
KALSHI_API_KEY_ID = load_key_from_file(public_key_path).strip()
DEMO_KALSHI_API_KEY_ID = load_key_from_file(demo_public_key_path).strip()

def get_current_event(series="KXBTC"):
    # default series is KXBTC
    url = f"https://api.elections.kalshi.com/trade-api/v2/events?status=open&series_ticker={series}"
    headers = {"accept": "application/json"}
    response = requests.get(url, headers=headers)
    data = response.json()

    # sort events by strike date
    data['events'].sort(key=lambda x: x['strike_date'])

    for event in data['events']:
        print(f"Event: {event['event_ticker']} Strike Date: {event['strike_date']}")

    # take first ticker 
    first_event = data['events'][0]
    print(f"First Event Ticker: {first_event['event_ticker']}")
    return first_event['event_ticker']

def get_markets_from_event(event):
    try:
        url = f"https://api.elections.kalshi.com/trade-api/v2/events/{event}"
        headers = {"accept": "application/json"}
        response = requests.get(url, headers=headers)
        res = json.loads(response.text)

        tickers = [market['ticker'] for market in res['markets']]

        return tickers    
        
    except Exception as e:
        print("❌ Error fetching markets:", e)
        return None

def get_orderbook(ticker):    
    try: 
        url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook"
        headers = {"accept": "application/json"}
        response = requests.get(url, headers=headers, timeout=5)

        data = response.json()
        order_book = data.get('orderbook', None)

        if order_book is None:
            debug_print("❌ Order book not found:", data)
            return None
        
        asks = []
        bids = []

        # YES side = bids
        for price, size in (order_book.get('yes') or []):
            bids.append({'price': price, 'quantity': size})

        # NO side = asks (flip to YES terms)
        for price, size in (order_book.get('no') or []):
            asks.append({'price': 100 - price, 'quantity': size})

        # Sort: best prices first
        sorted_bids = sorted(bids, key=lambda x: -x["price"])  # High to low
        sorted_asks = sorted(asks, key=lambda x: x["price"])   # Low to high

        # debug_print top levels
        top_bid = sorted_bids[0] if sorted_bids else None
        top_ask = sorted_asks[0] if sorted_asks else None
        debug_print(f"UTILS: Top Bid: {top_bid}")
        debug_print(f"UTILS: Top Ask: {top_ask}")

        return {"bids": sorted_bids, "asks": sorted_asks}
    
    except Exception as e:
        debug_print("UTILS: ❌ Error fetching orderbook:", e)
        return None

def place_order(ticker, price, quantity, side="yes"):
    """
    Places a limit order on the Kalshi market.
    
    :param ticker: Market ticker
    :param side: 'yes' or 'no' side of the market
    :param price: Price in cents for the chosen side
    :param quantity: Number of contracts to buy/sell
    :return: Order ID if successful, None otherwise
    """
    url = "https://api.elections.kalshi.com/trade-api/v2/portfolio/orders"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {os.getenv('KALSHI_API_KEY')}",
        "Content-Type": "application/json"
    }

    # Generate a unique client_order_id
    client_order_id = f"my_order_{int(time.time())}_{uuid.uuid4().hex[:8]}"

    payload = {
        "ticker": ticker,
        "action": "buy",               # 'buy' or 'sell'
        "side": side,                  # 'yes' or 'no'
        "type": "limit",               # only 'limit' supported with price
        "count": quantity,
        "client_order_id": client_order_id,
        "time_in_force": "fill_or_kill",  # or leave out for GTC via expiration_ts
        "post_only": False,
    }

    # Either yes_price or no_price (in cents)
    if side == "yes":
        payload["yes_price"] = price
    else:
        payload["no_price"] = price

    # Send the request
    response = requests.post(url, headers=headers, json=payload, timeout=5)

    if response.status_code == 201:
        order = response.json().get("order", {})
        debug_print("UTILS: ✅ Order placed successfully:")
        debug_print(f"UTILS: Order ID: {order['order_id']}")
        debug_print(f"UTILS: Status: {order['status']}")
        return order["order_id"]
    else:
        debug_print("UTILS: ❌ Failed to place order:", response.status_code, response.text)
        return None

def sign_pss_text(private_key: rsa.RSAPrivateKey, text: str) -> str:
    message = text.encode('utf-8')
    try:
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    except InvalidSignature as e:
        raise ValueError("RSA sign PSS failed") from e
    
def kalshi_signed_request(method, path, private_key, key_id, base_url, params=None, body=None):
    # 1️⃣ Get timestamp
    current_time_milliseconds = int(time.time() * 1000)
    timestamp_str = str(current_time_milliseconds)

    # 2️⃣ Generate signature
    msg_string = timestamp_str + method.upper() + path
    signature = sign_pss_text(private_key, msg_string)

    # 3️⃣ Build headers
    headers = {
        'KALSHI-ACCESS-KEY': key_id,
        'KALSHI-ACCESS-SIGNATURE': signature,
        'KALSHI-ACCESS-TIMESTAMP': timestamp_str,
        'accept': 'application/json'
    }

    # 4️⃣ Prepare request
    url = base_url + path
    if body:
        headers['Content-Type'] = 'application/json'

    response = requests.request(
        method=method.upper(),
        url=url,
        headers=headers,
        params=params,
        json=body,
        timeout=5
    )

    return response

def submit_order(ticker, action, quantity, price, demo=True):
    """
    Fully self-contained helper:
    - Loads private key from .env
    - Places a signed limit order for the YES side
    - action: "buy" or "sell"

    :param ticker: Market ticker
    :param action: "buy" or "sell"
    :param quantity: Number of contracts
    :param price: Price in cents
    """
    # Prepare order body (always for YES side)
    path = "/trade-api/v2/portfolio/orders"
    body = {
        "ticker": ticker,
        "action": action,          # "buy" or "sell"
        "side": "yes",             # always "yes"
        "type": "limit",
        "count": quantity,
        "client_order_id": f"order_{int(time.time())}_{uuid.uuid4().hex[:8]}",
        "yes_price": price
    }

    if demo:
        private_key = demo_private_key_obj
        key_id = DEMO_KALSHI_API_KEY_ID
        base_url = demo_url
    else: 
        pass
        # private_key = private_key_obj
        # key_id = KALSHI_API_KEY_ID
        # base_url = url

    # Submit signed request
    response = kalshi_signed_request(
        method="POST",
        path=path,
        private_key=private_key,
        key_id=key_id,
        base_url=base_url,
        body=body
    )

    # debug_print response
    # debug_print("UTILS: Status Code:", response.status_code)
    try:
        if response.status_code != 201:
            debug_print("UTILS: ❌ Failed to place order. Status code:", response.status_code)
            return None
        else:
            return response.json()
        
    except Exception:
        debug_print("UTILS: ❌ Response parsing error:", response.text)
        return None
    
def check_order_fill_status(order_id, demo=True):
    """
    Checks if a given order_id has any fills.
    
    :param order_id: The ID of the order to check
    :return: True if the order has fills, False otherwise
    """
    path = f"/trade-api/v2/portfolio/fills" 
    params = {
        "order_id": order_id,
        "limit": 1  # Only need to check for existence
    }

    if demo:
        private_key = demo_private_key_obj
        key_id = DEMO_KALSHI_API_KEY_ID
        base_url = demo_url
    else:
        pass
        # private_key = private_key_obj
        # key_id = KALSHI_API_KEY_ID
        # base_url = url

    # Submit signed request
    response = kalshi_signed_request(
        method="GET",
        path=path,
        private_key=private_key,
        key_id=key_id,
        base_url=base_url,
        body=None,  # GET requests do not send a body
        params=params
    )

    if response.status_code == 200:
        # debug_print("UTILS: Status Code: 200")
        fills_data = response.json().get("fills", [])
        if fills_data:
            return True, response.json()
        else:
            return False, response.json()
    else:
        debug_print(f"UTILS: ❌ Failed to check fills for order {order_id}. Status code:", response.status_code)
        debug_print("UTILS: ❌ Response:", response.text)
        return None, None

def cancel_order(order_id, demo=True):
    """
    Fully self-contained helper:
    - Cancels an existing order by order_id
    - Uses Kalshi’s signed DELETE request

    :param order_id: The ID of the order to cancel
    """
    # Endpoint for cancelling an order
    path = f"/trade-api/v2/portfolio/orders/{order_id}"


    if demo:
        private_key = demo_private_key_obj
        key_id = DEMO_KALSHI_API_KEY_ID
        base_url = demo_url
    else:
        pass 
        # private_key_obj = private_key_obj
        # key_id = KALSHI_API_KEY_ID
        # base_url = url

    # Submit signed request (DELETE)
    response = kalshi_signed_request(
        method="DELETE",
        path=path,
        private_key=private_key,
        key_id=key_id,
        base_url=base_url,
        body=None
    )

    # debug_print response
    # debug_print("UTILS: Status Code:", response.status_code)

    try:
        if response.status_code != 200:
            debug_print("UTILS: ERROR CANCELLING ORDER:", response.text)
            return None
        else:
            return response.json()
    
    except Exception:
        debug_print("UTILS: ❌ Response parsing error:", response.text)
        return None

def test_authentication(demo=True):
    """Test if authentication is working by making a simple authenticated request"""
    try:
        if demo:
            private_key = demo_private_key_obj
            key_id = DEMO_KALSHI_API_KEY_ID
            base_url_test = demo_url
        else:
            private_key = private_key_obj
            key_id = KALSHI_API_KEY_ID
            base_url_test = url
        
        # Try to get account balance (simple authenticated endpoint)
        path = "/trade-api/v2/portfolio/balance"
        
        response = kalshi_signed_request(
            method="GET",
            path=path,
            private_key=private_key,
            key_id=key_id,
            base_url=base_url_test
        )
        
        print(f"Auth test status code: {response.status_code}")
        print(f"Auth test response: {response.text}")
        
        if response.status_code == 200:
            print("✅ Authentication working!")
            return True
        else:
            print("❌ Authentication failed!")
            return False
            
    except Exception as e:
        print(f"❌ Authentication test error: {e}")
        return False

def cancel_all_orders(demo=True):
    """
    Cancel all active orders for the account.
    
    :param demo: Whether to use demo API or production
    :return: Dictionary with cancellation results
    """
    try:
        # Step 1: Get all active orders
        debug_print("🔍 Fetching all active orders...")
        
        path = "/trade-api/v2/portfolio/orders"
        params = {
            "status": "resting"  # Only get open/active orders
        }

        if demo:
            private_key = demo_private_key_obj
            key_id = DEMO_KALSHI_API_KEY_ID
            base_url = demo_url
        else:
            pass
            # private_key = private_key_obj
            # key_id = KALSHI_API_KEY_ID
            # base_url = url

        # Get all orders
        response = kalshi_signed_request(
            method="GET",
            path=path,
            private_key=private_key,
            key_id=key_id,
            base_url=base_url,
            params=params
        )

        if response.status_code != 200:
            debug_print(f"❌ Failed to fetch orders. Status: {response.status_code}")
            debug_print(f"❌ Response: {response.text}")
            return {
                'success': False, 
                'error': f'Failed to fetch orders: {response.status_code}',
                'cancelled_count': 0,
                'failed_count': 0
            }

        orders_data = response.json()
        orders = orders_data.get('orders', [])
        
        if not orders:
            debug_print("✅ No active orders found to cancel")
            return {
                'success': True,
                'message': 'No active orders to cancel',
                'cancelled_count': 0,
                'failed_count': 0
            }

        debug_print(f"📋 Found {len(orders)} active orders to cancel")

        # Step 2: Cancel each order
        cancelled_count = 0
        failed_count = 0
        cancellation_results = []

        for order in orders:
            order_id = order.get('order_id')
            ticker = order.get('ticker', 'Unknown')
            side = order.get('side', 'Unknown')
            price = order.get('yes_price') or order.get('no_price', 'Unknown')
            
            if not order_id:
                debug_print(f"❌ Order missing order_id: {order}")
                failed_count += 1
                continue

            debug_print(f"❌ Cancelling order {order_id}: {ticker} {side} @ {price}")
            
            try:
                cancel_response = cancel_order(order_id, demo=demo)
                
                if cancel_response:
                    debug_print(f"✅ Successfully cancelled order {order_id}")
                    cancelled_count += 1
                    cancellation_results.append({
                        'order_id': order_id,
                        'ticker': ticker,
                        'side': side,
                        'price': price,
                        'status': 'cancelled'
                    })
                else:
                    debug_print(f"❌ Failed to cancel order {order_id}")
                    failed_count += 1
                    cancellation_results.append({
                        'order_id': order_id,
                        'ticker': ticker,
                        'side': side,
                        'price': price,
                        'status': 'failed'
                    })
                    
            except Exception as e:
                debug_print(f"❌ Exception cancelling order {order_id}: {e}")
                failed_count += 1
                cancellation_results.append({
                    'order_id': order_id,
                    'ticker': ticker,
                    'side': side,
                    'price': price,
                    'status': 'error',
                    'error': str(e)
                })

        # Step 3: Return summary
        result = {
            'success': True,
            'total_orders': len(orders),
            'cancelled_count': cancelled_count,
            'failed_count': failed_count,
            'cancellation_results': cancellation_results
        }

        debug_print(f"📊 Cancellation Summary:")
        debug_print(f"   Total orders: {len(orders)}")
        debug_print(f"   Successfully cancelled: {cancelled_count}")
        debug_print(f"   Failed to cancel: {failed_count}")

        return result

    except Exception as e:
        debug_print(f"❌ Error in cancel_all_orders: {e}")
        return {
            'success': False,
            'error': str(e),
            'cancelled_count': 0,
            'failed_count': 0
        }

def get_all_orders(demo=True, status="resting"):
    """
    Get all orders for the account.
    
    :param demo: Whether to use demo API or production
    :param status: Order status filter ('open', 'filled', 'canceled', etc.)
    :return: List of orders or None if error
    """
    try:
        debug_print(f"🔍 Fetching all {status} orders...")
        
        path = '/trade-api/v2/portfolio/orders?status={status}'
        params = {}
        
        if demo:
            private_key = demo_private_key_obj
            key_id = DEMO_KALSHI_API_KEY_ID
            base_url = demo_url
        else:
            pass
            # private_key = private_key_obj
            # key_id = KALSHI_API_KEY_ID
            # base_url = url

        response = kalshi_signed_request(
            method="GET",
            path=path,
            private_key=private_key,
            key_id=key_id,
            url=base_url,
            params=params
        )

        if response.status_code == 200:
            orders_data = response.json()
            orders = orders_data.get('orders', [])
            debug_print(f"✅ Retrieved {len(orders)} {status} orders")
            return orders
        else:
            debug_print(f"❌ Failed to fetch orders. Status: {response.status_code}")
            debug_print(f"❌ Response: {response.text}")
            return None

    except Exception as e:
        debug_print(f"❌ Error fetching orders: {e}")
        return None

def batch_create_orders(order_specs: List[Dict], demo=True) -> Dict:
    """
    Create multiple orders using Kalshi's batch API.
    
    :param order_specs: List of order specifications, each containing:
                       - ticker: str
                       - action: 'buy' or 'sell'
                       - price: int (in cents)
                       - quantity: int
                       - side: 'bid' or 'ask' (used for tracking)
    :param demo: Whether to use demo API
    :return: Response dictionary with success status and order data
    """
    if not order_specs:
        return {'success': True, 'orders': []}
    
    try:
        # Prepare the batch order request
        path = "/trade-api/v2/portfolio/orders/batched"
        
        # Convert our order specs to Kalshi's format
        orders_payload = []
        for spec in order_specs:
            order_payload = {
                "ticker": spec['ticker'],
                "action": spec['action'],  # 'buy' or 'sell'
                "side": "yes",  # Always trade YES side
                "type": "limit",
                "count": spec['quantity'],
                "client_order_id": f"batch_order_{int(time.time())}_{uuid.uuid4().hex[:8]}",
                "yes_price": spec['price'],
                "post_only": False  # Allow crossing the spread
            }
            orders_payload.append(order_payload)
        
        body = {"orders": orders_payload}
        
        # Choose API endpoint based on demo flag
        if demo:
            private_key = demo_private_key_obj
            key_id = DEMO_KALSHI_API_KEY_ID
            base_url = demo_url
        else:
            pass
            # private_key = private_key_obj
            # key_id = KALSHI_API_KEY_ID
            # base_url = url
        
        # Submit signed request
        response = kalshi_signed_request(
            method="POST",
            path=path,
            private_key=private_key,
            key_id=key_id,
            base_url=base_url,
            body=body
        )
        
        debug_print(f"UTILS: Batch create status code: {response.status_code}")
        
        if response.status_code == 201:
            response_data = response.json()
            orders = response_data.get('orders', [])
            
            debug_print(f"UTILS: ✅ Batch created {len(orders)} orders successfully")
            
            return {
                'success': True,
                'orders': orders,
                'total_created': len(orders)
            }
        else:
            debug_print(f"UTILS: ❌ Batch create failed: {response.status_code}")
            debug_print(f"UTILS: Response: {response.text}")
            return {
                'success': False,
                'error': f"HTTP {response.status_code}: {response.text}",
                'orders': []
            }
            
    except Exception as e:
        debug_print(f"UTILS: ❌ Exception in batch_create_orders: {e}")
        return {
            'success': False,
            'error': str(e),
            'orders': []
        }

def batch_cancel_orders(order_ids: List[str], demo=True) -> Dict:
    """
    Cancel multiple orders using Kalshi's batch API.
    
    :param order_ids: List of order IDs to cancel
    :param demo: Whether to use demo API
    :return: Response dictionary with success status
    """
    if not order_ids:
        return {'success': True, 'cancelled_count': 0}
    
    try:
        # Prepare the batch cancel request
        path = "/trade-api/v2/portfolio/orders/batched"
        body = {"ids": order_ids}
        
        # Choose API endpoint based on demo flag
        if demo:
            private_key = demo_private_key_obj
            key_id = DEMO_KALSHI_API_KEY_ID
            base_url = demo_url
        else:
            private_key = private_key_obj
            key_id = KALSHI_API_KEY_ID
            base_url = url
        
        # Submit signed DELETE request
        response = kalshi_signed_request(
            method="DELETE",
            path=path,
            private_key=private_key,
            key_id=key_id,
            base_url=base_url,
            body=body
        )
        
        debug_print(f"UTILS: Batch cancel status code: {response.status_code}")
        
        if response.status_code == 200:
            response_data = response.json()
            
            debug_print(f"UTILS: ✅ Batch cancelled {len(order_ids)} orders successfully")
            
            return {
                'success': True,
                'cancelled_count': len(order_ids),
                'response_data': response_data
            }
        else:
            debug_print(f"UTILS: ❌ Batch cancel failed: {response.status_code}")
            debug_print(f"UTILS: Response: {response.text}")
            return {
                'success': False,
                'error': f"HTTP {response.status_code}: {response.text}",
                'cancelled_count': 0
            }
            
    except Exception as e:
        debug_print(f"UTILS: ❌ Exception in batch_cancel_orders: {e}")
        return {
            'success': False,
            'error': str(e),
            'cancelled_count': 0
        }

def test_batch_apis(demo=True):
    """
    Test the batch APIs with a simple order create and cancel.
    """
    try:
        debug_print("🧪 Testing batch APIs...")
        
        # Test batch create with a simple order
        test_order_specs = [{
            'ticker': 'KXBTC-25JUN1615-B113625',  # Replace with a valid ticker
            'action': 'buy',
            'price': 10,  # Low price unlikely to fill
            'quantity': 1,
            'side': 'bid'
        }]
        
        # Create order
        create_response = batch_create_orders(test_order_specs, demo=demo)
        debug_print(f"Create response: {create_response}")
        
        if create_response['success'] and create_response['orders']:
            order_id = create_response['orders'][0]['order_id']
            debug_print(f"✅ Created test order: {order_id}")
            
            # Wait a moment
            time.sleep(1)
            
            # Cancel order
            cancel_response = batch_cancel_orders([order_id], demo=demo)
            debug_print(f"Cancel response: {cancel_response}")
            
            if cancel_response['success']:
                debug_print("✅ Batch APIs working correctly!")
                return True
            else:
                debug_print("❌ Batch cancel failed")
                return False
        else:
            debug_print("❌ Batch create failed")
            return False
            
    except Exception as e:
        debug_print(f"❌ Error testing batch APIs: {e}")
        return False

def start_kalshi_ws_client(market_ticker):
    """
    Starts a robust websocket client to stream real-time orderbook updates
    for a given Kalshi market.

    :param market_ticker: The ticker of the market to subscribe to.
    """
    ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    last_seq = 0  # Track last seq to detect gaps
    print(f"🔗 Connecting to Kalshi WebSocket for market: {market_ticker}...")

    def on_message(ws, message):
        nonlocal last_seq
        print("🟢 Received a message!")  # NEW
        data = json.loads(message)
        msg_type = data.get("type")

        if msg_type == "orderbook_snapshot":
            print("\n📊 Received snapshot:")
            debug_print(json.dumps(data["msg"], indent=2))
            last_seq = data["seq"]
        elif msg_type == "orderbook_delta":
            seq = data["seq"]
            if seq != last_seq + 1:
                print("⚠️ Sequence gap detected! Reconnecting...")
                ws.close()  # Force reconnect
                return
            last_seq = seq
            print("📈 Delta update:")
            debug_print(json.dumps(data["msg"], indent=2))
        elif msg_type == "subscribed":
            print("✅ Subscribed to channel:", data["msg"]["channel"])
        elif msg_type == "error":
            print("❌ WebSocket error:", data)
        else:
            print("ℹ️ Other message:", data)

    def on_error(ws, error):
        print("❌ WebSocket encountered an error:", error)

    def on_close(ws, close_status_code, close_msg):
        print("🔌 WebSocket closed. Code:", close_status_code, "Message:", close_msg)
        print("🔄 Reconnecting in 3 seconds...")
        time.sleep(3)
        start_kalshi_ws_client(market_ticker)

    def on_open(ws):
        print("🟢 WebSocket connection established! Sending subscription...")
        subscribe_cmd = {
            "id": 1,
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": [market_ticker]
            }
        }
        ws.send(json.dumps(subscribe_cmd))

    def get_auth_headers(method, path):
        timestamp_ms = str(int(time.time() * 1000))
        msg_string = timestamp_ms + method.upper() + path
        signature = sign_pss_text(private_key_obj, msg_string)
        return {
            "KALSHI-ACCESS-KEY": KALSHI_API_KEY_ID,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms
        }

    headers = get_auth_headers("GET", "/trade-api/ws/v2")
    print("🔐 Prepared authentication headers.")  # NEW

    ws_app = websocket.WebSocketApp(
        ws_url,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    # Launch in a dedicated thread
    thread = threading.Thread(
        target=ws_app.run_forever,
        kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}, "ping_interval": 10, "ping_timeout": 5}
    )
    thread.daemon = True  # Keep running until main process ends
    thread.start()
    print("🚀 WebSocket thread started.")  # NEW
    # Wait a moment to let the connection settle
    time.sleep(2)
    print("🔍 Checking if WebSocket is alive:", ws_app.sock and ws_app.sock.connected)