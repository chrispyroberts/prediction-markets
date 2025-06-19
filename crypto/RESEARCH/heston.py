import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import warnings
import time

warnings.filterwarnings('ignore')

# --- Load and segment your BRTI data ---
parquet_path = r"C:\Users\chris\OneDrive\Desktop\Programming\Trading\prediction markets\crypto\brti_data_collection\data\brti_price_data.parquet"
df = pd.read_parquet(parquet_path)

time_diff = df['timestamp_ms'].diff().fillna(0)
gap_indices = np.where(time_diff > 60000)[0]
start_indices = np.concatenate(([0], gap_indices))
end_indices = np.concatenate((gap_indices, [len(df)]))
split_dfs = [df.iloc[start:end].reset_index(drop=True) for start, end in zip(start_indices, end_indices)]
print(f"Number of segments: {len(split_dfs)}")

# --- Heston Model Classes and Functions (unchanged) ---
class HestonModel:
    def __init__(self, S0, v0, kappa, theta, xi, rho, r, T):
        self.S0 = S0
        self.v0 = v0
        self.kappa = kappa
        self.theta = theta
        self.xi = xi
        self.rho = rho
        self.r = r
        self.T = T
    def simulate_paths(self, n_paths=1000, n_steps=252):
        dt = self.T / n_steps
        S = np.zeros((n_paths, n_steps + 1))
        v = np.zeros((n_paths, n_steps + 1))
        S[:, 0] = self.S0
        v[:, 0] = self.v0
        for i in range(n_steps):
            Z1 = np.random.standard_normal(n_paths)
            Z2 = self.rho * Z1 + np.sqrt(1 - self.rho**2) * np.random.standard_normal(n_paths)
            v[:, i + 1] = np.maximum(
                v[:, i] + self.kappa * (self.theta - v[:, i]) * dt + 
                self.xi * np.sqrt(np.maximum(v[:, i], 0)) * np.sqrt(dt) * Z2,
                0
            )
            S[:, i + 1] = S[:, i] * np.exp(
                (self.r - 0.5 * v[:, i]) * dt + 
                np.sqrt(np.maximum(v[:, i], 0)) * np.sqrt(dt) * Z1
            )
        return S, v

def calibrate_heston_simple(stock_data, historical_vol):
    returns = stock_data['Returns'].dropna()
    v0 = historical_vol**2
    theta = historical_vol**2
    kappa = 2.0
    xi = 0.3
    rho = -0.7
    return v0, kappa, theta, xi, rho

def run_heston_on_segments(split_dfs, T=0.5, n_paths=1000):
    all_final_prices = []
    all_percentiles = []
    total_segments = len(split_dfs)
    print(f"\nStarting Heston analysis on {total_segments} segments...")
    for i, segment in enumerate(split_dfs):
        print(f"\n--- Segment {i+1}/{total_segments} ---")
        segment = segment.copy()
        segment['Close'] = segment['brti_price']
        segment['Returns'] = segment['Close'].pct_change()
        segment = segment.dropna(subset=['Returns'])
        print(f"Segment {i+1} size: {len(segment)} rows")
        if len(segment) < 10:
            print(f"Segment {i+1} skipped (too short)")
            continue
        historical_vol = segment['Returns'].std() * np.sqrt(252)
        current_price = segment['Close'].iloc[-1]
        risk_free_rate = 0.03
        v0, kappa, theta, xi, rho = calibrate_heston_simple(segment, historical_vol)
        print(f"Calibrated params: v0={v0:.4f}, kappa={kappa:.2f}, theta={theta:.4f}, xi={xi:.2f}, rho={rho:.2f}")
        heston = HestonModel(current_price, v0, kappa, theta, xi, rho, risk_free_rate, T)
        print(f"Simulating {n_paths} paths for {T} years...")
        t0 = time.time()
        S_paths, v_paths = heston.simulate_paths(n_paths=n_paths, n_steps=int(252 * T))
        t1 = time.time()
        print(f"Simulation done in {t1-t0:.2f} seconds.")
        final_prices = S_paths[:, -1]
        all_final_prices.append(final_prices)
        percentiles = np.percentile(final_prices, [5, 25, 50, 75, 95])
        all_percentiles.append(percentiles)
        print(f"Segment {i+1}: Percentiles (5,25,50,75,95): {percentiles}")
    print("\nAll segments processed. Aggregating results...")
    if all_final_prices:
        all_final_prices = np.concatenate(all_final_prices)
        aggregate_percentiles = np.percentile(all_final_prices, [5, 25, 50, 75, 95])
        print("\nAggregate percentiles across all segments:", aggregate_percentiles)
        plt.hist(all_final_prices, bins=50, alpha=0.7, color='skyblue', edgecolor='black')
        plt.title('Distribution of Simulated Final Prices (All Segments)')
        plt.xlabel('Final Price')
        plt.ylabel('Frequency')
        plt.grid(True, alpha=0.3)
        plt.show()
        print("Aggregation and plotting complete.")
    else:
        print("No valid segments for Heston analysis.")

if __name__ == "__main__":
    run_heston_on_segments(split_dfs, T=0.5, n_paths=1000)