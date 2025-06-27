# BRTI Data Collector - Binance Option Price Integration

## Overview
The BRTI data collector has been enhanced to also retrieve Binance option mark prices whenever a new BRTI price is successfully collected. This provides additional market data for analysis and correlation studies.

## Changes Made

### 1. Enhanced Price Collection
- **Function**: `get_binance_option_mark_price(brti_price, symbol=None)`
  - Retrieves Binance option mark prices for near-the-money BTC options expiring within 1 day
  - Filters for options within $1000 of the current BRTI price
  - Returns the average mark price of qualifying options
  - Includes proper error handling and timeout protection

### 2. Database Schema Update
- **New Column**: `binance_option_price` (DOUBLE PRECISION, nullable)
  - Added to the `brti_prices` table
  - Stores the Binance option mark price alongside BRTI data
  - Allows for NULL values when option data is unavailable

### 3. Enhanced Data Flow
- **Price Collection**: Every successful BRTI price retrieval now also attempts to get Binance option prices
- **Database Storage**: Option prices are stored in the same batch as BRTI prices for efficiency
- **WebSocket Updates**: Option prices are included in real-time WebSocket emissions
- **REST API**: Option prices are available through the `/price` endpoint

### 4. Logging and Monitoring
- **Enhanced Logging**: Option prices are included in console output and log files
- **Error Handling**: Graceful handling when Binance API is unavailable
- **Performance**: Option price retrieval doesn't block BRTI price collection

## Database Setup

### For Existing Installations
If you have an existing database, run one of these scripts to add the new column:

**Windows (PowerShell):**
```powershell
cd DATA/ALL_DATA_COLLECTORS
.\run_database_update.ps1
```

**Linux/Mac (Bash):**
```bash
cd DATA/ALL_DATA_COLLECTORS
chmod +x run_database_update.sh
./run_database_update.sh
```

**Manual SQL:**
```sql
ALTER TABLE brti_prices ADD COLUMN binance_option_price DOUBLE PRECISION;
```

### For New Installations
The updated `create_database.sql` script now includes the `binance_option_price` column by default.

## API Changes

### WebSocket Events
The `price_update` event now includes:
```json
{
  "brti": 45000.50,
  "simple_average": 44985.25,
  "timestamp": "2024-01-15 14:30:25.123",
  "active_clients": 3,
  "binance_option_price": 44850.75
}
```

### REST API Endpoint
`GET /price` now returns:
```json
{
  "brti": 45000.50,
  "simple_average": 44985.25,
  "timestamp": "2024-01-15 14:30:25.123",
  "active_clients": 3,
  "binance_option_price": 44850.75
}
```

## Configuration

### Database Connection
The script uses the same database configuration as before:
- Host: localhost
- Port: 5432
- Database: chris_db
- User: postgres
- Password: password

### Binance API
- **Endpoint**: https://eapi.binance.com/eapi/v1/mark
- **Timeout**: 10 seconds
- **Filtering**: BTC options only, near-the-money, expiring within 1 day

## Error Handling

### Binance API Failures
- Network timeouts are handled gracefully
- Invalid responses are logged but don't stop BRTI collection
- Option prices are set to NULL when unavailable
- BRTI price collection continues uninterrupted

### Database Issues
- Option price insertion failures are logged
- Database rollback occurs on errors
- BRTI price collection continues even if option prices fail

## Performance Considerations

### API Rate Limits
- Binance API calls are made for every BRTI price update
- Consider implementing rate limiting if needed
- Current implementation includes 10-second timeout

### Database Impact
- Additional column increases storage requirements slightly
- Batch insertion maintains efficiency
- NULL values are stored for missing option data

## Monitoring

### Log Files
Check `logs/data_logs_2.log` for:
- Option price retrieval success/failure
- API response times
- Error patterns

### Console Output
Enhanced output format:
```
💰 BRTI QUEUED [2024-01-15 14:30:25.123] Price: $45,000.50 | Simple Avg: $44,985.25 | Binance Option: $44,850.75
```

## Troubleshooting

### Common Issues

1. **Database Column Missing**
   - Run the database update script
   - Check database connection and permissions

2. **Binance API Timeouts**
   - Check network connectivity
   - Verify Binance API status
   - Option prices will be NULL until resolved

3. **Permission Errors**
   - Ensure database user has ALTER TABLE permissions
   - Check file permissions for update scripts

### Debug Mode
Set `DEBUG = True` in the script to enable detailed logging of Binance API calls.

## Future Enhancements

Potential improvements:
- Configurable option filtering criteria
- Multiple exchange support
- Caching of option data
- Rate limiting implementation
- Additional option metrics (IV, delta, etc.) 