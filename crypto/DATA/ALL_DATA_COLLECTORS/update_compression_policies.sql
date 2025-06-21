-- =================================================================
--  Update TimescaleDB Compression Policies
-- =================================================================
--  This script updates the compression policies for all tables
--  to compress data older than 1 day instead of 7 days.
--
--  Instructions:
--  1. Connect to your database (e.g., using `psql`).
--  2. Run this script: `\i update_compression_policies.sql`
-- =================================================================

-- Remove existing compression policies
SELECT remove_compression_policy('brti_prices');
SELECT remove_compression_policy('kalshi_trades');
SELECT remove_compression_policy('kalshi_orderbooks');
SELECT remove_compression_policy('binance_orderbook_features');
SELECT remove_compression_policy('binance_trades');

-- Add new compression policies with 1 day interval (86400000 milliseconds)
SELECT add_compression_policy('brti_prices', 86400000);
SELECT add_compression_policy('kalshi_trades', 86400000);
SELECT add_compression_policy('kalshi_orderbooks', 86400000);
SELECT add_compression_policy('binance_orderbook_features', 86400000);
SELECT add_compression_policy('binance_trades', 86400000);

-- Verify the new policies
SELECT 
    hypertable_name,
    compress_after
FROM timescaledb_information.compression_settings
WHERE hypertable_name IN (
    'brti_prices',
    'kalshi_trades', 
    'kalshi_orderbooks',
    'binance_orderbook_features',
    'binance_trades'
);

-- Show compression job information
SELECT 
    job_id,
    hypertable_name,
    config
FROM timescaledb_information.jobs 
WHERE proc_name = 'policy_compression'
ORDER BY hypertable_name;

-- =================================================================
--  End of Update Script
-- ================================================================= 