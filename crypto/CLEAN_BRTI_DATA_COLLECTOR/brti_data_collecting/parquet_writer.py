import pandas as pd
import numpy as np
import threading
import os

class ParquetWriter:
    def __init__(self, parquet_path, batch_size=30, logger=None):
        self.parquet_path = parquet_path
        self.batch_size = batch_size
        self.logger = logger
        self.price_batch = []
        self.price_batch_lock = threading.Lock()

    def add_price(self, price, receipt_timestamp_ms, timestamp_est, simple_avg):
        row = [timestamp_est, int(receipt_timestamp_ms), price, simple_avg]
        with self.price_batch_lock:
            self.price_batch.append(row)
            if len(self.price_batch) >= self.batch_size:
                batch_to_write = self.price_batch.copy()
                self.price_batch.clear()
                threading.Thread(
                    target=self.write_batch,
                    args=(batch_to_write,),
                    daemon=True
                ).start()

    def write_batch(self, batch_data):
        if not batch_data:
            return
        df = pd.DataFrame(batch_data, columns=[
            'timestamp_est', 'timestamp_ms', 'brti_price', 'simple_average'
        ])
        df['timestamp_est'] = pd.to_datetime(df['timestamp_est'])
        df['timestamp_ms'] = df['timestamp_ms'].astype('int64')
        if os.path.exists(self.parquet_path):
            existing_df = pd.read_parquet(self.parquet_path)
            combined_df = pd.concat([existing_df, df], ignore_index=True)
            combined_df.to_parquet(self.parquet_path, compression='snappy', index=False)
        else:
            df.to_parquet(self.parquet_path, compression='snappy', index=False)
        if self.logger:
            self.logger.info(f"BRTI BATCH: Wrote {len(batch_data)} records to Parquet")

    def flush(self):
        with self.price_batch_lock:
            if self.price_batch:
                self.write_batch(self.price_batch)
                self.price_batch.clear()
        if self.logger:
            self.logger.info("All batches flushed") 