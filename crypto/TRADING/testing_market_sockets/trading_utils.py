import pandas as pd
import sqlalchemy
import pytz
import re
from datetime import datetime, timedelta
from arch import arch_model
import numpy as np
import requests
from scipy.stats import norm
from scipy.optimize import minimize_scalar

def get_expiration(ticker_str): 
    """
    Parses a Kalshi ticker string to get the expiration timestamp in milliseconds.
    The expected format is YYMMMDDHH (e.g., '25JUN2117').
    """
    # Example ticker: "INX-25JUN2117"
    # This means Year=25 (2025), Month=JUN, Day=21, Hour=17
    ticker_str = ticker_str.split('-')[1]

    # The format is YYMMMDDHH
    pattern = r'(\d{2})([A-Z]{3})(\d{2})(\d{2})'
    match = re.match(pattern, ticker_str)
    
    if not match:
        raise ValueError(f"Invalid ticker format: {ticker_str}. Expected format: YYMMMDDHH")
        
    # Correctly assign the parsed groups based on YYMMMDDHH format
    year_str, month_str, day_str, hour_str = match.groups()
    
    # Convert to integers
    year = 2000 + int(year_str)  # '25' -> 2025
    day = int(day_str)           # '21' -> 21
    hour = int(hour_str)         # '17' -> 17
    
    # Month mapping
    month_map = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
    }
    if month_str not in month_map:
        raise ValueError(f"Invalid month abbreviation: {month_str}")
        
    month = month_map[month_str]
    
    # Create timezone-aware datetime object robustly
    est_tz = pytz.timezone('US/Eastern')
    naive_dt = datetime(year, month, day, hour, 0, 0)
    expiry_dt = est_tz.localize(naive_dt)

    # Convert to milliseconds timestamp
    timestamp_ms = int(expiry_dt.timestamp() * 1000)
    return timestamp_ms

def get_sql_brti_data():
    # --- Database Connection Details ---
    DB_NAME = "chris_db"
    DB_USER = "postgres"
    DB_PASSWORD = "password"  # The password you set in your docker run command
    DB_HOST = "localhost"
    DB_PORT = "5432"

    db_url = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    # Create a SQLAlchemy engine
    try:
        engine = sqlalchemy.create_engine(db_url)
        print("Successfully connected to the database!")
    except Exception as e:
        print(f"Failed to connect to the database. Error: {e}")
        return None

    # --- Read Data from the 'brti_prices' Table ---

    limit = 100000

    table_name = "brti_prices"
    query = f"SELECT * FROM {table_name} ORDER BY timestamp_ms DESC LIMIT {limit};"

    try:
        with engine.connect() as connection:
            df_brti = pd.read_sql(query, connection)
        
        print(f"Successfully loaded {len(df_brti)} rows from '{table_name}'.")
    except Exception as e:
        print(f"Failed to read data from table '{table_name}'. Error: {e}")
        return None
    
    return df_brti

def get_garch_volatility_forecast(price_series, horizon_seconds=3600, p=1, q=1):
    """
    Calculates the average annualized volatility forecast over a future period
    using a GARCH(1,1) model.
    """
    if not isinstance(price_series.index, pd.DatetimeIndex):
        raise TypeError("The price_series index must be a DatetimeIndex.")
        
    returns = 100 * price_series.pct_change().dropna()
    
    if len(returns) < 200:
        return np.nan

    model = arch_model(returns, vol='Garch', p=p, q=q, dist='t')
    
    try:
        fit_result = model.fit(disp='off', show_warning=False)
    except Exception:
        return np.nan
    
    # get conditional volatility series from fitted model
    conditional_vol_series = fit_result.conditional_volatility
    # calculate vol series
    vol_of_vol = conditional_vol_series.std() / 100


    forecast = fit_result.forecast(horizon=horizon_seconds, reindex=False)
    mean_forecast_variance = forecast.variance.iloc[-1].mean()
    avg_vol_per_second = np.sqrt(mean_forecast_variance) / 100.0
    
    seconds_in_year = 365.25 * 24 * 60 * 60
    annualized_vol = avg_vol_per_second * np.sqrt(seconds_in_year)
    
    return annualized_vol, vol_of_vol

