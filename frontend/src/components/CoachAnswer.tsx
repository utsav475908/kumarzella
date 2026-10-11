import { Fragment, useState, type ReactNode } from "react";
import type { AiEvidence, AiReview } from "../api/schemas";
import { fmtMoney, fmtPct, fmtRatio, fmtR } from "../lib/format";
import { Badge } from "./ui";

const STATUS: Record<AiReview["status"], { tone: "gain" | "warn" | "loss" | "muted"; label: string }> = {
  ok: { tone: "gain", label: "Every figure checked" },
  ungrounded: { tone: "loss", label: "Unverified figures" },
  declined: { tone: "warn", label: "Declined" },
  incomplete: { tone: "warn", label: "Incomplete" },
};

/** Turns "[E1]" markers into buttons that open that piece of evidence. */
function withCitations(text: string, onCite: (ref: string) => void, known: Set<string>): ReactNode[] {
  return text.split(/(\[E\d+\])/g).map((part, i) => {
    const m = part.match(/^\[(E\d+)\]$/);
    if (!m) return <Fragment key={i}>{part}</Fragment>;
    const ref = m[1];
    return known.has(ref) ? (
      <button key={i} type="button" onClick={() => onCite(ref)} aria-label={`Evidence ${ref}`}
        className="mx-0.5 rounded bg-accent/15 px-1 text-xs font-medium text-accent hover:bg-accent/25">{ref}</button>
    ) : <span key={i} className="mx-0.5 rounded bg-loss/15 px-1 text-xs text-loss" title="No such evidence">{ref}?</span>;
  });
}

export function AnswerText({ text, onCite, known }: { text: string; onCite: (ref: string) => void; known: Set<string> }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) {
      blocks.push(
        <ul key={`u${blocks.length}`} className="list-disc space-y-1 pl-5">
          {bullets.map((b, i) => <li key={i}>{withCitations(b, onCite, known)}</li>)}
        </ul>,
      );
      bullets = [];
    }
  };
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (/^[-*•] /.test(t)) bullets.push(t.slice(2));
    else {
      flush();
      if (t) blocks.push(<p key={`p${blocks.length}`}>{withCitations(t, onCite, known)}</p>);
    }
  }
  flush();
  return <div className="space-y-2 text-sm leading-relaxed">{blocks}</div>;
}

const FIGURES: [string, string, (v: string, c: string) => string][] = [
  ["closed_trades", "Closed trades", (v) => v],
  ["net_pnl", "Net P&L", (v, c) => fmtMoney(v, c, { sign: true })],
  ["win_rate", "Win rate", (v) => fmtPct(v)],
  ["profit_factor", "Profit factor", (v) => fmtRatio(v)],
  ["expectancy", "Expectancy", (v, c) => fmtMoney(v, c, { sign: true })],
  ["avg_r", "Avg R", (v) => fmtR(v)],
  ["fees", "Fees", (v, c) => fmtMoney(v, c)],
  ["max_drawdown", "Max drawdown", (v, c) => fmtMoney(v, c)],
];

function keyFigures(e: AiEvidence): [string, string][] {
  const r = e.result as Record<string, unknown>;
  const s = (r.summary ?? (r.trade as Record<string, unknown> | undefined)) as Record<string, unknown> | undefined;
  if (!s) return [];
  const c = String(r.currency ?? (r.trade as { currency?: string } | undefined)?.currency ?? "USD");
  return FIGURES.filter(([k]) => s[k] !== undefined && s[k] !== null).map(([k, label, f]) => [label, f(String(s[k]), c)]);
}

function filterText(f: Record<string, unknown>): string {
  const parts = Object.entries(f).map(([k, v]) => `${k} ${Array.isArray(v) ? v.join(", ") : String(v)}`);
  return parts.length ? parts.join(" · ") : "no filters";
}

