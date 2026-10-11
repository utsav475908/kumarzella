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
| MAE | Maximum adverse excursion: the lowest open P&L while the trade was open, capped at 0, gross of fees. Open P&L = multiplier × (position × mark − Σ signed fill qty × fill price), which is the same under average-cost and FIFO. Longs are marked at the bid low, shorts at the ask high. Only minutes wholly inside a period of constant position use bar extremes; a minute that contains a fill is evaluated at the fill prices. |
| MFE | Maximum favourable excursion: the highest open P&L while the trade was open, floored at 0. Same rules as MAE, with longs marked at the bid high and shorts at the ask low. |
| MAE and MFE in R | MAE ÷ initial risk and MFE ÷ initial risk, for trades with a known positive risk. |
| MFE kept | Σ net P&L ÷ Σ MFE over trades that have excursion data. |

## Rule adherence

Each trade with a playbook is judged against the playbook version it was pinned to when the playbook was assigned. Two kinds of evidence are kept apart:

| Verified rule (checked from trade data) | Pass when | Unknown when |
|---|---|---|
| Instrument allowed | The symbol is in the version's instrument list (no list = no check). | |
| Session allowed | The entry session (regular or extended hours) is permitted. | |
| Entry time window | The entry hour in market time is in [start, end). A window may wrap past midnight. | |
| Initial stop recorded | A planned stop price or planned risk amount is set. | |
| Risk within limit | Initial risk ≤ the version's max risk per trade. | Initial risk is not known. |
| Planned reward:risk | (target − entry) ÷ (entry − stop), sign-adjusted for shorts and rounded to 0.01, is at least the minimum. A stop or target on the wrong side of the entry fails. | Stop or target missing. |
| Trades per day | The trade's position among the same playbook's trades in the same account on the same session date is within the limit. | |
| Loss within planned risk | Checked when a stop or risk limit is set: R ≥ −1.1 (a little slippage past −1R is tolerated). | Trade still open, or R unknown. |

Checklist items are the trader's own yes/no answers. Answers given against an older version's checklist don't count for a different version.

| Outcome | Rule |
|---|---|
| Broken | Any verified rule failed, or any checklist item was answered "no". |
| Followed | Every verified rule passed and every checklist item was answered "yes". |
| Incomplete | Nothing failed, but a rule is unknown or an item is unanswered. |
| No rules | The version has no checkable limits and no checklist. |

Followed rate = followed ÷ (followed + broken). Incomplete trades are left out. Profitability is never an input.

## Advanced reports

| Report | Definition |
|---|---|
| Strategy comparison | The aggregates above per playbook ("No playbook" included), plus average MAE/MFE over trades with excursion data and the followed rate. |
| Rule results | Per verified rule: passed, failed and unknown counts, and net P&L and average R of the trades that passed and that failed it. |
| Checklist results | Per item: yes, no and unanswered counts, with net P&L for yes and for no. Items keep their id across versions, so a reworded item stays one row. |
| By holding time | Buckets: under 1 min, 1-5 min, 5-15 min, 15-60 min, 1-4 h, 4-24 h, 1-5 days, over 5 days. |
| By month | Grouped by the session date's month. |
| Costs by symbol | Fees, fees as % of gross profit, net and gross P&L, and trades turned negative by costs, per symbol. |

## Regression fixture

`backend/tests/fixtures/fixture_a.csv` is an executions file, and its expected results were computed by hand in `fixture_a_expected.json`:

- net P&L 260.45
- profit factor 2.2894
- win rate 0.75
- max drawdown 202

`tests/test_metrics.py` checks every aggregate above against that file. `tests/test_marketdata.py` checks MAE and MFE against hand-computed cases: a long where the fill minutes hold more extreme prices that must be ignored (MAE −5, MFE 8), a short marked at the ask, and a scale-in. The Playwright journey checks the same numbers in the UI.
