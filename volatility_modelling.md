Using the [CF Bitcoin volatility Real time Index](https://www.cfbenchmarks.com/data/indices/BVX) and scrape this data every second, then use it as the base implied vol seems like a decent starting point.

I use the black scholes formula to calculate the price using the implied volatility

```python
def effective_sigma(T, sigma_annual, beta=0.01, floor=0.05, T0=30/365):
    # Avoid negative or zero T
    if T <= 0:
        return sigma_annual * floor
    scaling = (T / T0) ** beta
    return sigma_annual * max(scaling, floor)
```

![image](https://github.com/user-attachments/assets/57cf6254-9f3a-4c26-829c-97a445ac1735)

This introduces new hyperparameters that must be tuned, specifically the beta decay factor and the floor. The idea would be I would use the 

![image](https://github.com/user-attachments/assets/781eb3cb-94d6-4824-987b-64acb03b752a)

