#!/bin/bash

# =================================================================
#  Database Update Script for BRTI Prices Table
# =================================================================
#  This script runs the SQL update to add the binance_option_price
#  column to the existing brti_prices table.
# =================================================================

echo "Updating BRTI prices table to include Binance option price column..."

# Database connection parameters
DB_HOST="localhost"
DB_PORT="5432"
DB_NAME="chris_db"
DB_USER="postgres"
DB_PASS="password"

# SQL file path
SQL_FILE="update_brti_table.sql"

# Check if SQL file exists
if [ ! -f "$SQL_FILE" ]; then
    echo "ERROR: SQL file '$SQL_FILE' not found!"
    echo "Please ensure you're running this script from the correct directory."
    exit 1
fi

# Run the SQL update
export PGPASSWORD="$DB_PASS"
psql -h "$DB_HOST" -p "$DB_PORT" -d "$DB_NAME" -U "$DB_USER" -f "$SQL_FILE"

if [ $? -eq 0 ]; then
    echo "SUCCESS: Database table updated successfully!"
    echo "The brti_prices table now includes the binance_option_price column."
else
    echo "ERROR: Failed to update database table."
    exit 1
fi

# Clear the password environment variable
unset PGPASSWORD

echo "Database update completed!" 