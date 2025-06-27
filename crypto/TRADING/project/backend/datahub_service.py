#!/usr/bin/env python3
"""
DataHub Service - Direct access to DataHub via Redis
Allows frontend to call DataHub methods directly without HTTP overhead
"""

import asyncio
import json
import time
import redis.asyncio as aioredis
from typing import Dict, Any, Optional, Type
from pydantic import BaseModel, ValidationError
from collections import deque
from .models import (
    FeedDataModel, Heartbeat, BRTIFeedData, BinanceVolSmileData,
    KalshiOrderbookData, KalshiTradeData, KalshiFullOrderbookData
)
from . import (
    DATAHUB_REDIS_URL, DATAHUB_HEARTBEAT_TIMEOUT, DATAHUB_DATA_TIMEOUT,
    BRTI_REDIS_CHANNEL, BINANCE_VOL_REDIS_CHANNEL, KALSHI_REDIS_CHANNEL,
    FEED_TIMEOUTS
)

# Per-feed rolling window sizes
FEED_HISTORY_LENGTHS = {
    "brti": 60,
    # Add more feeds and their history lengths here
}

FEED_MODEL_MAP = {
    "brti": BRTIFeedData,
    "binance_vol_smile": BinanceVolSmileData,
    "kalshi": [KalshiFullOrderbookData, KalshiTradeData],  # Handle both orderbook and trade data
    # Add more mappings as needed
}

class DataHub:
    """
    Central aggregator for all real-time data feeds.
    Tracks latest data (as Pydantic models), last update times, and provides health status.
    Separately tracks heartbeat and real data health for each feed, with per-feed timeouts.
    """
    def __init__(self):
        self.state: Dict[str, FeedDataModel] = {}
        self.kalshi_state: Dict[str, KalshiFullOrderbookData] = {}  # Store Kalshi data by ticker
        self.last_data_update: Dict[str, float] = {}
        self.last_heartbeat: Dict[str, float] = {}
        self.heartbeat_timeouts: Dict[str, float] = {}  # Per-feed heartbeat timeout
        self.data_timeouts: Dict[str, float] = {}       # Per-feed data timeout
        self.default_heartbeat_timeout: float = 10.0
        self.default_data_timeout: float = 10.0
        self.lock = asyncio.Lock()
        # Per-feed rolling buffers for recent data
        self.history_buffers: Dict[str, deque] = {
            feed: deque(maxlen=length) for feed, length in FEED_HISTORY_LENGTHS.items()
        }
        # Set per-feed timeouts from config
        for feed, timeouts in FEED_TIMEOUTS.items():
            self.set_heartbeat_timeout(feed, timeouts["heartbeat"])
            self.set_data_timeout(feed, timeouts["data"])

    async def update(self, feed_name: str, data: FeedDataModel):
        async with self.lock:
            if isinstance(data, Heartbeat):
                self.last_heartbeat[data.feed] = data.timestamp
            else:
                # For Kalshi, store by ticker instead of feed name
                if feed_name == 'kalshi':
                    if isinstance(data, KalshiFullOrderbookData):
                        # print(f"DataHub: Storing Kalshi orderbook for ticker {data.ticker}")
                        self.kalshi_state[data.ticker] = data
                        self.last_data_update[feed_name] = data.timestamp
                        if feed_name in self.history_buffers:
                            self.history_buffers[feed_name].append(data)
                            # print(f"Added to {feed_name} history buffer. Buffer size: {len(self.history_buffers[feed_name])}")
                    else:
                        # print(f"Ignoring Kalshi trade data, only storing orderbook data")
                        return
                else:
                    # For other feeds, store by feed name
                    self.state[feed_name] = data
                    self.last_data_update[feed_name] = data.timestamp
                    if feed_name in self.history_buffers:
                        self.history_buffers[feed_name].append(data)
                        # print(f"Added to {feed_name} history buffer. Buffer size: {len(self.history_buffers[feed_name])}")

    def set_heartbeat_timeout(self, feed_name: str, timeout: float):
        self.heartbeat_timeouts[feed_name] = timeout

    def set_data_timeout(self, feed_name: str, timeout: float):
        self.data_timeouts[feed_name] = timeout

    async def get(self, feed_name: str) -> Optional[FeedDataModel]:
        async with self.lock:
            if feed_name == 'kalshi':
                # Return all Kalshi contracts as a dict
                return self.kalshi_state
            return self.state.get(feed_name)

    async def get_all(self) -> Dict[str, FeedDataModel]:
        async with self.lock:
            result = dict(self.state)
            # Add Kalshi contracts to the result
            if self.kalshi_state:
                print(f"DataHub: Returning {len(self.kalshi_state)} Kalshi contracts")
                result['kalshi'] = self.kalshi_state
            else:
                print("DataHub: No Kalshi contracts to return")
            return result

    async def get_health(self) -> Dict[str, Dict[str, bool]]:
        now = time.time()
        async with self.lock:
            feeds = set(self.last_heartbeat.keys()) | set(self.last_data_update.keys())
            return {
                feed: {
                    'heartbeat_healthy': (now - self.last_heartbeat.get(feed, 0)) < self.heartbeat_timeouts.get(feed, self.default_heartbeat_timeout),
                    'data_healthy': (now - self.last_data_update.get(feed, 0)) < self.data_timeouts.get(feed, self.default_data_timeout)
                }
                for feed in feeds
            }

    async def subscribe_to_all_feeds(self):
        redis = aioredis.from_url(DATAHUB_REDIS_URL)
        pubsub = redis.pubsub()
        channels = list(FEED_TIMEOUTS.keys())
        await pubsub.subscribe(*channels)
        print(f"Subscribed to channels: {channels}")
        async for message in pubsub.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    feed = message['channel'].decode() if isinstance(message['channel'], bytes) else message['channel']
                    # print(f"DataHub: Received message on channel {feed}")
                    
                    if isinstance(data, dict) and data.get("type") == "heartbeat":
                        model = Heartbeat(**data)
                        await self.update(feed, model)
                    else:
                        model_cls = FEED_MODEL_MAP.get(feed)
                        if model_cls:
                            if isinstance(model_cls, list):
                                model = None
                                for cls in model_cls:
                                    try:
                                        # Parse JSON data into Pydantic model
                                        model = cls(**data)
                                        # print(f"DataHub: Successfully parsed {feed} data as {cls.__name__}")
                                        break
                                    except Exception as parse_error:
                                        print(f"Failed to parse with {cls.__name__}: {parse_error}")
                                        continue
                                if model:
                                    await self.update(feed, model)
                                else:
                                    print(f"Could not parse Kalshi data with any model type")
                            else:
                                # Parse JSON data into Pydantic model
                                model = model_cls(**data)
                                # print(f"DataHub: Successfully parsed {feed} data as {model_cls.__name__}")
                                await self.update(feed, model)
                        else:
                            print(f"Unknown feed: {feed}")
                except Exception as e:
                    print(f"Error parsing message: {e}")

    async def get_history(self, feed_name: str):
        async with self.lock:
            buf = self.history_buffers.get(feed_name)
            if buf is not None:
                history = [item.model_dump() for item in buf]
                print(f"History requested for {feed_name}. Returning {len(history)} items.")
                return history
            print(f"No history buffer found for {feed_name}")
            return []

    async def get_kalshi(self) -> Dict[str, KalshiFullOrderbookData]:
        """Get all Kalshi orderbook data"""
        async with self.lock:
            # print(f"DataHub get_kalshi: Returning {len(self.kalshi_state)} contracts")
            # print(f"DataHub get_kalshi: Contract tickers: {list(self.kalshi_state.keys())}")
            return dict(self.kalshi_state)

    async def get_brti(self) -> Optional[BRTIFeedData]:
        """Get latest BRTI data"""
        async with self.lock:
            return self.state.get('brti')

