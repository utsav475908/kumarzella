import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "../api/client";
import { qk, useImports, useTags } from "../api/hooks";
import { Badge, Button, Empty, ErrorState, Field, Input, Loading, Panel, Select, errorMessage } from "../components/ui";
import { fmtDateTime } from "../lib/format";

export function SettingsPage() {
  const tags = useTags();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [category, setCategory] = useState("general");
  const add = useMutation({
    mutationFn: () => api("/tags", { method: "POST", body: { name: name.trim(), category } }),
    onSuccess: () => { setName(""); qc.invalidateQueries({ queryKey: qk.tags }); },
  });
  const del = useMutation({ mutationFn: (id: string) => api(`/tags/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: qk.tags }) });
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api("/auth/sessions", { schema: z.array(z.object({ id: z.string(), created_at: z.string(), ip: z.string().nullable(), user_agent: z.string().nullable(), current: z.boolean() })) }),
  });
  const revoke = useMutation({ mutationFn: (id: string) => api(`/auth/sessions/${id}`, { method: "DELETE" }), onSuccess: () => sessions.refetch() });

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Settings</h1>
      <Panel title="Tags and mistake categories">
        {tags.isLoading ? <Loading /> : tags.isError ? <ErrorState error={tags.error} /> : (
          <div className="mb-3 flex flex-wrap gap-2">
            {tags.data?.length === 0 && <span className="text-sm text-muted">No tags yet.</span>}
            {tags.data?.map((t) => (
              <span key={t.id} className="flex items-center gap-1">
                <Badge tone={t.category === "mistake" ? "loss" : "muted"}>{t.name} · {t.trade_count}</Badge>
                <button aria-label={`Delete ${t.name}`} className="text-xs text-muted hover:text-loss" onClick={() => del.mutate(t.id)}>×</button>
              </span>
            ))}
          </div>
        )}
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) add.mutate(); }}>
          <Field label="Tag name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Category">
            <Select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="general">General</option><option value="setup">Setup</option><option value="mistake">Mistake</option><option value="emotion">Emotion</option>
            </Select>
          </Field>
          <Button type="submit" disabled={!name.trim() || add.isPending}>Add tag</Button>
        </form>
        {add.isError && <p role="alert" className="mt-2 text-sm text-loss">{errorMessage(add.error)}</p>}
      </Panel>
      <Panel title="Signed-in sessions">
        {sessions.isLoading ? <Loading /> : sessions.isError ? <ErrorState error={sessions.error} /> : (
          <ul className="space-y-1 text-sm">
            {sessions.data?.map((s) => (
              <li key={s.id} className="flex justify-between gap-2">
                <span className="truncate text-muted">{fmtDateTime(s.created_at)} · {s.ip} · {s.user_agent}</span>
                {s.current ? <Badge tone="accent">this device</Badge> : <button className="text-xs text-loss" onClick={() => revoke.mutate(s.id)}>Revoke</button>}
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel title="Your data">
        <p className="mb-2 text-sm text-muted">Download every account, execution, trade, note and tag as JSON.</p>
        <a className="text-sm text-accent hover:underline" href="/api/v1/exports/me">Download export</a>
      </Panel>
    </div>
  );
}

export function ImportsPage() {
  const imports = useImports();
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Import history</h1>
      <Panel>
        {imports.isLoading && <Loading />}
        {imports.isError && <ErrorState error={imports.error} onRetry={() => imports.refetch()} />}
        {imports.data?.items.length === 0 && <Empty title="No imports yet" />}
        {imports.data && imports.data.items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted uppercase"><tr className="border-b border-line"><th className="py-2">When</th><th>File</th><th>Status</th><th className="text-right">Rows</th><th className="text-right">Imported</th><th className="text-right">Duplicates</th><th className="text-right">Rejected</th></tr></thead>
            <tbody className="num">
              {imports.data.items.map((j) => (
                <tr key={j.id} className="border-b border-line/60">
                  <td className="py-2">{fmtDateTime(j.created_at)}</td>
                  <td>{j.filename}</td>
                  <td><Badge tone={j.status === "completed" ? "gain" : j.status === "failed" ? "loss" : "warn"}>{j.status}</Badge>{j.error_message && <span className="ml-2 text-xs text-loss">{j.error_message}</span>}</td>
                  <td className="text-right">{j.total_rows}</td><td className="text-right">{j.imported_rows}</td><td className="text-right">{j.duplicate_rows}</td><td className="text-right">{j.rejected_rows}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
