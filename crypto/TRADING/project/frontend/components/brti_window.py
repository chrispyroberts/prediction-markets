#!/usr/bin/env python3
"""
BRTI Price Chart Window
Real-time BRTI price chart with live updates
"""

import sys
import json
import asyncio
import uuid
import time
import redis.asyncio as aioredis
from datetime import datetime
from collections import deque
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QFrame)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates
import numpy as np
import matplotlib.ticker as mticker

class BrtiDataThread(QThread):
    """Background thread for BRTI data collection using Redis"""
    data_updated = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, datahub_connection):
        super().__init__()
        self.datahub = datahub_connection
        self.running = True
        self.current_data = None
        self.redis = None
        
    def run(self):
        asyncio.run(self._run_data_collection())
        
    async def _run_data_collection(self):
        """Collect real-time data from Redis stream"""
        try:
            # Connect to Redis
            self.redis = aioredis.from_url("redis://localhost")
            
            # Subscribe to BRTI data stream
            await self._stream_subscription()
        except Exception as e:
            self.error.emit(f"Data collection error: {e}")
        
    async def _stream_subscription(self):
        """Subscribe to BRTI data stream"""
        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe("brti")
            
            async for message in pubsub.listen():
                if not self.running:
                    break
                if message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        print(f"Stream data received: {type(data)}")
                        if isinstance(data, dict):
                            print(f"Stream data keys: {list(data.keys())}")
                        
                        # Ignore heartbeats
                        if data.get("type") == "heartbeat":
                            continue
                        self.current_data = data
                        self.data_updated.emit(data)
                    except Exception as e:
                        self.error.emit(f"Stream data error: {e}")
        except Exception as e:
            self.error.emit(f"Stream subscription error: {e}")
            
    def stop(self):
        self.running = False

