# utils.py
import requests
import random
import time
import json
from datetime import datetime, timezone

from scipy.stats import norm
from scipy.optimize import brentq
import numpy as np

session = requests.Session()

USE_YEARS = True  # Set to True if you want to use years for TTE, False for hours
MM_THRESHOLD = 300  # Threshold for market maker detection

def get_current_event_ticker():
    url = "https://api.elections.kalshi.com/trade-api/v2/events?status=open&series_ticker=KXBTC"
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

def get_brti_price():
    try:
        response = session.get("http://localhost:5000/price", timeout=0.2)
        if response.status_code == 200:
            data = response.json()
            return data['brti'], data['simple_average'], data['timestamp']
        else:
            print("⚠️ Server responded with:", response.status_code)
            return None, None, None
    except requests.exceptions.RequestException as e:
        print("❌ Error fetching price:", e)
        return None, None, None

def get_market_data(ticker):
    url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
    headers = {"accept": "application/json"}
    response = requests.get(url, headers=headers)

    market = json.loads(response.text)['market']
    
    # Expiration time in strict ISO 8601 format (UTC)
    expiration_time_str = market['expected_expiration_time']
    expiration_time = datetime.fromisoformat(expiration_time_str.replace('Z', '+00:00'))
    now_local = datetime.now().astimezone()
    now_utc = now_local.astimezone(timezone.utc)
    time_left = expiration_time - now_utc    
    total_seconds = int(time_left.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60


    tte = f"{hours:02}:{minutes:02}:{seconds:02}"
    interest = market['open_interest']
    strike = int(round(market['floor_strike'], 0))
    best_bid = market['yes_bid']
    best_ask = 100-market['no_bid']

    data = {
        'ticker': ticker,
        'expiration_time': expiration_time_str,
        'time_left': tte,
        'interest': interest,
        'strike': strike,
        'best_bid': best_bid,
        'best_ask': best_ask
    }
    return data

def get_orderbook(ticker):    
    try: 
        url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook"
        headers = {"accept": "application/json"}
        response = requests.get(url, headers=headers)

        order_book = json.loads(response.text).get('orderbook', None)

        if order_book is None:
            print(response.text)
            return None, None, None, None, None
        
        asks = []
        bids = []

        if order_book['yes']:
            for price, size in order_book['yes']:
                bids.append({'price': price, 'quantity': size})
        if order_book['no']:
            for price, size in order_book['no']:
                asks.append({'price': (100-price), 'quantity': size})
        
        sorted_bids = sorted(bids, key=lambda x: -x["price"])  # High to low
        sorted_asks = sorted(asks, key=lambda x: x["price"])   # Low to high


        top_ask = sorted_asks[0]['price'] if len(asks) > 0 else 100
        top_bid = sorted_bids[0]['price'] if len(bids) > 0 else 0

        # identify bids and asks mad eby marketmakers
        mm_bids = list(filter(lambda x: x['quantity'] >= MM_THRESHOLD, sorted_bids))
        mm_asks = list(filter(lambda x: x['quantity'] >= MM_THRESHOLD, sorted_asks))

        mm_bid = mm_bids[0]['price'] if len(mm_bids) > 0 else 0
        mm_ask = mm_asks[0]['price'] if len(mm_asks) > 0 else 100

        orderbook = (sorted_bids, sorted_asks)

        return orderbook, top_ask, top_bid, mm_bid, mm_ask  
    
    except Exception as e:
        print("❌ Error fetching orderbook:", e)
        return None, None, None, None, None

def binary_call_price(S, K, T_hours, sigma, r=0.0):
    T = T_hours / (365 * 24)  # Convert hours to years
    d2 = (np.log(S / K) + (r - 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    price = np.exp(-r * T) * norm.cdf(d2)
    return price

def one_touch_up_price(S, K, T, sigma, r=0.0):
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return np.nan  # sanity check for inputs

    # Calculate parameters
    lambda_ = (r / sigma**2) + 0.5
    d1_prime = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2_prime = (np.log(S / K) + (r - 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    
    # One-touch price
    term1 = (S / K) ** (2 * lambda_) * norm.cdf(d1_prime)
    term2 = norm.cdf(d2_prime)
    
    price = np.exp(-r * T) * (term1 + term2)
    
    return price

def implied_vol_one_touch(S, K, T_hours, market_price, r=0.0, sigma_lower=1e-6, sigma_upper=50.0):
    
    if USE_YEARS:
        # Convert t_hours to years
        T_hours = T_hours / (365 * 24)

    def objective(sigma):
        model_price = one_touch_up_price(S, K, T_hours, sigma, r)
        return model_price - market_price

    try:
        implied_vol = brentq(objective, sigma_lower, sigma_upper, xtol=1e-6)
        return implied_vol
    except ValueError:
        return np.nan  # No solution found

def binary_call_delta(S, K, T_hours, sigma, r=0.0):
    """
    Computes the delta of a European binary call option.

    Parameters:
    - S: Spot price
    - K: Strike price
    - T_hours: Time to expiration in hours
    - sigma: Volatility (annualized, decimal)
    - r: Risk-free rate (default 0)

    Returns:
    - Delta of the binary call option
    """
    if USE_YEARS:
        T = T_hours / (365 * 24)
    else:
        T = T_hours / 24  # fallback if hours are used directly

    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return np.nan

    d2 = (np.log(S / K) + (r - 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    delta = (np.exp(-r * T) * norm.pdf(d2)) / (S * sigma * np.sqrt(T))
    return delta

# Function to solve: theoretical price - market price = 0
def implied_vol_binary_call(S, K, T_hours, market_price, r=0.0):

    if USE_YEARS:
        # Convert t_hours to years
        T_hours = T_hours / (365 * 24)  # Convert hours to years

    def objective(sigma):
        return binary_call_price(S, K, T_hours, sigma, r) - market_price

    try:
        return brentq(objective, 1e-6, 200.0, xtol=0.01)  # Search for sigma in [0.001, 500%]
    except ValueError:
        return np.nan  # No solution found in the interval

def get_moneyness(S, K, T_hours):
    # convert T_hours to years
    if USE_YEARS:
        T_hours = T_hours / (365 * 24)  # Convert hours to years
    return np.log(S / K) / np.sqrt(T_hours)  # Moneyness = log(Spot Price - Strike Price) / TTE

def get_contract_trades(ticker):
    try:
        url =f"https://api.elections.kalshi.com/trade-api/v2/markets/trades?limit=10&ticker={ticker}"
        headers = {"accept": "application/json"}
        response = requests.get(url, headers=headers)
        headers = {"accept": "application/json"}
        response = requests.get(url, headers=headers)

        data = response.json()
        return data
    except Exception as e:
        print("❌ Error fetching trades:", e)
        return None

def get_options_chain_for_event(event, brti_price=0, threshold=1000):
    try:
        url = f"https://api.elections.kalshi.com/trade-api/v2/events/{event}"
        headers = {"accept": "application/json"}
        response = requests.get(url, headers=headers)

        chain = []
        res = json.loads(response.text)

        for m in res['markets']:
            things = m['subtitle'].split(" ")

            try:
                bottom = float(things[0][1:].replace(',', ''))

                top = float(things[2].replace(',', ''))
                middle = (bottom + top) / 2

                if abs(middle - brti_price) < threshold:
                    chain.append(m)

            except Exception as e:
                continue

        return chain    
    
    except Exception as e:
        print("❌ Error fetching chain:", e)
        return None, None