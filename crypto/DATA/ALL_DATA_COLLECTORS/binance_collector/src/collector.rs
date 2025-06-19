use crate::models::{
    AggTrade, AggregatedTrade, DisplayMode, OrderBookFeatures, OrderBookUpdate, 
    StreamMessage, TradeInfo
};
use crate::display::DisplayManager;
use crate::utils::{current_timestamp_ms, ensure_directory, timestamp_to_est, calculate_weighted_price, parse_f64};
use anyhow::{Result};
use parking_lot::Mutex;
use polars::prelude::*;
use std::sync::Arc;
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use tracing::{error, info, warn};
use url::Url;
use futures::StreamExt;

/// Main data collector for Binance BTC perpetual futures
pub struct BinanceBTCPerpetualDataCollector {
    symbol: String,
    ws_url: String,
    display_manager: DisplayManager,
    
    // Data collection setup
    update_count: u64,
    start_time: std::time::Instant,
    
    // Trade aggregation buffers
    trade_buffer: Arc<Mutex<Vec<TradeInfo>>>,
    
    // Feature generation for L1, L5, L10, L20
    orderbook_levels: Vec<usize>,
    
    // Parquet batching
    orderbook_batch: Arc<Mutex<Vec<OrderBookFeatures>>>,
    trade_batch: Arc<Mutex<Vec<AggregatedTrade>>>,
    orderbook_batch_size: usize,
    trade_batch_size: usize,
    
    // File paths
    orderbook_parquet: String,
    trade_parquet: String,
    
    // Recent trade tracking
    recent_trade: Arc<Mutex<Option<TradeInfo>>>,
    last_large_trade: Arc<Mutex<Option<TradeInfo>>>,
    last_large_aggregated_trade: Arc<Mutex<Option<AggregatedTrade>>>,
    large_trade_threshold: f64,
    
    // Restart logic
    max_reconnect_attempts: usize,
    reconnect_delay: u64,
    
    // Current orderbook features for display updates
    current_features: Arc<Mutex<Option<OrderBookFeatures>>>,
    
    // Display update counter for reducing choppiness in compact mode
    display_update_counter: Arc<Mutex<u32>>,
}

impl BinanceBTCPerpetualDataCollector {
    pub fn new(symbol: &str, display_mode: &str) -> Result<Self> {
        let collector = Self {
            symbol: symbol.to_lowercase(),
            ws_url: "wss://fstream.binance.com/stream".to_string(),
            display_manager: DisplayManager::new(DisplayMode::from(display_mode), 50.0),
            
            update_count: 0,
            start_time: std::time::Instant::now(),
            
            trade_buffer: Arc::new(Mutex::new(Vec::new())),
            
            orderbook_levels: vec![1, 5, 10, 20],
            
            orderbook_batch: Arc::new(Mutex::new(Vec::new())),
            trade_batch: Arc::new(Mutex::new(Vec::new())),
            orderbook_batch_size: 100,
            trade_batch_size: 100,
            
            orderbook_parquet: "C:\\Users\\chris\\OneDrive\\Desktop\\Programming\\Trading\\prediction markets\\crypto\\DATA\\ALL_DATA_COLLECTORS\\data\\btc_orderbook_features.parquet".to_string(),
            trade_parquet: "C:\\Users\\chris\\OneDrive\\Desktop\\Programming\\Trading\\prediction markets\\crypto\\DATA\\ALL_DATA_COLLECTORS\\data\\perp_trade_raw_data.parquet".to_string(),
            
            recent_trade: Arc::new(Mutex::new(None)),
            last_large_trade: Arc::new(Mutex::new(None)),
            last_large_aggregated_trade: Arc::new(Mutex::new(None)),
            large_trade_threshold: 50.0,
            
            max_reconnect_attempts: 10,
            reconnect_delay: 5,
            
            current_features: Arc::new(Mutex::new(None)),
            
            display_update_counter: Arc::new(Mutex::new(0)),
        };
        
        // Ensure data directory exists
        ensure_directory("../../ALL_DATA_COLLECTORS/data")?;
        
        info!("📊 BTC Perpetual Data Collector initialized");
        info!("💾 Orderbook: {}", collector.orderbook_parquet);
        info!("💰 Trade data: {}", collector.trade_parquet);
        info!("📈 Tracking levels: {:?}", collector.orderbook_levels);
        info!("🔄 Batch sizes: OB={}, Trade={}", 
              collector.orderbook_batch_size, collector.trade_batch_size);
        
        Ok(collector)
    }
    
