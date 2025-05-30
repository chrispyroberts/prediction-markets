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
        setTimestamp(update.timestamp); }
    });

    return () => socket.off('brti_and_options_update');
  }, []);

  const formatIV = (iv) => iv === null || isNaN(iv) ? 'nan%' : `${iv.toFixed(2)}%`;

  const smileData = contracts.map(c => {

    const mid_iv = c.mid_iv

    return {
      moneyness: c.moneyness,
      bid_iv: c.bid_iv ?? null,
      ask_iv: c.ask_iv ?? null,
      mid_iv: mid_iv ?? null
    };
  });

  const atmContract = contracts.reduce((closest, c) =>
    closest === null || Math.abs(c.moneyness) < Math.abs(closest.moneyness) ? c : closest,
    null
  );

  return (
    <div style={{ padding: '2rem' }}>
      {/* === Header === */}
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
            {['Ticker', 'Strike', 'Time Left', 'Moneyness', 'Interest', 'Bid IV', 'Bid Δ', 'Bid Value', 'Best Bid', 'Best Ask', 'Ask Value', 'Ask Δ', 'Ask IV'].map(h => (
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
              <td style={{ border: '1px solid #ccc', padding: '4px' }}>{isATM ? '⭐️ ' : ''}{c.strike}</td>
              <td style={{ border: '1px solid #ccc', padding: '4px' }}>{`${Math.floor(c.time_left_sec / 3600)}h ${Math.floor((c.time_left_sec % 3600) / 60)}m`}</td>
              <td style={{ border: '1px solid #ccc', padding: '4px' }}>{c.moneyness >= 0 ? '+' : ''}{c.moneyness.toFixed(2)}</td>
              <td style={{ border: '1px solid #ccc', padding: '4px' }}>{c.interest}</td>
              <td style={{ border: '1px solid #ccc', padding: '4px' }}>{formatIV(c.bid_iv)}</td>
              <td style={{ border: '1px solid #ccc', padding: '4px' }}>
                {typeof c.bid_delta === 'number' && !isNaN(c.bid_delta) ? c.bid_delta.toFixed(5) : '—'}
              </td>
              <td style={{ border: '1px solid #ccc', padding: '4px' }}>{c.bid_value}</td>
              <td style={{ border: '1px solid #ccc', padding: '4px', backgroundColor: '#eaffea' }}>{c.best_bid}</td>
              <td style={{ border: '1px solid #ccc', padding: '4px', backgroundColor: '#ffeaea' }}>{c.best_ask}</td>
              <td style={{ border: '1px solid #ccc', padding: '4px' }}>{c.ask_value}</td>
              <td style={{ border: '1px solid #ccc', padding: '4px' }}>
                {typeof c.ask_delta === 'number' && !isNaN(c.ask_delta) ? c.ask_delta.toFixed(5) : '—'}
              </td>
              <td style={{ border: '1px solid #ccc', padding: '4px' }}>{formatIV(c.ask_iv)}</td>


              </tr>
            );
          })}
        </tbody>
      </table>
    {/* === Range Replication Cost Table === */}
    <h3 style={{ marginTop: '2rem', marginBottom: '1rem' }}>Range Replication Costs (Including 2¢ Fee Per Leg)</h3>
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          <th>Range</th>
          <th>Cost to Buy Range</th>
          <th>Cost to Sell Range</th>
        </tr>
      </thead>
      <tbody>
        {contracts.slice(0, -1).map((c, i) => {
          const next = contracts[i + 1];
          const fee = 2;

          const buyCost = (
            parseFloat(c.best_ask) + fee - (parseFloat(next.best_bid) - fee)
          ).toFixed(4);

          const sellCost = (
            parseFloat(c.best_bid) - fee - (parseFloat(next.best_ask) + fee)
          ).toFixed(4);

          const isValid = ![c.best_ask, c.best_bid, next.best_ask, next.best_bid].some(val => isNaN(parseFloat(val)));

          return isValid ? (
            <tr key={i}>
              <td style={{ border: '1px solid #ccc', padding: '4px' }}>
                {c.strike}–{next.strike}
              </td>
              <td style={{ border: '1px solid #ccc', padding: '4px', backgroundColor: '#eaffea' }}>
                {buyCost}
              </td>
              <td style={{ border: '1px solid #ccc', padding: '4px', backgroundColor: '#ffeaea' }}>
                {sellCost}
              </td>
            </tr>
          ) : null;
        })}
      </tbody>
    </table>

      {/* === Volatility Smile === */}
      <h3 style={{ marginBottom: '1rem' }}>Volatility Smile (Bid, Ask, Mid IV)</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={smileData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="moneyness" label={{ value: "Moneyness", position: 'insideBottom', offset: -5 }} />
          <YAxis domain={['auto', 'auto']} tickFormatter={(v) => `${v.toFixed(2)}%`} label={{ value: "Implied Volatility (%)", angle: -90, position: 'insideLeft' }} />
          <Tooltip formatter={(value) => `${value?.toFixed(2)}%`} />
          <Legend />
          <Line type="monotone" dataKey="bid_iv" stroke="green" dot={{ r: 4 }} isAnimationActive={false} name="Bid IV" />
          <Line type="monotone" dataKey="ask_iv" stroke="red" dot={{ r: 4 }} isAnimationActive={false} name="Ask IV" />
          <Line type="monotone" dataKey="mid_iv" stroke="blue" dot={{ r: 4 }} isAnimationActive={false} name="Mid IV" />
        </LineChart>
      </ResponsiveContainer>

      {/* === Binary Price Chart === */}
      <h3 style={{ marginTop: '2rem', marginBottom: '1rem' }}>Binary Option Prices Across Strikes</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart
          data={contracts.map(c => ({
            strike: c.strike,
            best_bid: parseFloat(c.best_bid) / 100,
            best_ask: parseFloat(c.best_ask) / 100,
            mid_price: (parseFloat(c.best_bid) + parseFloat(c.best_ask)) / 200
          })).filter(d => !isNaN(d.best_bid) && !isNaN(d.best_ask))}
        >
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="strike" label={{ value: "Strike", position: 'insideBottom', offset: -5 }} />
          <YAxis domain={[0, 1]} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} label={{ value: "Binary Price (Implied Probability)", angle: -90, position: 'insideLeft' }} />
          <Tooltip formatter={(value) => `${(value * 100).toFixed(2)}%`} />
          <Legend />
          <Line type="monotone" dataKey="best_bid" stroke="#00C49F" dot={{ r: 4 }} isAnimationActive={false} name="Best Bid" />
          <Line type="monotone" dataKey="best_ask" stroke="#FF8042" dot={{ r: 4 }} isAnimationActive={false} name="Best Ask" />
          <Line type="monotone" dataKey="mid_price" stroke="#8884d8" dot={{ r: 4 }} isAnimationActive={false} name="Mid Price" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
