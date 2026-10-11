import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import {
  advanceReplay,
  patchReplay,
  qk,
  useAddAnnotation,
  useAnnotations,
  useCreateReplay,
  useDeleteAnnotation,
  useDeleteReplay,
  useMarketDataInfo,
  useReplayBars,
  useReplaySessions,
  useTrade,
} from "../api/hooks";
import * as s from "../api/schemas";
import { CandleChart, type ChartMarker, type PriceLine } from "../components/CandleChart";
import { Badge, Button, Empty, ErrorState, Field, Input, Loading, Panel, Select, errorMessage } from "../components/ui";
import { fmtDateTime, trimDecimal } from "../lib/format";
import { TF_SECONDS } from "../lib/bars";
import { SPEEDS, initialReplayState, replayReducer, tickPlan } from "../lib/replayMachine";

const TF = TF_SECONDS;
const sec = (iso: string) => Math.floor(new Date(iso).getTime() / 1000);
const iso = (t: number) => new Date(t * 1000).toISOString();

export function ReplayListPage() {
  const sessions = useReplaySessions();
  const del = useDeleteReplay();
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Replay</h1>
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Saved replays" className="xl:col-span-2">
          {sessions.isLoading ? <Loading /> : sessions.isError ? <ErrorState error={sessions.error} onRetry={() => sessions.refetch()} /> :
            sessions.data!.length === 0 ? (
              <Empty title="No replays yet">Start a blind replay here, or open a forex trade and choose “Replay this trade”.</Empty>
            ) : (
              <ul className="divide-y divide-line" data-testid="replay-list">
                {sessions.data!.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                    <Badge tone={r.mode === "blind" ? "warn" : "accent"}>{r.mode}</Badge>
                    <Link className="font-medium hover:text-accent" to={`/replay/${r.id}`}>{r.title}</Link>
                    <span className="text-xs text-muted">{r.symbol} · {r.timeframe} · {r.completed ? "completed" : `${Math.round(r.progress * 100)}%`}</span>
                    <span className="ml-auto text-xs text-muted">updated {fmtDateTime(r.updated_at)}</span>
                    <Button variant="ghost" onClick={() => { if (confirm(`Delete “${r.title}”?`)) del.mutate(r.id); }}>Delete</Button>
                  </li>
                ))}
              </ul>
            )}
          {del.isError && <p className="text-xs text-loss" role="alert">{errorMessage(del.error)}</p>}
        </Panel>
        <Panel title="New blind replay"><NewBlindReplay /></Panel>
      </div>
    </div>
  );
}

function NewBlindReplay() {
  const info = useMarketDataInfo();
  const create = useCreateReplay();
  const nav = useNavigate();
  const [yesterday] = useState(() => new Date(Date.now() - 86_400_000).toISOString().slice(0, 10));
  const [form, setForm] = useState({ symbol: "EURUSD", timeframe: "5m", date: yesterday, days: "1" });
  const [err, setErr] = useState<string | null>(null);
  if (info.isLoading) return <Loading />;
  if (info.isError) return <ErrorState error={info.error} />;
  if (!info.data?.enabled) return <p className="text-sm text-muted">Historical market data is disabled on this server.</p>;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const days = Number(form.days);
    const start = new Date(`${form.date}T00:00:00Z`);
    const end = new Date(start.getTime() + days * 86_400_000);
    if (!form.date || Number.isNaN(start.getTime())) return setErr("Choose a start date");
    if (end.toISOString().slice(0, 10) > new Date().toISOString().slice(0, 10)) return setErr("The replay must end by today (UTC)");
    setErr(null);
    create.mutate(
      { mode: "blind", symbol: form.symbol, timeframe: form.timeframe, start_at: start.toISOString(), end_at: end.toISOString() },
      { onSuccess: (r) => nav(`/replay/${r.id}`) },
    );
  };
  return (
    <form className="space-y-3" onSubmit={submit} aria-label="New blind replay">
      <p className="text-xs text-muted">Bars are revealed one at a time by the server, so you cannot see what comes next. Use it to practise reading price action.</p>
      <Field label="Symbol">
        <Select value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })}>
          {(info.data.symbols ?? []).map((x) => <option key={x}>{x}</option>)}
        </Select>
      </Field>
      <Field label="Timeframe">
        <Select value={form.timeframe} onChange={(e) => setForm({ ...form, timeframe: e.target.value })}>
          {info.data.timeframes.map((x) => <option key={x}>{x}</option>)}
        </Select>
      </Field>
      <Field label="Start date (UTC)"><Input type="date" value={form.date} max={yesterday} onChange={(e) => setForm({ ...form, date: e.target.value })} /></Field>
      <Field label="Days">
        <Select value={form.days} onChange={(e) => setForm({ ...form, days: e.target.value })}>
          {["1", "2", "3", "5"].map((x) => <option key={x}>{x}</option>)}
        </Select>
      </Field>
      {(err || create.isError) && <p className="text-xs text-loss" role="alert">{err ?? errorMessage(create.error)}</p>}
      <Button type="submit" disabled={create.isPending}>{create.isPending ? "Preparing data…" : "Start blind replay"}</Button>
      {info.data.provider && <p className="text-xs text-muted">{info.data.provider.attribution}. {info.data.provider.licence_note}</p>}
    </form>
  );
}

