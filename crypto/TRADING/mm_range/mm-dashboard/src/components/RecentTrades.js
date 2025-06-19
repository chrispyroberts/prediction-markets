// src/components/RecentTrades.js
import React, { useEffect, useState } from 'react';
import { io } from 'socket.io-client';

const socket = io('http://localhost:5052', {
  transports: ['websocket']
});

export default function RecentTrades() {
  const [trades, setTrades] = useState([]);

  useEffect(() => {
    socket.on('dashboard_update', (data) => {
      const log = data.trade_log || [];
      setTrades(log.slice().reverse()); // show latest first
    });
    return () => socket.off('dashboard_update');
  }, []);

  return (
    <div style={{ padding: '1.5rem', maxHeight: '500px', overflowY: 'auto' }}>
      <h2>📝 Recent Trades</h2>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {['Ticker', 'Side', 'Price', 'Size', 'Position After', 'Avg Entry Price After'].map(h => (
              <th key={h} style={{ border: '1px solid #ccc', padding: '8px', background: '#f5f5f5' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i} style={{ backgroundColor: t.side === 'buy' ? '#eaffea' : '#ffeaea' }}>
              <td style={{ border: '1px solid #ccc', padding: '8px' }}>{t.ticker}</td>
              <td style={{ border: '1px solid #ccc', padding: '8px', color: t.side === 'buy' ? 'green' : 'red' }}>{t.side}</td>
              <td style={{ border: '1px solid #ccc', padding: '8px' }}>{t.price?.toFixed(2)}</td>
              <td style={{ border: '1px solid #ccc', padding: '8px' }}>{t.size}</td>
              <td style={{ border: '1px solid #ccc', padding: '8px' }}>{t.position_after}</td>
              <td style={{ border: '1px solid #ccc', padding: '8px' }}>{t.avg_entry_price_after?.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
