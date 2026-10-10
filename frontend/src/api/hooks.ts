import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { api, type Query } from "./client";
import * as s from "./schemas";

export const qk = {
  me: ["me"] as const,
  accounts: ["accounts"] as const,
  tags: ["tags"] as const,
  playbooks: ["playbooks"] as const,
  trades: (q: Query) => ["trades", q] as const,
  trade: (id: string) => ["trade", id] as const,
  dashboard: (q: Query) => ["dashboard", q] as const,
  calendar: (q: Query) => ["calendar", q] as const,
  imports: ["imports"] as const,
  presets: ["presets"] as const,
};

export function useMe() {
  return useQuery({
    queryKey: qk.me,
    queryFn: async () => {
      try {
        return await api("/auth/me", { schema: s.user });
      } catch (e) {
        if ((e as { status?: number }).status === 401) return null;
        throw e;
      }
    },
    retry: false,
    staleTime: 60_000,
  });
}

export const useAccounts = () =>
  useQuery({ queryKey: qk.accounts, queryFn: () => api("/accounts", { schema: z.array(s.account) }) });
export const useTags = () => useQuery({ queryKey: qk.tags, queryFn: () => api("/tags", { schema: z.array(s.tag) }) });
export const usePlaybooks = () =>
  useQuery({ queryKey: qk.playbooks, queryFn: () => api("/playbooks", { schema: z.array(s.playbook) }) });

export const useTrades = (q: Query) =>
  useQuery({
    queryKey: qk.trades(q),
    queryFn: () => api("/trades", { query: q, schema: s.page(s.trade) }),
    placeholderData: (prev) => prev,
  });

export const useTrade = (id: string) =>
  useQuery({ queryKey: qk.trade(id), queryFn: () => api(`/trades/${id}`, { schema: s.tradeDetail }) });

export const useDashboard = (q: Query) =>
  useQuery({ queryKey: qk.dashboard(q), queryFn: () => api("/analytics/dashboard", { query: q, schema: s.dashboard }) });

export const useCalendar = (q: Query) =>
  useQuery({ queryKey: qk.calendar(q), queryFn: () => api("/analytics/calendar", { query: q, schema: s.calendar }) });

export const useImports = () =>
  useQuery({ queryKey: qk.imports, queryFn: () => api("/imports", { query: { page_size: 50 }, schema: s.page(s.importJob) }) });

export const usePresets = () =>
  useQuery({ queryKey: qk.presets, queryFn: () => api("/imports/presets", { schema: z.array(s.preset) }) });

/** After any write that can change trades, every derived view is refetched from the server. */
export function useInvalidateTradeData() {
  const qc = useQueryClient();
  return () =>
    Promise.all(
      ["trades", "trade", "dashboard", "calendar", "tags", "imports"].map((k) => qc.invalidateQueries({ queryKey: [k] })),
    );
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api("/auth/logout", { method: "POST" }),
    onSuccess: () => {
      qc.clear();
      qc.setQueryData(qk.me, null);
    },
  });
}
