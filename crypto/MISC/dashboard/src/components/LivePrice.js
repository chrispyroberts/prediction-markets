import React, { useEffect, useState } from 'react';
import { io } from 'socket.io-client';
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid
} from 'recharts';

const socket = io('http://localhost:5050', {
  transports: ['websocket']
});

export default function LivePriceChart() {
  const [data, setData] = useState([]);
  const [fullData, setFullData] = useState([]);
  const [vol60s, setVol60s] = useState(null);
  const [volFull, setVolFull] = useState(null);

  useEffect(() => {
    let lastUpdate = 0;

    socket.on('brti_and_options_update', (update) => {
      const now = Date.now();
      if (now - lastUpdate > 100) {
        lastUpdate = now;

        const newPoint = {
          time: update.timestamp.split(' ')[1],
          price: update.brti,
          average: update.simple_average
        };

        // Update 60s window
        setData(prev => {
          const updated = [...prev, newPoint];
          const sliced = updated.length > 60 ? updated.slice(-60) : updated;

          if (sliced.length >= 2) {
            const returns = sliced
              .map(p => p.price)
              .map((p, i, arr) => (i === 0 ? null : Math.log(p / arr[i - 1])))
              .filter(r => r !== null);

            const std = Math.sqrt(returns.reduce((sum, r) => sum + r ** 2, 0) / (returns.length - 1));
            const annualized = std * Math.sqrt(60 * 60 * 24 * 365);  // annualize from 1s intervals
            setVol60s(annualized);
          }

          return sliced;
        });

        // Update full window
        setFullData(prev => {
          const updated = [...prev, newPoint];

          if (updated.length >= 2) {
            const returns = updated
              .map(p => p.price)
              .map((p, i, arr) => (i === 0 ? null : Math.log(p / arr[i - 1])))
              .filter(r => r !== null);

            const std = Math.sqrt(returns.reduce((sum, r) => sum + r ** 2, 0) / (returns.length - 1));
            const annualized = std * Math.sqrt(60 * 60 * 24 * 365);
            setVolFull(annualized);
          }

          return updated;
        });
      }
    });

    return () => socket.off('brti_and_options_update');
  }, []);

  return (
    <div style={{ padding: '2rem', position: 'relative' }}>
      <h2>📈 Live Bitcoin Price</h2>

      <ResponsiveContainer width="100%" height={400}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="time" tick={{ fontSize: 10 }} />
          <YAxis domain={['auto', 'auto']} />
          <Tooltip />
          <Line
            type="monotone"
            dataKey="price"
            stroke="#82ca9d"
            dot={false}
            isAnimationActive={false}
            name="Price"
          />
          <Line
            type="monotone"
            dataKey="average"
            stroke="#8884d8"
            dot={false}
            isAnimationActive={false}
            name="Simple Avg"
          />
        </LineChart>
      </ResponsiveContainer>

      {data.length > 0 && (
        <div style={{
          position: 'absolute',
          top: '2.5rem',
          right: '2rem',
          backgroundColor: 'rgba(255,255,255,0.85)',
          padding: '0.75rem 1rem',
          borderRadius: '8px',
          boxShadow: '0 0 6px rgba(0,0,0,0.1)',
          fontSize: '0.9rem',
          lineHeight: '1.5'
        }}>
          <div>💰 <strong>${data.at(-1).price.toFixed(2)}</strong></div>
          <div>📊 Avg: <strong>${data.at(-1).average.toFixed(2)}</strong></div>
          <div>🕒 {data.at(-1).time}</div>
          <div>📈 RV (60s): <strong>{vol60s !== null ? (vol60s * 100).toFixed(2) + '%' : '—'}</strong></div>
          <div>📈 RV (Full): <strong>{volFull !== null ? (volFull * 100).toFixed(2) + '%' : '—'}</strong></div>
          <div>📏 60s Samples: <strong>{data.length}</strong></div>
          <div>📦 Full Samples: <strong>{fullData.length}</strong></div>
        </div>
      )}
    </div>
  );
}
