import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { qk, useDashboard, usePlaybooks, useTrades } from "../api/hooks";
import * as s from "../api/schemas";
import { DailyPnl, EquityCurve, GroupBars } from "../components/charts";
import { TradeTable } from "../components/TradeTable";
import { Button, Empty, ErrorState, Field, Input, Loading, Panel, errorMessage } from "../components/ui";
import { filtersToQuery, filtersToSearch, useFilters } from "../lib/filters";
import { KpiRow } from "./Dashboard";

export function PlaybooksPage() {
  const pbs = usePlaybooks();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api("/playbooks", { method: "POST", body: { name: name.trim(), description: description.trim() || null } }),
    onSuccess: () => { setName(""); setDescription(""); qc.invalidateQueries({ queryKey: qk.playbooks }); },
  });
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Strategy playbooks</h1>
      <Panel title="Playbooks">
        {pbs.isLoading && <Loading />}
        {pbs.isError && <ErrorState error={pbs.error} />}
        {pbs.data?.length === 0 && <Empty title="No playbooks yet">Create one and assign trades to it from the trade page.</Empty>}
        <ul className="divide-y divide-line">
          {pbs.data?.map((p) => (
            <li key={p.id} className="py-2">
              <Link className="font-medium hover:text-accent" to={`/playbooks/${p.id}`}>{p.name}</Link>
              {p.description && <p className="text-sm text-muted">{p.description}</p>}
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
        <p className="mt-3 text-xs text-muted">Versioned entry/exit rules, checklists and rule-adherence tracking arrive in Phase 4.</p>
      </Panel>
    </div>
  );
}

/** Strategy report: the dashboard metrics restricted to one playbook, under the current global filters. */
export function PlaybookReport() {
  const { id = "" } = useParams();
  const [filters] = useFilters();
  const nav = useNavigate();
  const pb = useQuery({ queryKey: ["playbook", id], queryFn: () => api(`/playbooks/${id}`, { schema: s.playbook }) });
  const f = { ...filters, playbook_id: [id] };
  const dash = useDashboard(filtersToQuery(f));
  const trades = useTrades({ ...filtersToQuery(f), page_size: 20, sort: "closed_at", order: "desc" });
  const search = filtersToSearch(filters);
  if (pb.isError) return <ErrorState error={pb.error} />;
  return (
    <div className="space-y-4">
      <Link to={`/${search}`} className="text-xs text-muted hover:text-fg">← Dashboard</Link>
      <h1 className="text-xl font-semibold">Strategy report: {pb.data?.name ?? "…"}</h1>
      {pb.data?.description && <p className="text-sm text-muted">{pb.data.description}</p>}
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
          <p className="text-xs text-muted">Profitability is not rule adherence: see the plan-adherence breakdown on the dashboard for self-reported plan following.</p>
        </>
      )}
      <Panel title="Trades in this playbook">
        {trades.data ? <TradeTable trades={trades.data.items} search={search} compact /> : <Loading />}
      </Panel>
    </div>
  );
}
