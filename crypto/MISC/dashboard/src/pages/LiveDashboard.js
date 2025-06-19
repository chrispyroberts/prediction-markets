import React from 'react';
import LivePriceChart from '../components/LivePrice';
import MarketViewer from '../components/MarketViewer';
import OptionsChainPanel from '../components/OptionsChainPanel';

export default function LiveDashboard() {
  return (
    <div style={{ padding: '2rem' }}>
      <h1>🚀 Real-Time Trading Dashboard</h1>

      {/* === BRTI Price Plot === */}
      <section style={{ marginBottom: '3rem' }}>
        <LivePriceChart />
      </section>

      {/* === Real-Time Order Book + Trades === */}
      <section style={{ marginBottom: '3rem' }}>
        <MarketViewer />
      </section>

      {/* === Options Chain + IV Smile === */}
      <section>
        <OptionsChainPanel />
      </section>
    </div>
  );
}
