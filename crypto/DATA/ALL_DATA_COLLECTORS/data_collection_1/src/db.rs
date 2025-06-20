use tokio_postgres::{NoTls, Client, Error};
use crate::models::{OrderBookFeatures, AggregatedTrade};

pub async fn connect_db() -> Result<Client, Error> {
    let (client, connection) =
        tokio_postgres::connect("host=localhost user=postgres password=password dbname=chris_db", NoTls).await?;

    tokio::spawn(async move {
        if let Err(e) = connection.await {
            eprintln!("Postgres connection error: {}", e);
        }
    });

    Ok(client)
}

pub async fn insert_orderbook_features_batch(
    client: &Client,
    batch: &[OrderBookFeatures],
) -> Result<u64, Error> {
    if batch.is_empty() {
        return Ok(0);
    }
    let stmt = client.prepare(
        "INSERT INTO binance_orderbook_features (
            timestamp_ms,
            bid_l1_price, bid_l1_cumulative_qty, bid_l1_weighted_price,
            ask_l1_price, ask_l1_cumulative_qty, ask_l1_weighted_price,
            bid_l5_price, bid_l5_cumulative_qty, bid_l5_weighted_price,
            ask_l5_price, ask_l5_cumulative_qty, ask_l5_weighted_price,
            bid_l10_price, bid_l10_cumulative_qty, bid_l10_weighted_price,
            ask_l10_price, ask_l10_cumulative_qty, ask_l10_weighted_price,
            bid_l20_price, bid_l20_cumulative_qty, bid_l20_weighted_price,
            ask_l20_price, ask_l20_cumulative_qty, ask_l20_weighted_price
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25
        ) ON CONFLICT (timestamp_ms) DO UPDATE SET
            bid_l1_price = EXCLUDED.bid_l1_price,
            bid_l1_cumulative_qty = EXCLUDED.bid_l1_cumulative_qty,
            bid_l1_weighted_price = EXCLUDED.bid_l1_weighted_price,
            ask_l1_price = EXCLUDED.ask_l1_price,
            ask_l1_cumulative_qty = EXCLUDED.ask_l1_cumulative_qty,
            ask_l1_weighted_price = EXCLUDED.ask_l1_weighted_price,
            bid_l5_price = EXCLUDED.bid_l5_price,
            bid_l5_cumulative_qty = EXCLUDED.bid_l5_cumulative_qty,
            bid_l5_weighted_price = EXCLUDED.bid_l5_weighted_price,
            ask_l5_price = EXCLUDED.ask_l5_price,
            ask_l5_cumulative_qty = EXCLUDED.ask_l5_cumulative_qty,
            ask_l5_weighted_price = EXCLUDED.ask_l5_weighted_price,
            bid_l10_price = EXCLUDED.bid_l10_price,
            bid_l10_cumulative_qty = EXCLUDED.bid_l10_cumulative_qty,
            bid_l10_weighted_price = EXCLUDED.bid_l10_weighted_price,
            ask_l10_price = EXCLUDED.ask_l10_price,
            ask_l10_cumulative_qty = EXCLUDED.ask_l10_cumulative_qty,
            ask_l10_weighted_price = EXCLUDED.ask_l10_weighted_price,
            bid_l20_price = EXCLUDED.bid_l20_price,
            bid_l20_cumulative_qty = EXCLUDED.bid_l20_cumulative_qty,
            bid_l20_weighted_price = EXCLUDED.bid_l20_weighted_price,
            ask_l20_price = EXCLUDED.ask_l20_price,
            ask_l20_cumulative_qty = EXCLUDED.ask_l20_cumulative_qty,
            ask_l20_weighted_price = EXCLUDED.ask_l20_weighted_price
        "
    ).await?;
    let mut count = 0;
    for ob in batch {
        client.execute(&stmt, &[
            &ob.timestamp_ms,
            &ob.bid_l1_price, &ob.bid_l1_cumulative_qty, &ob.bid_l1_weighted_price,
            &ob.ask_l1_price, &ob.ask_l1_cumulative_qty, &ob.ask_l1_weighted_price,
            &ob.bid_l5_price, &ob.bid_l5_cumulative_qty, &ob.bid_l5_weighted_price,
            &ob.ask_l5_price, &ob.ask_l5_cumulative_qty, &ob.ask_l5_weighted_price,
            &ob.bid_l10_price, &ob.bid_l10_cumulative_qty, &ob.bid_l10_weighted_price,
            &ob.ask_l10_price, &ob.ask_l10_cumulative_qty, &ob.ask_l10_weighted_price,
            &ob.bid_l20_price, &ob.bid_l20_cumulative_qty, &ob.bid_l20_weighted_price,
            &ob.ask_l20_price, &ob.ask_l20_cumulative_qty, &ob.ask_l20_weighted_price
        ]).await?;
        count += 1;
    }
    Ok(count)
}

pub async fn insert_aggregated_trades_batch(
    client: &Client,
    batch: &[AggregatedTrade],
) -> Result<u64, Error> {
    if batch.is_empty() {
        return Ok(0);
    }
    let stmt = client.prepare(
        "INSERT INTO binance_trades (
            timestamp_ms, sell_volume, buy_volume, vwap_sell_price, vwap_buy_price, total_volume, total_trade_count
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7
        ) ON CONFLICT (timestamp_ms) DO UPDATE SET
            sell_volume = EXCLUDED.sell_volume,
            buy_volume = EXCLUDED.buy_volume,
            vwap_sell_price = EXCLUDED.vwap_sell_price,
            vwap_buy_price = EXCLUDED.vwap_buy_price,
            total_volume = EXCLUDED.total_volume,
            total_trade_count = EXCLUDED.total_trade_count
        "
    ).await?;
    let mut count = 0;
    for t in batch {
        client.execute(&stmt, &[&t.timestamp_ms, &t.sell_volume, &t.buy_volume, &t.vwap_sell_price, &t.vwap_buy_price, &t.total_volume, &t.total_trade_count]).await?;
        count += 1;
    }
    Ok(count)
} 