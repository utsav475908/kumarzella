import { useEffect, useRef } from "react";
import { ColorType, LineSeries, createChart, createSeriesMarkers, type SeriesMarker, type UTCTimestamp } from "lightweight-charts";
import type { ExecutionLeg } from "../api/schemas";
import { useChartColors } from "./charts";

/**
 * Plots the trade's own fills over time. This is NOT market data; it is the fallback when the configured
 * historical-data provider does not cover the instrument. Prices come from the execution records returned by the API.
 */
export function ExecutionChart({ legs, stop, target }: { legs: ExecutionLeg[]; stop: string | null; target: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  const c = useChartColors();
  useEffect(() => {
    if (!ref.current || legs.length === 0) return;
    const chart = createChart(ref.current, {
      height: 260,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: c.muted },
      grid: { vertLines: { color: c.line }, horzLines: { color: c.line } },
      timeScale: { timeVisible: true, secondsVisible: true, borderColor: c.line },
      rightPriceScale: { borderColor: c.line },
      autoSize: true,
    });
    const series = chart.addSeries(LineSeries, { color: c.accent, lineWidth: 2, pointMarkersVisible: true });
    let last = 0;
    const points = legs.map((l) => {
      let t = Math.floor(new Date(l.executed_at).getTime() / 1000);
      if (t <= last) t = last + 1; // lightweight-charts needs strictly increasing times
      last = t;
      return { leg: l, time: t as UTCTimestamp, value: Number(l.price) };
    });
    series.setData(points.map(({ time, value }) => ({ time, value })));
    const markers: SeriesMarker<UTCTimestamp>[] = points.map(({ leg, time }) => ({
      time,
      position: leg.side === "buy" ? "belowBar" : "aboveBar",
      color: leg.side === "buy" ? c.gain : c.loss,
      shape: leg.side === "buy" ? "arrowUp" : "arrowDown",
      text: `${leg.side === "buy" ? "B" : "S"} ${Number(leg.allocated_quantity)} @ ${Number(leg.price)}`,
    }));
    createSeriesMarkers(series, markers);
    if (stop) series.createPriceLine({ price: Number(stop), color: c.loss, lineStyle: 2, lineWidth: 1, title: "stop" });
    if (target) series.createPriceLine({ price: Number(target), color: c.gain, lineStyle: 2, lineWidth: 1, title: "target" });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [legs, stop, target, c]);
  return (
    <div>
      <div ref={ref} className="h-[260px] w-full" data-testid="execution-chart" />
      <p className="mt-2 text-xs text-muted">
        Execution prices only, from your fills.
      </p>
    </div>
  );
}
