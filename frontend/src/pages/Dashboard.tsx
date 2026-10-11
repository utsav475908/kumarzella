import { Link, useNavigate } from "react-router";
import { useDashboard } from "../api/hooks";
import type { Dashboard as D } from "../api/schemas";
import { DailyPnl, Distribution, EquityCurve, GroupBars } from "../components/charts";
import { FilterBar } from "../components/FilterBar";
import { MonthCalendar } from "../components/MonthCalendar";
import { Empty, ErrorState, Loading, Panel } from "../components/ui";
import { filtersToQuery, filtersToSearch, useFilters, type Filters } from "../lib/filters";
import { fmtDuration, fmtMoney, fmtPct, fmtR, fmtRatio, pnlClass } from "../lib/format";
import { useTrades } from "../api/hooks";
import { TradeTable } from "../components/TradeTable";

function Kpi({ label, value, sub, tone, title }: { label: string; value: string; sub?: string; tone?: string; title?: string }) {
  return (
    <div className="rounded-xl border border-line bg-panel p-4" title={title}>
      <div className="text-xs font-medium tracking-wide text-muted uppercase">{label}</div>
      <div className={`num mt-1 text-2xl font-semibold ${tone ?? ""}`}>{value}</div>
      {sub && <div className="num mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function KpiRow({ d }: { d: D }) {
  const s = d.summary;
  const c = d.currency;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6" data-testid="kpis">
      <Kpi label="Net P&L" value={fmtMoney(s.net_pnl, c, { sign: true })} tone={pnlClass(s.net_pnl)}
        sub={`Gross ${fmtMoney(s.gross_pnl, c)} · fees ${fmtMoney(s.fees, c)}`} title="Gross P&L minus commissions and fees, closed trades only" />
      <Kpi label="Win rate" value={fmtPct(s.win_rate)} sub={`${s.wins}W · ${s.losses}L · ${s.breakevens} BE`} title="Wins / (wins + losses); breakevens excluded" />
      <Kpi label="Profit factor" value={fmtRatio(s.profit_factor)} sub={s.profit_factor_note ?? `Avg win ${fmtMoney(s.avg_win, c)} / loss ${fmtMoney(s.avg_loss, c)}`} title="Gross winning P&L / |gross losing P&L| (net per trade)" />
      <Kpi label="Expectancy" value={fmtMoney(s.expectancy, c, { sign: true })} tone={pnlClass(s.expectancy)} sub={`Avg R ${fmtR(s.avg_r)} (${s.trades_with_r} with risk)`} title="Net P&L per closed trade" />
      <Kpi label="Max drawdown" value={fmtMoney(s.max_drawdown, c)} tone={s.max_drawdown && Number(s.max_drawdown) > 0 ? "text-loss" : ""} sub={`Median trade ${fmtMoney(s.median_trade, c)}`} title="Largest peak-to-trough fall of cumulative net P&L" />
      <Kpi label="Closed trades" value={String(s.closed_trades)} sub={`${s.trading_days} days · ${s.profitable_days} green · avg hold ${fmtDuration(s.avg_holding_seconds)}`} />
    </div>
  );
}

export function DashboardPage() {
  const [filters] = useFilters();
  const q = filtersToQuery(filters);
  const dash = useDashboard(q);
  const recent = useTrades({ ...q, page_size: 8, sort: "closed_at", order: "desc", status: "closed" });
  const nav = useNavigate();
  const toTrades = (extra: Filters) => nav(`/trades${filtersToSearch({ ...filters, ...extra })}`);
  const search = filtersToSearch(filters);

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Performance</h1>
        <Link to="/import" className="text-sm text-accent hover:underline">Import trades</Link>
      </div>
      <FilterBar />
      {dash.isLoading && <Loading label="Calculating performance…" />}
      {dash.isError && <ErrorState error={dash.error} onRetry={() => dash.refetch()} />}
      {dash.data && dash.data.summary.closed_trades === 0 && (
        <Empty title="No closed trades match these filters">
          {Object.keys(filters).length ? "Try clearing filters." : <Link className="text-accent" to="/import">Import your first CSV</Link>}
          {dash.data.open_trades > 0 && <p className="mt-2">{dash.data.open_trades} open trades are not included in performance figures.</p>}
        </Empty>
      )}
      {dash.data && dash.data.summary.closed_trades > 0 && (
        <div className="space-y-4">
          {dash.data.includes_demo_data && (
            <p className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">Includes a demo account with synthetic data.</p>
          )}
          {dash.data.warnings.map((w) => (
            <p key={w} className="text-xs text-muted">⚠ {w}</p>
          ))}
          {dash.data.currencies_available.length > 1 && (
            <p className="text-xs text-muted">Showing {dash.data.currency}. Other currencies: {dash.data.currencies_available.filter((x) => x !== dash.data.currency).join(", ")} (add ?currency=XXX).</p>
          )}
          <KpiRow d={dash.data} />
          <div className="grid gap-4 xl:grid-cols-3">
            <Panel title="Cumulative net P&L" className="xl:col-span-2">
              <EquityCurve data={dash.data.equity_curve} currency={dash.data.currency} onSelect={(id) => nav(`/trades/${id}${search}`)} />
            </Panel>
            <Panel title="Risk and rule adherence"><RiskPanel d={dash.data} search={search} /></Panel>
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            <Panel title="Daily net P&L" className="xl:col-span-2">
              <DailyPnl data={dash.data.daily} currency={dash.data.currency} onSelect={(d) => toTrades({ date_from: d, date_to: d })} />
            </Panel>
            <Panel title="Month" action={<Link className="text-xs text-accent" to={`/calendar${search}`}>Full calendar</Link>}>
              <MonthCalendar month={dash.data.daily[dash.data.daily.length - 1].date.slice(0, 7)} days={dash.data.daily} currency={dash.data.currency}
                onSelect={(d) => toTrades({ date_from: d, date_to: d })} compact />
            </Panel>
          </div>
          <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
            <Panel title="Win / loss distribution">
              <Distribution data={dash.data.distribution} currency={dash.data.currency} onSelect={(from, to) => toTrades({ net_min: from, net_max: to })} />
            </Panel>
            <Panel title="P&L by symbol">
              <GroupBars data={dash.data.by_symbol.slice(0, 10)} currency={dash.data.currency} horizontal height={Math.max(160, dash.data.by_symbol.slice(0, 10).length * 30)}
                onSelect={(g) => toTrades({ symbol: [g.key ?? ""] })} />
            </Panel>
            <Panel title="P&L by strategy">
              <GroupBars data={dash.data.by_playbook} currency={dash.data.currency} horizontal height={Math.max(160, dash.data.by_playbook.length * 34)}
                onSelect={(g) => (g.key ? nav(`/playbooks/${g.key}${search}`) : toTrades({ playbook_id: ["none"] }))} />
            </Panel>
            <Panel title="Performance by entry hour (market time)">
              <GroupBars data={dash.data.by_hour} currency={dash.data.currency} onSelect={(g) => toTrades({ entry_hour: g.key ?? "" })} />
            </Panel>
            <Panel title="By weekday">
              <GroupBars data={dash.data.by_weekday} currency={dash.data.currency} onSelect={(g) => toTrades({ weekday: g.key ?? "" })} />
            </Panel>
            <Panel title="Long vs short">
              <GroupBars data={dash.data.by_direction} currency={dash.data.currency} onSelect={(g) => toTrades({ direction: g.key ?? "" })} />
            </Panel>
          </div>
          <Panel title="Recent trades" action={<Link className="text-xs text-accent" to={`/trades${search}`}>All trades</Link>}>
            {recent.isError ? <ErrorState error={recent.error} /> : recent.data ? <TradeTable trades={recent.data.items} search={search} compact /> : <Loading />}
          </Panel>
          <ExcursionPanel d={dash.data} />
        </div>
      )}
    </div>
  );
}

