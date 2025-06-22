import pandas as pd
import sqlalchemy
import psycopg2

# --- Database Connection Details ---
DB_NAME = "chris_db"
DB_USER = "postgres"
DB_PASSWORD = "password"
DB_HOST = "localhost"
DB_PORT = "5432"

# Create the database connection URL
db_url = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Create a SQLAlchemy engine
try:
    engine = sqlalchemy.create_engine(db_url)
    print("Successfully connected to the database!")
except Exception as e:
    print(f"Failed to connect to the database. Error: {e}")
    exit(1)

# --- Query for Large Volume Trades (>100 BTC) ---
table_name_trades = "binance_trades"
query_large_trades = f"""
SELECT * FROM {table_name_trades} 
WHERE total_volume > 100 
ORDER BY total_volume DESC, timestamp_ms DESC;
"""

try:
    with engine.connect() as connection:
        df_large_trades = pd.read_sql(query_large_trades, connection)
    
    print(f"\nFound {len(df_large_trades)} trades with volume > 100 BTC")
    print(f"Total volume range: {df_large_trades['total_volume'].min():.2f} - {df_large_trades['total_volume'].max():.2f} BTC")
    
    if len(df_large_trades) == 0:
        print("No trades found with volume > 100 BTC")
        exit(0)
        
except Exception as e:
    print(f"Failed to query large trades. Error: {e}")
    exit(1)

# --- Find Orderbook Snapshots Near Large Trades ---
print("\nFinding orderbook snapshots within 1000ms of large trades...")

# Create a list to store all nearby orderbook snapshots
all_nearby_snapshots = []

for idx, trade_row in df_large_trades.iterrows():
    trade_timestamp = trade_row['timestamp_ms']
    trade_volume = trade_row['total_volume']
    
    # Query for orderbook snapshots within 1000ms (before and after)
    query_nearby_ob = f"""
    SELECT * FROM binance_orderbook_features 
    WHERE timestamp_ms BETWEEN {trade_timestamp - 1000} AND {trade_timestamp + 1000}
    ORDER BY ABS(timestamp_ms - {trade_timestamp}) ASC;
    """
    
    try:
        with engine.connect() as connection:
            nearby_snapshots = pd.read_sql(query_nearby_ob, connection)
        
        if len(nearby_snapshots) > 0:
            # Add trade information to each snapshot
            nearby_snapshots['large_trade_timestamp'] = trade_timestamp
            nearby_snapshots['large_trade_volume'] = trade_volume
            nearby_snapshots['time_diff_ms'] = nearby_snapshots['timestamp_ms'] - trade_timestamp
            
            all_nearby_snapshots.append(nearby_snapshots)
            print(f"Trade {idx+1}: Found {len(nearby_snapshots)} snapshots near {pd.to_datetime(trade_timestamp, unit='ms')} (Volume: {trade_volume:.2f} BTC)")
        else:
            print(f"Trade {idx+1}: No snapshots found near {pd.to_datetime(trade_timestamp, unit='ms')} (Volume: {trade_volume:.2f} BTC)")
            
    except Exception as e:
        print(f"Error querying snapshots for trade {idx+1}: {e}")

# Combine all nearby snapshots
if all_nearby_snapshots:
    df_nearby_snapshots = pd.concat(all_nearby_snapshots, ignore_index=True)
    print(f"\nTotal nearby snapshots found: {len(df_nearby_snapshots)}")
    
    # Show summary statistics
    print(f"\nTime difference statistics (ms):")
    print(df_nearby_snapshots['time_diff_ms'].describe())
    
    # Show the closest snapshots to each large trade
    print(f"\nClosest snapshots to each large trade:")
    closest_snapshots = df_nearby_snapshots.loc[df_nearby_snapshots.groupby('large_trade_timestamp')['time_diff_ms'].abs().idxmin()]
    
    # Display the closest snapshots
    display_columns = ['timestamp_ms', 'large_trade_timestamp', 'large_trade_volume', 'time_diff_ms', 
                      'bid_l1_price', 'ask_l1_price', 'bid_l1_cumulative_qty', 'ask_l1_cumulative_qty']
    print(closest_snapshots[display_columns].head(10).to_string())
    
    # Save to CSV for further analysis
    df_nearby_snapshots.to_csv('large_trades_with_nearby_orderbook.csv', index=False)
    print(f"\nSaved {len(df_nearby_snapshots)} snapshots to 'large_trades_with_nearby_orderbook.csv'")
    
    # Additional analysis: Show spread and liquidity around large trades
    print(f"\nOrderbook analysis around large trades:")
    print(f"Average bid-ask spread: {closest_snapshots['ask_l1_price'] - closest_snapshots['bid_l1_price']:.2f}")
    print(f"Average bid liquidity: {closest_snapshots['bid_l1_cumulative_qty'].mean():.2f} BTC")
    print(f"Average ask liquidity: {closest_snapshots['ask_l1_cumulative_qty'].mean():.2f} BTC")
    
else:
    print("No nearby snapshots found for any large trades.") 