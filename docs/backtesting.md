# Manual backtesting

A backtest session replays historical candles bar by bar. The trader places simulated orders, and a deterministic simulator fills them. Nothing here touches a broker, and no simulated record is ever mixed with real trades.

Code:

- `backend/app/modules/backtesting/simulator.py` is the simulator. It is pure: no database, no clock, no randomness.
- `backend/app/modules/backtesting/service.py` stores state and runs the simulator over the bars the cursor reveals.
- `backend/app/modules/backtesting/router.py` exposes the API under `/api/v1/backtests`.
- `frontend/src/pages/Backtest.tsx` is the page.

## Sessions

| Setting | Rule |
|---|---|
| Symbol | A forex pair the market-data provider covers (Dukascopy). |
| Timeframe | 1m, 5m, 15m, 30m, 1h or 4h, for display. Fills are always simulated on 1-minute candles. |
| Window | Up to 31 UTC days, ending before today (only completed days are published). |
| Starting balance | In the pair's quote currency (USD for EURUSD, JPY for USDJPY). There is no conversion. |
| Commission | Per side, per 100,000 units of the base currency, in the quote currency. |
| Slippage | In pips, turned into a price amount (1 pip = 0.0001, or 0.01 for JPY pairs). |

The session opens with a warm-up of up to 60 bars, never more than a quarter of the window. After that the blind replay engine reveals bars only up to the cursor. The cursor never moves backwards. A jump forward (`PATCH cursor_at`) still simulates every skipped minute, so orders fill in bars the trader didn't look at.

The exact configuration is stored on the session (`config`), including the simulator version (`sim-1`), so a result can be reproduced later.

## Orders

- **Market:** fills at the open of the first minute at or after the cursor.
- **Limit and stop:** need a price. They wait until their level is reached.
- **Size:** units, or a risk amount. With a risk amount the server works out `floor(risk / |reference − stop| / 1000) × 1000` units. The reference is the order price, or for a market order the last revealed close (ask for buys, bid for sells).
- **Bracket:** an entry can carry a stop-loss and a take-profit. They must be on the correct side of the reference price. When the entry fills, they become two reduce-only orders that cancel each other: when one fills, the other is cancelled.
- **Cancel:** any pending order can be cancelled while the session is active.

## Fill rules (sim-1)

All prices come from 1-minute bid and ask candles. Buys fill on the ask, sells on the bid.

| Order | Triggers when | Fills at |
|---|---|---|
| Market | its first minute | open + slippage against the trader |
| Buy limit L | ask low ≤ L | min(L, ask open). No slippage. |
| Sell limit L | bid high ≥ L | max(L, bid open). No slippage. |
| Buy stop S | ask high ≥ S | max(S, ask open) + slippage |
| Sell stop S | bid low ≤ S | min(S, bid open) − slippage |

So a gap through a level fills at the open, which is worse than the level for a stop and better for a limit.

Orders fill whole. There are no partial fills, because candles carry no order-book depth.

### Order of events inside one minute

A candle says how high and how low price went, but not in which order. The simulator resolves this the same way every time:

1. Orders whose level was already crossed at the open fill first, in placement order.
2. The remaining orders that trigger in the minute fill next, stop-losses first. Assuming the loss came first is the conservative choice.
3. When two or more orders trigger inside the same minute, every fill from that minute is marked **ambiguous**. Ambiguous fills show a "?" on the chart and in the tables, and the results panel counts them.
4. When an entry fills in the middle of a minute, only its stop-loss can also fill in that minute, and that fill is marked ambiguous. Its take-profit waits for the next minute. When the entry filled at the open, both children are live for the whole minute.
5. Reduce-only orders are cancelled as soon as the position they protect is flat or reversed.

Ordering never depends on database ids or wall-clock time. Each order has a rank of (its root entry's placement sequence, kind), so the same orders always resolve the same way.

## Finishing

Finishing cancels all pending orders. If a position is open, it is closed at the last revealed close (bid for a long, ask for a short) with slippage. That fill is stored with kind `finish` and no order. A finished session is read-only.

## Results

Simulated fills go through the same position engine as real executions: average cost, flat-to-flat trades, and commissions allocated to the trade. Metrics come from the analytics module, the same code that computes the real dashboard (see [metrics.md](metrics.md)).

- **R multiple:** net P&L ÷ initial risk, where initial risk = |entry − entry order's stop-loss| × quantity. A trade without a stop has no R.
- **Balance:** starting balance + realized net P&L of closed simulated trades.
- **Return:** realized net P&L ÷ starting balance.
- **Open P&L (gross):** the open quantity marked at the last bid (long) or ask (short), minus its cost. It excludes the commission still to pay on exit.
- **Warnings:** fewer than 30 closed trades is flagged as a small sample. Any ambiguous fill is flagged too.

Every results response carries a disclaimer that a simulation on historical candles is not evidence of future results.

## Reproducibility check

`GET /api/v1/backtests/{id}/verify` (the "Re-run and verify" button) rebuilds the session from scratch. It replays the order log, with each order's placement time and any user cancellation, over the stored candles and compares every resulting fill with the stored fills: order, time, side, quantity, price, commission and the ambiguous flag. It returns `reproducible: true` or lists the mismatches. The test suite tampers with a stored fill and checks that verification catches it.

## Separation from real data

- Simulated orders, fills and trades are stored in `backtest_orders`, `backtest_fills` and `backtest_trades`, never in `executions` or `trades`.
- The journal, dashboard, calendar and reports never read them.
- Every endpoint is scoped to the session's owner. Other users get 404.
- Sessions, orders, fills and trades are included in the user's data export, and are deleted with the session.

## Limitations

- Forex only, and prices are Dukascopy's, not the trader's broker.
- 1-minute granularity: no tick replay, and the order of events within a minute is assumed, not known.
- No partial fills, no order-book depth, and no market impact.
- No swap, financing, margin or leverage checks.
- No currency conversion: balances are in the pair's quote currency.
