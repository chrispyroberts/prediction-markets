-- =================================================================
--  Aggressive Compression Setup: 1 Hour Threshold + Hourly Schedule
-- =================================================================

-- Step 1: Remove existing compression policies
SELECT remove_compression_policy('brti_prices');
SELECT remove_compression_policy('kalshi_trades');
SELECT remove_compression_policy('kalshi_orderbooks');
SELECT remove_compression_policy('binance_orderbook_features');
SELECT remove_compression_policy('binance_trades');

-- Step 2: Add new compression policies with 1 hour threshold (3600000 ms)
SELECT add_compression_policy('brti_prices', 3600000);
SELECT add_compression_policy('kalshi_trades', 3600000);
SELECT add_compression_policy('kalshi_orderbooks', 3600000);
SELECT add_compression_policy('binance_orderbook_features', 3600000);
SELECT add_compression_policy('binance_trades', 3600000);

-- Step 3: Update all compression jobs to run every hour
-- (This will update all compression jobs to hourly schedule)
DO $$
DECLARE
    job_record RECORD;
BEGIN
    FOR job_record IN 
        SELECT job_id, hypertable_name 
        FROM timescaledb_information.jobs 
        WHERE proc_name = 'policy_compression'
    LOOP
        PERFORM alter_job(job_record.job_id, schedule_interval => INTERVAL '1 hour');
        RAISE NOTICE 'Updated job % for table % to run every hour', job_record.job_id, job_record.hypertable_name;
    END LOOP;
END $$;

-- Step 4: Verify the new configuration
SELECT 
    job_id,
    hypertable_name,
    schedule_interval,
    config,
    next_start
FROM timescaledb_information.jobs 
WHERE proc_name = 'policy_compression'
ORDER BY hypertable_name; 