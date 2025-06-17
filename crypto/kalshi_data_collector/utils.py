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

DEBUG = True  # Toggle this to False to disable all debug prints

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

def load_key_from_file(file_path):
    with open(file_path, "r") as f:
        key = f.read().strip()
    return key

USE_DEMO_API = False  # Set to False for production API 

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