def analyze_option_volatility(current_timestamp_ms, future_timestamp_ms, lookback_period_str, brti_df_indexed):
    """
    Fits a GARCH model on recent data to forecast volatility for a specific option lifetime.

    Args:
        current_timestamp_ms (int): The current time (or time of analysis) in milliseconds.
        future_timestamp_ms (int): The option's expiration timestamp in milliseconds.
        lookback_period_str (str): The amount of historical data to use for fitting,
                                   e.g., '4H', '2H', '30T'.
        brti_df_indexed (pd.DataFrame): The BRTI DataFrame with a DatetimeIndex.

    Returns:
        float: The single, annualized GARCH volatility forecast, or np.nan if it fails.
    """
    horizon_seconds = (future_timestamp_ms - current_timestamp_ms) / 1000
    
    if horizon_seconds <= 0:
        print("Warning: Future timestamp must be after current timestamp.")
        return np.nan

    current_time = pd.to_datetime(current_timestamp_ms, unit='ms')
    lookback_start_time = current_time - pd.Timedelta(lookback_period_str)
    
    price_window = brti_df_indexed['brti_price'][lookback_start_time:current_time]

    forecast, vol_of_vol = get_garch_volatility_forecast(
        price_series=price_window,
        horizon_seconds=int(horizon_seconds) # Ensure it's an integer
    )
    
    return forecast, vol_of_vol

def get_strike(ticker):
    return float(ticker.split('-')[2][1:])

def get_btc_vol_estimate(tickers, lookback='12h'):

    df_brti = get_sql_brti_data()

    if df_brti is None:
        return None

    # get first ticker
    ticker = tickers[0]
    expiration_timestamp_ms = get_expiration(ticker)

    # get current timestamp in EST ms
    est_tz = pytz.timezone('US/Eastern')
    current_timestamp_ms = int(datetime.now(est_tz).timestamp() * 1000)


    df_brti_indexed = df_brti.copy()
    df_brti_indexed = df_brti_indexed.sort_values('timestamp_ms').copy()
    df_brti_indexed['datetime'] = pd.to_datetime(df_brti['timestamp_ms'], unit='ms')
    df_brti_indexed = df_brti_indexed.set_index('datetime')

    forecast_vol, vol_of_vol = analyze_option_volatility(current_timestamp_ms, expiration_timestamp_ms, lookback, df_brti_indexed)

    return forecast_vol, vol_of_vol


import numpy as np
from scipy.integrate import quad
from numpy import log, exp, sqrt, real


MODEL_PARAMS = {
    'a' : 1.56744012,
    'b' : -0.01774851,
    'c' : -0.03421711,
    'd' : 0.03809836
}

def heston_cf(u, S, T, r, v0, theta, kappa, sigma, rho):
    """
    Characteristic function for log(S_T) under Heston model.
    
    Parameters:
        u: complex argument for CF
        S: spot price
        T: time to maturity (years)
        r: risk-free rate
        v0: initial variance
        theta: long-run variance
        kappa: mean reversion speed
        sigma: vol of vol
        rho: correlation between asset and variance
    """
    i = complex(0, 1)
    d = np.sqrt((rho * sigma * i * u - kappa)**2 + (sigma**2) * (i * u + u**2))
    g = (kappa - rho * sigma * i * u - d) / (kappa - rho * sigma * i * u + d)
    
    C = r * i * u * T + (kappa * theta / sigma**2) * ((kappa - rho * sigma * i * u - d) * T - 2 * np.log((1 - g * np.exp(-d * T)) / (1 - g)))
    D = ((kappa - rho * sigma * i * u - d) / sigma**2) * ((1 - np.exp(-d * T)) / (1 - g * np.exp(-d * T)))
    
    return np.exp(C + D * v0 + i * u * np.log(S))

