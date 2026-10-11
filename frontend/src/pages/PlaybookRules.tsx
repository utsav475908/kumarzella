import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { qk } from "../api/hooks";
import type { ChecklistItem, PlaybookDetail, PlaybookRules } from "../api/schemas";
import { Badge, Button, Field, Input, Select, errorMessage } from "../components/ui";
import { fmtDateTime, trimDecimal } from "../lib/format";

const TEXT_FIELDS = [
  ["entry_rules", "Entry rules"],
  ["exit_rules", "Exit rules"],
  ["stop_rules", "Initial stop-loss rules"],
  ["target_rules", "Target rules"],
  ["sizing_rules", "Position sizing"],
  ["invalidation", "Invalidation conditions"],
  ["valid_examples", "Valid setup examples"],
  ["invalid_examples", "Invalid setup examples"],
] as const;
type TextKey = (typeof TEXT_FIELDS)[number][0];

const HOURS = Array.from({ length: 25 }, (_, h) => h);
const pad = (h: number) => `${String(h).padStart(2, "0")}:00`;

/** Read-only view of one version's rules. */
export function RulesView({ r }: { r: PlaybookRules }) {
  const limits: [string, string][] = [];
  if (r.instruments.length) limits.push(["Instruments", r.instruments.join(", ")]);
  if (r.timeframe) limits.push(["Timeframe", r.timeframe]);
  if (r.permitted_sessions.length) limits.push(["Sessions", r.permitted_sessions.map((x) => `${x} hours`).join(", ")]);
  if (r.entry_hour_start !== null && r.entry_hour_end !== null) limits.push(["Entry window (market time)", `${pad(r.entry_hour_start)}–${pad(r.entry_hour_end)}`]);
  if (r.require_stop) limits.push(["Initial stop", "required"]);
  if (r.max_risk_per_trade) limits.push(["Max risk per trade", trimDecimal(r.max_risk_per_trade)]);
  if (r.min_reward_risk) limits.push(["Min planned reward:risk", `${trimDecimal(r.min_reward_risk)}:1`]);
  if (r.max_trades_per_day) limits.push(["Max trades per day", String(r.max_trades_per_day)]);
  const texts = TEXT_FIELDS.filter(([k]) => r[k]);
  return (
    <div className="space-y-4 text-sm" data-testid="rules-view">
      <div>
        <h3 className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">Checked automatically</h3>
        {limits.length === 0 ? <p className="text-muted">No checkable limits in this version.</p> : (
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[max-content_1fr]">
            {limits.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd>{v}</dd></div>)}
          </dl>
        )}
      </div>
      {(["pre_trade_checklist", "post_trade_checklist"] as const).map((k) => r[k].length > 0 && (
        <div key={k}>
          <h3 className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">{k === "pre_trade_checklist" ? "Pre-trade checklist" : "Post-trade checklist"}</h3>
          <ul className="list-inside list-disc">{r[k].map((i) => <li key={i.id}>{i.text}</li>)}</ul>
        </div>
      ))}
      {texts.map(([k, label]) => (
        <div key={k}>
          <h3 className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">{label}</h3>
          <p className="whitespace-pre-wrap">{r[k]}</p>
        </div>
      ))}
      {texts.length === 0 && r.pre_trade_checklist.length === 0 && r.post_trade_checklist.length === 0 && limits.length === 0 && (
        <p className="text-muted">This version has no rules yet. Edit the rules to add them.</p>
      )}
    </div>
  );
}

type Draft = {
  instruments: string; timeframe: string; sessions: string[]; start: string; end: string; require_stop: boolean;
  max_risk: string; min_rr: string; max_trades: string; pre: ChecklistItem[]; post: ChecklistItem[];
  change_note: string;
} & Record<TextKey, string>;

function toDraft(r: PlaybookRules): Draft {
  return {
    instruments: r.instruments.join(", "), timeframe: r.timeframe ?? "", sessions: r.permitted_sessions,
    start: r.entry_hour_start === null ? "" : String(r.entry_hour_start), end: r.entry_hour_end === null ? "" : String(r.entry_hour_end),
    require_stop: r.require_stop, max_risk: trimDecimal(r.max_risk_per_trade), min_rr: trimDecimal(r.min_reward_risk),
    max_trades: r.max_trades_per_day === null ? "" : String(r.max_trades_per_day), pre: r.pre_trade_checklist, post: r.post_trade_checklist,
    change_note: "", ...Object.fromEntries(TEXT_FIELDS.map(([k]) => [k, r[k] ?? ""])) as Record<TextKey, string>,
  };
}

