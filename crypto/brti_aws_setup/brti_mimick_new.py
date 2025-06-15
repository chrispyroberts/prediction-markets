import asyncio, bisect, time, os, logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple
import numpy as np
import psycopg2
from psycopg2 import OperationalError
from pytz import timezone
from dotenv import load_dotenv

# === Load env for DB creds ===
load_dotenv()
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "brti")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))

# === Setup logging to file and console ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("brti_calc.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

est = timezone('US/Eastern')
conn = None

def connect_to_db():
    global conn
    while True:
        try:
            logger.info("📡 Attempting PostgreSQL connection...")
            conn = psycopg2.connect(
                host=DB_HOST,
                dbname=DB_NAME,
                user=DB_USER,
                port=DB_PORT
            )
            conn.autocommit = True
            logger.info("✅ Connected to PostgreSQL.")
            break
        except OperationalError as e:
            logger.warning(f"⏳ PostgreSQL connection failed. Retrying in 5s... Error: {e}")
            time.sleep(5)

def insert_to_db(price: float, timestamp: datetime):
    global conn
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO brti_prices (price, timestamp) VALUES (%s, %s)",
                (float(price), timestamp)
            )
    except (Exception, OperationalError) as e:
        logger.error(f"❌ Database insert error: {e}")
        connect_to_db()

# === Choose ccxt backend ===
try:
    import ccxt.pro as ccxt
    USE_WS = True
    logger.info("[INIT] ccxt.pro detected – WebSocket mode ✔︎")
except ImportError:
    import ccxt.async_support as ccxt
    USE_WS = False
    logger.info("[INIT] ccxt.pro not found – REST mode …")

# === Method constants ===
SPACING_VOL = 1
DEV_MID = 0.005
ERR_BAND = 0.05
MAX_SAMPLE = 50
STALE_S = 30
TICK = 1.0

CANDIDATES = [
    "coinbase", "kraken", "gemini", "bitstamp",
    "lmaxdigital", "bullish", "cryptocom",
]
SYM = {"kraken": "BTC/USD"}
DEPTH = {"kraken": 500}
DEF_SYM = "BTC/USD"

@dataclass(slots=True)
class Book:
    bids: List[Tuple[float, float]]
    asks: List[Tuple[float, float]]
    ts: int

def now_ms() -> int: return int(time.time() * 1000)
def mid(b: Book) -> float: return (b.bids[0][0] + b.asks[0][0]) / 2
def crossing(b: Book) -> bool: return b.bids[0][0] >= b.asks[0][0]

class BRTI:
    def __init__(self):
        connect_to_db()
        self.ex: Dict[str, "ccxt.Exchange"] = {}
        for eid in CANDIDATES:
            try:
                cls = getattr(ccxt, eid)
                self.ex[eid] = cls()
            except AttributeError:
                logger.warning(f"[WARN] ccxt has no exchange id '{eid}' – skipping …")
        self.books: Dict[str, Book] = {}
        if not self.ex:
            raise RuntimeError("No supported exchanges available in this ccxt build.")

    async def _pull_rest(self, eid: str):
        ex = self.ex[eid]
        sym = SYM.get(eid, DEF_SYM)
        lim = DEPTH.get(eid)
        try:
            ob = await ex.fetch_order_book(sym, limit=lim)
            self.books[eid] = Book(
                [(float(p), float(s)) for p, s, *_ in ob['bids'] if s > 0],
                [(float(p), float(s)) for p, s, *_ in ob['asks'] if s > 0],
                ob.get('timestamp') or now_ms())
        except Exception as e:
            logger.warning(f"[{eid}] REST error: {e}")

    async def _ws(self, eid: str):
        ex = self.ex[eid]
        sym = SYM.get(eid, DEF_SYM)
        lim = DEPTH.get(eid)
        while True:
            try:
                ob = await ex.watch_order_book(sym, limit=lim)
                self.books[eid] = Book(
                    [(float(p), float(s)) for p, s, *_ in ob['bids'] if s > 0],
                    [(float(p), float(s)) for p, s, *_ in ob['asks'] if s > 0],
                    ob.get('timestamp') or now_ms())
            except Exception as e:
                logger.warning(f"[{eid}] WS error: {e}")
                await asyncio.sleep(1)

    @staticmethod
    def _consol(bks: Dict[str, Book]):
        bmap, amap = defaultdict(float), defaultdict(float)
        for bk in bks.values():
            for p, s in bk.bids: bmap[p] += s
            for p, s in bk.asks: amap[p] += s
        bids = sorted(bmap.items(), key=lambda x: -x[0])
        asks = sorted(amap.items(), key=lambda x: x[0])
        return bids, asks

    @staticmethod
    def _cap(bids, asks):
        samp = np.array([s for _, s in bids[:MAX_SAMPLE]] + [s for _, s in asks[:MAX_SAMPLE]])
        if samp.size == 0: return 0.
        samp.sort(); k = max(1, int(.01 * len(samp)))
        wins = samp.copy(); wins[:k] = wins[k]; wins[-k:] = wins[-k - 1]
        return float(wins.mean() + 5 * wins.std(ddof=1))

    @staticmethod
    def _cum(levels):
        v, p, tot = [], [], 0.
        for pr, sz in levels:
            tot += sz; v.append(tot); p.append(pr)
        return np.asarray(v), np.asarray(p)

    def _curve(self, vols, prices, grid):
        return np.fromiter((prices[min(bisect.bisect_left(vols, v), len(prices) - 1)] for v in grid), float)

    def calc(self):
        fresh = {e: b for e, b in self.books.items() if now_ms() - b.ts <= STALE_S * 1000 and not crossing(b)}
        if not fresh: return None, []
        mids = np.array([mid(b) for b in fresh.values()])
        med = np.median(mids)
        ok = {e: b for e, b in fresh.items() if abs(mid(b) / med - 1) <= ERR_BAND}
        if not ok: return None, []
        bids, asks = self._consol(ok)
        cap = self._cap(bids, asks)
        if cap == 0: return None, []
        bids = [(p, min(s, cap)) for p, s in bids]
        asks = [(p, min(s, cap)) for p, s in asks]
        bv, bp = self._cum(bids)
        av, ap = self._cum(asks)
        tot = min(bv[-1], av[-1])
        if tot < SPACING_VOL: return None, []
        grid = np.arange(SPACING_VOL, tot + SPACING_VOL, SPACING_VOL)
        mc = (self._curve(bv, bp, grid) + self._curve(av, ap, grid)) / 2
        sc = self._curve(av, ap, grid) / mc - 1
        mask = sc <= DEV_MID
        depth = grid[mask].max() if mask.any() else SPACING_VOL
        gu = grid[grid <= depth]
        mu = mc[grid <= depth]
        lam = 1 / (0.3 * depth)
        w = lam * np.exp(-lam * gu)
        w /= w.sum()
        return float((mu * w).sum()), sorted(ok.keys())

    async def run(self):
        if USE_WS:
            for e in self.ex:
                asyncio.create_task(self._ws(e))

        while True:
            if not USE_WS:
                await asyncio.gather(*[self._pull_rest(e) for e in self.ex])
            idx, ven = self.calc()
            ts = datetime.now(est)
            ts_str = ts.strftime('%Y-%m-%d %H:%M:%S')
            if idx is None:
                logger.info(f"[{ts_str} EST] BRTI withheld – data")
            else:
                logger.info(f"[{ts_str} EST] BRTI {idx:,.2f} USD (from {', '.join(ven)})")
                insert_to_db(idx, ts)
            await asyncio.sleep(TICK)

if __name__ == '__main__':
    try:
        asyncio.run(BRTI().run())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
