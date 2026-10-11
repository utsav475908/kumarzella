# Metric definitions

Every financial figure in EdgeLedger is computed in the backend, by `app/modules/analytics` (`formulas.py` handles per-trade figures and `metrics.py` handles aggregates). The frontend only formats the strings it receives. The same definitions are served at `GET /api/v1/analytics/definitions`. If you change a formula, update this file, that endpoint, and the regression fixtures in `backend/tests/fixtures/` together.

## Conventions

- **Arithmetic** is Python `Decimal`, never float.
- **Storage precision:**
  - Amounts are stored at 8 decimal places, and prices at 10.
  - Fee splits use `split_proportionally`, so the parts always sum exactly to the original fee.
- **Display rounding:**
  - Aggregate money figures are quantized to 0.01.
  - Ratios and R-multiples are quantized to 0.0001.
  - Rounding is banker's rounding (half-even).
- **Currencies:** metrics are grouped per account currency. Amounts in different currencies are never added together or converted.
- **Which trades count:** only closed trades enter P&L metrics. Open trades appear in the trade list, with partial realized P&L shown separately.
- **Ordering:** "close order" means sorting by `(closed_at, opened_at, id)`.
- **Missing values:** a metric whose denominator is zero, or whose inputs are unknown, is `null`. It is never 0.

## Trade construction

- **What a trade is:** a position from flat back to flat, per account and instrument. A fill that crosses zero (a reversal) is split in two. One part closes the old trade and the remainder opens the new one, and the fill's fees are split pro rata by quantity.
- **Multiplier:**
  - Futures: by root symbol (for example ES = 50, NQ = 20, CL = 1000).
  - Options: 100, parsed from OCC symbols.
  - Stocks, ETFs, crypto and forex units: 1.
- **Gross P&L** = direction × (exit value − entry value) × multiplier. The direction factor is +1 for a long and −1 for a short.
- **Net P&L** = gross P&L − fees. Every report labelled "net" uses this figure.
- **Partial realized P&L** on open trades depends on the account's lot policy: `average_cost` (the default) or `fifo`. Closed-trade P&L is identical under both policies.
- **Forex P&L** is in the pair's quote currency.

## Per-trade

| Metric | Definition |
|---|---|
| Outcome | Win if net > 0, loss if net < 0, breakeven if net = 0 exactly. |
| Initial risk | The explicit planned risk amount if one was entered. Otherwise \|entry avg price − planned stop\| × peak quantity × multiplier, but only when the stop is on the losing side of the entry. Otherwise unknown. |
| R-multiple | net P&L ÷ initial risk, for closed trades with a known positive risk only. |
| Holding time | close time − open time. |
| Entry hour | The hour of the first fill, in the instrument's market timezone. |
| Session date | The trading date in the market calendar. US equities use the New York date. CME futures and forex roll at 17:00 in Chicago and New York respectively, and a weekend roll moves to Monday. |
| Session | Regular hours or extended hours, judged from the first fill in market time. |

## Aggregates

| Metric | Definition |
|---|---|
| Net P&L, gross P&L, fees | Sums over closed trades. |
| Win rate | wins ÷ (wins + losses). Breakevens are excluded from both. |
| Profit factor | sum of winning net P&L ÷ \|sum of losing net P&L\|. `null` when there are no losses. |
| Expectancy | net P&L ÷ number of closed trades, breakevens included. |
| Average win and average loss | The mean net P&L of winners, and of losers (the loss average is negative). |
| Median trade | The median of per-trade net P&L. |
| Average R and total R | Over trades that have an R-multiple. |
| Equity curve | Cumulative net P&L after each closed trade, in close order. Deposits and withdrawals are excluded. |
| Max drawdown | The largest fall of the equity curve from its running peak. The peak starts at 0, so a losing first trade is a drawdown. |
| Consecutive wins and losses | The longest runs in close order. A breakeven trade ends a run. |
| Daily P&L, profitable days | Net P&L summed per session date. A profitable day has a total above 0. |
| By hour, weekday, symbol, tag, playbook | The same aggregates within each group. Hour is the entry hour. Weekday is that of the exit session date. A trade with several tags counts once in each of its tags. |
| Fees as % of gross profit | total fees ÷ sum of positive gross P&L. |
| Risk-limit violations | Trades whose initial risk exceeded the account's max risk per trade. |
| Losses beyond planned risk | Closed trades with R < −1. |
| Daily loss-limit breaches | Session dates where the account's net P&L fell below minus its daily loss limit. |
| MAE and MFE | Not computed yet. They need historical market data (Phase 5). |

## Regression fixture

`backend/tests/fixtures/fixture_a.csv` is an executions file, and its expected results were computed by hand in `fixture_a_expected.json`:

- net P&L 260.45
- profit factor 2.2894
- win rate 0.75
- max drawdown 202

`tests/test_metrics.py` checks every aggregate above against that file. The Playwright journey checks the same numbers in the UI.
