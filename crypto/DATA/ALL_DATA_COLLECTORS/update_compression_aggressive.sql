-- =================================================================
--  Update to Aggressive Compression: 1 Hour Threshold + Hourly Schedule
-- =================================================================
--  This script updates compression to be very aggressive:
--  - Compress data older than 1 hour (instead of 1 day)
--  - Run compression jobs every hour (instead of daily)

-- First, remove existing compression policies
SELECT remove_compression_policy('brti_prices');
SELECT remove_compression_policy('kalshi_trades');
SELECT remove_compression_policy('kalshi_orderbooks');
SELECT remove_compression_policy('binance_orderbook_features');
SELECT remove_compression_policy('binance_trades');

-- Add new compression policies with 1 hour interval (3600000 milliseconds)
SELECT add_compression_policy('brti_prices', 3600000);
SELECT add_compression_policy('kalshi_trades', 3600000);
SELECT add_compression_policy('kalshi_orderbooks', 3600000);
SELECT add_compression_policy('binance_orderbook_features', 3600000);
SELECT add_compression_policy('binance_trades', 3600000);

-- Get the new job IDs and update their schedules to run every hour
-- (We need to get the new job IDs first)
SELECT 
    'UPDATE SCHEDULE FOR: ' || hypertable_name || ' (Job ID: ' || job_id || ')' as info
FROM timescaledb_information.jobs 
WHERE proc_name = 'policy_compression'
ORDER BY hypertable_name;

-- Update all compression jobs to run every hour
-- (Replace the job IDs below with the actual new job IDs from above)
-- SELECT alter_job(NEW_JOB_ID, schedule_interval => INTERVAL '1 hour');

-- Verify the new settings
SELECT 
    job_id,
    hypertable_name,
    schedule_interval,
    config,
    next_start
FROM timescaledb_information.jobs 
WHERE proc_name = 'policy_compression'
ORDER BY hypertable_name; 