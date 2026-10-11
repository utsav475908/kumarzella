import { useState } from "react";
import { useNavigate } from "react-router";
import { useAddTradeAnnotation, useCreateReplay, useDeleteTradeAnnotation, useTradeAnnotations, useTradeChart } from "../api/hooks";
import type { Bar, TradeAnnotation, TradeDetail } from "../api/schemas";
import { snapToBar } from "../lib/bars";
import { fmtDateTime, fmtMoney, fmtR, trimDecimal } from "../lib/format";
import { CandleChart, type ChartMarker, type PriceLine } from "./CandleChart";
import { ExecutionChart } from "./ExecutionChart";
import { Badge, Button, ErrorState, Field, Input, Loading, Select, errorMessage } from "./ui";

const TIMEFRAMES = ["1m", "5m", "15m", "1h"];

export function TradeChartPanel({ d }: { d: TradeDetail }) {
  const [tf, setTf] = useState("1m");
  const chart = useTradeChart(d.id, tf);
  const notes = useTradeAnnotations(d.id);
  const [selected, setSelected] = useState<Bar | null>(null);
  const create = useCreateReplay();
  const nav = useNavigate();
  const c = d.currency;

  if (chart.isLoading) return <Loading label="Loading market data…" />;
  if (chart.isError) {
    return (
      <div className="space-y-3">
        <ErrorState error={chart.error} onRetry={() => chart.refetch()} />
        <ExecutionChart legs={d.executions} stop={d.planned_stop_price} target={d.planned_target_price} />
      </div>
    );
  }
  const data = chart.data!;
  if (data.status === "unsupported") {
    return (
      <div className="space-y-2">
        <ExecutionChart legs={d.executions} stop={d.planned_stop_price} target={d.planned_target_price} />
        <p className="text-xs text-muted" data-testid="chart-unsupported">{data.reason}</p>
      </div>
    );
  }
  if (data.status === "pending") {
    return <Loading label={`Downloading ${data.provider?.display_name ?? "market"} data for ${data.coverage?.pending_days.length ?? 0} day(s)…`} />;
  }

  const markers: ChartMarker[] = [
    ...data.markers.map((m) => ({
      t: m.t, kind: m.side, text: `${m.side === "buy" ? "B" : "S"} ${trimDecimal(m.quantity)} @ ${trimDecimal(m.price)}`,
    })),
    ...(notes.data ?? []).map((a) => ({ t: snapToBar(Date.parse(a.bar_time) / 1000, tf), kind: "note" as const, text: a.text.slice(0, 24) })),
  ];
  const lines: PriceLine[] = [];
  if (data.planned_stop_price) lines.push({ price: data.planned_stop_price, label: "stop", tone: "loss" });
  if (data.planned_target_price) lines.push({ price: data.planned_target_price, label: "target", tone: "gain" });
  const ex = data.excursions;
  const failed = data.coverage?.failed_days ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label="Timeframe" value={tf} onChange={(e) => setTf(e.target.value)} className="w-24">
          {TIMEFRAMES.map((x) => <option key={x} value={x}>{x}</option>)}
        </Select>
        <Badge>{data.symbol} · {data.side}</Badge>
        {data.status !== "ready" && <Badge tone="warn">{data.status === "partial" ? "partial data" : "data unavailable"}</Badge>}
        <div className="ml-auto">
          <Button variant="ghost" disabled={create.isPending || data.bars.length === 0}
            onClick={() => create.mutate({ mode: "review", trade_id: d.id, timeframe: tf }, { onSuccess: (s) => nav(`/replay/${s.id}`) })}>
            Replay this trade
          </Button>
        </div>
      </div>
      {create.isError && <p className="text-xs text-loss" role="alert">{errorMessage(create.error)}</p>}
      {data.bars.length === 0 ? (
        <p className="text-sm text-muted">No candles for this period. {failed.length ? `Download failed: ${failed[0].error}` : ""}</p>
      ) : (
        <CandleChart bars={data.bars} timeframe={tf} markers={markers} priceLines={lines} testId="trade-candles" onBarClick={setSelected} />
      )}
      <ChartNotes tradeId={d.id} selected={selected} onDone={() => setSelected(null)} notes={notes.data ?? []} error={notes.error} />
      {ex ? (
        <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4" data-testid="trade-excursions">
          <div><div className="text-xs text-muted">MAE</div><div className="num text-loss">{fmtMoney(ex.mae, c)}</div>
            <div className="text-xs text-muted">{ex.r ? fmtR(ex.r.mae_r) : ""} {ex.mae_at ? fmtDateTime(ex.mae_at) : ""}</div></div>
          <div><div className="text-xs text-muted">MFE</div><div className="num text-gain">{fmtMoney(ex.mfe, c)}</div>
            <div className="text-xs text-muted">{ex.r ? fmtR(ex.r.mfe_r) : ""} {ex.mfe_at ? fmtDateTime(ex.mfe_at) : ""}</div></div>
          <p className="col-span-2 text-xs text-muted">Gross of fees, from {ex.source}. {ex.precision}</p>
        </div>
      ) : d.status === "closed" ? (
        <p className="text-xs text-muted">MAE/MFE need every minute of the holding period; they appear once that data is cached.</p>
      ) : null}
      {data.gaps && data.gaps.length > 0 && (
        <p className="text-xs text-muted">{data.gaps.length} gap(s) of 5+ minutes without ticks in this window (normal around the 17:00 New York rollover).</p>
      )}
      <p className="text-xs text-muted">{[...(data.notes ?? []), data.provider?.attribution].filter(Boolean).join(" ")}</p>
    </div>
  );
}