class BrtiChart(FigureCanvas):
    """Matplotlib chart widget for BRTI data"""
    
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(10, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        
        # Setup chart
        self.setup_chart()
        
    def setup_chart(self):
        """Setup chart appearance"""
        self.ax.set_title('BRTI Price Chart', fontsize=16, fontweight='bold')
        self.ax.set_xlabel('Time', fontsize=12)
        self.ax.set_ylabel('Price ($)', fontsize=12)
        self.ax.grid(True, alpha=0.3)
        
        # Add proper margins to prevent cutoff
        self.fig.subplots_adjust(left=0.1, right=0.95, top=0.9, bottom=0.15)
        
    def update_chart(self, history_data):
        """Update chart with new data"""
        if not history_data:
            return
            
        # Ensure history_data is a list
        if not isinstance(history_data, list):
            print(f"Warning: history_data is not a list, got {type(history_data)}")
            return
            
        self.ax.clear()
        self.setup_chart()
        
        # Extract data with proper error handling
        timestamps = []
        prices = []
        
        for point in history_data:
            try:
                # Ensure point is a dictionary
                if not isinstance(point, dict):
                    print(f"Warning: Skipping non-dict point: {type(point)}")
                    continue
                    
                # Check if required keys exist
                if 'timestamp' not in point or 'price' not in point:
                    print(f"Warning: Missing required keys in point: {point.keys()}")
                    continue
                    
                timestamp = point['timestamp']
                price = point['price']
                
                # Validate data types
                if not isinstance(timestamp, (int, float)) or not isinstance(price, (int, float)):
                    print(f"Warning: Invalid data types - timestamp: {type(timestamp)}, price: {type(price)}")
                    continue
                    
                timestamps.append(datetime.fromtimestamp(timestamp))
                prices.append(price)
                
            except Exception as e:
                print(f"Warning: Error processing data point: {e}")
                continue
        
        # Only plot if we have valid data
        if not timestamps or not prices:
            print("Warning: No valid data points to plot")
            return
        
        # Plot data
        self.ax.plot(timestamps, prices, 'b-', linewidth=2, alpha=0.8)
        
        # Format x-axis
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=1))
        
        # Format y-axis as currency
        self.ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'${x:,.2f}'))
        
        # Rotate x-axis labels
        plt.setp(self.ax.xaxis.get_majorticklabels(), rotation=45)
        
        # Add current price annotation
        if prices:
            current_price = prices[-1]
            self.ax.axhline(y=current_price, color='r', linestyle='--', alpha=0.5)
            self.ax.text(0.02, 0.98, f'Current: ${current_price:,.2f}', 
                        transform=self.ax.transAxes, fontsize=12, 
                        verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        # Ensure proper layout
        self.fig.tight_layout()
        self.draw()

class BrtiWindow(QMainWindow):
    """BRTI Price Chart Window"""
    
    def __init__(self, datahub_connection):
        super().__init__()
        self.setWindowTitle("BRTI Price Chart")
        self.setGeometry(200, 200, 1200, 800)
        self.datahub = datahub_connection
        self.setup_ui()
        self.setup_data_thread()
        
        # Add timeout tracking
        self.last_datahub_response = None
        self.datahub_timeout_timer = QTimer()
        self.datahub_timeout_timer.timeout.connect(self.check_datahub_timeout)
        self.datahub_timeout_timer.start(10000)  # Check every 10 seconds
        
    def setup_ui(self):
        """Setup the UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Chart
        self.chart = BrtiChart()
        layout.addWidget(self.chart)
        
        # Status bar
        self.status_label = QLabel("Connecting to DataHub...")
        self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        layout.addWidget(self.status_label)
        
    def setup_data_thread(self):
        """Setup data collection thread"""
        self.data_thread = BrtiDataThread(self.datahub)
        self.data_thread.data_updated.connect(self.on_data_updated)
        self.data_thread.error.connect(self.on_error)
        self.data_thread.start()
        
        # Setup timer for historical data requests
        self.history_timer = QTimer()
        self.history_timer.timeout.connect(self.request_history)
        self.history_timer.start(1000)  # Request history every second
        
        # Connect DataHub response signals
        self.datahub.data_received.connect(self.on_datahub_response)
        
        # Store current data for real-time updates
        self.current_data = None
        self.history_data = []
        
        # Request history after a short delay to allow DataHub to initialize
        QTimer.singleShot(2000, self.request_history)
        
    def request_history(self):
        """Request historical data from DataHub"""
        try:
            self.datahub.request('get_history', {'feed_name': 'brti'})
        except Exception as e:
            print(f"Error requesting history: {e}")
            self.status_label.setText(f"History request error: {e}")
            self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        
    def on_datahub_response(self, response):
        """Handle DataHub response"""
        # Update last response time
        self.last_datahub_response = time.time()
        
        print(f"DataHub response received: {type(response)}")
        if isinstance(response, dict):
            print(f"Response keys: {list(response.keys())}")
            
        if 'result' in response:
            history = response['result']
            print(f"History data type: {type(history)}")
            if isinstance(history, list):
                print(f"History list length: {len(history)}")
                if history:
                    print(f"First history item type: {type(history[0])}")
                    if isinstance(history[0], dict):
                        print(f"First history item keys: {list(history[0].keys())}")
                self.history_data = history
                self.on_history_updated(history)
            else:
                print(f"Warning: Expected list for history, got {type(history)}")
                self.history_data = []
        elif 'error' in response:
            print(f"DataHub error: {response['error']}")
            self.status_label.setText(f"DataHub error: {response['error']}")
            self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        else:
            print(f"Unexpected response format: {response}")
        
    def on_history_updated(self, history):
        """Handle historical data updates"""
        try:
            # Ensure history is a list before updating chart
            if isinstance(history, list):
                if history:
                    self.chart.update_chart(history)
                    self.status_label.setText("Connected - Historical data loaded")
                    self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
                else:
                    print("Warning: Empty history list received")
                    self.status_label.setText("Connected - No historical data available")
                    self.status_label.setStyleSheet("color: #f39c12; font-weight: bold;")
            else:
                print(f"Warning: Cannot update chart with non-list data: {type(history)}")
                self.status_label.setText("Error: Invalid history data format")
                self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        except Exception as e:
            print(f"Chart update error: {e}")
            self.status_label.setText(f"Chart error: {e}")
            self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        
    def on_data_updated(self, data):
        """Handle real-time data updates"""
        try:
            # Store current data
            self.current_data = data
            
            # Update timestamp in window title
            timestamp = data.get('timestamp', 0)
            if timestamp:
                dt = datetime.fromtimestamp(timestamp)
                time_str = dt.strftime("%H:%M:%S")
                self.setWindowTitle(f"BRTI Price Chart - Last Update: {time_str}")
            
            # Ensure history_data is a list
            if not isinstance(self.history_data, list):
                print(f"Warning: history_data is not a list, resetting to empty list. Was: {type(self.history_data)}")
                self.history_data = []
            
            # Add to history if it's valid price data
            if data.get('price') and data.get('price') > 0:
                self.history_data.append(data)
                # Keep only last 60 points
                if len(self.history_data) > 60:
                    self.history_data = self.history_data[-60:]
                
                # Update chart in real-time
                self.chart.update_chart(self.history_data)
            
            # Update status
            self.status_label.setText("Connected - Real-time data")
            self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
            
        except Exception as e:
            print(f"Data update error: {e}")
            self.status_label.setText(f"Data error: {e}")
            self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
            
    def on_error(self, error_msg):
        """Handle errors"""
        print(f"BRTI window error: {error_msg}")
        self.status_label.setText(f"Error: {error_msg}")
        self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        
    def closeEvent(self, event):
        """Handle window close"""
        # Stop the history timer
        if hasattr(self, 'history_timer'):
            self.history_timer.stop()
        
        # Disconnect from DataHub signals
        if hasattr(self, 'datahub'):
            self.datahub.data_received.disconnect(self.on_datahub_response)
        
        # Stop the data thread
        self.data_thread.stop()
        self.data_thread.wait()
        event.accept()

    def check_datahub_timeout(self):
        """Check if DataHub has timed out"""
        if self.last_datahub_response is None:
            # No response yet, still initializing
            return
            
        time_since_response = time.time() - self.last_datahub_response
        if time_since_response > 30:  # 30 second timeout
            self.status_label.setText("Warning: DataHub not responding")
            self.status_label.setStyleSheet("color: #f39c12; font-weight: bold;")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BrtiWindow()
    window.show()
    sys.exit(app.exec()) 