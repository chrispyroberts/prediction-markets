import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.optimize import curve_fit
from scipy.interpolate import interp1d
import warnings

warnings.filterwarnings('ignore')

def calculate_moneyness(S, K, T):
    """
    Calculate moneyness for binary options.
    M = ln(S/K) / sqrt(T) - this is the standard normalized moneyness.
    """
    return np.log(S / K) / np.sqrt(T)

def fast_implied_vol_binary(S, K, T, price, r=0.0, initial_guess=0.5, max_iter=100, tol=1e-6):
    """
    Fast Newton-Raphson solver for implied volatility of binary options.
    """
    def binary_call_price(sigma):
        d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
        return np.exp(-r*T) * norm.cdf(d1)
    
    def binary_call_vega(sigma):
        d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
        return np.exp(-r*T) * norm.pdf(d1) * np.sqrt(T)
    
    from scipy.stats import norm
    
    sigma = initial_guess
    
    for i in range(max_iter):
        price_est = binary_call_price(sigma)
        vega = binary_call_vega(sigma)
        
        if abs(vega) < 1e-10:
            break
            
        sigma_new = sigma - (price_est - price) / vega
        
        if abs(sigma_new - sigma) < tol:
            sigma = sigma_new
            break
            
        sigma = max(0.001, sigma_new)  # Ensure positive volatility
    
    return sigma

