import clsx from "clsx";
import type { DayRow } from "../api/schemas";
import { fmtMoney, sign } from "../lib/format";

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Lays out server-computed daily P&L on a month grid. No figures are computed here. */
export function MonthCalendar({ month, days, currency, onSelect, compact = false }: { month: string; days: DayRow[]; currency: string; onSelect: (date: string) => void; compact?: boolean }) {
  const [y, m] = month.split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1, 1));
  const daysInMonth = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const lead = (first.getUTCDay() + 6) % 7;
  const byDate = new Map(days.map((d) => [d.date, d]));
  const cells: (number | null)[] = [...Array(lead).fill(null), ...Array.from({ length: daysInMonth }, (_, i) => i + 1)];
  while (cells.length % 7) cells.push(null);

  return (
    <div className="grid grid-cols-7 gap-1 text-xs" role="grid" aria-label={`P&L calendar ${month}`}>
      {DOW.map((d) => (
        <div key={d} className="pb-1 text-center font-medium text-muted">{d}</div>
      ))}
      {cells.map((day, i) => {
        if (day === null) return <div key={`e${i}`} />;
        const iso = `${month}-${String(day).padStart(2, "0")}`;
        const d = byDate.get(iso);
        const s = d ? sign(d.net_pnl) : 0;
        return (
          <button
            key={iso}
            type="button"
            role="gridcell"
            disabled={!d}
            onClick={() => d && onSelect(iso)}
            title={d ? `${iso}: ${fmtMoney(d.net_pnl, currency)} over ${d.trades} trades` : iso}
            className={clsx(
              compact ? "aspect-square" : "min-h-20",
              "flex min-w-0 flex-col justify-between rounded-lg border p-1.5 text-left transition",
              !d && "border-line/50 text-muted/60",
              d && s > 0 && "border-gain/40 bg-gain/15 hover:bg-gain/25",
              d && s < 0 && "border-loss/40 bg-loss/15 hover:bg-loss/25",
              d && s === 0 && "border-line bg-panel-2",
            )}
          >
            <span className="text-muted">{day}</span>
            {d && compact && <span className={clsx("mx-auto h-2 w-2 rounded-full", s > 0 ? "bg-gain" : s < 0 ? "bg-loss" : "bg-muted")} />}
            {d && !compact && (
              <span className="num overflow-hidden">
                <span className={clsx("block truncate font-semibold", s > 0 ? "text-gain" : s < 0 ? "text-loss" : "text-muted")}>
                  {fmtMoney(d.net_pnl, currency, { sign: true })}
                </span>
                <span className="block text-muted">{d.trades} tr</span>
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