export function EvidenceCard({ e, open, onToggle }: { e: AiEvidence; open: boolean; onToggle: () => void }) {
  const figs = keyFigures(e);
  return (
    <li id={`evidence-${e.ref}`} className={`rounded-lg border p-3 ${open ? "border-accent" : "border-line"}`}>
      <button type="button" onClick={onToggle} className="flex w-full items-start justify-between gap-2 text-left">
        <span className="text-sm"><span className="mr-2 font-semibold text-accent">{e.ref}</span>{e.label}</span>
        <span className="shrink-0 text-xs text-muted">{e.sample_size != null ? `n = ${e.sample_size}` : e.tool}</span>
      </button>
      {open && (
        <div className="mt-2 space-y-2 text-xs">
          <p className="text-muted">Source: {e.tool} · filters: {filterText(e.filters)}</p>
          {figs.length > 0 && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
              {figs.map(([k, v]) => (
                <div key={k}><dt className="text-muted">{k}</dt><dd className="num font-medium">{v}</dd></div>
              ))}
            </dl>
          )}
          <details>
            <summary className="cursor-pointer text-muted">Exact data the coach saw</summary>
            <pre className="mt-1 max-h-72 overflow-auto rounded bg-panel-2 p-2 text-[11px] leading-snug">{JSON.stringify(e.result, null, 2)}</pre>
          </details>
        </div>
      )}
    </li>
  );
}

export function CoachAnswer({ review, footer }: { review: AiReview; footer?: ReactNode }) {
  const [open, setOpen] = useState<string | null>(null);
  const known = new Set(review.evidence.map((e) => e.ref));
  const st = STATUS[review.status];
  const cite = (ref: string) => {
    setOpen(ref);
    document.getElementById(`evidence-${ref}`)?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  };
  return (
    <div className="space-y-3" data-testid="coach-answer">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={st.tone}>{st.label}</Badge>
        <span className="text-xs text-muted">{review.question}</span>
      </div>
      {review.status === "ungrounded" && (
        <p role="alert" className="rounded-lg border border-loss/40 bg-loss/10 p-2 text-xs text-loss">
          These figures couldn't be traced to your data, so don't rely on them: {review.unsupported_numbers.join(", ")}.
        </p>
      )}
      <AnswerText text={review.answer} onCite={cite} known={known} />
      {review.suggested_tags.length > 0 && footer}
      {review.limitations.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-muted uppercase">Limitations</h3>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-muted">
            {review.limitations.map((l) => <li key={l}>{l}</li>)}
          </ul>
        </div>
      )}
      {review.evidence.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-muted uppercase">Evidence ({review.evidence.length})</h3>
          <ul className="mt-1 space-y-2" data-testid="coach-evidence">
            {review.evidence.map((e) => <EvidenceCard key={e.ref} e={e} open={open === e.ref} onToggle={() => setOpen(open === e.ref ? null : e.ref)} />)}
          </ul>
        </div>
      )}
      <p className="text-[11px] text-muted">
        {review.model} · {review.usage.tool_calls ?? 0} data lookups · {((review.usage.input_tokens ?? 0) + (review.usage.output_tokens ?? 0)).toLocaleString()} tokens · {((review.usage.latency_ms ?? 0) / 1000).toFixed(1)} s.
        {" "}AI answers can be wrong. Figures are checked against your data; advice is not financial advice.
      </p>
    </div>
  );
}

export function CoachSetup({ reason }: { reason: string | null }) {
  return (
    <div className="space-y-2 text-sm" data-testid="coach-setup">
      <p className="font-medium">The AI coach is switched off.</p>
      <p className="text-muted">{reason ?? "No Anthropic API key is configured."}</p>
      <p className="text-muted">
        To turn it on, put your own Anthropic API key in a file called <code>.env</code> next to <code>docker-compose.yml</code>{" "}
        as <code>ANTHROPIC_API_KEY=sk-ant-…</code>, then run <code>docker compose up -d</code>. Usage is billed to that key.
      </p>
    </div>
  );
}
