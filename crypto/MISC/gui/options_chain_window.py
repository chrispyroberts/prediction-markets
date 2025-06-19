from websockets.utils import get_brti_price, get_options_chain_for_event, get_market_data, implied_vol_binary_call, get_moneyness, get_top_orderbook, implied_vol_one_touch
from tkinter import ttk
import tkinter as tk
from datetime import datetime, timezone
from contract_window import ContractWindow
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

ONE_TOUCH = False  # Set to True if you want to use one-touch pricing instead of binary call pricing

class OptionsChainWindow(tk.Toplevel):
    def __init__(self, event, threshold=1000, master=None):
        super().__init__(master)
        self.title(f"{event} Options Chain")

        self.event = event
        self.chain_data = []
        self.one_touch_threshold = 100001
        self.threshold = 1000

        if ONE_TOUCH:
            self.iv_function = implied_vol_one_touch
        else:
            self.iv_function = implied_vol_binary_call


        self.main_frame = tk.Frame(self)
        self.main_frame.pack(padx=20, pady=20)

        self.tree = ttk.Treeview(self.main_frame, columns=(
            "Ticker", "Strike", "Time Left", "Moneyness", "Interest", "Bid IV", "Bid Value", "Best Bid", "Best Ask", "Ask Value", "Ask IV",
        ), show="headings", height=10)

        for col in ["Ticker", "Strike", "Time Left", "Moneyness", "Interest", "Bid IV", "Bid Value", "Best Bid", "Best Ask", "Ask Value", "Ask IV"]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=90, anchor="center")

        self.tree.bind("<Double-1>", self.on_double_click)

        self.tree.pack()

        # volatility smile
        self.plot_frame = tk.Frame(self)
        self.plot_frame.pack(side="bottom", padx=20, pady=20)

        self.fig, self.ax = plt.subplots(figsize=(6, 3))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)  # Put under your plot_frame (make plot_frame if needed)
        self.canvas.get_tk_widget().pack()


        # set values to 0
        self.brti_price = 0
        self.brti_average = 0

        # Load the options chain
        self.load_options_chain()

        self.bid_m_ts = []
        self.bid_ivs = []
        self.ask_m_ts = []
        self.ask_ivs = []

    def update_volatility_smile(self):
        # Clear the previous plot
        self.ax.clear()

        self.ax.plot(self.ask_m_ts, self.ask_ivs, marker='o', linestyle='-', color='red', label="Ask IVs")
        self.ax.plot(self.bid_m_ts, self.bid_ivs, marker='o', linestyle='-', color='green', label="Bid IVs")
        self.ax.set_xlabel("Moneyness")
        self.ax.set_ylabel("Implied Volatility (%)")
        self.ax.set_title("Volatility Smile")
        self.ax.grid(True)

        self.ax.relim()
        self.ax.autoscale_view()
        self.ax.margins(x=0.1, y=0.2) 
        self.fig.tight_layout()


        # Draw updated plot
        self.canvas.draw()

    def load_options_chain(self):

        for row in self.tree.get_children():
            self.tree.delete(row)

        brti_price, average, timestamp = get_brti_price()
        self.brti_price = brti_price
        self.brti_average = average
        self.chain_data = get_options_chain_for_event(self.event, average, threshold=self.threshold)

        self.bid_ivs = []
        self.ask_ivs = []
        self.bid_m_ts = []
        self.ask_m_ts = []

        print(len(self.chain_data), " contracts loaded")
        for contract in self.chain_data:
            ticker = contract['ticker']
            expiration_time_str = contract['expected_expiration_time']
            interest = contract['open_interest']

            strike = int(round(contract['floor_strike'], 0))

            if ONE_TOUCH:
                if strike < self.one_touch_threshold:
                    continue

            best_bid = contract['yes_bid']
            best_ask = 100-contract['no_bid']

            # Calculate time left
            expiration_time = datetime.fromisoformat(expiration_time_str.replace('Z', '+00:00'))
            now_local = datetime.now().astimezone()
            now_utc = now_local.astimezone(timezone.utc)
            time_left = expiration_time - now_utc
            total_seconds = int(time_left.total_seconds())
            
            hours_left = total_seconds / 3600

            if total_seconds <= 0:
                time_left_str = "Expired"
            else:
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                time_left_str = f"{hours}h {minutes}m"

            moneyness = get_moneyness(self.brti_price, strike, hours_left)
            bid_iv = self.iv_function(self.brti_price, strike, hours_left, best_bid/100)
            ask_iv = self.iv_function(self.brti_price, strike, hours_left, best_ask/100)

            if not(np.isnan(bid_iv) or np.isinf(bid_iv)):
                self.bid_m_ts.append(moneyness)
                self.bid_ivs.append(bid_iv)
            
            if not (np.isnan(ask_iv)):
                self.ask_m_ts.append(moneyness)
                self.ask_ivs.append(ask_iv)
         
            bid_value, ask_value = get_top_orderbook(ticker)

            # Things to put on the row:
            # Strike, Time Left, moneyness, interest, bid iv, best_bid, best_ask, ask_iv

            row = (
                contract['ticker'],
                strike,
                time_left_str,
                f"{moneyness:+.2f}",
                interest,
                f"{bid_iv:.2f}%",
                bid_value,
                f"{int(best_bid)}",
                f"{int(best_ask)}",
                ask_value,
                f"{ask_iv:.2f}%"
            )

            # Insert into treeview
            row_id = self.tree.insert("", "end", values=row)

            # Attach a button to the "Action" column
            self.tree.bind("<Double-1>", self.on_double_click)
        
        self.update_volatility_smile()
        self.after(1000, self.load_options_chain)


    def on_double_click(self, event):
        selected_item = self.tree.selection()
        if selected_item:
            item = self.tree.item(selected_item)
            values = item['values']
            ticker = values[0]  # Ticker is first column

            # Open Contract Viewer
            ContractWindow(ticker, master=self)