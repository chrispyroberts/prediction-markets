#!/usr/bin/env python3
"""
Test script to check if BrtiWindow can be opened
"""

import sys
import os

# Add the frontend directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'frontend'))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal
from frontend.components.brti_window import BrtiWindow

def test_brti_window():
    """Test if BrtiWindow can be opened"""
    app = QApplication(sys.argv)
    
    try:
        # Create a mock DataHub connection with proper signals
        class MockDataHub(QObject):
            data_received = pyqtSignal(dict)
            
            def __init__(self):
                super().__init__()
                
            def request(self, method, params=None):
                # Mock response for get_history
                if method == 'get_history':
                    mock_history = [
                        {'timestamp': 1700000000 + i, 'price': 45000.0 + i * 10} 
                        for i in range(10)
                    ]
                    response = {'result': mock_history}
                    self.data_received.emit(response)
        
        # Create the window
        window = BrtiWindow(MockDataHub())
        window.show()
        
        print("✓ BrtiWindow opened successfully!")
        print("Window should be visible now.")
        
        # Keep the window open for a few seconds
        import time
        time.sleep(3)
        
        return True
        
    except Exception as e:
        print(f"✗ Error opening BrtiWindow: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_brti_window() 