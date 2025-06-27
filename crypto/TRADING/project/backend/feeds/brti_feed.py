import asyncio
import time
import redis.asyncio as aioredis
import sys
import os

# Add the backend directory to the path for direct execution
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models import BRTIFeedData, Heartbeat
from feeds import HEARTBEAT_INTERVAL, SCRAPE_INTERVAL, REDIS_URL, REDIS_CHANNEL
from playwright.async_api import async_playwright
import random

async def brti_price_poller(redis):
    url = "https://www.cfbenchmarks.com/data/indices/BRTI"
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )
    max_retries = 5
    base_backoff = 5  # seconds
    while True:
        retry_count = 0
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.set_extra_http_headers({"User-Agent": user_agent})
                await page.goto(url, timeout=20000)
                await page.wait_for_selector("div.leading-6 span", timeout=10000)
                prev_last_updated = None
                while True:
                    try:
                        price_text = await page.locator("div.leading-6 span").first.text_content()
                        locator = page.locator("span:text('Last updated:')")
                        last_updated = await locator.text_content()
                        if price_text and price_text.strip():
                            price = float(price_text.replace("$", "").replace(",", ""))
                            if last_updated and last_updated != prev_last_updated:
                                print(f"BRTI: ${price} Last Updated: {last_updated}")
                                prev_last_updated = last_updated
                                data = BRTIFeedData(price=price, timestamp=time.time())
                                await redis.publish(REDIS_CHANNEL, data.model_dump_json())
                        await asyncio.sleep(random.uniform(SCRAPE_INTERVAL-0.1, SCRAPE_INTERVAL+0.1))
                    except Exception as e:
                        print(f"Error in BRTI price poller inner loop: {e}")
                        await asyncio.sleep(random.uniform(SCRAPE_INTERVAL-0.1, SCRAPE_INTERVAL+0.1))
                    
        except Exception as e:
            retry_count += 1
            backoff = min(base_backoff * retry_count, 60)  # Cap backoff at 60s
            print(f"Error in BRTI price poller session: {e}. Retrying in {backoff} seconds (attempt {retry_count}/{max_retries})")
            await asyncio.sleep(backoff)
            if retry_count >= max_retries:
                print("Max retries reached. Waiting longer before next attempt.")
                await asyncio.sleep(120)
                retry_count = 0  # Reset after long wait

async def heartbeat_publisher(redis):
    while True:
        heartbeat = Heartbeat(feed="brti", timestamp=time.time())
        await redis.publish(REDIS_CHANNEL, heartbeat.model_dump_json())
        await asyncio.sleep(HEARTBEAT_INTERVAL)

async def main():
    redis = aioredis.from_url(REDIS_URL)
    await asyncio.gather(
        brti_price_poller(redis),
        heartbeat_publisher(redis)
    )

if __name__ == "__main__":
    asyncio.run(main())