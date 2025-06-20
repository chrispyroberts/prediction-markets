# Binance BTC Perpetual Data Collector (Rust Port)

This is a Rust port of the original Python Binance BTC perpetual futures data collector. The application connects to Binance's WebSocket API to collect real-time order book and trade data, processes it into features, and stores it in Parquet format.

## Features

- **Real-time Data Collection**: Connects to Binance Futures WebSocket API
- **Order Book Analysis**: Processes 20 levels of order book data
- **Feature Generation**: Calculates features for L1, L5, L10, and L20 levels including:
  - Bid/Ask prices and quantities
  - Cumulative quantities
  - Volume-weighted average prices (VWAP)
  - Bid-Ask spreads
- **Trade Aggregation**: Collects and aggregates trade data
- **Multiple Display Modes**: Full, compact, and silent modes
- **Data Storage**: Saves data to Parquet files for efficient storage and analysis
- **Automatic Reconnection**: Handles connection drops with automatic retry logic

## Architecture

The Rust implementation is organized into several modules:

- **`main.rs`**: Application entry point and initialization
- **`models.rs`**: Data structures and serialization/deserialization
- **`collector.rs`**: Main data collection logic and WebSocket handling
- **`display.rs`**: Terminal display management
- **`utils.rs`**: Utility functions for time conversion and data processing

## Dependencies

### Core Dependencies
- **tokio**: Async runtime for concurrent operations
- **tokio-tungstenite**: WebSocket client for real-time data
- **serde/serde_json**: JSON serialization/deserialization
- **polars**: Data manipulation and Parquet file handling (replaces pandas)
- **chrono**: Time handling and timezone conversion
- **anyhow**: Error handling
- **tracing**: Logging and observability

### Additional Dependencies
- **parking_lot**: Fast mutex implementation
- **futures**: Async utilities
- **url**: URL parsing for WebSocket connections

## Installation

1. Ensure you have Rust installed (version 1.70+ recommended)
2. Clone the repository
3. Navigate to the project directory
4. Build the project:

```bash
cargo build --release
```

## Usage

Run the application:

```bash
cargo run --release
```

The application will:
1. Connect to Binance Futures WebSocket
2. Subscribe to BTCUSDT order book and trade streams
3. Display real-time data in the terminal
4. Save processed data to Parquet files in the `better_data/` directory

## Data Output

### Order Book Features (`btc_orderbook_features.parquet`)
Contains processed order book data with features for each level (L1, L5, L10, L20):
- Timestamp (EST and UTC)
- Bid/Ask prices and quantities
- Cumulative quantities
- Volume-weighted average prices
- Bid-Ask spreads

### Trade Data (`perp_trade_raw_data.parquet`)
Contains aggregated trade data:
- Timestamp
- Buy/Sell volumes
- VWAP prices
- Total trade counts

## Display Modes

- **Full Mode**: Complete order book display with all levels
- **Compact Mode**: Summary view with key metrics and features
- **Silent Mode**: No terminal output, data collection only

## Performance Optimizations

The Rust implementation provides several performance improvements over the Python version:

1. **Memory Safety**: Rust's ownership system prevents memory leaks and data races
2. **Zero-Cost Abstractions**: Efficient async/await implementation
3. **Fast Data Processing**: Optimized data structures and algorithms
4. **Efficient Storage**: Parquet format with compression
5. **Concurrent Processing**: Background tasks for data writing

## Error Handling

The application includes comprehensive error handling:
- WebSocket connection failures with automatic retry
- JSON parsing errors
- File I/O errors
- Graceful shutdown handling

## Configuration

Key configuration parameters can be modified in the `BinanceBTCPerpetualDataCollector::new()` method:
- WebSocket URL
- Symbol (default: "btcusdt")
- Batch sizes for data writing
- Reconnection parameters
- Display mode

## Comparison with Python Version

### Major Differences

1. **Language Paradigms**:
   - **Python**: Object-oriented with dynamic typing
   - **Rust**: Systems programming with static typing and ownership

2. **Concurrency**:
   - **Python**: asyncio with cooperative multitasking
   - **Rust**: tokio with true parallelism and zero-cost abstractions

3. **Data Processing**:
   - **Python**: pandas for data manipulation
   - **Rust**: polars for high-performance data processing

4. **Error Handling**:
   - **Python**: Exception-based with try/catch
   - **Rust**: Result-based with explicit error propagation

### Performance Implications

- **Memory Usage**: Significantly lower due to Rust's memory management
- **CPU Usage**: More efficient due to compiled code and zero-cost abstractions
- **Latency**: Lower latency for real-time data processing
- **Throughput**: Higher throughput for data writing and processing

### Library Replacements

| Python Library | Rust Equivalent | Reason |
|----------------|-----------------|---------|
| `pandas` | `polars` | Better performance, native Rust implementation |
| `asyncio` | `tokio` | More efficient async runtime |
| `websockets` | `tokio-tungstenite` | Better integration with tokio |
| `json` | `serde` | Type-safe serialization |
| `datetime` | `chrono` | More comprehensive time handling |

## Development

### Building for Development

```bash
cargo build
```

### Running Tests

```bash
cargo test
```

### Code Formatting

```bash
cargo fmt
```

### Linting

```bash
cargo clippy
```

## License

This project is licensed under the MIT License.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 