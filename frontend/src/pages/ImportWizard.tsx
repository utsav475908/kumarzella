import { useEffect, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAccounts, useInvalidateTradeData, usePresets } from "../api/hooks";
import * as s from "../api/schemas";
import type { ImportJob, RawRecord, UploadOut } from "../api/schemas";
import { Badge, Button, Empty, ErrorState, Field, Loading, Panel, Select, errorMessage } from "../components/ui";

export const MAPPING_FIELDS: { key: string; label: string; required?: boolean }[] = [
  { key: "timestamp", label: "Date/time (combined)" },
  { key: "date", label: "Date (if separate)" },
  { key: "time", label: "Time (if separate)" },
  { key: "symbol", label: "Symbol", required: true },
  { key: "side", label: "Side (buy/sell)" },
  { key: "quantity", label: "Quantity", required: true },
  { key: "price", label: "Price", required: true },
  { key: "commission", label: "Commission" },
  { key: "fees", label: "Fees" },
  { key: "execution_id", label: "Execution ID" },
  { key: "asset_class", label: "Asset class" },
  { key: "currency", label: "Currency" },
  { key: "multiplier", label: "Multiplier" },
];

export function validateMapping(mapping: Record<string, string>, sideFromSign: boolean): string[] {
  const errs: string[] = [];
  for (const f of MAPPING_FIELDS) if (f.required && !mapping[f.key]) errs.push(`Map a column to ${f.label}`);
  if (!mapping.timestamp && !mapping.date) errs.push("Map a date/time column (combined, or a separate date column)");
  if (!mapping.side && !sideFromSign) errs.push("Map a side column, or derive side from the quantity sign");
  const used = Object.values(mapping).filter(Boolean);
  if (new Set(used).size !== used.length) errs.push("Each CSV column can only be mapped once");
  return errs;
}

type Step = "upload" | "map" | "preview" | "done";

