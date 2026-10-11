import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import {
  useAiReview, useAiReviews, useAiStatus, useAskCoach, useDeleteAiReview, useInvalidateTradeData, useReviewTrade, useSummarise,
} from "../api/hooks";
import type { AiReview, AiSuggestedTag, TradeDetail } from "../api/schemas";
import { CoachAnswer, CoachSetup } from "../components/CoachAnswer";
import { Badge, Button, ErrorState, Field, Input, Loading, Panel, errorMessage } from "../components/ui";
import { fmtDateTime } from "../lib/format";

const STARTERS = [
  "How am I doing overall, and what is my biggest leak?",
  "Which playbook performs best, and am I following its rules?",
  "Which mistake tags cost me the most?",
  "Do I trade better long or short, and at what hours?",
];

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

export function CoachPage() {
  const status = useAiStatus();
  const [selected, setSelected] = useState<string | null>(null);
  const history = useAiReviews();
  const shown = useAiReview(selected);
  if (status.isLoading) return <Loading />;
  if (status.isError) return <ErrorState error={status.error} onRetry={() => status.refetch()} />;
  const on = status.data?.enabled;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">AI coach</h1>
        <p className="text-sm text-muted">
          Ask about your own trading. The coach reads your journal through the same analytics as the dashboard, cites every
          figure, and can't change anything or place orders.
        </p>
      </div>
      {!on ? <Panel><CoachSetup reason={status.data?.reason ?? null} /></Panel> : (
        <div className="grid gap-4 xl:grid-cols-3">
          <div className="space-y-4 xl:col-span-2">
            <AskPanel onAnswer={setSelected} />
            <Panel title="Answer">
              {!selected ? <p className="text-sm text-muted">Ask a question or pick one from your history.</p>
                : shown.isLoading ? <Loading /> : shown.isError ? <ErrorState error={shown.error} />
                : shown.data ? <CoachAnswer review={shown.data} /> : null}
            </Panel>
          </div>
          <div className="space-y-4">
            <SummaryPanel onAnswer={setSelected} />
            <Panel title="History">
              <History items={history.data ?? []} selected={selected} onSelect={setSelected} />
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}

function AskPanel({ onAnswer }: { onAnswer: (id: string) => void }) {
  const [q, setQ] = useState("");
  const ask = useAskCoach();
  const send = (question: string) => {
    if (question.trim().length < 3) return;
    ask.mutate({ question: question.trim() }, { onSuccess: (r) => { onAnswer(r.id); setQ(""); } });
  };
  return (
    <Panel title="Ask the coach">
      <form aria-label="Ask the coach" className="space-y-2" onSubmit={(e) => { e.preventDefault(); send(q); }}>
        <textarea
          aria-label="Question" value={q} onChange={(e) => setQ(e.target.value)} rows={3} maxLength={2000}
          placeholder="e.g. Why did I lose money in March?"
          className="w-full rounded-lg border border-line bg-panel-2 p-2 text-sm outline-none focus:border-accent"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={ask.isPending || q.trim().length < 3}>{ask.isPending ? "Thinking…" : "Ask"}</Button>
          {ask.isPending && <span className="text-xs text-muted">Looking up your data. This can take up to a minute.</span>}
        </div>
        {ask.isError && <p role="alert" className="text-sm text-loss">{errorMessage(ask.error)}</p>}
      </form>
      <div className="mt-3 flex flex-wrap gap-2">
        {STARTERS.map((s) => (
          <button key={s} type="button" disabled={ask.isPending} onClick={() => send(s)}
            className="rounded-full border border-line px-3 py-1 text-xs text-muted hover:border-accent hover:text-fg disabled:opacity-50">{s}</button>
        ))}
      </div>
    </Panel>
  );
}

function SummaryPanel({ onAnswer }: { onAnswer: (id: string) => void }) {
  const [from, setFrom] = useState(() => isoDay(new Date(Date.now() - 6 * 86400_000)));
  const [to, setTo] = useState(() => isoDay(new Date()));
  const sum = useSummarise();
  const bad = !from || !to || from > to;
  return (
    <Panel title="Summarise a day or week">
      <form aria-label="Summarise a period" className="space-y-2"
        onSubmit={(e) => { e.preventDefault(); if (!bad) sum.mutate({ date_from: from, date_to: to }, { onSuccess: (r) => onAnswer(r.id) }); }}>
        <div className="grid grid-cols-2 gap-2">
          <Field label="From"><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="To"><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        </div>
        <Button type="submit" variant="ghost" disabled={bad || sum.isPending}>{sum.isPending ? "Summarising…" : "Summarise"}</Button>
        {sum.isError && <p role="alert" className="text-sm text-loss">{errorMessage(sum.error)}</p>}
      </form>
    </Panel>
  );
}

function History({ items, selected, onSelect }: { items: { id: string; question: string; created_at: string; status: string; kind: string }[]; selected: string | null; onSelect: (id: string) => void }) {
  const del = useDeleteAiReview();
  if (!items.length) return <p className="text-sm text-muted">No answers yet.</p>;
  return (
    <ul className="space-y-1" data-testid="coach-history">
      {items.map((r) => (
        <li key={r.id} className={`flex items-start justify-between gap-2 rounded-lg p-2 ${selected === r.id ? "bg-panel-2" : ""}`}>
          <button type="button" className="text-left text-sm hover:text-accent" onClick={() => onSelect(r.id)}>
            {r.question}
            <span className="block text-xs text-muted">{fmtDateTime(r.created_at)}{r.status !== "ok" ? ` · ${r.status}` : ""}</span>
          </button>
          <button type="button" aria-label="Delete answer" className="text-xs text-muted hover:text-loss" onClick={() => del.mutate(r.id)}>✕</button>
        </li>
      ))}
    </ul>
  );
}

// ------------------------------------------------------------------------------------------- trade page panel

export function TradeCoachPanel({ d }: { d: TradeDetail }) {
  const status = useAiStatus();
  const past = useAiReviews({ trade_id: d.id, kind: "trade_review", limit: 1 });
  const latestId = past.data?.[0]?.id ?? null;
  const latest = useAiReview(latestId);
  const review = useReviewTrade();
  if (status.isLoading) return <Loading />;
  if (!status.data?.enabled) return <CoachSetup reason={status.data?.reason ?? null} />;
  const shown: AiReview | undefined = review.data ?? latest.data;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" onClick={() => review.mutate(d.id)} disabled={review.isPending}>
          {review.isPending ? "Reviewing…" : shown ? "Review again" : "Review this trade"}
        </Button>
        {review.isPending && <span className="text-xs text-muted">Reading the trade, your notes and similar trades.</span>}
        {shown && !review.isPending && <span className="text-xs text-muted">Reviewed {fmtDateTime(shown.created_at)}</span>}
      </div>
      {review.isError && <p role="alert" className="text-sm text-loss">{errorMessage(review.error)}</p>}
      {shown ? <CoachAnswer review={shown} footer={<SuggestedTags d={d} tags={shown.suggested_tags} />} />
        : !past.isLoading && <p className="text-sm text-muted">No AI review yet. The coach only cites figures it looked up in your data.</p>}
    </div>
  );
}

function SuggestedTags({ d, tags }: { d: TradeDetail; tags: AiSuggestedTag[] }) {
  const invalidate = useInvalidateTradeData();
  // Tags added from here, kept until the trade reloads, so two quick clicks don't drop each other.
  const [added, setAdded] = useState<{ id: string; name: string }[]>([]);
  const current = new Set([...d.tags, ...added].map((t) => t.name.toLowerCase()));
  const apply = useMutation({
    mutationFn: async (t: AiSuggestedTag) => {
      let id = t.tag_id;
      if (!id) id = (await api<{ id: string }>("/tags", { method: "POST", body: { name: t.name, category: t.category } })).id;
      const ids = [...new Set([...d.tags.map((x) => x.id), ...added.map((x) => x.id), id])];
      await api(`/trades/${d.id}`, { method: "PATCH", body: { tag_ids: ids } });
      setAdded((a) => [...a, { id: id!, name: t.name }]);
    },
    onSuccess: () => invalidate(),
  });
  return (
    <div>
      <h3 className="text-xs font-semibold text-muted uppercase">Suggested tags</h3>
      <ul className="mt-1 space-y-2" data-testid="suggested-tags">
        {tags.map((t) => {
          const applied = current.has(t.name.toLowerCase());
          return (
            <li key={t.name} className="flex flex-wrap items-start gap-2 text-sm">
              <Badge tone={t.category === "mistake" ? "loss" : t.category === "emotion" ? "warn" : "accent"}>{t.name}</Badge>
              {t.new && <span className="text-xs text-muted">new tag</span>}
              <span className="flex-1 text-xs text-muted">{t.reason}</span>
              <Button type="button" variant="ghost" className="px-2 py-1 text-xs" disabled={applied || apply.isPending}
                onClick={() => apply.mutate(t)}>{applied ? "Added" : t.new ? "Create and add" : "Add tag"}</Button>
            </li>
          );
        })}
      </ul>
      {apply.isError && <p role="alert" className="text-xs text-loss">{errorMessage(apply.error)}</p>}
      <p className="mt-1 text-[11px] text-muted">Tags are only added when you click.</p>
    </div>
  );
}
