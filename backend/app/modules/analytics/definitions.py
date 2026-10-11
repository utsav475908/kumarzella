"""Machine-readable metric definitions served at /api/v1/analytics/definitions (mirrors docs/metrics.md)."""

DEFINITIONS = {
    "gross_pnl": "Sum over closed trades of direction x (exit value - entry value) x multiplier.",
    "fees": "Sum of commissions and fees allocated to closed trades (reversal fills are split pro rata).",
    "net_pnl": "gross_pnl - fees. All reports labelled 'net' use this figure.",
    "win_rate": "wins / (wins + losses). Breakeven trades (net exactly 0) are excluded from both.",
    "profit_factor": "sum of net P&L of winning trades / |sum of net P&L of losing trades|. Null when there are no losses.",
    "expectancy": "net_pnl / number of closed trades (average net outcome per trade, breakevens included).",
    "avg_win": "Mean net P&L of winning trades.",
    "avg_loss": "Mean net P&L of losing trades (negative).",
    "median_trade": "Median of per-trade net P&L.",
    "initial_risk": "Explicit planned risk amount, else |entry avg price - planned stop| x peak quantity x multiplier.",
    "r_multiple": "net P&L / initial risk, closed trades with a known positive risk only.",
    "max_drawdown": "Largest fall of cumulative net P&L from its running peak (peak starts at 0), in trade close order.",
    "equity_curve": "Cumulative net P&L after each closed trade, ordered by close time. Excludes deposits/withdrawals.",
    "consecutive": "Longest runs of wins/losses in close order. A breakeven trade ends a run.",
    "avg_holding_seconds": "Mean of (close time - open time) over closed trades.",
    "profitable_days": "Session dates whose summed net P&L > 0. Session dates follow the instrument's market calendar.",
    "by_hour": "Grouped by the hour of the trade's first fill in the instrument's market timezone.",
    "by_weekday": "Grouped by the weekday of the trade's exit session date.",
    "risk_limit_violations": "Trades whose initial risk exceeded the account's max risk per trade.",
    "losses_beyond_planned_risk": "Closed trades with R < -1 (lost more than planned).",
    "daily_loss_limit_breaches": "Account session dates whose net P&L was below minus the account's daily loss limit.",
    "fees_pct_of_gross_profit": "Total fees / sum of positive gross P&L.",
    "mae": "Maximum adverse excursion: lowest open P&L (realized so far + position marked to market) while the trade "
    "was open, capped at 0, gross of fees. Longs are marked at the bid, shorts at the ask, from 1-minute candles; "
    "minutes that contain a fill are evaluated at fill prices only.",
    "mfe": "Maximum favourable excursion: highest open P&L while the trade was open, floored at 0, same rules as MAE.",
    "mfe_capture": "sum of net P&L / sum of MFE over trades with excursion data: how much of the best open profit "
    "was kept.",
}
