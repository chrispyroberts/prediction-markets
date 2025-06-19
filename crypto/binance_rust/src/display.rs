use crate::models::{OrderBookFeatures, TradeInfo, DisplayMode};
use crate::utils::clear_screen;
use chrono::Utc;
use std::time::Instant;
use tracing::info;

/// Handles live updating display in terminal
pub struct LiveOrderBookDisplay {
    start_time: Instant,
}

impl LiveOrderBookDisplay {
    pub fn new() -> Self {
        Self {
            start_time: Instant::now(),
        }
    }
    
    pub fn clear_screen(&self) {
        clear_screen();
    }
    
    pub fn cleanup(&self) {
        // In Rust, we don't need to hide/show cursor like in Python
        // The terminal will handle this automatically
    }
}

impl Default for LiveOrderBookDisplay {
    fn default() -> Self {
        Self::new()
    }
}

/// Display manager for the data collector
pub struct DisplayManager {
    display: Option<LiveOrderBookDisplay>,
    mode: DisplayMode,
    update_count: u64,
    start_time: Instant,
    recent_trade: Option<TradeInfo>,
    last_large_trade: Option<TradeInfo>,
    large_trade_threshold: f64,
}

impl DisplayManager {
    pub fn new(mode: DisplayMode, large_trade_threshold: f64) -> Self {
        Self {
            display: if mode != DisplayMode::Silent {
                Some(LiveOrderBookDisplay::new())
            } else {
                None
            },
            mode,
            update_count: 0,
            start_time: Instant::now(),
            recent_trade: None,
            last_large_trade: None,
            large_trade_threshold,
        }
    }
    
    pub fn increment_update_count(&mut self) {
        self.update_count += 1;
    }
    
    pub fn update_recent_trade(&mut self, trade: TradeInfo) {
        self.recent_trade = Some(trade.clone());
        
        if trade.quantity >= self.large_trade_threshold {
            info!("📊 DISPLAY MANAGER: Large trade tracked: {:.3} BTC @ ${:.2}", 
                  trade.quantity, trade.price);
            self.last_large_trade = Some(trade);
        }
    }
    
    pub fn update_last_large_aggregated_trade(&mut self, aggregated_trade: crate::models::AggregatedTrade) {
        self.last_large_trade = None; // Clear individual large trade
        // Note: We'll need to add a field for aggregated trades in DisplayManager
        info!("📊 DISPLAY MANAGER: Large aggregated trade period: {:.3} BTC total", 
              aggregated_trade.total_volume);
    }
    
    pub fn print_static_header(&self) {
        if self.mode == DisplayMode::Silent {
            return;
        }
        
        info!("✅ Connected to Binance Futures WebSocket");
        info!("📊 Listening for BTCUSDT Perpetual Contract Order Book...");
        info!("🔄 Stream: btcusdt@depth20@100ms (20 levels, 100ms updates)");
        info!("💾 Collecting features: L1, L5, L10, L20");
        info!("{}", "=".repeat(80));
    }
    
    pub fn update_full_display(&self, features: &OrderBookFeatures, orderbook_batch_count: usize, orderbook_batch_size: usize, trade_batch_count: usize, trade_batch_size: usize) {
        if self.mode != DisplayMode::Full {
            return;
        }
        
        if let Some(display) = &self.display {
            display.clear_screen();
        }
        
        let current_time = Utc::now().format("%H:%M:%S.%3f").to_string();
        let uptime = self.start_time.elapsed().as_secs();
        
        let mid_price = (features.ask_l1_price + features.bid_l1_price) / 2.0;
        let spread = features.spread_l1;
        
        info!("[{}] 📊 BTCUSDT PERPETUAL ORDER BOOK & FEATURES", current_time);
        info!("🔄 Updates: {} | Uptime: {}s", self.update_count, uptime);
        info!("💰 Mid Price: ${:.2} | Spread: ${:.2}", mid_price, spread);
        info!("📊 Cumulative Bid Volumes - L1: {:.3} | L5: {:.3} | L10: {:.3} | L20: {:.3} BTC", 
              features.bid_l1_cumulative_qty, features.bid_l5_cumulative_qty, 
              features.bid_l10_cumulative_qty, features.bid_l20_cumulative_qty);
        info!("Batch Status: {}/{} orderbook, {}/{} trades", orderbook_batch_count, orderbook_batch_size, trade_batch_count, trade_batch_size);
        info!("{}", "-".repeat(80));
        // Note: Full order book display would be implemented here
        // For brevity, we'll focus on the compact display
    }
    
