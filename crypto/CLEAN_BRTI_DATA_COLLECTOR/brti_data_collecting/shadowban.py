import time

class ShadowBanDetector:
    def __init__(self, timeout=20):
        self.timeout = timeout
        self.last_price_update_time = None

    def update(self):
        self.last_price_update_time = time.time()

    def is_shadow_banned(self):
        if self.last_price_update_time is None:
            return False
        return (time.time() - self.last_price_update_time) > self.timeout

def wait_for_retry(retry_count, wait_time, logger=None):
    if logger:
        logger.info(f"Waiting {wait_time} seconds before retry #{retry_count}...")
    for remaining in range(wait_time, 0, -1):
        if remaining % 30 == 0 or remaining <= 10:
            if logger:
                logger.info(f"Retrying in {remaining} seconds...")
        time.sleep(1) 