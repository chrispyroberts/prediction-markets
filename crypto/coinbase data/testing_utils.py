import time
from typing import Dict, List, Tuple, Optional
from decimal import Decimal, ROUND_HALF_UP
import json
from collections import OrderedDict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OrderBook:
    def __init__(self, product_id: str, precision: int = 8):
        """
        Real-time order book with snapshot and update handling
        
        Args:
            product_id: Product identifier (e.g., "BTC-INTX-PERP")
            precision: Decimal precision for price calculations
        """
        self.product_id = product_id
        self.precision = precision
        
        # Order book data - using OrderedDict for sorted price levels
        self.bids: OrderedDict[Decimal, Decimal] = OrderedDict()  # price -> quantity
        self.asks: OrderedDict[Decimal, Decimal] = OrderedDict()  # price -> quantity
        self.best_bid = None  # (price, quantity)
        self.best_ask = None
        
        # Metadata
        self.last_update_time = None
        self.sequence_number = None
        self.is_initialized = False
        
        # Spread tracking
        self.current_spread = None
        self.spread_percentage = None
        self.mid_price = None
        
        # Statistics
        self.update_count = 0
        self.snapshot_count = 0
        
    def _decimal_price(self, price: str | float) -> Decimal:
        """Convert price to Decimal with proper precision"""
        return Decimal(str(price)).quantize(Decimal('0.' + '0' * self.precision), rounding=ROUND_HALF_UP)
    
    def _decimal_quantity(self, quantity: str | float) -> Decimal:
        """Convert quantity to Decimal with proper precision"""
        return Decimal(str(quantity)).quantize(Decimal('0.' + '0' * self.precision), rounding=ROUND_HALF_UP)
    
    def process_snapshot(self, snapshot_data: Dict) -> bool:
        """
        Process L2 snapshot to initialize the order book
        
        Args:
            snapshot_data: Snapshot message from WebSocket
            
        Returns:
            bool: True if snapshot was processed successfully
        """
        try:
            # Clear existing data
            self.bids.clear()
            self.asks.clear()
            
            # Extract updates from snapshot
            events = snapshot_data.get("events", [])
            
            for event in events:
                if event.get("type") == "snapshot":
                    updates = event.get("updates", [])
                    
                    for update in updates:
                        side = update.get("side")
                        price = self._decimal_price(update.get("price_level", 0))
                        quantity = self._decimal_quantity(update.get("new_quantity", 0))
                        
                        if side == "bid":
                            if quantity > 0:
                                self.bids[price] = quantity
                        elif side == "offer":  # asks
                            if quantity > 0:
                                self.asks[price] = quantity
            
            # Sort order book
            self._sort_order_book()
            
            # Calculate initial spread
            self._calculate_spread()
            
            # Update metadata
            self.last_update_time = time.time()
            self.is_initialized = True
            self.snapshot_count += 1
            
            logger.info(f"📸 Snapshot processed for {self.product_id}")
            logger.info(f"   Bids: {len(self.bids)} levels, Asks: {len(self.asks)} levels")
            logger.info(f"   Spread: ${self.current_spread:.2f} ({self.spread_percentage:.4f}%)")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing snapshot: {e}")
            return False
    
    def process_update(self, update_data: Dict) -> bool:
        """
        Process L2 update to maintain real-time order book
        
        Args:
            update_data: Update message from WebSocket
            
        Returns:
            bool: True if update was processed successfully
        """
        if not self.is_initialized:
            logger.warning("Order book not initialized. Need snapshot first.")
            return False
        
        try:
            events = update_data.get("events", [])
            
            for event in events:
                if event.get("type") == "update":
                    updates = event.get("updates", [])
                    
                    for update in updates:
                        side = update.get("side")
                        price = self._decimal_price(update.get("price_level", 0))
                        new_quantity = self._decimal_quantity(update.get("new_quantity", 0))
                        
                        # Apply update
                        if side == "bid":
                            if new_quantity == 0:
                                # Remove price level
                                self.bids.pop(price, None)
                            else:
                                # Update/add price level
                                self.bids[price] = new_quantity
                                
                        elif side == "offer":  # asks
                            if new_quantity == 0:
                                # Remove price level
                                self.asks.pop(price, None)
                            else:
                                # Update/add price level
                                self.asks[price] = new_quantity
            
            # Re-sort and recalculate after updates
            self._sort_order_book()
            self._calculate_spread()
            
            # Update metadata
            self.last_update_time = time.time()
            self.update_count += 1
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing update: {e}")
            return False
    
    def _sort_order_book(self):
        """Sort order book: bids descending (highest first), asks ascending (lowest first)"""
        # Sort bids in descending order (highest price first)
        self.bids = OrderedDict(sorted(self.bids.items(), key=lambda x: x[0], reverse=True))
        
        # Sort asks in ascending order (lowest price first)
        self.asks = OrderedDict(sorted(self.asks.items(), key=lambda x: x[0]))
    
    def _calculate_spread(self):
        """Calculate current spread, spread percentage, and mid price"""
        try:
            if not self.bids or not self.asks:
                self.current_spread = None
                self.spread_percentage = None
                self.mid_price = None
                return
            
            # Get best bid and ask
            best_bid = next(iter(self.bids))  # Highest bid
            best_ask = next(iter(self.asks))  # Lowest ask
            
            # Calculate spread
            self.current_spread = float(best_ask - best_bid)
            
            # Calculate mid price
            self.mid_price = float((best_bid + best_ask) / 2)
            
            # Calculate spread percentage
            if self.mid_price > 0:
                self.spread_percentage = (self.current_spread / self.mid_price) * 100
            else:
                self.spread_percentage = 0
                
        except Exception as e:
            logger.error(f"Error calculating spread: {e}")
            self.current_spread = None
            self.spread_percentage = None
            self.mid_price = None
    
    def get_best_bid(self) -> Optional[Tuple[Decimal, Decimal]]:
        """Get best bid (highest price)"""
        if self.bids:
            price = next(iter(self.bids))
            return (price, self.bids[price])
        return None
    
    def get_best_ask(self) -> Optional[Tuple[Decimal, Decimal]]:
        """Get best ask (lowest price)"""
        if self.asks:
            price = next(iter(self.asks))
            return (price, self.asks[price])
        return None
    
    def get_spread_info(self) -> Dict:
        """Get current spread information"""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()

        self.best_bid = best_bid
        self.best_ask = best_ask
        
        return {
            "product_id": self.product_id,
            "best_bid": {"price": float(best_bid[0]), "quantity": float(best_bid[1])} if best_bid else None,
            "best_ask": {"price": float(best_ask[0]), "quantity": float(best_ask[1])} if best_ask else None,
            "spread": self.current_spread,
            "spread_percentage": self.spread_percentage,
            "mid_price": self.mid_price,
            "last_update": self.last_update_time
        }
    
    def get_top_levels(self, levels: int = 5) -> Dict:
        """
        Get top N levels of the order book
        
        Args:
            levels: Number of price levels to return
        """
        bids_list = []
        asks_list = []
        
        # Get top bids (highest prices first)
        for i, (price, quantity) in enumerate(self.bids.items()):
            if i >= levels:
                break
            bids_list.append({"price": float(price), "quantity": float(quantity)})
        
        # Get top asks (lowest prices first)
        for i, (price, quantity) in enumerate(self.asks.items()):
            if i >= levels:
                break
            asks_list.append({"price": float(price), "quantity": float(quantity)})
        
        return {
            "product_id": self.product_id,
            "bids": bids_list,
            "asks": asks_list,
            "spread_info": self.get_spread_info()
        }
    
    def print_order_book(self, levels: int = 10):
        """Print formatted order book"""
        print(f"\n{'='*60}")
        print(f"ORDER BOOK - {self.product_id}")
        print(f"{'='*60}")
        
        if not self.is_initialized:
            print("❌ Order book not initialized")
            return
        
        spread_info = self.get_spread_info()
        print(f"Mid Price: ${spread_info['mid_price']:.2f}")
        print(f"Spread: ${spread_info['spread']:.2f} ({spread_info['spread_percentage']:.4f}%)")
        print(f"Updates: {self.update_count}, Snapshots: {self.snapshot_count}")
        print()
        
        # Print asks (highest to lowest, so reverse the list)
        asks_to_show = list(self.asks.items())[:levels]
        print("ASKS (Selling)")
        print("-" * 30)
        for price, quantity in reversed(asks_to_show):
            print(f"${float(price):>10.2f} | {float(quantity):>10.6f}")
        
        print("-" * 30)
        print(f"SPREAD: ${self.current_spread:.2f}")
        print("-" * 30)
        
        # Print bids (highest to lowest)
        bids_to_show = list(self.bids.items())[:levels]
        print("BIDS (Buying)")
        for price, quantity in bids_to_show:
            print(f"${float(price):>10.2f} | {float(quantity):>10.6f}")
        
        print("=" * 60)
    
    def print_top_orderbook(self):
        if self.best_bid is None or self.best_ask is None:
            print("Order book not initialized or empty.")
            return

        print(f"(BID | ASK): ${self.best_bid[0]:.2f} @ ({self.best_bid[1]:.6f}) | ${self.best_ask[0]:.2f} @ ({self.best_ask[1]:.6f})")

    def get_stats(self) -> Dict:
        """Get order book statistics"""
        return {
            "product_id": self.product_id,
            "is_initialized": self.is_initialized,
            "bid_levels": len(self.bids),
            "ask_levels": len(self.asks),
            "total_bid_volume": float(sum(self.bids.values())),
            "total_ask_volume": float(sum(self.asks.values())),
            "update_count": self.update_count,
            "snapshot_count": self.snapshot_count,
            "last_update_time": self.last_update_time,
            "spread_info": self.get_spread_info()
        }

