-- =================================================================
--  TimescaleDB Compression Monitoring Queries
-- =================================================================
--  Use these queries to monitor compression performance and effectiveness

-- 1. Check compression job status and timing
SELECT 
    job_id,
    hypertable_name,
    last_run_started_at,
    last_successful_finish,
    total_runs,
    total_successes,
    total_failures
FROM timescaledb_information.jobs 
WHERE proc_name = 'policy_compression'
ORDER BY hypertable_name;

-- 2. Check compression statistics for each table
SELECT 
    hypertable_name,
    compression_status,
    uncompressed_total_size,
    compressed_total_size,
    compression_ratio
FROM timescaledb_information.compression_settings
ORDER BY hypertable_name;

-- 3. Check chunk compression status
SELECT 
    hypertable_name,
    chunk_name,
    compression_status,
    uncompressed_total_size,
    compressed_total_size
FROM timescaledb_information.chunks
WHERE compression_status IS NOT NULL
ORDER BY hypertable_name, chunk_name;

-- 4. Monitor compression job performance
SELECT 
    job_id,
    hypertable_name,
    config,
    next_start,
    last_run_duration
FROM timescaledb_information.jobs 
WHERE proc_name = 'policy_compression'
ORDER BY hypertable_name;

-- 5. Check overall database size and compression savings
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) as index_size
FROM pg_tables 
WHERE schemaname = 'public' 
AND tablename IN ('brti_prices', 'kalshi_trades', 'kalshi_orderbooks', 'binance_orderbook_features', 'binance_trades')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- 6. Check recent compression activity
SELECT 
    hypertable_name,
    chunk_name,
    compression_status,
    uncompressed_total_size,
    compressed_total_size,
    CASE 
        WHEN uncompressed_total_size > 0 
        THEN ROUND((1 - compressed_total_size::float / uncompressed_total_size::float) * 100, 2)
        ELSE 0 
    END as compression_savings_percent
FROM timescaledb_information.chunks
WHERE compression_status = 'compressed'
ORDER BY hypertable_name, chunk_name; 