export function ReplayPlayerPage() {
  const { id = "" } = useParams();
  const q = useReplayBars(id);
  if (q.isLoading) return <Loading label="Loading replay…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;
  if (d.status === "pending") return <Loading label={`Downloading ${d.provider.display_name} data for ${d.coverage.pending_days.length} day(s)…`} />;
  return <Player key={`${d.id}`} initial={d} />;
}

function Player({ initial }: { initial: s.ReplayBars }) {
  const id = initial.id;
  const tf = TF[initial.timeframe] ?? 60;
  const blind = initial.mode === "blind";
  const start = sec(initial.start_at);
  const end = sec(initial.end_at);
  const [bars, setBars] = useState<s.Bar[]>(initial.bars);
  const [cursor, setCursor] = useState(sec(initial.cursor_at));
  const [speed, setSpeed] = useState(initial.speed);
  const [seekTo, setSeekTo] = useState<number | null>(null);
  const [state, dispatch] = useReducer(replayReducer, initialReplayState);
  const [selected, setSelected] = useState<s.Bar | null>(null);
  const busy = useRef(false);
  const annotations = useAnnotations(id);
  const trade = useTrade(initial.trade_id ?? "");

  useEffect(() => dispatch({ type: "LOADED", completed: initial.completed }), [initial.completed]);

  const visible = useMemo(() => (blind ? bars : bars.filter((b) => b.t + tf <= cursor)), [bars, blind, cursor, tf]);

  /** Reveal n bars. Blind: the server returns them. Review: move the local cursor over bars already loaded. */
  const step = useCallback(async (n: number): Promise<boolean> => {
    if (blind) {
      const r = await advanceReplay(id, n);
      setBars((prev) => [...prev, ...r.bars]);
      setCursor(sec(r.cursor_at));
      return r.completed;
    }
    const ahead = bars.filter((b) => b.t + tf > cursor);
    if (ahead.length <= n) {
      setCursor(end);
      return true;
    }
    setCursor(ahead[n - 1].t + tf);
    return false;
  }, [blind, id, bars, cursor, tf, end]);

  const tick = useCallback(async (n: number) => {
    if (busy.current) return;
    busy.current = true;
    try {
      dispatch({ type: "STEP_DONE", completed: await step(n) });
    } catch (e) {
      dispatch({ type: "FAIL", message: errorMessage(e) });
    } finally {
      busy.current = false;
    }
  }, [step]);

  useEffect(() => {
    if (state.status !== "playing") return;
    const plan = tickPlan(speed);
    const h = setInterval(() => void tick(plan.steps), plan.intervalMs);
    return () => clearInterval(h);
  }, [state.status, speed, tick]);

  // Review sessions keep their cursor locally; save it whenever playback stops so the replay can resume later.
  const saved = useRef(sec(initial.cursor_at));
  const qc = useQueryClient();
  useEffect(() => {
    if (blind || state.status === "playing" || state.status === "loading" || cursor === saved.current) return;
    saved.current = cursor;
    patchReplay(id, { cursor_at: iso(cursor) })
      .then(() => qc.invalidateQueries({ queryKey: qk.replaySessions }))
      .catch(() => undefined);
  }, [blind, cursor, id, state.status, qc]);

  const changeSpeed = (v: number) => {
    setSpeed(v);
    void patchReplay(id, { speed: v }).catch(() => undefined);
  };

  const commitSeek = async (target: number) => {
    setSeekTo(null);
    const aligned = target - (target % tf);
    dispatch({ type: "SEEK" });
    try {
      if (blind) {
        await patchReplay(id, { cursor_at: iso(aligned) });
        const r = await api(`/replay/sessions/${id}/bars`, { schema: s.replayBars });
        setBars(r.bars);
        setCursor(sec(r.cursor_at));
        dispatch({ type: "SEEK_DONE", completed: r.completed });
      } else {
        const c = Math.min(Math.max(aligned, start), end);
        setCursor(c);
        dispatch({ type: "SEEK_DONE", completed: c >= end });
      }
    } catch (e) {
      dispatch({ type: "FAIL", message: errorMessage(e) });
    }
  };

  const markers: ChartMarker[] = [
    ...initial.markers.filter((m) => m.t < cursor).map((m) => ({
      t: m.t, kind: m.side, text: `${m.side === "buy" ? "B" : "S"} ${trimDecimal(m.quantity)} @ ${trimDecimal(m.price)}`,
    })),
    ...(annotations.data ?? []).filter((a) => a.t < cursor).map((a) => ({ t: a.t, kind: "note" as const, text: a.text.slice(0, 24) })),
  ];
  const o = initial.overlay;
  const lines: PriceLine[] = [];
  if (o?.planned_stop_price) lines.push({ price: o.planned_stop_price, label: "stop", tone: "loss" });
  if (o?.planned_target_price) lines.push({ price: o.planned_target_price, label: "target", tone: "gain" });
  if (o?.entry_avg_price && initial.markers.some((m) => m.t < cursor)) lines.push({ price: o.entry_avg_price, label: "entry avg", tone: "accent" });

  const progress = end > start ? Math.min(1, Math.max(0, (cursor - start) / (end - start))) : 1;
  const playing = state.status === "playing";
  const canPlay = ["ready", "paused"].includes(state.status);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/replay" className="text-xs text-muted hover:text-fg">← Replays</Link>
        <h1 className="text-xl font-semibold">{initial.title}</h1>
        <Badge tone={blind ? "warn" : "accent"}>{blind ? "blind" : "review"}</Badge>
        {o?.playbook && <Badge>{o.playbook}</Badge>}
        <span className="text-xs text-muted" data-testid="replay-state">{state.status}</span>
      </div>
      <p className="text-xs text-muted">
        {blind
          ? "Blind mode: the server only sends bars that have closed before the replay clock. Seeking forward reveals the bars you skip."
          : "Review mode: a retrospective look at your trade. Fills appear as the replay clock passes them."}
      </p>

      <Panel>
        <CandleChart bars={visible} timeframe={initial.timeframe} markers={markers} priceLines={lines} height={420} follow={playing}
          onBarClick={(b) => setSelected(b)} testId="replay-chart" />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {playing ? (
            <Button onClick={() => dispatch({ type: "PAUSE" })}>Pause</Button>
          ) : (
            <Button onClick={() => dispatch({ type: "PLAY" })} disabled={!canPlay}>Play</Button>
          )}
          <Button variant="ghost" disabled={!canPlay} onClick={() => void tick(1)}>Step</Button>
          <Select aria-label="Speed" className="w-28" value={speed} onChange={(e) => changeSpeed(Number(e.target.value))}>
            {SPEEDS.map((v) => <option key={v} value={v}>{v} bar{v > 1 ? "s" : ""}/s</option>)}
          </Select>
          <input aria-label="Seek" type="range" className="min-w-40 flex-1" min={start} max={end} step={tf}
            value={seekTo ?? cursor} disabled={state.status === "seeking" || state.status === "loading"}
            onChange={(e) => setSeekTo(Number(e.target.value))}
            onPointerUp={(e) => void commitSeek(Number((e.target as HTMLInputElement).value))}
            onKeyUp={(e) => { if (seekTo !== null) void commitSeek(Number((e.target as HTMLInputElement).value)); }} />
          <span className="num w-44 text-right text-xs text-muted" data-testid="replay-clock">{fmtDateTime(iso(cursor))} · {Math.round(progress * 100)}%</span>
        </div>
        <div className="mt-2 h-1 w-full rounded bg-line" role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-1 rounded bg-accent" style={{ width: `${progress * 100}%` }} />
        </div>
        {state.status === "error" && (
          <div className="mt-2 flex items-center gap-2 text-sm text-loss" role="alert">
            {state.message} <Button variant="ghost" onClick={() => { dispatch({ type: "RETRY" }); dispatch({ type: "LOADED", completed: false }); }}>Retry</Button>
          </div>
        )}
        {state.status === "completed" && <p className="mt-2 text-sm text-muted">Replay complete. Seek back to review any part of it.</p>}
        <p className="mt-2 text-xs text-muted">{initial.provider.attribution}. {initial.timeframe} candles built from 1-minute data ({initial.side}); no tick-level detail. {initial.provider.volume_note}</p>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Annotations">
          <AnnotationEditor id={id} selected={selected} onDone={() => setSelected(null)} />
          <ul className="mt-3 space-y-1 text-sm" data-testid="annotations">
            {(annotations.data ?? []).map((a) => <AnnotationRow key={a.id} id={id} a={a} />)}
            {annotations.data?.length === 0 && <li className="text-muted">Click a candle to add a note at that bar.</li>}
          </ul>
        </Panel>
        {initial.trade_id && (
          <Panel title="Trade notes" action={<Link className="text-xs text-accent" to={`/trades/${initial.trade_id}`}>Open trade</Link>}>
            {trade.isLoading ? <Loading /> : trade.isError ? <ErrorState error={trade.error} /> : trade.data && trade.data.notes.length ? (
              <ul className="space-y-2 text-sm">{trade.data.notes.map((n) => <li key={n.id} className="whitespace-pre-wrap">{n.body}</li>)}</ul>
            ) : <p className="text-sm text-muted">No notes on this trade.</p>}
          </Panel>
        )}
      </div>
    </div>
  );
}