export function ImportWizard() {
  const accounts = useAccounts();
  const presets = usePresets();
  const invalidate = useInvalidateTradeData();
  const [step, setStep] = useState<Step>("upload");
  const [accountId, setAccountId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<UploadOut | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [timezone, setTimezone] = useState("America/New_York");
  const [sideFromSign, setSideFromSign] = useState(false);
  const [defaultAsset, setDefaultAsset] = useState("");
  const [preset, setPreset] = useState<string | null>(null);
  const [mapErrors, setMapErrors] = useState<string[]>([]);
  const [preview, setPreview] = useState<{ job: ImportJob; rows: RawRecord[] } | null>(null);
  const [result, setResult] = useState<ImportJob | null>(null);

  useEffect(() => {
    if (!accountId && accounts.data?.length) setAccountId(accounts.data[0].id);
  }, [accounts.data, accountId]);

  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("account_id", accountId);
      form.append("file", file as File);
      return api("/imports", { method: "POST", form, schema: s.uploadOut });
    },
    onSuccess: (j) => {
      setJob(j);
      setMapping(j.suggested_mapping);
      setPreset(j.detected_preset);
      const p = presets.data?.find((x) => x.key === j.detected_preset);
      if (p?.options.side_from_quantity_sign) setSideFromSign(true);
      setStep("map");
    },
  });
  const runPreview = useMutation({
    mutationFn: () =>
      api(`/imports/${job!.id}/preview`, {
        method: "POST",
        schema: s.previewOut,
        body: {
          mapping: Object.fromEntries(Object.entries(mapping).filter(([, v]) => v)),
          options: { timezone, side_from_quantity_sign: sideFromSign, default_asset_class: defaultAsset || null },
          preset,
        },
      }),
    onSuccess: (p) => { setPreview(p); setStep("preview"); },
  });
  const commit = useMutation({
    mutationFn: () => api(`/imports/${job!.id}/commit`, { method: "POST", schema: s.importJob }),
    onSuccess: (j) => { setResult(j); setStep("done"); invalidate(); },
  });

  const poll = useQuery({
    queryKey: ["import-job", result?.id],
    queryFn: () => api(`/imports/${result!.id}`, { schema: s.importJob }),
    enabled: !!result && ["queued", "committing"].includes(result.status),
    refetchInterval: 1500,
  });
  const final = poll.data ?? result;
  useEffect(() => {
    if (poll.data && poll.data.status === "completed") invalidate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [poll.data?.status]);

  if (accounts.isLoading) return <Loading />;
  if (accounts.isError) return <ErrorState error={accounts.error} onRetry={() => accounts.refetch()} />;
  if (!accounts.data?.length)
    return <Empty title="Create an account first"><Link className="text-accent" to="/accounts">Add a trading account</Link> to import executions into.</Empty>;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Import executions</h1>
      <ol className="flex gap-4 text-sm" aria-label="Steps">
        {(["upload", "map", "preview", "done"] as Step[]).map((st, i) => (
          <li key={st} className={step === st ? "font-semibold text-accent" : "text-muted"}>{i + 1}. {{ upload: "Upload", map: "Map columns", preview: "Review", done: "Summary" }[st]}</li>
        ))}
      </ol>

      {step === "upload" && (
        <Panel title="Upload a CSV">
          <div className="grid max-w-lg gap-3">
            <Field label="Account">
              <Select className="w-full" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                {accounts.data.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </Select>
            </Field>
            <div>
              <span className="mb-1 block text-xs text-muted">CSV file</span>
              <label
                className={`flex cursor-pointer flex-col items-center gap-1 rounded-xl border-2 border-dashed px-4 py-6 text-center text-sm transition hover:border-accent ${file ? "border-accent/60 bg-accent/5" : "border-line bg-panel-2"}`}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) setFile(f); }}
              >
                <input aria-label="CSV file" type="file" accept=".csv,.tsv,.txt,text/csv" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                {file
                  ? <><span className="font-medium" data-testid="chosen-file">{file.name}</span><span className="text-xs text-muted">{(file.size / 1024).toFixed(1)} KB · click to choose a different file</span></>
                  : <><span className="font-medium text-accent">Choose a CSV file</span><span className="text-xs text-muted">or drag it here</span></>}
              </label>
              <p className="mt-1 text-xs text-muted">One row per fill (execution). Partial fills, scale-ins and reversals are reconstructed into trades.</p>
            </div>
            <div className="flex items-center gap-3">
              <Button onClick={() => upload.mutate()} disabled={!file || !accountId || upload.isPending}>{upload.isPending ? "Uploading…" : "Upload"}</Button>
              {!file && <span className="text-xs text-muted">Choose a file first</span>}
            </div>
            {upload.isError && <p role="alert" className="text-sm text-loss">{errorMessage(upload.error)}</p>}
          </div>
        </Panel>
      )}

      {step === "map" && job && (
        <Panel title={`Map columns · ${job.filename} (${job.total_rows} rows)`}>
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <Field label="Preset">
              <Select value={preset ?? ""} onChange={(e) => {
                const p = presets.data?.find((x) => x.key === e.target.value);
                setPreset(p?.key ?? null);
                if (p) { setMapping(Object.fromEntries(Object.entries(p.mapping).filter(([, v]) => job.headers.includes(v)))); setSideFromSign(!!p.options.side_from_quantity_sign); }
              }}>
                <option value="">Custom</option>
                {presets.data?.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
              </Select>
            </Field>
            <Field label="Timezone of timestamps without an offset">
              <Select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
                {["America/New_York", "America/Chicago", "America/Los_Angeles", "UTC", "Europe/London", "Asia/Kolkata", "Asia/Tokyo"].map((z) => <option key={z}>{z}</option>)}
              </Select>
            </Field>
            <Field label="Default asset class">
              <Select value={defaultAsset} onChange={(e) => setDefaultAsset(e.target.value)}>
                <option value="">Infer from symbol</option>
                {["stock", "etf", "option", "future", "forex", "crypto"].map((a) => <option key={a}>{a}</option>)}
              </Select>
            </Field>
            <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={sideFromSign} onChange={(e) => setSideFromSign(e.target.checked)} />Side from quantity sign</label>
          </div>
          <div className="grid gap-2 md:grid-cols-3">
            {MAPPING_FIELDS.map((f) => (
              <Field key={f.key} label={`${f.label}${f.required ? " *" : ""}`}>
                <Select aria-label={f.label} className="w-full" value={mapping[f.key] ?? ""} onChange={(e) => setMapping({ ...mapping, [f.key]: e.target.value })}>
                  <option value="">— not in file —</option>
                  {job.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                </Select>
              </Field>
            ))}
          </div>
          <SampleTable rows={job.sample_rows} headers={job.headers} />
          {mapErrors.length > 0 && <ul role="alert" className="mt-3 list-disc pl-5 text-sm text-loss">{mapErrors.map((e) => <li key={e}>{e}</li>)}</ul>}
          {runPreview.isError && <p role="alert" className="mt-3 text-sm text-loss">{errorMessage(runPreview.error)}</p>}
          <div className="mt-4 flex gap-2">
            <Button variant="ghost" onClick={() => setStep("upload")}>Back</Button>
            <Button disabled={runPreview.isPending} onClick={() => { const errs = validateMapping(mapping, sideFromSign); setMapErrors(errs); if (!errs.length) runPreview.mutate(); }}>
              {runPreview.isPending ? "Validating…" : "Validate and preview"}
            </Button>
          </div>
        </Panel>
      )}

      {step === "preview" && preview && (
        <Panel title="Review before importing">
          <div className="mb-3 flex flex-wrap gap-3 text-sm">
            <Badge tone="gain">{preview.job.valid_rows} ready to import</Badge>
            <Badge tone="loss">{preview.job.rejected_rows} rejected</Badge>
            <Badge tone="warn">{preview.job.duplicate_rows} duplicates (skipped)</Badge>
            <span className="text-muted">{preview.job.total_rows} rows total</span>
          </div>
          <PreviewTable rows={preview.rows} />
          {preview.job.rejected_rows > 0 && <p className="mt-2 text-xs text-muted">Rejected rows are kept with their errors for reference and are never imported. Fix the file and re-upload to include them.</p>}
          {commit.isError && <p role="alert" className="mt-3 text-sm text-loss">{errorMessage(commit.error)}</p>}
          <div className="mt-4 flex gap-2">
            <Button variant="ghost" onClick={() => setStep("map")}>Back to mapping</Button>
            <Button disabled={preview.job.valid_rows === 0 || commit.isPending} onClick={() => commit.mutate()}>
              {commit.isPending ? "Importing…" : `Import ${preview.job.valid_rows} executions`}
            </Button>
          </div>
        </Panel>
      )}

      {step === "done" && final && (
        <Panel title="Import summary">
          {["queued", "committing"].includes(final.status) && <Loading label="Import is processing in the background…" />}
          {final.status === "failed" && <ErrorState error={new Error(final.error_message ?? "Import failed. Nothing was saved.")} />}
          {final.status === "completed" && final.summary && (
            <div className="space-y-2 text-sm">
              <p className="font-medium text-gain">Import complete.</p>
              <ul className="num space-y-1 text-muted">
                <li>Executions imported: {String(final.summary.executions_created)}</li>
                <li>Trades created: {String(final.summary.trades_created)} · updated: {String(final.summary.trades_updated)}</li>
                <li>Duplicates skipped: {final.duplicate_rows} · rejected rows: {final.rejected_rows}</li>
              </ul>
              <div className="flex gap-3 pt-2">
                <Link className="text-accent" to={`/trades?account_id=${final.account_id}`}>Open journal</Link>
                <Link className="text-accent" to={`/?account_id=${final.account_id}`}>View dashboard</Link>
                <button className="text-accent" onClick={() => { setStep("upload"); setJob(null); setPreview(null); setResult(null); setFile(null); }}>Import another file</button>
              </div>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}

function SampleTable({ rows, headers }: { rows: Record<string, string>[]; headers: string[] }) {
  return (
    <div className="mt-4 overflow-x-auto">
      <p className="mb-1 text-xs text-muted">First rows of the file</p>
      <table className="text-xs">
        <thead><tr>{headers.map((h) => <th key={h} className="border-b border-line px-2 py-1 text-left text-muted">{h}</th>)}</tr></thead>
        <tbody>{rows.slice(0, 5).map((r, i) => <tr key={i}>{headers.map((h) => <td key={h} className="px-2 py-1 whitespace-nowrap">{r[h]}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function PreviewTable({ rows }: { rows: RawRecord[] }) {
  return (
    <div className="max-h-[420px] overflow-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-panel text-left text-muted">
          <tr><th className="py-1 pr-2">Row</th><th className="pr-2">Status</th><th className="pr-2">Time (UTC)</th><th className="pr-2">Symbol</th><th className="pr-2">Side</th><th className="pr-2">Qty</th><th className="pr-2">Price</th><th className="pr-2">Costs</th><th>Messages</th></tr>
        </thead>
        <tbody className="num">
          {rows.map((r) => {
            const n = r.normalized as Record<string, string> | null;
            return (
              <tr key={r.id} className="border-t border-line/60 align-top">
                <td className="py-1 pr-2">{r.row_number}</td>
                <td className="pr-2"><Badge tone={r.status === "valid" ? "gain" : r.status === "rejected" ? "loss" : "warn"}>{r.status}</Badge></td>
                <td className="pr-2 whitespace-nowrap">{n?.executed_at ?? "—"}</td>
                <td className="pr-2">{n ? `${n.symbol} (${n.asset_class})` : r.raw[Object.keys(r.raw)[1]]}</td>
                <td className="pr-2">{n?.side ?? "—"}</td>
                <td className="pr-2">{n?.quantity ?? "—"}</td>
                <td className="pr-2">{n?.price ?? "—"}</td>
                <td className="pr-2">{n ? `${n.commission} + ${n.fees}` : "—"}</td>
                <td className="text-muted">{[...r.errors, ...r.warnings].join("; ")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-1 text-xs text-muted">Showing the first {rows.length} rows.</p>
    </div>
  );
}