const positive = (v: string) => v === "" || (/^\d+(\.\d+)?$/.test(v) && Number(v) > 0);

export function validateDraft(d: Draft): Record<string, string> {
  const e: Record<string, string> = {};
  if (!positive(d.max_risk)) e.max_risk = "Enter a positive amount";
  if (!positive(d.min_rr)) e.min_rr = "Enter a positive ratio";
  if (d.max_trades !== "" && !/^[1-9]\d*$/.test(d.max_trades)) e.max_trades = "Enter a whole number of at least 1";
  if ((d.start === "") !== (d.end === "")) e.window = "Set both ends of the entry window, or neither";
  else if (d.start !== "" && d.start === d.end) e.window = "The window is empty";
  if ([...d.pre, ...d.post].some((i) => !i.text.trim())) e.checklist = "Checklist items cannot be empty";
  return e;
}

function toBody(d: Draft) {
  return {
    instruments: d.instruments.split(",").map((s) => s.trim()).filter(Boolean),
    timeframe: d.timeframe.trim() || null,
    permitted_sessions: d.sessions,
    entry_hour_start: d.start === "" ? null : Number(d.start),
    entry_hour_end: d.end === "" ? null : Number(d.end),
    require_stop: d.require_stop,
    max_risk_per_trade: d.max_risk || null,
    min_reward_risk: d.min_rr || null,
    max_trades_per_day: d.max_trades ? Number(d.max_trades) : null,
    // New items are sent without an id; the server assigns one. Kept ids let answers survive rewording.
    pre_trade_checklist: d.pre.map((i) => ({ id: i.id || null, text: i.text.trim() })),
    post_trade_checklist: d.post.map((i) => ({ id: i.id || null, text: i.text.trim() })),
    change_note: d.change_note.trim() || null,
    ...Object.fromEntries(TEXT_FIELDS.map(([k]) => [k, d[k].trim() || null])),
  };
}

