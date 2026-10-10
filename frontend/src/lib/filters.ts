import { useSearchParams } from "react-router";
import type { Query } from "../api/client";

/** Global filters live in the URL so every page, chart and drill-down shares them. */
export const FILTER_KEYS = [
  "account_id",
  "date_from",
  "date_to",
  "symbol",
  "asset_class",
  "playbook_id",
  "tag_id",
  "direction",
  "session",
  "net_min",
  "net_max",
  "entry_hour",
  "weekday",
] as const;
export const MULTI_KEYS = new Set(["account_id", "symbol", "asset_class", "playbook_id", "tag_id"]);

export type Filters = Partial<Record<(typeof FILTER_KEYS)[number], string | string[]>>;

export function readFilters(sp: URLSearchParams): Filters {
  const f: Filters = {};
  for (const k of FILTER_KEYS) {
    if (MULTI_KEYS.has(k)) {
      const v = sp.getAll(k).filter(Boolean);
      if (v.length) f[k] = v;
    } else {
      const v = sp.get(k);
      if (v) f[k] = v;
    }
  }
  return f;
}

export function filtersToQuery(f: Filters): Query {
  return { ...f } as Query;
}

export function filtersToSearch(f: Filters, extra: Record<string, string> = {}): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) {
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
    else if (v) sp.set(k, v);
  }
  for (const [k, v] of Object.entries(extra)) sp.set(k, v);
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export function useFilters(): [Filters, (next: Filters) => void] {
  const [sp, setSp] = useSearchParams();
  const filters = readFilters(sp);
  const set = (next: Filters) => {
    const keep = new URLSearchParams();
    // Preserve non-filter params (e.g. page) except pagination, which resets on filter change.
    sp.forEach((v, k) => {
      if (!(FILTER_KEYS as readonly string[]).includes(k) && k !== "page") keep.append(k, v);
    });
    for (const [k, v] of Object.entries(next)) {
      if (Array.isArray(v)) v.forEach((x) => keep.append(k, x));
      else if (v) keep.set(k, v);
    }
    setSp(keep);
  };
  return [filters, set];
}
