import React from 'react';

export default function OrderbookPanel({ ticker, bids, asks, onClose }) {
  // Determine max rows to display
  const maxRows = Math.max(bids.length, asks.length);

  return (
    <div style={{
      position: 'fixed',
      top: '10%',
      left: '10%',
      width: '400px',
      background: 'white',
      border: '1px solid #ccc',
      borderRadius: '10px',
      boxShadow: '0 2px 10px rgba(0,0,0,0.3)',
      zIndex: 1000,
      padding: '1rem'
    }}>
      <h3>📈 Order Book for {ticker}</h3>
      <button onClick={onClose} style={{ float: 'right' }}>❌ Close</button>

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ border: '1px solid #ccc' }}>Bid Qty</th>
            <th style={{ border: '1px solid #ccc' }}>Bid Price</th>
            <th style={{ border: '1px solid #ccc' }}>Ask Price</th>
            <th style={{ border: '1px solid #ccc' }}>Ask Qty</th>
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: maxRows }).map((_, i) => (
            <tr key={i}>
              <td style={{ border: '1px solid #ccc' }}>{bids[i]?.quantity ?? ''}</td>
              <td style={{ border: '1px solid #ccc' }}>{bids[i]?.price ?? ''}</td>
              <td style={{ border: '1px solid #ccc' }}>{asks[i]?.price ?? ''}</td>
              <td style={{ border: '1px solid #ccc' }}>{asks[i]?.quantity ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
