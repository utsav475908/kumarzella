import { useNavigate, useSearchParams } from "react-router";
import { useCalendar } from "../api/hooks";
import { FilterBar } from "../components/FilterBar";
import { MonthCalendar } from "../components/MonthCalendar";
import { Button, ErrorState, Loading, Panel } from "../components/ui";
import { filtersToQuery, filtersToSearch, useFilters } from "../lib/filters";
import { fmtMoney, pnlClass } from "../lib/format";

function shift(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function CalendarPage() {
  const [filters] = useFilters();
  const [sp, setSp] = useSearchParams();
  const now = new Date();
  const month = sp.get("month") ?? `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const { date_from: _f, date_to: _t, ...rest } = filters;
  const cal = useCalendar({ ...filtersToQuery(rest), month: `${month}-01` });
  const nav = useNavigate();
  const go = (m: string) => { const n = new URLSearchParams(sp); n.set("month", m); setSp(n); };

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">P&L calendar</h1>
      <FilterBar />
      <Panel
        title={month}
        action={
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => go(shift(month, -1))} aria-label="Previous month">‹</Button>
            <Button variant="ghost" onClick={() => go(shift(month, 1))} aria-label="Next month">›</Button>
          </div>
        }
      >
        {cal.isLoading && <Loading />}
        {cal.isError && <ErrorState error={cal.error} onRetry={() => cal.refetch()} />}
        {cal.data && (
          <>
            <div className="mb-3 flex gap-6 text-sm">
              <span>Month net: <b className={pnlClass(cal.data.summary.net_pnl)}>{fmtMoney(cal.data.summary.net_pnl, cal.data.currency, { sign: true })}</b></span>
              <span className="text-muted">{cal.data.summary.trading_days} trading days · {cal.data.summary.profitable_days} green</span>
            </div>
            <MonthCalendar month={month} days={cal.data.days} currency={cal.data.currency}
              onSelect={(d) => nav(`/trades${filtersToSearch({ ...rest, date_from: d, date_to: d })}`)} />
            {cal.data.weeks.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-3 text-xs">
                {cal.data.weeks.map((w) => (
                  <span key={w.iso_week} className="rounded-lg border border-line px-2 py-1">
                    Week {w.iso_week}: <span className={pnlClass(w.net_pnl)}>{fmtMoney(w.net_pnl, cal.data.currency, { sign: true })}</span> ({w.trades} trades)
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </Panel>
    </div>
  );
}
