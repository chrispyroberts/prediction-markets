use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};
use std::collections::HashMap;

/// WebSocket stream message wrapper
#[derive(Debug, Deserialize)]
pub struct StreamMessage {
    pub stream: String,
    pub data: serde_json::Value,
}

/// Order book update data
#[derive(Debug, Deserialize)]
pub struct OrderBookUpdate {
    #[serde(rename = "e")]
    pub event_type: String,
    #[serde(rename = "E")]
    pub event_time: i64,
    #[serde(rename = "s")]
    pub symbol: String,
    #[serde(rename = "U")]
    pub first_update_id: i64,
    #[serde(rename = "u")]
    pub final_update_id: i64,
    #[serde(rename = "b")]
    pub bids: Vec<[String; 2]>,
    #[serde(rename = "a")]
    pub asks: Vec<[String; 2]>,
}

/// Aggregated trade data
#[derive(Debug, Deserialize)]
pub struct AggTrade {
    #[serde(rename = "e")]
    pub event_type: String,
    #[serde(rename = "E")]
    pub event_time: i64,
    #[serde(rename = "s")]
    pub symbol: String,
    #[serde(rename = "p")]
    pub price: String,
    #[serde(rename = "q")]
    pub quantity: String,
    #[serde(rename = "T")]
    pub trade_time: i64,
    #[serde(rename = "m")]
    pub is_buyer_maker: bool,
    #[serde(rename = "a")]
    pub aggregate_trade_id: i64,
    #[serde(rename = "f")]
    pub first_trade_id: i64,
    #[serde(rename = "l")]
    pub last_trade_id: i64,
}

/// Trade information for internal use
#[derive(Debug, Clone)]
pub struct TradeInfo {
    pub price: f64,
    pub quantity: f64,
    pub is_buyer_maker: bool,
    pub trade_count: i64,
    pub receipt_timestamp: i64,
}

/// Order book features for different levels
#[derive(Debug, Clone, Serialize)]
pub struct OrderBookFeatures {
    pub timestamp_est: String,
    pub timestamp_ms: i64,
    // L1 features
    pub bid_l1_price: f64,
    pub bid_l1_cumulative_qty: f64,
    pub bid_l1_weighted_price: f64,
    pub ask_l1_price: f64,
    pub ask_l1_cumulative_qty: f64,
    pub ask_l1_weighted_price: f64,
    pub spread_l1: f64,
    // L5 features
    pub bid_l5_price: f64,
    pub bid_l5_cumulative_qty: f64,
    pub bid_l5_weighted_price: f64,
    pub ask_l5_price: f64,
    pub ask_l5_cumulative_qty: f64,
    pub ask_l5_weighted_price: f64,
    pub spread_l5: f64,
    // L10 features
    pub bid_l10_price: f64,
    pub bid_l10_cumulative_qty: f64,
    pub bid_l10_weighted_price: f64,
    pub ask_l10_price: f64,
    pub ask_l10_cumulative_qty: f64,
    pub ask_l10_weighted_price: f64,
    pub spread_l10: f64,
    // L20 features
    pub bid_l20_price: f64,
    pub bid_l20_cumulative_qty: f64,
    pub bid_l20_weighted_price: f64,
    pub ask_l20_price: f64,
    pub ask_l20_cumulative_qty: f64,
    pub ask_l20_weighted_price: f64,
    pub spread_l20: f64,
}

/// Aggregated trade data for storage
#[derive(Debug, Clone, Serialize)]
pub struct AggregatedTrade {
    pub timestamp_est: String,
    pub timestamp_ms: i64,
    pub sell_volume: f64,
    pub buy_volume: f64,
    pub vwap_sell_price: f64,
    pub vwap_buy_price: f64,
    pub total_volume: f64,
    pub total_trade_count: i64,
}

/// Display mode enum
#[derive(Debug, Clone, PartialEq)]
pub enum DisplayMode {
    Full,
    Compact,
    Silent,
}

impl From<&str> for DisplayMode {
    fn from(s: &str) -> Self {
        match s {
            "full" => DisplayMode::Full,
            "compact" => DisplayMode::Compact,
            "silent" => DisplayMode::Silent,
            _ => DisplayMode::Compact, // Default
        }
    }
} 