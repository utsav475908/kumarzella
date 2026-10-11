import type { TradeDetail } from "../api/schemas";
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
    excursions: {
      available: false, trades_with_data: 0, closed_trades: 4, avg_mae: null, avg_mfe: null, avg_mae_r: null,
      avg_mfe_r: null, mfe_capture: null, note: "MAE/MFE come from historical candles.",
    },
    ...over,
  };
}

const leg = (over: Partial<TradeDetail["executions"][number]>) => ({
  execution_id: "e1", executed_at: "2024-01-16T10:00:30Z", side: "buy", quantity: "10000", price: "1.09", commission: "0.5",
  fees: "0", source: "import", source_execution_id: "FX1", role: "open", allocated_quantity: "10000", fees_allocated: "0.5",
  realized_pnl: "0", position_after: "10000", shared_with_other_trade: false, source_ref: null, ...over,
});

export const tradeDetailFixture: TradeDetail = {
  id: "t1", account_id: "a1", account_name: "FX", symbol: "EURUSD", asset_class: "forex", multiplier: "1", direction: "long",
  status: "closed", origin: "imported", currency: "USD", opened_at: "2024-01-16T10:00:30Z", closed_at: "2024-01-16T10:05:20Z",
  session_date: "2024-01-16", entry_session: "regular", entry_qty: "10000", exit_qty: "10000", peak_qty: "10000", open_qty: "0",
  entry_avg_price: "1.09", exit_avg_price: "1.0905", gross_pnl: "5", fees: "1", net_pnl: "4", holding_seconds: 290, execution_count: 2,
  planned_stop_price: null, planned_target_price: null, planned_risk_amount: null, initial_risk: null, r_multiple: null,
  mae: null, mfe: null, playbook_id: null, playbook_name: null, followed_plan: null, rating: null, tags: [], is_demo: false,
  executions: [leg({}), leg({ execution_id: "e2", executed_at: "2024-01-16T10:05:20Z", side: "sell", price: "1.0905", role: "close", position_after: "0" })],
  notes: [], day_note: null, attachments: [], audit: [], prev_trade_id: null, next_trade_id: null, calculation: {},
};