function RiskPanel({ d, search }: { d: D; search: string }) {
  const r = d.risk;
  const c = d.currency;
  const pa = r.plan_adherence;
  return (
    <div className="space-y-3 text-sm">
      <div className="flex justify-between"><span className="text-muted">Trades with planned risk</span><span className="num">{r.trades_with_planned_risk} ({fmtPct(r.planned_risk_coverage, 0)})</span></div>
      <div className="flex justify-between"><span className="text-muted">Risk-limit violations</span><span className="num">{r.risk_limit_violations.length}</span></div>
      <div className="flex justify-between"><span className="text-muted">Losses beyond planned risk</span><span className="num">{r.losses_beyond_planned_risk.length}</span></div>
      <div className="flex justify-between"><span className="text-muted">Daily loss limit breaches</span><span className="num">{r.daily_loss_limit_breaches.length}</span></div>
      <div className="flex justify-between"><span className="text-muted">Fees / gross profit</span><span className="num">{fmtPct(d.costs.fees_pct_of_gross_profit)}</span></div>
      <div className="border-t border-line pt-3">
        <div className="mb-1 text-xs text-muted uppercase">Followed plan (self-reported)</div>
        {(["followed", "not_followed", "unrated"] as const).map((k) => (
          <div key={k} className="flex justify-between">
            <span className="text-muted">{k.replace("_", " ")}</span>
            <span className="num">{pa[k]?.trades ?? 0} · <span className={pnlClass(pa[k]?.net_pnl)}>{fmtMoney(pa[k]?.net_pnl, c)}</span></span>
          </div>
        ))}
      </div>
      {r.mistakes.length > 0 && (
        <div className="border-t border-line pt-3">
          <div className="mb-1 text-xs text-muted uppercase">Costliest mistakes</div>
          {r.mistakes.slice(0, 4).map((m) => (
            <div key={m.tag} className="flex justify-between"><span>{m.tag}</span><span className={`num ${pnlClass(m.net_pnl)}`}>{fmtMoney(m.net_pnl, c)} ({m.trades})</span></div>
          ))}
        </div>
      )}
      {r.losses_beyond_planned_risk.slice(0, 3).map((x) => (
        <Link key={x.trade_id} to={`/trades/${x.trade_id}${search}`} className="block text-xs text-loss hover:underline">
          {x.symbol}: {fmtR(x.r_multiple)} ({fmtMoney(x.net_pnl, c)})
        </Link>
      ))}
      <p className="text-xs text-muted">{r.note}</p>
    </div>
  );
}