    /// Generate comprehensive orderbook features for L1, L5, L10, L20
    fn generate_orderbook_features(&self, bids: &[[String; 2]], asks: &[[String; 2]], receipt_timestamp: i64) -> OrderBookFeatures {
        let timestamp_est = timestamp_to_est(receipt_timestamp);
        
        let mut features = OrderBookFeatures {
            timestamp_est,
            timestamp_ms: receipt_timestamp,
            // Initialize with default values
            bid_l1_price: 0.0, bid_l1_cumulative_qty: 0.0, bid_l1_weighted_price: 0.0,
            ask_l1_price: 0.0, ask_l1_cumulative_qty: 0.0, ask_l1_weighted_price: 0.0,
            spread_l1: 0.0,
            bid_l5_price: 0.0, bid_l5_cumulative_qty: 0.0, bid_l5_weighted_price: 0.0,
            ask_l5_price: 0.0, ask_l5_cumulative_qty: 0.0, ask_l5_weighted_price: 0.0,
            spread_l5: 0.0,
            bid_l10_price: 0.0, bid_l10_cumulative_qty: 0.0, bid_l10_weighted_price: 0.0,
            ask_l10_price: 0.0, ask_l10_cumulative_qty: 0.0, ask_l10_weighted_price: 0.0,
            spread_l10: 0.0,
            bid_l20_price: 0.0, bid_l20_cumulative_qty: 0.0, bid_l20_weighted_price: 0.0,
            ask_l20_price: 0.0, ask_l20_cumulative_qty: 0.0, ask_l20_weighted_price: 0.0,
            spread_l20: 0.0,
        };
        
        // Generate features for each level
        for &level in &self.orderbook_levels {
            let max_level = level.min(bids.len()).min(asks.len());
            
            if max_level == 0 {
                continue;
            }
            
            // Bid side features
            let bid_prices: Vec<f64> = bids[..max_level].iter()
                .map(|bid| parse_f64(&bid[0]))
                .collect();
            let bid_quantities: Vec<f64> = bids[..max_level].iter()
                .map(|bid| parse_f64(&bid[1]))
                .collect();
            let bid_cumulative_qty: f64 = bid_quantities.iter().sum();
            let bid_weighted_price = calculate_weighted_price(&bid_prices, &bid_quantities);
            
            // Ask side features
            let ask_prices: Vec<f64> = asks[..max_level].iter()
                .map(|ask| parse_f64(&ask[0]))
                .collect();
            let ask_quantities: Vec<f64> = asks[..max_level].iter()
                .map(|ask| parse_f64(&ask[1]))
                .collect();
            let ask_cumulative_qty: f64 = ask_quantities.iter().sum();
            let ask_weighted_price = calculate_weighted_price(&ask_prices, &ask_quantities);
            
            // Store features based on level
            match level {
                1 => {
                    features.bid_l1_price = bid_prices[0];
                    features.bid_l1_cumulative_qty = bid_cumulative_qty;
                    features.bid_l1_weighted_price = bid_weighted_price;
                    features.ask_l1_price = ask_prices[0];
                    features.ask_l1_cumulative_qty = ask_cumulative_qty;
                    features.ask_l1_weighted_price = ask_weighted_price;
                    features.spread_l1 = ask_prices[0] - bid_prices[0];
                },
                5 => {
                    features.bid_l5_price = bid_prices[level-1];
                    features.bid_l5_cumulative_qty = bid_cumulative_qty;
                    features.bid_l5_weighted_price = bid_weighted_price;
                    features.ask_l5_price = ask_prices[level-1];
                    features.ask_l5_cumulative_qty = ask_cumulative_qty;
                    features.ask_l5_weighted_price = ask_weighted_price;
                    features.spread_l5 = ask_prices[level-1] - bid_prices[level-1];
                },
                10 => {
                    features.bid_l10_price = bid_prices[level-1];
                    features.bid_l10_cumulative_qty = bid_cumulative_qty;
                    features.bid_l10_weighted_price = bid_weighted_price;
                    features.ask_l10_price = ask_prices[level-1];
                    features.ask_l10_cumulative_qty = ask_cumulative_qty;
                    features.ask_l10_weighted_price = ask_weighted_price;
                    features.spread_l10 = ask_prices[level-1] - bid_prices[level-1];
                },
                20 => {
                    features.bid_l20_price = bid_prices[level-1];
                    features.bid_l20_cumulative_qty = bid_cumulative_qty;
                    features.bid_l20_weighted_price = bid_weighted_price;
                    features.ask_l20_price = ask_prices[level-1];
                    features.ask_l20_cumulative_qty = ask_cumulative_qty;
                    features.ask_l20_weighted_price = ask_weighted_price;
                    features.spread_l20 = ask_prices[level-1] - bid_prices[level-1];
                },
                _ => {}
            }
        }
        
        features
    }
    
