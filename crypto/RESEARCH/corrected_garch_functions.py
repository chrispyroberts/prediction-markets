import pandas as pd
import numpy as np
from arch import arch_model
import warnings

# Suppress convergence warnings from the GARCH model fitting process
warnings.filterwarnings("ignore", category=UserWarning, module='arch')

# --- Function 1: The Core GARCH Volatility Forecaster (CORRECTED) ---
def get_garch_volatility_forecast(price_series, horizon_seconds=3600, p=1, q=1):
    """
    Calculates the average annualized volatility forecast over a future period
    using a GARCH(1,1) model.
    
    Returns:
        tuple: (annualized_vol, vol_of_vol) or (np.nan, np.nan) if failed
    """
    if not isinstance(price_series.index, pd.DatetimeIndex):
        raise TypeError("The price_series index must be a DatetimeIndex.")
        
    returns = 100 * price_series.pct_change().dropna()
    
    if len(returns) < 200:
        return np.nan, np.nan  # FIXED: Return tuple

    model = arch_model(returns, vol='Garch', p=p, q=q, dist='t')
    
    try:
        fit_result = model.fit(disp='off', show_warning=False)
    except Exception:
        return np.nan, np.nan  # FIXED: Return tuple
    
    # get conditional volatility series from fitted model
    conditional_vol_series = fit_result.conditional_volatility
    # calculate vol of vol
    vol_of_vol = conditional_vol_series.std() / 100

    forecast = fit_result.forecast(horizon=horizon_seconds, reindex=False)
    mean_forecast_variance = forecast.variance.iloc[-1].mean()
    avg_vol_per_second = np.sqrt(mean_forecast_variance) / 100.0
    
    seconds_in_year = 365.25 * 24 * 60 * 60
    annualized_vol = avg_vol_per_second * np.sqrt(seconds_in_year)
    
    return annualized_vol, vol_of_vol  # FIXED: Return tuple

# --- Function 2: The Wrapper Function (CORRECTED) ---
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
        tuple: (forecast, vol_of_vol) or (np.nan, np.nan) if failed
    """
    # 1. Calculate the forecast horizon in seconds
    horizon_seconds = (future_timestamp_ms - current_timestamp_ms) / 1000
    
    if horizon_seconds <= 0:
        print("Warning: Future timestamp must be after current timestamp.")
        return np.nan, np.nan  # FIXED: Return tuple

    # 2. Define the lookback window for slicing the data
    # Convert the current time to a pandas Timestamp for slicing
    current_time = pd.to_datetime(current_timestamp_ms, unit='ms')
    lookback_start_time = current_time - pd.Timedelta(lookback_period_str)
    
    # Slice the historical data based on the lookback window
    price_window = brti_df_indexed['brti_price'][lookback_start_time:current_time]

    # Check if we have enough data
    if len(price_window) < 200:
        print(f"Warning: Insufficient data. Got {len(price_window)} points, need at least 200.")
        return np.nan, np.nan

    # print(f"Analyzing option from {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    # print(f"  - Fitting model on data from the last {lookback_period_str} ({len(price_window)} points).")
    # print(f"  - Forecasting volatility for the next {horizon_seconds/60:.1f} minutes.")
    
    # 3. Call the core GARCH function with the sliced data and calculated horizon
    forecast, vol_of_vol = get_garch_volatility_forecast(
        price_series=price_window,
        horizon_seconds=int(horizon_seconds) # Ensure it's an integer
    )
    
    return forecast, vol_of_vol  # FIXED: Return tuple

# --- Additional helper function for testing ---
def test_garch_functions():
    """
    Test function to verify the GARCH functions work correctly.
    """
    
    # Create sample data
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=1000, freq='1min')
    prices = 100 + np.cumsum(np.random.randn(1000) * 0.01)  # Random walk
    sample_data = pd.DataFrame({'brti_price': prices}, index=dates)
    
    print("Testing GARCH functions...")
    print("=" * 50)
    
    # Test 1: Direct GARCH function
    print("Test 1: Direct GARCH function")
    vol_forecast, vol_of_vol = get_garch_volatility_forecast(sample_data['brti_price'], horizon_seconds=3600)
    print(f"Volatility Forecast: {vol_forecast*100:.2f}%")
    print(f"Vol of Vol: {vol_of_vol*100:.4f}%")
    print()
    
    # Test 2: Wrapper function
    print("Test 2: Wrapper function")
    current_time = pd.Timestamp('2024-01-01 12:00:00')
    future_time = current_time + pd.Timedelta(hours=1)
    
    current_ms = int(current_time.timestamp() * 1000)
    future_ms = int(future_time.timestamp() * 1000)
    
    forecast, vol_of_vol = analyze_option_volatility(
        current_timestamp_ms=current_ms,
        future_timestamp_ms=future_ms,
        lookback_period_str='4H',
        brti_df_indexed=sample_data
    )
    
    print(f"Volatility Forecast: {forecast*100:.2f}%")
    print(f"Vol of Vol: {vol_of_vol*100:.4f}%")
    print()
    
    # Test 3: Error handling
    print("Test 3: Error handling with insufficient data")
    small_data = sample_data.iloc[:50]  # Only 50 points
    forecast, vol_of_vol = get_garch_volatility_forecast(small_data['brti_price'])
    print(f"Result with insufficient data: {forecast}, {vol_of_vol}")
    print()
    
    print("All tests completed!")

if __name__ == "__main__":
    test_garch_functions() 