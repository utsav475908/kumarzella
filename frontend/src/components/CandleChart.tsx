import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Bar } from "../api/schemas";
import { snapToBar } from "../lib/bars";
import { trimDecimal } from "../lib/format";
import { useChartColors } from "./charts";

export type ChartMarker = { t: number; kind: "buy" | "sell" | "note"; text: string };
export type PriceLine = { price: string; label: string; tone: "gain" | "loss" | "accent" | "muted" };

const alpha = (hex: string, a: string) => (/^#[0-9a-f]{6}$/i.test(hex) ? `${hex}${a}` : hex);


type Props = {
  bars: Bar[];
  timeframe: string;
  markers?: ChartMarker[];
  priceLines?: PriceLine[];
  height?: number;
  /** Keep the newest bar in view as bars arrive (replay). */
  follow?: boolean;
  onBarClick?: (bar: Bar) => void;
  testId?: string;
};

/**
 * Candlestick chart with volume. Prices arrive as decimal strings and are converted to numbers only to draw them;
 * nothing here calculates a financial figure.
 */
export function CandleChart({ bars, timeframe, markers = [], priceLines = [], height = 360, follow = false, onBarClick, testId = "candle-chart" }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const markerApi = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const byTime = useRef(new Map<number, Bar>());
  const clickRef = useRef(onBarClick);
  const [hover, setHover] = useState<Bar | null>(null);
  const c = useChartColors();
  useEffect(() => {
    clickRef.current = onBarClick;
  }, [onBarClick]);

  useEffect(() => {
    if (!ref.current) return;
    const ch = createChart(ref.current, {
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: c.muted },
      grid: { vertLines: { color: c.line }, horzLines: { color: c.line } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: c.line },
      rightPriceScale: { borderColor: c.line },
      autoSize: true,
    });
    const cs = ch.addSeries(CandlestickSeries, {
      upColor: c.gain, downColor: c.loss, borderUpColor: c.gain, borderDownColor: c.loss, wickUpColor: c.gain, wickDownColor: c.loss,
      priceFormat: { type: "price", precision: 5, minMove: 0.00001 },
    });
    const vs = ch.addSeries(HistogramSeries, { priceScaleId: "vol", color: c.line, priceFormat: { type: "volume" } });
    ch.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    const onMove = (p: MouseEventParams) => setHover(p.time ? byTime.current.get(p.time as number) ?? null : null);
    const onClick = (p: MouseEventParams) => {
      const b = p.time ? byTime.current.get(p.time as number) : undefined;
      if (b && clickRef.current) clickRef.current(b);
    };
    ch.subscribeCrosshairMove(onMove);
    ch.subscribeClick(onClick);
    chart.current = ch;
    candles.current = cs;
    volume.current = vs;
    markerApi.current = createSeriesMarkers(cs, []);
    return () => {
      ch.remove();
      chart.current = candles.current = volume.current = markerApi.current = null;
      lines.current = [];
    };
  }, [c, height]);

  useEffect(() => {
    if (!candles.current || !volume.current) return;
    byTime.current = new Map(bars.map((b) => [b.t, b]));
    candles.current.setData(bars.map((b) => ({ time: b.t as UTCTimestamp, open: +b.o, high: +b.h, low: +b.l, close: +b.c })));
    volume.current.setData(bars.map((b) => ({ time: b.t as UTCTimestamp, value: +b.v, color: alpha(+b.c >= +b.o ? c.gain : c.loss, "55") })));
    if (follow && bars.length) chart.current?.timeScale().scrollToRealTime();
    else chart.current?.timeScale().fitContent();
  }, [bars, follow, c]);

  useEffect(() => {
    if (!markerApi.current) return;
    const have = new Set(bars.map((b) => b.t));
    const ms: SeriesMarker<Time>[] = markers
      .map((m) => ({ ...m, t: snapToBar(m.t, timeframe) }))
      .filter((m) => have.has(m.t))
      .sort((a, b) => a.t - b.t)
      .map((m) => ({
        time: m.t as UTCTimestamp,
        position: m.kind === "buy" ? "belowBar" : "aboveBar",
        color: m.kind === "buy" ? c.gain : m.kind === "sell" ? c.loss : c.accent,
        shape: m.kind === "buy" ? "arrowUp" : m.kind === "sell" ? "arrowDown" : "circle",
        text: m.text,
      }));
    markerApi.current.setMarkers(ms);
  }, [markers, bars, timeframe, c]);

  useEffect(() => {
    const cs = candles.current;
    if (!cs) return;
    lines.current.forEach((l) => cs.removePriceLine(l));
    const tone = { gain: c.gain, loss: c.loss, accent: c.accent, muted: c.muted };
    lines.current = priceLines.map((p) => cs.createPriceLine({ price: +p.price, color: tone[p.tone], lineStyle: 2, lineWidth: 1, title: p.label }));
  }, [priceLines, c]);

  const last = bars.length ? bars[bars.length - 1] : null;
  const shown = hover ?? last;
  return (
    <div>
      <div className="mb-1 flex flex-wrap gap-x-3 font-mono text-xs text-muted" aria-live="off" data-testid={`${testId}-legend`}>
        {shown ? (
          <>
            <span>{new Date(shown.t * 1000).toLocaleString()}</span>
            <span>O {trimDecimal(shown.o)}</span><span>H {trimDecimal(shown.h)}</span>
            <span>L {trimDecimal(shown.l)}</span><span>C {trimDecimal(shown.c)}</span>
            <span>Vol {trimDecimal(shown.v)}</span>
          </>
        ) : (
          <span>No bars</span>
        )}
      </div>
      <div ref={ref} style={{ height }} className="w-full" data-testid={testId} data-bars={bars.length} />
    </div>
  );
}
