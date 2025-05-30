import React, { useEffect, useState, useRef } from 'react';
import { io } from 'socket.io-client';

const socket = io('http://localhost:5052', {
  transports: ['websocket']
});

export default function QuotesPanel() {
  const [quotes, setQuotes] = useState({});
  const seenTickers = useRef(new Set());

  useEffect(() => {
    socket.on('dashboard_update', (data) => {
      const currentMarket = data.market_quotes || {};
      const currentOur = data.our_quotes || {};
      const currentPositions = data.positions || {};
      const avgPrices = data.avg_prices || {};
      const midPrices = data.mid_prices || {};
      const realizedPnls = data.realized_pnl || {};
      const strikes = data.strikes || {};
      const brti = data.brti_60s_price || 0;

      Object.keys({
        ...currentMarket,
        ...currentOur,
        ...currentPositions,
        ...midPrices,
        ...realizedPnls
      }).forEach(ticker => seenTickers.current.add(ticker));

      const merged = {};
      seenTickers.current.forEach(ticker => {
        const pos = currentPositions[ticker] ?? 0;
        const avg = avgPrices[ticker] ?? null;
        const mid = midPrices[ticker] ?? null;
        const unrealized = (pos !== 0 && avg !== null && mid !== null)
          ? ((mid - avg) * pos) / 100
          : null;
        const realized = realizedPnls[ticker] ?? null;

        merged[ticker] = {
          ticker,
          strike: strikes[ticker] ?? ticker,
          position: pos,
          avg_price: avg,
          mid_price: mid,
          unrealized_pnl: unrealized,
          realized_pnl: realized,
          spread: null,
          mm_bid: null,
          mm_ask: null,
          best_bid: null,
          best_ask: null,
          our_bid: null,
          our_ask: null
        };
      });

      Object.entries(currentMarket).forEach(([ticker, quote]) => {
        merged[ticker] = {
          ...merged[ticker],
          ...quote
        };
      });

      Object.entries(currentOur).forEach(([ticker, quote]) => {
        merged[ticker].our_bid = quote.bid;
        merged[ticker].our_ask = quote.ask;
      });

      merged._brti = brti; // inject brti into hidden key
      setQuotes(merged);
    });

    return () => socket.off('dashboard_update');
  }, []);

  const brtiPrice = quotes._brti || 0;
  const sorted = Object.values(quotes)
    .filter(q => q.ticker !== '_brti')
    .sort((a, b) => (a.ticker || '').localeCompare(b.ticker || ''));

  return (
    <div style={{ padding: '1.5rem', maxHeight: '1090px', overflowY: 'auto' }}>
      <h2>📊 Live Market Quotes (Bid/Ask) — BRTI: ${brtiPrice.toFixed(2)}</h2>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {[ 'Ticker', 'Strike', 'Position', 'Avg Price', 'Last Mid Price', 'Unrealized PnL ($)', 'Realized PnL ($)', 'Spread', 'MM Bid', 'Our Bid', 'Our Ask', 'MM Ask' ].map(h => (
              <th key={h} style={{ border: '1px solid #ccc', padding: '8px', background: '#f5f5f5' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(entry => {
            const isITM = (() => {
              if (!entry.strike || typeof entry.strike !== 'string') return false;
              const [low, high] = entry.strike.split('-').map(Number);
              return brtiPrice >= low && brtiPrice <= high;
            })();

            return (
              <tr key={entry.ticker} style={{ backgroundColor: isITM ? '#fff3cd' : '' }}>
                <td style={{ border: '1px solid #ccc', padding: '8px' }}>{entry.ticker}</td>
                <td style={{ border: '1px solid #ccc', padding: '8px' }}>{entry.strike}</td>
                <td style={{ border: '1px solid #ccc', padding: '8px' }}>{entry.position}</td>
                <td style={{ border: '1px solid #ccc', padding: '8px' }}>{typeof entry.avg_price === 'number' ? entry.avg_price.toFixed(2) : ''}</td>
                <td style={{ border: '1px solid #ccc', padding: '8px' }}>{typeof entry.mid_price === 'number' ? entry.mid_price.toFixed(2) : ''}</td>
                <td style={{ border: '1px solid #ccc', padding: '8px', color: entry.unrealized_pnl >= 0 ? 'green' : 'red' }}>{typeof entry.unrealized_pnl === 'number' ? entry.unrealized_pnl.toFixed(2) : ''}</td>
                <td style={{ border: '1px solid #ccc', padding: '8px', color: entry.realized_pnl >= 0 ? 'green' : 'red' }}>{typeof entry.realized_pnl === 'number' ? entry.realized_pnl.toFixed(2) : ''}</td>
                <td style={{ border: '1px solid #ccc', padding: '8px' }}>{typeof entry.spread === 'number' ? entry.spread.toFixed(2) : ''}</td>
                <td style={{ border: '1px solid #ccc', padding: '8px', backgroundColor: '#eaffea' }}>{entry.mm_bid ?? ''}</td>
                <td style={{ border: '1px solid #ccc', padding: '8px' }}>{entry.our_bid ?? ''}</td>
                <td style={{ border: '1px solid #ccc', padding: '8px' }}>{entry.our_ask ?? ''}</td>
                <td style={{ border: '1px solid #ccc', padding: '8px', backgroundColor: '#ffeaea' }}>{entry.mm_ask ?? ''}</td>
              </tr>
            );
          })}
        </tbody>

      </table>
    </div>
  );
}