const KINDS = [["note", "Note"], ["mistake", "Mistake"], ["good", "Good decision"]] as const;

/** Notes pinned to a candle of this trade's chart. Click a candle to add one. */
function ChartNotes({ tradeId, selected, onDone, notes, error }: {
  tradeId: string; selected: Bar | null; onDone: () => void; notes: TradeAnnotation[]; error: unknown;
}) {
  const add = useAddTradeAnnotation(tradeId);
  const del = useDeleteTradeAnnotation(tradeId);
  const [text, setText] = useState("");
  const [kind, setKind] = useState<string>("note");
  const at = selected ? new Date(selected.t * 1000).toISOString() : "";
  return (
    <div className="space-y-2" data-testid="chart-notes">
      {selected ? (
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim()) return;
          add.mutate({ bar_time: at, price: selected.c, kind, text: text.trim() }, { onSuccess: () => { setText(""); onDone(); } });
        }}>
          <Field label={`Chart note at ${fmtDateTime(at)} (close ${trimDecimal(selected.c)})`}>
            <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={5000} autoFocus />
          </Field>
          <Select aria-label="Note type" value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </Select>
          <Button type="submit" disabled={add.isPending}>Save note</Button>
          <Button type="button" variant="ghost" onClick={onDone}>Cancel</Button>
          {add.isError && <p className="w-full text-xs text-loss" role="alert">{errorMessage(add.error)}</p>}
        </form>
      ) : (
        <p className="text-xs text-muted">Click a candle to pin a note, mistake or good decision to it.</p>
      )}
      {error ? <p className="text-xs text-loss" role="alert">{errorMessage(error)}</p> : null}
      {notes.length > 0 && (
        <ul className="space-y-1 text-sm">
          {notes.map((a) => (
            <li key={a.id} className="flex items-center gap-2">
              <Badge tone={a.kind === "mistake" ? "loss" : a.kind === "good" ? "gain" : "muted"}>{KINDS.find(([k]) => k === a.kind)?.[1]}</Badge>
              <span className="text-xs text-muted">{fmtDateTime(a.bar_time)}{a.price ? ` @ ${trimDecimal(a.price)}` : ""}</span>
              <span>{a.text}</span>
              <button className="ml-auto text-xs text-muted hover:text-loss" onClick={() => del.mutate(a.id)} aria-label={`Delete chart note ${a.text}`}>✕</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