function AnnotationEditor({ id, selected, onDone }: { id: string; selected: s.Bar | null; onDone: () => void }) {
  const add = useAddAnnotation(id);
  const [text, setText] = useState("");
  if (!selected) return null;
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => {
      e.preventDefault();
      if (!text.trim()) return;
      add.mutate({ bar_time: iso(selected.t), price: selected.c, text: text.trim() }, { onSuccess: () => { setText(""); onDone(); } });
    }}>
      <Field label={`Note at ${fmtDateTime(iso(selected.t))} (close ${trimDecimal(selected.c)})`}>
        <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={5000} autoFocus />
      </Field>
      <Button type="submit" disabled={add.isPending}>Save note</Button>
      <Button type="button" variant="ghost" onClick={onDone}>Cancel</Button>
      {add.isError && <p className="w-full text-xs text-loss" role="alert">{errorMessage(add.error)}</p>}
    </form>
  );
}

function AnnotationRow({ id, a }: { id: string; a: s.Annotation }) {
  const del = useDeleteAnnotation(id);
  return (
    <li className="flex items-center gap-2">
      <span className="text-xs text-muted">{fmtDateTime(a.bar_time)}</span>
      <span>{a.text}</span>
      <button className="ml-auto text-xs text-muted hover:text-loss" onClick={() => del.mutate(a.id)} aria-label={`Delete note ${a.text}`}>✕</button>
    </li>
  );
}
