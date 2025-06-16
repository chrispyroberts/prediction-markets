import asyncio
import time
from typing import Dict, Optional, Tuple, Any


from utils import submit_order, cancel_order, check_order_fill_status, debug_print

class OrderManager:
    def __init__(self, mm_instance, demo=True):
        self.mm = mm_instance
        self.demo = demo
        
        # Track our active orders: {ticker: {'bid_order_id': str, 'ask_order_id': str}}
        self.active_orders = {ticker: {'bid_order_id': None, 'ask_order_id': None} 
                             for ticker in self.mm.tickers}
        
        # Track our current quotes that we've sent to market
        self.live_quotes = {ticker: {'bid': None, 'ask': None} 
                           for ticker in self.mm.tickers}
        
        # Order fill tracking
        self.pending_fill_checks = {}  # {order_id: {'ticker': str, 'side': str, 'price': int, 'size': int}}
        
        # Track pending cancellations to avoid race conditions
        self.pending_cancellations = set()  # {order_id}
        
        # Config
        self.order_timeout = 30  # seconds before we consider re-quoting
        self.fill_check_interval = 100  # seconds between fill checks
        self.cancel_wait_time = 0.5  # seconds to wait after cancellation before placing new order
    
    def safe_get(self, dictionary: dict, *keys, default=None) -> Any:
        """
        Safely access nested dictionary keys, returning default (None) if any key doesn't exist.
        """
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
        """
        Safely set a nested dictionary value, creating intermediate dicts as needed.
        """
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
        """Ensure ticker is properly initialized in our tracking dictionaries"""
        if ticker not in self.active_orders:
            self.active_orders[ticker] = {'bid_order_id': None, 'ask_order_id': None}
        else:
            if 'bid_order_id' not in self.active_orders[ticker]:
                self.active_orders[ticker]['bid_order_id'] = None
            if 'ask_order_id' not in self.active_orders[ticker]:
                self.active_orders[ticker]['ask_order_id'] = None
                
        if ticker not in self.live_quotes:
            self.live_quotes[ticker] = {'bid': None, 'ask': None}
        else:
            if 'bid' not in self.live_quotes[ticker]:
                self.live_quotes[ticker]['bid'] = None
            if 'ask' not in self.live_quotes[ticker]:
                self.live_quotes[ticker]['ask'] = None
        
    async def handle_quote_update(self, ticker: str):
        """
        Main function called whenever quotes are updated.
        Handles bid and ask separately with proper cancellation logic.
        """
        if not ticker:
            debug_print("❌ handle_quote_update called with empty ticker")
            return
            
        self._ensure_ticker_initialized(ticker)
        
        calculated_bid = self.safe_get(self.mm.our_quotes, ticker, 'bid')
        calculated_ask = self.safe_get(self.mm.our_quotes, ticker, 'ask')
        
        # debug_print(f"🔄 Quote update for {ticker}: New bid={calculated_bid}, New ask={calculated_ask}")
        
        # Handle bid and ask independently
        await self._handle_bid_logic(ticker, calculated_bid)
        await self._handle_ask_logic(ticker, calculated_ask)
    
    async def _handle_bid_logic(self, ticker: str, new_bid: Optional[int]):
        """
        Handle bid side logic:
        1. If new_bid is None: cancel any existing bid
        2. If new_bid exists: check if different from current, cancel old and place new
        """
        current_bid_order_id = self.safe_get(self.active_orders, ticker, 'bid_order_id')
        current_live_bid = self.safe_get(self.live_quotes, ticker, 'bid')
        
        # debug_print(f"📊 BID Logic for {ticker}:")
        # debug_print(f"  New bid: {new_bid}")
        # debug_print(f"  Current live bid: {current_live_bid}")
        # debug_print(f"  Current bid order ID: {current_bid_order_id}")
        
        # Case 1: New bid is None - we should cancel any existing bid
        if new_bid is None:
            if current_bid_order_id is not None:
                # debug_print(f"🚫 Case 1: New bid is None, cancelling existing bid order {current_bid_order_id}")
                await self._cancel_order_and_wait(ticker, 'bid')
            else:
                pass
                # debug_print(f"✅ Case 1: New bid is None, no existing bid to cancel")
            return
        
        # Case 2: New bid exists
        if current_bid_order_id is None:
            # No existing order, place new one
            # debug_print(f"📤 Case 2a: No existing bid, placing new bid at {new_bid}")
            await self._place_bid_order(ticker, new_bid)
        else:
            # Existing order exists, check if price is different
            if current_live_bid != new_bid:
                # debug_print(f"🔄 Case 2b: Price changed from {current_live_bid} to {new_bid}, cancelling and replacing")
                await self._cancel_order_and_wait(ticker, 'bid')
                await self._place_bid_order(ticker, new_bid)
            else:
                pass
                # debug_print(f"✅ Case 2c: Price unchanged at {new_bid}, keeping existing order")
    
    async def _handle_ask_logic(self, ticker: str, new_ask: Optional[int]):
        """
        Handle ask side logic:
        1. If new_ask is None: cancel any existing ask
        2. If new_ask exists: check if different from current, cancel old and place new
        """
        current_ask_order_id = self.safe_get(self.active_orders, ticker, 'ask_order_id')
        current_live_ask = self.safe_get(self.live_quotes, ticker, 'ask')
        
        # debug_print(f"📊 ASK Logic for {ticker}:")
        # debug_print(f"  New ask: {new_ask}")
        # debug_print(f"  Current live ask: {current_live_ask}")
        # debug_print(f"  Current ask order ID: {current_ask_order_id}")
        
        # Case 1: New ask is None - we should cancel any existing ask
        if new_ask is None:
            if current_ask_order_id is not None:
                # debug_print(f"🚫 Case 1: New ask is None, cancelling existing ask order {current_ask_order_id}")
                await self._cancel_order_and_wait(ticker, 'ask')
            else:
                pass
                # debug_print(f"✅ Case 1: New ask is None, no existing ask to cancel")
            return
        
        # Case 2: New ask exists
        if current_ask_order_id is None:
            # No existing order, place new one
            # debug_print(f"📤 Case 2a: No existing ask, placing new ask at {new_ask}")
            await self._place_ask_order(ticker, new_ask)
        else:
            # Existing order exists, check if price is different
            if current_live_ask != new_ask:
                # debug_print(f"🔄 Case 2b: Price changed from {current_live_ask} to {new_ask}, cancelling and replacing")
                await self._cancel_order_and_wait(ticker, 'ask')
                await self._place_ask_order(ticker, new_ask)
            else:
                pass
                # debug_print(f"✅ Case 2c: Price unchanged at {new_ask}, keeping existing order")
    
    async def _cancel_order_and_wait(self, ticker: str, side: str):
        """
        Cancel an order and wait for cancellation to complete before proceeding.
        """
        if not ticker or side not in ['bid', 'ask']:
            debug_print(f"❌ Invalid parameters for cancel: ticker={ticker}, side={side}")
            return False
            
        self._ensure_ticker_initialized(ticker)
        
        order_id = self.safe_get(self.active_orders, ticker, f'{side}_order_id')
        if order_id is None:
            debug_print(f"⚠️ No {side} order to cancel for {ticker}")
            return True
        
        if order_id in self.pending_cancellations:
            debug_print(f"⏳ {side} order {order_id} already being cancelled, waiting...")
            return False
            
        try:
            # debug_print(f"❌ Cancelling {side.upper()} order: {order_id} for {ticker}")
            self.pending_cancellations.add(order_id)
            
            response = cancel_order(order_id, demo=self.demo)
            
            # Wait a bit for cancellation to process
            await asyncio.sleep(self.cancel_wait_time)
            
            if response:
                pass
                # debug_print(f"✅ Successfully cancelled {side.upper()} order: {order_id}")
            else:
                debug_print(f"⚠️ Cancel response for {order_id}: {response}")
                
            return True
                
        except Exception as e:
            debug_print(f"❌ Error cancelling {side} order {order_id}: {e}")
            return False
        finally:
            # Clean up tracking regardless of cancel success
            self.safe_set(self.active_orders, [ticker, f'{side}_order_id'], None)
            self.safe_set(self.live_quotes, [ticker, side], None)
            self.pending_fill_checks.pop(order_id, None)
            self.pending_cancellations.discard(order_id)
    
    async def _place_bid_order(self, ticker: str, price: int):
        """Place a bid order (we want to buy at this price)"""
        if not ticker or price is None or price <= 0:
            debug_print(f"❌ Invalid parameters for bid order: ticker={ticker}, price={price}")
            return
            
        self._ensure_ticker_initialized(ticker)
        
        try:
            # debug_print(f"📤 Placing BID order: {ticker} @ {price} for {self.mm.mm_size}")
            
            response = submit_order(
                ticker=ticker,
                action="buy",
                quantity=self.mm.mm_size,
                price=price,
                demo=self.demo
            )
            
            if response and 'order' in response:
                order_id = self.safe_get(response, 'order', 'order_id')
                if order_id:
                    self.safe_set(self.active_orders, [ticker, 'bid_order_id'], order_id)
                    self.safe_set(self.live_quotes, [ticker, 'bid'], price)
                    
                    # Track for fill checking
                    self.pending_fill_checks[order_id] = {
                        'ticker': ticker,
                        'side': 'buy',
                        'price': price,
                        'size': self.mm.mm_size,
                        'timestamp': time.time()
                    }
                    
                    # debug_print(f"✅ BID order placed successfully: {order_id} at {price}")
                else:
                    debug_print(f"❌ No order_id in response: {response}")
            else:
                debug_print(f"❌ Failed to place BID order for {ticker}: {response}")
                
        except Exception as e:
            debug_print(f"❌ Error placing BID order for {ticker}: {e}")
    
    async def _place_ask_order(self, ticker: str, price: int):
        """Place an ask order (we want to sell at this price)"""
        if not ticker or price is None or price <= 0:
            debug_print(f"❌ Invalid parameters for ask order: ticker={ticker}, price={price}")
            return
            
        self._ensure_ticker_initialized(ticker)
        
        try:
            # debug_print(f"📤 Placing ASK order: {ticker} @ {price} for {self.mm.mm_size}")
            
            response = submit_order(
                ticker=ticker,
                action="sell",
                quantity=self.mm.mm_size,
                price=price,
                demo=self.demo
            )
            
            if response and 'order' in response:
                order_id = self.safe_get(response, 'order', 'order_id')
                if order_id:
                    self.safe_set(self.active_orders, [ticker, 'ask_order_id'], order_id)
                    self.safe_set(self.live_quotes, [ticker, 'ask'], price)
                    
                    # Track for fill checking
                    self.pending_fill_checks[order_id] = {
                        'ticker': ticker,
                        'side': 'sell',
                        'price': price,
                        'size': self.mm.mm_size,
                        'timestamp': time.time()
                    }
                    
                    # debug_print(f"✅ ASK order placed successfully: {order_id} at {price}")
                else:
                    debug_print(f"❌ No order_id in response: {response}")
            else:
                debug_print(f"❌ Failed to place ASK order for {ticker}: {response}")
                
        except Exception as e:
            debug_print(f"❌ Error placing ASK order for {ticker}: {e}")
    
    async def check_fills_periodically(self):
        """Periodically check for fills on our pending orders"""
        while True:
            try:
                await asyncio.sleep(self.fill_check_interval)
                await self._check_pending_fills()
            except Exception as e:
                debug_print(f"❌ Error in fill checking loop: {e}")
                await asyncio.sleep(5)  # Wait a bit longer on error
    
    async def _check_pending_fills(self):
        """Check all pending orders for fills"""
        if not self.pending_fill_checks:
            return
            
        for order_id, order_info in list(self.pending_fill_checks.items()):
            if not order_id or not order_info:
                debug_print(f"❌ Invalid order data: order_id={order_id}, order_info={order_info}")
                continue
                
            try:
                has_fills, fill_data = check_order_fill_status(order_id, demo=self.demo)
                
                if has_fills and fill_data:
                    await self._process_order_fills(order_id, order_info, fill_data)
                elif has_fills is None:
                    # API error, remove from pending to avoid infinite retries
                    debug_print(f"⚠️ Removing order {order_id} from pending fills due to API error")
                    self.pending_fill_checks.pop(order_id, None)
                    
            except Exception as e:
                debug_print(f"❌ Error checking fills for order {order_id}: {e}")
    
    async def _process_order_fills(self, order_id: str, order_info: dict, fill_data: dict):
        """Process fills for an order and update our market maker"""
        if not order_id or not order_info or not fill_data:
            debug_print(f"❌ Invalid fill data: order_id={order_id}")
            return
            
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
                debug_print(f"❌ Invalid fill data: size={fill_size}, price={fill_price}")
                continue
            
            # Update our market maker with the fill
            try:
                self.mm._process_fill(ticker, side, fill_price, fill_size)
                total_filled += fill_size
                debug_print(f"💰 FILL DETECTED: {ticker} {side.upper()} {fill_size} @ {fill_price}")
            except Exception as e:
                debug_print(f"❌ Error processing fill: {e}")
        
        if total_filled > 0:
            # Remove from pending fills since we've processed them
            self.pending_fill_checks.pop(order_id, None)
            
            # Update our order tracking
            side_key = 'bid' if side == 'buy' else 'ask'
                
            # If order was completely filled, clear it from active orders
            order_size = self.safe_get(order_info, 'size', default=0)
            if total_filled >= order_size:
                self._ensure_ticker_initialized(ticker)
                self.safe_set(self.active_orders, [ticker, f'{side_key}_order_id'], None)
                self.safe_set(self.live_quotes, [ticker, side_key], None)
                debug_print(f"📝 Order {order_id} completely filled, cleared from active orders")
    
    def get_order_status(self):
        """Get current status of all orders"""
        try:
            status = {
                'active_orders_count': 0,
                'pending_fills_count': len(self.pending_fill_checks),
                'pending_cancellations_count': len(self.pending_cancellations),
                'live_quotes': self.live_quotes.copy(),
                'active_orders': {}
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
            return {
                'active_orders_count': 0,
                'pending_fills_count': 0,
                'pending_cancellations_count': 0,
                'live_quotes': {},
                'active_orders': {},
                'error': str(e)
            }