    pub fn update_compact_display(&self, features: &OrderBookFeatures, orderbook_batch_count: usize, orderbook_batch_size: usize, trade_batch_count: usize, trade_batch_size: usize, last_large_aggregated_trade: Option<&crate::models::AggregatedTrade>) {
        if self.mode != DisplayMode::Compact {
            return;
        }
        
        if let Some(display) = &self.display {
            display.clear_screen();
        }
        
        let current_time = Utc::now().format("%H:%M:%S").to_string();
        let uptime = self.start_time.elapsed().as_secs();
        
        let mid_price = (features.ask_l1_price + features.bid_l1_price) / 2.0;
        let spread_abs = features.spread_l1;
        
        info!("🚀 BTC PERPETUAL - COMPACT LIVE VIEW WITH FEATURES");
        info!("{}", "=".repeat(80));
        info!("🕐 {} | Updates: {} | Uptime: {}s", current_time, self.update_count, uptime);
        info!("💰 Mid: ${:.2} | Spread: ${:.2}", mid_price, spread_abs);
        info!("Batch Status: {}/{} orderbook, {}/{} trades", orderbook_batch_count, orderbook_batch_size, trade_batch_count, trade_batch_size);
        info!("{}", "=".repeat(80));
        // L1, L5, L10, L20 Data Table
        info!("📊 ORDER BOOK LEVELS - CUMULATIVE QUANTITIES & VWAP");
        info!("{}", "-".repeat(80));
        info!("{:<8} {:<12} {:<12} {:<12} {:<12} {:<10}", 
              "Level", "Bid Qty", "Bid VWAP", "Ask Qty", "Ask VWAP", "Spread");
        info!("{}", "-".repeat(80));
        let levels = [(1, features.bid_l1_cumulative_qty, features.bid_l1_weighted_price, 
                       features.ask_l1_cumulative_qty, features.ask_l1_weighted_price, features.spread_l1),
                      (5, features.bid_l5_cumulative_qty, features.bid_l5_weighted_price,
                       features.ask_l5_cumulative_qty, features.ask_l5_weighted_price, features.spread_l5),
                      (10, features.bid_l10_cumulative_qty, features.bid_l10_weighted_price,
                       features.ask_l10_cumulative_qty, features.ask_l10_weighted_price, features.spread_l10),
                      (20, features.bid_l20_cumulative_qty, features.bid_l20_weighted_price,
                       features.ask_l20_cumulative_qty, features.ask_l20_weighted_price, features.spread_l20)];
        for (level, bid_qty, bid_vwap, ask_qty, ask_vwap, spread) in levels {
            info!("L{:<7} {:<12.3} ${:<11.2} {:<12.3} ${:<11.2} ${:<9.2}", 
                  level, bid_qty, bid_vwap, ask_qty, ask_vwap, spread);
        }
        info!("{}", "-".repeat(80));
        // Best prices for each level
        info!("📈 BEST PRICES BY LEVEL");
        info!("{}", "-".repeat(80));
        info!("{:<8} {:<12} {:<12} {:<12} {:<12}", 
              "Level", "Best Bid", "Best Ask", "Mid Price", "Spread");
        info!("{}", "-".repeat(80));
        let best_prices = [(1, features.bid_l1_price, features.ask_l1_price, features.spread_l1),
                           (5, features.bid_l5_price, features.ask_l5_price, features.spread_l5),
                           (10, features.bid_l10_price, features.ask_l10_price, features.spread_l10),
                           (20, features.bid_l20_price, features.ask_l20_price, features.spread_l20)];
        for (level, best_bid, best_ask, spread) in best_prices {
            let mid = (best_ask + best_bid) / 2.0;
            info!("L{:<7} ${:<11.2} ${:<11.2} ${:<11.2} {:.1}", 
                  level, best_bid, best_ask, mid, spread);
        }
        info!("{}", "-".repeat(80));
        // Volume analysis
        info!("📊 VOLUME ANALYSIS");
        info!("{}", "-".repeat(40));
        let total_bid_l1 = features.bid_l1_cumulative_qty;
        let total_bid_l20 = features.bid_l20_cumulative_qty;
        let total_ask_l1 = features.ask_l1_cumulative_qty;
        let total_ask_l20 = features.ask_l20_cumulative_qty;
        let bid_depth_ratio = if total_bid_l1 > 0.0 { total_bid_l20 / total_bid_l1 } else { 0.0 };
        let ask_depth_ratio = if total_ask_l1 > 0.0 { total_ask_l20 / total_ask_l1 } else { 0.0 };
        info!("Bid L1 vs L20: {:.3} → {:.3} BTC (ratio: {:.1}x)", 
              total_bid_l1, total_bid_l20, bid_depth_ratio);
        info!("Ask L1 vs L20: {:.3} → {:.3} BTC (ratio: {:.1}x)", 
              total_ask_l1, total_ask_l20, ask_depth_ratio);
        // Order book imbalance
        let l1_imbalance = total_bid_l1 - total_ask_l1;
        let l20_imbalance = total_bid_l20 - total_ask_l20;
        let l1_emoji = if l1_imbalance > 0.0 { "🟢" } else if l1_imbalance < 0.0 { "🔴" } else { "⚪" };
        let l20_emoji = if l20_imbalance > 0.0 { "🟢" } else if l20_imbalance < 0.0 { "🔴" } else { "⚪" };
        info!("L1 Imbalance: {} {:+.3} BTC", l1_emoji, l1_imbalance);
        info!("L20 Imbalance: {} {:+.3} BTC", l20_emoji, l20_imbalance);
        // Recent trade info
        info!("💰 RECENT TRADE");
        info!("{}", "-".repeat(25));
        if let Some(trade) = &self.recent_trade {
            let trade_type = if trade.is_buyer_maker { "SELL" } else { "BUY" };
            let trade_emoji = if trade.is_buyer_maker { "🔴" } else { "🟢" };
            info!("{} {}: {:.3} BTC @ ${:.2}", 
                  trade_emoji, trade_type, trade.quantity, trade.price);
        } else {
            info!("No trades yet");
        }
        // Last large aggregated trade period info
        info!("🚨 LAST LARGE AGGREGATED PERIOD (>{} BTC total)", self.large_trade_threshold);
        info!("{}", "-".repeat(45));
        if let Some(aggregated_trade) = last_large_aggregated_trade {
            let imbalance = aggregated_trade.buy_volume - aggregated_trade.sell_volume;
            let imbalance_emoji = if imbalance > 0.0 { "🟢" } else if imbalance < 0.0 { "🔴" } else { "⚪" };
            info!("{} Total: {:.3} BTC | Buy: {:.3} | Sell: {:.3} | Trades: {}", 
                  imbalance_emoji, aggregated_trade.total_volume, aggregated_trade.buy_volume, 
                  aggregated_trade.sell_volume, aggregated_trade.total_trade_count);
            info!("   VWAP Buy: ${:.2} | VWAP Sell: ${:.2} | Time: {}", 
                  aggregated_trade.vwap_buy_price, aggregated_trade.vwap_sell_price, aggregated_trade.timestamp_est);
        } else {
            info!("No large aggregated periods (>{} BTC total) yet", self.large_trade_threshold);
        }
        info!("{}", "=".repeat(80));
    }
    
    pub fn get_update_count(&self) -> u64 {
        self.update_count
    }
    
    pub fn get_mode(&self) -> &DisplayMode {
        &self.mode
    }
} 