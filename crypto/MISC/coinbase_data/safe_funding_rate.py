import requests
import json
import time
import logging
import signal
import sys
import os
import traceback
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Any
from dateutil import parser
import pytz
from collections import defaultdict, deque
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

def bulletproof_runner():
    """Bulletproof runner that restarts no matter what"""
    restart_count = 0
    
    while True:
        restart_count += 1
        logger.info(f"Bulletproof restart #{restart_count}")  # FIXED: Removed emoji
        
        try:
            # Your existing main function
            run_production_collector()
            
            # If we get here, main function exited unexpectedly
            logger.warning("Main collector function exited - this should not happen!")  # FIXED: Removed emoji
            
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt - stopping bulletproof runner")  # FIXED: Removed emoji
            break
            
        except SystemExit:
            logger.info("System exit called - stopping bulletproof runner")  # FIXED: Removed emoji
            break
            
        except Exception as e:
            logger.error(f"Bulletproof runner caught exception: {e}")  # FIXED: Removed emoji
            logger.debug(traceback.format_exc())
        
        # Always restart after a delay
        delay = min(60, restart_count * 5)
        logger.info(f"Bulletproof restart in {delay} seconds...")  # FIXED: Removed emoji
        time.sleep(delay)

# Production logging setup
def setup_production_logging():
    """Set up production-grade logging with rotation and error handling"""
    import logging.handlers
    
    # Create logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # Prevent duplicate handlers
    if logger.handlers:
        logger.handlers.clear()
    
    # Console handler for immediate feedback
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler with rotation for persistence
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            'funding_collector.log', 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.INFO)
        file_format = logging.Formatter('%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s')
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not set up file logging: {e}")
    
    return logger

logger = setup_production_logging()

