# Trading System - Real-time Data Dashboard

A modular trading system with real-time data feeds (BRTI price and Binance volatility smile) using Python, Redis, and PyQt6.

## Architecture

- **Backend**: Data feeds publish to Redis channels
- **DataHub Service**: Aggregates feed data and exposes methods via Redis pub/sub
- **Frontend**: PyQt6 GUI with real-time charts and data displays
- **Communication**: Direct Redis pub/sub (no HTTP overhead)

## Quick Start

### 1. Start Redis
```bash
docker-compose up -d
```

### 2. Test the Setup
```bash
python test_setup.py
```

### 3. Run the System
```bash
python -m backend.main
```

This will:
- Start all data feeds in separate terminals
- Start the DataHub service
- Launch the PyQt6 frontend

## System Components

### Data Feeds
- **BRTI Feed**: Scrapes BRTI price from CF Benchmarks
- **Binance Vol Smile**: Calculates volatility smile from Binance options

### Frontend Windows
- **BRTI Price Chart**: Real-time price chart with historical data
- **Volatility Smile**: Real-time volatility metrics and analysis

### Data Flow
1. Data feeds publish to Redis channels (`brti`, `binance_vol_smile`)
2. DataHub service subscribes to feeds and stores data
3. Frontend subscribes to real-time streams and requests historical data
4. PyQt6 windows display data with live updates

## Features

- **Real-time Updates**: Stream subscription for live data
- **Historical Data**: Periodic polling for chart updates
- **Error Handling**: Graceful error recovery and status display
- **Modular Design**: Easy to add new feeds and windows

## Dependencies

- Python 3.8+
- Redis
- PyQt6
- redis.asyncio
- matplotlib
- playwright (for web scraping)

## Troubleshooting

1. **Redis Connection Failed**: Make sure Redis is running with `docker-compose up -d`
2. **Feed Errors**: Check that all dependencies are installed
3. **Frontend Issues**: Verify PyQt6 is installed and working

## Development

To add a new data feed:
1. Create feed in `backend/feeds/`
2. Add to `FEED_MODEL_MAP` in `datahub.py`
3. Create corresponding frontend window
4. Update `main.py` to start the new feed 