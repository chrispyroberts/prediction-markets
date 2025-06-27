import asyncio
from .run_all import start_all_feeds
from .datahub_service import DataHubService
import os
import platform
import subprocess
import sys

def start_frontend():
    """Start the PyQt6 frontend"""
    frontend_script = os.path.join(os.path.dirname(__file__), "..", "frontend", "main.py")
    
    if platform.system() == "Windows":
        return subprocess.Popen(
            [sys.executable, frontend_script],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    else:
        return subprocess.Popen([sys.executable, frontend_script])

def main():
    print("Starting complete trading system...")
    
    # Start all data feeds and DataHub service in separate processes/terminals
    feed_processes = start_all_feeds()
    
    # Start the PyQt6 frontend
    frontend_process = start_frontend()
    print("Frontend started")
    
    try:
        print("All components started successfully!")
        print("Press Ctrl+C to stop all processes.")
        
        # Keep the main process alive
        while True:
            # Check if any process has died
            for i, proc in enumerate(feed_processes):
                if proc.poll() is not None:
                    print(f"Process {i} has stopped unexpectedly")
            
            if frontend_process.poll() is not None:
                print("Frontend has stopped unexpectedly")
            
            import time
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("\nShutting down... Terminating all processes.")
        
        # Kill frontend
        if platform.system() == "Windows":
            try:
                os.system(f"taskkill /PID {frontend_process.pid} /T /F")
            except Exception as e:
                print(f"Failed to kill frontend: {e}")
        else:
            frontend_process.terminate()
        
        # Kill feed processes
        for proc in feed_processes:
            if proc.poll() is None:  # Process is still running
                if platform.system() == "Windows":
                    try:
                        os.system(f"taskkill /PID {proc.pid} /T /F")
                    except Exception as e:
                        print(f"Failed to kill feed: {e}")
                else:
                    proc.terminate()
        
        # Wait for processes to exit
        for proc in feed_processes:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
                
        try:
            frontend_process.wait(timeout=5)
        except Exception:
            pass
            
        print("All processes terminated. Exiting.")

if __name__ == "__main__":
    main() 