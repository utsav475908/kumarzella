import { vi } from "vitest";

/** lightweight-charts draws on canvas, which jsdom lacks. This stand-in records what the components pass to it. */
export const chartCalls = {
  data: [] as unknown[][], markers: [] as unknown[][], lines: [] as unknown[],
  click: null as null | ((p: { time?: number }) => void),
};

vi.mock("lightweight-charts", () => {
  const series = () => ({
    setData: (d: unknown[]) => chartCalls.data.push(d),
    update: () => undefined,
    createPriceLine: (o: unknown) => { chartCalls.lines.push(o); return o; },
    removePriceLine: () => undefined,
  });
  return {
    ColorType: { Solid: "solid" },
    CandlestickSeries: "candles",
    HistogramSeries: "histogram",
    LineSeries: "line",
    createChart: () => ({
      addSeries: series,
      priceScale: () => ({ applyOptions: () => undefined }),
      timeScale: () => ({ fitContent: () => undefined, scrollToRealTime: () => undefined }),
      subscribeCrosshairMove: () => undefined,
      subscribeClick: (fn: (p: { time?: number }) => void) => { chartCalls.click = fn; },
      remove: () => undefined,
    }),
    createSeriesMarkers: () => ({ setMarkers: (m: unknown[]) => chartCalls.markers.push(m) }),
  };
});
