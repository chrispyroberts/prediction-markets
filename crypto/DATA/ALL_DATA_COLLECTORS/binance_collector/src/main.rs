use anyhow::Result;
use tracing::info;
use tracing_subscriber::EnvFilter;
use std::iter;
use std::fs;

mod collector;
mod display;
mod models;
mod utils;

use collector::BinanceBTCPerpetualDataCollector;

#[tokio::main]
async fn main() -> Result<()> {
    // Ensure logs directory exists
    let log_dir = "C:\\Users\\chris\\OneDrive\\Desktop\\Programming\\Trading\\prediction markets\\crypto\\DATA\\ALL_DATA_COLLECTORS\\logs";
    fs::create_dir_all(log_dir)?;
    
    // Set up file logging
    let log_file = format!("{}\\binance_collector.log", log_dir);
    let file_appender = tracing_appender::rolling::never(log_dir, "binance_collector.log");
    
    // Initialize logging with both console and file output
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env()
            .add_directive("binance_collector=warn".parse()?)
            .add_directive("warn".parse()?))
        .with_target(false)
        .with_file(true)
        .with_line_number(true)
        .with_thread_ids(true)
        .with_thread_names(true)
        .with_writer(file_appender)
        .init();

    info!("🚀 Binance BTC Perpetual Live Order Book & Data Collector");
    info!("📝 Log file: {}", log_file);
    info!("{}", iter::repeat("=").take(60).collect::<String>());

    // For now, default to compact mode (equivalent to choice "2" in Python)
    let display_mode = "compact";
    
    info!("🔄 Starting {} mode...", display_mode);
    tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;
    
    let mut collector = BinanceBTCPerpetualDataCollector::new("btcusdt", display_mode)?;
    collector.run_with_restart().await?;

    Ok(())
}
