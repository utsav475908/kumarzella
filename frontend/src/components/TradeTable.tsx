import { Link } from "react-router";
import type { Trade } from "../api/schemas";
import { fmtDateTime, fmtDuration, fmtMoney, fmtNum, fmtR, pnlClass } from "../lib/format";
import { Badge } from "./ui";

export function TradeTable({ trades, search = "", compact = false }: { trades: Trade[]; search?: string; compact?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] text-sm">
        <thead className="text-left text-xs text-muted uppercase">
          <tr className="border-b border-line">
            <th className="py-2 pr-3">Date</th>
            {!compact && <th className="pr-3">Account</th>}
            <th className="pr-3">Symbol</th>
            <th className="pr-3">Side</th>
            <th className="pr-3 text-right">Entry</th>
            <th className="pr-3 text-right">Exit</th>
            <th className="pr-3 text-right">Qty</th>
            {!compact && <th className="pr-3 text-right">Gross</th>}
            <th className="pr-3 text-right">Net P&L</th>
            {!compact && <th className="pr-3 text-right">Fees</th>}
            {!compact && <th className="pr-3 text-right">Risk</th>}
            <th className="pr-3 text-right">R</th>
            {!compact && <th className="pr-3">Strategy</th>}
            {!compact && <th className="pr-3">Tags</th>}
            <th className="pr-3 text-right">Held</th>
          </tr>
        </thead>
        <tbody className="num">
          {trades.map((t) => (
            <tr key={t.id} className="border-b border-line/60 hover:bg-panel-2">
              <td className="py-2 pr-3 whitespace-nowrap">
                <Link className="hover:text-accent" to={`/trades/${t.id}${search}`}>{fmtDateTime(t.opened_at)}</Link>
              </td>
              {!compact && <td className="pr-3 text-muted">{t.account_name}</td>}
              <td className="pr-3 font-medium">
                <Link className="hover:text-accent" to={`/trades/${t.id}${search}`}>{t.symbol}</Link>
                {t.status === "open" && <span className="ml-2"><Badge tone="warn">open</Badge></span>}
              </td>
              <td className="pr-3"><Badge tone={t.direction === "long" ? "accent" : "muted"}>{t.direction}</Badge></td>
              <td className="pr-3 text-right">{fmtNum(t.entry_avg_price, 4)}</td>
              <td className="pr-3 text-right">{fmtNum(t.exit_avg_price, 4)}</td>
              <td className="pr-3 text-right">{fmtNum(t.peak_qty, 4)}</td>
              {!compact && <td className={`pr-3 text-right ${pnlClass(t.gross_pnl)}`}>{fmtMoney(t.gross_pnl, t.currency, { sign: true })}</td>}
              <td className={`pr-3 text-right font-semibold ${pnlClass(t.net_pnl)}`}>{fmtMoney(t.net_pnl, t.currency, { sign: true })}</td>
              {!compact && <td className="pr-3 text-right text-muted">{fmtMoney(t.fees, t.currency)}</td>}
              {!compact && <td className="pr-3 text-right text-muted">{fmtMoney(t.initial_risk, t.currency)}</td>}
              <td className={`pr-3 text-right ${pnlClass(t.r_multiple)}`}>{fmtR(t.r_multiple)}</td>
              {!compact && <td className="pr-3 text-muted">{t.playbook_name ?? "—"}</td>}
              {!compact && (
                <td className="pr-3">
                  <div className="flex flex-wrap gap-1">{t.tags.map((g) => <Badge key={g.id} tone={g.category === "mistake" ? "loss" : "muted"}>{g.name}</Badge>)}</div>
                </td>
              )}
              <td className="pr-3 text-right text-muted">{fmtDuration(t.holding_seconds)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
