use anyhow::Result;
use tracing::{info, Level};
use tracing_subscriber;
use std::iter;

mod collector;
mod display;
mod models;
mod utils;

use collector::BinanceBTCPerpetualDataCollector;

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_max_level(Level::INFO)
        .with_target(false)
        .init();

    info!("🚀 Binance BTC Perpetual Live Order Book & Data Collector");
    info!("{}", iter::repeat("=").take(60).collect::<String>());

    // For now, default to compact mode (equivalent to choice "2" in Python)
    let display_mode = "compact";
    
    info!("🔄 Starting {} mode...", display_mode);
    tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;
    
    let mut collector = BinanceBTCPerpetualDataCollector::new("btcusdt", display_mode)?;
    collector.run_with_restart().await?;

    Ok(())
}
