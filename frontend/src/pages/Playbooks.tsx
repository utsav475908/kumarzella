import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { qk, useDashboard, usePlaybook, usePlaybookAdherence, usePlaybooks, usePlaybookVersion, useTrades } from "../api/hooks";
import * as s from "../api/schemas";
import { AdherenceSummary } from "../components/Adherence";
import { DailyPnl, EquityCurve, GroupBars } from "../components/charts";
import { TradeTable } from "../components/TradeTable";
import { Badge, Button, Empty, ErrorState, Field, Input, Loading, Panel, errorMessage } from "../components/ui";
import { filtersToQuery, filtersToSearch, useFilters } from "../lib/filters";
import { KpiRow } from "./Dashboard";
import { RulesEditor, RulesView, VersionList } from "./PlaybookRules";

export function PlaybooksPage() {
  const pbs = usePlaybooks();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api("/playbooks", { method: "POST", body: { name: name.trim(), description: description.trim() || null }, schema: s.playbookDetail }),
    onSuccess: (pb) => {
      qc.invalidateQueries({ queryKey: qk.playbooks });
      nav(`/playbooks/${pb.id}?tab=rules&edit=1`);
    },
  });
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Strategy playbooks</h1>
      <Panel title="Playbooks">
        {pbs.isLoading && <Loading />}
        {pbs.isError && <ErrorState error={pbs.error} />}
        {pbs.data?.length === 0 && <Empty title="No playbooks yet">Create one, write its rules and checklists, then assign trades to it from the trade page.</Empty>}
        <ul className="divide-y divide-line">
          {pbs.data?.map((p) => (
            <li key={p.id} className="flex items-baseline gap-2 py-2">
              <Link className="font-medium hover:text-accent" to={`/playbooks/${p.id}`}>{p.name}</Link>
              <Badge>v{p.current_version}</Badge>
              {p.description && <p className="truncate text-sm text-muted">{p.description}</p>}
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="New playbook">
        <form className="grid max-w-xl gap-3" onSubmit={(e) => { e.preventDefault(); if (!name.trim()) { setErr("Name is required"); return; } setErr(null); create.mutate(); }} noValidate>
          <Field label="Setup name" error={err}><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Description"><textarea className="h-20 w-full rounded-lg border border-line bg-panel-2 p-2 text-sm" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
          <div><Button type="submit" disabled={create.isPending}>Create playbook</Button></div>
          {create.isError && <p role="alert" className="text-sm text-loss">{errorMessage(create.error)}</p>}
        </form>
      </Panel>
    </div>
  );
}

const TABS = [["report", "Report"], ["rules", "Rules"], ["screenshots", "Screenshots"]] as const;
type Tab = (typeof TABS)[number][0];

/** One playbook: its strategy report (metrics plus rule adherence), its versioned rules and its setup screenshots. */
export function PlaybookPage() {
  const { id = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const tab = (TABS.some(([k]) => k === sp.get("tab")) ? sp.get("tab") : "report") as Tab;
  const pb = usePlaybook(id);
  const [filters] = useFilters();
  const search = filtersToSearch(filters);
  if (pb.isLoading) return <Loading />;
  if (pb.isError) return <ErrorState error={pb.error} onRetry={() => pb.refetch()} />;
  const p = pb.data!;
  const go = (t: Tab) => { const next = new URLSearchParams(sp); next.set("tab", t); next.delete("edit"); setSp(next, { replace: true }); };
  return (
    <div className="space-y-4">
      <Link to={`/playbooks`} className="text-xs text-muted hover:text-fg">← Playbooks</Link>
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold">{p.name}</h1>
        <Badge tone="accent">rules v{p.current_version}</Badge>
        {p.archived_at && <Badge tone="warn">archived</Badge>}
      </div>
      {p.description && <p className="text-sm text-muted">{p.description}</p>}
      <div role="tablist" className="flex gap-1 border-b border-line">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => go(k)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === k ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg"}`}>
            {label}
          </button>
        ))}
      </div>
      {tab === "report" && <PlaybookReport p={p} search={search} />}
      {tab === "rules" && <RulesTab p={p} editing={sp.get("edit") === "1"} setEditing={(on) => { const n = new URLSearchParams(sp); if (on) n.set("edit", "1"); else n.delete("edit"); setSp(n, { replace: true }); }} />}
      {tab === "screenshots" && <Screenshots p={p} />}
    </div>
  );
}

