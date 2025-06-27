import sys
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QLabel, QHeaderView, QApplication
)
from PyQt6.QtCore import QTimer
import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm
from datetime import datetime
import pytz
import re

# Redis configuration
KALSHI_REDIS_URL = "redis://localhost"
KALSHI_REDIS_CHANNEL = "kalshi"

def get_expiration(ticker_str): 
    """
    Parses a Kalshi ticker string to get the expiration timestamp in milliseconds.
    The expected format is YYMMMDDHH (e.g., '25JUN2117').
    """
    # Example ticker: "INX-25JUN2117"
    # This means Year=25 (2025), Month=JUN, Day=21, Hour=17
    ticker_str = ticker_str.split('-')[1]

    # The format is YYMMMDDHH
    pattern = r'(\d{2})([A-Z]{3})(\d{2})(\d{2})'
    match = re.match(pattern, ticker_str)
    
    if not match:
        raise ValueError(f"Invalid ticker format: {ticker_str}. Expected format: YYMMMDDHH")
        
    # Correctly assign the parsed groups based on YYMMMDDHH format
    year_str, month_str, day_str, hour_str = match.groups()
    
    # Convert to integers
    year = 2000 + int(year_str)  # '25' -> 2025
    day = int(day_str)           # '21' -> 21
    hour = int(hour_str)         # '17' -> 17
    
    # Month mapping
    month_map = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
    }
    if month_str not in month_map:
        raise ValueError(f"Invalid month abbreviation: {month_str}")
        
    month = month_map[month_str]
    
    # Create timezone-aware datetime object robustly
    est_tz = pytz.timezone('US/Eastern')
    naive_dt = datetime(year, month, day, hour, 0, 0)
    expiry_dt = est_tz.localize(naive_dt)

    # Convert to milliseconds timestamp
    timestamp_ms = int(expiry_dt.timestamp() * 1000)
    return timestamp_ms

def get_time_to_expiry_hours(ticker):
    est_tz = pytz.timezone('US/Eastern')
    current_timestamp_ms = int(datetime.now(est_tz).timestamp() * 1000)
    tte = get_expiration(ticker) 
    tte_seconds = (tte - current_timestamp_ms) / 1000
    return tte_seconds / 3600

def binary_call_price(S, K, tte, sigma, r=0.0):
    d2 = (np.log(S / K) + (r - 0.5 * sigma**2) * tte) / (sigma * np.sqrt(tte))
    price = np.exp(-r * tte) * norm.cdf(d2)
    return price

# Function to solve: theoretical price - market price = 0
def implied_vol_binary_call(S, K, tte, market_price, r=0.0):
    def objective(sigma):
        return binary_call_price(S, K, tte, sigma, r) - market_price

    try:
        return brentq(objective, 1e-9, 5000.0, xtol=0.5, maxiter=1000)  # Search for sigma in [0.001, 200%]
    except ValueError:
        return None 

