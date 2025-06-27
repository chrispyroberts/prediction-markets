-- =================================================================
--  TimescaleDB Schema for Crypto Data Collectors
-- =================================================================
--  This script contains all commands to set up the database tables
--  for the BRTI, Kalshi, and Binance data collectors.
--
--  Instructions:
--  1. Ensure you have the TimescaleDB extension enabled in your database.
--     (Run `CREATE EXTENSION IF NOT EXISTS timescaledb;` in your PostgreSQL instance)
--  2. Connect to your database (e.g., using `psql`).
--  3. Run this entire script.
-- =================================================================

-- =================================================================
--  Table 1: BRTI Price Data
--  Stores price data from the BRTI index scraper.
-- =================================================================
DROP TABLE IF EXISTS brti_prices CASCADE;
CREATE TABLE brti_prices (
    timestamp_ms           BIGINT            NOT NULL,
    brti_price             DOUBLE PRECISION  NOT NULL,
    simple_average         DOUBLE PRECISION  NOT NULL,
    binance_option_price   DOUBLE PRECISION,
    PRIMARY KEY(timestamp_ms)
);

-- Convert to a hypertable, partitioning by the BIGINT timestamp_ms
-- The interval is one day in milliseconds (24 * 60 * 60 * 1000)
SELECT create_hypertable('brti_prices', 'timestamp_ms', chunk_time_interval => 86400000);

-- Add compression
ALTER TABLE brti_prices SET (timescaledb.compress);
SELECT add_compression_policy('brti_prices', 604800000);

-- =================================================================
--  Table 2: Kalshi Trade Data
--  Stores individual trade data from Kalshi markets.
-- =================================================================
DROP TABLE IF EXISTS kalshi_trades CASCADE;
CREATE TABLE kalshi_trades (
    timestamp_ms    BIGINT            NOT NULL,
    ticker          TEXT              NOT NULL,
    yes_price       INTEGER           NOT NULL,
    count           BIGINT            NOT NULL,
    taker_side      TEXT              NOT NULL,
    trade_value     BIGINT            NOT NULL,
    PRIMARY KEY (timestamp_ms, ticker, yes_price, count, taker_side)
);

-- Convert to a hypertable, partitioning by timestamp_ms
SELECT create_hypertable('kalshi_trades', 'timestamp_ms', chunk_time_interval => 86400000);

-- Add compression, segmenting by ticker for better performance
ALTER TABLE kalshi_trades SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'ticker'
);
SELECT add_compression_policy('kalshi_trades', 604800000);

-- =================================================================
--  Table 3: Kalshi Order Book Data (Top-of-Book)
--  Stores top-of-book order data from Kalshi markets.
-- =================================================================
DROP TABLE IF EXISTS kalshi_orderbooks CASCADE;
CREATE TABLE kalshi_orderbooks (
    timestamp_ms    BIGINT   NOT NULL,
    ticker          TEXT     NOT NULL,
    best_bid        INTEGER  NOT NULL,
    best_bid_qty    BIGINT   NOT NULL,
    best_ask        INTEGER  NOT NULL,
    best_ask_qty    BIGINT   NOT NULL,
    PRIMARY KEY (timestamp_ms, ticker)
);

-- Convert to a hypertable, partitioning by the BIGINT timestamp_ms
SELECT create_hypertable('kalshi_orderbooks', 'timestamp_ms', chunk_time_interval => 86400000);

-- Add compression, segmenting by ticker for better performance
ALTER TABLE kalshi_orderbooks SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'ticker'
);
SELECT add_compression_policy('kalshi_orderbooks', 604800000);

-- =================================================================
--  Table 4: Binance Order Book Features
--  Stores pre-calculated features from the Binance order book.
-- =================================================================
DROP TABLE IF EXISTS binance_orderbook_features CASCADE;
CREATE TABLE binance_orderbook_features (
    timestamp_ms                BIGINT           NOT NULL,

    -- Level 1 Features
    bid_l1_price                DOUBLE PRECISION NOT NULL,
    bid_l1_cumulative_qty       DOUBLE PRECISION NOT NULL,
    bid_l1_weighted_price       DOUBLE PRECISION NOT NULL,
    ask_l1_price                DOUBLE PRECISION NOT NULL,
    ask_l1_cumulative_qty       DOUBLE PRECISION NOT NULL,
    ask_l1_weighted_price       DOUBLE PRECISION NOT NULL,

    -- Level 5 Features
    bid_l5_price                DOUBLE PRECISION NOT NULL,
    bid_l5_cumulative_qty       DOUBLE PRECISION NOT NULL,
    bid_l5_weighted_price       DOUBLE PRECISION NOT NULL,
    ask_l5_price                DOUBLE PRECISION NOT NULL,
    ask_l5_cumulative_qty       DOUBLE PRECISION NOT NULL,
    ask_l5_weighted_price       DOUBLE PRECISION NOT NULL,

    -- Level 10 Features
    bid_l10_price               DOUBLE PRECISION NOT NULL,
    bid_l10_cumulative_qty      DOUBLE PRECISION NOT NULL,
    bid_l10_weighted_price      DOUBLE PRECISION NOT NULL,
    ask_l10_price               DOUBLE PRECISION NOT NULL,
    ask_l10_cumulative_qty      DOUBLE PRECISION NOT NULL,
    ask_l10_weighted_price      DOUBLE PRECISION NOT NULL,

    -- Level 20 Features
    bid_l20_price               DOUBLE PRECISION NOT NULL,
    bid_l20_cumulative_qty      DOUBLE PRECISION NOT NULL,
    bid_l20_weighted_price      DOUBLE PRECISION NOT NULL,
    ask_l20_price               DOUBLE PRECISION NOT NULL,
    ask_l20_cumulative_qty      DOUBLE PRECISION NOT NULL,
    ask_l20_weighted_price      DOUBLE PRECISION NOT NULL,

    PRIMARY KEY (timestamp_ms)
);

-- Convert to a hypertable
SELECT create_hypertable('binance_orderbook_features', 'timestamp_ms', chunk_time_interval => 86400000);

-- Add compression
ALTER TABLE binance_orderbook_features SET (timescaledb.compress);
SELECT add_compression_policy('binance_orderbook_features', 604800000);

-- =================================================================
--  Table 5: Binance Aggregated Trades
--  Stores aggregated trade data from Binance.
-- =================================================================
DROP TABLE IF EXISTS binance_trades CASCADE;
CREATE TABLE binance_trades (
    timestamp_ms        BIGINT            NOT NULL,
    sell_volume         DOUBLE PRECISION  NOT NULL,
    buy_volume          DOUBLE PRECISION  NOT NULL,
    vwap_sell_price     DOUBLE PRECISION  NOT NULL,
    vwap_buy_price      DOUBLE PRECISION  NOT NULL,
    total_volume        DOUBLE PRECISION  NOT NULL,
    total_trade_count   BIGINT            NOT NULL,
    PRIMARY KEY (timestamp_ms)
);

-- Convert to a hypertable
SELECT create_hypertable('binance_trades', 'timestamp_ms', chunk_time_interval => 86400000);

-- Add compression
ALTER TABLE binance_trades SET (timescaledb.compress);
SELECT add_compression_policy('binance_trades', 604800000);

-- =================================================================
--  End of Schema Script
-- ================================================================= 