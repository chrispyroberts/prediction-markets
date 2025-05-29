// src/components/MarketViewer.js
import React, { useEffect, useState } from 'react';
import { io } from 'socket.io-client';
import Plot from 'react-plotly.js';

const socket = io('http://localhost:5051', {
  transports: ['websocket']
});

export default function MarketViewer() {
  const [bids, setBids] = useState([]);
  const [asks, setAsks] = useState([]);
  const [trades, setTrades] = useState([]);

  useEffect(() => {
    socket.on('market_data_update', data => {
      setBids(data.order_book.bids.slice(0, 20));
      setAsks(data.order_book.asks.slice(0, 20));
      setTrades(data.recent_trades.slice(0, 20));
    });
    return () => socket.off('market_data_update');
  }, []);

  const cumulate = arr => arr.reduce((acc, val, i) => {
    acc.push((acc[i - 1] || 0) + val[1]);
    return acc;
  }, []);

  const bidPrices = bids.map(b => b[0]);
  const bidSizes = bids.map(b => b[1]);
  const askPrices = asks.map(a => a[0]);
  const askSizes = asks.map(a => a[1]);

  const cumBidSizes = cumulate(bids);
  const cumAskSizes = cumulate(asks);

  return (
    <div style={{ display: 'flex', gap: '20px', padding: '10px' }}>
      {/* Depth Chart */}
      <div style={{ flex: 1, minWidth: '300px' }}>
        <h3>Depth Chart</h3>
        <Plot
          data={[
            {
              x: bidPrices,
              y: cumBidSizes,
              type: 'scatter',
              mode: 'lines',
              name: 'Bids',
              line: { color: 'green' }
            },
            {
              x: askPrices,
              y: cumAskSizes,
              type: 'scatter',
              mode: 'lines',
              name: 'Asks',
              line: { color: 'red' }
            }
          ]}
          layout={{
            margin: { t: 30, l: 40, r: 10, b: 40 },
            xaxis: { title: 'Price' },
            yaxis: { title: 'Cumulative Size' },
            height: 300
          }}
        />
      </div>

      {/* Order Book */}
      <div style={{ flex: 0.6, minWidth: '200px' }}>
        <h3>Order Book (Top 20)</h3>
        <div style={{ display: 'flex', gap: '10px' }}>
          <pre style={{ color: 'green', flex: 1 }}>
            {bids.map(([p, s], i) => `${p.toFixed(2)} x ${s.toFixed(4)}`).join('\n')}
          </pre>
          <pre style={{ color: 'red', flex: 1 }}>
            {asks.map(([p, s], i) => `${p.toFixed(2)} x ${s.toFixed(4)}`).join('\n')}
          </pre>
        </div>
      </div>

      {/* Recent Trades */}
      <div style={{ flex: 0.8, minWidth: '250px' }}>
        <h3>Recent Trades</h3>
        <div style={{ fontSize: '12px' }}>
          {trades.map((t, i) => (
            <div key={i} style={{ color: t.side === 'buy' ? 'green' : 'red' }}>
              {new Date(t.timestamp).toLocaleTimeString()} | {t.side.toUpperCase()} | {t.price} x {t.amount}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
