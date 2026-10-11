import { Link } from "react-router";
import { useSaveChecklist, useTradeAdherence } from "../api/hooks";
import type { AdherenceBlock, Assessment, Outcome, TradeDetail } from "../api/schemas";
import { fmtDateTime, fmtMoney, fmtPct, fmtR, pnlClass } from "../lib/format";
import { Badge, ErrorState, Loading, errorMessage } from "./ui";

const OUTCOME: Record<Outcome, { label: string; tone: "gain" | "loss" | "warn" | "muted"; icon: string }> = {
  followed: { label: "Followed", tone: "gain", icon: "✓" },
  broken: { label: "Broken", tone: "loss", icon: "✕" },
  incomplete: { label: "Incomplete", tone: "warn", icon: "?" },
  no_rules: { label: "No rules", tone: "muted", icon: "–" },
};

const RULE = {
  pass: { icon: "✓", cls: "text-gain", label: "pass" },
  fail: { icon: "✕", cls: "text-loss", label: "fail" },
  unknown: { icon: "?", cls: "text-warn", label: "unknown" },
} as const;

export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  const o = OUTCOME[outcome];
  return <Badge tone={o.tone}>{o.icon} {o.label}</Badge>;
}

/** Verified rule results and the trader's checklist answers for one trade, kept visibly separate. */
export function TradeAdherencePanel({ d }: { d: TradeDetail }) {
  const q = useTradeAdherence(d.id);
  const save = useSaveChecklist(d.id);
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const data = q.data!;
  if (!data.assessment) {
    return <p className="text-sm text-muted">Assign a playbook in the journal form to check this trade against its rules.</p>;
  }
  const a = data.assessment;
  const stale = data.current_version !== undefined && data.current_version > a.version;
  return (
    <div className="space-y-4" data-testid="trade-adherence">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Link className="font-medium hover:text-accent" to={`/playbooks/${data.playbook_id}`}>{data.playbook_name}</Link>
        <Badge>rules v{a.version}</Badge>
        <OutcomeBadge outcome={a.outcome} />
      </div>
      {stale && (
        <p className="text-xs text-muted">
          This trade is judged by version {a.version}, the rules in force when it was assigned. The playbook is now at version {data.current_version};
          remove and re-assign the playbook to judge it by the new rules.
        </p>
      )}
      <section>
        <h3 className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">Verified from trade data</h3>
        {a.verified.length === 0 ? <p className="text-sm text-muted">This version has no checkable limits.</p> : (
          <ul className="space-y-1 text-sm">
            {a.verified.map((r) => (
              <li key={r.key} className="flex gap-2">
                <span className={`w-14 shrink-0 ${RULE[r.status].cls}`}>{RULE[r.status].icon} {RULE[r.status].label}</span>
                <span><span className="font-medium">{r.label}</span> <span className="text-muted">· {r.detail}</span></span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <Checklist a={a} pending={save.isPending} onAnswer={(item_id, answer) => save.mutate([{ item_id, answer }])} />
      {save.isError && <p role="alert" className="text-xs text-loss">{errorMessage(save.error)}</p>}
      <p className="text-xs text-muted">Adherence is about following the rules, not about profit: a losing trade can follow every rule.</p>
    </div>
  );
}

function Checklist({ a, pending, onAnswer }: { a: Assessment; pending: boolean; onAnswer: (id: string, v: boolean | null) => void }) {
  if (a.checklist.length === 0) return null;
  return (
    <section>
      <h3 className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">Your checklist (self-assessed)</h3>
      <ul className="space-y-2 text-sm">
        {a.checklist.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-2">
            <span className="w-10 text-xs text-muted">{c.phase === "pre" ? "Before" : "After"}</span>
            <span className="min-w-0 flex-1">{c.text}</span>
            <div role="group" aria-label={c.text} className="flex overflow-hidden rounded-lg border border-line text-xs">
              {([[true, "Yes"], [false, "No"]] as const).map(([v, label]) => (
                <button key={label} type="button" disabled={pending} aria-pressed={c.answer === v}
                  onClick={() => onAnswer(c.id, c.answer === v ? null : v)}
                  className={`px-3 py-1 ${c.answer === v ? (v ? "bg-gain/20 text-gain" : "bg-loss/20 text-loss") : "hover:bg-panel-2"}`}>
                  {label}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function AdherenceSummary({ data, currency, search }: { data: AdherenceBlock; currency: string; search: string }) {
  if (data.assessed_trades === 0) {
    return <p className="text-sm text-muted">No closed trades with a playbook under these filters. Assign playbooks on the trade page to see rule adherence.</p>;
  }
  const c = data.counts;
  return (
    <div className="space-y-4" data-testid="adherence-summary">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ["Followed rate", fmtPct(data.followed_rate), `${c.followed} followed / ${c.followed + c.broken} judged`],
          ["Followed", String(c.followed), "every rule passed, every item yes"],
          ["Broken", String(c.broken), "a rule failed or an item was no"],
          ["Incomplete", String(c.incomplete), "unknown rules or unanswered items"],
        ].map(([k, v, hint]) => (
          <div key={k} className="rounded-xl border border-line bg-panel-2 p-3">
            <div className="text-xs text-muted">{k}</div>
            <div className="num text-lg font-semibold">{v}</div>
            <div className="text-xs text-muted">{hint}</div>
          </div>
        ))}
      </div>
      <Table head={["Outcome", "Trades", "Net P&L", "Win rate", "Expectancy", "Avg R"]}>
        {data.outcomes.filter((o) => o.closed_trades > 0).map((o) => (
          <tr key={o.outcome} className="border-b border-line/60">
            <td className="py-1.5 pr-3"><OutcomeBadge outcome={o.outcome} /></td>
            <td className="pr-3 text-right">{o.closed_trades}</td>
            <td className={`pr-3 text-right ${pnlClass(o.net_pnl)}`}>{fmtMoney(o.net_pnl, currency, { sign: true })}</td>
            <td className="pr-3 text-right">{fmtPct(o.win_rate)}</td>
            <td className="pr-3 text-right">{fmtMoney(o.expectancy, currency)}</td>
            <td className="pr-3 text-right">{fmtR(o.avg_r)}</td>
          </tr>
        ))}
      </Table>
      {data.rules.length > 0 && (
        <Table head={["Verified rule", "Passed", "Failed", "Unknown", "Net when failed", "Avg R when failed", "Avg R when passed"]}>
          {data.rules.map((r) => (
            <tr key={r.key} className="border-b border-line/60">
              <td className="py-1.5 pr-3 text-left">{r.label}</td>
              <td className="pr-3 text-right">{r.passed}</td>
              <td className="pr-3 text-right">{r.failed}</td>
              <td className="pr-3 text-right text-muted">{r.unknown}</td>
              <td className={`pr-3 text-right ${pnlClass(r.net_pnl_when_failed)}`}>{fmtMoney(r.net_pnl_when_failed, currency, { sign: true })}</td>
              <td className="pr-3 text-right">{fmtR(r.avg_r_when_failed)}</td>
              <td className="pr-3 text-right">{fmtR(r.avg_r_when_passed)}</td>
            </tr>
          ))}
        </Table>
      )}
      {data.checklist.length > 0 && (
        <Table head={["Checklist item", "Yes", "No", "Unanswered", "Net when no", "Net when yes"]}>
          {data.checklist.map((i) => (
            <tr key={i.id} className="border-b border-line/60">
              <td className="py-1.5 pr-3 text-left"><span className="text-xs text-muted">{i.phase === "pre" ? "Before · " : "After · "}</span>{i.text}</td>
              <td className="pr-3 text-right">{i.yes}</td>
              <td className="pr-3 text-right">{i.no}</td>
              <td className="pr-3 text-right text-muted">{i.unanswered}</td>
              <td className={`pr-3 text-right ${pnlClass(i.net_pnl_when_no)}`}>{fmtMoney(i.net_pnl_when_no, currency, { sign: true })}</td>
              <td className={`pr-3 text-right ${pnlClass(i.net_pnl_when_yes)}`}>{fmtMoney(i.net_pnl_when_yes, currency, { sign: true })}</td>
            </tr>
          ))}
        </Table>
      )}
      {data.broken_trades.length > 0 && (
        <div>
          <h3 className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">Trades that broke their playbook</h3>
          <ul className="space-y-1 text-sm">
            {data.broken_trades.slice(0, 20).map((b) => (
              <li key={b.trade_id} className="flex flex-wrap gap-x-2">
                <Link className="text-accent hover:underline" to={`/trades/${b.trade_id}${search}`}>{b.symbol} · {fmtDateTime(b.closed_at)}</Link>
                <span className={pnlClass(b.net_pnl)}>{fmtMoney(b.net_pnl, currency, { sign: true })}</span>
                <span className="text-muted">{[...b.failed_rules, ...b.checklist_no.map((t) => `"${t}": no`)].join(" · ")}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-xs text-muted">{data.note}</p>
    </div>
  );
}

export function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead className="text-xs text-muted uppercase">
          <tr className="border-b border-line">
            {head.map((h, i) => <th key={h} className={`py-2 pr-3 ${i === 0 ? "text-left" : "text-right"}`}>{h}</th>)}
          </tr>
        </thead>
        <tbody className="num">{children}</tbody>
      </table>
    </div>
  );
}
