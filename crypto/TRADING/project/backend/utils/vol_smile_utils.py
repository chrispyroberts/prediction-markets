import requests
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import pytz
from scipy.optimize import curve_fit
from scipy.stats import norm
from scipy.optimize import brentq
import asyncio
from scipy.interpolate import CubicSpline


def binance_data(symbol=None):
    base_url = "https://eapi.binance.com/eapi/v1/mark"
    params = {}
    if symbol:
        params['symbol'] = symbol

    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        data = response.json()
    else:
        print(f"Error: Status code {response.status_code}")
        print(response.text)
        return None

    options = []
    for option in data:

        full_symbol = option['symbol']
        symbol = full_symbol.split('-')[0]

        if symbol != 'BTC':
            continue

        options.append(option)

    return options

def get_spot_price(underlying='BTCUSDT'):
    base_url = "https://eapi.binance.com/eapi/v1/index"
    params = {
        'underlying' : underlying,
    }

    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        data = response.json()
    else:
        print(f"Error: Status code {response.status_code}")
        print(response.text)
        return None
    
    return data['indexPrice']

def get_open_interest(expiration, underlying='BTC'):
    params = {
        'underlyingAsset' : underlying,
        'expiration': expiration,
    }

    base_url = "https://eapi.binance.com/eapi/v1/openInterest"

    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        data = response.json()
    else:
        print(f"Error: Status code {response.status_code}")
        print(response.text)
        return None

    return data

def get_data(symbol='BTC'):
    S0 = float(get_spot_price())

    current_time =  datetime.now(pytz.timezone('US/Eastern'))

    strikes = []
    mark_IVs = []
    ttes = []
    mark_prices = []
    open_interests = []
    is_calls = []
    bid_ivs = []
    ask_ivs = []

    open_interest_dict = {}
    expiry_times = {}

    for option in binance_data():
        full_symbol = option['symbol']
        symbol = full_symbol.split('-')[0]

        if symbol != 'BTC':
            continue

        expiration = full_symbol.split('-')[1]

        strike = int(full_symbol.split('-')[2])
        markIV = float(option['markIV'])

        year = expiration[:2]
        month = expiration[2:4]
        day = expiration[4:6]

        # convert to a datetime object
        expiration_date = datetime(int(year)+2000, int(month), int(day), 4, 0, 0, tzinfo=pytz.timezone('US/Eastern'))
        strike = float(full_symbol.split('-')[2])
        is_call = full_symbol.split('-')[3] == 'C'

        tte = (expiration_date - current_time).total_seconds() / 3600 / 24 / 365.25

        open_interest = open_interest_dict.get(full_symbol, None)
        if open_interest is None:
            interest_data = get_open_interest(expiration) 
            for opt in interest_data:
                symbol = opt['symbol']

                sumOpenInterest = opt['sumOpenInterest']
                open_interest_dict[symbol] = sumOpenInterest

            open_interest = open_interest_dict[full_symbol]

        mark_price = option['markPrice']
        mark_IV = option['markIV']

        strikes.append(strike)
        mark_IVs.append(mark_IV)
        ttes.append(tte)
        mark_prices.append(mark_price)
        open_interests.append(open_interest)
        is_calls.append(is_call)
        bid_ivs.append(option['bidIV'])
        ask_ivs.append(option['askIV'])

    ttes = np.array(ttes).astype(float)
    strikes = np.array(strikes).astype(float)
    mark_IVs = np.array(mark_IVs).astype(float)
    mark_prices = np.array(mark_prices).astype(float)
    open_interests = np.array(open_interests).astype(float)
    bid_ivs = np.array(bid_ivs).astype(float)
    ask_ivs = np.array(ask_ivs).astype(float)

    df = pd.DataFrame({'strike': strikes, 'IV': mark_IVs, 'tte': ttes, 'price': mark_prices, 'open_interest': open_interests, 'is_call': is_calls, 'bid_IV': bid_ivs, 'ask_IV': ask_ivs})

    return df, S0

def binary_call_price(S, K, tte, sigma, r=0.0):
    d2 = (np.log(S / K) + (r - 0.5 * sigma**2) * tte) / (sigma * np.sqrt(tte))
    price = np.exp(-r * tte) * norm.cdf(d2)
    return price

# Function to solve: theoretical price - market price = 0
def implied_vol_binary_call(S, K, tte, market_price, r=0.0):
    def objective(sigma):
        return binary_call_price(S, K, tte, sigma, r) - market_price

    try:
        return brentq(objective, 1e-6, 5000.0, xtol=0.005, maxiter=1000)  # Search for sigma in [0.001, 200%]
    except ValueError:
        return None 

# Define sigmoid function
def sigmoid(x, k, x0):
    return 1 / (1 + np.exp(-k * (x - x0)))

def vol_smile(k, b, c, atm_vol):
    return atm_vol + b * k + c * k**2

def vol_smile_quadratic(k, b, c, atm_vol):
    return atm_vol + b * k + c * k**2

def svi_model(k, a, b, rho, m, sigma):
    """
    SVI model with time scaling: σ(k) = a + b(ρ*(k-m) + √((k-m)² + σ²))
    where k = log(K/S) / sqrt(tte)
    """
    return a + b * (rho * (k - m) + np.sqrt((k - m)**2 + sigma**2))

