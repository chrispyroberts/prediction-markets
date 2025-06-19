use chrono::{DateTime, TimeZone, Utc};
use chrono_tz::US::Eastern;
use std::time::{SystemTime, UNIX_EPOCH};

/// Convert timestamp in milliseconds to EST string
pub fn timestamp_to_est(timestamp_ms: i64) -> String {
    let dt = Utc.timestamp_millis_opt(timestamp_ms).unwrap();
    let est_time = dt.with_timezone(&Eastern);
    est_time.format("%Y-%m-%d %H:%M:%S.%3f").to_string()
}

/// Get current timestamp in milliseconds
pub fn current_timestamp_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64
}

/// Ensure directory exists, creating it if necessary
pub fn ensure_directory(path: &str) -> std::io::Result<()> {
    std::fs::create_dir_all(path)
}

/// Clear terminal screen
pub fn clear_screen() {
    if cfg!(windows) {
        std::process::Command::new("cmd")
            .args(&["/c", "cls"])
            .status()
            .ok();
    } else {
        std::process::Command::new("clear")
            .status()
            .ok();
    }
}

/// Parse string to f64, returning 0.0 on error
pub fn parse_f64(s: &str) -> f64 {
    s.parse::<f64>().unwrap_or(0.0)
}

/// Calculate weighted average price
pub fn calculate_weighted_price(prices: &[f64], quantities: &[f64]) -> f64 {
    if prices.is_empty() || quantities.is_empty() {
        return 0.0;
    }
    
    let total_value: f64 = prices.iter()
        .zip(quantities.iter())
        .map(|(p, q)| p * q)
        .sum();
    
    let total_quantity: f64 = quantities.iter().sum();
    
    if total_quantity > 0.0 {
        total_value / total_quantity
    } else {
        0.0
    }
} 