def extract_base_iv_methods(kalshi_data, current_price, time_to_expiry):
    """
    Extract base IV using multiple methods from binary options market data.
    
    Args:
        kalshi_data: DataFrame with columns ['strike', 'bid', 'ask', 'last_price']
        current_price: Current underlying price
        time_to_expiry: Time to expiry in years
    
    Returns:
        Dictionary with different base IV estimates
    """
    
    # Calculate mid prices and moneyness
    kalshi_data = kalshi_data.copy()
    kalshi_data['mid_price'] = (kalshi_data['bid'] + kalshi_data['ask']) / 2
    kalshi_data['moneyness'] = calculate_moneyness(current_price, kalshi_data['strike'], time_to_expiry)
    
    # Remove any invalid data
    kalshi_data = kalshi_data.dropna()
    kalshi_data = kalshi_data[kalshi_data['mid_price'] > 0]
    kalshi_data = kalshi_data[kalshi_data['mid_price'] < 1]
    
    if len(kalshi_data) == 0:
        return None
    
    results = {}
    
    # Method 1: Closest to ATM (moneyness closest to 0)
    atm_idx = np.argmin(np.abs(kalshi_data['moneyness']))
    atm_strike = kalshi_data.iloc[atm_idx]['strike']
    atm_price = kalshi_data.iloc[atm_idx]['mid_price']
    
    try:
        atm_iv = fast_implied_vol_binary(current_price, atm_strike, time_to_expiry, atm_price)
        results['closest_to_atm'] = {
            'iv': atm_iv,
            'strike': atm_strike,
            'price': atm_price,
            'moneyness': kalshi_data.iloc[atm_idx]['moneyness']
        }
    except:
        results['closest_to_atm'] = None
    
    # Method 2: Linear interpolation to find true ATM (moneyness = 0)
    try:
        # Sort by moneyness
        sorted_data = kalshi_data.sort_values('moneyness')
        
        # Find straddle points around moneyness = 0
        negative_moneyness = sorted_data[sorted_data['moneyness'] <= 0]
        positive_moneyness = sorted_data[sorted_data['moneyness'] >= 0]
        
        if len(negative_moneyness) > 0 and len(positive_moneyness) > 0:
            # Get closest points on each side
            neg_point = negative_moneyness.iloc[-1]
            pos_point = positive_moneyness.iloc[0]
            
            # Linear interpolation
            weight = abs(neg_point['moneyness']) / (abs(neg_point['moneyness']) + abs(pos_point['moneyness']))
            interpolated_price = weight * pos_point['mid_price'] + (1 - weight) * neg_point['mid_price']
            
            # Calculate IV for interpolated price
            interpolated_iv = fast_implied_vol_binary(current_price, current_price, time_to_expiry, interpolated_price)
            
            results['linear_interpolation'] = {
                'iv': interpolated_iv,
                'price': interpolated_price,
                'moneyness': 0.0
            }
        else:
            results['linear_interpolation'] = None
    except:
        results['linear_interpolation'] = None
    
    # Method 3: Quadratic fit to extract ATM level
    try:
        # Fit quadratic curve: IV = a*M² + b*M + c
        # At M=0 (ATM), IV = c
        valid_data = kalshi_data.dropna()
        
        if len(valid_data) >= 3:
            # Calculate IV for all points
            ivs = []
            for _, row in valid_data.iterrows():
                try:
                    iv = fast_implied_vol_binary(current_price, row['strike'], time_to_expiry, row['mid_price'])
                    ivs.append(iv)
                except:
                    ivs.append(np.nan)
            
            valid_data = valid_data.copy()
            valid_data['iv'] = ivs
            valid_data = valid_data.dropna()
            
            if len(valid_data) >= 3:
                # Fit quadratic curve
                def quadratic_smile(M, a, b, c):
                    return a * M**2 + b * M + c
                
                try:
                    popt, _ = curve_fit(quadratic_smile, valid_data['moneyness'], valid_data['iv'])
                    a, b, c = popt
                    
                    # ATM IV is the constant term (c)
                    atm_price_quad = binary_call_price(current_price, current_price, time_to_expiry, c)
                    
                    results['quadratic_fit'] = {
                        'iv': c,
                        'price': atm_price_quad,
                        'moneyness': 0.0,
                        'smile_params': {'a': a, 'b': b, 'c': c}
                    }
                except:
                    results['quadratic_fit'] = None
            else:
                results['quadratic_fit'] = None
        else:
            results['quadratic_fit'] = None
    except:
        results['quadratic_fit'] = None
    
    # Method 4: Volume-weighted average (if volume data available)
    if 'volume' in kalshi_data.columns:
        try:
            # Weight by volume, but give more weight to ATM options
            weights = kalshi_data['volume'] * np.exp(-np.abs(kalshi_data['moneyness']))
            weights = weights / weights.sum()
            
            weighted_iv = 0
            weighted_price = 0
            
            for _, row in kalshi_data.iterrows():
                try:
                    iv = fast_implied_vol_binary(current_price, row['strike'], time_to_expiry, row['mid_price'])
                    weight = weights[row.name]
                    weighted_iv += iv * weight
                    weighted_price += row['mid_price'] * weight
                except:
                    continue
            
            results['volume_weighted'] = {
                'iv': weighted_iv,
                'price': weighted_price,
                'moneyness': 0.0
            }
        except:
            results['volume_weighted'] = None
    else:
        results['volume_weighted'] = None
    
    # Method 5: Simple average of liquid options
    try:
        # Consider options with reasonable bid-ask spreads as "liquid"
        spread_threshold = 0.05  # 5% spread threshold
        liquid_options = kalshi_data[(kalshi_data['ask'] - kalshi_data['bid']) / kalshi_data['mid_price'] < spread_threshold]
        
        if len(liquid_options) > 0:
            ivs = []
            for _, row in liquid_options.iterrows():
                try:
                    iv = fast_implied_vol_binary(current_price, row['strike'], time_to_expiry, row['mid_price'])
                    ivs.append(iv)
                except:
                    continue
            
            if len(ivs) > 0:
                avg_iv = np.mean(ivs)
                avg_price = liquid_options['mid_price'].mean()
                
                results['liquid_average'] = {
                    'iv': avg_iv,
                    'price': avg_price,
                    'moneyness': 0.0,
                    'num_liquid_options': len(ivs)
                }
            else:
                results['liquid_average'] = None
        else:
            results['liquid_average'] = None
    except:
        results['liquid_average'] = None
    
    return results

def binary_call_price(S, K, T, sigma, r=0.0):
    """Binary call option price using Black-Scholes."""
    from scipy.stats import norm
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    return np.exp(-r*T) * norm.cdf(d1)

