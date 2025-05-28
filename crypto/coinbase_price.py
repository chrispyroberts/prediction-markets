import asyncio
import websockets
import hmac
import hashlib
import base64
import json
import os
import time
from dotenv import load_dotenv
import os

load_dotenv()

# === Replace with your credentials ===
ACCESS_KEY = os.getenv("MARKET_API_KEY")
SECRET_KEY = os.getenv("MARKET_API_SECRET")
PASSPHRASE = ""  # Coinbase Prime allows empty string
SIGN_PATH = "/users/self/verify"

# === Endpoint ===
WS_URL = "wss://ws-feed.exchange.coinbase.com"  # or prime.coinbase.com if using Prime

# === Signature helper ===
def generate_cb_signature(timestamp: str, method: str, path: str) -> str:
    message = f"{timestamp}{method}{path}"
    hmac_key = base64.b64decode(SECRET_KEY)
    signature = hmac.new(hmac_key, message.encode(), hashlib.sha256).digest()
    return base64.b64encode(signature).decode()

async def main():
    async with websockets.connect(WS_URL) as ws:
        print("✅ Connected to Coinbase WebSocket")

        timestamp = str(int(time.time()))
        signature = generate_cb_signature(timestamp, "GET", SIGN_PATH)

        # Auth + subscribe message
        subscribe_msg = {
            "type": "subscribe",
            "channels": [
                "level2",
                "heartbeat",
                {
                    "name": "ticker",
                    "product_ids": ["ETH-BTC", "ETH-USD"]
                }
            ],
            "signature": signature,
            "key": ACCESS_KEY,
            "passphrase": PASSPHRASE,
            "timestamp": timestamp
        }

        print("📨 Sending subscription...")
        await ws.send(json.dumps(subscribe_msg))

        while True:
            msg = await ws.recv()
            print("📥", msg)

if __name__ == "__main__":
    asyncio.run(main())