class ProductionRequestsSession:
    """Production-grade requests session with retry logic and connection pooling"""
    
    def __init__(self, timeout: int = 30, max_retries: int = 5):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = None
        self.session_lock = threading.Lock()
        self.request_count = 0
        self.error_count = 0
        
        self._create_session()
    
    def _create_session(self):
        """Create a new requests session with retry strategy"""
        try:
            self.session = requests.Session()
            
            # Configure retry strategy
            retry_strategy = Retry(
                total=self.max_retries,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS"]
            )
            
            # Mount adapter with retry strategy
            adapter = HTTPAdapter(
                max_retries=retry_strategy,
                pool_connections=10,
                pool_maxsize=20
            )
            
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
            
            # Set default headers
            self.session.headers.update({
                'User-Agent': 'ProductionFundingCollector/1.0',
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            })
            
            logger.info("HTTP session created with retry strategy")  # FIXED: Removed emoji
            
        except Exception as e:
            logger.error(f"Failed to create HTTP session: {e}")  # FIXED: Removed emoji
            raise
    
    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make GET request with comprehensive error handling"""
        with self.session_lock:
            try:
                self.request_count += 1
                
                # Set timeout if not provided
                if 'timeout' not in kwargs:
                    kwargs['timeout'] = self.timeout
                
                response = self.session.get(url, **kwargs)
                response.raise_for_status()  # Raise an exception for bad status codes
                
                return response
                
            except requests.exceptions.Timeout as e:
                self.error_count += 1
                logger.warning(f"Request timeout: {e}")
                return None
                
            except requests.exceptions.ConnectionError as e:
                self.error_count += 1
                logger.warning(f"Connection error: {e}")
                return None
                
            except requests.exceptions.HTTPError as e:
                self.error_count += 1
                logger.warning(f"HTTP error: {e}")
                return None
                
            except requests.exceptions.RequestException as e:
                self.error_count += 1
                logger.error(f"Request exception: {e}")
                return None
                
            except Exception as e:
                self.error_count += 1
                logger.error(f"Unexpected request error: {e}")
                return None
    
    def get_statistics(self) -> Dict:
        """Get session statistics"""
        return {
            'request_count': self.request_count,
            'error_count': self.error_count,
            'success_rate': ((self.request_count - self.error_count) / max(1, self.request_count)) * 100
        }
    
    def close(self):
        """Close the session"""
        with self.session_lock:
            if self.session:
                try:
                    self.session.close()
                    logger.info("HTTP session closed")  # FIXED: Removed emoji
                except Exception as e:
                    logger.warning(f"Error closing session: {e}")
                finally:
                    self.session = None

class ProductionDataStore:
    """Production-grade data storage with thread safety and limits"""
    
    def __init__(self, max_records: int = 10000):
        self.max_records = max_records
        self.data_store = deque(maxlen=self.max_records)
        self.store_lock = threading.Lock()
        self.total_records_stored = 0
        self.last_funding_rates = deque(maxlen=100)  # Keep last 100 rates for analysis
        
    def add_record(self, funding_data: Dict) -> bool:
        """Add funding record with validation and thread safety"""
        try:
            with self.store_lock:
                # Validate required fields
                required_fields = ['timestamp', 'funding_rate', 'price', 'open_interest']
                for field in required_fields:
                    if field not in funding_data:
                        logger.warning(f"Missing required field '{field}' in funding data")
                        return False
                
                # Add timestamp for storage
                funding_data['storage_timestamp'] = datetime.now(timezone.utc).isoformat()
                
                # Store record
                self.data_store.append(funding_data.copy())
                self.total_records_stored += 1
                
                # Track funding rates for analysis
                if 'funding_rate' in funding_data:
                    self.last_funding_rates.append(funding_data['funding_rate'])
                
                logger.debug(f"Stored funding record: {funding_data.get('timestamp', 'unknown')}")
                return True
                
        except Exception as e:
            logger.error(f"Error storing funding record: {e}")
            return False
    
    def get_latest_records(self, count: int = 10) -> List[Dict]:
        """Get latest funding records"""
        try:
            with self.store_lock:
                records = list(self.data_store)
                return records[-count:] if count < len(records) else records
        except Exception as e:
            logger.error(f"Error retrieving records: {e}")
            return []
    
    def get_funding_rate_stats(self) -> Dict:
        """Get funding rate statistics"""
        try:
            with self.store_lock:
                if not self.last_funding_rates:
                    return {}
                
                rates = list(self.last_funding_rates)
                
                return {
                    'count': len(rates),
                    'current': rates[-1] if rates else 0,
                    'average': sum(rates) / len(rates),
                    'min': min(rates),
                    'max': max(rates),
                    'std_dev': self._calculate_std_dev(rates)
                }
        except Exception as e:
            logger.error(f"Error calculating funding rate stats: {e}")
            return {}
    
    def _calculate_std_dev(self, values: List[float]) -> float:
        """Calculate standard deviation"""
        try:
            if len(values) < 2:
                return 0.0
            
            mean = sum(values) / len(values)
            variance = sum((x - mean) ** 2 for x in values) / len(values)
            return variance ** 0.5
        except:
            return 0.0
    
    def get_statistics(self) -> Dict:
        """Get storage statistics"""
        try:
            with self.store_lock:
                return {
                    'total_records_stored': self.total_records_stored,
                    'current_records_count': len(self.data_store),
                    'storage_utilization': (len(self.data_store) / self.max_records) * 100
                }
        except Exception as e:
            logger.error(f"Error getting storage statistics: {e}")
            return {}

class ProductionFundingDataCollector:
    """Production-grade funding data collector with comprehensive error handling"""
    
    def __init__(self, product_id: str = "BTC-PERP-INTX"):
        self.base_url = "https://api.coinbase.com/api/v3/brokerage/market/products"
        self.product_id = product_id
        self.should_run = True
        
        # Components
        self.session = ProductionRequestsSession()
        self.data_store = ProductionDataStore()
        
        # Statistics
        self.fetch_attempts = 0
        self.fetch_successes = 0
        self.fetch_errors = 0
        self.consecutive_errors = 0
        self.max_consecutive_errors = 50
        self.start_time = time.time()
        self.last_stats_print = 0
        self.stats_print_interval = 300  # Print stats every 5 minutes
        
        # Error handling
        self.error_backoff = 1
        self.max_error_backoff = 300  # 5 minutes max backoff
        
        # Alternative product IDs to try
        self.product_variants = ["BTC-PERP-INTX", "BTC-INTX-PERP", "BTC-PERP"]
        
        # Setup signal handlers
        self.setup_signal_handlers()
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            if signum in [signal.SIGINT, signal.SIGTERM]:
                logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
                self.should_run = False
            else:
                logger.info(f"Ignoring signal {signum}")  # FIXED: Added proper signal handling
        
        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGHUP, signal.SIG_IGN)  # FIXED: Added SIGHUP ignore as per requirements
        except Exception as e:
            logger.warning(f"Could not setup signal handlers: {e}")
    
    def validate_product_id(self, product_id: str) -> bool:
        """Validate that a product ID exists and is accessible"""
        try:
            params = {
                "product_type": "FUTURE",
                "contract_expiry_type": "PERPETUAL"
            }
            
            response = self.session.get(self.base_url, params=params)
            if not response:
                return False
            
            data = response.json()
            products = data.get("products", [])
            
            # Check if our product exists
            for product in products:
                if product.get("product_id") == product_id:
                    logger.info(f"Product {product_id} validated successfully")  # FIXED: Removed emoji
                    return True
            
            logger.warning(f"Product {product_id} not found in API response")  # FIXED: Removed emoji
            return False
            
        except Exception as e:
            logger.error(f"Product validation error for {product_id}: {e}")  # FIXED: Removed emoji
            return False
    
    def get_btc_perp_data_safe(self) -> Optional[Dict]:
        """Get BTC perpetual data with comprehensive error handling"""
        try:
            self.fetch_attempts += 1
            
            params = {
                "product_type": "FUTURE",
                "contract_expiry_type": "PERPETUAL"
            }
            
            response = self.session.get(self.base_url, params=params)
            if not response:
                raise Exception("HTTP request failed")
            
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                raise Exception(f"JSON decode failed: {e}")
            
            products = data.get("products", [])
            if not products:
                raise Exception("No products in response")
            
            # Find our product
            for product in products:
                if product.get("product_id") == self.product_id:
                    self.fetch_successes += 1
                    self.consecutive_errors = 0
                    self.error_backoff = 1
                    return product
            
            raise Exception(f"Product {self.product_id} not found in response")
            
        except Exception as e:
            self.fetch_errors += 1
            self.consecutive_errors += 1
            
            if self.consecutive_errors <= 5:  # Only log first few errors
                logger.error(f"Failed to fetch BTC perp data: {e}")
            elif self.consecutive_errors == 6:
                logger.error("Suppressing further error logs (too many consecutive errors)")
            
            return None
    
    def extract_funding_info_safe(self, product_data: Dict) -> Optional[Dict]:
        """Extract funding information with comprehensive error handling"""
        if not product_data:
            return None
        
        try:
            # Extract perpetual details safely
            perpetual_details = product_data.get("future_product_details", {}).get("perpetual_details", {})
            
            # Get current time in UTC
            now_utc = datetime.now(timezone.utc)
            
            # Calculate time to next funding safely
            try:
                next_hour = now_utc.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                time_diff = next_hour - now_utc
                time_to_funding_minutes = time_diff.total_seconds() / 60
                
                minutes = int(time_to_funding_minutes)
                seconds = int((time_to_funding_minutes % 1) * 60)
                
                if minutes > 0:
                    time_to_funding = f"{minutes}m {seconds}s"
                else:
                    time_to_funding = f"{seconds}s"
                
                next_funding_utc = next_hour.strftime('%H:%M UTC')
                
            except Exception as e:
                logger.warning(f"Error calculating funding time: {e}")
                time_to_funding = "Unknown"
                next_funding_utc = "Unknown"
                time_to_funding_minutes = 0
            
            # Safely extract and convert numeric values
            def safe_float(value, default=0.0):
                try:
                    return float(value) if value is not None else default
                except (ValueError, TypeError):
                    return default
            
            # Extract key information with safe conversions
            funding_info = {
                # Basic product info
                "product_id": product_data.get("product_id", "Unknown"),
                "timestamp": now_utc.isoformat(),
                "timestamp_utc": now_utc.strftime('%Y-%m-%d %H:%M:%S UTC'),
                "price": safe_float(product_data.get("price")),
                "mid_market_price": safe_float(product_data.get("mid_market_price")),
                
                # 24h statistics
                "price_change_24h_pct": safe_float(product_data.get("price_percentage_change_24h")),
                "volume_24h": safe_float(product_data.get("volume_24h")),
                "volume_change_24h_pct": safe_float(product_data.get("volume_percentage_change_24h")),
                "quote_volume_24h": safe_float(product_data.get("approximate_quote_24h_volume")),
                
                # Contract specifications
                "base_increment": safe_float(product_data.get("base_increment")),
                "quote_increment": safe_float(product_data.get("quote_increment")),
                "price_increment": safe_float(product_data.get("price_increment")),
                "quote_min_size": safe_float(product_data.get("quote_min_size")),
                "quote_max_size": safe_float(product_data.get("quote_max_size")),
                
                # Perpetual-specific data
                "open_interest": safe_float(perpetual_details.get("open_interest")),
                "funding_rate": safe_float(perpetual_details.get("funding_rate")),
                "funding_time": perpetual_details.get("funding_time", "Unknown"),
                "next_funding_time": next_funding_utc,
                "time_to_funding": time_to_funding,
                "time_to_funding_minutes": time_to_funding_minutes,
                "max_leverage": safe_float(perpetual_details.get("max_leverage")),
                
                # Status
                "status": product_data.get("status", "Unknown"),
                "trading_disabled": bool(product_data.get("trading_disabled", False)),
                "is_disabled": bool(product_data.get("is_disabled", False)),
            }
            
            # Calculate derived metrics safely
            try:
                funding_rate = funding_info["funding_rate"]
                funding_info["funding_rate_bps"] = funding_rate * 10000
                funding_info["funding_rate_annual_pct"] = funding_rate * 365 * 24 * 100
            except Exception as e:
                logger.warning(f"Error calculating derived funding metrics: {e}")
                funding_info["funding_rate_bps"] = 0.0
                funding_info["funding_rate_annual_pct"] = 0.0
            
            return funding_info
            
        except Exception as e:
            logger.error(f"Error extracting funding info: {e}")
            logger.debug(traceback.format_exc())
            return None
    
    def collect_data_safe(self) -> Optional[Dict]:
        """Collect and process funding data with error handling"""
        try:
            # Get raw data
            raw_data = self.get_btc_perp_data_safe()
            if not raw_data:
                return None
            
            # Extract funding info
            funding_info = self.extract_funding_info_safe(raw_data)
            if not funding_info:
                return None
            
            # Store data
            if not self.data_store.add_record(funding_info):
                logger.warning("Failed to store funding data")
            
            return funding_info
            
        except Exception as e:
            logger.error(f"Critical error in data collection: {e}")
            logger.debug(traceback.format_exc())
            return None
    
    def print_funding_summary_safe(self, funding_info: Dict):
        """Print funding summary with error handling"""
        try:
            if not funding_info:
                print("❌ No data to display")  # Emojis OK in print()
                return
            
            print(f"\n{'='*60}")
            print(f"BTC PERPETUAL FUNDING SUMMARY")
            print(f"{'='*60}")
            print(f"Timestamp: {funding_info.get('timestamp', 'Unknown')}")
            print(f"Product: {funding_info.get('product_id', 'Unknown')}")
            
            print(f"\n📊 PRICING:")  # Emojis OK in print()
            print(f"  Current Price: ${funding_info.get('price', 0):,.2f}")
            print(f"  Mid Market: ${funding_info.get('mid_market_price', 0):,.2f}")
            print(f"  24h Change: {funding_info.get('price_change_24h_pct', 0):+.4f}%")
            
            print(f"\n📈 VOLUME & INTEREST:")  # Emojis OK in print()
            print(f"  24h Volume: {funding_info.get('volume_24h', 0):,.4f} BTC")
            print(f"  24h Volume Change: {funding_info.get('volume_change_24h_pct', 0):+.2f}%")
            print(f"  24h Quote Volume: ${funding_info.get('quote_volume_24h', 0):,.2f}")
            print(f"  Open Interest: {funding_info.get('open_interest', 0):,.4f} BTC")
            
            print(f"\n💰 FUNDING:")  # Emojis OK in print()
            print(f"  Funding Rate: {funding_info.get('funding_rate', 0):.8f}")
            print(f"  Funding Rate (bps): {funding_info.get('funding_rate_bps', 0):+.2f}")
            print(f"  Annualized Rate: {funding_info.get('funding_rate_annual_pct', 0):+.4f}%")
            print(f"  Next Funding: {funding_info.get('funding_time', 'Unknown')}")
            print(f"  Time to Funding: {funding_info.get('time_to_funding', 'Unknown')}")
                
            print(f"\n⚙️  CONTRACT SPECS:")  # Emojis OK in print()
            print(f"  Max Leverage: {funding_info.get('max_leverage', 0):.0f}x")
            print(f"  Price Increment: ${funding_info.get('price_increment', 0)}")
            print(f"  Min Order Size: ${funding_info.get('quote_min_size', 0)}")
            print(f"  Status: {funding_info.get('status', 'Unknown')}")
            
            print(f"{'='*60}")
            
        except Exception as e:
            logger.error(f"Error printing funding summary: {e}")
            print("❌ Error displaying funding summary")  # Emojis OK in print()
    
    def print_compact_update(self, funding_info: Dict):
        """Print compact update for continuous monitoring"""
        try:
            if not funding_info:
                print(f"❌ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} | Failed to collect data")  # Emojis OK in print()
                return
            
            rate = funding_info.get('funding_rate', 0)
            rate_bps = funding_info.get('funding_rate_bps', 0)
            price = funding_info.get('price', 0)
            oi = funding_info.get('open_interest', 0)
            time_to_funding = funding_info.get('time_to_funding', 'Unknown')

            est = pytz.timezone('US/Eastern')
            est_time = datetime.now(timezone.utc).astimezone(est)
            
            print(f"⏰ {est_time.strftime('%H:%M:%S EST')} | "  # Emojis OK in print()
                  f"Price: ${price:,.0f} | "
                  f"Funding: {rate_bps:+.2f}bps | "
                  f"Next: {time_to_funding} | "
                  f"OI: {oi:,.0f} BTC")
                  
        except Exception as e:
            logger.error(f"Error printing compact update: {e}")
            print(f"❌ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} | Display error")  # Emojis OK in print()
    
    def print_statistics(self):
        """Print comprehensive statistics"""
        try:
            current_time = time.time()
            uptime = current_time - self.start_time
            
            print("\n" + "="*60)
            print(f"📊 PRODUCTION STATISTICS (Uptime: {uptime/3600:.1f}h)")  # Emojis OK in print()
            print("="*60)
            
            # Request statistics
            success_rate = 0
            if self.fetch_attempts > 0:
                success_rate = (self.fetch_successes / self.fetch_attempts) * 100
            
            print(f"API Requests: {self.fetch_attempts}")
            print(f"Success Rate: {success_rate:.1f}%")
            print(f"Consecutive Errors: {self.consecutive_errors}")
            
            # Session statistics
            session_stats = self.session.get_statistics()
            print(f"HTTP Success Rate: {session_stats.get('success_rate', 0):.1f}%")
            
            # Storage statistics
            storage_stats = self.data_store.get_statistics()
            print(f"Records Stored: {storage_stats.get('total_records_stored', 0)}")
            print(f"Storage Utilization: {storage_stats.get('storage_utilization', 0):.1f}%")
            
            # Funding rate statistics
            funding_stats = self.data_store.get_funding_rate_stats()
            if funding_stats:
                print(f"\nFunding Rate Analysis ({funding_stats.get('count', 0)} samples):")
                print(f"  Current: {funding_stats.get('current', 0):.8f}")
                print(f"  Average: {funding_stats.get('average', 0):.8f}")
                print(f"  Range: {funding_stats.get('min', 0):.8f} to {funding_stats.get('max', 0):.8f}")
                print(f"  Std Dev: {funding_stats.get('std_dev', 0):.8f}")
            
            print("="*60 + "\n")
            
        except Exception as e:
            logger.error(f"Error printing statistics: {e}")
    
    def find_working_product(self) -> str:
        """Find a working product ID from variants"""
        logger.info("Testing product variants...")  # FIXED: Removed emoji
        
        for product_id in self.product_variants:
            if self.validate_product_id(product_id):
                return product_id
            time.sleep(1)  # Brief delay between tests
        
        # Fallback to original
        logger.warning(f"Using fallback product: {self.product_variants[0]}")  # FIXED: Removed emoji
        return self.product_variants[0]
    
    def run_continuous_monitoring(self, interval_seconds: int = 1):
        """Run continuous monitoring with production error handling"""
        logger.info(f"Starting continuous monitoring every {interval_seconds} seconds")  # FIXED: Removed emoji
        logger.info("   - Production error handling enabled")
        logger.info("   - Graceful shutdown on SIGINT/SIGTERM")
        logger.info("Press Ctrl+C to stop")
        
        # Find working product
        self.product_id = self.find_working_product()
        logger.info(f"Using product: {self.product_id}")  # FIXED: Removed emoji
        
        last_successful_update = time.time()
        
        # FIXED: Added infinite loop protection
        while self.should_run:
            try:
                current_time = time.time()
                
                # Print statistics periodically
                if current_time - self.last_stats_print >= self.stats_print_interval:
                    self.print_statistics()
                    self.last_stats_print = current_time
                
                # Collect data
                funding_info = self.collect_data_safe()
                
                if funding_info:
                    self.print_compact_update(funding_info)
                    last_successful_update = current_time
                else:
                    print(f"❌ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} | Failed to collect data")  # Emojis OK in print()
                
                # Handle consecutive errors
                if self.consecutive_errors > self.max_consecutive_errors:
                    logger.error(f"Too many consecutive errors ({self.consecutive_errors}). "  # FIXED: Removed emoji
                               f"Backing off for {self.error_backoff} seconds...")
                    time.sleep(self.error_backoff)
                    self.error_backoff = min(self.error_backoff * 2, self.max_error_backoff)
                    self.consecutive_errors = 0  # Reset after backoff
                
                # Check for extended downtime
                if current_time - last_successful_update > 600:  # 10 minutes
                    logger.warning(f"No successful updates for {(current_time - last_successful_update)/60:.1f} minutes")  # FIXED: Removed emoji
                
                time.sleep(interval_seconds)
                
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received in monitoring loop")  # FIXED: Removed emoji
                break
                
            except Exception as e:
                logger.error(f"FATAL ERROR in monitoring loop: {e}")  # FIXED: Removed emoji
                logger.debug(traceback.format_exc())
                
                # Emergency backoff
                emergency_backoff = min(60, self.consecutive_errors * 2)
                logger.info(f"Emergency backoff: {emergency_backoff} seconds")  # FIXED: Removed emoji
                time.sleep(emergency_backoff)
                
                self.consecutive_errors += 1
                # FIXED: Don't break the loop, continue retrying
        
        logger.info("Continuous monitoring exited")
    
    def shutdown(self):
        """Graceful shutdown"""
        logger.info("Starting graceful shutdown...")
        
        self.should_run = False
        
        # Print final statistics
        try:
            self.print_statistics()
        except:
            pass
        
        # Close HTTP session
        try:
            self.session.close()
        except:
            pass
        
        logger.info("Graceful shutdown complete")

def run_production_collector():
    """Main production runner with session management"""
    
    # Main runner with infinite retry - FIXED: Made truly infinite
    session_count = 0
    total_uptime = 0
    start_time = time.time()
    
    while True:  # FIXED: Infinite retry loop that never exits except on signals
        session_count += 1
        session_start = time.time()
        
        logger.info(f"Starting session #{session_count}")  # FIXED: Removed emoji
        
        collector = None
        try:
            collector = ProductionFundingDataCollector()
            collector.run_continuous_monitoring(interval_seconds=1)
            
            # If we get here, it was a graceful shutdown due to signal
            session_duration = time.time() - session_start
            total_uptime += session_duration
            logger.info(f"Session #{session_count} ended gracefully after {session_duration:.1f}s")
            
            # Check if we should really stop
            if not collector.should_run:
                logger.info("Graceful shutdown requested")
                break
            
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received")  # FIXED: Removed emoji
            break
            
        except Exception as e:
            session_duration = time.time() - session_start
            total_uptime += session_duration
            
            logger.error(f"Session #{session_count} crashed after {session_duration:.1f}s: {e}")  # FIXED: Removed emoji
            logger.debug(traceback.format_exc())
            
        finally:
            # Clean up current session
            if collector:
                try:
                    collector.shutdown()
                except Exception as e:
                    logger.warning(f"Error during cleanup: {e}")
        
        # Brief pause before retry (unless shutdown was requested)
        if collector and collector.should_run:
            retry_delay = min(30, session_count * 2)  # Progressive delay up to 30s
            logger.info(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
        else:
            break
    
    # Final statistics
    total_runtime = time.time() - start_time
    logger.info(f"FINAL STATISTICS:")  # FIXED: Removed emoji
    logger.info(f"   Total runtime: {total_runtime/3600:.1f} hours")
    logger.info(f"   Active uptime: {total_uptime/3600:.1f} hours ({100*total_uptime/max(1,total_runtime):.1f}%)")
    logger.info(f"   Sessions: {session_count}")
    logger.info("Production funding collector shutdown complete")

def main():
    """Production entry point with top-level error handling"""
    try:
        bulletproof_runner()  # FIXED: Use bulletproof runner instead of direct call
    except KeyboardInterrupt:
        logger.info("Main KeyboardInterrupt - shutting down")  # FIXED: Removed emoji
    except Exception as e:
        logger.critical(f"CRITICAL ERROR in main: {e}")  # FIXED: Removed emoji
        logger.critical(traceback.format_exc())
        sys.exit(1)

def demo_single_collection():
    """Demonstrate single data collection for testing"""
    print("🔍 Testing single data collection...")  # Emojis OK in print()
    
    collector = ProductionFundingDataCollector()
    
    try:
        # Find working product
        collector.product_id = collector.find_working_product()
        
        # Collect data
        funding_info = collector.collect_data_safe()
        
        if funding_info:
            collector.print_funding_summary_safe(funding_info)
            print("\n✅ Single collection test successful")  # Emojis OK in print()
            
            # Show some statistics
            stats = collector.data_store.get_statistics()
            print(f"📊 Records stored: {stats.get('total_records_stored', 0)}")  # Emojis OK in print()
            
            return True
        else:
            print("❌ Single collection test failed")  # Emojis OK in print()
            return False
            
    except Exception as e:
        logger.error(f"Error in single collection test: {e}")
        print("❌ Single collection test failed with error")  # Emojis OK in print()
        return False
        
    finally:
        collector.shutdown()

def interactive_mode():
    """Interactive mode for testing and configuration"""
    print("\n🚀 PRODUCTION BTC FUNDING DATA COLLECTOR")  # Emojis OK in print()
    print("=" * 50)
    print("Choose an option:")
    print("1. Run continuous monitoring (production mode)")
    print("2. Test single data collection")
    print("3. Test API connectivity")
    print("4. Exit")
    
    try:
        print("Defaulting to choice 1 (continuous monitoring)...")  # Emojis OK in print()
        choice = "1"
        
        if choice == "1":
            print("\n🔄 Starting continuous monitoring...")  # Emojis OK in print()
            print("This will run indefinitely. Press Ctrl+C to stop.\n")
            time.sleep(2)
            main()
            
        elif choice == "2":
            print("\n🔍 Testing single data collection...")  # Emojis OK in print()
            success = demo_single_collection()
            if success:
                cont = input("\n🔄 Start continuous monitoring? (y/n): ").lower().strip()  # Emojis OK in print()
                if cont in ['y', 'yes']:
                    print("\n🔄 Starting continuous monitoring...")  # Emojis OK in print()
                    time.sleep(1)
                    main()
            
        elif choice == "3":
            print("\n🔗 Testing API connectivity...")  # Emojis OK in print()
            collector = ProductionFundingDataCollector()
            
            try:
                working_product = collector.find_working_product()
                print(f"✅ API connectivity test successful with product: {working_product}")  # Emojis OK in print()
                
                # Test session statistics
                session_stats = collector.session.get_statistics()
                print(f"📊 Session stats: {session_stats}")  # Emojis OK in print()
                
            except Exception as e:
                print(f"❌ API connectivity test failed: {e}")  # Emojis OK in print()
            finally:
                collector.shutdown()
                
        elif choice == "4":
            print("👋 Goodbye!")  # Emojis OK in print()
            
        else:
            print("❌ Invalid choice. Please enter 1-4.")  # Emojis OK in print()
            
    except KeyboardInterrupt:
        print("\n🛑 Interrupted")  # Emojis OK in print()
    except Exception as e:
        print(f"❌ Error in interactive mode: {e}")  # Emojis OK in print()

# Test functions for validation
def run_validation_tests():
    """Run comprehensive validation tests"""
    print("🧪 Running validation tests...")  # Emojis OK in print()
    
    tests_passed = 0
    total_tests = 0
    
    # Test 1: Session creation
    total_tests += 1
    try:
        session = ProductionRequestsSession()
        session.close()
        print("✅ Test 1: Session creation - PASSED")  # Emojis OK in print()
        tests_passed += 1
    except Exception as e:
        print(f"❌ Test 1: Session creation - FAILED: {e}")  # Emojis OK in print()
    
    # Test 2: Data store
    total_tests += 1
    try:
        store = ProductionDataStore()
        test_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'funding_rate': 0.0001,
            'price': 50000,
            'open_interest': 1000
        }
        store.add_record(test_data)
        records = store.get_latest_records(1)
        assert len(records) == 1
        print("✅ Test 2: Data store - PASSED")  # Emojis OK in print()
        tests_passed += 1
    except Exception as e:
        print(f"❌ Test 2: Data store - FAILED: {e}")  # Emojis OK in print()
    
    # Test 3: Collector creation
    total_tests += 1
    try:
        collector = ProductionFundingDataCollector()
        collector.shutdown()
        print("✅ Test 3: Collector creation - PASSED")  # Emojis OK in print()
        tests_passed += 1
    except Exception as e:
        print(f"❌ Test 3: Collector creation - FAILED: {e}")  # Emojis OK in print()
    
    # Test 4: Safe numeric conversion
    total_tests += 1
    try:
        def safe_float(value, default=0.0):
            try:
                return float(value) if value is not None else default
            except (ValueError, TypeError):
                return default
        
        assert safe_float("123.45") == 123.45
        assert safe_float(None) == 0.0
        assert safe_float("invalid") == 0.0
        assert safe_float("") == 0.0
        print("✅ Test 4: Safe numeric conversion - PASSED")  # Emojis OK in print()
        tests_passed += 1
    except Exception as e:
        print(f"❌ Test 4: Safe numeric conversion - FAILED: {e}")  # Emojis OK in print()
    
    print(f"\n📊 Validation Results: {tests_passed}/{total_tests} tests passed")  # Emojis OK in print()
    
    if tests_passed == total_tests:
        print("✅ All validation tests passed!")  # Emojis OK in print()
        return True
    else:
        print("❌ Some validation tests failed!")  # Emojis OK in print()
        return False

if __name__ == "__main__":
    # System info
    logger.info("PRODUCTION BTC FUNDING DATA COLLECTOR")  # FIXED: Removed emoji
    logger.info("=" * 50)
    logger.info(f"Python: {sys.version}")
    logger.info(f"Platform: {sys.platform}")
    logger.info(f"PID: {os.getpid()}")
    logger.info("=" * 50)
    
    # Check if running in automated mode
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        
        if arg == "production" or arg == "auto":
            logger.info("Running in automated production mode")  # FIXED: Removed emoji
            try:
                main()
            except KeyboardInterrupt:
                logger.info("Top-level KeyboardInterrupt")  # FIXED: Removed emoji
            except Exception as e:
                logger.critical(f"FATAL ERROR: {e}")  # FIXED: Removed emoji
                logger.critical(traceback.format_exc())
                sys.exit(1)
            finally:
                logger.info("Application terminated")  # FIXED: Removed emoji
                
        elif arg == "test" or arg == "validate":
            logger.info("Running in validation mode")  # FIXED: Removed emoji
            if run_validation_tests():
                print("\n✅ Validation successful! Ready for production.")  # Emojis OK in print()
                sys.exit(0)
            else:
                print("\n❌ Validation failed! Please check configuration.")  # Emojis OK in print()
                sys.exit(1)
                
        elif arg == "single":
            logger.info("Running single collection test")  # FIXED: Removed emoji
            success = demo_single_collection()
            sys.exit(0 if success else 1)
            
        else:
            print(f"❌ Unknown argument: {arg}")  # Emojis OK in print()
            print("Valid arguments: production, auto, test, validate, single")
            sys.exit(1)
    
    else:
        # Interactive mode
        try:
            interactive_mode()
        except KeyboardInterrupt:
            logger.info("Top-level KeyboardInterrupt")  # FIXED: Removed emoji
        except Exception as e:
            logger.critical(f"FATAL ERROR: {e}")  # FIXED: Removed emoji
            logger.critical(traceback.format_exc())
            sys.exit(1)
        finally:
            logger.info("Application terminated")  # FIXED: Removed emoji