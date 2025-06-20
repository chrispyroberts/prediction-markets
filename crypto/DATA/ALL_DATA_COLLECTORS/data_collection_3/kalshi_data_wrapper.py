#!/usr/bin/env python3
"""
Kalshi Data Collector Python Wrapper
This script handles graceful shutdown and automatic restarts
"""

import subprocess
import time
import signal
import sys
import os
from datetime import datetime

class KalshiCollector:
    def __init__(self, disable_terminal_output=False):
        self.running = True
        self.process = None
        self.disable_terminal_output = disable_terminal_output
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def print_if_enabled(self, *args, **kwargs):
        """Print only if terminal output is enabled"""
        if not self.disable_terminal_output:
            print(*args, **kwargs)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.print_if_enabled(f"\n[{self.get_timestamp()}] Received shutdown signal - cleaning up...")
        self.running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        sys.exit(0)
    
    def get_timestamp(self):
        """Get current timestamp string"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def run_collector(self):
        """Run the Kalshi data collector with automatic restarts"""
        loop_count = 0
        
        self.print_if_enabled("Kalshi Data Collector")
        self.print_if_enabled("Press Ctrl+C to stop gracefully")
        self.print_if_enabled()
        
        while self.running:
            loop_count += 1
            timestamp = self.get_timestamp()
            self.print_if_enabled(f"[{timestamp}] Starting Kalshi data collector (attempt {loop_count})...")
            
            try:
                # Run the Python script
                self.process = subprocess.Popen(
                    [sys.executable, "kalshi_data.py"],
                    cwd=os.path.dirname(os.path.abspath(__file__))
                )
                
                # Wait for the process to complete
                exit_code = self.process.wait()
                
                if not self.running:
                    break
                
                if exit_code == 0:
                    self.print_if_enabled(f"[{timestamp}] Collector exited normally")
                    break
                elif exit_code == 99:
                    self.print_if_enabled(f"[{timestamp}] Stale data detected - restarting in 15 seconds...")
                    self.print_if_enabled("Press Ctrl+C to stop the collector")
                    time.sleep(15)
                else:
                    self.print_if_enabled(f"[{timestamp}] Collector crashed with code {exit_code} - restarting in 15 seconds...")
                    self.print_if_enabled("Press Ctrl+C to stop the collector")
                    time.sleep(15)
                    
            except KeyboardInterrupt:
                self.print_if_enabled(f"\n[{timestamp}] Interrupted by user")
                break
            except Exception as e:
                self.print_if_enabled(f"[{timestamp}] Error running collector: {e}")
                self.print_if_enabled("Restarting in 15 seconds...")
                time.sleep(15)
        
        self.print_if_enabled("\nCollector stopped.")

if __name__ == "__main__":
    # Check if running in unified mode (disable terminal output)
    disable_terminal_output = os.environ.get('KALSHI_DISABLE_TERMINAL', 'false').lower() == 'true'
    
    collector = KalshiCollector(disable_terminal_output=disable_terminal_output)
    collector.run_collector() 