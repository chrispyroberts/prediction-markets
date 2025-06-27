from PyQt6.QtCore import QObject, QThread, pyqtSignal
import asyncio
import redis.asyncio as aioredis
import uuid
import json
from components.brti_window import BrtiWindow
from components.vol_smile_window import VolSmileWindow
from components.kalshi_market_window import KalshiMarketWindow
from PyQt6.QtWidgets import QApplication, QMainWindow
import sys

class SharedDataManager(QObject):
    """Shared data manager for inter-window communication"""
    vol_smile_updated = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        self.vol_smile_params = {
            'atm_vol': 0.0,
            'vol_smile_b': 0.0,
            'vol_smile_c': 0.0,
            'sigmoid_x0': 0.0,
            'sigmoid_d': 0.0,
            'fitting_params': {},
            'tte': 1.0,
            'fit_type': 'polynomial'
        }
    
    def update_vol_smile_params(self, params):
        """Update vol smile parameters and emit signal"""
        self.vol_smile_params.update(params)
        self.vol_smile_updated.emit(self.vol_smile_params)
    
    def get_vol_smile_params(self):
        """Get current vol smile parameters"""
        return self.vol_smile_params.copy()

class DataHubWorker(QThread):
    data_received = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.redis = None
        self.loop = None

    async def _connect(self):
        self.redis = aioredis.from_url("redis://localhost")

    async def request(self, method, params=None, timeout=5):
        if not self.redis:
            await self._connect()
        req_id = str(uuid.uuid4())
        msg = {"method": method, "params": params or {}, "id": req_id}
        await self.redis.publish("datahub_methods", json.dumps(msg))
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(f"datahub_response_{req_id}")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    await pubsub.unsubscribe(f"datahub_response_{req_id}")
                    self.data_received.emit(data)
                    return
        except Exception as e:
            self.error.emit(f"Request error: {e}")

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop(self):
        self.running = False
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

class DataHubConnection(QObject):
    data_received = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.worker = DataHubWorker()
        self.worker.data_received.connect(self.data_received)
        self.worker.error.connect(self.error)
        self.worker.start()

    def request(self, method, params=None):
        if self.worker.loop and self.worker.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.worker.request(method, params), self.worker.loop
            )

    def stop(self):
        self.worker.stop()
        self.worker.quit()
        self.worker.wait()

class MainWindow(QMainWindow):
    """Main trading dashboard window with window selector"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trading Dashboard")
        self.setGeometry(100, 100, 800, 600)
        self.datahub = DataHubConnection()
        self.shared_data = SharedDataManager()
        self.setup_ui()
        self.setup_data_connection()

    def setup_ui(self):
        from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QPushButton, QHBoxLayout
        from PyQt6.QtGui import QFont
        from PyQt6.QtCore import Qt

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Title
        title = QLabel("Trading Dashboard")
        title.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #2c3e50; margin: 20px;")
        layout.addWidget(title)

        # Subtitle
        subtitle = QLabel("Select a window to open")
        subtitle.setFont(QFont("Arial", 12))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #7f8c8d; margin-bottom: 30px;")
        layout.addWidget(subtitle)

        # Window selector frame
        selector_frame = QFrame()
        selector_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        selector_frame.setStyleSheet("""
            QFrame {
                background-color: #ecf0f1;
                border-radius: 10px;
                border: 2px solid #bdc3c7;
            }
        """)
        selector_layout = QVBoxLayout(selector_frame)

        # Window buttons
        self.brti_btn = QPushButton("BRTI Price Chart")
        self.vol_smile_btn = QPushButton("Volatility Smile")
        self.kalshi_market_btn = QPushButton("Kalshi Market Orderbooks")
        selector_layout.addWidget(self.brti_btn)
        selector_layout.addWidget(self.vol_smile_btn)
        selector_layout.addWidget(self.kalshi_market_btn)

        layout.addWidget(selector_frame)
        layout.addStretch()

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        layout.addWidget(self.status_label)

        # Connect buttons
        self.brti_btn.clicked.connect(self.open_brti_window)
        self.vol_smile_btn.clicked.connect(self.open_vol_smile_window)
        self.kalshi_market_btn.clicked.connect(self.open_kalshi_market_window)

    def setup_data_connection(self):
        self.status_label.setText("Connected to DataHub (Redis)")

    def open_brti_window(self):
        self.brti_window = BrtiWindow(self.datahub)
        self.brti_window.show()

    def open_vol_smile_window(self):
        self.vol_smile_window = VolSmileWindow(self.datahub, self.shared_data)
        self.vol_smile_window.show()

    def open_kalshi_market_window(self):
        self.kalshi_market_window = KalshiMarketWindow(self.datahub, self.shared_data)
        self.kalshi_market_window.show()

    def closeEvent(self, event):
        self.datahub.stop()
        event.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 