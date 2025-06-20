#!/usr/bin/env python3
"""
Unified Data Collector
Runs all three data collectors (BRTI, Kalshi, Binance) as subprocesses
with proper monitoring, graceful shutdown, and automatic restarts.
"""

import subprocess
import signal
import time
import os
import sys
import threading
import logging
from datetime import datetime
import shutil
from pathlib import Path
import pandas as pd

# Import Windows-specific signal constants
if os.name == 'nt':
    import win32api
    import win32con

class UnifiedDataCollector:
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.data_dir = self.base_dir / "data"
        self.logs_dir = self.base_dir / "logs"
        self.backups_dir = self.base_dir / "backups"
        
        # Ensure directories exist
        self.data_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        self.backups_dir.mkdir(exist_ok=True)
        
        # Setup logging
        self.setup_logging()
        
        # Collector processes
        self.processes = {}
        self.running = True
        
        # Backup settings
        self.backup_interval = 30 * 60  # 30 minutes
        self.last_backup = time.time()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        self.logger.info("=" * 80)
        self.logger.info("UNIFIED DATA COLLECTOR STARTED")
        self.logger.info("=" * 80)
        
    def setup_logging(self):
        """Setup logging for the unified collector"""
        log_file = self.logs_dir / "unified_collector.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s | %(levelname)s | %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
        self.stop_all_collectors()
        
    def start_collector(self, name, command, cwd=None):
        """Start a collector as a subprocess"""
        try:
            self.logger.info(f"Starting {name} collector...")
            
            # For BRTI collector, don't capture output to prevent hanging
            if name == "BRTI":
                # Set environment variable to disable terminal output
                env = os.environ.copy()
                env['BRTI_DISABLE_TERMINAL'] = 'true'
                
                process = subprocess.Popen(
                    command,
                    cwd=cwd or self.base_dir,
                    env=env,
                    # Don't capture output for BRTI to prevent hanging
                )
            elif name == "Kalshi":
                # Set environment variable to disable terminal output for Kalshi
                env = os.environ.copy()
                env['KALSHI_DISABLE_TERMINAL'] = 'true'
                
                # Start the process with output capture for Kalshi
                process = subprocess.Popen(
                    command,
                    cwd=cwd or self.base_dir,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                # Start background threads to read output and prevent hanging
                def read_output(stream, prefix):
                    try:
                        for line in iter(stream.readline, ''):
                            if line.strip():
                                self.logger.info(f"{name} {prefix}: {line.strip()}")
                    except Exception as e:
                        self.logger.error(f"Error reading {name} {prefix}: {e}")
                
                stdout_thread = threading.Thread(target=read_output, args=(process.stdout, "STDOUT"), daemon=True)
                stderr_thread = threading.Thread(target=read_output, args=(process.stderr, "STDERR"), daemon=True)
                stdout_thread.start()
                stderr_thread.start()
            elif name == "Binance":
                # Set environment variable to disable terminal output for Binance Rust collector
                env = os.environ.copy()
                env['BINANCE_DISABLE_TERMINAL'] = 'true'
                
                # Start the process with output capture for Binance
                process = subprocess.Popen(
                    command,
                    cwd=cwd or self.base_dir,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                # Start background threads to read output and prevent hanging
                def read_output(stream, prefix):
                    try:
                        for line in iter(stream.readline, ''):
                            if line.strip():
                                self.logger.info(f"{name} {prefix}: {line.strip()}")
                    except Exception as e:
                        self.logger.error(f"Error reading {name} {prefix}: {e}")
                
                stdout_thread = threading.Thread(target=read_output, args=(process.stdout, "STDOUT"), daemon=True)
                stderr_thread = threading.Thread(target=read_output, args=(process.stderr, "STDERR"), daemon=True)
                stdout_thread.start()
                stderr_thread.start()
            else:
                # Start the process with output capture for other collectors
                process = subprocess.Popen(
                    command,
                    cwd=cwd or self.base_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                # Start background threads to read output and prevent hanging
                def read_output(stream, prefix):
                    try:
                        for line in iter(stream.readline, ''):
                            if line.strip():
                                self.logger.info(f"{name} {prefix}: {line.strip()}")
                    except Exception as e:
                        self.logger.error(f"Error reading {name} {prefix}: {e}")
                
                stdout_thread = threading.Thread(target=read_output, args=(process.stdout, "STDOUT"), daemon=True)
                stderr_thread = threading.Thread(target=read_output, args=(process.stderr, "STDERR"), daemon=True)
                stdout_thread.start()
                stderr_thread.start()
            
            self.processes[name] = {
                'process': process,
                'command': command,
                'cwd': cwd or self.base_dir,
                'start_time': time.time(),
                'restart_count': 0
            }
            
            self.logger.info(f"{name} collector started with PID: {process.pid}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start {name} collector: {e}")
            return False
            
    def stop_collector(self, name):
        """Stop a collector gracefully"""
        if name not in self.processes:
            return
            
        process_info = self.processes[name]
        process = process_info['process']
        
        try:
            self.logger.info(f"Stopping {name} collector (PID: {process.pid})...")
            
            # For Binance collector on Windows, send Ctrl+C instead of SIGTERM
            if name == "Binance" and os.name == 'nt':  # Windows
                self.logger.info(f"Sending Ctrl+C to {name} collector...")
                try:
                    process.send_signal(signal.CTRL_C_EVENT)
                except AttributeError:
                    # Fallback to terminate if CTRL_C_EVENT not available
                    self.logger.info(f"CTRL_C_EVENT not available, using terminate for {name} collector...")
                    process.terminate()
            else:
                # Send SIGTERM for graceful shutdown
                process.terminate()
            
            # Wait for graceful shutdown - increased timeout for Rust collector
            timeout = 30 if name == "Binance" else 10  # Give Rust collector more time to flush
            try:
                process.wait(timeout=timeout)
                self.logger.info(f"{name} collector stopped gracefully")
            except subprocess.TimeoutExpired:
                self.logger.warning(f"{name} collector didn't stop gracefully after {timeout}s, force killing...")
                process.kill()
                process.wait()
                
        except Exception as e:
            self.logger.error(f"Error stopping {name} collector: {e}")
            
        finally:
            if name in self.processes:
                del self.processes[name]
                
    def stop_all_collectors(self):
        """Stop all collectors gracefully"""
        self.logger.info("Stopping all collectors...")
        
        # Stop all processes
        for name in list(self.processes.keys()):
            self.stop_collector(name)
            
        self.logger.info("All collectors stopped")
        
    def check_processes(self):
        """Check if any processes have died and restart them"""
        to_restart = []
        
        for name, info in self.processes.items():
            process = info['process']
            
            # Check if process is still running
            if process.poll() is not None:
                exit_code = process.returncode
                self.logger.warning(f"{name} collector exited with code {exit_code}")
                to_restart.append(name)
                
        # Restart dead processes
        for name in to_restart:
            info = self.processes[name]
            self.logger.info(f"Restarting {name} collector...")
            
            # Remove from processes dict
            del self.processes[name]
            
            # Restart
            self.start_collector(name, info['command'], info['cwd'])
            
    def create_backup(self):
        """Create backup of all parquet files"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_path = self.backups_dir / f"backup_{timestamp}"
            backup_path.mkdir(exist_ok=True)
            
            self.logger.info(f"Creating backup: {backup_path}")
            
            # Find all parquet files
            parquet_files = list(self.data_dir.glob("*.parquet"))
            
            if not parquet_files:
                self.logger.warning("No parquet files found to backup")
                return
            
            successful_backups = 0
            failed_backups = 0
            
            # Copy files with individual error handling
            for file_path in parquet_files:
                try:
                    # Verify file is not corrupted before backing up
                    if self.verify_parquet_file(file_path):
                        backup_file = backup_path / file_path.name
                        shutil.copy2(file_path, backup_file)
                        size_mb = file_path.stat().st_size / (1024 * 1024)
                        self.logger.info(f"Backed up: {file_path.name} ({size_mb:.2f} MB)")
                        successful_backups += 1
                    else:
                        self.logger.warning(f"Skipping corrupted file: {file_path.name}")
                        failed_backups += 1
                        
                except PermissionError as e:
                    self.logger.error(f"Permission error backing up {file_path.name}: {e}")
                    failed_backups += 1
                except Exception as e:
                    self.logger.error(f"Error backing up {file_path.name}: {e}")
                    failed_backups += 1
                
            self.last_backup = time.time()
            self.logger.info(f"Backup completed: {successful_backups} successful, {failed_backups} failed")
            
            # Clean up old backups (keep last 10)
            self.cleanup_old_backups()
            
        except Exception as e:
            self.logger.error(f"Error creating backup: {e}")
            
    def verify_parquet_file(self, file_path):
        """Verify that a parquet file is not corrupted"""
        try:
            # Try to read the parquet file to check for corruption
            df = pd.read_parquet(file_path)
            # If we can read it, it's probably not corrupted
            return True
        except Exception as e:
            self.logger.warning(f"Parquet file {file_path.name} appears corrupted: {e}")
            return False
            
    def cleanup_old_backups(self):
        """Keep only the last 10 backups"""
        try:
            backup_dirs = sorted(
                [d for d in self.backups_dir.iterdir() if d.is_dir() and d.name.startswith("backup_")],
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            
            if len(backup_dirs) > 10:
                for old_backup in backup_dirs[10:]:
                    shutil.rmtree(old_backup)
                    self.logger.info(f"Removed old backup: {old_backup.name}")
                    
        except Exception as e:
            self.logger.error(f"Error cleaning up old backups: {e}")
            
    def should_create_backup(self):
        """Check if it's time for a backup"""
        return time.time() - self.last_backup >= self.backup_interval
        
    def verify_files_unlocked(self):
        """Verify that parquet files are not locked and can be accessed"""
        try:
            parquet_files = list(self.data_dir.glob("*.parquet"))
            if not parquet_files:
                self.logger.info("No parquet files found to verify")
                return True
                
            self.logger.info(f"Verifying {len(parquet_files)} parquet files are unlocked...")
            
            for file_path in parquet_files:
                try:
                    # Try to open the file for reading to check if it's locked
                    with open(file_path, 'rb') as f:
                        # Read first few bytes to ensure file is accessible
                        f.read(1024)
                    self.logger.info(f"File {file_path.name} is unlocked")
                except PermissionError:
                    self.logger.warning(f"File {file_path.name} is still locked")
                    return False
                except Exception as e:
                    self.logger.warning(f"Error checking file {file_path.name}: {e}")
                    return False
            
            self.logger.info("All parquet files are unlocked and ready for backup")
            return True
            
        except Exception as e:
            self.logger.error(f"Error in file verification: {e}")
            return False
        
    def run(self):
        """Main run loop"""
        try:
            # Start all collectors
            self.logger.info("Starting all data collectors...")
            
            # Start BRTI collector
            brti_success = self.start_collector(
                "BRTI",
                [sys.executable, "brti_collector/brti_data_collecting.py"],
                cwd=self.base_dir
            )
            
            # Start Kalshi collector
            kalshi_success = self.start_collector(
                "Kalshi", 
                [sys.executable, "kalshi_collector/kalshi_data_wrapper.py"],
                cwd=self.base_dir
            )
            
            # Start Binance collector
            binance_success = self.start_collector(
                "Binance",
                ["./binance_collector/target/release/binance_rust.exe"],
                cwd=self.base_dir
            )
            
            if not all([brti_success, kalshi_success, binance_success]):
                self.logger.error("Failed to start some collectors")
                return
                
            self.logger.info("All collectors started successfully")
            self.logger.info("Entering monitoring loop...")
            
            # Main monitoring loop
            while self.running:
                try:
                    # Check if any processes have died
                    self.check_processes()
                    
                    # Check if it's time for backup
                    if self.should_create_backup():
                        self.logger.info("Scheduled backup time reached...")
                        
                        # Stop all collectors for backup
                        self.stop_all_collectors()
                        
                        # Wait longer for file handles to be released
                        self.logger.info("Waiting for file handles to be released...")
                        time.sleep(15)  # Increased from 5 to 15 seconds
                        
                        # Additional verification that files are not locked
                        if self.verify_files_unlocked():
                            # Create backup
                            self.create_backup()
                            
                            # Restart all collectors
                            self.logger.info("Restarting all collectors after backup...")
                            self.start_collector("BRTI", [sys.executable, "brti_collector/brti_data_collecting.py"], cwd=self.base_dir)
                            self.start_collector("Kalshi", [sys.executable, "kalshi_collector/kalshi_data_wrapper.py"], cwd=self.base_dir)
                            self.start_collector("Binance", ["./binance_collector/target/release/binance_rust.exe"], cwd=self.base_dir)
                            
                            self.logger.info("All collectors restarted after backup")
                        else:
                            self.logger.warning("Files still locked, skipping backup and restarting collectors...")
                            # Restart collectors even if backup failed
                            self.start_collector("BRTI", [sys.executable, "brti_collector/brti_data_collecting.py"], cwd=self.base_dir)
                            self.start_collector("Kalshi", [sys.executable, "kalshi_collector/kalshi_data_wrapper.py"], cwd=self.base_dir)
                            self.start_collector("Binance", ["./binance_collector/target/release/binance_rust.exe"], cwd=self.base_dir)
                    
                    # Sleep before next check
                    time.sleep(60)
                    
                except Exception as e:
                    self.logger.error(f"Error in monitoring loop: {e}")
                    time.sleep(30)
                    
        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt")
        finally:
            self.stop_all_collectors()
            self.logger.info("Unified data collector shutdown complete")

def main():
    collector = UnifiedDataCollector()
    collector.run()

if __name__ == "__main__":
    main() 