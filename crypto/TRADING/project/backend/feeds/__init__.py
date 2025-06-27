# Config for brti feed
HEARTBEAT_INTERVAL = 1  # seconds
SCRAPE_INTERVAL = 0.4     # seconds
REDIS_URL = "redis://localhost"
REDIS_CHANNEL = "brti" 

# Config for binance_vol_smile feed
BINANCE_VOL_SCRAPE_INTERVAL = 5  # seconds
BINANCE_VOL_HEARTBEAT_INTERVAL = 10  # seconds
BINANCE_VOL_REDIS_URL = "redis://localhost"
BINANCE_VOL_REDIS_CHANNEL = "binance_vol_smile" 

# Config for kalshi feed
KALSHI_REDIS_URL = "redis://localhost"
KALSHI_REDIS_CHANNEL = "kalshi"
KALSHI_HEARTBEAT_INTERVAL = 30.0 