def spline_interpolator(k, k_points, iv_points):
    """
    Cubic spline interpolator for volatility smile
    """
    # Sort points by k to ensure proper spline fitting
    sorted_indices = np.argsort(k_points)
    k_sorted = k_points[sorted_indices]
    iv_sorted = iv_points[sorted_indices]
    
    # Create cubic spline
    spline = CubicSpline(k_sorted, iv_sorted, bc_type='natural')
    return spline(k)

def fetch_0dte_vol_smile():
    filtered_df, S0 = get_data()

    filtered_df = filtered_df[filtered_df['ask_IV'] - filtered_df['bid_IV'] < 0.2] # iv spread filtering
    filtered_df = filtered_df[filtered_df['tte'] < 1/365] # filter for 0 DTE


    filtered_df['d2'] = (np.log(S0/filtered_df['strike']) - 0.5* (filtered_df['IV']**2 * filtered_df['tte'])) / (filtered_df['IV'] * np.sqrt(filtered_df['tte']))
    filtered_df['log_moneyness'] = np.log(filtered_df['strike'] / S0) / np.sqrt(filtered_df['tte'])

    filtered_df = filtered_df[abs(filtered_df['log_moneyness']) < 0.75] # filter for near the money
    filtered_df = filtered_df.groupby(['tte', 'strike'], as_index=False).mean() # average puts and calls

    # Calculate ITM probability
    filtered_df['binary_price'] = np.where(
        filtered_df['is_call'],
        norm.cdf(filtered_df['d2']),     # Call option
        norm.cdf(filtered_df['d2'])     # Put option
    )

    # fit a sigmoid to the 0dte data
    x_data = filtered_df['d2']
    y_data = filtered_df['binary_price']
    tte = filtered_df['tte'].iloc[0]

    # Initial guess for parameters: k=1, x0=0
    p0 = [1, 0]

    # Curve fitting
    params, _ = curve_fit(sigmoid, x_data, y_data, p0)
    x0_fit, d_fit = params

    def simgoid_0dte_fit(k):
        return 1 / (1 + np.exp(-k * (x0_fit - d_fit)))
    
    # Now for vol smile
    tte = filtered_df['tte'].iloc[0]
    ivs = filtered_df['IV']
    moneyness = filtered_df['log_moneyness']

    # find the atm vol
    idx_atm = np.argmin(np.abs(moneyness))  # index of closest to zero
    atm_vol = ivs.iloc[idx_atm]
    atm_vol_1hr = atm_vol * np.sqrt(tte*365)

    # print(f'ATM Vol {tte*365.25*24:.2f}hrs: {atm_vol*100:.5f}%')
    # print(f'ATM Vol 1hr: {atm_vol_1hr*100:.5f}%')

    # Now fit b and c parameters
    vol_params, _ = curve_fit(vol_smile, moneyness/np.sqrt(tte), ivs, p0=[0, 0, atm_vol])  # initial guess for b, c, and atm_vol
    b_fit, c_fit, atm_vol_fit = vol_params

    def fitted_vol_smile(k):
        return atm_vol_fit + b_fit * k + c_fit * k**2
    
    # Fit SVI model
    def svi_fit_func(k, a, b, rho, m, sigma):
        return svi_model(k, a, b, rho, m, sigma)
    
    try:
        svi_params, _ = curve_fit(svi_fit_func, moneyness/np.sqrt(tte), ivs,
                                p0=[atm_vol, 0.1, 0.0, 0.0, 0.1], 
                                bounds=([0.01, 0.01, -0.99, -2.0, 0.01], [10.0, 10.0, 0.99, 2.0, 10.0]))
        a_fit, b_fit_svi, rho_fit_svi, m_fit, sigma_fit = svi_params
    except:
        # Fallback if SVI fitting fails
        a_fit, b_fit_svi, rho_fit_svi, m_fit, sigma_fit = atm_vol, 0.1, 0.0, 0.0, 0.1
    
    def fitted_svi(k):
        return svi_model(k, a_fit, b_fit_svi, rho_fit_svi, m_fit, sigma_fit)
    
    # Prepare spline data
    k_points = moneyness / np.sqrt(tte)
    iv_points = ivs
    
    def fitted_spline(k):
        return spline_interpolator(k, k_points, iv_points)
    
    d2_data =  x_data
    binary_price_data = y_data
    
    # Calculate rev_moneyness (log(K/S)) for the original filtered data
    rev_moneyness = np.log(S0 / filtered_df['strike'])
    
    # Create fitting parameters dictionary
    fitting_params = {
        'polynomial': {
            'atm_vol': atm_vol_fit,
            'b': b_fit,
            'c': c_fit
        },
        'svi': {
            'a': a_fit,
            'b': b_fit_svi,
            'rho': rho_fit_svi,
            'm': m_fit,
            'sigma': sigma_fit
        },
        'spline': {
            'k_points': list(k_points),
            'iv_points': list(iv_points)
        }
    }

    return fitted_vol_smile, simgoid_0dte_fit, d2_data, binary_price_data, moneyness, ivs, tte, atm_vol, atm_vol_1hr, b_fit, c_fit, rev_moneyness, fitting_params, x0_fit, d_fit

async def fetch_binance_vol_smile():
    """
    Async wrapper to fetch and process the volatility smile data from Binance.
    Returns the tuple: (fitted_vol_smile, simgoid_0dte_fit, d2_data, binary_price_data, moneyness, ivs, tte, atm_vol, atm_vol_1hr, b_fit, c_fit, d_fit, e_fit, rev_moneyness, fitting_params, x0_fit, d_fit)
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_0dte_vol_smile)
