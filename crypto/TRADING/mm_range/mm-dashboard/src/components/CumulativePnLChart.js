// src/components/CumulativePnLChart.js
import React, { useEffect, useState, useRef } from 'react';
import { io } from 'socket.io-client';
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  CartesianGrid, ResponsiveContainer, Legend
} from 'recharts';

const socket = io('http://localhost:5052', {
  transports: ['websocket']
});

export default function CumulativePnLChart() {
  const pnlHistoryRef = useRef({});
  const expectedHistoryRef = useRef([]);
  const [, forceUpdate] = useState(0); // renamed _ to avoid eslint warning
  const [selected, setSelected] = useState('ALL');
  const seenTickers = useRef(new Set());

  useEffect(() => {
    socket.on('dashboard_update', (data) => {
      const currentPositions = data.positions || {};
      const avgPrices = data.avg_prices || {};
      const midPrices = data.mid_prices || {};
      const realizedPnls = data.realized_pnl || {};
      const timestamp = data.timestamp || new Date().toISOString();
      const totalExpected = data.total_expected_spread_pnl || 0;

      const updated = { ...pnlHistoryRef.current };

      const allKeys = new Set([
        ...Object.keys(currentPositions),
        ...Object.keys(avgPrices),
        ...Object.keys(midPrices),
        ...Object.keys(realizedPnls)
      ]);

      allKeys.forEach(ticker => {
        seenTickers.current.add(ticker);

        const pos = currentPositions[ticker] ?? 0;
        const avg = avgPrices[ticker] ?? null;
        const mid = midPrices[ticker] ?? null;
        const realized = realizedPnls[ticker] ?? 0;

        const unrealized = (pos !== 0 && avg !== null && mid !== null)
          ? ((mid - avg) * pos) / 100
          : 0;

        const total = unrealized + realized;

        if (!updated[ticker]) updated[ticker] = [];

        updated[ticker].push({ timestamp, pnl: total });
      });

      pnlHistoryRef.current = updated;

      expectedHistoryRef.current.push({ timestamp, expected: totalExpected });

      forceUpdate(prev => prev + 1); // trigger re-render
    });

    return () => socket.off('dashboard_update');
  }, []);

  const tickerOptions = ['ALL', ...Array.from(seenTickers.current).sort()];

  const chartData = selected === 'ALL'
    ? Object.entries(pnlHistoryRef.current).reduce((acc, [, data]) => {
        data.forEach((point, i) => {
          if (!acc[i]) acc[i] = { timestamp: point.timestamp, pnl: 0 };
          acc[i].pnl += point.pnl;
        });
        expectedHistoryRef.current.forEach((point, i) => {
          if (acc[i]) acc[i].expected = point.expected;
        });
        return acc;
      }, [])
    : pnlHistoryRef.current[selected] || [];

  return (
    <div style={{ padding: '2rem' }}>
      <h2>📈 Cumulative PnL Over Time</h2>

      <select value={selected} onChange={e => setSelected(e.target.value)} style={{ marginBottom: '1rem' }}>
        {tickerOptions.map(t => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>

      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData} isAnimationActive={false}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="timestamp" hide={true} />
          <YAxis domain={['auto', 'auto']} label={{ value: 'PnL ($)', angle: -90, position: 'insideLeft' }} />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="pnl" stroke="#8884d8" dot={false} name="Cumulative PnL" isAnimationActive={false} />
          {selected === 'ALL' && (
            <Line type="monotone" dataKey="expected" stroke="#00C49F" dot={false} name="Expected Spread PnL" isAnimationActive={false} />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
