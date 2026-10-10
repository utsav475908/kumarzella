/**
 * Display formatting only. Values arrive from the analytics API as decimal strings; nothing here
 * derives a financial metric. Converting to Number is for locale formatting of an already-computed value.
 */
export function fmtMoney(v: string | null | undefined, currency = "USD", opts: { sign?: boolean } = {}): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  const s = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(n));
  if (n < 0) return `-${s}`;
  return opts.sign && n > 0 ? `+${s}` : s;
}

export function fmtNum(v: string | number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  return n.toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function fmtPct(v: string | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return `${(Number(v) * 100).toFixed(digits)}%`;
}

export function fmtRatio(v: string | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return Number(v).toFixed(2);
}

export function fmtR(v: string | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}R`;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** -1, 0 or 1 from a decimal string, for colouring only. */
export function sign(v: string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const t = v.trim();
  if (/^-/.test(t) && !/^-0*(\.0*)?$/.test(t)) return -1;
  if (/^0*(\.0*)?$/.test(t.replace(/^[+-]/, ""))) return 0;
  return 1;
}

export function pnlClass(v: string | null | undefined): string {
  const s = sign(v);
  return s > 0 ? "text-gain" : s < 0 ? "text-loss" : "text-muted";
}

/** "202.0000000000" -> "202" for editable inputs (string manipulation only, no rounding). */
export function trimDecimal(v: string | null | undefined): string {
  if (!v) return "";
  return v.includes(".") ? v.replace(/0+$/, "").replace(/\.$/, "") : v;
}