class FeedStatus:
    def __init__(self, name: str):
        self.name = name
        self.last_heartbeat: Optional[float] = None
        self.last_data: Optional[float] = None
        self.is_alive = False
        self.data_count = 0

    def update_heartbeat(self, timestamp: float):
        self.last_heartbeat = timestamp
        self.is_alive = True

    def update_data(self, timestamp: float):
        self.last_data = timestamp
        self.data_count += 1

    def check_timeout(self, current_time: float, heartbeat_timeout: float, data_timeout: float) -> bool:
        """Check if feed has timed out"""
        if self.last_heartbeat and (current_time - self.last_heartbeat) > heartbeat_timeout:
            self.is_alive = False
            return True
        return False

class DataHubService:
    """Service that exposes DataHub methods via Redis pub/sub"""
    
    def __init__(self):
        self.datahub = DataHub()
        self.redis = None
        self.running = True
        self.feeds: Dict[str, FeedStatus] = {
            'brti': FeedStatus('brti'),
            'binance_vol_smile': FeedStatus('binance_vol_smile'),
            'kalshi': FeedStatus('kalshi')
        }
        
    async def start(self):
        """Start the DataHub service"""
        self.redis = aioredis.from_url(DATAHUB_REDIS_URL)
        self.running = True
        
        print("DataHub Service started")
        print(f"Monitoring feeds: {list(self.feeds.keys())}")
        print(f"Heartbeat timeout: {DATAHUB_HEARTBEAT_TIMEOUT}s")
        print(f"Data timeout: {DATAHUB_DATA_TIMEOUT}s")
        
        # Start both feed subscription (for rolling buffers) and monitoring tasks
        await asyncio.gather(
            self.datahub.subscribe_to_all_feeds(),
            self.monitor_feeds(),
            self.handle_method_calls(),
            self.status_reporter()
        )
        
    async def monitor_feeds(self):
        """Monitor all feeds and update status"""
        pubsub = self.redis.pubsub()
        channels = [BRTI_REDIS_CHANNEL, BINANCE_VOL_REDIS_CHANNEL, KALSHI_REDIS_CHANNEL]
        await pubsub.subscribe(*channels)
        
        async for message in pubsub.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    channel = message['channel'].decode() if isinstance(message['channel'], bytes) else message['channel']
                    
                    # Map channel to feed name
                    feed_name = None
                    if channel == BRTI_REDIS_CHANNEL:
                        feed_name = 'brti'
                    elif channel == BINANCE_VOL_REDIS_CHANNEL:
                        feed_name = 'binance_vol_smile'
                    elif channel == KALSHI_REDIS_CHANNEL:
                        feed_name = 'kalshi'
                    
                    if feed_name and feed_name in self.feeds:
                        feed_status = self.feeds[feed_name]
                        
                        if data.get('type') == 'heartbeat':
                            feed_status.update_heartbeat(data['timestamp'])
                        else:
                            feed_status.update_data(data['timestamp'])
                            
                except Exception as e:
                    print(f"Error processing feed message: {e}")

    async def handle_method_calls(self):
        """Handle method calls from frontend via Redis"""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe("datahub_methods")
        print("DataHub service: Listening for method calls on datahub_methods channel")
        
        async for message in pubsub.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    method = data.get('method')
                    params = data.get('params', {})
                    request_id = data.get('id')
                    
                    print(f"DataHub service: Received method call: {method} (id: {request_id})")
                    
                    # Call the method
                    result = await self.call_method(method, params)
                    
                    print(f"DataHub service: Method {method} returned result type: {type(result)}")
                    if isinstance(result, dict):
                        print(f"DataHub service: Result has {len(result)} keys: {list(result.keys())}")
                    
                    # Send response
                    response = {
                        'id': request_id,
                        'result': result,
                        'timestamp': time.time()
                    }
                    
                    await self.redis.publish(f"datahub_response_{request_id}", json.dumps(response))
                    print(f"DataHub service: Sent response for {method} (id: {request_id})")
                    
                except Exception as e:
                    print(f"DataHub service: Error handling method call: {e}")
                    # Send error response
                    error_response = {
                        'id': data.get('id'),
                        'error': str(e),
                        'timestamp': time.time()
                    }
                    await self.redis.publish(f"datahub_response_{data.get('id')}", json.dumps(error_response))
                    
    async def call_method(self, method, params):
        """Call a DataHub method"""
        if method == 'get_all':
            all_data = await self.datahub.get_all()
            result = {}
            for k, v in all_data.items():
                if k == 'kalshi':
                    # Kalshi data is already a dict of Pydantic models, convert each to dict
                    result[k] = {ticker: contract.model_dump() for ticker, contract in v.items()}
                else:
                    # Other feeds are single Pydantic models
                    result[k] = v.model_dump()
            return result
        elif method == 'get_kalshi':
            print(f"DataHub call_method: get_kalshi requested")
            kalshi_data = await self.datahub.get_kalshi()
            print(f"DataHub call_method: got {len(kalshi_data)} contracts from get_kalshi")
            result = {ticker: contract.model_dump() for ticker, contract in kalshi_data.items()}
            print(f"DataHub call_method: returning {len(result)} contracts")
            return result
        elif method == 'get_brti':
            brti_data = await self.datahub.get_brti()
            return brti_data.model_dump() if brti_data else None
        elif method == 'get_health':
            return await self.datahub.get_health()
        elif method == 'get_history':
            feed_name = params.get('feed_name')
            if feed_name:
                return await self.datahub.get_history(feed_name)
            else:
                raise ValueError("feed_name parameter required")
        else:
            raise ValueError(f"Unknown method: {method}")

    async def status_reporter(self):
        """Report feed status periodically"""
        while self.running:
            current_time = time.time()
            
            print("\n" + "="*60)
            print(f"DataHub Status Report - {time.strftime('%H:%M:%S')}")
            print("="*60)
            
            for feed_name, feed_status in self.feeds.items():
                status = "🟢 ALIVE" if feed_status.is_alive else "🔴 DEAD"
                
                heartbeat_age = "N/A"
                if feed_status.last_heartbeat:
                    age = current_time - feed_status.last_heartbeat
                    heartbeat_age = f"{age:.1f}s"
                
                data_age = "N/A"
                if feed_status.last_data:
                    age = current_time - feed_status.last_data
                    data_age = f"{age:.1f}s"
                
                print(f"{feed_name:20} | {status:10} | Heartbeat: {heartbeat_age:>8} | Data: {data_age:>8} | Count: {feed_status.data_count}")
            
            print("="*60)
            
            # Check for timeouts
            for feed_name, feed_status in self.feeds.items():
                if feed_status.check_timeout(current_time, DATAHUB_HEARTBEAT_TIMEOUT, DATAHUB_DATA_TIMEOUT):
                    print(f"⚠️  WARNING: {feed_name} feed has timed out!")
            
            await asyncio.sleep(10)  # Report every 10 seconds for better visibility
            
    def stop(self):
        """Stop the service"""
        self.running = False

async def main():
    """Main entry point"""
    service = DataHubService()
    try:
        await service.start()
    except KeyboardInterrupt:
        print("\nShutting down DataHub Service...")
        service.stop()

if __name__ == "__main__":
    asyncio.run(main()) 