function PlaybookReport({ p, search }: { p: s.PlaybookDetail; search: string }) {
  const [filters] = useFilters();
  const nav = useNavigate();
  const f = { ...filters, playbook_id: [p.id] };
  const q = filtersToQuery(f);
  const dash = useDashboard(q);
  const adh = usePlaybookAdherence(p.id, filtersToQuery(filters));
  const trades = useTrades({ ...q, page_size: 20, sort: "closed_at", order: "desc" });
  return (
    <div className="space-y-4">
      {dash.isLoading && <Loading />}
      {dash.isError && <ErrorState error={dash.error} />}
      {dash.data && dash.data.summary.closed_trades === 0 && <Empty title="No closed trades are assigned to this playbook under the current filters" />}
      {dash.data && dash.data.summary.closed_trades > 0 && (
        <>
          <KpiRow d={dash.data} />
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Cumulative net P&L"><EquityCurve data={dash.data.equity_curve} currency={dash.data.currency} onSelect={(t) => nav(`/trades/${t}${search}`)} /></Panel>
            <Panel title="Daily net P&L"><DailyPnl data={dash.data.daily} currency={dash.data.currency} onSelect={(d) => nav(`/trades${filtersToSearch({ ...f, date_from: d, date_to: d })}`)} /></Panel>
            <Panel title="By symbol"><GroupBars data={dash.data.by_symbol} currency={dash.data.currency} horizontal onSelect={(g) => nav(`/trades${filtersToSearch({ ...f, symbol: [g.key ?? ""] })}`)} /></Panel>
            <Panel title="Long vs short"><GroupBars data={dash.data.by_direction} currency={dash.data.currency} /></Panel>
          </div>
        </>
      )}
      <Panel title="Rule adherence">
        {adh.isLoading && <Loading />}
        {adh.isError && <ErrorState error={adh.error} onRetry={() => adh.refetch()} />}
        {adh.data && <AdherenceSummary data={adh.data} currency={adh.data.currency} search={search} />}
      </Panel>
      <Panel title="Trades in this playbook">
        {trades.data ? <TradeTable trades={trades.data.items} search={search} compact /> : <Loading />}
      </Panel>
    </div>
  );
}

function RulesTab({ p, editing, setEditing }: { p: s.PlaybookDetail; editing: boolean; setEditing: (on: boolean) => void }) {
  const [viewing, setViewing] = useState(p.current_version);
  const old = usePlaybookVersion(p.id, viewing !== p.current_version ? viewing : null);
  const shown = viewing === p.current_version ? p.rules : old.data;
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_260px]">
      <Panel
        title={editing ? "Edit rules" : `Rules · version ${viewing}${viewing === p.current_version ? " (current)" : ""}`}
        action={!editing && viewing === p.current_version ? <Button variant="ghost" onClick={() => setEditing(true)}>Edit rules</Button> : undefined}
      >
        {editing ? <RulesEditor pb={p} onDone={() => { setEditing(false); setViewing(p.current_version + 1); }} /> : (
          <>
            {old.isLoading && <Loading />}
            {old.isError && <ErrorState error={old.error} />}
            {shown && <RulesView r={shown} />}
          </>
        )}
      </Panel>
      <Panel title="Version history">
        <VersionList pb={p} selected={viewing} onSelect={(v) => { setEditing(false); setViewing(v); }} />
        <p className="mt-3 text-xs text-muted">Rules are never edited in place. Each trade stays pinned to the version that was current when it was assigned.</p>
      </Panel>
    </div>
  );
}

function Screenshots({ p }: { p: s.PlaybookDetail }) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: qk.playbook(p.id) });
  const up = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api(`/playbooks/${p.id}/attachments`, { method: "POST", form });
    },
    onSuccess: refresh,
  });
  const del = useMutation({ mutationFn: (aid: string) => api(`/attachments/${aid}`, { method: "DELETE" }), onSuccess: refresh });
  return (
    <Panel title="Setup screenshots">
      {p.attachments.length === 0 && <p className="mb-3 text-sm text-muted">Add examples of valid and invalid setups.</p>}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {p.attachments.map((a) => (
          <figure key={a.id} className="rounded-lg border border-line p-1 text-xs">
            <a href={`/api/v1/attachments/${a.id}/content`} target="_blank" rel="noreferrer">
              <img src={`/api/v1/attachments/${a.id}/content`} alt={a.filename} className="h-36 w-full rounded object-cover" />
            </a>
            <figcaption className="mt-1 flex justify-between text-muted"><span className="truncate">{a.filename}</span>
              <button onClick={() => del.mutate(a.id)} className="hover:text-loss" aria-label={`Delete ${a.filename}`}>×</button></figcaption>
          </figure>
        ))}
      </div>
      <label className="mt-3 inline-block cursor-pointer rounded-lg border border-line bg-panel-2 px-3 py-2 text-sm hover:border-accent">
        {up.isPending ? "Uploading…" : "Add screenshot"}
        <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) up.mutate(f); e.target.value = ""; }} />
      </label>
      {(up.isError || del.isError) && <p role="alert" className="mt-2 text-xs text-loss">{errorMessage(up.error ?? del.error)}</p>}
    </Panel>
  );
}
