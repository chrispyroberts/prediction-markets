So far, I've looked at GBM modelling to determine the price of the contracts. If my understanding is correct, their price is exactly equal to the expected value of the contract at the current moment, which means the price is the probability of that contract expiring ITM. 

![image](https://github.com/user-attachments/assets/01e6b7fd-5ab5-4406-9200-b4154a99c0a9)

![image](https://github.com/user-attachments/assets/41430c21-682d-4f0c-91ea-ee34aab8bbe9)

These were some generated images, and it appears to be a decent model for predicitng, but I definetly need to tweak what volatility I use in the monte carlo simulations. Here I used an annualized volatility of 25% on the underlying to make 1000 simulations at every step, and counted how many times the strike expired ITM as a proxy for the price.

Implied volatility generally changes as we get closer to expiration, so I added in a scaling factor that depends on the time to expiration

<pre> ```python def effective_sigma(T, sigma_annual, beta=0.01, floor=0.05, T0=30/365): # Avoid negative or zero T if T <= 0: return sigma_annual * floor scaling = (T / T0) ** beta return sigma_annual * max(scaling, floor) ``` </pre>

![image](https://github.com/user-attachments/assets/57cf6254-9f3a-4c26-829c-97a445ac1735)

This introduces new hyperparameters that must be tuned, specifically the beta decay factor and the floor. The idea would be I would use the [CF Bitcoin volatility Real time Index](https://www.cfbenchmarks.com/data/indices/BVX) and scrape this data every second, then use it as the base implied vol. This seems like a promising approach.

![image](https://github.com/user-attachments/assets/781eb3cb-94d6-4824-987b-64acb03b752a)

