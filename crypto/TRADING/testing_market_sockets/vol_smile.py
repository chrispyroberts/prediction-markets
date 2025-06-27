import socketio
from trading_utils import get_strike
from vol_smile_utils import fetch_0dte_vol_smile, implied_vol_binary_call, sigmoid
import pandas as pd
import numpy as np
from scipy.optimize import curve_fit
import os
from datetime import datetime
import matplotlib
matplotlib.use('Agg')  # Use a non-GUI backend for headless environments

import matplotlib.pyplot as plt
import time


# Create a Socket.IO client
sio = socketio.Client()

class VolSmile():
    def __init__(self):

        self.orderbooks = {}

    def update(self, payload):
        self.last_updated = payload['timestamp']
        self.brti_price = payload['brti_price']
        self.tte = payload['tte'] / 24 / 365 # in hours so convert to years
        self.orderbooks = payload['orderbooks']

        self.best_bids = []
        self.mm_bids = []

        self.best_asks = []
        self.mm_asks = []

        self.best_mids = []
        self.mm_mids = []

        self.best_bid_ivs = []
        self.mm_bid_ivs = []

        self.best_ask_ivs = []
        self.mm_ask_ivs = []

        self.best_mid_ivs = []
        self.mm_mid_ivs = []

        self.Ks = []
        self.Ms = []

        # lets make a dataframe
        for ticker in self.orderbooks.keys():
            strike = get_strike(ticker)
            log_moneyness = np.log(strike / self.brti_price) / np.sqrt(self.tte)
            moneyness = np.log(self.brti_price / strike)

            mm_bid = self.orderbooks[ticker]['mm_bid']
            best_bid = self.orderbooks[ticker]['best_bid']

            mm_ask = self.orderbooks[ticker]['mm_ask']
            best_ask = self.orderbooks[ticker]['best_ask']

            mm_mid = (mm_bid + mm_ask) / 2
            best_mid = (best_bid + best_ask) / 2

            mm_bid_iv = implied_vol_binary_call(self.brti_price, strike, self.tte, mm_bid/100)
            best_bid_iv = implied_vol_binary_call(self.brti_price, strike, self.tte, best_bid/100)

            mm_ask_iv = implied_vol_binary_call(self.brti_price, strike, self.tte, mm_ask/100)
            best_ask_iv = implied_vol_binary_call(self.brti_price, strike, self.tte, best_ask/100)

            mm_mid_iv = implied_vol_binary_call(self.brti_price, strike, self.tte, mm_mid/100)
            best_mid_iv = implied_vol_binary_call(self.brti_price, strike, self.tte, best_mid/100)

            # filter for good spread
            if abs(best_bid - best_ask) < 20 and (mm_mid_iv is not None):
                self.best_bids.append(best_bid)
                self.mm_bids.append(mm_bid)
                self.best_asks.append(best_ask)
                self.mm_asks.append(mm_ask)
                self.best_mids.append(best_mid)
                self.mm_mids.append(mm_mid)
                
                self.best_bid_ivs.append(best_bid_iv)
                self.mm_bid_ivs.append(mm_bid_iv)
                self.best_ask_ivs.append(best_ask_iv)
                self.mm_ask_ivs.append(mm_ask_iv)
                self.best_mid_ivs.append(best_mid_iv)
                self.mm_mid_ivs.append(mm_mid_iv)

                self.Ks.append(log_moneyness)
                self.Ms.append(moneyness)
        
        df = pd.DataFrame({
            'K' : self.Ks,
            'best_bid' : self.best_bids,
            'mm_bid' : self.mm_bids,
            'best_ask' : self.best_asks,
            'mm_ask' : self.mm_asks,
            'best_bid_iv' : self.best_bid_ivs,
            'mm_bid_iv' : self.mm_bid_ivs,
            'best_ask_iv' : self.best_ask_ivs,
            'mm_ask_iv' : self.mm_ask_ivs,
            'best_mid_iv' : self.best_mid_ivs,
            'mm_mid_iv' : self.mm_mid_ivs,
            'Ms' : self.Ms,
        })

        # sort by K
        self.df = df.sort_values(by='K')

    def get_binance_smile(self):
        # get the binance vol smile
        fitted_vol_smile, simgoid_0dte_fit, d2_data, binary_price_data, moneyness, ivs, tte, atm_vol, atm_vol_1hr = fetch_0dte_vol_smile()

        # fitted functions
        self.binance_vol_smile = fitted_vol_smile
        self.simgoid_0dte_fit = simgoid_0dte_fit

        # for plotting the binance sigmoid
        self.d2_data = d2_data
        self.binary_price_data = binary_price_data
        
        # for plotting the vol smile
        self.moneyness = moneyness
        self.ivs = ivs
        
        # time to expiry
        self.zero_dte_tte = tte

        # fitted vol and decayed to 1hr
        self.atm_vol = atm_vol
        self.atm_vol_1hr = atm_vol_1hr
    


    def fit_kalshi_vol_smile(self):
        # fit a quadtratic to the mm_mid_iv
        moneyness = self.df['Ms']
        vols = self.df['mm_mid_iv']
        tte = self.tte

        d2 = (moneyness - 0.5 * vols**2 * tte) / (vols * np.sqrt(tte))
        prices = (self.df['mm_bid'] + self.df['mm_ask']) / 2 / 100 # to probabilities


        # fit sigmoid to d2 and prices
        popt, pcov = curve_fit(sigmoid, d2, prices)

        self.sigmoid_kalshi_fit = lambda x: sigmoid(x, popt[0], popt[1])
        self.d2s = d2
        self.prices = prices

    def plot(self):
        fig, ax = plt.subplots(figsize=(10, 5))
        
        ax.scatter(self.d2s, self.prices*100, label='Kalshi MM Mids', color='Green')
        d2_fit = np.linspace(min(self.d2s), max(self.d2s), 100)
        ax.plot(d2_fit, self.sigmoid_kalshi_fit(d2_fit)*100, color='green')

        ax.scatter(self.d2_data, self.binary_price_data*100, label='Binance Options', color='Red')
        ax.plot(d2_fit, self.simgoid_0dte_fit(d2_fit)*100, color='red')

        ax.legend()
        ax.set_title(f"Kalshi and Binance Binary Prices vs D2")
        ax.set_xlabel("D2")
        ax.set_ylabel("Price")

        filename = f"vol_smile.png"
        fig.savefig(filename, dpi=150)
        plt.close(fig)  # close to free memor



smile = VolSmile()

@sio.event(namespace='/orderbook')
def connect():
    print('Connected to /orderbook namespace')

@sio.event(namespace='/orderbook')
def disconnect():
    print('Disconnected from /orderbook namespace')

@sio.on('orderbook_update', namespace='/orderbook')
def on_orderbook_update(data):
    smile.update(data)

if __name__ == '__main__':
    sio.connect('http://localhost:5010', namespaces=['/orderbook'])
    time.sleep(5)
    while True:
        time.sleep(5)
        smile.get_binance_smile()
        smile.fit_kalshi_vol_smile()
        smile.plot()
    
