import requests
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
import logging
from dateutil import parser
import pytz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FundingDataCollector:
    def __init__(self):
        """
        Collector for BTC-PERP-INTX funding rate and market data
        """
        self.base_url = "https://api.coinbase.com/api/v3/brokerage/market/products"
        self.product_id = "BTC-PERP-INTX"
        
    def get_btc_perp_data(self) -> Optional[Dict]:
        """
        Get BTC-PERP-INTX data from the perpetuals endpoint
        
        Returns:
            Dict containing BTC perpetual data or None if failed
        """
        params = {
            "product_type": "FUTURE",
            "contract_expiry_type": "PERPETUAL"
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"API request failed: {response.status_code}")
                return None
                
            data = response.json()
            products = data.get("products", [])
            
            # Find BTC-PERP-INTX
            for product in products:
                if product.get("product_id") == self.product_id:
                    return product
                    
            logger.error(f"Product {self.product_id} not found in response")
            return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None

    def extract_funding_info(self, product_data: Dict) -> Dict:
        """
        Extract key funding and market information from product data
        
        Args:
            product_data: Product data from API response
            
        Returns:
            Dict with extracted funding information
        """
        if not product_data:
            return {}
        
        # Extract perpetual details
        perpetual_details = product_data.get("future_product_details", {}).get("perpetual_details", {})
        
        # Get current time in UTC
        now_utc = datetime.now(timezone.utc)
        
        # Calculate time to next hour (when funding happens)
        next_hour = now_utc.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        time_diff = next_hour - now_utc
        time_to_funding_minutes = time_diff.total_seconds() / 60
        
        # Format time difference
        minutes = int(time_to_funding_minutes)
        seconds = int((time_to_funding_minutes % 1) * 60)
        
        if minutes > 0:
            time_to_funding = f"{minutes}m {seconds}s"
        else:
            time_to_funding = f"{seconds}s"
        
        # Get next funding time in readable format
        next_funding_utc = next_hour.strftime('%H:%M UTC')
        
        # Extract key information
        funding_info = {
            # Basic product info
            "product_id": product_data.get("product_id"),
            "timestamp": now_utc.isoformat(),
            "timestamp_utc": now_utc.strftime('%Y-%m-%d %H:%M:%S UTC'),
            "price": float(product_data.get("price", 0)),
            "mid_market_price": float(product_data.get("mid_market_price", 0)),
            
            # 24h statistics
            "price_change_24h_pct": float(product_data.get("price_percentage_change_24h", 0)),
            "volume_24h": float(product_data.get("volume_24h", 0)),
            "volume_change_24h_pct": float(product_data.get("volume_percentage_change_24h", 0)),
            "quote_volume_24h": float(product_data.get("approximate_quote_24h_volume", 0)),
            
            # Contract specifications
            "base_increment": float(product_data.get("base_increment", 0)),
            "quote_increment": float(product_data.get("quote_increment", 0)),
            "price_increment": float(product_data.get("price_increment", 0)),
            "quote_min_size": float(product_data.get("quote_min_size", 0)),
            "quote_max_size": float(product_data.get("quote_max_size", 0)),
            
            # Perpetual-specific data
            "open_interest": float(perpetual_details.get("open_interest", 0)),
            "funding_rate": float(perpetual_details.get("funding_rate", 0)),
            "funding_time": perpetual_details.get("funding_time"),  # Keep original API time
            "next_funding_time": next_funding_utc,  # Our calculated next funding
            "time_to_funding": time_to_funding,
            "time_to_funding_minutes": time_to_funding_minutes,
            "max_leverage": float(perpetual_details.get("max_leverage", 0)),
            
            # Status
            "status": product_data.get("status"),
            "trading_disabled": product_data.get("trading_disabled", False),
            "is_disabled": product_data.get("is_disabled", False),
        }
        
        # Calculate funding rate in basis points and annualized
        funding_rate = funding_info["funding_rate"]
        funding_info["funding_rate_bps"] = funding_rate * 10000  # Convert to basis points
        funding_info["funding_rate_annual_pct"] = funding_rate * 365 * 24 * 100  # Assuming hourly funding
        
        return funding_info    

    def collect_data(self) -> Optional[Dict]:
        """
        Collect and process BTC-PERP-INTX data
        
        Returns:
            Processed funding information or None if failed
        """
        # print(f"🔍 Fetching data for {self.product_id}...")
        
        # Get raw data
        raw_data = self.get_btc_perp_data()
        if not raw_data:
            print("❌ Failed to fetch data")
            return None
        
        # Extract funding info
        funding_info = self.extract_funding_info(raw_data)
        
        # print("✅ Data collected successfully")
        return funding_info
    
    def print_funding_summary(self, funding_info: Dict):
        """
        Print a clean summary of funding information
        """
        if not funding_info:
            print("❌ No data to display")
            return
        
        print(f"\n{'='*60}")
        print(f"BTC PERPETUAL FUNDING SUMMARY")
        print(f"{'='*60}")
        print(f"Timestamp: {funding_info['timestamp']}")
        print(f"Product: {funding_info['product_id']}")
        
        print(f"\n📊 PRICING:")
        print(f"  Current Price: ${funding_info['price']:,.2f}")
        print(f"  Mid Market: ${funding_info['mid_market_price']:,.2f}")
        print(f"  24h Change: {funding_info['price_change_24h_pct']:+.4f}%")
        
        print(f"\n📈 VOLUME & INTEREST:")
        print(f"  24h Volume: {funding_info['volume_24h']:,.4f} BTC")
        print(f"  24h Volume Change: {funding_info['volume_change_24h_pct']:+.2f}%")
        print(f"  24h Quote Volume: ${funding_info['quote_volume_24h']:,.2f}")
        print(f"  Open Interest: {funding_info['open_interest']:,.4f} BTC")
        
        print(f"\n💰 FUNDING:")
        print(f"  Funding Rate: {funding_info['funding_rate']:.8f}")
        print(f"  Funding Rate (bps): {funding_info['funding_rate_bps']:+.2f}")
        print(f"  Annualized Rate: {funding_info['funding_rate_annual_pct']:+.4f}%")
        print(f"  Next Funding: {funding_info['funding_time']}")
        print(f"  Time to Funding: {funding_info['time_to_funding']}")
            
        print(f"\n⚙️  CONTRACT SPECS:")
        print(f"  Max Leverage: {funding_info['max_leverage']:.0f}x")
        print(f"  Price Increment: ${funding_info['price_increment']}")
        print(f"  Min Order Size: ${funding_info['quote_min_size']}")
        print(f"  Status: {funding_info['status']}")
        
        print(f"{'='*60}")

