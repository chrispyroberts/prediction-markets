import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from arch import arch_model
import warnings
from datetime import datetime, timedelta
import matplotlib.dates as mdates

# Suppress convergence warnings from the GARCH model fitting process
warnings.filterwarnings("ignore", category=UserWarning, module='arch')

# Set style for better plots
plt.style.use('seaborn-v0_8')
sns.set_palette("husl")

# --- Function 1: The Core GARCH Volatility Forecaster ---
def get_garch_volatility_forecast(price_series, horizon_seconds=3600, p=1, q=1):
    """
    Calculates the average annualized volatility forecast over a future period
    using a GARCH(1,1) model.
    """
    if not isinstance(price_series.index, pd.DatetimeIndex):
        raise TypeError("The price_series index must be a DatetimeIndex.")
        
    returns = 100 * price_series.pct_change().dropna()
    
    if len(returns) < 200:
        return np.nan, np.nan

    model = arch_model(returns, vol='Garch', p=p, q=q, dist='t')
    
    try:
        fit_result = model.fit(disp='off', show_warning=False)
    except Exception:
        return np.nan, np.nan
    
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

# --- Function 2: The Wrapper Function for Option Analysis ---
def analyze_option_volatility(current_timestamp_ms, future_timestamp_ms, lookback_period_str, brti_df_indexed):
    """
    Fits a GARCH model on recent data to forecast volatility for a specific option lifetime.
    """
    # 1. Calculate the forecast horizon in seconds
    horizon_seconds = (future_timestamp_ms - current_timestamp_ms) / 1000
    
    if horizon_seconds <= 0:
        return np.nan, np.nan

    # 2. Define the lookback window for slicing the data
    current_time = pd.to_datetime(current_timestamp_ms, unit='ms')
    lookback_start_time = current_time - pd.Timedelta(lookback_period_str)
    
    # Slice the historical data based on the lookback window
    price_window = brti_df_indexed['brti_price'][lookback_start_time:current_time]

    # 3. Call the core GARCH function with the sliced data and calculated horizon
    forecast, vol_of_vol = get_garch_volatility_forecast(
        price_series=price_window,
        horizon_seconds=int(horizon_seconds)
    )
    
    return forecast, vol_of_vol

def calculate_rolling_garch_volatility(df_brti_indexed, lookback_period='4H', forecast_horizon='1H', 
                                     step_size='30T', start_date=None, end_date=None):
    """
    Calculate GARCH volatility forecasts at regular intervals over time.
    
    Args:
        df_brti_indexed: DataFrame with DatetimeIndex and 'brti_price' column
        lookback_period: How much historical data to use for GARCH fitting
        forecast_horizon: How far ahead to forecast volatility
        step_size: How often to calculate volatility (e.g., every 30 minutes)
        start_date: Start date for analysis (if None, uses earliest data)
        end_date: End date for analysis (if None, uses latest data)
    
    Returns:
        DataFrame with timestamp, volatility forecast, and vol-of-vol
    """
    
    # Set date range
    if start_date is None:
        start_date = df_brti_indexed.index.min()
    if end_date is None:
        end_date = df_brti_indexed.index.max()
    
    # Convert to datetime if strings
    if isinstance(start_date, str):
        start_date = pd.to_datetime(start_date)
    if isinstance(end_date, str):
        end_date = pd.to_datetime(end_date)
    
    # Create time points for analysis
    time_points = pd.date_range(start=start_date, end=end_date, freq=step_size)
    
    # Convert forecast horizon to seconds
    forecast_seconds = pd.Timedelta(forecast_horizon).total_seconds()
    
    results = []
    
    print(f"Calculating GARCH volatility forecasts...")
    print(f"Time range: {start_date} to {end_date}")
    print(f"Step size: {step_size}")
    print(f"Total time points: {len(time_points)}")
    
    for i, current_time in enumerate(time_points):
        if i % 50 == 0:  # Progress indicator
            print(f"Progress: {i}/{len(time_points)} ({i/len(time_points)*100:.1f}%)")
        
        # Convert to milliseconds
        current_timestamp_ms = int(current_time.timestamp() * 1000)
        future_timestamp_ms = int((current_time.timestamp() + forecast_seconds) * 1000)
        
        # Calculate volatility forecast
        vol_forecast, vol_of_vol = analyze_option_volatility(
            current_timestamp_ms, future_timestamp_ms, lookback_period, df_brti_indexed
        )
        
        # Get current price
        current_price = df_brti_indexed['brti_price'].loc[:current_time].iloc[-1] if len(df_brti_indexed['brti_price'].loc[:current_time]) > 0 else np.nan
        
        results.append({
            'timestamp': current_time,
            'brti_price': current_price,
            'volatility_forecast': vol_forecast,
            'vol_of_vol': vol_of_vol
        })
    
    return pd.DataFrame(results)

