import asyncio
import time
from typing import Dict, Optional, List, Tuple, Any
import concurrent.futures

from utils import debug_print, submit_order, cancel_order

class BatchOrderManager:
    """
    Unified batch order manager that:
    - Uses real batch APIs in production (demo=False) 
    - Simulates batch behavior in demo (demo=True) by grouping individual calls
    - Maintains identical logic and timing in both modes for proper testing
    """
    def __init__(self, mm_instance, demo=True):
        self.mm = mm_instance
        self.demo = demo
        # Add after self.fill_check_interval = 2.0
        self.max_workers = 8  # Allow up to 8 simultaneous API calls
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
            
        # Tracking dictionaries (identical for both modes)
        self.active_orders = {ticker: {'bid_order_id': None, 'ask_order_id': None} 
                             for ticker in self.mm.tickers}
        self.live_quotes = {ticker: {'bid': None, 'ask': None} 
                           for ticker in self.mm.tickers}
        self.pending_fill_checks = {}
        self.desired_quotes = {ticker: {'bid': None, 'ask': None} 
                              for ticker in self.mm.tickers}
        
        # Same timing for both modes - this is key for testing consistency
        self.batch_interval = 1.0  # 400ms in both modes
        self.fill_check_interval = 5.0
        
        # Determine which batch implementation to use
        if demo:
            self.batch_mode = "simulated"
            debug_print("🧪 Using SIMULATED BATCH mode (demo - tests same logic as production)")
        else:
            self.batch_mode = "real_api"
            debug_print("🚀 Using REAL BATCH API mode (production)")
        
        # Stats tracking
        self.batch_stats = {
            'total_cycles': 0,
            'orders_cancelled': 0,
            'orders_placed': 0,
            'batch_errors': 0,
            'mode': self.batch_mode
        }
    
    def safe_get(self, dictionary: dict, *keys, default=None) -> Any:
        """Safely access nested dictionary keys."""
        try:
            result = dictionary
            for key in keys:
                if result is None:
                    return default
                result = result[key]
            return result
        except (KeyError, TypeError, AttributeError):
            return default
    
    def safe_set(self, dictionary: dict, keys: list, value: Any) -> bool:
        """Safely set a nested dictionary value."""
        try:
            current = dictionary
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            current[keys[-1]] = value
            return True
        except (TypeError, AttributeError) as e:
            debug_print(f"❌ Error setting {keys}: {e}")
            return False
    
    def _ensure_ticker_initialized(self, ticker: str):
        """Ensure ticker is properly initialized in tracking dictionaries"""
        for dict_obj in [self.active_orders, self.live_quotes, self.desired_quotes]:
            if ticker not in dict_obj:
                dict_obj[ticker] = {'bid': None, 'ask': None}
                if dict_obj is self.active_orders:
                    dict_obj[ticker] = {'bid_order_id': None, 'ask_order_id': None}
    
    async def handle_quote_update(self, ticker: str):
        """Store desired quotes for batch processing (identical logic for both modes)"""
        if not ticker:
            debug_print("❌ handle_quote_update called with empty ticker")
            return
            
        self._ensure_ticker_initialized(ticker)
        
        calculated_bid = self.safe_get(self.mm.our_quotes, ticker, 'bid')
        calculated_ask = self.safe_get(self.mm.our_quotes, ticker, 'ask')
        
        self.safe_set(self.desired_quotes, [ticker, 'bid'], calculated_bid)
        self.safe_set(self.desired_quotes, [ticker, 'ask'], calculated_ask)
        
        # debug_print(f"🎯 [{self.batch_mode}] Updated desired quotes for {ticker}: Bid={calculated_bid}, Ask={calculated_ask}")
    
    async def batch_process_loop(self):
        """Main batch processing loop - identical timing and logic for both modes"""
        debug_print(f"🔄 Starting {self.batch_mode} batch processing with {self.batch_interval}s intervals")
        
        while True:
            try:
                start_time = time.time()
                await self._execute_batch_cycle()
                
                cycle_time = time.time() - start_time
                sleep_time = max(0, self.batch_interval - cycle_time)
                
                if cycle_time > self.batch_interval:
                    debug_print(f"⚠️ Batch cycle took {cycle_time:.3f}s, longer than interval {self.batch_interval}s")
                
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                debug_print(f"❌ Error in batch processing loop: {e}")
                await asyncio.sleep(0.1)
    
    async def _execute_batch_cycle(self):
        """Execute one batch cycle - routes to real or simulated implementation"""
        self.batch_stats['total_cycles'] += 1
        cycle_start = time.time()
        
        debug_print(f"🔄 [{self.batch_mode}] Starting batch cycle #{self.batch_stats['total_cycles']}")
        
        # Step 1: Analyze what needs to change (identical logic for both modes)
        orders_to_cancel = []
        orders_to_place = []
        
        for ticker in self.mm.tickers:
            self._analyze_ticker_changes(ticker, orders_to_cancel, orders_to_place)
        
        # Step 2: Execute operations using appropriate method
        cancel_success = True
        if orders_to_cancel:
            if self.batch_mode == "real_api":
                cancel_success = await self._real_batch_cancel(orders_to_cancel)
            else:
                cancel_success = await self._simulated_batch_cancel(orders_to_cancel)
        
        if cancel_success and orders_to_place:
            if self.batch_mode == "real_api":
                await self._real_batch_create(orders_to_place)
            else:
                await self._simulated_batch_create(orders_to_place)
        
        cycle_time = time.time() - cycle_start
        debug_print(f"✅ [{self.batch_mode}] Batch cycle completed in {cycle_time:.3f}s - "
                   f"Cancelled: {len(orders_to_cancel)}, Placed: {len(orders_to_place)}")
    
    def _analyze_ticker_changes(self, ticker: str, orders_to_cancel: List[str], orders_to_place: List[Dict]):
        """Analyze what orders need to change for a ticker (identical for both modes)"""
        self._ensure_ticker_initialized(ticker)
        
        desired_bid = self.safe_get(self.desired_quotes, ticker, 'bid')
        desired_ask = self.safe_get(self.desired_quotes, ticker, 'ask')
        
        current_bid = self.safe_get(self.live_quotes, ticker, 'bid')
        current_ask = self.safe_get(self.live_quotes, ticker, 'ask')
        
        current_bid_order_id = self.safe_get(self.active_orders, ticker, 'bid_order_id')
        current_ask_order_id = self.safe_get(self.active_orders, ticker, 'ask_order_id')
        
        # Analyze bid changes
        if desired_bid != current_bid:
            if current_bid_order_id:
                orders_to_cancel.append(current_bid_order_id)
                debug_print(f"📋 Will cancel bid order {current_bid_order_id} for {ticker}")
            
            if desired_bid is not None:
                order_spec = {
                    'ticker': ticker,
                    'side': 'bid',
                    'action': 'buy',
                    'price': desired_bid,
                    'quantity': self.mm.mm_size
                }
                orders_to_place.append(order_spec)
                debug_print(f"📋 Will place bid order for {ticker} @ {desired_bid}")
        
        # Analyze ask changes  
        if desired_ask != current_ask:
            if current_ask_order_id:
                orders_to_cancel.append(current_ask_order_id)
                debug_print(f"📋 Will cancel ask order {current_ask_order_id} for {ticker}")
            
            if desired_ask is not None:
                order_spec = {
                    'ticker': ticker,
                    'side': 'ask', 
                    'action': 'sell',
                    'price': desired_ask,
                    'quantity': self.mm.mm_size
                }
                orders_to_place.append(order_spec)
                debug_print(f"📋 Will place ask order for {ticker} @ {desired_ask}")
    
    def __del__(self):
        """Clean up thread pool when manager is destroyed"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)

    def _create_single_order_sync(self, order_spec: Dict) -> Optional[Dict]:
        """Synchronous order creation function that runs in thread pool"""
        try:
            response = submit_order(
                ticker=order_spec['ticker'],
                action=order_spec['action'],
                quantity=order_spec['quantity'],
                price=order_spec['price'],
                demo=self.demo
            )
            
            if response and 'order' in response:
                return response['order']
            return None
            
        except Exception as e:
            # Check if it's a 409 conflict
            if "409" in str(e):
                debug_print(f"⚠️ Order conflict for {order_spec['ticker']} @ {order_spec['price']} - likely duplicate")
            else:
                debug_print(f"❌ Thread create error for {order_spec['ticker']}: {e}")
            return None

    def _create_single_order_sync(self, order_spec: Dict) -> Optional[Dict]:
        """Synchronous order creation function that runs in thread pool"""
        try:
            response = submit_order(
                ticker=order_spec['ticker'],
                action=order_spec['action'],
                quantity=order_spec['quantity'],
                price=order_spec['price'],
                demo=self.demo
            )
            
            if response and 'order' in response:
                return response['order']
            return None
            
        except Exception as e:
            debug_print(f"❌ Thread create error for {order_spec['ticker']}: {e}")
            return None

    async def _real_batch_cancel(self, order_ids: List[str]) -> bool:
        """Cancel orders using real Kalshi batch API"""
        try:
            debug_print(f"❌ [REAL API] Batch cancelling {len(order_ids)} orders")
            
            from utils import batch_cancel_orders
            response = batch_cancel_orders(order_ids, demo=self.demo)
            
            if response and response.get('success'):
                for order_id in order_ids:
                    self._remove_order_from_tracking(order_id)
                
                self.batch_stats['orders_cancelled'] += len(order_ids)
                debug_print(f"✅ [REAL API] Successfully cancelled {len(order_ids)} orders")
                return True
            else:
                debug_print(f"❌ [REAL API] Batch cancel failed: {response}")
                self.batch_stats['batch_errors'] += 1
                return False
                
        except Exception as e:
            debug_print(f"❌ [REAL API] Error in batch cancel: {e}")
            self.batch_stats['batch_errors'] += 1
            return False
    
    async def _simulated_batch_cancel(self, order_ids: List[str]) -> bool:
        """Cancel orders using TRUE PARALLEL execution with threads"""
        if not order_ids:
            return True
            
        try:
            debug_print(f"❌ [PARALLEL] Cancelling {len(order_ids)} orders on {min(len(order_ids), self.max_workers)} threads")
            
            parallel_start = time.time()
            loop = asyncio.get_event_loop()
            
            # Submit all cancel operations to thread pool simultaneously
            futures = []
            for order_id in order_ids:
                future = loop.run_in_executor(self.executor, self._cancel_single_order_sync, order_id)
                futures.append(future)
            
            # Wait for ALL operations to complete in parallel
            results = await asyncio.gather(*futures, return_exceptions=True)
            parallel_time = time.time() - parallel_start
            
            # Process results
            successful_cancels = 0
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    debug_print(f"❌ Cancel failed for {order_ids[i]}: {result}")
                elif result:
                    successful_cancels += 1
                    self._remove_order_from_tracking(order_ids[i])
            
            self.batch_stats['orders_cancelled'] += successful_cancels
            debug_print(f"✅ [PARALLEL] Cancelled {successful_cancels}/{len(order_ids)} orders in {parallel_time*1000:.0f}ms")
            
            return successful_cancels > 0
                
        except Exception as e:
            debug_print(f"❌ Error in parallel batch cancel: {e}")
            self.batch_stats['batch_errors'] += 1
            return False

        """Cancel a single order (used in simulated mode)"""
        try:
            response = cancel_order(order_id, demo=self.demo)
            return response is not None
        except Exception as e:
            debug_print(f"❌ Error cancelling order {order_id}: {e}")
            return False
    
    async def _real_batch_create(self, order_specs: List[Dict]) -> bool:
        """Create orders using real Kalshi batch API"""
        try:
            debug_print(f"📤 [REAL API] Batch creating {len(order_specs)} orders")
            
            from utils import batch_create_orders
            response = batch_create_orders(order_specs, demo=self.demo)
            
            if response and response.get('success'):
                orders_data = response.get('orders', [])
                for i, order_data in enumerate(orders_data):
                    if i < len(order_specs):
                        self._add_order_to_tracking(order_specs[i], order_data)
                
                self.batch_stats['orders_placed'] += len(order_specs)
                debug_print(f"✅ [REAL API] Successfully placed {len(order_specs)} orders")
                return True
            else:
                debug_print(f"❌ [REAL API] Batch create failed: {response}")
                self.batch_stats['batch_errors'] += 1
                return False
                
        except Exception as e:
            debug_print(f"❌ [REAL API] Error in batch create: {e}")
            self.batch_stats['batch_errors'] += 1
            return False
    
    async def _simulated_batch_create(self, order_specs: List[Dict]) -> bool:
        """Create orders using TRUE PARALLEL execution with threads"""
        if not order_specs:
            return True
            
        try:
            debug_print(f"📤 [PARALLEL] Creating {len(order_specs)} orders on {min(len(order_specs), self.max_workers)} threads")
            
            parallel_start = time.time()
            loop = asyncio.get_event_loop()
            
            # Submit all create operations to thread pool simultaneously
            futures = []
            for spec in order_specs:
                future = loop.run_in_executor(self.executor, self._create_single_order_sync, spec)
                futures.append(future)
            
            # Wait for ALL operations to complete in parallel
            results = await asyncio.gather(*futures, return_exceptions=True)
            parallel_time = time.time() - parallel_start
            
            # Process results
            successful_creates = 0
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    debug_print(f"❌ Create failed for {order_specs[i]['ticker']}: {result}")
                elif result:
                    successful_creates += 1
                    self._add_order_to_tracking(order_specs[i], result)
            
            self.batch_stats['orders_placed'] += successful_creates
            debug_print(f"✅ [PARALLEL] Created {successful_creates}/{len(order_specs)} orders in {parallel_time*1000:.0f}ms")
            
            return successful_creates > 0
                
        except Exception as e:
            debug_print(f"❌ Error in parallel batch create: {e}")
            self.batch_stats['batch_errors'] += 1
            return False
    
        """Create a single order (used in simulated mode)"""
        try:
            response = submit_order(
                ticker=order_spec['ticker'],
                action=order_spec['action'],
                quantity=order_spec['quantity'],
                price=order_spec['price'],
                demo=self.demo
            )
            
            if response and 'order' in response:
                return response['order']
            return None
            
        except Exception as e:
            debug_print(f"❌ Error creating order for {order_spec['ticker']}: {e}")
            return None
    
    def _remove_order_from_tracking(self, order_id: str):
        """Remove an order from all tracking dictionaries (identical for both modes)"""
        for ticker in self.active_orders:
            if self.active_orders[ticker].get('bid_order_id') == order_id:
                self.active_orders[ticker]['bid_order_id'] = None
                self.live_quotes[ticker]['bid'] = None
                debug_print(f"🗑️ Removed bid tracking for {ticker}")
            elif self.active_orders[ticker].get('ask_order_id') == order_id:
                self.active_orders[ticker]['ask_order_id'] = None
                self.live_quotes[ticker]['ask'] = None
                debug_print(f"🗑️ Removed ask tracking for {ticker}")
        
        self.pending_fill_checks.pop(order_id, None)
    
    def _add_order_to_tracking(self, order_spec: Dict, order_data: Dict):
        """Add a new order to tracking dictionaries (identical for both modes)"""
        ticker = order_spec['ticker']
        side = order_spec['side']
        price = order_spec['price']
        order_id = order_data.get('order_id')
        
        if not order_id:
            debug_print(f"❌ No order_id in response for {ticker} {side}")
            return
        
        self._ensure_ticker_initialized(ticker)
        
        # Update active orders tracking
        if side == 'bid':
            self.active_orders[ticker]['bid_order_id'] = order_id
            self.live_quotes[ticker]['bid'] = price
        elif side == 'ask':
            self.active_orders[ticker]['ask_order_id'] = order_id
            self.live_quotes[ticker]['ask'] = price
        
        # Add to fill tracking
        self.pending_fill_checks[order_id] = {
            'ticker': ticker,
            'side': 'buy' if side == 'bid' else 'sell',
            'price': price,
            'size': order_spec['quantity'],
            'timestamp': time.time()
        }
        
        debug_print(f"📝 [{self.batch_mode}] Added {side} tracking for {ticker}: {order_id} @ {price}")
    
    async def check_fills_periodically(self):
        """Check fills periodically (identical for both modes)"""
        while True:
            try:
                await asyncio.sleep(self.fill_check_interval)
                await self._check_pending_fills()
            except Exception as e:
                debug_print(f"❌ Error in fill checking loop: {e}")
                await asyncio.sleep(5)
    
    async def _check_pending_fills(self):
        """Check all pending orders for fills (identical for both modes)"""
        if not self.pending_fill_checks:
            return
            
        for order_id, order_info in list(self.pending_fill_checks.items()):
            try:
                from utils import check_order_fill_status
                has_fills, fill_data = check_order_fill_status(order_id, demo=self.demo)
                
                if has_fills and fill_data:
                    await self._process_order_fills(order_id, order_info, fill_data)
                elif has_fills is None:
                    debug_print(f"⚠️ Removing order {order_id} from pending fills due to API error")
                    self.pending_fill_checks.pop(order_id, None)
                    
            except Exception as e:
                debug_print(f"❌ Error checking fills for order {order_id}: {e}")
    
    async def _process_order_fills(self, order_id: str, order_info: dict, fill_data: dict):
        """Process fills for an order (identical for both modes)"""
        ticker = self.safe_get(order_info, 'ticker')
        side = self.safe_get(order_info, 'side')
        
        if not ticker or not side:
            debug_print(f"❌ Invalid order info: ticker={ticker}, side={side}")
            return
        
        fills = self.safe_get(fill_data, 'fills', default=[])
        total_filled = 0
        
        for fill in fills:
            if not fill:
                continue
                
            fill_size = self.safe_get(fill, 'count', default=0)
            fill_price = self.safe_get(fill, 'yes_price', default=self.safe_get(order_info, 'price', default=0))
            
            if fill_size <= 0 or fill_price <= 0:
                continue
            
            try:
                self.mm._process_fill(ticker, side, fill_price, fill_size)
                total_filled += fill_size
                debug_print(f"💰 [{self.batch_mode}] FILL DETECTED: {ticker} {side.upper()} {fill_size} @ {fill_price}")
            except Exception as e:
                debug_print(f"❌ Error processing fill: {e}")
        
        if total_filled > 0:
            self.pending_fill_checks.pop(order_id, None)
            
            # If completely filled, clear from active orders
            order_size = self.safe_get(order_info, 'size', default=0)
            if total_filled >= order_size:
                side_key = 'bid' if side == 'buy' else 'ask'
                self._ensure_ticker_initialized(ticker)
                self.safe_set(self.active_orders, [ticker, f'{side_key}_order_id'], None)
                self.safe_set(self.live_quotes, [ticker, side_key], None)
    
    def get_order_status(self):
        """Get current status (identical for both modes)"""
        try:
            status = {
                'active_orders_count': 0,
                'pending_fills_count': len(self.pending_fill_checks),
                'live_quotes': self.live_quotes.copy(),
                'desired_quotes': self.desired_quotes.copy(),
                'active_orders': {},
                'batch_stats': self.batch_stats.copy(),
                'batch_interval': self.batch_interval,
                'mode': self.batch_mode
            }
            
            for ticker in self.mm.tickers:
                bid_order = self.safe_get(self.active_orders, ticker, 'bid_order_id')
                ask_order = self.safe_get(self.active_orders, ticker, 'ask_order_id')
                
                if bid_order or ask_order:
                    status['active_orders'][ticker] = {
                        'bid_order_id': bid_order,
                        'ask_order_id': ask_order
                    }
                    status['active_orders_count'] += (1 if bid_order else 0) + (1 if ask_order else 0)
            
            return status
            
        except Exception as e:
            debug_print(f"❌ Error getting order status: {e}")
            return {'error': str(e)}