# Example usage and testing
def test_orderbook():
    """Test the OrderBook class with sample data"""
    
    # Create order book
    ob = OrderBook("BTC-INTX-PERP")
    
    # Sample snapshot data (mimicking Coinbase Advanced Trade format)
    snapshot_data = {
        "channel": "level2",
        "client_id": "",
        "timestamp": "2023-06-15T10:00:00Z",
        "sequence_num": 0,
        "events": [
            {
                "type": "snapshot",
                "product_id": "BTC-INTX-PERP",
                "updates": [
                    {"side": "bid", "price_level": "50000.00", "new_quantity": "1.5"},
                    {"side": "bid", "price_level": "49999.50", "new_quantity": "2.0"},
                    {"side": "bid", "price_level": "49999.00", "new_quantity": "0.75"},
                    {"side": "offer", "price_level": "50001.00", "new_quantity": "1.2"},
                    {"side": "offer", "price_level": "50001.50", "new_quantity": "0.8"},
                    {"side": "offer", "price_level": "50002.00", "new_quantity": "2.5"},
                ]
            }
        ]
    }
    
    # Process snapshot
    print("🔄 Processing snapshot...")
    success = ob.process_snapshot(snapshot_data)
    print(f"Snapshot processed: {success}")
    
    # Print initial order book
    ob.print_order_book()
    
    # Sample update data
    update_data = {
        "channel": "level2",
        "client_id": "",
        "timestamp": "2023-06-15T10:00:05Z",
        "sequence_num": 1,
        "events": [
            {
                "type": "update",
                "product_id": "BTC-INTX-PERP",
                "updates": [
                    {"side": "bid", "price_level": "50000.50", "new_quantity": "3.0"},  # New bid
                    {"side": "offer", "price_level": "50001.00", "new_quantity": "0.0"},  # Remove ask
                    {"side": "offer", "price_level": "50000.75", "new_quantity": "1.5"},  # New best ask
                ]
            }
        ]
    }
    
    # Process update
    print("\n🔄 Processing update...")
    success = ob.process_update(update_data)
    print(f"Update processed: {success}")
    
    # Print updated order book
    ob.print_order_book()
    
    # Print statistics
    print("\n📊 Order Book Statistics:")
    stats = ob.get_stats()
    print(json.dumps(stats, indent=2, default=str))

if __name__ == "__main__":
    print("Real-time Order Book Class")
    print("=" * 50)
    print("Features:")
    print("- Snapshot initialization")
    print("- Real-time updates")
    print("- Spread calculation")
    print("- Order book visualization")
    print("=" * 50)
    
    # Run test
    test_orderbook()