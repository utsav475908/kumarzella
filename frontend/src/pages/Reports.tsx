import { Link, useNavigate } from "react-router";
import { useReports } from "../api/hooks";
import type { GroupRow, StatRow } from "../api/schemas";
import { AdherenceSummary, Table } from "../components/Adherence";
import { GroupBars } from "../components/charts";
import { FilterBar } from "../components/FilterBar";
import { Empty, ErrorState, Loading, Panel } from "../components/ui";
import { filtersToQuery, filtersToSearch, useFilters } from "../lib/filters";
import { fmtMoney, fmtPct, fmtR, fmtRatio, pnlClass } from "../lib/format";

const asGroup = (r: StatRow & { key: string; label: string }): GroupRow => ({
  key: r.key, label: r.label, trades: r.closed_trades, net_pnl: r.net_pnl, gross_pnl: null, fees: null, wins: r.wins,
  losses: r.losses, win_rate: r.win_rate, profit_factor: r.profit_factor, expectancy: r.expectancy, avg_r: r.avg_r,
});

function monthEnd(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return `${ym}-${String(new Date(Date.UTC(y, m, 0)).getUTCDate()).padStart(2, "0")}`;
}

export function ReportsPage() {
  const [filters] = useFilters();
  const rep = useReports(filtersToQuery(filters));
  const nav = useNavigate();
  const search = filtersToSearch(filters);
  const d = rep.data;
  const c = d?.currency ?? "USD";
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Reports</h1>
      <FilterBar />
      {rep.isLoading && <Loading label="Building reports…" />}
      {rep.isError && <ErrorState error={rep.error} onRetry={() => rep.refetch()} />}
      {d && d.summary.closed_trades === 0 && <Empty title="No closed trades match these filters" />}
      {d && d.summary.closed_trades > 0 && (
        <div className="space-y-4">
          {d.warnings.map((w) => <p key={w} className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-sm">{w}</p>)}
          <Panel title="Strategy comparison">
            <Table head={["Playbook", "Trades", "Net P&L", "Win rate", "Profit factor", "Expectancy", "Avg R", "Avg MAE", "Avg MFE", "Followed rate"]}>
              {d.playbooks.map((p) => (
                <tr key={p.key ?? "none"} className="border-b border-line/60">
                  <td className="py-1.5 pr-3 text-left">
                    <Link className="text-accent hover:underline" to={p.key ? `/playbooks/${p.key}${search}` : `/trades${filtersToSearch({ ...filters, playbook_id: ["none"] })}`}>{p.label}</Link>
                  </td>
                  <td className="pr-3 text-right">{p.closed_trades}</td>
                  <td className={`pr-3 text-right ${pnlClass(p.net_pnl)}`}>{fmtMoney(p.net_pnl, c, { sign: true })}</td>
                  <td className="pr-3 text-right">{fmtPct(p.win_rate)}</td>
                  <td className="pr-3 text-right">{fmtRatio(p.profit_factor)}</td>
                  <td className="pr-3 text-right">{fmtMoney(p.expectancy, c)}</td>
                  <td className="pr-3 text-right">{fmtR(p.avg_r)}</td>
                  <td className="pr-3 text-right" title={`${p.trades_with_excursions} trades with market data`}>{fmtMoney(p.avg_mae, c)}</td>
                  <td className="pr-3 text-right">{fmtMoney(p.avg_mfe, c)}</td>
                  <td className="pr-3 text-right">{p.adherence ? `${fmtPct(p.followed_rate)} (${p.adherence.followed}/${p.adherence.followed + p.adherence.broken})` : "—"}</td>
                </tr>
              ))}
            </Table>
          </Panel>
          <Panel title="Rule adherence"><AdherenceSummary data={d.adherence} currency={c} search={search} /></Panel>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Net P&L by month">
              <GroupBars data={d.by_month.map(asGroup)} currency={c}
                onSelect={(g) => g.key && nav(`/trades${filtersToSearch({ ...filters, date_from: `${g.key}-01`, date_to: monthEnd(g.key) })}`)} />
            </Panel>
            <Panel title="Net P&L by holding time"><GroupBars data={d.by_holding_time.map(asGroup)} currency={c} /></Panel>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="By tag">
              {d.by_tag.length === 0 ? <p className="text-sm text-muted">No tagged trades under these filters.</p> : (
                <>
                  <Table head={["Tag", "Trades", "Net P&L", "Win rate", "Expectancy"]}>
                    {d.by_tag.map((t) => (
                      <tr key={`${t.category}-${t.tag}`} className="border-b border-line/60">
                        <td className="py-1.5 pr-3 text-left">{t.tag}{t.category === "mistake" && <span className="text-xs text-loss"> mistake</span>}</td>
                        <td className="pr-3 text-right">{t.closed_trades}</td>
                        <td className={`pr-3 text-right ${pnlClass(t.net_pnl)}`}>{fmtMoney(t.net_pnl, c, { sign: true })}</td>
                        <td className="pr-3 text-right">{fmtPct(t.win_rate)}</td>
                        <td className="pr-3 text-right">{fmtMoney(t.expectancy, c)}</td>
                      </tr>
                    ))}
                  </Table>
                  <p className="mt-2 text-xs text-muted">A trade with several tags counts under each, so rows don't add up to the total.</p>
                </>
              )}
            </Panel>
            <Panel title="Trading costs by symbol">
              <Table head={["Symbol", "Trades", "Fees", "Fees / gross profit", "Net P&L", "Gross P&L", "Turned negative"]}>
                {d.costs_by_symbol.map((r) => (
                  <tr key={r.symbol} className="border-b border-line/60">
                    <td className="py-1.5 pr-3 text-left">
                      <Link className="text-accent hover:underline" to={`/trades${filtersToSearch({ ...filters, symbol: [r.symbol] })}`}>{r.symbol}</Link>
                    </td>
                    <td className="pr-3 text-right">{r.trades}</td>
                    <td className="pr-3 text-right">{fmtMoney(r.total_fees, c)}</td>
                    <td className="pr-3 text-right">{fmtPct(r.fees_pct_of_gross_profit)}</td>
                    <td className={`pr-3 text-right ${pnlClass(r.net_pnl)}`}>{fmtMoney(r.net_pnl, c, { sign: true })}</td>
                    <td className={`pr-3 text-right ${pnlClass(r.net_without_costs)}`}>{fmtMoney(r.net_without_costs, c, { sign: true })}</td>
                    <td className="pr-3 text-right">{r.trades_turned_negative_by_costs}</td>
                  </tr>
                ))}
              </Table>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
