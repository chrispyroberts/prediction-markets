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
    

def calculate_tte(expiration_time):
    now_local = datetime.now().astimezone()
    now_utc = now_local.astimezone(timezone.utc)
    time_left = expiration_time - now_utc    
    total_seconds = int(time_left.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if USE_YEARS:
        tte = total_seconds / (365 * 24 * 3600)
    else:
        tte = f"{hours:02}:{minutes:02}:{seconds:02}"
    
    return tte


class dataRow:
    def __init__(self, timestamp, product, price=None, strike=None, expiration_time=None, bids=[], asks=[]):
        self.timestamp = timestamp
        self.product = product
        self.price = price
        self.strike = strike
        self.expiration_time = expiration_time
        self.bids = bids
        self.asks = asks

    def make_data_row(self):
        data = {
            'timestamp': self.timestamp,
            'product': self.product,
            'price': self.price,
            'strike': self.strike,
            'expiration_time': self.expiration_time,
        }

        for i, bid in enumerate(self.bids):
            data[f'bid_{i+1}_price'] = bid['price']
            data[f'bid_{i+1}_quantity'] = bid['quantity']
        
        for i, ask in enumerate(self.asks):
            data[f'ask_{i+1}_price'] = ask['price']
            data[f'ask_{i+1}_quantity'] = ask['quantity']

        return data

