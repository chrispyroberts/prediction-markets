from pydantic import BaseModel
from typing import Dict, List

class FeedDataModel(BaseModel):
    """
    Base class for all feed data models. Extend this for each feed type.
    """
    timestamp: float

class BRTIFeedData(FeedDataModel):
    """
    BRTI feed data model.
    """
    price: float

class BinanceVolSmileData(FeedDataModel):
    """
    Binance volatility smile data model.
    """
    atm_vol: float
    atm_vol_1hr: float
    tte: float
    fitted_params: Dict[str, float]
    moneyness: List[float]
    ivs: List[float]
    # Function parameters for fitted_vol_smile: vol(k) = atm_vol + b*k + c*k^2
    vol_smile_b: float  # b parameter
    vol_smile_c: float  # c parameter
    # Function parameters for sigmoid_0dte_fit: sigmoid(k) = 1/(1 + exp(-k*(x0 - d)))
    sigmoid_x0: float   # x0 parameter
    sigmoid_d: float    # d parameter
    # Array of log(K/S) values for calculating d2 with fitted vol smile
    rev_moneyness: List[float]
    # Actual calculated d2 and binary prices from 0dte fit
    d2_data: List[float]
    binary_price_data: List[float]
    # Fitting parameters for all models (SABR, SVI, Polynomial, Spline)
    fitting_params: Dict[str, Dict[str, float | List[float]]]

class Heartbeat(BaseModel):
    """
    Heartbeat message model for liveness checks.
    Includes the feed name.
    """
    type: str = "heartbeat"
    feed: str
    timestamp: float

class KalshiOrderbookData(FeedDataModel):
    """
    Kalshi orderbook data model.
    """
    ticker: str
    best_bid: float
    best_bid_qty: int
    best_ask: float
    best_ask_qty: int

class KalshiFullOrderbookData(FeedDataModel):
    """
    Kalshi full orderbook data model with complete orderbook state.
    """
    ticker: str
    strike: float
    bids: Dict[str, int]      # price -> quantity (YES side)
    asks: Dict[str, int]      # price -> quantity (NO side converted to YES equivalent)
    best_bid: float
    best_bid_qty: int
    best_ask: float
    best_ask_qty: int
    spread: float
    mid_price: float

class KalshiTradeData(FeedDataModel):
    """
    Kalshi trade data model.
    """
    ticker: str
    yes_price: float
    count: int
    taker_side: str
    trade_value: float

