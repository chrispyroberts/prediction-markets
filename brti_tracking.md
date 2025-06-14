* **📡 Real-time price scraper**

  * Uses `Playwright` to poll BRTI index every \~0.3s
  * Detects new prices and calculates a 60-second simple moving average (SMA)

* **🛠 EC2 server setup**

  * Runs the scraper 24/7 on an AWS EC2 instance
  * Uses system-level watchdog logic to auto-restart if it stalls

* **🗃 PostgreSQL database**

  * Stores all price updates in a `brti_prices` table with a `TIMESTAMPTZ` field
  * Accepts direct inserts from the scraper and allows remote SSH access

* **🔐 Secure local access**

  * Connects via SSH tunnel from your local machine
  * Allows read-only access to data in Python notebooks

* **📈 Pandas + Matplotlib visualization**

  * Fetches all data into a DataFrame
  * Plots BRTI price over time with EST timestamps
  * Supports resampling, formatting, and rolling analysis

* **🧠 Flexible for analysis**

  * Can easily extend to track volatility, price spikes, or export to CSV/Parquet
  * Ready for integration into models, alerts, or dashboards
