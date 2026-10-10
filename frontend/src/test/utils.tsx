import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { ReactNode } from "react";
import { vi } from "vitest";

export function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname + loc.search}</div>;
}

export function renderWithProviders(ui: ReactNode, { route = "/", path = "*" }: { route?: string; path?: string } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={<>{ui}<LocationProbe /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

type Handler = (url: URL, init?: RequestInit) => { status?: number; body?: unknown } | undefined;

/** Routes fetch() calls to handlers keyed by path prefix; unmatched calls return an empty list. */
export function mockFetch(handlers: Record<string, Handler | { status?: number; body?: unknown }>) {
  const calls: { url: URL; init?: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    calls.push({ url, init });
    const key = Object.keys(handlers)
      .sort((a, b) => b.length - a.length)
      .find((k) => url.pathname.startsWith(k));
    const h = key ? handlers[key] : undefined;
    const res = typeof h === "function" ? h(url, init) : h;
    const status = res?.status ?? 200;
    const body = res?.body ?? [];
    return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  document.cookie = "el_csrf=test-token";
  return calls;
}
