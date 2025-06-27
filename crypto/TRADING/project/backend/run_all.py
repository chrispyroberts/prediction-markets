import subprocess
import sys
import platform
import asyncio
import os

FEEDS = [
    "backend.feeds.brti_feed",
    "backend.feeds.binance_vol_smile_feed",
    "backend.feeds.kalshi_feed",
    # Add more feeds here as you create them
]

def start_feed(feed_module, feed_name=None):
    if platform.system() == "Windows":
        # Use cmd.exe to set the window title
        title = feed_name or feed_module
        return subprocess.Popen(
            ['cmd.exe', '/c', f'title {title} && {sys.executable} -m {feed_module}'],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    else:
        return subprocess.Popen([sys.executable, "-m", feed_module])

def start_datahub_service():
    """Start the DataHub service"""
    if platform.system() == "Windows":
        return subprocess.Popen(
            ['cmd.exe', '/c', f'title DataHub Service && {sys.executable} -m backend.datahub_service'],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    else:
        return subprocess.Popen([sys.executable, "-m", "backend.datahub_service"])

def start_all_feeds():
    processes = []
    
    # Start DataHub service first
    datahub_proc = start_datahub_service()
    processes.append(datahub_proc)
    print("DataHub service started")
    
    # Start all feeds
    for feed in FEEDS:
        feed_name = feed.split('.')[-1]  # e.g., 'brti_feed'
        proc = start_feed(feed, feed_name)
        processes.append(proc)
        print(f"{feed_name} started")
    
    return processes

def main():
    print("Starting all feeds and DataHub service...")
    feed_processes = start_all_feeds()
    
    try:
        print(f"All {len(feed_processes)} processes started successfully!")
        print("Press Ctrl+C to stop all processes.")
        
        # Keep the main process alive
        while True:
            # Check if any process has died
            for i, proc in enumerate(feed_processes):
                if proc.poll() is not None:
                    print(f"Process {i} has stopped unexpectedly")
            
            import time
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("\nShutting down... Terminating all processes.")
        for proc in feed_processes:
            if proc.poll() is None:  # Process is still running
                proc.terminate()
        
        # Wait for processes to terminate
        for proc in feed_processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        
        print("All processes terminated. Exiting.")

if __name__ == "__main__":
    main() 