def plot_garch_volatility_analysis(volatility_df, save_plot=True):
    """
    Create comprehensive plots of GARCH volatility analysis.
    """
    
    fig, axes = plt.subplots(3, 1, figsize=(15, 12), sharex=True)
    
    # Remove NaN values for plotting
    clean_df = volatility_df.dropna()
    
    if len(clean_df) == 0:
        print("No valid data points found for plotting.")
        return
    
    # Plot 1: BTC Price
    axes[0].plot(clean_df['timestamp'], clean_df['brti_price'], linewidth=1, alpha=0.8)
    axes[0].set_ylabel('BRTI Price (USD)', fontsize=12)
    axes[0].set_title('BTC Price Over Time', fontsize=14, fontweight='bold')
    axes[0].grid(True, alpha=0.3)
    
    # Plot 2: GARCH Volatility Forecast
    axes[1].plot(clean_df['timestamp'], clean_df['volatility_forecast'] * 100, 
                linewidth=1.5, color='red', alpha=0.8)
    axes[1].set_ylabel('Volatility Forecast (%)', fontsize=12)
    axes[1].set_title('GARCH(1,1) Volatility Forecast (Annualized)', fontsize=14, fontweight='bold')
    axes[1].grid(True, alpha=0.3)
    
    # Add moving average for volatility
    if len(clean_df) > 20:
        vol_ma = clean_df['volatility_forecast'].rolling(window=20).mean() * 100
        axes[1].plot(clean_df['timestamp'], vol_ma, linewidth=2, color='darkred', 
                    alpha=0.7, label='20-period MA')
        axes[1].legend()
    
    # Plot 3: Volatility of Volatility
    axes[2].plot(clean_df['timestamp'], clean_df['vol_of_vol'] * 100, 
                linewidth=1.5, color='purple', alpha=0.8)
    axes[2].set_ylabel('Vol of Vol (%)', fontsize=12)
    axes[2].set_xlabel('Time', fontsize=12)
    axes[2].set_title('Volatility of Volatility (Smile Curvature)', fontsize=14, fontweight='bold')
    axes[2].grid(True, alpha=0.3)
    
    # Add moving average for vol-of-vol
    if len(clean_df) > 20:
        vol_of_vol_ma = clean_df['vol_of_vol'].rolling(window=20).mean() * 100
        axes[2].plot(clean_df['timestamp'], vol_of_vol_ma, linewidth=2, color='darkmagenta', 
                    alpha=0.7, label='20-period MA')
        axes[2].legend()
    
    # Format x-axis
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
    
    plt.tight_layout()
    
    if save_plot:
        plt.savefig('garch_volatility_analysis.png', dpi=300, bbox_inches='tight')
        print("Plot saved as 'garch_volatility_analysis.png'")
    
    plt.show()
    
    # Print summary statistics
    print("\n=== GARCH Volatility Analysis Summary ===")
    print(f"Analysis period: {clean_df['timestamp'].min()} to {clean_df['timestamp'].max()}")
    print(f"Total data points: {len(clean_df)}")
    print(f"Valid volatility forecasts: {len(clean_df.dropna(subset=['volatility_forecast']))}")
    
    print(f"\nVolatility Forecast Statistics:")
    print(f"  Mean: {clean_df['volatility_forecast'].mean()*100:.2f}%")
    print(f"  Std:  {clean_df['volatility_forecast'].std()*100:.2f}%")
    print(f"  Min:  {clean_df['volatility_forecast'].min()*100:.2f}%")
    print(f"  Max:  {clean_df['volatility_forecast'].max()*100:.2f}%")
    
    print(f"\nVolatility of Volatility Statistics:")
    print(f"  Mean: {clean_df['vol_of_vol'].mean()*100:.4f}%")
    print(f"  Std:  {clean_df['vol_of_vol'].std()*100:.4f}%")
    print(f"  Min:  {clean_df['vol_of_vol'].min()*100:.4f}%")
    print(f"  Max:  {clean_df['vol_of_vol'].max()*100:.4f}%")

