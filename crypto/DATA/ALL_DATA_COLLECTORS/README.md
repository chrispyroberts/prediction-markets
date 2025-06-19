# Master Data Collector System

This system manages all three data collectors (BRTI, Kalshi, and Binance) with automatic backups and graceful shutdown handling.

## Features

- **Automatic Management**: Starts all three data collectors in separate terminals
- **Automatic Backups**: Creates backups every 30 minutes by default
- **Graceful Shutdown**: Handles Ctrl+C to stop all collectors cleanly
- **Auto-Restart**: Automatically restarts any collector that crashes
- **Comprehensive Logging**: Logs all activities to `logs/master_collector.log`
- **Backup Management**: Keeps the last 10 backups, automatically cleans up old ones

## Directory Structure

```
ALL_DATA_COLLECTORS/
├── master_data_collector.ps1    # Main master script
├── start_all_collectors.bat     # Easy-to-use batch wrapper
├── data/                        # Shared data directory (all parquet files)
├── backups/                     # Automatic backups (timestamped folders)
├── logs/                        # Log files
├── brti_collector/              # BRTI data collector
├── kalshi_collector/            # Kalshi data collector
└── binance_collector/           # Binance data collector (Rust)
```

## Usage

### Quick Start
1. Double-click `start_all_collectors.bat` to start all collectors
2. Press `Ctrl+C` in the master script window to stop all collectors gracefully

### Advanced Usage
```powershell
# Start with default settings (30-minute backups)
.\master_data_collector.ps1

# Start without automatic backups
.\master_data_collector.ps1 -NoBackup

# Start with custom backup interval (modify script)
# Edit $BACKUP_INTERVAL_MINUTES in the script
```

## How It Works

### Startup Process
1. Creates necessary directories (backups, logs)
2. Starts each collector in a separate PowerShell window:
   - **BRTI**: `brti_data_collecting.py`
   - **Kalshi**: `run_kalshi_data.ps1`
   - **Binance**: `binance_rust.exe` (compiled Rust binary)
3. Monitors all collectors for crashes and restarts them automatically

### Backup Process (Every 30 Minutes)
1. Stops all collectors gracefully
2. Waits 5 seconds for file handles to be released
3. Creates timestamped backup of all parquet files
4. Restarts all collectors
5. Cleans up old backups (keeps last 10)

### Shutdown Process
1. Receives Ctrl+C signal
2. Sends graceful shutdown to all collector processes
3. Waits for processes to exit (up to 5 seconds each)
4. Force kills any remaining processes
5. Logs shutdown completion

## Logging

The master script logs all activities to `logs/master_collector.log` with timestamps and log levels:
- `INFO`: Normal operations
- `WARN`: Warnings (collector restarts, etc.)
- `ERROR`: Errors during operation

## Configuration

Edit the configuration section in `master_data_collector.ps1`:

```powershell
# Configuration
$BACKUP_INTERVAL_MINUTES = 30                    # Backup frequency
$GRACEFUL_SHUTDOWN_WAIT_SECONDS = 10            # Wait time for graceful shutdown
$DATA_DIR = "C:\Users\chris\OneDrive\Desktop\Programming\Trading\prediction markets\crypto\DATA\ALL_DATA_COLLECTORS"
$BACKUP_DIR = "$DATA_DIR\backups"               # Backup directory
$LOG_FILE = "$DATA_DIR\logs\master_collector.log" # Log file
```

## Troubleshooting

### Collectors Not Starting
- Check that all collector scripts exist and are executable
- Verify Python is installed and accessible
- For Binance collector, ensure the Rust binary is compiled (`cargo build --release`)

### Backup Issues
- Ensure sufficient disk space for backups
- Check file permissions on backup directory
- Verify parquet files are not locked by other processes

### Graceful Shutdown Issues
- If collectors don't stop gracefully, they will be force-killed after 5 seconds
- Check individual collector logs for shutdown issues

## Individual Collector Scripts

Each collector has its own script that handles its specific data collection:

- **BRTI**: `brti_collector/brti_data_collecting.py`
- **Kalshi**: `kalshi_collector/run_kalshi_data.ps1`
- **Binance**: `binance_collector/target/release/binance_rust.exe`

All collectors save their data to the shared `data/` directory and logs to the shared `logs/` directory.

## Data Files

All parquet files are stored in the shared `data/` directory:
- `brti_price_data.parquet` - BRTI price data
- `kalshi_orderbook_data.parquet` - Kalshi orderbook data
- `kalshi_trade_data.parquet` - Kalshi trade data
- `btc_orderbook_features.parquet` - Binance orderbook features
- `perp_trade_raw_data.parquet` - Binance trade data 