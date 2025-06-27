#!/usr/bin/env python3
"""
Volatility Smile Window
Real-time Binance volatility smile analysis
"""

import sys
import json
import asyncio
import uuid
import redis.asyncio as aioredis
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QFrame, QGridLayout, QRadioButton, QButtonGroup)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont

# Enable interactive mode
plt.ion()

class VolSmileChart(FigureCanvas):
    """Matplotlib chart widget for volatility smile data"""
    
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(18, 8), dpi=100)
        # Create two subplots side by side
        self.ax1 = self.fig.add_subplot(121)  # Left subplot for vol smile
        self.ax2 = self.fig.add_subplot(122)  # Right subplot for binary prices vs d2
        super().__init__(self.fig)
        
        # Setup charts
        self.setup_charts()
        self.current_data = None
        self.fit_type = "polynomial"
        
    def setup_charts(self):
        """Setup chart appearance"""
        # Left subplot - Volatility Smile
        self.ax1.set_title('Volatility Smile', fontsize=16, fontweight='bold')
        self.ax1.set_xlabel('Scaled Moneyness (k/√T)', fontsize=12)
        self.ax1.set_ylabel('Implied Volatility', fontsize=12)
        self.ax1.grid(True, alpha=0.3)
        
        # Right subplot - Binary Prices vs d2
        self.ax2.set_title('Binary Prices vs d2', fontsize=16, fontweight='bold')
        self.ax2.set_xlabel('d2', fontsize=12)
        self.ax2.set_ylabel('Binary Price', fontsize=12)
        self.ax2.grid(True, alpha=0.3)
        
        # Add tighter margins
        self.fig.subplots_adjust(left=0.06, right=0.95, top=0.85, bottom=0.12, wspace=0.3)
    
    def set_fit_type(self, fit_type):
        """Set the fit type and redraw if data is available"""
        self.fit_type = fit_type
        if self.current_data is not None:
            self.update_chart(self.current_data)
        
    def update_chart(self, data):
        """Update chart with new volatility smile data"""
        if not data or 'moneyness' not in data or 'ivs' not in data:
            return
            
        self.current_data = data
        self.ax1.clear()
        self.ax2.clear()
        self.setup_charts()
        
        # Extract data
        moneyness = np.array(data['moneyness'])
        ivs = np.array(data['ivs'])
        tte = data.get('tte', 1.0)
        rev_moneyness = np.array(data.get('rev_moneyness', []))
        d2_data = np.array(data.get('d2_data', []))
        binary_price_data = np.array(data.get('binary_price_data', []))
        fitting_params = data.get('fitting_params', {})
        
        # Get fitted function parameters
        atm_vol = data.get('atm_vol', 0.0)
        vol_smile_b = data.get('vol_smile_b', 0.0)
        vol_smile_c = data.get('vol_smile_c', 0.0)
        sigmoid_x0 = data.get('sigmoid_x0', 0.0)
        sigmoid_d = data.get('sigmoid_d', 0.0)
        
        # LEFT SUBPLOT - Volatility Smile
        # Calculate scaled moneyness
        scaled_moneyness = moneyness / np.sqrt(tte)
        
        # Plot scatter of actual IVs vs scaled moneyness
        self.ax1.scatter(scaled_moneyness, ivs, alpha=0.6, s=30, label='Binance Option IVs', color='blue')
        
        # Create fitted function based on selected fit type
        def fitted_vol_smile(k):
            if self.fit_type == "polynomial":
                params = fitting_params.get('polynomial', {})
                atm_vol_fit = params.get('atm_vol', atm_vol)
                b = params.get('b', vol_smile_b)
                c = params.get('c', vol_smile_c)
                return atm_vol_fit + b * k + c * k**2
            elif self.fit_type == "svi":
                params = fitting_params.get('svi', {})
                a = params.get('a', atm_vol)
                b = params.get('b', 0.1)
                rho = params.get('rho', 0.0)
                m = params.get('m', 0.0)
                sigma = params.get('sigma', 0.1)
                return a + b * (rho * (k - m) + np.sqrt((k - m)**2 + sigma**2))
            elif self.fit_type == "spline":
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
        
        # Create linspace for fitted curve
        k_min, k_max = scaled_moneyness.min(), scaled_moneyness.max()
        k_range = np.linspace(k_min, k_max, 100)
        fitted_ivs = fitted_vol_smile(k_range)
        
        # Plot fitted curve
        fit_colors = {"polynomial": "red", "svi": "orange", "spline": "purple"}
        fit_color = fit_colors.get(self.fit_type, "red")
        self.ax1.plot(k_range, fitted_ivs, color=fit_color, linewidth=2, 
                     label=f'{self.fit_type.upper()} Fit', alpha=0.8)
        
        # Add ATM line
        self.ax1.axhline(y=atm_vol, color='g', linestyle='--', alpha=0.7, label=f'ATM Vol: {atm_vol*100:.2f}%')
        
        # Add fitted equation with parameters to 3 sig figs
        if self.fit_type == "polynomial":
            params = fitting_params.get('polynomial', {})
            atm_vol_sig = f"{params.get('atm_vol', atm_vol):.3g}"
            b_sig = f"{params.get('b', vol_smile_b):.3g}"
            c_sig = f"{params.get('c', vol_smile_c):.3g}"
            equation_text = f"σ(k) = {atm_vol_sig} + {b_sig}·k + {c_sig}·k²"
        elif self.fit_type == "svi":
            params = fitting_params.get('svi', {})
            a_sig = f"{params.get('a', atm_vol):.3g}"
            b_sig = f"{params.get('b', 0.1):.3g}"
            rho_sig = f"{params.get('rho', 0.0):.3g}"
            m_sig = f"{params.get('m', 0.0):.3g}"
            sigma_sig = f"{params.get('sigma', 0.1):.3g}"
            equation_text = f"SVI: a={a_sig}, b={b_sig}, ρ={rho_sig}, m={m_sig}, σ={sigma_sig}"
        elif self.fit_type == "spline":
            params = fitting_params.get('spline', {})
            n_points = len(params.get('k_points', []))
            equation_text = f"Cubic Spline ({n_points} points)"
        else:
            equation_text = f"{self.fit_type.upper()} Fit"
        
        # Add equation as text annotation
        self.ax1.text(0.02, 0.98, equation_text, 
                    transform=self.ax1.transAxes, fontsize=8, 
                    verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))
        
        # RIGHT SUBPLOT - Binary Prices vs d2
        # Plot actual d2 and binary prices from 0dte fit
        self.ax2.scatter(d2_data, binary_price_data, alpha=0.6, s=30, 
                       label='Actual 0DTE Data', color='blue')
        
        # Calculate d2 using fitted vol smile
        # For each rev_moneyness, convert to moneyness/sqrt(tte), apply vol smile fit, then calculate d2
        
        fitted_ivs_for_d2 = fitted_vol_smile(scaled_moneyness)
        
        # Calculate d2 using fitted IV: d2 = (log(K/S) - 0.5 * iv^2 * tte) / (iv * sqrt(tte))
        d2_fitted = (rev_moneyness - 0.5 * fitted_ivs_for_d2**2 * tte) / (fitted_ivs_for_d2 * np.sqrt(tte))
        
        # Calculate binary prices using sigmoid fit
        def sigmoid_fit(d2):
            return 1 / (1 + np.exp(-d2 * (sigmoid_x0 - sigmoid_d)))
        
        binary_prices_fitted = sigmoid_fit(d2_fitted)
        
        # Plot the new binary prices vs d2
        self.ax2.scatter(d2_fitted, binary_prices_fitted, alpha=0.6, s=30, 
                       label='Fitted Binary Prices', color='red')
        
        # Create linspace for sigmoid fit curve
        d2_min, d2_max = min(d2_fitted.min(), d2_data.min() if len(d2_data) > 0 else d2_fitted.min()), max(d2_fitted.max(), d2_data.max() if len(d2_data) > 0 else d2_fitted.max())
        d2_range = np.linspace(d2_min, d2_max, 100)
        sigmoid_curve = sigmoid_fit(d2_range)

        equation_text = f"x0={sigmoid_x0:.3g}, d={sigmoid_d:.3g}"


        # Plot sigmoid fit curve
        self.ax2.plot(d2_range, sigmoid_curve, 'g-', linewidth=2, 
                     label='Sigmoid Fit', alpha=0.8)
        
        # fix x axis
        self.ax2.set_xlim(min(d2_fitted)-0.5, max(d2_fitted)+0.5)
        
        # Ensure proper layout
        self.fig.tight_layout()
        self.draw()

