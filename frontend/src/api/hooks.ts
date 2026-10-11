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
  marketData: ["marketdata"] as const,
  tradeChart: (id: string, tf: string) => ["trade-chart", id, tf] as const,
  replaySessions: ["replay-sessions"] as const,
  replay: (id: string) => ["replay", id] as const,
  annotations: (id: string) => ["replay-annotations", id] as const,
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
  useQuery({ queryKey: qk.trade(id), queryFn: () => api(`/trades/${id}`, { schema: s.tradeDetail }), enabled: id !== "" });

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

// ---------------------------------------------------------------- market data and replay

export const useMarketDataInfo = () =>
  useQuery({ queryKey: qk.marketData, queryFn: () => api("/marketdata/provider", { schema: s.marketDataInfo }), staleTime: 300_000 });

/** Polls every 3 s while the server is still fetching provider data (HTTP 202, status "pending"). */
export const useTradeChart = (id: string, timeframe: string, enabled = true) =>
  useQuery({
    queryKey: qk.tradeChart(id, timeframe),
    queryFn: () => api(`/trades/${id}/chart`, { query: { timeframe }, schema: s.tradeChart }),
    enabled,
    refetchInterval: (q) => (q.state.data?.status === "pending" ? 3000 : false),
  });

export const useReplaySessions = () =>
  useQuery({ queryKey: qk.replaySessions, queryFn: () => api("/replay/sessions", { schema: z.array(s.replaySession) }) });

export const useReplayBars = (id: string) =>
  useQuery({
    queryKey: qk.replay(id),
    queryFn: () => api(`/replay/sessions/${id}/bars`, { schema: s.replayBars }),
    refetchInterval: (q) => (q.state.data?.status === "pending" ? 3000 : false),
    refetchOnWindowFocus: false,
  });

export const useAnnotations = (id: string) =>
  useQuery({ queryKey: qk.annotations(id), queryFn: () => api(`/replay/sessions/${id}/annotations`, { schema: z.array(s.annotation) }) });

export function useCreateReplay() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api("/replay/sessions", { method: "POST", body, schema: s.replaySession }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.replaySessions }),
  });
}

export function useDeleteReplay() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(`/replay/sessions/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.replaySessions }),
  });
}

export function useAddAnnotation(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { bar_time: string; price?: string; text: string }) =>
      api(`/replay/sessions/${id}/annotations`, { method: "POST", body, schema: s.annotation }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.annotations(id) }),
  });
}

export function useDeleteAnnotation(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (aid: string) => api(`/replay/sessions/${id}/annotations/${aid}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.annotations(id) }),
  });
}

export const advanceReplay = (id: string, steps: number) =>
  api(`/replay/sessions/${id}/advance`, { method: "POST", body: { steps }, schema: s.replayAdvance });

export const patchReplay = (id: string, body: { speed?: number; cursor_at?: string }) =>
  api(`/replay/sessions/${id}`, { method: "PATCH", body, schema: s.replaySession });
