// src/components/MarketMakingStats.js
import React, { useEffect, useState } from 'react';
import { io } from 'socket.io-client';

const socket = io('http://localhost:5052', {
  transports: ['websocket']
});

export default function MarketMakingStats() {
  const [totalPnL, setTotalPnL] = useState(0);
  const [totalTrades, setTotalTrades] = useState(0);
  const [totalExpected, setTotalExpected] = useState(0);
  const [totalCumulativePnL, setTotalCumulativePnL] = useState(0);

  useEffect(() => {
    socket.on('dashboard_update', (data) => {
      const realized = data.realized_pnl || {};
      const trades = data.total_trades || 0;
      const expected = data.total_expected_spread_pnl || 0;
      const totalRealized = Object.values(realized).reduce((a, b) => a + b, 0);
      const cumulative = data.cumulative_pnl || 0;

      setTotalPnL(totalRealized);
      setTotalTrades(trades);
      setTotalExpected(expected);
      setTotalCumulativePnL(cumulative);
    });
    return () => socket.off('dashboard_update');
  }, []);

  const realizedPerTrade = totalTrades > 0 ? (totalPnL / totalTrades).toFixed(4) : 'N/A';
  const expectedPerTrade = totalTrades > 0 ? (totalExpected / totalTrades).toFixed(4) : 'N/A';
  const pnlVsExpected = (totalPnL - totalExpected).toFixed(4);

  return (
    <div style={{ padding: '1.5rem' }}>
      <h2>⚖️ Market Making Stats</h2>
      <p><strong>Total Trades:</strong> {totalTrades}</p>
      <p><strong>Total Expected Edge:</strong> ${totalExpected.toFixed(4)}</p>
      <p><strong>Total Realized PnL:</strong> ${totalPnL.toFixed(4)}</p>
      <p><strong>Total PnL (Realized + Unrealized):</strong> ${totalCumulativePnL.toFixed(4)}</p>
      <p><strong>Realized PnL / Trade:</strong> ${realizedPerTrade}</p>
      <p><strong>Expected Realized PnL / Trade:</strong> ${expectedPerTrade}</p>
      <p><strong>PnL vs Expected:</strong> ${pnlVsExpected}</p>
    </div>
  );
}