class KalshiMarketWindow(QWidget):
    def __init__(self, datahub_connection, shared_data_manager=None):
        super().__init__()
        self.setWindowTitle("Kalshi Market Orderbooks")
        self.resize(1100, 600)
        self.datahub = datahub_connection
        self.shared_data_manager = shared_data_manager
        self.latest_brti = None
        self.orderbooks = {}  # ticker -> orderbook dict
        self.strikes = {}     # ticker -> strike
        self.init_ui()
        self.setup_timers()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.status_label = QLabel("Waiting for data...")
        layout.addWidget(self.status_label)
        self.table = QTableWidget(0, 6)  # Changed from 7 to 6 columns
        self.table.setHorizontalHeaderLabels([
            "best_bid_qty", "best_bid", "strike", "best_ask", "best_ask_qty", "PREDICTED"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

    def setup_timers(self):
        # Poll for new data every second
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_table)
        self.timer.start(1000)
        
        # Request Kalshi data every second
        self.kalshi_timer = QTimer(self)
        self.kalshi_timer.timeout.connect(lambda: self.datahub.request('get_kalshi'))
        self.kalshi_timer.start(1000)
        
        # Request BRTI data every second
        self.brti_timer = QTimer(self)
        self.brti_timer.timeout.connect(lambda: self.datahub.request('get_brti'))
        self.brti_timer.start(500)
        
        # Subscribe to datahub signals
        self.datahub.data_received.connect(self.on_datahub_response)
        
        # Subscribe to shared data manager updates
        if self.shared_data_manager:
            self.shared_data_manager.vol_smile_updated.connect(self.on_vol_smile_updated)
        
        # Request initial data
        self.datahub.request('get_kalshi')
        self.datahub.request('get_brti')
        self.datahub.request('get_history', {'feed_name': 'brti'})

    def on_datahub_response(self, response):
        # print("Received response:", response)  # Debug print
        # print(f"Response type: {type(response)}")  # Debug print
        # print(f"Response keys: {response.keys() if isinstance(response, dict) else 'not a dict'}")  # Debug print
        
        # Handle responses
        if 'result' in response:
            result = response['result']
            #print(f"Result type: {type(result)}")  # Debug print
            #print(f"Result keys: {result.keys() if isinstance(result, dict) else 'not a dict'}")  # Debug print
            
            if isinstance(result, dict):
                # Check if it's BRTI data (has price field but no ticker field)
                if 'price' in result and 'ticker' not in result:
                    # BRTI data response
                    old_brti = self.latest_brti
                    self.latest_brti = result['price']
                    # print(f"BRTI UPDATE: {old_brti} -> {self.latest_brti}")  # Debug print
                elif 'ticker' in result:
                    print(f"Kalshi data found")
                    # Single Kalshi contract response
                    ticker = result['ticker']
                    strike = result.get('strike')
                    # print(f"Single Kalshi orderbook: ticker={ticker}, strike={strike}, data={result}")
                    if ticker and strike is not None:
                        self.orderbooks[ticker] = result
                        self.strikes[ticker] = strike
                        # print(f"Added single orderbook for {ticker} with strike {strike}")
                else:
                    # print(f"Kalshi data found")
                    # Kalshi data response (dict of contracts)
                    if result:  # If it's a dict of contracts
                        # print(f"Kalshi data found: {result}")  # Debug print
                        # print(f"Processing {len(result)} Kalshi contracts")  # Debug print
                        for ticker, ob in result.items():
                            # print(f"Processing ticker: {ticker}")  # Debug print
                            strike = ob.get('strike')
                            print(f"Orderbook received for ticker={ticker}, strike={strike}: {ob}")  # Debug print
                            if ticker and strike is not None:
                                self.orderbooks[ticker] = ob
                                self.strikes[ticker] = strike
                                # print(f"Added orderbook for {ticker} with strike {strike}")  # Debug print
                                # print(f"Skipping {ticker} - missing ticker or strike")  # Debug print
                    else:
                        print("No Kalshi data in result")  # Debug print
                
            elif isinstance(result, list):
                # get_history response for brti
                if result and 'price' in result[-1]:
                    old_brti = self.latest_brti
                    self.latest_brti = result[-1]['price']
                    # print(f"BRTI HISTORY UPDATE: {old_brti} -> {self.latest_brti}")  # Debug print
        elif 'price' in response:
            old_brti = self.latest_brti
            self.latest_brti = response['price']
            #print(f"BRTI DIRECT UPDATE: {old_brti} -> {self.latest_brti}")  # Debug print
        elif 'ticker' in response and 'strike' in response:
            # print(f"Orderbook update for ticker={response['ticker']}, strike={response['strike']}: {response}")  # Debug print
            self.orderbooks[response['ticker']] = response
            self.strikes[response['ticker']] = response['strike']

    def on_vol_smile_updated(self, params):
        """Handle vol smile parameter updates"""
        # Force refresh the table to recalculate predictions with new parameters
        self.refresh_table()

    def calculate_predicted_price(self, S, K, tte):
        """Calculate predicted price using vol smile parameters"""
        if not self.shared_data_manager:
            return None
            
        params = self.shared_data_manager.get_vol_smile_params()
        atm_vol = params.get('atm_vol', 0.0)
        vol_smile_b = params.get('vol_smile_b', 0.0)
        vol_smile_c = params.get('vol_smile_c', 0.0)
        sigmoid_x0 = params.get('sigmoid_x0', 0.0)
        sigmoid_d = params.get('sigmoid_d', 0.0)
        fitting_params = params.get('fitting_params', {})
        fit_type = params.get('fit_type', 'polynomial')
        
        if atm_vol <= 0:
            return None
            
        # Calculate moneyness
        moneyness = np.log(K / S) / np.sqrt(tte)
        
        # Calculate implied volatility using the selected fit type
        def fitted_vol_smile(k):
            if fit_type == "polynomial":
                params = fitting_params.get('polynomial', {})
                atm_vol_fit = params.get('atm_vol', atm_vol)
                b = params.get('b', vol_smile_b)
                c = params.get('c', vol_smile_c)
                return atm_vol_fit + b * k + c * k**2
            elif fit_type == "svi":
                params = fitting_params.get('svi', {})
                a = params.get('a', atm_vol)
                b = params.get('b', 0.1)
                rho = params.get('rho', 0.0)
                m = params.get('m', 0.0)
                sigma = params.get('sigma', 0.1)
                return a + b * (rho * (k - m) + np.sqrt((k - m)**2 + sigma**2))
            elif fit_type == "spline":
                params = fitting_params.get('spline', {})
                k_points = np.array(params.get('k_points', []))
                iv_points = np.array(params.get('iv_points', []))
                if len(k_points) > 0 and len(iv_points) > 0:
                    # Import here to avoid circular imports
                    from scipy.interpolate import CubicSpline
                    # Sort points by k to ensure proper spline fitting
                    sorted_indices = np.argsort(k_points)
                    k_sorted = k_points[sorted_indices]
                    iv_sorted = iv_points[sorted_indices]
                    # Create cubic spline
                    spline = CubicSpline(k_sorted, iv_sorted, bc_type='natural')
                    return spline(k)
                else:
                    return np.full_like(k, atm_vol)
            else:
                # Default to polynomial
                return atm_vol + vol_smile_b * k + vol_smile_c * k**2
        
        # Calculate implied volatility using fitted function
        implied_vol = fitted_vol_smile(moneyness)
        
        # Calculate d2
        d2 = (np.log(K / S) - 0.5 * implied_vol**2 * tte) / (implied_vol * np.sqrt(tte))
        
        # Calculate binary price using fitted sigmoid function
        # This uses the same sigmoid function as the Vol Smile Window
        predicted_price = 1 / (1 + np.exp(d2 * (sigmoid_x0 - sigmoid_d)))
        
        return predicted_price * 100  # Convert to percentage

    def refresh_table(self):
        # print("Latest BRTI:", self.latest_brti)  # Debug print
        # print("Orderbooks:", self.orderbooks)   # Debug print
        # print(f"Number of orderbooks received: {len(self.orderbooks)}")  # Debug print
        
        if self.latest_brti is None or not self.orderbooks:
            self.status_label.setText("Waiting for BRTI and Kalshi data...")
            return
        
        # Filter orderbooks within 750 of BRTI
        filtered = [
            (ticker, ob) for ticker, ob in self.orderbooks.items()
            if abs(self.strikes[ticker] - self.latest_brti) <= 1500
        ]
        #print(f"Filtered orderbooks (within 750): {filtered}")  # Debug print
        #print(f"Number of filtered orderbooks: {len(filtered)}")  # Debug print
        
        # Sort by strike descending
        filtered.sort(key=lambda x: self.strikes[x[0]], reverse=True)
        
        # Set table to have the right number of rows
        self.table.setRowCount(len(filtered))
        
        # Fill each row with data
        for row, (ticker, ob) in enumerate(filtered):
            S = self.latest_brti
            K = ob['strike']  # Use stored strike
            tte = get_time_to_expiry_hours(ticker) / 24 / 365  # Use real tte if available
            best_bid = ob['best_bid']
            best_ask = ob['best_ask']
            best_bid_qty = ob['best_bid_qty']
            best_ask_qty = ob['best_ask_qty']
            
            # Calculate predicted price
            predicted_price = self.calculate_predicted_price(S, K, tte)
            predicted_str = f"{predicted_price:.2f}" if predicted_price is not None else "N/A"
            
            # Fill table (6 columns now)
            self.table.setItem(row, 0, QTableWidgetItem(str(best_bid_qty)))
            self.table.setItem(row, 1, QTableWidgetItem(f"{best_bid:.2f}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{K:.2f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{best_ask:.2f}"))
            self.table.setItem(row, 4, QTableWidgetItem(str(best_ask_qty)))
            self.table.setItem(row, 5, QTableWidgetItem(predicted_str))
        
        self.status_label.setText(f"Showing {len(filtered)} strikes within 750 of BRTI {self.latest_brti:.2f}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # You would pass a real datahub connection here
    window = KalshiMarketWindow(datahub_connection=None)
    window.show()
    sys.exit(app.exec()) 