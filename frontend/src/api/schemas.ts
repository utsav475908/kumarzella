import { z } from "zod";

/** Money and quantities are decimal strings from the API. They are formatted for display, never re-computed. */
const money = z.string();
const moneyN = z.string().nullable();

export const user = z.object({
  id: z.string(),
  email: z.string(),
  display_name: z.string(),
  role: z.string(),
  timezone: z.string(),
});
export type User = z.infer<typeof user>;

export const account = z.object({
  id: z.string(),
  name: z.string(),
  broker: z.string().nullable(),
  account_type: z.string(),
  base_currency: z.string(),
  timezone: z.string(),
  accounting_policy: z.string(),
  starting_balance: moneyN,
  max_risk_per_trade: moneyN,
  daily_loss_limit: moneyN,
  is_demo: z.boolean(),
  archived_at: z.string().nullable(),
});
export type Account = z.infer<typeof account>;

export const tagRef = z.object({ id: z.string(), name: z.string(), category: z.string(), color: z.string().nullable().optional() });
export const tag = tagRef.extend({ trade_count: z.number() });
export type Tag = z.infer<typeof tag>;

export const playbook = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  current_version: z.number(),
  archived_at: z.string().nullable(),
});
export type Playbook = z.infer<typeof playbook>;

export const trade = z.object({
  id: z.string(),
  account_id: z.string(),
  account_name: z.string(),
  symbol: z.string(),
  asset_class: z.string(),
  multiplier: money,
  direction: z.enum(["long", "short"]),
  status: z.enum(["open", "closed"]),
  origin: z.string(),
  currency: z.string(),
  opened_at: z.string(),
  closed_at: z.string().nullable(),
  session_date: z.string(),
  entry_session: z.string(),
  entry_qty: money,
  exit_qty: money,
  peak_qty: money,
  open_qty: money,
  entry_avg_price: money,
  exit_avg_price: moneyN,
  gross_pnl: money,
  fees: money,
  net_pnl: money,
  holding_seconds: z.number().nullable(),
  execution_count: z.number(),
  planned_stop_price: moneyN,
  planned_target_price: moneyN,
  planned_risk_amount: moneyN,
  initial_risk: moneyN,
  r_multiple: moneyN,
  mae: moneyN.optional(),
  mfe: moneyN.optional(),
  playbook_id: z.string().nullable(),
  playbook_name: z.string().nullable(),
  followed_plan: z.boolean().nullable(),
  rating: z.number().nullable(),
  tags: z.array(tagRef),
  is_demo: z.boolean(),
});
export type Trade = z.infer<typeof trade>;

export const page = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ items: z.array(item), total: z.number(), page: z.number(), page_size: z.number() });

export const executionLeg = z.object({
  execution_id: z.string(),
  executed_at: z.string(),
  side: z.string(),
  quantity: money,
  price: money,
  commission: money,
  fees: money,
  source: z.string(),
  source_execution_id: z.string().nullable(),
  role: z.string(),
  allocated_quantity: money,
  fees_allocated: money,
  realized_pnl: money,
  position_after: money,
  shared_with_other_trade: z.boolean(),
  source_ref: z
    .object({
      import_job_id: z.string().nullable(),
      filename: z.string().nullable(),
      row_number: z.number().nullable(),
      raw: z.record(z.string(), z.unknown()).nullable(),
    })
    .nullable(),
});
export type ExecutionLeg = z.infer<typeof executionLeg>;

export const note = z.object({ id: z.string(), body: z.string(), created_at: z.string(), updated_at: z.string() });
export const attachment = z.object({
  id: z.string(),
  filename: z.string(),
  content_type: z.string(),
  size_bytes: z.number(),
  created_at: z.string(),
});
export const tradeDetail = trade.extend({
  executions: z.array(executionLeg),
  notes: z.array(note),
  day_note: z.string().nullable(),
  attachments: z.array(attachment),
  audit: z.array(z.object({ id: z.string(), action: z.string(), data: z.record(z.string(), z.unknown()).nullable(), created_at: z.string() })),
  prev_trade_id: z.string().nullable(),
  next_trade_id: z.string().nullable(),
  calculation: z.record(z.string(), z.string()),
});
export type TradeDetail = z.infer<typeof tradeDetail>;

