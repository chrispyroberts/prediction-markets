Using the [CF Bitcoin volatility Real time Index](https://www.cfbenchmarks.com/data/indices/BVX) and scrape this data every second, then use it as the base implied vol seems like a decent starting point.

I use the black scholes formula to calculate the price using the implied volatility as well as a scaling factor to account for changing volatility.




```python
def binary_call_price(S0, K, sigma, r, T):
    if T <= 0 or S0 <= 0 or K <= 0 or sigma <= 0:
        return np.nan
    d2 = (np.log(S0 / K) + (r - 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return np.exp(-r * T) * norm.cdf(d2)

def effective_sigma(T, sigma_annual, beta=0.01, floor=0.05, T0=30/365):
    # Avoid negative or zero T
    if T <= 0:
        return sigma_annual * floor
    scaling = (T / T0) ** beta
    return sigma_annual * max(scaling, floor)
```

Using the current volatlity from the index (43.06%), and tuning the beta parameter to fit, we get this

![image](https://github.com/user-attachments/assets/57cf6254-9f3a-4c26-829c-97a445ac1735)

This introduces new hyperparameters that must be tuned, specifically the beta decay factor and the floor. 

![image](https://github.com/user-attachments/assets/781eb3cb-94d6-4824-987b-64acb03b752a)

Another approach is to model the implied volatility from the market directly using a root solving approach.

```python
def implied_vol_binary_call(S0, K, market_price, r, T, tol=1e-6, max_iter=100):
    # Objective: find sigma such that BS binary call price matches market price
    def objective(sigma):
        return binary_call_price(S0, K, sigma, r, T) - market_price

    try:
        # Use Brent's method between a very small vol and high vol (e.g., 0.001 to 5.0)
        return brentq(objective, 1e-6, 5.0, xtol=tol, maxiter=max_iter)
    except ValueError:
        # No root found within range
        return np.nan
```

Getting the implied volatility of the market then plotting the moneyness versus implied volatility squared * time to expiration (SVI approach), we can get a view of the volatility surface in 2D.

![image](https://github.com/user-attachments/assets/b19f71f5-60d0-4a0b-b1bd-ef9f27744e6f)