def heston_binary_call_price(S, K, T, r, v0, theta, kappa, sigma, rho):
    """
    Prices a cash-or-nothing binary call under the Heston model.
    
    Parameters:
        S: spot price
        K: strike price
        T: time to maturity (years)
        r: risk-free rate
        v0: initial variance
        theta: long-run variance
        kappa: mean reversion speed
        sigma: vol of vol
        rho: correlation
    
    Returns:
        price: binary call option price
    """
    i = complex(0, 1)

    def integrand(u):
        numerator = np.exp(-i * u * np.log(K)) * heston_cf(u - i, S, T, r, v0, theta, kappa, sigma, rho)
        denominator = i * u * heston_cf(-i, S, T, r, v0, theta, kappa, sigma, rho)
        return real(numerator / denominator)

    integral, _ = quad(integrand, 0, 100)  # integration upper limit can be tuned
    prob = 0.5 + integral / np.pi
    price = np.exp(-r * T) * prob
    return price

def smile_adjusted_iv(base_iv, moneyness, strength=3000.0):
    """
    Adjust base implied volatility using a quadratic smile curve.
    `strength` controls how steep the wings are.
    """
    return base_iv * (1 + strength * moneyness**2)

def estimate_constract_price_advanced(ticker, brti_price, volatility, vol_of_vol):
    """
    Calculates the price of a binary option using the Heston model.
    """
    kappa = 2                   # calculated from btc price and vol data
    rho = -0.2          # calculated from btc price and vol data
    theta = 0.411 ** 2             # 30 day btc options ATM vol

    strike = int(get_strike(ticker))
    if strike % 10 == 0:
        range = 250
    else:
        range = 125

    top = strike + range
    bottom = strike - range

    est_tz = pytz.timezone('US/Eastern')
    current_timestamp_ms = int(datetime.now(est_tz).timestamp() * 1000)
    tte = get_expiration(ticker) 

    tte_seconds = (tte - current_timestamp_ms) / 1000

    tte_years = tte_seconds / (365.25 * 24 * 60 * 60)



    top_price = heston_binary_call_price(brti_price, top, tte_years, 0.0, volatility ** 2, theta, kappa, vol_of_vol, rho)
    bot_price = heston_binary_call_price(brti_price, bottom, tte_years, 0.0, volatility ** 2, theta, kappa, vol_of_vol, rho)

    if top >= 99000 and top <= 100000:
        print(f"BRTI Price: {brti_price}")
        print(f"Volatility: {volatility}")
        print(f"TTE: {tte_years}")
        print(f"Strike: {top} : {top_price*100:.2f}")
        print(f"Strike: {bottom} : {bot_price*100:.2f}")

    return bot_price - top_price