class VolSmileDataThread(QThread):
    """Background thread for volatility smile data collection using Redis"""
    data_updated = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, datahub_connection):
        super().__init__()
        self.datahub = datahub_connection
        self.running = True
        self.redis = None
        
    def run(self):
        asyncio.run(self._stream_subscription())
        
    async def _stream_subscription(self):
        """Subscribe to volatility smile data stream"""
        try:
            # Connect to Redis
            self.redis = aioredis.from_url("redis://localhost")
            
            pubsub = self.redis.pubsub()
            await pubsub.subscribe("binance_vol_smile")
            
            async for message in pubsub.listen():
                if not self.running:
                    break
                if message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        # Ignore heartbeats
                        if data.get("type") == "heartbeat":
                            continue
                        self.data_updated.emit(data)
                    except Exception as e:
                        self.error.emit(f"Stream data error: {e}")
        except Exception as e:
            self.error.emit(f"Stream subscription error: {e}")
            
    def stop(self):
        self.running = False

class MetricCard(QFrame):
    """Individual metric display card"""
    
    def __init__(self, title, value="--", unit="", color="#3498db"):
        super().__init__()
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {color};
                border-radius: 4px;
                padding: 4px 8px;
                margin: 1px;
                min-width: 200px;
                max-height: 30px;
            }}
        """)
        
        layout = QHBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 2, 4, 2)
        
        # Title and value in horizontal layout
        title_label = QLabel(f"{title}:")
        title_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        title_label.setStyleSheet("color: white;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(title_label)
        
        # Value
        self.value_label = QLabel(value)
        self.value_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.value_label.setStyleSheet("color: white;")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.value_label)
        
        # Unit (if provided)
        if unit:
            unit_label = QLabel(unit)
            unit_label.setFont(QFont("Arial", 8))
            unit_label.setStyleSheet("color: rgba(255,255,255,0.8);")
            unit_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(unit_label)
            
    def update_value(self, value):
        """Update the displayed value"""
        self.value_label.setText(str(value))

class FitSelector(QFrame):
    """Fit selection widget with radio buttons"""
    
    def __init__(self):
        super().__init__()
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: #ecf0f1;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 200px;
                max-height: 30px;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(4, 2, 4, 2)
        
        # Title
        title = QLabel("Fit:")
        title.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(title)
        
        # Radio buttons
        self.button_group = QButtonGroup()
        self.polynomial_btn = QRadioButton("Polynomial")
        self.svi_btn = QRadioButton("SVI")
        self.spline_btn = QRadioButton("Spline")
        
        # Style radio buttons
        radio_style = """
            QRadioButton {
                font-size: 9px;
                font-weight: bold;
                padding: 1px;
            }
            QRadioButton::indicator {
                width: 12px;
                height: 12px;
            }
        """
        self.polynomial_btn.setStyleSheet(radio_style)
        self.svi_btn.setStyleSheet(radio_style)
        self.spline_btn.setStyleSheet(radio_style)
        
        # Add to button group
        self.button_group.addButton(self.polynomial_btn, 0)
        self.button_group.addButton(self.svi_btn, 1)
        self.button_group.addButton(self.spline_btn, 2)
        
        # Set polynomial as default
        self.polynomial_btn.setChecked(True)
        
        # Add to layout
        layout.addWidget(self.polynomial_btn)
        layout.addWidget(self.svi_btn)
        layout.addWidget(self.spline_btn)
        
    def get_selected_fit(self):
        """Get the currently selected fit type"""
        if self.polynomial_btn.isChecked():
            return "polynomial"
        elif self.svi_btn.isChecked():
            return "svi"
        elif self.spline_btn.isChecked():
            return "spline"
        return "polynomial"

class VolSmileWindow(QMainWindow):
    """Main volatility smile window"""
    
    def __init__(self, datahub_connection, shared_data_manager=None):
        super().__init__()
        self.setWindowTitle("Volatility Smile Analysis")
        self.setGeometry(100, 100, 1400, 900)
        self.datahub = datahub_connection
        self.shared_data_manager = shared_data_manager
        self.setup_ui()
        self.setup_data_thread()
        
    def setup_ui(self):
        """Setup the UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Metrics grid
        metrics_frame = QFrame()
        metrics_frame.setStyleSheet("""
            QFrame {
                background-color: #ecf0f1;
                border-radius: 5px;
                padding: 4px;
            }
        """)
        metrics_layout = QHBoxLayout(metrics_frame)
        metrics_layout.setSpacing(6)
        
        # Create metric cards (smaller)
        self.atm_vol_card = MetricCard("ATM Vol", "--", "%", "#e74c3c")
        self.atm_vol_1hr_card = MetricCard("1hr Vol", "--", "%", "#f39c12")
        self.tte_card = MetricCard("TTE", "--", "hrs", "#9b59b6")
        
        # Create fit selector
        self.fit_selector = FitSelector()
        
        # Add cards and fit selector to layout
        metrics_layout.addWidget(self.atm_vol_card)
        metrics_layout.addWidget(self.atm_vol_1hr_card)
        metrics_layout.addWidget(self.tte_card)
        metrics_layout.addStretch(2)  # Add more space
        metrics_layout.addWidget(self.fit_selector)
        
        layout.addWidget(metrics_frame)
        
        # Chart container with navigation toolbar
        chart_container = QWidget()
        chart_layout = QVBoxLayout(chart_container)
        chart_layout.setSpacing(2)  # Reduce spacing between toolbar and chart
        
        # Add navigation toolbar for interactive features
        self.chart = VolSmileChart()
        self.toolbar = NavigationToolbar(self.chart, chart_container)
        chart_layout.addWidget(self.toolbar)
        chart_layout.addWidget(self.chart, 1)  # Give it more space
        
        layout.addWidget(chart_container, 1)  # Give it more space
        
        # Status bar
        self.status_label = QLabel("Connecting to DataHub...")
        self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        layout.addWidget(self.status_label)
        
    def setup_data_thread(self):
        """Setup data collection thread"""
        self.data_thread = VolSmileDataThread(self.datahub)
        self.data_thread.data_updated.connect(self.on_data_updated)
        self.data_thread.error.connect(self.on_error)
        self.data_thread.start()
        
        # Connect fit selector to chart updates
        self.fit_selector.button_group.buttonClicked.connect(self.on_fit_changed)
        
    def on_data_updated(self, data):
        """Handle updated volatility smile data"""
        if not data:
            return
            
        # Update the chart
        self.chart.update_chart(data)
        
        # Update metrics
        atm_vol = data.get('atm_vol', 0.0)
        atm_vol_1hr = data.get('atm_vol_1hr', 0.0)
        tte = data.get('tte', 1.0)
        
        self.atm_vol_card.update_value(f"{atm_vol*100:.2f}%")
        self.atm_vol_1hr_card.update_value(f"{atm_vol_1hr*100:.2f}%")
        self.tte_card.update_value(f"{tte*365*24:.1f}h")
        
        # Update shared data manager with vol smile parameters
        if self.shared_data_manager:
            vol_smile_params = {
                'atm_vol': atm_vol,
                'vol_smile_b': data.get('vol_smile_b', 0.0),
                'vol_smile_c': data.get('vol_smile_c', 0.0),
                'sigmoid_x0': data.get('sigmoid_x0', 0.0),
                'sigmoid_d': data.get('sigmoid_d', 0.0),
                'fitting_params': data.get('fitting_params', {}),
                'tte': tte,
                'fit_type': self.fit_selector.get_selected_fit()  # Include current fit type
            }
            self.shared_data_manager.update_vol_smile_params(vol_smile_params)
        
        # Update timestamp
        timestamp = data.get('timestamp', 0)
        if timestamp:
            dt = datetime.fromtimestamp(timestamp)
            time_str = dt.strftime("%H:%M:%S")
            self.setWindowTitle(f"Volatility Smile Analysis - Last Update: {time_str}")
        
        # Update status
        self.status_label.setText("Connected - Real-time data")
        self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        
    def on_error(self, error_msg):
        """Handle errors"""
        self.status_label.setText(f"Error: {error_msg}")
        self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        
    def on_fit_changed(self):
        """Handle fit type change"""
        fit_type = self.fit_selector.get_selected_fit()
        self.chart.set_fit_type(fit_type)
        
        # Update shared data manager with new fit type
        if self.shared_data_manager:
            self.shared_data_manager.update_vol_smile_params({'fit_type': fit_type})
        
    def closeEvent(self, event):
        """Handle window close"""
        self.data_thread.stop()
        self.data_thread.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VolSmileWindow()
    window.show()
    sys.exit(app.exec()) 