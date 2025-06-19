import http.client
import json
import time
import logging
import signal
import sys
import os
import traceback
from collections import defaultdict, deque
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Any
import threading
from contextlib import contextmanager

def bulletproof_runner():
    """Bulletproof runner that restarts no matter what"""
    restart_count = 0
    
    while True:
        restart_count += 1
        logger.info(f"Bulletproof restart #{restart_count}")  # FIXED: Removed emoji
        
        try:
            # Your existing main function
            run_production_fetcher()
            
            # If we get here, main function exited unexpectedly
            logger.warning("Main fetcher function exited - this should not happen!")  # FIXED: Removed emoji
            
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
            'coinbase_candles.log', 
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

class ProductionConnectionManager:
    """Production-grade HTTPS connection manager with retry logic"""
    
    def __init__(self, host: str = "api.coinbase.com", timeout: int = 30):
        self.host = host
        self.timeout = timeout
        self.connection = None
        self.connection_lock = threading.Lock()
        self.last_connection_time = 0
        self.connection_attempts = 0
        self.max_connection_attempts = 10
        self.connection_cooldown = 5  # seconds between connection attempts
        
    def get_connection(self) -> Optional[http.client.HTTPSConnection]:
        """Get HTTPS connection with thread safety and retry logic"""
        with self.connection_lock:
            current_time = time.time()
            
            # Check if we need to cool down
            if (current_time - self.last_connection_time) < self.connection_cooldown:
                if self.connection and self._test_connection():
                    return self.connection
                return None
            
            try:
                # Close existing connection if it exists
                if self.connection:
                    try:
                        self.connection.close()
                    except:
                        pass
                    self.connection = None
                
                # Create new connection
                self.connection = http.client.HTTPSConnection(
                    self.host, 
                    timeout=self.timeout
                )
                
                # Test the connection
                if self._test_connection():
                    self.connection_attempts = 0
                    self.last_connection_time = current_time
                    logger.info(f"HTTPS connection established to {self.host}")
                    return self.connection
                else:
                    self.connection = None
                    raise Exception("Connection test failed")
                    
            except Exception as e:
                self.connection_attempts += 1
                self.last_connection_time = current_time
                
                if self.connection_attempts >= self.max_connection_attempts:
                    logger.error(f"Failed to connect after {self.max_connection_attempts} attempts")  # FIXED: Removed emoji
                    self.connection_attempts = 0  # Reset for next cycle
                else:
                    logger.warning(f"Connection attempt {self.connection_attempts}/{self.max_connection_attempts} failed: {e}")  # FIXED: Removed emoji
                
                self.connection = None
                return None
    
    def _test_connection(self) -> bool:
        """Test if connection is alive"""
        if not self.connection:
            return False
        
        try:
            # Simple HEAD request to test connectivity
            self.connection.request("HEAD", "/", headers={'User-Agent': 'ProductionCandleFetcher/1.0'})
            response = self.connection.getresponse()
            response.read()  # Consume response body
            return True
        except Exception:
            return False
    
    def close(self):
        """Safely close connection"""
        with self.connection_lock:
            if self.connection:
                try:
                    self.connection.close()
                    logger.info("HTTPS connection closed")
                except Exception as e:
                    logger.warning(f"Warning closing connection: {e}")
                finally:
                    self.connection = None

