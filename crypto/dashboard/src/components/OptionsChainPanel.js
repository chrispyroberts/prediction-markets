import React, { useEffect, useState } from 'react';
import { io } from 'socket.io-client';
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  CartesianGrid, ResponsiveContainer, Legend
} from 'recharts';

const socket = io('http://localhost:5050', {
  transports: ['websocket']
});

export default function OptionsChainPanel() {
  const [contracts, setContracts] = useState([]);
  const [brti, setBrti] = useState(null);
  const [avg, setAvg] = useState(null);
  const [timestamp, setTimestamp] = useState(null);

  useEffect(() => {
    socket.on('brti_and_options_update', (update) => {
      if (update.contracts) {
        setContracts(update.contracts);
        setBrti(update.brti);
        setAvg(update.simple_average);
        setTimestamp(update.timestamp);
      }
    });

    return () => socket.off('brti_and_options_update');
  }, []);

  const formatIV = (iv) => iv === null || isNaN(iv) ? 'nan%' : `${iv.toFixed(2)}%`;

  const smileData = contracts.map(c => {
    const hasBid = c.bid_iv !== null && !isNaN(c.bid_iv);
    const hasAsk = c.ask_iv !== null && !isNaN(c.ask_iv);
    const mid_iv = hasBid && hasAsk ? (c.bid_iv + c.ask_iv) / 2 : null;

    return {
      moneyness: c.moneyness,
      bid_iv: c.bid_iv ?? null,
      ask_iv: c.ask_iv ?? null,
      mid_iv
    };
  });

  const atmContract = contracts.reduce((closest, c) =>
    closest === null || Math.abs(c.moneyness) < Math.abs(closest.moneyness) ? c : closest,
    null
  );

  return (
    <div style={{ padding: '2rem' }}>
      {/* === Live Price Header === */}
      <div style={{
        marginBottom: '1.5rem',
        padding: '1rem',
        backgroundColor: '#f8f8f8',
        borderRadius: '10px',
        boxShadow: '0 2px 5px rgba(0,0,0,0.05)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        fontSize: '1.1rem'
      }}>
        <div>💰 <strong>BRTI:</strong> {brti ? `$${brti.toFixed(2)}` : 'Loading...'}</div>
        <div>📊 <strong>Avg:</strong> {avg ? `$${avg.toFixed(2)}` : '...'}</div>
        <div>🕒 <strong>{timestamp ?? ''}</strong></div>
      </div>

      {/* === Options Table === */}
      <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: '2rem' }}>
        <thead>
          <tr>
            {['Ticker', 'Strike', 'Time Left', 'Moneyness', 'Interest', 'Bid IV', 'Bid Value', 'Best Bid', 'Best Ask', 'Ask Value', 'Ask IV'].map(h => (
              <th key={h} style={{ border: '1px solid #ccc', padding: '8px', background: '#f5f5f5' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {contracts.map(c => {
            const isATM = atmContract && c.ticker === atmContract.ticker;
            const rowStyle = {
              backgroundColor: isATM ? '#ffeaa7' : undefined,
              fontWeight: isATM ? 'bold' : 'normal'
            };

            return (
              <tr key={c.ticker} style={rowStyle}>
                <td style={{ border: '1px solid #ccc', padding: '4px' }}>{c.ticker}</td>
                <td style={{ border: '1px solid #ccc', padding: '4px' }}>
                  {isATM ? '⭐️ ' : ''}{c.strike}
                </td>
                <td style={{ border: '1px solid #ccc', padding: '4px' }}>
                  {`${Math.floor(c.time_left_sec / 3600)}h ${Math.floor((c.time_left_sec % 3600) / 60)}m`}
                </td>
                <td style={{ border: '1px solid #ccc', padding: '4px' }}>
                  {c.moneyness >= 0 ? '+' : ''}{c.moneyness.toFixed(2)}
                </td>
                <td style={{ border: '1px solid #ccc', padding: '4px' }}>{c.interest}</td>
                <td style={{ border: '1px solid #ccc', padding: '4px' }}>{formatIV(c.bid_iv)}</td>
                <td style={{ border: '1px solid #ccc', padding: '4px' }}>{c.bid_value}</td>
                <td style={{
                  border: '1px solid #ccc',
                  padding: '4px',
                  backgroundColor: '#eaffea' // light green
                }}>{c.best_bid}</td>
                <td style={{
                  border: '1px solid #ccc',
                  padding: '4px',
                  backgroundColor: '#ffeaea' // light red
                }}>{c.best_ask}</td>
                <td style={{ border: '1px solid #ccc', padding: '4px' }}>{c.ask_value}</td>
                <td style={{ border: '1px solid #ccc', padding: '4px' }}>{formatIV(c.ask_iv)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* === Volatility Smile Chart (Bid/Ask/Mid Overlay) === */}
      <h3 style={{ marginBottom: '1rem' }}>Volatility Smile (Bid, Ask, Mid IV)</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={smileData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="moneyness" label={{ value: "Moneyness", position: 'insideBottom', offset: -5 }} />
          <YAxis
            domain={['auto', 'auto']}
            tickFormatter={(v) => `${v.toFixed(2)}%`}
            label={{ value: "Implied Volatility (%)", angle: -90, position: 'insideLeft' }}
          />
          <Tooltip formatter={(value) => `${value?.toFixed(2)}%`} />
          <Legend />
          <Line
            type="monotone"
            dataKey="bid_iv"
            stroke="green"
            dot={{ r: 4 }}
            isAnimationActive={false}
            name="Bid IV"
          />
          <Line
            type="monotone"
            dataKey="ask_iv"
            stroke="red"
            dot={{ r: 4 }}
            isAnimationActive={false}
            name="Ask IV"
          />
          <Line
            type="monotone"
            dataKey="mid_iv"
            stroke="blue"
            dot={{ r: 4 }}
            isAnimationActive={false}
            name="Mid IV"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
