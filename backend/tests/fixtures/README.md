# Financial regression fixtures

These files are independent, hand-computed test fixtures. They are **synthetic**: the symbols are real tickers
but the fills never happened. They exist only to pin down the reconstruction and metric formulas.

## fixture_a.csv (generic preset, timestamps naive in America/New_York)

| Trade | Fills | Entry value | Exit value | Gross | Fees | Net |
|---|---|---|---|---|---|---|
| AAPL long | A1 buy 100@170, A2 buy 100@171, A3 sell 150@172, A4 sell 50@169 | 34,100 | 34,250 | 150 | 1+1+1.60+0.55 = 4.15 | 145.85 |
| TSLA short | T1 sell 50@200, T2 buy 50@204 | 10,000 | 10,200 | -200 | 2 | -202 |
| ES long (x50) | E1 buy 1@5100, first half of E2 sell 2@5104 | 5,100 | 5,104 | 4 x 50 = 200 | 2.10 + 2.10 | 195.80 |
| ES short (x50) | second half of E2, E3 buy 1@5101.50 | 5,104 | 5,101.50 | 2.5 x 50 = 125 | 2.10 + 2.10 | 120.80 |
| MSFT long | M1 buy 10@400, still open | | | 0 realized | 0 | 0 (excluded from closed metrics) |
| NVDA long | N1 buy 10@800, N2 sell 10@800 | 8,000 | 8,000 | 0 | 0 | 0 (breakeven) |

Row 11 is rejected (`quantity: 'abc'`), row 12 repeats execution id A1 and is flagged duplicate.

Aggregates over the 5 closed trades: net 260.45; wins 3, losses 1, breakeven 1; win rate 3/4 = 0.75
(breakevens excluded); profit factor 462.45 / 202 = 2.2894; expectancy 260.45 / 5 = 52.09; median 120.80.
Equity by close time: 145.85, -56.15, 139.65, 260.45, 260.45 so max drawdown = 145.85 - (-56.15) = 202.