def plot_smile_with_base_iv(kalshi_data, current_price, time_to_expiry, base_iv_results):
    """
    Plot the volatility smile with different base IV estimates.
    """
    
    # Calculate moneyness and IV for all options
    kalshi_data = kalshi_data.copy()
    kalshi_data['moneyness'] = calculate_moneyness(current_price, kalshi_data['strike'], time_to_expiry)
    kalshi_data['mid_price'] = (kalshi_data['bid'] + kalshi_data['ask']) / 2
    
    # Calculate IV for each option
    ivs = []
    for _, row in kalshi_data.iterrows():
        try:
            iv = fast_implied_vol_binary(current_price, row['strike'], time_to_expiry, row['mid_price'])
            ivs.append(iv)
        except:
            ivs.append(np.nan)
    
    kalshi_data['iv'] = ivs
    valid_data = kalshi_data.dropna()
    
    if len(valid_data) == 0:
        print("No valid data for plotting")
        return
    
    # Create the plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # Plot 1: Price vs Moneyness
    ax1.scatter(valid_data['moneyness'], valid_data['mid_price'], alpha=0.7, s=50)
    ax1.set_xlabel('Moneyness ln(S/K)/√T')
    ax1.set_ylabel('Binary Option Price')
    ax1.set_title('Binary Option Prices vs Moneyness')
    ax1.grid(True, alpha=0.3)
    ax1.axvline(x=0, color='red', linestyle='--', alpha=0.7, label='ATM (Moneyness=0)')
    ax1.legend()
    
    # Plot 2: IV vs Moneyness (Smile)
    ax2.scatter(valid_data['moneyness'], valid_data['iv']*100, alpha=0.7, s=50, label='Market IV')
    ax2.set_xlabel('Moneyness ln(S/K)/√T')
    ax2.set_ylabel('Implied Volatility (%)')
    ax2.set_title('Volatility Smile with Base IV Estimates')
    ax2.grid(True, alpha=0.3)
    ax2.axvline(x=0, color='red', linestyle='--', alpha=0.7, label='ATM (Moneyness=0)')
    
    # Add base IV estimates
    colors = ['blue', 'green', 'orange', 'purple', 'brown']
    color_idx = 0
    
    for method, result in base_iv_results.items():
        if result is not None:
            ax2.axhline(y=result['iv']*100, color=colors[color_idx], linestyle='-', 
                       alpha=0.8, label=f"{method.replace('_', ' ').title()}: {result['iv']*100:.2f}%")
            color_idx = (color_idx + 1) % len(colors)
    
    ax2.legend()
    plt.tight_layout()
    plt.show()
    
    # Print summary
    print("\n=== Base IV Estimates Summary ===")
    for method, result in base_iv_results.items():
        if result is not None:
            print(f"{method.replace('_', ' ').title()}: {result['iv']*100:.2f}%")
        else:
            print(f"{method.replace('_', ' ').title()}: Failed")

def recommend_base_iv(base_iv_results):
    """
    Recommend the best base IV estimate based on data quality and method reliability.
    """
    
    # Priority order for methods (most reliable first)
    priority_order = [
        'quadratic_fit',
        'linear_interpolation', 
        'closest_to_atm',
        'liquid_average',
        'volume_weighted'
    ]
    
    recommendations = []
    
    for method in priority_order:
        if method in base_iv_results and base_iv_results[method] is not None:
            recommendations.append({
                'method': method,
                'iv': base_iv_results[method]['iv'],
                'priority': priority_order.index(method)
            })
    
    if not recommendations:
        return None
    
    # Sort by priority
    recommendations.sort(key=lambda x: x['priority'])
    
    # Return the best available method
    best = recommendations[0]
    
    print(f"\n=== Recommended Base IV ===")
    print(f"Method: {best['method'].replace('_', ' ').title()}")
    print(f"Base IV: {best['iv']*100:.2f}%")
    
    if len(recommendations) > 1:
        print(f"\nAlternative estimates:")
        for rec in recommendations[1:3]:  # Show top 3
            print(f"  {rec['method'].replace('_', ' ').title()}: {rec['iv']*100:.2f}%")
    
    return best['iv']

# Example usage function
def analyze_market_smile_example():
    """
    Example of how to use the base IV extraction functions.
    """
    
    # Example data structure (replace with your actual Kalshi data)
    example_data = pd.DataFrame({
        'strike': [102000, 102500, 103000, 103500, 104000, 104500, 105000],
        'bid': [0.35, 0.42, 0.48, 0.52, 0.45, 0.38, 0.30],
        'ask': [0.37, 0.44, 0.50, 0.54, 0.47, 0.40, 0.32],
        'last_price': [0.36, 0.43, 0.49, 0.53, 0.46, 0.39, 0.31]
    })
    
    current_price = 103000  # Current BTC price
    time_to_expiry = 1/24   # 1 hour in years
    
    print("Example: Extracting Base IV from Binary Options Market Data")
    print("=" * 60)
    
    # Extract base IV using all methods
    base_iv_results = extract_base_iv_methods(example_data, current_price, time_to_expiry)
    
    # Plot the results
    plot_smile_with_base_iv(example_data, current_price, time_to_expiry, base_iv_results)
    
    # Get recommendation
    recommended_iv = recommend_base_iv(base_iv_results)
    
    return base_iv_results, recommended_iv

if __name__ == "__main__":
    # Run the example
    results, recommended = analyze_market_smile_example() 