class ProductionCandleStore:
    """Production-grade candle data storage with limits and error handling"""
    
    def __init__(self, max_candles_per_granularity: int = 1000):
        self.max_candles = max_candles_per_granularity
        self.store = defaultdict(lambda: deque(maxlen=self.max_candles))
        self.store_lock = threading.Lock()
        self.total_candles_stored = 0
        self.last_candle_times = defaultdict(int)
        
    def add_candle(self, granularity: str, candle_data: Dict) -> bool:
        """Add candle data with thread safety and validation"""
        try:
            with self.store_lock:
                # Validate candle data
                required_fields = ['start', 'open', 'close', 'high', 'low', 'volume']
                for field in required_fields:
                    if field not in candle_data:
                        logger.warning(f"Missing field '{field}' in candle data for {granularity}")
                        return False
                
                # Check for duplicate timestamps
                candle_time = int(candle_data['start'])
                if candle_time <= self.last_candle_times[granularity]:
                    logger.debug(f"Duplicate or old candle for {granularity}: {candle_time}")
                    return False
                
                # Store candle
                self.store[granularity].append(candle_data)
                self.last_candle_times[granularity] = candle_time
                self.total_candles_stored += 1
                
                logger.debug(f"Stored candle for {granularity}: {candle_time}")
                return True
                
        except Exception as e:
            logger.error(f"Error storing candle for {granularity}: {e}")
            return False
    
    def get_latest_candles(self, granularity: str, count: int = 10) -> List[Dict]:
        """Get latest candles for a granularity"""
        try:
            with self.store_lock:
                candles = list(self.store[granularity])
                return candles[-count:] if count < len(candles) else candles
        except Exception as e:
            logger.error(f"Error retrieving candles for {granularity}: {e}")
            return []
    
    def get_statistics(self) -> Dict:
        """Get storage statistics"""
        try:
            with self.store_lock:
                stats = {
                    'total_candles_stored': self.total_candles_stored,
                    'granularities': {}
                }
                
                for granularity, candles in self.store.items():
                    stats['granularities'][granularity] = {
                        'count': len(candles),
                        'latest_time': self.last_candle_times.get(granularity, 0)
                    }
                
                return stats
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {'error': str(e)}

