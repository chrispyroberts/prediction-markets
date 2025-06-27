import asyncio
import time
import redis.asyncio as aioredis
import sys
import os

# Add the backend directory to the path for direct execution
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models import BinanceVolSmileData, Heartbeat
from utils.vol_smile_utils import fetch_binance_vol_smile
from feeds import BINANCE_VOL_HEARTBEAT_INTERVAL, BINANCE_VOL_REDIS_URL, BINANCE_VOL_REDIS_CHANNEL, BINANCE_VOL_SCRAPE_INTERVAL
import random

FEED_NAME = "binance_vol_smile"
DATA_CHANNEL = BINANCE_VOL_REDIS_CHANNEL

async def binance_vol_smile_poller(redis):
    while True:
        try:
            (
                fitted_vol_smile, simgoid_0dte_fit, d2_data, binary_price_data,
                moneyness, ivs, tte, atm_vol, atm_vol_1hr, b_fit, c_fit, rev_moneyness, fitting_params, x0_fit, d_fit
            ) = await fetch_binance_vol_smile()

            # Extract function parameters
            # For fitted_vol_smile: vol(k) = atm_vol + b*k + c*k^2
            vol_smile_b = b_fit
            vol_smile_c = c_fit
            
            # For sigmoid_0dte_fit: sigmoid(k) = 1/(1 + exp(-k*(x0 - d)))
            sigmoid_x0 = x0_fit
            sigmoid_d = d_fit

            data = BinanceVolSmileData(
                atm_vol=atm_vol,
                atm_vol_1hr=atm_vol_1hr,
                tte=tte,
                fitted_params={},  # Keep empty for now, we have the specific params
                moneyness=list(moneyness),
                ivs=list(ivs),
                vol_smile_b=vol_smile_b,
                vol_smile_c=vol_smile_c,
                sigmoid_x0=sigmoid_x0,
                sigmoid_d=sigmoid_d,
                rev_moneyness=list(rev_moneyness),
                d2_data=list(d2_data),
                binary_price_data=list(binary_price_data),
                fitting_params=fitting_params,
                timestamp=time.time()
            )
            print(f"ATM Vol: {atm_vol*100:.2f}% ATM Vol 1hr: {atm_vol_1hr*100:.2f}%")
            await redis.publish(DATA_CHANNEL, data.model_dump_json())
        except Exception as e:
            print(f"Error in Binance vol smile poller: {e}")
        await asyncio.sleep(random.uniform(BINANCE_VOL_SCRAPE_INTERVAL-0.1, BINANCE_VOL_SCRAPE_INTERVAL+0.1))

async def heartbeat_publisher(redis):
    while True:
        heartbeat = Heartbeat(feed=FEED_NAME, timestamp=time.time())
        await redis.publish(DATA_CHANNEL, heartbeat.model_dump_json())
        await asyncio.sleep(BINANCE_VOL_HEARTBEAT_INTERVAL)

async def main():
    redis = aioredis.from_url(BINANCE_VOL_REDIS_URL)
    await asyncio.gather(
        binance_vol_smile_poller(redis),
        heartbeat_publisher(redis)
    )

if __name__ == "__main__":
    asyncio.run(main()) 