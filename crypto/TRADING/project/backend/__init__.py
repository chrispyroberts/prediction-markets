FEEDS = ['brti', 'binance_vol_smile', 'kalshi']
FEED_TIMEOUTS = {
    "brti": {"heartbeat": 60.0, "data": 300.0},
    "binance_vol_smile": {"heartbeat": 60.0, "data": 300.0},
    "kalshi": {"heartbeat": 60.0, "data": 300.0},
}

# Config for binance_vol_smile feed
SCRAPE_INTERVAL = 5  # seconds
HEARTBEAT_INTERVAL = 5  # seconds
REDIS_URL = "redis://localhost"
REDIS_CHANNEL = "binance_vol_smile"

# BRTI Feed Configuration
BRTI_REDIS_URL = "redis://localhost"
BRTI_REDIS_CHANNEL = "brti"
BRTI_SCRAPE_INTERVAL = 1.0  # seconds
BRTI_HEARTBEAT_INTERVAL = 30.0  # seconds

# Binance Volatility Smile Feed Configuration
BINANCE_VOL_REDIS_URL = "redis://localhost"
BINANCE_VOL_REDIS_CHANNEL = "binance_vol_smile"
BINANCE_VOL_SCRAPE_INTERVAL = 5.0  # seconds
BINANCE_VOL_HEARTBEAT_INTERVAL = 30.0  # seconds

# Kalshi Feed Configuration
KALSHI_REDIS_URL = "redis://localhost"
KALSHI_REDIS_CHANNEL = "kalshi"
KALSHI_HEARTBEAT_INTERVAL = 30.0  # seconds

# DataHub Configuration
DATAHUB_REDIS_URL = "redis://localhost"
DATAHUB_HEARTBEAT_TIMEOUT = 60.0  # seconds
DATAHUB_DATA_TIMEOUT = 300.0  # seconds 