#!/usr/bin/env python3
"""
Test script to verify the trading system setup
"""

import asyncio
import json
import redis.asyncio as aioredis
import sys
import os

# Add the backend directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

async def test_redis_connection():
    """Test Redis connection"""
    print("Testing Redis connection...")
    try:
        redis = aioredis.from_url("redis://localhost")
        await redis.ping()
        print("✓ Redis connection successful")
        return True
    except Exception as e:
        print(f"✗ Redis connection failed: {e}")
        return False

async def test_datahub_service():
    """Test DataHub service methods"""
    print("\nTesting DataHub service...")
    try:
        from backend.datahub_service import DataHubService
        
        service = DataHubService()
        service.redis = aioredis.from_url("redis://localhost")
        
        # Test get_all method
        result = await service.call_method('get_all', {})
        print(f"✓ DataHub get_all: {len(result)} feeds")
        
        # Test get_health method
        health = await service.call_method('get_health', {})
        print(f"✓ DataHub health: {len(health)} feeds")
        
        return True
    except Exception as e:
        print(f"✗ DataHub service test failed: {e}")
        return False

async def test_frontend_connection():
    """Test frontend Redis connection"""
    print("\nTesting frontend Redis connection...")
    try:
        redis = aioredis.from_url("redis://localhost")
        
        # Test publishing a message
        test_data = {"test": "data", "timestamp": 1234567890}
        await redis.publish("datahub_methods", json.dumps({
            "method": "get_all",
            "params": {},
            "id": "test-123"
        }))
        print("✓ Frontend can publish to Redis")
        
        return True
    except Exception as e:
        print(f"✗ Frontend connection test failed: {e}")
        return False

async def main():
    """Run all tests"""
    print("=== Trading System Setup Test ===\n")
    
    # Test Redis connection
    redis_ok = await test_redis_connection()
    
    # Test DataHub service
    datahub_ok = await test_datahub_service()
    
    # Test frontend connection
    frontend_ok = await test_frontend_connection()
    
    print("\n=== Test Results ===")
    print(f"Redis: {'✓' if redis_ok else '✗'}")
    print(f"DataHub Service: {'✓' if datahub_ok else '✗'}")
    print(f"Frontend Connection: {'✓' if frontend_ok else '✗'}")
    
    if all([redis_ok, datahub_ok, frontend_ok]):
        print("\n🎉 All tests passed! The system is ready to run.")
        print("\nTo start the system:")
        print("1. Make sure Redis is running: docker-compose up -d")
        print("2. Run the backend: python -m backend.main")
    else:
        print("\n❌ Some tests failed. Please check the setup.")
        if not redis_ok:
            print("- Make sure Redis is running: docker-compose up -d")
        if not datahub_ok:
            print("- Check that all backend dependencies are installed")
        if not frontend_ok:
            print("- Check that Redis is accessible")

if __name__ == "__main__":
    asyncio.run(main()) 