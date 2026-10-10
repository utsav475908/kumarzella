/** Labelled test fixture shaped like the analytics API response. Values are arbitrary test data. */
export function dashboardPayload(over: Record<string, unknown> = {}) {
  const group = (key: string, label: string, net: string) => ({
    key, label, trades: 1, net_pnl: net, gross_pnl: net, fees: "0.00", wins: Number(net) > 0 ? 1 : 0,
    losses: Number(net) < 0 ? 1 : 0, win_rate: "1", profit_factor: null, expectancy: net, avg_r: null,
  });
  return {
    filters: {}, currency: "USD", currencies_available: ["USD"], excluded_other_currency_trades: 0, open_trades: 0,
    includes_demo_data: false, warnings: [],
    summary: {
      closed_trades: 2, wins: 1, losses: 1, breakevens: 0, gross_pnl: "10.00", fees: "1.00", net_pnl: "9.00",
      win_rate: "0.5", profit_factor: "1.9", profit_factor_note: null, expectancy: "4.50", avg_win: "19.00",
      avg_loss: "-10.00", median_trade: "4.50", avg_r: null, trades_with_r: 0, avg_holding_seconds: 60,
      max_drawdown: "10.00", max_consecutive_wins: 1, max_consecutive_losses: 1, trading_days: 2, profitable_days: 1,
      day_win_rate: "0.5", largest_win: "19.00", largest_loss: "-10.00",
    },
    equity_curve: [
      { trade_id: "t1", closed_at: "2024-03-04T15:00:00Z", symbol: "AAA", net_pnl: "19.00", cumulative: "19.00", drawdown: "0.00" },
      { trade_id: "t2", closed_at: "2024-03-05T15:00:00Z", symbol: "BBB", net_pnl: "-10.00", cumulative: "9.00", drawdown: "-10.00" },
    ],
    daily: [
      { date: "2024-03-04", net_pnl: "19.00", gross_pnl: "20.00", fees: "1.00", trades: 1, wins: 1, losses: 0, cumulative: "19.00" },
      { date: "2024-03-05", net_pnl: "-10.00", gross_pnl: "-10.00", fees: "0.00", trades: 1, wins: 0, losses: 1, cumulative: "9.00" },
    ],
    distribution: { bucket_width: "2.42", buckets: [{ from: "-10.00", to: "19.00", count: 2, wins: 1 }] },
    r_distribution: [],
    by_symbol: [group("AAA", "AAA", "19.00"), group("BBB", "BBB", "-10.00")],
    by_playbook: [group("pb1", "ORB", "9.00")],
    by_hour: [group("10", "10:00", "9.00")],
    by_weekday: [group("0", "Monday", "19.00")],
    by_direction: [group("long", "long", "9.00")],
    by_session: [group("regular", "regular", "9.00")],
    costs: { total_fees: "1.00", avg_fees_per_trade: "0.50", fees_pct_of_gross_profit: "0.05", trades_turned_negative_by_costs: 0 },
    risk: {
      trades_with_planned_risk: 0, planned_risk_coverage: "0", risk_limit_violations: [], losses_beyond_planned_risk: [],
      daily_loss_limit_breaches: [], plan_adherence: {}, mistakes: [], note: "Plan adherence is self-reported.",
    },
    mae_mfe: { available: false, reason: "No market data." },
    ...over,
  };
}