def black_scholes_binary_call_price(S, K, T, sigma, r=0):
    """
    Price of a cash-or-nothing binary call option using Black-Scholes formula.

    Args:
        S (float): Current underlying price
        K (float): Strike price
        T (float): Time to maturity in years
        r (float): Risk-free interest rate (annualized)
        sigma (float): Volatility of underlying (annualized)

    Returns:
        float: Option price (present value of payout)
    """
    if T <= 0:
        # At expiry: option pays 1 if S > K, else 0
        return float(S > K)

    d2 = (np.log(S / K) + (r - 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    price = np.exp(-r * T) * norm.cdf(d2)
    return price

def binary_call_price(S, K, T, sigma, r=0.0):
    """Black-Scholes price for binary cash-or-nothing call option"""
    if T == 0 or sigma == 0:
        return 1.0 if S > K else 0.0
    d2 = (np.log(S / K) - 0.5 * sigma ** 2 * T) / (sigma * np.sqrt(T))
    return np.exp(-r * T) * norm.cdf(d2)

def find_max_binary_price(S, K, T, r=0.0):
    """Find volatility that maximizes binary call price"""
    def objective(sigma):
        return -binary_call_price(S, K, T, sigma, r)

    res = minimize_scalar(objective, bounds=(1e-4, 1.5), method='bounded')

    max_vol = res.x
    max_price = -res.fun
    return max_price, max_vol

def custom_sigmoid(x, a, b, c, d):
    return 1 / ((1 + np.exp(-a * (x - b + c * x + d * x**2)))) 

def model(spot_price, strike, time_to_expiry, vol):
    # time to expiry in hours
    # vol annualized

    # calculate log moneyness
    log_moneyness = np.log((spot_price / strike))

    numerator = log_moneyness - 0.5 * vol**2 * time_to_expiry
    denominator = vol * np.sqrt(time_to_expiry)

    d2 = numerator / denominator

    val = custom_sigmoid(d2, MODEL_PARAMS['a'], MODEL_PARAMS['b'], MODEL_PARAMS['c'], MODEL_PARAMS['d'])

    return val

def contract_type(ticker):
    if ticker.split('-')[0] == 'KXBTCD':
        return 'calls'
    else:
        return 'range'


def get_time_to_expiry_hours(ticker):
    est_tz = pytz.timezone('US/Eastern')
    current_timestamp_ms = int(datetime.now(est_tz).timestamp() * 1000)
    tte = get_expiration(ticker) 
    tte_seconds = (tte - current_timestamp_ms) / 1000
    return tte_seconds / 3600

def estimate_price_using_model(ticker, brti_price, volatility):
    strike = int(get_strike(ticker))
    if strike % 10 == 0:
        range = 250
    else:
        range = 125

    top = strike + range
    bot = strike - range

    est_tz = pytz.timezone('US/Eastern')
    current_timestamp_ms = int(datetime.now(est_tz).timestamp() * 1000)
    tte = get_expiration(ticker) 

    tte_seconds = (tte - current_timestamp_ms) / 1000
    tte_years = tte_seconds / 3600 / 24 / 365

    if contract_type(ticker) == 'calls':
        return model(brti_price, strike, tte_years, volatility) * 100
    else:
        top_price = model(brti_price, top, tte_years, volatility)
        bot_price = model(brti_price, bot, tte_years, volatility)
        est_price = (bot_price - top_price) * 100
        return  est_price

def get_binance_option_mark_price(brti_price, symbol=None):
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

    nearest_expiry_ATM = []
    for option in data:

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
        # est = pytz.timezone('US/Eastern')
        # find all options expiring soon
        now = datetime.now(pytz.timezone('US/Eastern'))
        if expiration_date < now + timedelta(days=1):
            # check they are near the money
            if abs(strike - brti_price) < 1000:
                nearest_expiry_ATM.append(markIV)
            
    return np.mean(nearest_expiry_ATM)









def estimate_constract_price(ticker, brti_price, volatility):
    """
    Calculates the price of a binary option using the Black-Scholes model.
    """
    strike = float(get_strike(ticker))
    if strike % 10 == 0:
        range = 250
    else:
        range = 125

    top = strike + range
    bottom = strike - range

    est_tz = pytz.timezone('US/Eastern')
    current_timestamp_ms = int(datetime.now(est_tz).timestamp() * 1000)
    tte = get_expiration(ticker) 

    tte_seconds = (tte - current_timestamp_ms) / 1000

    tte_years = tte_seconds / (365*25 * 24 * 60 * 60)
    
    top_price = black_scholes_binary_call_price(brti_price, top, tte_years, volatility, r=0)
    bot_price = black_scholes_binary_call_price(brti_price, bottom, tte_years, volatility, r=0)

    max_top_price, top_opt_vol = find_max_binary_price(brti_price, top, tte_years, r=0)
    max_bot_price, bot_opt_vol = find_max_binary_price(brti_price, bottom, tte_years, r=0)

    if top > 99000 and top < 102000:
        print(f"BRTI Price: {brti_price}")
        print(f"Volatility: {volatility}")
        print(f"Top Opt Vol: {top_opt_vol} Top Price: {max_top_price*100:.2f}")
        print(f"Bot Opt Vol: {bot_opt_vol} Bot Price: {max_bot_price*100:.2f}")
        print(f"TTE: {tte_years}")
        print(f"Strike: {top} : {top_price*100:.2f}")
        print(f"Strike: {bottom} : {bot_price*100:.2f}")

    return bot_price - top_price






