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

def get_orderbook(ticker, cents=True):    
    try: 
        url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook"
        headers = {"accept": "application/json"}
        response = requests.get(url, headers=headers)
        order_book = json.loads(response.text)['orderbook']

        if cents:
            divisor = 1
        else:
            divisor = 100
        
        asks = []
        bids = []

        # print(order_book)

        if order_book['yes']:
            for price, size in order_book['yes']:
                bids.append({'price': price/divisor, 'quantity': size})
        if order_book['no']:
            for price, size in order_book['no']:
                asks.append({'price': (100-price)/divisor, 'quantity': size})
        
        return bids, asks   
    
    except Exception as e:
        print("❌ Error fetching orderbook:", e)
        return None, None

def get_top_orderbook(ticker):
    try: 
        url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook"
        headers = {"accept": "application/json"}
        response = requests.get(url, headers=headers)
        order_book = json.loads(response.text)['orderbook']

        ask_value = 0
        bid_value = 0


        asks = []
        bids = []

        # print(order_book)

        if order_book['yes']:
            for price, size in order_book['yes']:
                bids.append({'price': price/100, 'quantity': size})
        if order_book['no']:
            for price, size in order_book['no']:
                asks.append({'price': (100-price)/100, 'quantity': size})
                

        sorted_bids = sorted(bids, key=lambda x: -x["price"])  # High to low
        sorted_asks = sorted(asks, key=lambda x: x["price"])   # Low to high

        bid_value = f"${sorted_bids[0]["price"] * sorted_bids[0]["quantity"] if sorted_bids else 0:.2f}"
        ask_value = f"${sorted_asks[0]["price"] * sorted_asks[0]["quantity"] if sorted_asks else 0:.2f}"
        
        return bid_value, ask_value   

    except Exception as e:
        print("❌ Error fetching orderbook:", e)
        return None, None

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

def get_options_chain_for_event(event, brti_price=0, threshold=1000):
    try:
        url = f"https://api.elections.kalshi.com/trade-api/v2/events/{event}"
        headers = {"accept": "application/json"}
        response = requests.get(url, headers=headers)

        chain = []
        for m in json.loads(response.text)['markets']:
            strike = (round(m['floor_strike'], 0))

            if abs(strike - brti_price) < threshold:
                chain.append(m)

        return chain    
    except Exception as e:
        print("❌ Error fetching chain:", e)
        return None, None