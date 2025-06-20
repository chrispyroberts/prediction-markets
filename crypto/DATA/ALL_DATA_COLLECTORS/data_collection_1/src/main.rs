use anyhow::Result;
use tracing::info;
use tracing_subscriber::EnvFilter;
use std::iter;
use std::fs;
use tokio::signal;
use std::panic;

mod collector;
mod display;
mod models;
mod utils;
mod db;

use collector::BinanceBTCPerpetualDataCollector;
use crate::db::{connect_db, insert_orderbook_features_batch, insert_aggregated_trades_batch};

#[tokio::main]
async fn main() -> Result<()> {
    // Ensure logs directory exists
    let log_dir = "C:\\Users\\chris\\OneDrive\\Desktop\\Programming\\Trading\\prediction markets\\crypto\\DATA\\data_collection_1\\logs";
    fs::create_dir_all(log_dir)?;
    
    // Check if running in unified mode (disable terminal output)
    let disable_terminal_output = std::env::var("BINANCE_DISABLE_TERMINAL").unwrap_or_default() == "true";
    
    // Set up file logging
    let log_file = format!("{}\\data_logs_1.log", log_dir);
    let file_appender = tracing_appender::rolling::never(log_dir, "data_logs_1.log");
    
    // Initialize logging with conditional console output
    let mut builder = tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env()
            .add_directive("binance_collector=info".parse()?)
            .add_directive("info".parse()?))
        .with_target(false)
        .with_file(true)
        .with_line_number(true)
        .with_thread_ids(true)
        .with_thread_names(true)
        .with_writer(file_appender);
    
    // Only add console output if terminal output is enabled
    if !disable_terminal_output {
        builder = builder.with_ansi(true);
    }
    
    builder.init();

    info!("TEST LOG: If you see this, logging is working!");

    info!("🚀 Binance BTC Perpetual Live Order Book & Data Collector");
    info!("📝 Log file: {}", log_file);
    info!("{}", iter::repeat("=").take(60).collect::<String>());

    // For now, default to compact mode (equivalent to choice "2" in Python)
    let display_mode = "compact";
    
    info!("🔄 Starting {} mode...", display_mode);
    tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;
    
    let mut collector = BinanceBTCPerpetualDataCollector::new("btcusdt", display_mode).await?;

    // Set up panic hook to log panics (data flushing is handled in run_with_restart)
    panic::set_hook(Box::new(|panic_info| {
        info!("PANIC_DETECTED | Panic occurred: {:?}", panic_info);
        info!("PANIC_SHUTDOWN | Exiting due to panic");
    }));

    #[cfg(unix)]
    {
        use tokio::signal::unix::{signal, SignalKind};
        let mut sigterm_stream = signal(SignalKind::terminate()).expect("Failed to install SIGTERM handler");
        tokio::select! {
            _ = signal::ctrl_c() => {
                info!("Received SIGINT (Ctrl+C) - initiating graceful shutdown...");
                if let Err(e) = collector.flush_remaining_batches().await {
                    info!("Error flushing batches during shutdown: {}", e);
                }
                info!("Shutdown complete. Exiting.");
            }
            _ = sigterm_stream.recv() => {
                info!("Received SIGTERM - initiating graceful shutdown...");
                if let Err(e) = collector.flush_remaining_batches().await {
                    info!("Error flushing batches during shutdown: {}", e);
                }
                info!("Shutdown complete. Exiting.");
            }
            res = collector.run_with_restart() => {
                if let Err(e) = res {
                    info!("Collector exited with error: {}", e);
                    // Flush data even on error exit
                    if let Err(flush_err) = collector.flush_remaining_batches().await {
                        info!("Error flushing batches after collector error: {}", flush_err);
                    }
                }
            }
        }
    }
    #[cfg(not(unix))]
    {
        // For Windows, we need to handle both Ctrl+C and the terminate signal
        // The unified collector sends SIGTERM, so we need to catch that
        tokio::select! {
            _ = signal::ctrl_c() => {
                info!("Received SIGINT (Ctrl+C) - initiating graceful shutdown...");
                if let Err(e) = collector.flush_remaining_batches().await {
                    info!("Error flushing batches during shutdown: {}", e);
                }
                info!("Shutdown complete. Exiting.");
            }
            res = collector.run_with_restart() => {
                if let Err(e) = res {
                    info!("Collector exited with error: {}", e);
                    // Flush data even on error exit
                    if let Err(flush_err) = collector.flush_remaining_batches().await {
                        info!("Error flushing batches after collector error: {}", flush_err);
                    }
                }
            }
        }
    }
    Ok(())
}
