-- =================================================================
--  Update TimescaleDB Compression Schedule to Every Hour
-- =================================================================
--  This script updates all compression jobs to run every hour
--  instead of the default schedule.

-- Update compression job schedules to run every hour
SELECT alter_job(1010, schedule_interval => INTERVAL '1 hour');  -- brti_prices
SELECT alter_job(1011, schedule_interval => INTERVAL '1 hour');  -- kalshi_trades  
SELECT alter_job(1012, schedule_interval => INTERVAL '1 hour');  -- kalshi_orderbooks
SELECT alter_job(1013, schedule_interval => INTERVAL '1 hour');  -- binance_orderbook_features
SELECT alter_job(1014, schedule_interval => INTERVAL '1 hour');  -- binance_trades

-- Verify the updated schedules
SELECT 
    job_id,
    hypertable_name,
    schedule_interval,
    next_start,
    last_run_started_at
FROM timescaledb_information.jobs 
WHERE proc_name = 'policy_compression'
ORDER BY hypertable_name;

-- Show when the next compression jobs will run
SELECT 
    hypertable_name,
    next_start,
    schedule_interval
FROM timescaledb_information.jobs 
WHERE proc_name = 'policy_compression'
ORDER BY hypertable_name; 