export function RulesEditor({ pb, onDone }: { pb: PlaybookDetail; onDone: () => void }) {
  const qc = useQueryClient();
  const [d, setD] = useState<Draft>(() => toDraft(pb.rules));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
  const save = useMutation({
    mutationFn: () => api(`/playbooks/${pb.id}/versions`, { method: "POST", body: toBody(d) }),
    onSuccess: async () => {
      await Promise.all([qc.invalidateQueries({ queryKey: qk.playbook(pb.id) }), qc.invalidateQueries({ queryKey: qk.playbooks })]);
      onDone();
    },
  });
  return (
    <form className="space-y-4" aria-label="Playbook rules" noValidate onSubmit={(e) => {
      e.preventDefault();
      const errs = validateDraft(d);
      setErrors(errs);
      if (Object.keys(errs).length === 0) save.mutate();
    }}>
      <p className="text-xs text-muted">Saving creates version {pb.current_version + 1}. Trades already assigned keep being judged by the version they were assigned under.</p>
      <fieldset className="grid gap-3 md:grid-cols-2">
        <legend className="mb-2 text-xs font-medium tracking-wide text-muted uppercase">Checked automatically from trade data</legend>
        <Field label="Instruments (comma separated, empty = any)"><Input value={d.instruments} onChange={(e) => set("instruments", e.target.value)} placeholder="EURUSD, ESH4" /></Field>
        <Field label="Timeframe (for reference)"><Input value={d.timeframe} onChange={(e) => set("timeframe", e.target.value)} placeholder="5m" /></Field>
        <div>
          <span className="mb-1 block text-sm text-muted">Permitted sessions (none = any)</span>
          <div className="flex gap-4 text-sm">
            {(["regular", "extended"] as const).map((x) => (
              <label key={x} className="flex items-center gap-1">
                <input type="checkbox" checked={d.sessions.includes(x)} onChange={(e) => set("sessions", e.target.checked ? [...d.sessions, x] : d.sessions.filter((y) => y !== x))} />
                {x} hours
              </label>
            ))}
          </div>
        </div>
        <Field label="Entry window (market time)" error={errors.window}>
          <div className="flex items-center gap-2">
            <Select aria-label="Window start" value={d.start} onChange={(e) => set("start", e.target.value)}>
              <option value="">Any</option>{HOURS.slice(0, 24).map((h) => <option key={h} value={h}>{pad(h)}</option>)}
            </Select>
            <span className="text-muted">to</span>
            <Select aria-label="Window end" value={d.end} onChange={(e) => set("end", e.target.value)}>
              <option value="">Any</option>{HOURS.slice(1).map((h) => <option key={h} value={h}>{pad(h)}</option>)}
            </Select>
          </div>
        </Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={d.require_stop} onChange={(e) => set("require_stop", e.target.checked)} /> Initial stop (or risk amount) required</label>
        <Field label="Max risk per trade" error={errors.max_risk}><Input inputMode="decimal" value={d.max_risk} onChange={(e) => set("max_risk", e.target.value)} /></Field>
        <Field label="Min planned reward:risk" error={errors.min_rr} hint="e.g. 2 for 2:1, from planned stop and target"><Input inputMode="decimal" value={d.min_rr} onChange={(e) => set("min_rr", e.target.value)} /></Field>
        <Field label="Max trades per day" error={errors.max_trades}><Input inputMode="numeric" value={d.max_trades} onChange={(e) => set("max_trades", e.target.value)} /></Field>
      </fieldset>
      <div className="grid gap-3 md:grid-cols-2">
        <ChecklistEditor label="Pre-trade checklist" items={d.pre} onChange={(v) => set("pre", v)} />
        <ChecklistEditor label="Post-trade checklist" items={d.post} onChange={(v) => set("post", v)} />
      </div>
      {errors.checklist && <p role="alert" className="text-xs text-loss">{errors.checklist}</p>}
      <fieldset className="grid gap-3 md:grid-cols-2">
        <legend className="mb-2 text-xs font-medium tracking-wide text-muted uppercase">Written rules (need your judgment)</legend>
        {TEXT_FIELDS.map(([k, label]) => (
          <Field key={k} label={label}>
            <textarea className="h-20 w-full rounded-lg border border-line bg-panel-2 p-2 text-sm" value={d[k]} onChange={(e) => set(k, e.target.value)} />
          </Field>
        ))}
      </fieldset>
      <Field label="What changed (optional)"><Input value={d.change_note} onChange={(e) => set("change_note", e.target.value)} maxLength={2000} /></Field>
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : `Save as version ${pb.current_version + 1}`}</Button>
        <Button type="button" variant="ghost" onClick={onDone}>Cancel</Button>
        {save.isError && <span role="alert" className="text-xs text-loss">{errorMessage(save.error)}</span>}
      </div>
    </form>
  );
}

function ChecklistEditor({ label, items, onChange }: { label: string; items: ChecklistItem[]; onChange: (v: ChecklistItem[]) => void }) {
  return (
    <div>
      <span className="mb-1 block text-sm text-muted">{label}</span>
      <ul className="space-y-2">
        {items.map((i, n) => (
          <li key={i.id || `new-${n}`} className="flex gap-2">
            <Input aria-label={`${label} item ${n + 1}`} className="flex-1" value={i.text} maxLength={500}
              onChange={(e) => onChange(items.map((x, m) => (m === n ? { ...x, text: e.target.value } : x)))} />
            <button type="button" className="text-xs text-muted hover:text-loss" aria-label={`Remove ${label} item ${n + 1}`} onClick={() => onChange(items.filter((_, m) => m !== n))}>✕</button>
          </li>
        ))}
      </ul>
      <button type="button" className="mt-2 text-xs text-accent" onClick={() => onChange([...items, { id: "", text: "" }])}>+ Add item</button>
    </div>
  );
}

export function VersionList({ pb, selected, onSelect }: { pb: PlaybookDetail; selected: number; onSelect: (v: number) => void }) {
  return (
    <ul className="space-y-1 text-sm" data-testid="playbook-versions">
      {pb.versions.map((v) => (
        <li key={v.id}>
          <button className={`w-full rounded-lg px-2 py-1 text-left hover:bg-panel-2 ${v.version === selected ? "bg-panel-2" : ""}`} onClick={() => onSelect(v.version)}>
            <span className="font-medium">v{v.version}</span> {v.version === pb.current_version && <Badge tone="accent">current</Badge>}
            <span className="block text-xs text-muted">{fmtDateTime(v.created_at)}{v.change_note ? ` · ${v.change_note}` : ""}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