def continuous_monitoring(interval_seconds: int = 1):
    """
    Continuously monitor funding rates
    
    Args:
        interval_seconds: How often to collect data (default: 5 minutes)
    """
    collector = FundingDataCollector()
    
    print(f"🔄 Starting continuous monitoring every {interval_seconds} seconds")
    print("Press Ctrl+C to stop")
    
    try:
        while True:
            funding_info = collector.collect_data()
            
            if funding_info:
                # Quick summary for continuous monitoring
                rate = funding_info['funding_rate']
                rate_bps = funding_info['funding_rate_bps']
                price = funding_info['price']
                oi = funding_info['open_interest']
                
                print(f"⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} | "
                        f"Price: ${price:,.0f} | "
                        f"Funding: {rate_bps:+.2f}bps | "
                        f"Next: {funding_info['time_to_funding']} | "
                        f"OI: {oi:,.0f} BTC")
            else:
                print(f"❌ {datetime.now().strftime('%H:%M:%S')} | Failed to collect data")
            
            time.sleep(interval_seconds)
            
    except KeyboardInterrupt:
        print(f"\n🛑 Monitoring stopped")

def main():
    """
    Main function to demonstrate usage
    """
    print("BTC-PERP-INTX Funding Data Collector")
    print("=" * 50)
    
    collector = FundingDataCollector()
    
    # Collect current data
    funding_info = collector.collect_data()
    
    if funding_info:
        # Print detailed summary
        collector.print_funding_summary(funding_info)
        
        # Ask if user wants continuous monitoring
        print(f"\n🔄 Start continuous monitoring? (y/n): ", end="")
        try:
            choice = input().lower().strip()
            if choice in ['y', 'yes']:
                continuous_monitoring(interval_seconds=1) 
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
    else:
        print("❌ Failed to collect initial data")

if __name__ == "__main__":
    # Example usage:
    # python funding_collector.py
    
    main()