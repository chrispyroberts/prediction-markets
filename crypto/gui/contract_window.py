import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import threading
import time
from utils import get_orderbook, get_market_data, get_brti_price, implied_vol_binary_call, get_moneyness
from datetime import datetime, timezone

class ContractWindow(tk.Toplevel):
    def __init__(self, ticker, master=None):
        super().__init__(master)

        self.bind_all(",", lambda event: self.destroy())

        self.ticker = ticker
        self.data = get_market_data(ticker)
        self.strike = self.data['strike']
        self.expiration_time = datetime.fromisoformat(self.data['expiration_time'].replace('Z', '+00:00'))
        self.title(f"{ticker}")
                
        # Configure the Treeview style
        # style = ttk.Style(self)
        # self.configure(bg="#ffffff")  # Background window
        # style.configure("Treeview",
        #                 background="#ffffff",
        #                 foreground="black",
        #                 fieldbackground="#ffffff",
        #                 rowheight=30,
        #                 font=('Arial', 14))
        # style.configure("Treeview.Heading",
        #                 background="#e0e0e0",
        #                 foreground="black",
        #                 font=('Arial', 16, 'bold'))
        # style.layout("Treeview", [('Treeview.treearea', {'sticky': 'nswe'})])

        self.main_frame = tk.Frame(self)
        self.main_frame.pack(padx=20, pady=20)

        # Unified orderbook
        self.orderbook_frame = tk.Frame(self.main_frame)
        self.orderbook_frame.pack()

        # 🔥 FIRST create self.tree
        self.tree = ttk.Treeview(self.orderbook_frame, columns=(
            "B-IV", "B-$", "B-S.", "Price", "A-S.", "A-$", "A-IV"
        ), show="headings", height=20)

        for col in ["B-IV", "B-$", "B-S.", "Price", "A-S.", "A-$", "A-IV"]:
            # self.tree.heading(col, text=col)
            self.tree.column(col, width=100, anchor="center")
        self.tree.pack()

        # After creating self.tree
        self.tree.tag_configure('bid', foreground='#00FF00')  # Bright green
        self.tree.tag_configure('ask', foreground='#FF3333')  # Bright red
        self.tree.tag_configure('spread', foreground='#AAAAAA', font=('Arial', 14, 'bold'))  # Optional midprice separator

        self.depth_level = 5

        # set initial values
        self.brti_average = 0.0
        self.tte = 0.0 # in hours

        #  Depth chart
        # self.fig, self.ax = plt.subplots(figsize=(3, 3))
        # self.canvas = FigureCanvasTkAgg(self.fig, master=self.main_frame)
        # self.canvas.get_tk_widget().pack()
        #
        # self.slider = tk.Scale(
        #    self.main_frame,
        #    from_=1,
        #    to=10,
        #    orient=tk.HORIZONTAL,
        #    label="Depth Levels",
        #    command=self.update_from_slider
        # 
        # self.slider.set(self.depth_level)  # Set initial value to match
        # self.slider.pack()
        #  Y-Lim slider
        # self.y_limit = 1000
        # self.ylim_slider = tk.Scale(
        #    self.main_frame,
        #    from_=10,
        #    to=3000,
        #    orient=tk.HORIZONTAL,
        #    label="Y-Axis Limit",
        #    command=self.update_from_slider
        # 
        # self.ylim_slider.set(100)  # Default initial Y limit
        # self.ylim_slider.pack()


        # Start updating loop
        self.update_loop()

    # def update_from_slider(self, event=None):
    #    self.depth_level = self.slider.get()
    #    self.y_limit = self.ylim_slider.get()

    def update_title_and_brti(self):

        brti_price, average, timestamp = get_brti_price()
        self.brti_average = average

        now_local = datetime.now().astimezone()
        now_utc = now_local.astimezone(timezone.utc)
        
        time_left = self.expiration_time - now_utc
        total_seconds = int(time_left.total_seconds())

        if total_seconds < 0:
            title_time = -1
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            title_time = f"{hours}h {minutes}m {seconds}s left"

    
        seconds_per_hour = 3600
        hours_left = total_seconds / seconds_per_hour
        self.tte = hours_left
        moneyness = get_moneyness(self.brti_average, self.strike, hours_left)

        self.title(f"Strike: {self.strike} | Moneyness: {moneyness:.2f} | TTE: {title_time}")

    def update_loop(self):
        def updater():
            while True:
                bids, asks = get_orderbook(self.ticker)  # 🔥 Now expect bids and asks
                self.update_title_and_brti()
                self.update_orderbook(bids, asks)
                time.sleep(1.0)

        threading.Thread(target=updater, daemon=True).start()

    def update_orderbook(self, bids, asks):
        # Clear old
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Sort properly

        sorted_bids = sorted(bids, key=lambda x: -x["price"])  # High to low
        sorted_asks = sorted(asks, key=lambda x: x["price"])   # Low to high
        self.bids = sorted_bids
        self.asks = sorted_asks

        # 🔥 Only show top self.depth_level bids and asks
        top_bids = sorted_bids[:self.depth_level]
        top_asks = sorted_asks[:self.depth_level]

        rows = [] # ↑↓

        previous_price = None
        epsilion = 1e-5

        # Walk down asks first 
        for ask in reversed(top_asks):
            ask_price = int(ask["price"])
            size = ask["quantity"]
            value = f"${ask_price * size / 100}"

            IV = implied_vol_binary_call(self.brti_average, self.strike, self.tte, ask_price/100)
            IV = f"{IV:.1f}%" # Convert to percentage

            if previous_price and abs(ask_price - previous_price) < 1 + epsilion:
                rows.append(("", "", "", ask_price, size, value, IV))
            elif previous_price and abs(ask_price - previous_price) > 1 + epsilion:
                spread = int(abs(round(ask_price - previous_price, 2)))
                rows.append(('', "", "", f"↑{spread}↓", '', "", '')) # add spread row
                rows.append(('', "", "", ask_price, size, value, IV))
            else:
                rows.append(('', "", "", ask_price, size, value, IV))
            
            previous_price = ask_price

        for bid in top_bids:
            bid_price = int(bid["price"])
            size = bid["quantity"]
            value = f"${bid_price * size / 100}"

            IV = implied_vol_binary_call(self.brti_average, self.strike, self.tte, bid_price/100)
            IV = f"{IV:.1f}%" # Convert to percentage

            if previous_price and abs(bid_price - previous_price) < 1 + epsilion:
                rows.append((IV, value, size, bid_price, '', '', ''))
            elif previous_price and abs(bid_price - previous_price) > 1 + epsilion:
                spread = int(abs(round(bid_price - previous_price, 2)))
                rows.append(('', "", "", f"↑{spread}↓", '', "", '')) # add spread row
                rows.append((IV, value, size, bid_price, '', '', ''))
            else:
                rows.append((IV, value, size, bid_price, '', '', ''))
            
            previous_price = bid_price


        # Insert into Treeview
        for row in rows:
            # Tagging
            tag = ""
            if row[0] and not row[-1]:  # Bid
                tag = "bid"
            elif row[-1] and not row[0]:  # Ask
                tag = "ask"
            elif "↑" in row[len(row)//2-1]:  # Spread
                tag = "spread"

            self.tree.insert("", "end", values=row, tags=(tag,))

        # Configure tags
        self.tree.tag_configure("bid", background="#173d1b")
        self.tree.tag_configure("ask", background="#3d1717")
        self.tree.tag_configure("spread", background="black", foreground="white", font=('Arial', 14, 'bold'))

        # Plot depth ,chart also limited by self.depth_level
        # self.plot_depth_chart(self.bids, self.asks, self.depth_level, self.y_limit)


    def plot_depth_chart(self, bids, asks, depth_level=3, size_lim=1000):
        self.ax.cla()

        if not bids or not asks:
            return

        # Sort properly
        bids = sorted(bids, key=lambda x: -x["price"])  # High to low
        asks = sorted(asks, key=lambda x: x["price"])   # Low to high

        # 🔥 Find best bid and ask
        best_bid = bids[0]["price"] if bids else None
        best_ask = asks[0]["price"] if asks else None

        if best_bid is None or best_ask is None:
            return

        # 🔥 Define midprice
        midprice = (best_bid + best_ask) / 2

        # 🔥 Select 3 nearest bids below mid
        close_bids = [b for b in bids if b["price"] <= midprice][:depth_level]

        # 🔥 Select 3 nearest asks above mid
        close_asks = [a for a in asks if a["price"] >= midprice][:depth_level]

        # Plot bids
        if len(close_bids) >= 1:
            bid_prices = [b["price"] for b in close_bids]
            bid_sizes = [b["quantity"] for b in close_bids]
            bid_cumsum = []
            total = 0
            for qty in bid_sizes:
                total += qty
                bid_cumsum.append(total)

            self.ax.step(bid_prices, bid_cumsum, where='post', color='green', alpha=0.7, label="Bids")
            self.ax.fill_between(bid_prices, bid_cumsum, step='post', alpha=0.3, color='green')

        # Plot asks
        if len(close_asks) >= 1:
            ask_prices = [a["price"] for a in close_asks]
            ask_sizes = [a["quantity"] for a in close_asks]
            ask_cumsum = []
            total = 0
            for qty in ask_sizes:
                total += qty
                ask_cumsum.append(total)

            self.ax.step(ask_prices, ask_cumsum, where='post', color='red', alpha=0.7, label="Asks")
            self.ax.fill_between(ask_prices, ask_cumsum, step='post', alpha=0.3, color='red')

        self.ax.grid(True)
        self.ax.relim()
        y_lim = min(size_lim, max(max(bid_cumsum) if bid_cumsum else 0, max(ask_cumsum) if ask_cumsum else 0))
        self.ax.set_ylim(0, size_lim) # Massive orders at the edges of the market
        self.ax.autoscale_view()

        self.canvas.draw()
