# BRTI Data Collector

## Overview

This script provides robust, automated collection of the Bitcoin Real Time Index (BRTI) from CF Benchmarks. It is designed for reliability, production use, and efficient data storage, with advanced features for error handling, shadow ban detection, and detailed logging.

## Features

- **Automated BRTI Data Collection**: Uses Playwright to poll the BRTI price at high frequency.
- **Shadow Ban Detection**: Monitors for periods of missing data and automatically retries with backoff to avoid shadow bans.
- **Batched Parquet Storage**: Efficiently stores price data in Parquet format with Snappy compression for fast analytics and minimal disk usage.
- **Session and Failure Logging**: Comprehensive logging of all sessions, failures, retries, and shadow ban events to a dedicated log file.
- **Thread-Safe Batching**: Uses threading locks to ensure data integrity during concurrent batch writes.
- **Timezone Handling**: All timestamps are stored in EST and as Unix milliseconds for compatibility.

## Requirements

- Python 3.8+
- [Playwright](https://playwright.dev/python/) (`pip install playwright`)
- pandas
- numpy
- pytz

To install Playwright browsers (required for first use):

```bash
playwright install
```

## Usage

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Run the data collector:

```bash
python main.py
```

3. Data will be written to `data/brti_price_data.parquet` and logs to `logs/brti_backoff_analysis.log`.

## Output

- **Parquet File**: Contains columns for EST timestamp, Unix timestamp (ms), BRTI price, and a rolling simple average.
- **Log File**: Detailed session, error, and retry logs for monitoring and debugging.

## Unique Functionalities

- **Automatic Recovery**: The script will automatically attempt to recover from shadow bans and connection failures, with configurable retry logic.
- **Detailed Metrics**: Each session is logged with duration, update frequency, and reason for termination.
- **Production-Ready Logging**: All operational events are logged using Python's logging module for easy integration with monitoring systems.

## Customization

You can adjust batch size, shadow ban timeout, and retry logic by modifying the parameters in the `BRTIDataCollector` class.

## License

MIT License. See LICENSE file for details. 