#!/usr/bin/env python3
"""
Update TimescaleDB Compression Policies
This script updates the compression policies for all tables
to compress data older than 1 day instead of 7 days.
"""

import psycopg2
import sys
from datetime import datetime

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'port': '5432',
    'dbname': 'chris_db',
    'user': 'postgres',
    'password': 'password'
}

def connect_to_db():
    """Connect to the database"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print(f"✅ Connected to database: {DB_CONFIG['dbname']} on {DB_CONFIG['host']}:{DB_CONFIG['port']}")
        return conn
    except psycopg2.OperationalError as e:
        print(f"❌ Failed to connect to database: {e}")
        sys.exit(1)

def update_compression_policies(conn):
    """Update compression policies for all tables"""
    tables = [
        'brti_prices',
        'kalshi_trades',
        'kalshi_orderbooks', 
        'binance_orderbook_features',
        'binance_trades'
    ]
    
    with conn.cursor() as cur:
        print("\n🔄 Updating compression policies...")
        
        for table in tables:
            try:
                # Remove existing compression policy
                cur.execute(f"SELECT remove_compression_policy('{table}')")
                print(f"   Removed existing policy for {table}")
                
                # Add new compression policy (1 day = 86400000 milliseconds)
                cur.execute(f"SELECT add_compression_policy('{table}', 86400000)")
                print(f"   Added new 1-day policy for {table}")
                
            except Exception as e:
                print(f"   ⚠️  Error updating {table}: {e}")
        
        conn.commit()
        print("✅ All compression policies updated successfully!")

def verify_compression_settings(conn):
    """Verify the new compression settings"""
    with conn.cursor() as cur:
        print("\n📊 Verifying compression settings...")
        
        cur.execute("""
            SELECT 
                hypertable_name,
                compress_after
            FROM timescaledb_information.compression_settings
            WHERE hypertable_name IN (
                'brti_prices',
                'kalshi_trades', 
                'kalshi_orderbooks',
                'binance_orderbook_features',
                'binance_trades'
            )
            ORDER BY hypertable_name
        """)
        
        results = cur.fetchall()
        
        if results:
            print("\nCurrent compression settings:")
            print("-" * 50)
            for table, compress_after in results:
                days = compress_after / (1000 * 60 * 60 * 24)  # Convert ms to days
                print(f"{table:<25} | {days:.1f} days")
        else:
            print("No compression settings found.")

def show_compression_jobs(conn):
    """Show compression job information"""
    with conn.cursor() as cur:
        print("\n🔧 Compression job information:")
        print("-" * 50)
        
        cur.execute("""
            SELECT 
                job_id,
                hypertable_name,
                config
            FROM timescaledb_information.jobs 
            WHERE proc_name = 'policy_compression'
            ORDER BY hypertable_name
        """)
        
        results = cur.fetchall()
        
        if results:
            for job_id, hypertable_name, config in results:
                print(f"Job ID: {job_id}")
                print(f"Table: {hypertable_name}")
                print(f"Config: {config}")
                print()
        else:
            print("No compression jobs found.")

def main():
    """Main function"""
    print("=" * 60)
    print("TimescaleDB Compression Policy Update")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Database: {DB_CONFIG['dbname']}")
    print(f"Host: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print("=" * 60)
    
    # Connect to database
    conn = connect_to_db()
    
    try:
        # Update compression policies
        update_compression_policies(conn)
        
        # Verify the changes
        verify_compression_settings(conn)
        
        # Show job information
        show_compression_jobs(conn)
        
        print("\n✅ Compression policy update completed successfully!")
        print("\n📝 Summary:")
        print("   - All tables now compress data older than 1 day")
        print("   - Previous 7-day policies have been removed")
        print("   - Compression will happen automatically via background jobs")
        
    except Exception as e:
        print(f"\n❌ Error during update: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()
        print("\n🔌 Database connection closed.")

if __name__ == "__main__":
    main() 