export const importJob = z.object({
  id: z.string(),
  account_id: z.string(),
  filename: z.string(),
  file_size: z.number(),
  status: z.string(),
  headers: z.array(z.string()),
  mapping: z.record(z.string(), z.unknown()).nullable(),
  total_rows: z.number(),
  valid_rows: z.number(),
  rejected_rows: z.number(),
  duplicate_rows: z.number(),
  imported_rows: z.number(),
  error_message: z.string().nullable(),
  summary: z.record(z.string(), z.unknown()).nullable(),
  created_at: z.string(),
  committed_at: z.string().nullable(),
});
export type ImportJob = z.infer<typeof importJob>;
export const uploadOut = importJob.extend({
  suggested_mapping: z.record(z.string(), z.string()),
  detected_preset: z.string().nullable(),
  sample_rows: z.array(z.record(z.string(), z.string())),
});
export type UploadOut = z.infer<typeof uploadOut>;
export const rawRecord = z.object({
  id: z.string(),
  row_number: z.number(),
  raw: z.record(z.string(), z.string()),
  normalized: z.record(z.string(), z.unknown()).nullable(),
  status: z.string(),
  errors: z.array(z.string()),
  warnings: z.array(z.string()),
  duplicate_of_execution_id: z.string().nullable(),
});
export type RawRecord = z.infer<typeof rawRecord>;
export const previewOut = z.object({ job: importJob, rows: z.array(rawRecord) });
export const preset = z.object({
  key: z.string(),
  name: z.string(),
  description: z.string(),
  mapping: z.record(z.string(), z.string()),
  options: z.record(z.string(), z.unknown()),
});
export type Preset = z.infer<typeof preset>;

const groupRow = z.object({
  key: z.string().nullable(),
  label: z.string(),
  trades: z.number(),
  net_pnl: moneyN,
  gross_pnl: moneyN,
  fees: moneyN,
  wins: z.number(),
  losses: z.number(),
  win_rate: moneyN,
  profit_factor: moneyN,
  expectancy: moneyN,
  avg_r: moneyN,
});
export type GroupRow = z.infer<typeof groupRow>;

export const dayRow = z.object({
  date: z.string(),
  net_pnl: money,
  gross_pnl: money,
  fees: money,
  trades: z.number(),
  wins: z.number(),
  losses: z.number(),
  cumulative: money,
});
export type DayRow = z.infer<typeof dayRow>;

export const dashboard = z.object({
  filters: z.record(z.string(), z.unknown()),
  currency: z.string(),
  currencies_available: z.array(z.string()),
  excluded_other_currency_trades: z.number(),
  open_trades: z.number(),
  includes_demo_data: z.boolean(),
  warnings: z.array(z.string()),
  summary: z.object({
    closed_trades: z.number(),
    wins: z.number(),
    losses: z.number(),
    breakevens: z.number(),
    gross_pnl: moneyN,
    fees: moneyN,
    net_pnl: moneyN,
    win_rate: moneyN,
    profit_factor: moneyN,
    profit_factor_note: z.string().nullable(),
    expectancy: moneyN,
    avg_win: moneyN,
    avg_loss: moneyN,
    median_trade: moneyN,
    avg_r: moneyN,
    trades_with_r: z.number(),
    avg_holding_seconds: z.number().nullable(),
    max_drawdown: moneyN,
    max_consecutive_wins: z.number(),
    max_consecutive_losses: z.number(),
    trading_days: z.number(),
    profitable_days: z.number(),
    day_win_rate: moneyN,
    largest_win: moneyN,
    largest_loss: moneyN,
  }),
  equity_curve: z.array(
    z.object({ trade_id: z.string(), closed_at: z.string(), symbol: z.string(), net_pnl: money, cumulative: money, drawdown: money }),
  ),
  daily: z.array(dayRow),
  distribution: z.object({
    bucket_width: moneyN,
    buckets: z.array(z.object({ from: money, to: money, count: z.number(), wins: z.number() })),
  }),
  r_distribution: z.array(z.object({ label: z.string(), count: z.number() })),
  by_symbol: z.array(groupRow),
  by_playbook: z.array(groupRow),
  by_hour: z.array(groupRow),
  by_weekday: z.array(groupRow),
  by_direction: z.array(groupRow),
  by_session: z.array(groupRow),
  costs: z.object({
    total_fees: moneyN,
    avg_fees_per_trade: moneyN,
    fees_pct_of_gross_profit: moneyN,
    trades_turned_negative_by_costs: z.number(),
  }),
  risk: z.object({
    trades_with_planned_risk: z.number(),
    planned_risk_coverage: moneyN,
    risk_limit_violations: z.array(z.object({ trade_id: z.string(), symbol: z.string(), initial_risk: moneyN, limit: moneyN })),
    losses_beyond_planned_risk: z.array(z.object({ trade_id: z.string(), symbol: z.string(), r_multiple: moneyN, net_pnl: moneyN })),
    daily_loss_limit_breaches: z.array(z.object({ account_id: z.string(), date: z.string(), net_pnl: moneyN, limit: moneyN })),
    plan_adherence: z.record(z.string(), z.object({ trades: z.number(), net_pnl: moneyN, win_rate: moneyN })),
    mistakes: z.array(z.object({ tag: z.string(), trades: z.number(), net_pnl: moneyN })),
    note: z.string(),
  }),
  excursions: z.object({
    available: z.boolean(),
    trades_with_data: z.number(),
    closed_trades: z.number(),
    avg_mae: moneyN,
    avg_mfe: moneyN,
    avg_mae_r: moneyN,
    avg_mfe_r: moneyN,
    mfe_capture: moneyN,
    note: z.string(),
  }),
});
export type Dashboard = z.infer<typeof dashboard>;

