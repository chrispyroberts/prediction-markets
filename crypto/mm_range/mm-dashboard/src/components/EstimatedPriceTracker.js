import React, { useEffect, useState } from 'react';
import { io } from 'socket.io-client';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line
} from 'recharts';

const socket = io('http://localhost:5052', {
  transports: ['websocket']
});

export default function EstimatedPriceTracker() {
  const [selectedContract, setSelectedContract] = useState('');
  const [contracts, setContracts] = useState([]);
  const [allData, setAllData] = useState({});
  const [volatilityData, setVolatilityData] = useState([]);

  useEffect(() => {
    socket.on('dashboard_update', (update) => {
      const marketQuotes = update.market_quotes || {};
      const estMidPrices = update.estimated_mid_prices || {};
      const volatility = update.brti_60s_realized_volatility || 0;
      const time = new Date().toLocaleTimeString();

      // Update volatility data (last 10 min = 600 points)
      setVolatilityData(prev => [
        ...prev.slice(-599),
        { time, volatility: volatility * 100 }  // convert to percentage
      ]);

      const updatedData = { ...allData };

      Object.keys(marketQuotes).forEach((ticker) => {
        const { best_bid, best_ask } = marketQuotes[ticker];
        const estMid = estMidPrices[ticker] ?? null;

        const estMin = estMid !== null ? Math.max(0, estMid - 5) : null;
        const estMax = estMid !== null ? Math.min(100, estMid + 5) : null;
        const bandHeight = estMax !== null && estMin !== null ? estMax - estMin : null;

        let marketBandMin = null;
        let marketBandHeight = null;
        if (best_bid !== null && best_ask !== null && best_bid !== undefined && best_ask !== undefined) {
          marketBandMin = best_bid;
          marketBandHeight = best_ask - best_bid;
        }

        if (!updatedData[ticker]) updatedData[ticker] = [];
        updatedData[ticker] = [
          ...updatedData[ticker].slice(-99),
          { time, estMin, bandHeight, marketBandMin, marketBandHeight }
        ];
      });

      setAllData(updatedData);

      if (contracts.length === 0 && Object.keys(marketQuotes).length > 0) {
        setContracts(Object.keys(marketQuotes));
        setSelectedContract(Object.keys(marketQuotes)[0]);
      }
    });

    return () => socket.off('dashboard_update');
  }, [allData, contracts]);

  const currentData = selectedContract ? allData[selectedContract] || [] : [];

  return (
    <div style={{ marginTop: '2rem', padding: '1rem', border: '1px solid #ccc', borderRadius: '10px' }}>
      <h3>📈 Estimated Price Band (±5c) & Market Bid/Ask Band</h3>
      <label>Select Contract: </label>
      <select value={selectedContract} onChange={e => setSelectedContract(e.target.value)}>
        {contracts.map(ticker => (
          <option key={ticker} value={ticker}>{ticker}</option>
        ))}
      </select>

      {/* Main Shaded Area Plot */}
      <div style={{ width: '100%', height: 300, marginTop: '1rem' }}>
        <ResponsiveContainer>
          <AreaChart data={currentData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" />
            <YAxis />
            <Tooltip />

            {/* Estimated mid price band (blue) */}
            <Area
              type="monotone"
              dataKey="estMin"
              stackId="1"
              stroke="none"
              fill="transparent"
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="bandHeight"
              stackId="1"
              stroke="none"
              fill="blue"
              fillOpacity={0.3}
              isAnimationActive={false}
            />

            {/* Market bid/ask band (red) */}
            <Area
              type="monotone"
              dataKey="marketBandMin"
              stackId="2"
              stroke="none"
              fill="transparent"
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="marketBandHeight"
              stackId="2"
              stroke="none"
              fill="red"
              fillOpacity={0.3}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Volatility Plot */}
      <div style={{ width: '100%', height: 200, marginTop: '2rem' }}>
        <h4>📊 60s Realized Annualized Volatility (Last 10 min)</h4>
        <ResponsiveContainer>
          <LineChart data={volatilityData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" />
            <YAxis unit="%" />
            <Tooltip />
            <Line
              type="monotone"
              dataKey="volatility"
              stroke="orange"
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