def create_volatility_heatmap(volatility_df, save_plot=True):
    """
    Create a heatmap showing volatility patterns by hour of day and day of week.
    """
    
    clean_df = volatility_df.dropna()
    
    if len(clean_df) == 0:
        print("No valid data points found for heatmap.")
        return
    
    # Add time features
    clean_df['hour'] = clean_df['timestamp'].dt.hour
    clean_df['day_of_week'] = clean_df['timestamp'].dt.day_name()
    clean_df['day_of_week_num'] = clean_df['timestamp'].dt.dayofweek
    
    # Create pivot table for heatmap
    vol_pivot = clean_df.pivot_table(
        values='volatility_forecast', 
        index='hour', 
        columns='day_of_week_num', 
        aggfunc='mean'
    ) * 100  # Convert to percentage
    
    # Create the heatmap
    fig, ax = plt.subplots(figsize=(12, 8))
    
    sns.heatmap(vol_pivot, annot=True, fmt='.2f', cmap='RdYlBu_r', 
                cbar_kws={'label': 'Volatility Forecast (%)'}, ax=ax)
    
    # Set labels
    ax.set_xlabel('Day of Week', fontsize=12)
    ax.set_ylabel('Hour of Day', fontsize=12)
    ax.set_title('Average GARCH Volatility Forecast by Hour and Day', fontsize=14, fontweight='bold')
    
    # Set tick labels
    day_labels = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    ax.set_xticklabels(day_labels, rotation=45)
    
    plt.tight_layout()
    
    if save_plot:
        plt.savefig('volatility_heatmap.png', dpi=300, bbox_inches='tight')
        print("Heatmap saved as 'volatility_heatmap.png'")
    
    plt.show()

# Main execution function
def main():
    """
    Main function to run the GARCH volatility analysis.
    """
    
    # Load your BRTI data (you'll need to modify this path)
    print("Loading BRTI data...")
    
    # You'll need to load your actual data here
    # For example:
    # df_brti = pd.read_csv('your_brti_data.csv')
    # df_brti['datetime'] = pd.to_datetime(df_brti['timestamp_ms'], unit='ms')
    # df_brti_indexed = df_brti.set_index('datetime')
    
    # For now, let's create a placeholder
    print("Please load your BRTI data and set up df_brti_indexed before running this script.")
    print("Example:")
    print("df_brti = pd.read_csv('your_data.csv')")
    print("df_brti['datetime'] = pd.to_datetime(df_brti['timestamp_ms'], unit='ms')")
    print("df_brti_indexed = df_brti.set_index('datetime')")
    
    return
    
    # Calculate rolling GARCH volatility
    print("Calculating GARCH volatility forecasts...")
    volatility_df = calculate_rolling_garch_volatility(
        df_brti_indexed=df_brti_indexed,
        lookback_period='4H',      # Use 4 hours of data for GARCH fitting
        forecast_horizon='1H',     # Forecast 1 hour ahead
        step_size='30T',          # Calculate every 30 minutes
        start_date='2024-01-01',  # Adjust to your data range
        end_date='2024-01-31'     # Adjust to your data range
    )
    
    # Save results
    volatility_df.to_csv('garch_volatility_results.csv', index=False)
    print("Results saved to 'garch_volatility_results.csv'")
    
    # Create plots
    plot_garch_volatility_analysis(volatility_df)
    create_volatility_heatmap(volatility_df)
    
    return volatility_df

if __name__ == "__main__":
    main() 