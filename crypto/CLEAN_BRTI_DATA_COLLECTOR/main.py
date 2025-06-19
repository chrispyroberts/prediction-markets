from brti_data_collecting.collector import BRTIDataCollector

def main():
    collector = BRTIDataCollector()
    try:
        collector.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        collector.flush_remaining_batches()

if __name__ == "__main__":
    main() 