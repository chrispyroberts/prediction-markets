# brti_calc_ccxt.py
"""Minimal, complete BRTI prototype – now **auto‑skips unsupported venues**
=======================================================================
Streams order‑books from every exchange in `EXCHANGES`, but if the user’s
local `ccxt` / `ccxt.pro` build doesn’t recognise a given id (e.g. `lmaxdigital`
or `bullish`) the script now prints a notice and simply leaves that venue out of
the calculation instead of raising an AttributeError.

The rest of the methodology is unchanged: 1‑BTC grid, μ + 5σ cap, 0.5 % depth
cut‑off, exponential weighting.  WebSockets (ccxt.pro) if available, otherwise
concurrent REST polling.
"""

from __future__ import annotations
import asyncio, bisect, time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Tuple
import numpy as np

# optional faster loop
try:
    import uvloop  # type: ignore
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

# choose ccxt backend
try:
    import ccxt.pro as ccxt  # type: ignore
    USE_WS = True
    print("[INIT] ccxt.pro detected – WebSocket mode ✔︎")
except ImportError:
    import ccxt.async_support as ccxt  # type: ignore
    USE_WS = False
    print("[INIT] ccxt.pro not found – REST mode …")

# methodology constants
SPACING_VOL = 1        # 1 BTC grid spacing
DEV_MID = 0.005        # 0.5 % utilised‑depth threshold
ERR_BAND = 0.05        # 5 % potentially erroneous data band
MAX_SAMPLE = 50        # dynamic‑cap sample size
STALE_S = 30           # book freshness window
TICK = 1.0             # seconds between REST ticks

# candidate exchanges – may not all exist in the local ccxt build
CANDIDATES = [
    "coinbase", "kraken", "gemini", "bitstamp",
    "lmaxdigital", "bullish", "cryptocom",
]
# symbol quirks
SYM = {"kraken": "BTC/USD"}
DEPTH = {"kraken": 500}
DEF_SYM = "BTC/USD"

@dataclass(slots=True)
class Book:
    bids: List[Tuple[float, float]]
    asks: List[Tuple[float, float]]
    ts: int

def now_ms() -> int: return int(time.time()*1000)

def mid(b: Book) -> float: return (b.bids[0][0]+b.asks[0][0])/2

def crossing(b: Book) -> bool: return b.bids[0][0] >= b.asks[0][0]

class BRTI:
    def __init__(self):
        self.ex: Dict[str, "ccxt.Exchange"] = {}
        for eid in CANDIDATES:
            try:
                cls = getattr(ccxt, eid)
                self.ex[eid] = cls()
            except AttributeError:
                print(f"[WARN] ccxt has no exchange id '{eid}' – skipping …")
        self.books: Dict[str, Book] = {}
        if not self.ex:
            raise RuntimeError("No supported exchanges available in this ccxt build.")

    # ------------- data capture -------------
    async def _pull_rest(self, eid: str):
        ex = self.ex[eid]
        sym = SYM.get(eid, DEF_SYM)
        lim = DEPTH.get(eid)
        try:
            ob = await ex.fetch_order_book(sym, limit=lim)
            self.books[eid] = Book(
                [(float(p), float(s)) for p,s,*_ in ob['bids'] if s>0],
                [(float(p), float(s)) for p,s,*_ in ob['asks'] if s>0],
                ob.get('timestamp') or now_ms())
        except Exception as e:
            print(f"[{eid}] REST {e}")

    async def _ws(self, eid: str):
        ex = self.ex[eid]
        sym = SYM.get(eid, DEF_SYM)
        lim = DEPTH.get(eid)
        while True:
            try:
                ob = await ex.watch_order_book(sym, limit=lim)
                self.books[eid] = Book(
                    [(float(p), float(s)) for p,s,*_ in ob['bids'] if s>0],
                    [(float(p), float(s)) for p,s,*_ in ob['asks'] if s>0],
                    ob.get('timestamp') or now_ms())
            except Exception as e:
                print(f"[{eid}] WS {e}")
                await asyncio.sleep(1)

    # ------------- math helpers -------------
    @staticmethod
    def _consol(bks: Dict[str, Book]):
        bmap, amap = defaultdict(float), defaultdict(float)
        for bk in bks.values():
            for p,s in bk.bids: bmap[p]+=s
            for p,s in bk.asks: amap[p]+=s
        bids = sorted(bmap.items(), key=lambda x:-x[0])
        asks = sorted(amap.items(), key=lambda x:x[0])
        return bids, asks

    @staticmethod
    def _cap(bids, asks):
        samp=np.array([s for _,s in bids[:MAX_SAMPLE]]+[s for _,s in asks[:MAX_SAMPLE]])
        if samp.size==0: return 0.
        samp.sort(); k=max(1,int(.01*len(samp)))
        wins=samp.copy(); wins[:k]=wins[k]; wins[-k:]=wins[-k-1]
        return float(wins.mean()+5*wins.std(ddof=1))

    @staticmethod
    def _cum(levels):
        v,p,tot=[],[],0.
        for pr,sz in levels: tot+=sz; v.append(tot); p.append(pr)
        return np.asarray(v),np.asarray(p)

    def _curve(self, vols, prices, grid):
        return np.fromiter((prices[min(bisect.bisect_left(vols,v), len(prices)-1)] for v in grid),float)

    def calc(self):
        fresh={e:b for e,b in self.books.items() if now_ms()-b.ts<=STALE_S*1000 and not crossing(b)}
        if not fresh: return None,[]
        mids=np.array([mid(b) for b in fresh.values()]); med=np.median(mids)
        ok={e:b for e,b in fresh.items() if abs(mid(b)/med-1)<=ERR_BAND}
        if not ok: return None,[]
        bids,asks=self._consol(ok); cap=self._cap(bids,asks)
        if cap==0: return None,[]
        bids=[(p,min(s,cap)) for p,s in bids]; asks=[(p,min(s,cap)) for p,s in asks]
        bv,bp=self._cum(bids); av,ap=self._cum(asks)
        tot=min(bv[-1],av[-1]);
        if tot<SPACING_VOL: return None,[]
        grid=np.arange(SPACING_VOL,tot+SPACING_VOL,SPACING_VOL)
        mc=(self._curve(bv,bp,grid)+self._curve(av,ap,grid))/2
        sc=self._curve(av,ap,grid)/mc-1
        mask=sc<=DEV_MID; depth=grid[mask].max() if mask.any() else SPACING_VOL
        gu=grid[grid<=depth]; mu=mc[grid<=depth]
        lam=1/(0.3*depth); w=lam*np.exp(-lam*gu); w/=w.sum()
        return float((mu*w).sum()),sorted(ok.keys())

    async def run(self):
        if USE_WS:
            for e in self.ex: asyncio.create_task(self._ws(e))
        while True:
            if not USE_WS:
                await asyncio.gather(*[self._pull_rest(e) for e in self.ex])
            idx,ven=self.calc()
            ts=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            if idx is None:
                print(f"[{ts} UTC] BRTI withheld – data")
            else:
                print(f"[{ts} UTC] BRTI {idx:,.2f} USD (from {', '.join(ven)})")
            await asyncio.sleep(TICK)

if __name__=='__main__':
    try:
        asyncio.run(BRTI().run())
    except KeyboardInterrupt:
        print("Stopped.")
