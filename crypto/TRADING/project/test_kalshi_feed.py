#!/usr/bin/env python3
"""
Test script for Kalshi feed functionality
"""

import asyncio
import sys
import os

# Add the backend directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from backend.utils.kalshi_utils import get_current_event, get_markets_from_event, test_authentication

async def test_kalshi_feed():
    """Test Kalshi feed functionality"""
    print("Testing Kalshi feed functionality...")
    
    # Test authentication
    print("\n1. Testing authentication...")
    if test_authentication():
        print("✅ Authentication successful")
    else:
        print("❌ Authentication failed")
        return False
    
    # Test getting current event
    print("\n2. Testing event retrieval...")
    try:
        event = get_current_event()
        print(f"✅ Current event: {event}")
    except Exception as e:
        print(f"❌ Failed to get current event: {e}")
        return False
    
    # Test getting markets
    print("\n3. Testing market retrieval...")
    try:
        markets = get_markets_from_event(event)
        if markets:
            print(f"✅ Found {len(markets)} markets")
            for market in markets[:5]:  # Show first 5
                print(f"   - {market}")
            if len(markets) > 5:
                print(f"   ... and {len(markets) - 5} more")
        else:
            print("❌ No markets found")
            return False
    except Exception as e:
        print(f"❌ Failed to get markets: {e}")
        return False
    
    print("\n✅ All Kalshi feed tests passed!")
    return True

if __name__ == "__main__":
    success = asyncio.run(test_kalshi_feed())
    sys.exit(0 if success else 1) 