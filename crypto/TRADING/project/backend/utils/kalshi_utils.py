import requests
import time
import json
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
import base64
from cryptography.exceptions import InvalidSignature

def load_key_from_file(file_path):
    """Load key from file"""
    with open(file_path, "r") as f:
        key = f.read().strip()
    return key

# Load API keys
private_key_path = "backend/feeds/.private_key"
public_key_path = "backend/feeds/.public_key"

private_key_str = load_key_from_file(private_key_path.strip())
private_key_obj = serialization.load_pem_private_key(
    private_key_str.encode('utf-8'),
    password=None,
    backend=default_backend()
)

KALSHI_API_KEY_ID = load_key_from_file(public_key_path).strip()

def get_current_event(series="KXBTCD"):
    """Get current event ticker"""
    url = f"https://api.elections.kalshi.com/trade-api/v2/events?status=open&series_ticker={series}"
    headers = {"accept": "application/json"}
    response = requests.get(url, headers=headers)
    data = response.json()

    # Sort events by strike date
    data['events'].sort(key=lambda x: x['strike_date'])

    # Take first ticker 
    first_event = data['events'][0]
    return first_event['event_ticker']

def get_markets_from_event(event):
    """Get market tickers from event"""
    try:
        url = f"https://api.elections.kalshi.com/trade-api/v2/events/{event}"
        headers = {"accept": "application/json"}
        response = requests.get(url, headers=headers)
        res = json.loads(response.text)

        tickers = [market['ticker'] for market in res['markets']]
        return tickers    
        
    except Exception as e:
        print("Error fetching markets:", e)
        return None

def sign_pss_text(private_key: rsa.RSAPrivateKey, text: str) -> str:
    """Sign text using RSA PSS"""
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

def test_authentication():
    """Test if authentication is working"""
    try:
        # Try to get account balance (simple authenticated endpoint)
        path = "/trade-api/v2/portfolio/balance"
        
        # Generate timestamp and signature
        timestamp_ms = str(int(time.time() * 1000))
        msg_string = timestamp_ms + "GET" + path
        signature = sign_pss_text(private_key_obj, msg_string)
        
        # Build headers
        headers = {
            'KALSHI-ACCESS-KEY': KALSHI_API_KEY_ID,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp_ms,
            'accept': 'application/json'
        }
        
        url = f"https://api.elections.kalshi.com{path}"
        response = requests.get(url, headers=headers, timeout=5)
        
        return response.status_code == 200
            
    except Exception as e:
        print(f"Authentication test error: {e}")
        return False 