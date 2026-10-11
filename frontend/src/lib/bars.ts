export const TF_SECONDS: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400 };

/** Snap a timestamp (UNIX seconds) to the open time of the bar that contains it, so markers sit on a candle. */
export function snapToBar(t: number, timeframe: string): number {
  const s = TF_SECONDS[timeframe] ?? 60;
  return t - (t % s);
}
