// src/App.js
import React from 'react';
import QuotesPanel from './components/QuotesPanel';
import CumulativePnLChart from './components/CumulativePnLChart';
import RecentTrades from './components/RecentTrades'; // <-- import here
import MarketMakingStats from './components/MarketMakingStats'; // <-- import if needed

function App() {
  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
      <QuotesPanel />
      <MarketMakingStats /> {/* <-- add component if needed */}
      <CumulativePnLChart />
      <RecentTrades /> {/* <-- add component here */}
    </div>
  );
}

export default App;
