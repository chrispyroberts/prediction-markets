import asyncio
import ccxt
import dash
from dash import dcc, html, Dash, Input, Output
import plotly.graph_objs as go
from datetime import datetime
import pandas as pd
import threading
import time

# === Global orderbook and trades ===
order_book = {'bids': [], 'asks': []}
recent_trades = []
exchange = ccxt.coinbase()
symbol = 'BTC/USD'

# === Background updater ===
def update_data():
    global order_book, recent_trades
    while True:
        try:
            ob = exchange.fetch_order_book(symbol, limit=50)
            order_book = ob
            recent_trades[:] = exchange.fetch_trades(symbol, limit=20)
        except Exception as e:
            print("❌ Update error:", e)
        time.sleep(1)

threading.Thread(target=update_data, daemon=True).start()

# === Dash App ===
app = Dash(__name__)
app.layout = html.Div([
    html.H1("Live BTC/USD Market Data Viewer"),
    dcc.Interval(id='interval', interval=1000, n_intervals=0),

    html.Div([
        html.Div([
            html.H3("Cumulative Order Depth"),
            dcc.Graph(id='depth-chart')
        ], style={'width': '49%', 'display': 'inline-block'}),

        html.Div([
            html.H3("Recent Trades"),
            html.Div(id='recent-trades')
        ], style={'width': '49%', 'display': 'inline-block', 'verticalAlign': 'top'})
    ]),

    html.Div([
        html.H3("Raw Order Book (Top 20)"),
        html.Div([
            html.Div(id='orderbook-bids', style={'width': '49%', 'display': 'inline-block', 'color': 'green'}),
            html.Div(id='orderbook-asks', style={'width': '49%', 'display': 'inline-block', 'color': 'red'})
        ])
    ])
])

@app.callback(
    Output('depth-chart', 'figure'),
    Output('recent-trades', 'children'),
    Output('orderbook-bids', 'children'),
    Output('orderbook-asks', 'children'),
    Input('interval', 'n_intervals')
)
def update_live(n):
    bids = order_book.get('bids', [])[:20]
    asks = order_book.get('asks', [])[:20]

    bids_sorted = sorted(bids, key=lambda x: -x[0])
    asks_sorted = sorted(asks, key=lambda x: x[0])

    bid_prices, bid_sizes = zip(*bids_sorted) if bids_sorted else ([], [])
    ask_prices, ask_sizes = zip(*asks_sorted) if asks_sorted else ([], [])

    cum_bid_sizes = list(pd.Series(bid_sizes).cumsum())
    cum_ask_sizes = list(pd.Series(ask_sizes).cumsum())

    depth_fig = go.Figure()
    depth_fig.add_trace(go.Scatter(x=bid_prices, y=cum_bid_sizes, name='Cumulative Bids', fill='tozeroy', mode='lines', line=dict(color='green')))
    depth_fig.add_trace(go.Scatter(x=ask_prices, y=cum_ask_sizes, name='Cumulative Asks', fill='tozeroy', mode='lines', line=dict(color='red')))
    depth_fig.update_layout(title='Order Depth', xaxis_title='Price', yaxis_title='Cumulative Size')

    trades_list = [
        html.Div(
            f"{datetime.fromtimestamp(t['timestamp']/1000)} | {t['side'].upper()} | {t['price']} x {t['amount']}",
            style={'color': 'green' if t['side'] == 'buy' else 'red'}
        )
        for t in recent_trades
    ]

    bids_table = html.Pre('\n'.join([f"{p:.2f} x {s:.4f}" for p, s in bids_sorted]))
    asks_table = html.Pre('\n'.join([f"{p:.2f} x {s:.4f}" for p, s in asks_sorted]))

    return depth_fig, trades_list, bids_table, asks_table

if __name__ == "__main__":
    app.run(debug=True)