class ProductionCandleFetcher:
    """Production-grade candle data fetcher with comprehensive error handling"""
    
    def __init__(self, product_id: str = "BTC-PERP-INTX"):
        self.product_id = product_id
        self.should_run = True
        
        # Candle granularities in seconds
        self.granularities = {
            'ONE_MINUTE': 60,
            'FIVE_MINUTE': 300,
            'FIFTEEN_MINUTE': 900,
            'THIRTY_MINUTE': 1800,
            'ONE_HOUR': 3600,
            'TWO_HOUR': 7200,
            'SIX_HOUR': 21600,
            'ONE_DAY': 86400,
        }
        
        # Components
        self.connection_manager = ProductionConnectionManager()
        self.candle_store = ProductionCandleStore()
        
        # Statistics
        self.fetch_attempts = defaultdict(int)
        self.fetch_successes = defaultdict(int)
        self.fetch_errors = defaultdict(int)
        self.total_requests = 0
        self.start_time = time.time()
        self.last_stats_print = 0
        self.stats_print_interval = 300  # Print stats every 5 minutes
        
        # Error handling
        self.consecutive_errors = 0
        self.max_consecutive_errors = 50
        self.error_backoff = 1
        self.max_error_backoff = 300  # 5 minutes max backoff
        
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
    
    def validate_product_id(self) -> bool:
        """Validate that the product ID exists"""
        try:
            conn = self.connection_manager.get_connection()
            if not conn:
                return False
            
            path = f"/api/v3/brokerage/market/products/{self.product_id}"
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'ProductionCandleFetcher/1.0'
            }
            
            conn.request("GET", path, '', headers)
            res = conn.getresponse()
            data = res.read().decode("utf-8")
            
            if res.status == 200:
                logger.info(f"Product {self.product_id} validated successfully")
                return True
            else:
                logger.error(f"Product {self.product_id} validation failed: HTTP {res.status}")
                return False
                
        except Exception as e:
            logger.error(f"Product validation error: {e}")  # FIXED: Removed emoji
            return False
    
    def fetch_candles_safe(self, granularity: str, now: int) -> bool:
        """Fetch candles with comprehensive error handling"""
        try:
            self.fetch_attempts[granularity] += 1
            self.total_requests += 1
            
            # Get connection
            conn = self.connection_manager.get_connection()
            if not conn:
                raise Exception("No connection available")
            
            # Calculate time range
            seconds = self.granularities[granularity]
            start = now - seconds
            end = now
            
            # Build request
            path = f"/api/v3/brokerage/market/products/{self.product_id}/candles?start={start}&end={end}&granularity={granularity}"
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'ProductionCandleFetcher/1.0'
            }
            
            # Make request with timeout handling
            conn.request("GET", path, '', headers)
            res = conn.getresponse()
            
            if res.status != 200:
                raise Exception(f"HTTP {res.status}: {res.reason}")
            
            # Parse response
            data = json.loads(res.read().decode("utf-8"))
            candles = data.get('candles', [])
            
            if not candles:
                logger.debug(f"No candles returned for {granularity}")
                return True  # Not an error, just no new data
            
            # Process latest candle
            latest_candle = candles[0]
            
            # Store candle
            if self.candle_store.add_candle(granularity, latest_candle):
                # Format and display
                try:
                    ts = datetime.fromtimestamp(
                        int(latest_candle['start']), 
                        tz=ZoneInfo("UTC")
                    ).astimezone(ZoneInfo("US/Eastern"))
                    
                    print(f"[{granularity}] {ts.strftime('%Y-%m-%d %H:%M:%S')} | "
                          f"Open: {latest_candle['open']} Close: {latest_candle['close']} "
                          f"High: {latest_candle['high']} Low: {latest_candle['low']} "
                          f"Volume: {latest_candle['volume']}")
                          
                except Exception as e:
                    logger.warning(f"Error formatting candle display: {e}")
                    print(f"[{granularity}] New candle stored (display error)")
            
            self.fetch_successes[granularity] += 1
            self.consecutive_errors = 0  # Reset error counter
            self.error_backoff = 1  # Reset backoff
            
            return True
            
        except json.JSONDecodeError as e:
            self.fetch_errors[granularity] += 1
            logger.error(f"JSON decode error for {granularity}: {e}")
            return False
            
        except Exception as e:
            self.fetch_errors[granularity] += 1
            self.consecutive_errors += 1
            
            if self.consecutive_errors <= 5:  # Only log first few errors to avoid spam
                logger.error(f"Fetch error for {granularity}: {e}")
            elif self.consecutive_errors == 6:
                logger.error(f"Suppressing further error logs (too many consecutive errors)")
            
            return False
    
    def print_statistics(self):
        """Print performance statistics"""
        try:
            current_time = time.time()
            uptime = current_time - self.start_time
            
            print("\n" + "="*60)
            print(f"📊 PRODUCTION STATISTICS (Uptime: {uptime/3600:.1f}h)")  # Emojis OK in print()
            print("="*60)
            
            # Request statistics
            success_rate = 0
            if self.total_requests > 0:
                total_successes = sum(self.fetch_successes.values())
                success_rate = (total_successes / self.total_requests) * 100
            
            print(f"Total Requests: {self.total_requests}")
            print(f"Success Rate: {success_rate:.1f}%")
            print(f"Consecutive Errors: {self.consecutive_errors}")
            
            # Per-granularity statistics
            print("\nPer-Granularity Stats:")
            for granularity in self.granularities.keys():
                attempts = self.fetch_attempts[granularity]
                successes = self.fetch_successes[granularity]
                errors = self.fetch_errors[granularity]
                
                success_pct = (successes / attempts * 100) if attempts > 0 else 0
                print(f"  {granularity:15} | Attempts: {attempts:4} | Success: {success_pct:5.1f}% | Errors: {errors:3}")
            
            # Storage statistics
            storage_stats = self.candle_store.get_statistics()
            print(f"\nCandles Stored: {storage_stats.get('total_candles_stored', 0)}")
            
            print("="*60 + "\n")
            
        except Exception as e:
            logger.error(f"Error printing statistics: {e}")
    
    def run_aligned_updater(self):
        """Main update loop with production-grade error handling"""
        logger.info("Starting production candle fetcher...")
        
        # Validate product first
        if not self.validate_product_id():
            logger.error("Product validation failed. Exiting.")  # FIXED: Removed emoji
            return
        
        logger.info(f"Product {self.product_id} validated. Starting data collection...")
        print(f"[START] Entering main update loop for {self.product_id}...\n")
        
        last_minute = -1
        
        # FIXED: Added infinite loop protection
        while self.should_run:
            try:
                current_time = time.time()
                now = int(current_time)
                current_minute = now // 60
                
                # Print statistics periodically
                if current_time - self.last_stats_print >= self.stats_print_interval:
                    self.print_statistics()
                    self.last_stats_print = current_time
                
                # Check for aligned candle updates
                any_updates = False
                
                for granularity, seconds in self.granularities.items():
                    if now % seconds == 0:
                        if self.fetch_candles_safe(granularity, now):
                            any_updates = True
                
                # Handle consecutive errors
                if self.consecutive_errors > self.max_consecutive_errors:
                    logger.error(f"Too many consecutive errors ({self.consecutive_errors}). "  # FIXED: Removed emoji
                               f"Backing off for {self.error_backoff} seconds...")
                    time.sleep(self.error_backoff)
                    self.error_backoff = min(self.error_backoff * 2, self.max_error_backoff)
                    self.consecutive_errors = 0  # Reset after backoff
                
                # Sleep until next second
                time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received in main loop")
                break
                
            except Exception as e:
                logger.error(f"FATAL LOOP ERROR: {e}")  # FIXED: Removed emoji
                logger.debug(traceback.format_exc())
                
                # Emergency backoff
                emergency_backoff = min(60, self.consecutive_errors * 2)
                logger.info(f"Emergency backoff: {emergency_backoff} seconds")  # FIXED: Removed emoji
                time.sleep(emergency_backoff)
                
                self.consecutive_errors += 1
                # FIXED: Don't break the loop, continue retrying
        
        logger.info("Main update loop exited")
    
    def shutdown(self):
        """Graceful shutdown"""
        logger.info("Starting graceful shutdown...")
        
        self.should_run = False
        
        # Print final statistics
        try:
            self.print_statistics()
        except:
            pass
        
        # Close connections
        try:
            self.connection_manager.close()
        except:
            pass
        
        logger.info("Graceful shutdown complete")

