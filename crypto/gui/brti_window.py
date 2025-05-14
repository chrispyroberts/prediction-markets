# brti_window.py
import tkinter as tk
import threading
import time
from datetime import datetime

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from utils import get_brti_price

class BRTIWindow(tk.Toplevel):
    def __init__(self, master=None, params=None):
        super().__init__(master)
        self.title("BRTI Price Viewer")

        # Graph
        self.fig, self.ax = plt.subplots(figsize=(5, 3))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack()

        # Boxes for live numbers
        self.price_frame = tk.Frame(self)
        self.price_frame.pack(pady=10)

        self.brti_label = tk.Label(self.price_frame, text="BRTI Price: Loading...", font=("Arial", 12))
        self.brti_label.pack()

        self.simple_avg_label = tk.Label(self.price_frame, text="Simple Average: Loading...", font=("Arial", 12))
        self.simple_avg_label.pack()

        self.timestamps = []
        self.brti_prices = []
        self.simple_averages = []

        if params:
            self.params = params
        else:
            self.params = {
                'window_length' : 60,
            }

        self.update_price_loop()

    def update_price_loop(self):
        threading.Thread(target=self.update_price_forever, daemon=True).start()

    def update_price_forever(self):
        while True:
            brti, simple_avg, timestamp = get_brti_price()
            if brti is not None:

                # update box values
                self.brti_label.config(text=f"BRTI Price: {brti:.2f}")
                self.simple_avg_label.config(text=f"Simple Average: {simple_avg:.2f}")

                # parse info
                dt_object = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                self.timestamps.append(dt_object)
                self.brti_prices.append(brti)
                self.simple_averages.append(simple_avg)

                if len(self.timestamps) > self.params['window_length']:
                    self.brti_prices.pop(0)
                    self.simple_averages.pop(0)
                    self.timestamps.pop(0)

                self.plot_price()
            time.sleep(1.0)

    def plot_price(self):
        self.ax.clear()
        
        self.ax.plot(self.timestamps, self.brti_prices, marker='o', label='BRTI Price')
        self.ax.plot(self.timestamps, self.simple_averages, marker='x', linestyle='--', label='Simple Average')

        self.ax.set_title("BRTI Price and Simple Average Over Time")
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Price")
        self.ax.legend()
        self.ax.grid(True)

        self.fig.autofmt_xdate()
        self.canvas.draw()