    /// Write orderbook feature batch to Parquet file
    fn write_orderbook_batch_to_parquet(&self, batch_data: Vec<OrderBookFeatures>) -> Result<()> {
        if batch_data.is_empty() {
            return Ok(());
        }
        
        let start_time = std::time::Instant::now();
        let batch_size = batch_data.len();
        
        warn!("📊 PARQUET_WRITE_START | Orderbook batch | Records: {} | File: {}", 
              batch_size, self.orderbook_parquet);
        
        // Convert to Polars DataFrame
        // Add columns
        let timestamp_est: Vec<String> = batch_data.iter().map(|f| f.timestamp_est.clone()).collect();
        let timestamp_ms: Vec<i64> = batch_data.iter().map(|f| f.timestamp_ms).collect();
        let bid_l1_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l1_price).collect();
        let bid_l1_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.bid_l1_cumulative_qty).collect();
        let bid_l1_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l1_weighted_price).collect();
        let ask_l1_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l1_price).collect();
        let ask_l1_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.ask_l1_cumulative_qty).collect();
        let ask_l1_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l1_weighted_price).collect();
        let spread_l1: Vec<f64> = batch_data.iter().map(|f| f.spread_l1).collect();
        let bid_l5_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l5_price).collect();
        let bid_l5_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.bid_l5_cumulative_qty).collect();
        let bid_l5_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l5_weighted_price).collect();
        let ask_l5_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l5_price).collect();
        let ask_l5_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.ask_l5_cumulative_qty).collect();
        let ask_l5_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l5_weighted_price).collect();
        let spread_l5: Vec<f64> = batch_data.iter().map(|f| f.spread_l5).collect();
        let bid_l10_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l10_price).collect();
        let bid_l10_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.bid_l10_cumulative_qty).collect();
        let bid_l10_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l10_weighted_price).collect();
        let ask_l10_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l10_price).collect();
        let ask_l10_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.ask_l10_cumulative_qty).collect();
        let ask_l10_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l10_weighted_price).collect();
        let spread_l10: Vec<f64> = batch_data.iter().map(|f| f.spread_l10).collect();
        let bid_l20_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l20_price).collect();
        let bid_l20_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.bid_l20_cumulative_qty).collect();
        let bid_l20_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l20_weighted_price).collect();
        let ask_l20_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l20_price).collect();
        let ask_l20_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.ask_l20_cumulative_qty).collect();
        let ask_l20_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l20_weighted_price).collect();
        let spread_l20: Vec<f64> = batch_data.iter().map(|f| f.spread_l20).collect();
        
        let mut new_df = DataFrame::new(vec![
            Series::new("timestamp_est", timestamp_est),
            Series::new("timestamp_ms", timestamp_ms),
            Series::new("bid_l1_price", bid_l1_price),
            Series::new("bid_l1_cumulative_qty", bid_l1_cumulative_qty),
            Series::new("bid_l1_weighted_price", bid_l1_weighted_price),
            Series::new("ask_l1_price", ask_l1_price),
            Series::new("ask_l1_cumulative_qty", ask_l1_cumulative_qty),
            Series::new("ask_l1_weighted_price", ask_l1_weighted_price),
            Series::new("spread_l1", spread_l1),
            Series::new("bid_l5_price", bid_l5_price),
            Series::new("bid_l5_cumulative_qty", bid_l5_cumulative_qty),
            Series::new("bid_l5_weighted_price", bid_l5_weighted_price),
            Series::new("ask_l5_price", ask_l5_price),
            Series::new("ask_l5_cumulative_qty", ask_l5_cumulative_qty),
            Series::new("ask_l5_weighted_price", ask_l5_weighted_price),
            Series::new("spread_l5", spread_l5),
            Series::new("bid_l10_price", bid_l10_price),
            Series::new("bid_l10_cumulative_qty", bid_l10_cumulative_qty),
            Series::new("bid_l10_weighted_price", bid_l10_weighted_price),
            Series::new("ask_l10_price", ask_l10_price),
            Series::new("ask_l10_cumulative_qty", ask_l10_cumulative_qty),
            Series::new("ask_l10_weighted_price", ask_l10_weighted_price),
            Series::new("spread_l10", spread_l10),
            Series::new("bid_l20_price", bid_l20_price),
            Series::new("bid_l20_cumulative_qty", bid_l20_cumulative_qty),
            Series::new("bid_l20_weighted_price", bid_l20_weighted_price),
            Series::new("ask_l20_price", ask_l20_price),
            Series::new("ask_l20_cumulative_qty", ask_l20_cumulative_qty),
            Series::new("ask_l20_weighted_price", ask_l20_weighted_price),
            Series::new("spread_l20", spread_l20),
        ])?;
        
        // Check if file exists and append to it, otherwise create new file
        let file_exists = std::path::Path::new(&self.orderbook_parquet).exists();
        let original_size = if file_exists {
            std::fs::metadata(&self.orderbook_parquet).map(|m| m.len()).unwrap_or(0)
        } else {
            0
        };
        
        if file_exists {
            // Read existing data
            let existing_df = LazyFrame::scan_parquet(&self.orderbook_parquet, Default::default())?.collect()?;
            
            // Concatenate with new data using vstack
            let mut combined_df = existing_df.vstack(&new_df)?;
            
            // Write back to file
            let mut file = std::fs::File::create(&self.orderbook_parquet)?;
            ParquetWriter::new(&mut file).finish(&mut combined_df)?;
        } else {
            // Create new file
            let mut file = std::fs::File::create(&self.orderbook_parquet)?;
            ParquetWriter::new(&mut file).finish(&mut new_df)?;
        }
        
        let write_duration = start_time.elapsed();
        let new_size = std::fs::metadata(&self.orderbook_parquet).map(|m| m.len()).unwrap_or(0);
        let size_increase = new_size - original_size;
        
        warn!("💾 PARQUET_WRITE_COMPLETE | Orderbook batch | Records: {} | Duration: {:?} | File: {} | Size: {} bytes (+{} bytes)", 
              batch_size, write_duration, self.orderbook_parquet, new_size, size_increase);
        
        Ok(())
    }
    
    /// Add orderbook features to batch for Parquet writing
    fn add_orderbook_to_batch(&self, features: OrderBookFeatures) {
        let mut batch = self.orderbook_batch.lock();
        batch.push(features.clone());
        
        // Store current features for display updates
        {
            let mut current = self.current_features.lock();
            *current = Some(features);
        }
        
        if batch.len() >= self.orderbook_batch_size {
            let batch_to_write = batch.clone();
            let batch_size = batch_to_write.len();
            batch.clear();
            
            warn!("📦 BATCH_TRIGGER | Orderbook batch full | Size: {} | Triggering async write", batch_size);
            
            let parquet_path = self.orderbook_parquet.clone();
            let display_mode = self.display_manager.get_mode().clone();
            tokio::task::spawn_blocking(move || {
                if let Err(e) = Self::write_orderbook_batch_to_parquet_static(batch_to_write, &parquet_path, &display_mode) {
                    error!("Failed to write orderbook batch: {}", e);
                }
            });
        }
    }
    
    /// Aggregate trades and add to batch for Parquet writing
    fn aggregate_and_add_to_batch(
        trades: &[TradeInfo],
        trade_batch: &Arc<Mutex<Vec<AggregatedTrade>>>,
        trade_batch_size: usize,
        trade_parquet: &str,
        large_trade_threshold: f64,
        last_large_aggregated_trade: &Arc<Mutex<Option<AggregatedTrade>>>,
    ) {
        let mut sell_volume = 0.0;
        let mut buy_volume = 0.0;
        let mut sell_value = 0.0;
        let mut buy_value = 0.0;
        let mut total_trade_count = 0;
        
        // Use current timestamp if no trades, otherwise use earliest trade timestamp
        let timestamp = if trades.is_empty() {
            current_timestamp_ms()
        } else {
            trades.iter().map(|t| t.receipt_timestamp).min().unwrap_or(0)
        };
        
        for trade in trades {
            let volume = trade.quantity;
            let price = trade.price;
            let value = volume * price;
            
            total_trade_count += trade.trade_count;
            
            if trade.is_buyer_maker {
                sell_volume += volume;
                sell_value += value;
            } else {
                buy_volume += volume;
                buy_value += value;
            }
        }
        
        let vwap_sell_price = if sell_volume > 0.0 { sell_value / sell_volume } else { 0.0 };
        let vwap_buy_price = if buy_volume > 0.0 { buy_value / buy_volume } else { 0.0 };
        let total_volume = sell_volume + buy_volume;
        
        let timestamp_est = timestamp_to_est(timestamp);
        
        let aggregated_trade = AggregatedTrade {
            timestamp_est: timestamp_est.clone(),
            timestamp_ms: timestamp,
            sell_volume,
            buy_volume,
            vwap_sell_price,
            vwap_buy_price,
            total_volume,
            total_trade_count,
        };
        
        // Check if this is a large aggregated trade period
        if total_volume >= large_trade_threshold {
            let mut last_large = last_large_aggregated_trade.lock();
            *last_large = Some(aggregated_trade.clone());
            info!("🚨 LARGE AGGREGATED TRADE PERIOD: {:.3} BTC total {}", total_volume, timestamp_est);
        }
        
        let mut batch = trade_batch.lock();
        batch.push(aggregated_trade);
        
        if batch.len() >= trade_batch_size {
            let batch_to_write = batch.clone();
            batch.clear();
            
            // Write in background thread
            let trade_parquet = trade_parquet.to_string();
            tokio::task::spawn_blocking(move || {
                if let Err(e) = Self::write_trade_batch_to_parquet_static(batch_to_write, &trade_parquet) {
                    error!("Failed to write trade batch: {}", e);
                }
            });
        }
        
        let imbalance = buy_volume - sell_volume;
        let _imbalance_emoji = if imbalance > 0.0 { "🟢" } else if imbalance < 0.0 { "🔴" } else { "⚪" };
        
        if total_volume > 50.0 {
            info!("🚨 LARGE VOLUME PERIOD: {:.3} BTC total {}", total_volume, timestamp_est);
        }
    }
    
    /// Static version for writing trade batches
    fn write_trade_batch_to_parquet_static(batch_data: Vec<AggregatedTrade>, parquet_path: &str) -> Result<()> {
        if batch_data.is_empty() {
            return Ok(());
        }
        
        let start_time = std::time::Instant::now();
        let batch_size = batch_data.len();
        
        warn!("📊 PARQUET_WRITE_START | Trade batch | Records: {} | File: {}", 
              batch_size, parquet_path);
        
        // Convert to Polars DataFrame
        let timestamp_est: Vec<String> = batch_data.iter().map(|t| t.timestamp_est.clone()).collect();
        let timestamp_ms: Vec<i64> = batch_data.iter().map(|t| t.timestamp_ms).collect();
        let sell_volume: Vec<f64> = batch_data.iter().map(|t| t.sell_volume).collect();
        let buy_volume: Vec<f64> = batch_data.iter().map(|t| t.buy_volume).collect();
        let vwap_sell_price: Vec<f64> = batch_data.iter().map(|t| t.vwap_sell_price).collect();
        let vwap_buy_price: Vec<f64> = batch_data.iter().map(|t| t.vwap_buy_price).collect();
        let total_volume: Vec<f64> = batch_data.iter().map(|t| t.total_volume).collect();
        let total_trade_count: Vec<i64> = batch_data.iter().map(|t| t.total_trade_count).collect();
        
        let mut new_df = DataFrame::new(vec![
            Series::new("timestamp_est", timestamp_est),
            Series::new("timestamp_ms", timestamp_ms),
            Series::new("sell_volume", sell_volume),
            Series::new("buy_volume", buy_volume),
            Series::new("vwap_sell_price", vwap_sell_price),
            Series::new("vwap_buy_price", vwap_buy_price),
            Series::new("total_volume", total_volume),
            Series::new("total_trade_count", total_trade_count),
        ])?;
        
        // Check if file exists and append to it, otherwise create new file
        let file_exists = std::path::Path::new(parquet_path).exists();
        let original_size = if file_exists {
            std::fs::metadata(parquet_path).map(|m| m.len()).unwrap_or(0)
        } else {
            0
        };
        
        if file_exists {
            // Read existing data
            let existing_df = LazyFrame::scan_parquet(parquet_path, Default::default())?.collect()?;
            
            // Concatenate with new data using vstack
            let mut combined_df = existing_df.vstack(&new_df)?;
            
            // Write back to file
            let mut file = std::fs::File::create(parquet_path)?;
            ParquetWriter::new(&mut file).finish(&mut combined_df)?;
        } else {
            // Create new file
            let mut file = std::fs::File::create(parquet_path)?;
            ParquetWriter::new(&mut file).finish(&mut new_df)?;
        }
        
        let write_duration = start_time.elapsed();
        let new_size = std::fs::metadata(parquet_path).map(|m| m.len()).unwrap_or(0);
        let size_increase = new_size - original_size;
        
        warn!("💾 PARQUET_WRITE_COMPLETE | Trade batch | Records: {} | Duration: {:?} | File: {} | Size: {} bytes (+{} bytes)", 
              batch_size, write_duration, parquet_path, new_size, size_increase);
        
        info!("💾 TRADE BATCH: Wrote {} records to Parquet", batch_data.len());
        Ok(())
    }
    
    /// Static version for async tasks
    fn write_orderbook_batch_to_parquet_static(
        batch_data: Vec<OrderBookFeatures>, 
        parquet_path: &str, 
        display_mode: &DisplayMode
    ) -> Result<()> {
        if batch_data.is_empty() {
            return Ok(());
        }
        
        let start_time = std::time::Instant::now();
        let batch_size = batch_data.len();
        
        warn!("📊 PARQUET_WRITE_START | Orderbook batch (static) | Records: {} | File: {}", 
              batch_size, parquet_path);
        
        // Convert to Polars DataFrame
        let timestamp_est: Vec<String> = batch_data.iter().map(|f| f.timestamp_est.clone()).collect();
        let timestamp_ms: Vec<i64> = batch_data.iter().map(|f| f.timestamp_ms).collect();
        let bid_l1_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l1_price).collect();
        let bid_l1_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.bid_l1_cumulative_qty).collect();
        let bid_l1_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l1_weighted_price).collect();
        let ask_l1_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l1_price).collect();
        let ask_l1_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.ask_l1_cumulative_qty).collect();
        let ask_l1_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l1_weighted_price).collect();
        let spread_l1: Vec<f64> = batch_data.iter().map(|f| f.spread_l1).collect();
        let bid_l5_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l5_price).collect();
        let bid_l5_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.bid_l5_cumulative_qty).collect();
        let bid_l5_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l5_weighted_price).collect();
        let ask_l5_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l5_price).collect();
        let ask_l5_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.ask_l5_cumulative_qty).collect();
        let ask_l5_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l5_weighted_price).collect();
        let spread_l5: Vec<f64> = batch_data.iter().map(|f| f.spread_l5).collect();
        let bid_l10_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l10_price).collect();
        let bid_l10_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.bid_l10_cumulative_qty).collect();
        let bid_l10_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l10_weighted_price).collect();
        let ask_l10_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l10_price).collect();
        let ask_l10_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.ask_l10_cumulative_qty).collect();
        let ask_l10_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l10_weighted_price).collect();
        let spread_l10: Vec<f64> = batch_data.iter().map(|f| f.spread_l10).collect();
        let bid_l20_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l20_price).collect();
        let bid_l20_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.bid_l20_cumulative_qty).collect();
        let bid_l20_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.bid_l20_weighted_price).collect();
        let ask_l20_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l20_price).collect();
        let ask_l20_cumulative_qty: Vec<f64> = batch_data.iter().map(|f| f.ask_l20_cumulative_qty).collect();
        let ask_l20_weighted_price: Vec<f64> = batch_data.iter().map(|f| f.ask_l20_weighted_price).collect();
        let spread_l20: Vec<f64> = batch_data.iter().map(|f| f.spread_l20).collect();
        
        let mut new_df = DataFrame::new(vec![
            Series::new("timestamp_est", timestamp_est),
            Series::new("timestamp_ms", timestamp_ms),
            Series::new("bid_l1_price", bid_l1_price),
            Series::new("bid_l1_cumulative_qty", bid_l1_cumulative_qty),
            Series::new("bid_l1_weighted_price", bid_l1_weighted_price),
            Series::new("ask_l1_price", ask_l1_price),
            Series::new("ask_l1_cumulative_qty", ask_l1_cumulative_qty),
            Series::new("ask_l1_weighted_price", ask_l1_weighted_price),
            Series::new("spread_l1", spread_l1),
            Series::new("bid_l5_price", bid_l5_price),
            Series::new("bid_l5_cumulative_qty", bid_l5_cumulative_qty),
            Series::new("bid_l5_weighted_price", bid_l5_weighted_price),
            Series::new("ask_l5_price", ask_l5_price),
            Series::new("ask_l5_cumulative_qty", ask_l5_cumulative_qty),
            Series::new("ask_l5_weighted_price", ask_l5_weighted_price),
            Series::new("spread_l5", spread_l5),
            Series::new("bid_l10_price", bid_l10_price),
            Series::new("bid_l10_cumulative_qty", bid_l10_cumulative_qty),
            Series::new("bid_l10_weighted_price", bid_l10_weighted_price),
            Series::new("ask_l10_price", ask_l10_price),
            Series::new("ask_l10_cumulative_qty", ask_l10_cumulative_qty),
            Series::new("ask_l10_weighted_price", ask_l10_weighted_price),
            Series::new("spread_l10", spread_l10),
            Series::new("bid_l20_price", bid_l20_price),
            Series::new("bid_l20_cumulative_qty", bid_l20_cumulative_qty),
            Series::new("bid_l20_weighted_price", bid_l20_weighted_price),
            Series::new("ask_l20_price", ask_l20_price),
            Series::new("ask_l20_cumulative_qty", ask_l20_cumulative_qty),
            Series::new("ask_l20_weighted_price", ask_l20_weighted_price),
            Series::new("spread_l20", spread_l20),
        ])?;
        
        // Check if file exists and append to it, otherwise create new file
        let file_exists = std::path::Path::new(parquet_path).exists();
        let original_size = if file_exists {
            std::fs::metadata(parquet_path).map(|m| m.len()).unwrap_or(0)
        } else {
            0
        };
        
        if file_exists {
            // Read existing data
            let existing_df = LazyFrame::scan_parquet(parquet_path, Default::default())?.collect()?;
            
            // Concatenate with new data using vstack
            let mut combined_df = existing_df.vstack(&new_df)?;
            
            // Write back to file
            let mut file = std::fs::File::create(parquet_path)?;
            ParquetWriter::new(&mut file).finish(&mut combined_df)?;
        } else {
            // Create new file
            let mut file = std::fs::File::create(parquet_path)?;
            ParquetWriter::new(&mut file).finish(&mut new_df)?;
        }
        
        let write_duration = start_time.elapsed();
        let new_size = std::fs::metadata(parquet_path).map(|m| m.len()).unwrap_or(0);
        let size_increase = new_size - original_size;
        
        warn!("💾 PARQUET_WRITE_COMPLETE | Orderbook batch (static) | Records: {} | Duration: {:?} | File: {} | Size: {} bytes (+{} bytes)", 
              batch_size, write_duration, parquet_path, new_size, size_increase);
        
        if display_mode != &DisplayMode::Silent {
            info!("💾 FEATURES BATCH: Wrote {} records to Parquet", batch_data.len());
        }
        Ok(())
    }
    
    /// Update display with current data
    fn update_display(&self) {
        let orderbook_batch_count = self.orderbook_batch.lock().len();
        let trade_batch_count = self.trade_batch.lock().len();
        let orderbook_batch_size = self.orderbook_batch_size;
        let trade_batch_size = self.trade_batch_size;
        let last_large_aggregated_trade_lock = self.last_large_aggregated_trade.lock();
        let last_large_aggregated_trade = last_large_aggregated_trade_lock.as_ref().map(|t| t);
        
        if let Some(features) = self.current_features.lock().clone() {
            match self.display_manager.get_mode() {
                DisplayMode::Full => {
                    self.display_manager.update_full_display(&features, orderbook_batch_count, orderbook_batch_size, trade_batch_count, trade_batch_size);
                }
                DisplayMode::Compact => {
                    // Only update compact display once per second to reduce choppiness
                    let mut counter = self.display_update_counter.lock();
                    *counter += 1;
                    if *counter % 10 == 0 { // Update every 10th call (roughly once per second with 100ms updates)
                        self.display_manager.update_compact_display(&features, orderbook_batch_count, orderbook_batch_size, trade_batch_count, trade_batch_size, last_large_aggregated_trade);
                    }
                }
                DisplayMode::Silent => {}
            }
        }
    }
    
    /// Connect to Binance Futures WebSocket and subscribe to streams
    async fn connect_and_subscribe(&mut self) -> Result<()> {
        let stream_url = format!("{}?streams={}@depth20@100ms/{}@aggTrade", 
                                self.ws_url, self.symbol, self.symbol);
        
        for attempt in 1..=self.max_reconnect_attempts {
            match connect_async(Url::parse(&stream_url)?).await {
                Ok((ws_stream, _)) => {
                    info!("✅ Connected (attempt {})", attempt);
                    self.display_manager.print_static_header();
                    let (_, mut read) = ws_stream.split();
                    while let Some(msg) = read.next().await {
                        match msg {
                            Ok(Message::Text(text)) => {
                                let receipt_timestamp = current_timestamp_ms();
                                self.handle_message(&text, receipt_timestamp).await?;
                            }
                            Ok(Message::Close(_)) => {
                                warn!("WebSocket connection closed");
                                break;
                            }
                            Err(e) => {
                                error!("WebSocket error: {}", e);
                                break;
                            }
                            _ => {}
                        }
                    }
                }
                Err(e) => {
                    error!("❌ Connection Error (attempt {}): {}", attempt, e);
                }
            }
            if attempt < self.max_reconnect_attempts {
                info!("🔄 Reconnecting in {} seconds...", self.reconnect_delay);
                tokio::time::sleep(tokio::time::Duration::from_secs(self.reconnect_delay)).await;
            } else {
                error!("❌ Max reconnection attempts reached");
                break;
            }
        }
        Ok(())
    }
    
    /// Process incoming messages (both orderbook and trade data)
    async fn handle_message(&mut self, message: &str, receipt_timestamp: i64) -> Result<()> {
        match serde_json::from_str::<StreamMessage>(message) {
            Ok(stream_msg) => {
                match stream_msg.stream.as_str() {
                    "btcusdt@depth20@100ms" => {
                        if let Ok(orderbook_data) = serde_json::from_value::<OrderBookUpdate>(stream_msg.data) {
                            self.process_orderbook_update(&orderbook_data, receipt_timestamp).await?;
                        }
                    }
                    "btcusdt@aggTrade" => {
                        if let Ok(trade_data) = serde_json::from_value::<AggTrade>(stream_msg.data) {
                            self.add_trade_to_buffer(&trade_data, receipt_timestamp).await?;
                            // Update display when trade arrives
                            self.update_display();
                        }
                    }
                    _ => {}
                }
            }
            Err(_) => {
                // Try to parse as direct orderbook data
                if let Ok(orderbook_data) = serde_json::from_str::<OrderBookUpdate>(message) {
                    self.process_orderbook_update(&orderbook_data, receipt_timestamp).await?;
                }
            }
        }
        Ok(())
    }
    
    /// Process orderbook update and generate features
    async fn process_orderbook_update(&mut self, data: &OrderBookUpdate, receipt_timestamp: i64) -> Result<()> {
        if data.bids.is_empty() || data.asks.is_empty() {
            return Ok(());
        }
        self.update_count += 1;
        self.display_manager.increment_update_count();
        
        // Aggregate all trades since last orderbook update
        {
            let mut buffer = self.trade_buffer.lock();
            if !buffer.is_empty() {
                Self::aggregate_and_add_to_batch(
                    &buffer,
                    &self.trade_batch,
                    self.trade_batch_size,
                    &self.trade_parquet,
                    self.large_trade_threshold,
                    &self.last_large_aggregated_trade,
                );
                buffer.clear();
            } else {
                // Create empty aggregated trade record for this period
                Self::aggregate_and_add_to_batch(
                    &[],
                    &self.trade_batch,
                    self.trade_batch_size,
                    &self.trade_parquet,
                    self.large_trade_threshold,
                    &self.last_large_aggregated_trade,
                );
            }
        }
        
        // Generate features for all levels
        let features = self.generate_orderbook_features(&data.bids, &data.asks, receipt_timestamp);
        
        // Update current features for display
        {
            let mut current_features = self.current_features.lock();
            *current_features = Some(features.clone());
        }
        
        // Add to batch for storage
        self.add_orderbook_to_batch(features.clone());
        // Update display
        self.update_display();
        Ok(())
    }
    
    /// Add trade to aggregation buffer with receipt timestamp
    async fn add_trade_to_buffer(&mut self, data: &AggTrade, receipt_timestamp: i64) -> Result<()> {
        let trade_info = TradeInfo {
            price: parse_f64(&data.price),
            quantity: parse_f64(&data.quantity),
            is_buyer_maker: data.is_buyer_maker,
            trade_count: data.last_trade_id - data.first_trade_id + 1,
            receipt_timestamp,
        };
        
        // Debug: Log large trades
        if trade_info.quantity >= self.large_trade_threshold {
            info!("🚨 LARGE TRADE DETECTED: {:.3} BTC @ ${:.2} (threshold: {:.1})", 
                  trade_info.quantity, trade_info.price, self.large_trade_threshold);
        }
        
        // Update recent trade tracking
        {
            let mut recent_trade = self.recent_trade.lock();
            *recent_trade = Some(trade_info.clone());
        }
        if trade_info.quantity >= self.large_trade_threshold {
            let mut last_large_trade = self.last_large_trade.lock();
            *last_large_trade = Some(trade_info.clone());
        }
        // Add to buffer
        {
            let mut buffer = self.trade_buffer.lock();
            buffer.push(trade_info.clone());
        }
        // Update display manager (this also handles large trade tracking)
        self.display_manager.update_recent_trade(trade_info);
        Ok(())
    }
    
    /// Flush any remaining data in batches before shutdown
    fn flush_remaining_batches(&self) -> Result<()> {
        info!("🔄 Flushing remaining batches...");
        {
            let batch = self.orderbook_batch.lock();
            if !batch.is_empty() {
                let batch_to_write = batch.clone();
                drop(batch);
                self.write_orderbook_batch_to_parquet(batch_to_write)?;
            }
        }
        {
            let batch = self.trade_batch.lock();
            if !batch.is_empty() {
                let batch_to_write = batch.clone();
                drop(batch);
                Self::write_trade_batch_to_parquet_static(batch_to_write, &self.trade_parquet)?;
            }
        }
        info!("✅ All batches flushed");
        Ok(())
    }
    
    /// Main run loop with automatic restart logic
    pub async fn run_with_restart(&mut self) -> Result<()> {
        loop {
            match self.connect_and_subscribe().await {
                Ok(_) => {
                    info!("Connection completed successfully");
                    break;
                }
                Err(e) => {
                    error!("❌ Unexpected error: {}", e);
                    info!("🔄 Restarting in {} seconds...", self.reconnect_delay);
                    tokio::time::sleep(tokio::time::Duration::from_secs(self.reconnect_delay)).await;
                }
            }
        }
        self.flush_remaining_batches()?;
        Ok(())
    }
} 