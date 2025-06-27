# =================================================================
#  Database Update Script for BRTI Prices Table
# =================================================================
#  This script runs the SQL update to add the binance_option_price
#  column to the existing brti_prices table.
# =================================================================

Write-Host "Updating BRTI prices table to include Binance option price column..." -ForegroundColor Green

# Database connection parameters
$DB_HOST = "localhost"
$DB_PORT = "5432"
$DB_NAME = "chris_db"
$DB_USER = "postgres"
$DB_PASS = "password"

# SQL file path
$SQL_FILE = "update_brti_table.sql"

# Check if SQL file exists
if (-not (Test-Path $SQL_FILE)) {
    Write-Host "ERROR: SQL file '$SQL_FILE' not found!" -ForegroundColor Red
    Write-Host "Please ensure you're running this script from the correct directory." -ForegroundColor Yellow
    exit 1
}

# Run the SQL update
try {
    $env:PGPASSWORD = $DB_PASS
    psql -h $DB_HOST -p $DB_PORT -d $DB_NAME -U $DB_USER -f $SQL_FILE
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "SUCCESS: Database table updated successfully!" -ForegroundColor Green
        Write-Host "The brti_prices table now includes the binance_option_price column." -ForegroundColor Cyan
    } else {
        Write-Host "ERROR: Failed to update database table." -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "ERROR: Failed to execute database update: $_" -ForegroundColor Red
    exit 1
} finally {
    # Clear the password environment variable
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

Write-Host "Database update completed!" -ForegroundColor Green 