def run_production_fetcher():
    """Main production runner with top-level error handling"""
    
    # Test different product IDs
    product_variants = ["BTC-PERP-INTX", "BTC-INTX-PERP", "BTC-PERP"]
    working_product = None
    
    logger.info("Testing product variants...")
    
    for product_id in product_variants:
        try:
            fetcher = ProductionCandleFetcher(product_id)
            if fetcher.validate_product_id():
                working_product = product_id
                fetcher.shutdown()
                break
            fetcher.shutdown()
        except Exception as e:
            logger.warning(f"Error testing {product_id}: {e}")
        
        time.sleep(1)  # Brief delay between tests
    
    if not working_product:
        working_product = "BTC-PERP-INTX"  # Fallback
        logger.warning(f"Using fallback product: {working_product}")  # FIXED: Removed emoji
    else:
        logger.info(f"Using validated product: {working_product}")
    
    # Main runner with infinite retry - FIXED: Made truly infinite
    session_count = 0
    total_uptime = 0
    start_time = time.time()
    
    while True:  # FIXED: Infinite retry loop that never exits except on signals
        session_count += 1
        session_start = time.time()
        
        logger.info(f"Starting session #{session_count}")
        
        fetcher = None
        try:
            fetcher = ProductionCandleFetcher(working_product)
            fetcher.run_aligned_updater()
            
            # If we get here, it was a graceful shutdown due to signal
            session_duration = time.time() - session_start
            total_uptime += session_duration
            logger.info(f"Session #{session_count} ended gracefully after {session_duration:.1f}s")
            
            # Check if we should really stop
            if not fetcher.should_run:
                logger.info("Graceful shutdown requested")
                break
            
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received")
            break
            
        except Exception as e:
            session_duration = time.time() - session_start
            total_uptime += session_duration
            
            logger.error(f"Session #{session_count} crashed after {session_duration:.1f}s: {e}")
            logger.debug(traceback.format_exc())
            
        finally:
            # Clean up current session
            if fetcher:
                try:
                    fetcher.shutdown()
                except Exception as e:
                    logger.warning(f"Error during cleanup: {e}")
        
        # Brief pause before retry (unless shutdown was requested)
        if fetcher and fetcher.should_run:
            retry_delay = min(30, session_count * 2)  # Progressive delay up to 30s
            logger.info(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
        else:
            break
    
    # Final statistics
    total_runtime = time.time() - start_time
    logger.info(f"FINAL STATISTICS:")
    logger.info(f"   Total runtime: {total_runtime/3600:.1f} hours")
    logger.info(f"   Active uptime: {total_uptime/3600:.1f} hours ({100*total_uptime/max(1,total_runtime):.1f}%)")
    logger.info(f"   Sessions: {session_count}")
    logger.info("Production fetcher shutdown complete")

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

if __name__ == "__main__":
    # System info
    logger.info("PRODUCTION COINBASE CANDLE FETCHER")
    logger.info("=" * 50)
    logger.info(f"Python: {sys.version}")
    logger.info(f"Platform: {sys.platform}")
    logger.info(f"PID: {os.getpid()}")
    logger.info("=" * 50)
    
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