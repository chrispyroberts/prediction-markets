I'm building some tools for trading and analysis of BTC hourly options on [Kalhsi](https://kalshi.com/events/crypto/hourly).

Here are some of the tools that I've made so far. All of them are built in Python, so the GUI tools are not as fast or robust as I would like them to be, but for now I'm just trying to get an MVP up and running. A goal later on will be to make some sort of visualizer similar to the one Jasper Van Merle made for [IMC's Prosperity challange](https://github.com/jmerle/imc-prosperity-3-visualizer). Lots of the code and data structures I will implement will draw on the work I did during that challange. 

![image](https://github.com/user-attachments/assets/513300b2-b511-4de3-99a5-96e950a41913)

This is a simple local endpoint for me to constantly track the realtime BRTI index, which is what the options track.

![image](https://github.com/user-attachments/assets/24f06494-16ba-43f9-9adc-25710c3b30ee)

A live-data graph that updates in real time with the 60s average of BRTI.

![image](https://github.com/user-attachments/assets/0bdc4bd8-40af-4a37-80d5-2f2901ba0629)

A live-data options chain visualizer that displays top of orderbook bids and asks, including their sizings, moneyness, time to expiry, strike as well as implied volatility. The numbers for IV appear quite large so their needs to be some tinkering done with how that is implemented, but the basic tooling is there. I also added in a graph to see the current volatility smile.

![image](https://github.com/user-attachments/assets/fc32c9c6-12e0-46e5-bf93-b48c2e876f71)

You can also click on any of the contracts in the volatility smile to view that specific market's orderbooks. It will show you the price, size and IV for each of the orders.

My goal is to collect lots of data on this market and analyze it to look for any profitable trading strategies that I can implement, whether it be market making, statistical arbitrage, or whatever else I can cook up. 

So far, I've looked at GBM modelling to determine the price of the contracts. If my understanding is correct, their price is exactly equal to the expected value of the contract at the current moment, which means the price is the probability of that contract expiring ITM. 

![image](https://github.com/user-attachments/assets/01e6b7fd-5ab5-4406-9200-b4154a99c0a9)

![image](https://github.com/user-attachments/assets/41430c21-682d-4f0c-91ea-ee34aab8bbe9)

These were some generated images, and it appears to be a decent model for predicitng, but I definetly need to tweak what volatility I use in the monte carlo simulations. Here I used an annualized volatility of 25% on the underlying to make 1000 simulations at every step, and counted how many times the strike expired ITM as a proxy for the price.

To get the GUI up and running, copy the resporitory to a local directory and run `python brti_listener.py` in a terminal. This will begin tracking and storing the BRTI price information locally. Then run `python gui/main.py` to open the GUI. For the options chain, copy the event ticker on Kahlshi for the BTC hourly contracts. For the contract viewer, copy the specific market.

![image](https://github.com/user-attachments/assets/819edae3-aff9-4813-b3e4-f45e84a181e0)


