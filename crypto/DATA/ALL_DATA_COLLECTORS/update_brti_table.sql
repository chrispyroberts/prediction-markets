-- =================================================================
--  Update BRTI Prices Table to Include Binance Option Price
-- =================================================================
--  This script adds the binance_option_price column to the existing
--  brti_prices table to store Binance option mark prices alongside
--  BRTI price data.
-- =================================================================

-- Add the binance_option_price column to the brti_prices table
ALTER TABLE brti_prices 
ADD COLUMN binance_option_price DOUBLE PRECISION;

-- Add a comment to document the new column
COMMENT ON COLUMN brti_prices.binance_option_price IS 
'Binance option mark price for near-the-money options expiring within 1 day';

-- =================================================================
--  End of Update Script
-- ================================================================= 