So far, I've looked at GBM modelling to determine the price of the contracts. If my understanding is correct, their price is exactly equal to the expected value of the contract at the current moment, which means the price is the probability of that contract expiring ITM. 

![image](https://github.com/user-attachments/assets/01e6b7fd-5ab5-4406-9200-b4154a99c0a9)

![image](https://github.com/user-attachments/assets/41430c21-682d-4f0c-91ea-ee34aab8bbe9)

These were some generated images, and it appears to be a decent model for predicitng, but I definetly need to tweak what volatility I use in the monte carlo simulations. Here I used an annualized volatility of 25% on the underlying to make 1000 simulations at every step, and counted how many times the strike expired ITM as a proxy for the price.

Implied volatility generally changes as we get closer to expiration, so I probably need to adapt this to account for it, rather than using a static value.

