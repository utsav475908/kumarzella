import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useTrades } from "../api/hooks";
import { FilterBar } from "../components/FilterBar";
import { TradeTable } from "../components/TradeTable";
import { Button, Empty, ErrorState, Input, Loading, Panel, Select, errorMessage } from "../components/ui";
import { filtersToQuery, filtersToSearch, useFilters } from "../lib/filters";
import { fmtDate } from "../lib/format";

export function TradesPage() {
  const [filters] = useFilters();
  const [sp, setSp] = useSearchParams();
  const page = Number(sp.get("page") ?? "1");
  const sort = sp.get("sort") ?? "opened_at";
  const order = sp.get("order") ?? "desc";
  const q = sp.get("q") ?? "";
  const outcome = sp.get("outcome") ?? "";
  const status = sp.get("status") ?? "";
  const [search, setSearch] = useState(q);
  useEffect(() => setSearch(q), [q]);
  const trades = useTrades({ ...filtersToQuery(filters), page, page_size: 50, sort, order, q, outcome, status });
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k !== "page") next.delete("page");
    setSp(next);
  };
  const singleDay = typeof filters.date_from === "string" && filters.date_from === filters.date_to ? filters.date_from : null;
  const pages = trades.data ? Math.max(1, Math.ceil(trades.data.total / trades.data.page_size)) : 1;

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Trade journal</h1>
      <FilterBar />
      <div className="mb-3 flex flex-wrap gap-2">
        <form onSubmit={(e) => { e.preventDefault(); setParam("q", search.trim()); }} className="flex gap-2">
          <Input aria-label="Search symbol" placeholder="Search symbol" className="!w-48" value={search} onChange={(e) => setSearch(e.target.value)} />
          <Button variant="ghost" type="submit">Search</Button>
        </form>
        <Select aria-label="Outcome" value={outcome} onChange={(e) => setParam("outcome", e.target.value)}>
          <option value="">All outcomes</option><option value="win">Winners</option><option value="loss">Losers</option><option value="breakeven">Breakeven</option>
        </Select>
        <Select aria-label="Status" value={status} onChange={(e) => setParam("status", e.target.value)}>
          <option value="">Open & closed</option><option value="closed">Closed</option><option value="open">Open</option>
        </Select>
        <Select aria-label="Sort" value={`${sort}:${order}`} onChange={(e) => { const [s, o] = e.target.value.split(":"); const n = new URLSearchParams(sp); n.set("sort", s); n.set("order", o); n.delete("page"); setSp(n); }}>
          <option value="opened_at:desc">Newest first</option><option value="opened_at:asc">Oldest first</option>
          <option value="net_pnl:desc">Best net P&L</option><option value="net_pnl:asc">Worst net P&L</option>
          <option value="r_multiple:desc">Highest R</option><option value="holding_seconds:desc">Longest hold</option>
        </Select>
      </div>
      {singleDay && <DayNote day={singleDay} />}
      <Panel>
        {trades.isLoading && <Loading />}
        {trades.isError && <ErrorState error={trades.error} onRetry={() => trades.refetch()} />}
        {trades.data && trades.data.items.length === 0 && <Empty title="No trades match these filters" />}
        {trades.data && trades.data.items.length > 0 && (
          <>
            <TradeTable trades={trades.data.items} search={filtersToSearch(filters)} />
            <div className="mt-3 flex items-center justify-between text-sm text-muted">
              <span>{trades.data.total} trades</span>
              <div className="flex items-center gap-2">
                <Button variant="ghost" disabled={page <= 1} onClick={() => setParam("page", String(page - 1))}>Previous</Button>
                <span>Page {page} of {pages}</span>
                <Button variant="ghost" disabled={page >= pages} onClick={() => setParam("page", String(page + 1))}>Next</Button>
              </div>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}

function DayNote({ day }: { day: string }) {
  const qc = useQueryClient();
  const note = useQuery({
    queryKey: ["day-note", day],
    queryFn: async () => {
      try {
        return await api<{ body: string }>(`/day-notes/${day}`);
      } catch (e) {
        if ((e as { status?: number }).status === 404) return { body: "" };
        throw e;
      }
    },
  });
  const [body, setBody] = useState("");
  useEffect(() => setBody(note.data?.body ?? ""), [note.data]);
  const save = useMutation({
    mutationFn: () => api(`/day-notes/${day}`, { method: "PUT", body: { body } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["day-note", day] }),
  });
  return (
    <Panel title={`Day notes · ${fmtDate(day)}`} className="mb-3">
      {note.isLoading ? <Loading /> : (
        <>
          <textarea aria-label="Day notes" className="h-24 w-full rounded-lg border border-line bg-panel-2 p-2 text-sm" value={body} onChange={(e) => setBody(e.target.value)} placeholder="How did the session go?" />
          <div className="mt-2 flex items-center gap-3">
            <Button onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending ? "Saving…" : "Save day note"}</Button>
            {save.isSuccess && !save.isPending && <span className="text-xs text-gain">Saved</span>}
            {save.isError && <span role="alert" className="text-xs text-loss">{errorMessage(save.error)}</span>}
          </div>
        </>
      )}
    </Panel>
  );
}