function ExcursionPanel({ d }: { d: D }) {
  const e = d.excursions;
  const c = d.currency;
  return (
    <Panel title="Excursions (MAE / MFE)">
      {e.available ? (
        <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4" data-testid="excursions">
          <div><div className="text-xs text-muted">Avg MAE</div><div className="tabular-nums text-loss">{fmtMoney(e.avg_mae, c)}</div>
            <div className="text-xs text-muted">{fmtR(e.avg_mae_r)}</div></div>
          <div><div className="text-xs text-muted">Avg MFE</div><div className="tabular-nums text-gain">{fmtMoney(e.avg_mfe, c)}</div>
            <div className="text-xs text-muted">{fmtR(e.avg_mfe_r)}</div></div>
          <div><div className="text-xs text-muted">MFE kept</div><div className="tabular-nums">{fmtPct(e.mfe_capture)}</div>
            <div className="text-xs text-muted">net P&L / MFE</div></div>
          <div><div className="text-xs text-muted">Coverage</div><div className="tabular-nums">{e.trades_with_data} / {e.closed_trades}</div>
            <div className="text-xs text-muted">trades with market data</div></div>
        </div>
      ) : (
        <p className="text-sm text-muted">No trades have excursion data yet. Open a forex trade to load its candles.</p>
      )}
      <p className="mt-2 text-xs text-muted">{e.note}</p>
    </Panel>
  );
}
