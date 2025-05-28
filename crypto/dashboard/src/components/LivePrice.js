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

  useEffect(() => {
    let lastUpdate = 0;

    socket.on('brti_and_options_update', (update) => {
      const now = Date.now();
      if (now - lastUpdate > 100) { // 1 point/sec
        lastUpdate = now;

        const newPoint = {
          time: update.timestamp.split(' ')[1],
          price: update.brti,
          average: update.simple_average
        };

        setData(prev => {
          const updated = [...prev, newPoint];
          return updated.length > 60 ? updated.slice(-60) : updated;
        });
      }
    });

    return () => socket.off('price_update');
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
          backgroundColor: 'rgba(255,255,255,0.8)',
          padding: '0.5rem 1rem',
          borderRadius: '8px',
          boxShadow: '0 0 5px rgba(0,0,0,0.1)',
          fontSize: '0.9rem'
        }}>
          <div>💰 <strong>${data.at(-1).price.toFixed(2)}</strong></div>
          <div>📊 Avg: <strong>${data.at(-1).average.toFixed(2)}</strong></div>
          <div>🕒 {data.at(-1).time}</div>
        </div>
      )}
    </div>
  );
}