export const calendar = z.object({
  month: z.string(),
  currency: z.string(),
  days: z.array(dayRow),
  weeks: z.array(z.object({ iso_week: z.number(), net_pnl: money, trades: z.number(), days: z.number() })),
  summary: z.object({ net_pnl: money, trading_days: z.number(), profitable_days: z.number() }).passthrough(),
});
export type Calendar = z.infer<typeof calendar>;

// ---------------------------------------------------------------- market data and replay

export const providerInfo = z.object({
  name: z.string(),
  display_name: z.string(),
  asset_classes: z.array(z.string()),
  granularity: z.string(),
  sides: z.array(z.string()),
  attribution: z.string(),
  licence_note: z.string(),
  volume_note: z.string(),
});
export type ProviderInfo = z.infer<typeof providerInfo>;

export const marketDataInfo = z.object({
  enabled: z.boolean(),
  provider: providerInfo.nullable(),
  timeframes: z.array(z.string()),
  symbols: z.array(z.string()).optional(),
});

/** One candle. t is the bar open in UNIX seconds (UTC); prices are decimal strings. */
export const bar = z.object({ t: z.number(), o: money, h: money, l: money, c: money, v: money });
export type Bar = z.infer<typeof bar>;

export const fillMarker = z.object({ t: z.number(), ts: z.string(), side: z.enum(["buy", "sell"]), quantity: money, price: money });
export type FillMarker = z.infer<typeof fillMarker>;

export const coverage = z.object({
  status: z.string(),
  pending_days: z.array(z.string()),
  failed_days: z.array(z.object({ day: z.string(), error: z.string() })),
  unpublished_days: z.array(z.string()),
});

export const chartStatus = z.enum(["ready", "pending", "partial", "unavailable", "unsupported"]);

export const tradeChart = z.object({
  status: chartStatus,
  reason: z.string().optional(),
  provider: providerInfo.nullable(),
  symbol: z.string().optional(),
  timeframe: z.string().optional(),
  side: z.string().optional(),
  coverage: coverage.optional(),
  bars: z.array(bar),
  gaps: z.array(z.object({ start: z.string(), end: z.string(), minutes: z.number() })).optional(),
  markers: z.array(fillMarker),
  planned_stop_price: moneyN.optional(),
  planned_target_price: moneyN.optional(),
  excursions: z
    .object({
      mae: money,
      mfe: money,
      source: z.string().nullable(),
      computed_at: z.string().nullable(),
      r: z.object({ mae_r: money, mfe_r: money }).nullable(),
      precision: z.string(),
      mae_at: z.string().optional(),
      mfe_at: z.string().optional(),
      minutes_missing: z.number().optional(),
    })
    .nullable()
    .optional(),
  notes: z.array(z.string()).optional(),
});
export type TradeChart = z.infer<typeof tradeChart>;

export const replaySession = z.object({
  id: z.string(),
  mode: z.enum(["review", "blind"]),
  trade_id: z.string().nullable(),
  title: z.string(),
  provider: z.string(),
  symbol: z.string(),
  timeframe: z.string(),
  side: z.string(),
  start_at: z.string(),
  end_at: z.string(),
  cursor_at: z.string(),
  speed: z.number(),
  completed: z.boolean(),
  progress: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type ReplaySession = z.infer<typeof replaySession>;

export const replayBars = replaySession.extend({
  status: chartStatus,
  coverage,
  provider: providerInfo,
  bars: z.array(bar),
  markers: z.array(fillMarker),
  overlay: z
    .object({
      planned_stop_price: moneyN,
      planned_target_price: moneyN,
      entry_avg_price: moneyN,
      exit_avg_price: moneyN,
      playbook: z.string().nullable(),
      direction: z.string(),
    })
    .nullable(),
});
export type ReplayBars = z.infer<typeof replayBars>;

export const replayAdvance = replaySession.extend({ bars: z.array(bar) });
export type ReplayAdvance = z.infer<typeof replayAdvance>;

export const annotation = z.object({
  id: z.string(),
  bar_time: z.string(),
  t: z.number(),
  price: moneyN,
  text: z.string(),
  created_at: z.string(),
});
export type Annotation = z.infer<typeof annotation>;
