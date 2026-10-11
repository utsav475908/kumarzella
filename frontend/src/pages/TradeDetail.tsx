import { Fragment, useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { useMutation } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "../api/client";
import { useInvalidateTradeData, usePlaybooks, useTags, useTrade } from "../api/hooks";
import type { TradeDetail as TD } from "../api/schemas";
import { TradeAdherencePanel } from "../components/Adherence";
import { TradeChartPanel } from "../components/TradeChartPanel";
import { TradeCoachPanel } from "./Coach";
import { Badge, Button, ErrorState, Field, Input, Loading, Panel, Select, errorMessage } from "../components/ui";
import { fmtDateTime, fmtDuration, fmtMoney, fmtNum, fmtR, pnlClass, trimDecimal } from "../lib/format";

const priceField = z.string().trim().regex(/^(\d+(\.\d+)?)?$/, "Enter a non-negative number");

export function TradeDetailPage() {
  const { id = "" } = useParams();
  const loc = useLocation();
  const t = useTrade(id);
  if (t.isLoading) return <Loading />;
  if (t.isError) return <ErrorState error={t.error} onRetry={() => t.refetch()} />;
  if (!t.data) return null;
  const d = t.data;
  const c = d.currency;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to={`/trades${loc.search}`} className="text-xs text-muted hover:text-fg">← Journal</Link>
          <h1 className="mt-1 flex items-center gap-3 text-xl font-semibold">
            {d.symbol}
            <Badge tone={d.direction === "long" ? "accent" : "muted"}>{d.direction}</Badge>
            <Badge tone={d.status === "open" ? "warn" : "muted"}>{d.status}</Badge>
            <Badge>{d.origin}</Badge>
            {d.is_demo && <Badge tone="warn">demo data</Badge>}
          </h1>
          <p className="text-sm text-muted">{d.account_name} · {d.asset_class} · multiplier {fmtNum(d.multiplier)} · session {d.session_date} ({d.entry_session} hours)</p>
        </div>
        <div className="flex gap-2">
          {d.prev_trade_id ? <Link className="rounded-lg border border-line px-3 py-2 text-sm hover:border-accent" to={`/trades/${d.prev_trade_id}${loc.search}`}>← Previous</Link> : null}
          {d.next_trade_id ? <Link className="rounded-lg border border-line px-3 py-2 text-sm hover:border-accent" to={`/trades/${d.next_trade_id}${loc.search}`}>Next →</Link> : null}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        {[
          ["Net P&L", fmtMoney(d.net_pnl, c, { sign: true }), pnlClass(d.net_pnl)],
          ["Gross P&L", fmtMoney(d.gross_pnl, c, { sign: true }), pnlClass(d.gross_pnl)],
          ["Fees", fmtMoney(d.fees, c), ""],
          ["R-multiple", fmtR(d.r_multiple), pnlClass(d.r_multiple)],
          ["Initial risk", fmtMoney(d.initial_risk, c), ""],
          ["Entry avg", fmtNum(d.entry_avg_price, 6), ""],
          ["Exit avg", fmtNum(d.exit_avg_price, 6), ""],
          ["Held", fmtDuration(d.holding_seconds), ""],
          ...(d.mae != null && d.mfe != null
            ? [["MAE", fmtMoney(d.mae, c), "text-loss"], ["MFE", fmtMoney(d.mfe, c), "text-gain"]]
            : []),
        ].map(([k, v, cls]) => (
          <div key={k} className="rounded-xl border border-line bg-panel p-3">
            <div className="text-xs text-muted">{k}</div>
            <div className={`num text-lg font-semibold ${cls}`}>{v}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Chart" className="xl:col-span-2">
          <TradeChartPanel d={d} />
        </Panel>
        <Panel title="Journal"><JournalForm d={d} /></Panel>
      </div>

      <Panel title="Playbook rules"><TradeAdherencePanel d={d} /></Panel>

      <Panel title="Execution history and source data"><Executions d={d} /></Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Trade notes"><Notes d={d} /></Panel>
        <Panel title="Screenshots and files"><Attachments d={d} /></Panel>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Day notes">
          <p className="text-sm whitespace-pre-wrap text-muted">{d.day_note || "No note for this session."}</p>
          <Link className="mt-2 inline-block text-xs text-accent" to={`/trades?date_from=${d.session_date}&date_to=${d.session_date}`}>Open this day</Link>
        </Panel>
        <Panel title="How this trade was calculated">
          <dl className="space-y-1 text-xs">
            {Object.entries(d.calculation).map(([k, v]) => (
              <div key={k}><dt className="inline font-medium">{k}: </dt><dd className="inline text-muted">{v}</dd></div>
            ))}
          </dl>
        </Panel>
      </div>
      <Panel title="AI review">
        <TradeCoachPanel d={d} />
      </Panel>
      <Panel title="Audit history">
        {d.audit.length === 0 ? <p className="text-sm text-muted">No changes recorded.</p> : (
          <ul className="space-y-1 text-xs">
            {d.audit.map((a) => (
              <li key={a.id}><span className="text-muted">{fmtDateTime(a.created_at)}</span> · {a.action}{a.data && "fields" in a.data ? ` (${(a.data.fields as string[]).join(", ")})` : ""}</li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

function Executions({ d }: { d: TD }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[800px] text-sm">
        <thead className="text-left text-xs text-muted uppercase">
          <tr className="border-b border-line">
            <th className="py-2 pr-3">Time</th><th className="pr-3">Side</th><th className="pr-3">Role</th>
            <th className="pr-3 text-right">Fill qty</th><th className="pr-3 text-right">Allocated</th><th className="pr-3 text-right">Price</th>
            <th className="pr-3 text-right">Costs allocated</th><th className="pr-3 text-right">Realized</th><th className="pr-3 text-right">Position after</th><th className="pr-3">Source</th>
          </tr>
        </thead>
        <tbody className="num">
          {d.executions.map((e) => (
            <Fragment key={e.execution_id}>
              <tr className="border-b border-line/60">
                <td className="py-2 pr-3 whitespace-nowrap">{fmtDateTime(e.executed_at)}</td>
                <td className="pr-3">{e.side}</td>
                <td className="pr-3">{e.role}{e.shared_with_other_trade && <span className="ml-1"><Badge tone="warn">split</Badge></span>}</td>
                <td className="pr-3 text-right">{fmtNum(e.quantity, 8)}</td>
                <td className="pr-3 text-right">{fmtNum(e.allocated_quantity, 8)}</td>
                <td className="pr-3 text-right">{fmtNum(e.price, 10)}</td>
                <td className="pr-3 text-right">{fmtMoney(e.fees_allocated, d.currency)}</td>
                <td className={`pr-3 text-right ${pnlClass(e.realized_pnl)}`}>{fmtMoney(e.realized_pnl, d.currency)}</td>
                <td className="pr-3 text-right">{fmtNum(e.position_after, 8)}</td>
                <td className="pr-3 text-xs">
                  {e.source_ref ? (
                    <button className="text-accent hover:underline" onClick={() => setOpen(open === e.execution_id ? null : e.execution_id)}>
                      {e.source_ref.filename} row {e.source_ref.row_number}
                    </button>
                  ) : <span className="text-muted">{e.source} entry</span>}
                </td>
              </tr>
              {open === e.execution_id && e.source_ref?.raw && (
                <tr><td colSpan={10} className="bg-panel-2 p-2 font-mono text-xs">{JSON.stringify(e.source_ref.raw)}</td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">"split" marks a reversal fill shared with the adjacent trade; its costs are allocated pro rata by quantity.</p>
    </div>
  );
}

export function JournalForm({ d }: { d: TD }) {
  const playbooks = usePlaybooks();
  const tags = useTags();
  const invalidate = useInvalidateTradeData();
  const [stop, setStop] = useState(trimDecimal(d.planned_stop_price));
  const [target, setTarget] = useState(trimDecimal(d.planned_target_price));
  const [risk, setRisk] = useState(trimDecimal(d.planned_risk_amount));
  const [pb, setPb] = useState(d.playbook_id ?? "");
  const [followed, setFollowed] = useState(d.followed_plan === null ? "" : String(d.followed_plan));
  const [rating, setRating] = useState(d.rating ? String(d.rating) : "");
  const [tagIds, setTagIds] = useState<string[]>(d.tags.map((t) => t.id));
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    setStop(trimDecimal(d.planned_stop_price)); setTarget(trimDecimal(d.planned_target_price)); setRisk(trimDecimal(d.planned_risk_amount));
    setPb(d.playbook_id ?? ""); setFollowed(d.followed_plan === null ? "" : String(d.followed_plan));
    setRating(d.rating ? String(d.rating) : ""); setTagIds(d.tags.map((t) => t.id));
  }, [d]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/trades/${d.id}`, { method: "PATCH", body }),
    onSuccess: () => invalidate(),
  });
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    for (const [k, v] of Object.entries({ stop, target, risk })) {
      const r = priceField.safeParse(v);
      if (!r.success) errs[k] = r.error.issues[0].message;
    }
    if (risk && Number(risk) <= 0) errs.risk = "Risk must be greater than zero";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    save.mutate({
      planned_stop_price: stop || null,
      planned_target_price: target || null,
      planned_risk_amount: risk || null,
      playbook_id: pb || null,
      followed_plan: followed === "" ? null : followed === "true",
      rating: rating ? Number(rating) : null,
      tag_ids: tagIds,
    });
  };
  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Journal">
      <div className="grid grid-cols-2 gap-2">
        <Field label="Planned stop" error={errors.stop}><Input inputMode="decimal" value={stop} onChange={(e) => setStop(e.target.value)} /></Field>
        <Field label="Target" error={errors.target}><Input inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} /></Field>
      </div>
      <Field label="Planned risk amount (overrides stop)" error={errors.risk}><Input inputMode="decimal" value={risk} onChange={(e) => setRisk(e.target.value)} /></Field>
      <Field label="Strategy playbook">
        <Select className="w-full" value={pb} onChange={(e) => setPb(e.target.value)}>
          <option value="">None</option>
          {playbooks.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
        {d.playbook_version != null && pb === d.playbook_id && <span className="text-xs text-muted">Judged by rules v{d.playbook_version}</span>}
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Followed plan?">
          <Select className="w-full" value={followed} onChange={(e) => setFollowed(e.target.value)}>
            <option value="">Not rated</option><option value="true">Yes</option><option value="false">No</option>
          </Select>
        </Field>
        <Field label="Execution rating">
          <Select className="w-full" value={rating} onChange={(e) => setRating(e.target.value)}>
            <option value="">—</option>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
          </Select>
        </Field>
      </div>
      <fieldset>
        <legend className="mb-1 text-sm text-muted">Tags and mistakes</legend>
        <div className="flex flex-wrap gap-2">
          {tags.data?.length === 0 && <span className="text-xs text-muted">Create tags in Settings.</span>}
          {tags.data?.map((t) => (
            <label key={t.id} className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={tagIds.includes(t.id)} onChange={(e) => setTagIds(e.target.checked ? [...tagIds, t.id] : tagIds.filter((x) => x !== t.id))} />
              {t.name}{t.category === "mistake" && <span className="text-loss"> (mistake)</span>}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save journal"}</Button>
        {save.isSuccess && !save.isPending && <span className="text-xs text-gain">Saved</span>}
        {save.isError && <span role="alert" className="text-xs text-loss">{errorMessage(save.error)}</span>}
      </div>
    </form>
  );
}

function Notes({ d }: { d: TD }) {
  const invalidate = useInvalidateTradeData();
  const [body, setBody] = useState("");
  const add = useMutation({
    mutationFn: () => api(`/trades/${d.id}/notes`, { method: "POST", body: { body } }),
    onSuccess: () => { setBody(""); invalidate(); },
  });
  const del = useMutation({
    mutationFn: (noteId: string) => api(`/trades/${d.id}/notes/${noteId}`, { method: "DELETE" }),
    onSuccess: () => invalidate(),
  });
  return (
    <div className="space-y-3">
      {d.notes.length === 0 && <p className="text-sm text-muted">No notes yet.</p>}
      {d.notes.map((n) => (
        <div key={n.id} className="rounded-lg border border-line bg-panel-2 p-2 text-sm">
          <p className="whitespace-pre-wrap">{n.body}</p>
          <div className="mt-1 flex justify-between text-xs text-muted">
            <span>{fmtDateTime(n.created_at)}</span>
            <button className="hover:text-loss" onClick={() => del.mutate(n.id)}>Delete</button>
          </div>
        </div>
      ))}
      <textarea aria-label="New note" className="h-20 w-full rounded-lg border border-line bg-panel-2 p-2 text-sm" value={body} onChange={(e) => setBody(e.target.value)} placeholder="What did you see? What would you do differently?" />
      <div className="flex items-center gap-3">
        <Button onClick={() => add.mutate()} disabled={!body.trim() || add.isPending}>{add.isPending ? "Adding…" : "Add note"}</Button>
        {add.isError && <span role="alert" className="text-xs text-loss">{errorMessage(add.error)}</span>}
      </div>
    </div>
  );
}

function Attachments({ d }: { d: TD }) {
  const invalidate = useInvalidateTradeData();
  const up = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api(`/trades/${d.id}/attachments`, { method: "POST", form });
    },
    onSuccess: () => invalidate(),
  });
  const del = useMutation({ mutationFn: (id: string) => api(`/attachments/${id}`, { method: "DELETE" }), onSuccess: () => invalidate() });
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        {d.attachments.map((a) => (
          <figure key={a.id} className="rounded-lg border border-line p-1 text-xs">
            {a.content_type.startsWith("image/") ? (
              <a href={`/api/v1/attachments/${a.id}/content`} target="_blank" rel="noreferrer">
                <img src={`/api/v1/attachments/${a.id}/content`} alt={a.filename} className="h-28 w-full rounded object-cover" />
              </a>
            ) : (
              <a className="block p-4 text-accent" href={`/api/v1/attachments/${a.id}/content`}>{a.filename}</a>
            )}
            <figcaption className="mt-1 flex justify-between text-muted"><span className="truncate">{a.filename}</span><button onClick={() => del.mutate(a.id)} className="hover:text-loss">×</button></figcaption>
          </figure>
        ))}
      </div>
      <label className="inline-block cursor-pointer rounded-lg border border-line bg-panel-2 px-3 py-2 text-sm hover:border-accent">
        {up.isPending ? "Uploading…" : "Add screenshot or PDF"}
        <input type="file" accept="image/png,image/jpeg,image/gif,image/webp,application/pdf" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) up.mutate(f); e.target.value = ""; }} />
      </label>
      {up.isError && <p role="alert" className="text-xs text-loss">{errorMessage(up.error)}</p>}
    </div>
  );
}
