# main.py
import tkinter as tk
# from orderbook_window import OrderbookWindow
from brti_window import BRTIWindow
from contract_window import ContractWindow
from options_chain_window import OptionsChainWindow
from tkinter import simpledialog
from utils import get_orderbook, get_options_chain_for_event

class MainApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Trading Dashboard")

        # Bind ',' key to quit
        root.bind(',', self.close_app)

        tk.Label(root, text="Select windows to open:", font=("Arial", 16)).pack(pady=10)
        # tk.Button(root, text="Open Orderbook", width=20, command=self.open_orderbook).pack(pady=5)
        tk.Button(root, text="Open BRTI Price", width=20, command=self.open_brti).pack(pady=5)
        tk.Button(root, text="Open Contract Viewer", width=25, command=self.ask_and_open_contract).pack(pady=5)

        tk.Button(root, text="Open Options Chain", width=25, command=self.ask_and_open_options_chain).pack(pady=5) 

    def ask_and_open_options_chain(self):
        # 🔥 Popup asking for event string
        event = simpledialog.askstring("Input", "Enter event name:", parent=self.root)

        if event:
            data = get_options_chain_for_event(event)

            if data is None:
                tk.messagebox.showerror("Error", "No options chain found for that event.")
                return
            else:
                OptionsChainWindow(event, master=self.root)

    def open_brti(self):
        BRTIWindow(self.root)

    def ask_and_open_contract(self):
        # 🔥 Popup asking for ticker
        ticker = simpledialog.askstring("Input", "Enter ticker:", parent=self.root)

        res, _ =  get_orderbook(ticker)

        # tell user invalid ticker
        if res is None:
            tk.messagebox.showerror("Error", "Invalid ticker. Please try again.")
            return

        if res:  # If user didn't cancel
            ContractWindow(ticker, self.root)
        
    def close_app(self, event=None):
        print("Closing app because ',' key pressed.")
        self.root.quit()  # Or you could use self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()
