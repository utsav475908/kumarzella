import "../test/chartMock";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BacktestPage, NewBacktest } from "./Backtest";
import { chartCalls } from "../test/chartMock";
import { mockFetch, renderWithProviders } from "../test/utils";

const provider = {
  name: "dukascopy", display_name: "Dukascopy", asset_classes: ["forex"], granularity: "1-minute candles", sides: ["bid", "ask"],
  attribution: "Historical prices: Dukascopy Bank SA", licence_note: "personal use", volume_note: "Dukascopy volume",
};
const coverage = { status: "ready", pending_days: [], failed_days: [], unpublished_days: [] };
const T0 = 1705478400 + 8 * 3600; // 2024-01-17 08:00 UTC
const bar = (t: number) => ({ t, o: "1.09", h: "1.0901", l: "1.0899", c: "1.09", v: "1" });

const session = (over: Record<string, unknown> = {}) => ({
  id: "b1", title: "EURUSD 2024-01-17", provider: "dukascopy", symbol: "EURUSD", timeframe: "1m", side: "bid",
  start_at: "2024-01-17T08:00:00Z", end_at: "2024-01-17T10:00:00Z", cursor_at: "2024-01-17T08:30:00Z", speed: 1,
  currency: "USD", starting_balance: "10000", config: { simulator: "sim-1", slippage_pips: "0.2" }, notes: null,
  status: "active", completed_at: null, at_end: false, progress: 0.25, pip_size: "0.0001",
  created_at: "2024-01-17T00:00:00Z", updated_at: "2024-01-17T00:00:00Z", ...over,
});
const state = (over: Record<string, unknown> = {}, sOver: Record<string, unknown> = {}) => ({
  session: session(sOver), position: "0", open_pnl: null, quote: { t: T0 + 29 * 60, bid: "1.09", ask: "1.0901" },
  orders: [], fills: [], trades: [], ...over,
});
const results = (sOver: Record<string, unknown> = {}) => ({
  session: session(sOver), currency: "USD", starting_balance: "10000", realized_net_pnl: "81.00", balance: "10081.00",
  return_pct: "0.0081", position: "0", open_pnl: null, summary: { closed_trades: 1, win_rate: "1", profit_factor: null, max_drawdown: "0" },
  equity_curve: [], ambiguous_fills: 0, warnings: ["Only 1 closed trade: too few to judge an edge."],
  disclaimer: "Simulated results are not evidence of future results.", trades: [],
});
const bars = Array.from({ length: 30 }, (_, i) => bar(T0 + i * 60));

function routes(over: Record<string, unknown> = {}) {
  return {
    "/api/v1/backtests/b1/bars": { body: { session: session(), status: "ready", coverage, provider, bars } },
    "/api/v1/backtests/b1/results": { body: results() },
    "/api/v1/backtests/b1/attachments": { body: [] },
    "/api/v1/backtests/b1": { body: state() },
    ...over,
  };
}

describe("backtest session", () => {
  it("sends a bracket order from the ticket and validates it first", async () => {
    const placed = state({
      orders: [{ id: "o1", seq: 1, kind: "entry", parent_id: null, side: "buy", type: "limit", quantity: "45000", price: "1.0895",
                 stop_loss: "1.0885", take_profit: "1.0915", risk_amount: "50", placed_at: "2024-01-17T08:30:00Z",
                 status: "pending", cancelled_at: null, reason: null, note: null }],
    });
    const calls = mockFetch(routes({ "/api/v1/backtests/b1/orders": { status: 201, body: placed } }));
    renderWithProviders(<BacktestPage />, { route: "/backtest/b1", path: "/backtest/:id" });
    const form = await screen.findByRole("form", { name: "Order ticket" });
    const f = within(form);
    await userEvent.selectOptions(f.getByLabelText("Order type"), "limit");
    await userEvent.selectOptions(f.getByLabelText("Size by"), "risk");
    const size = f.getByLabelText("Risk (USD)");
    await userEvent.clear(size);
    await userEvent.type(size, "50");
    await userEvent.click(f.getByRole("button", { name: "Buy" }));
    expect(form).toHaveTextContent("Limit and stop orders need a price");
    expect(form).toHaveTextContent("Sizing by risk needs a stop-loss");
    expect(calls.some((c) => c.url.pathname.endsWith("/orders"))).toBe(false);
    await userEvent.type(f.getByLabelText(/^Price/), "1.0895");
    await userEvent.type(f.getByLabelText(/^Stop-loss/), "1.0885");
    await userEvent.type(f.getByLabelText("Take-profit"), "1.0915");
    await userEvent.click(f.getByRole("button", { name: "Buy" }));
    await waitFor(() => expect(calls.some((c) => c.url.pathname.endsWith("/orders"))).toBe(true));
    const post = calls.find((c) => c.url.pathname.endsWith("/orders"))!;
    expect(JSON.parse(String(post.init?.body))).toEqual({
      side: "buy", type: "limit", risk_amount: "50", price: "1.0895", stop_loss: "1.0885", take_profit: "1.0915", note: null,
    });
    expect(await screen.findByTestId("backtest-orders")).toHaveTextContent("buy limit");
    // the pending entry is drawn on the chart as a price line
    await waitFor(() => expect(chartCalls.lines.at(-1)).toMatchObject({ price: 1.0895, title: "buy limit" }));
  });

  it("steps forward, appends only the new bars and reports fills", async () => {
    const after = state(
      { position: "10000", bars: [bar(T0 + 30 * 60)], events: { fills: 1, cancels: 0, ambiguous: 0 },
        fills: [{ id: "f1", order_id: "o1", kind: "entry", t: T0 + 30 * 60, ts: "2024-01-17T08:30:00Z", side: "buy", quantity: "10000",
                  price: "1.09012", commission: "0.35", slippage: "0.00002", ambiguous: false, reason: null }] },
      { cursor_at: "2024-01-17T08:31:00Z" },
    );
    const calls = mockFetch(routes({ "/api/v1/backtests/b1/advance": { body: after } }));
    renderWithProviders(<BacktestPage />, { route: "/backtest/b1", path: "/backtest/:id" });
    await userEvent.click(await screen.findByRole("button", { name: "Step" }));
    await waitFor(() => expect(screen.getByTestId("backtest-fills")).toHaveTextContent("buy 10,000 @ 1.09012"));
    const adv = calls.find((c) => c.url.pathname.endsWith("/advance"))!;
    expect(JSON.parse(String(adv.init?.body))).toEqual({ steps: 1 });
    expect(chartCalls.data.at(-2)).toHaveLength(31); // candles, then volume
    expect(screen.getByTestId("backtest-account")).toHaveTextContent("long 10,000");
    expect(screen.getByText(/Last step: 1 fill\(s\)/)).toBeInTheDocument();
  });

  it("shows results, warnings and a verified re-run once finished", async () => {
    const done = { status: "completed", completed_at: "2024-01-17T10:00:00Z", at_end: true, progress: 1 };
    mockFetch(routes({
      "/api/v1/backtests/b1/results": { body: results(done) },
      "/api/v1/backtests/b1/verify": { body: { reproducible: true, stored_fills: 2, rerun_fills: 2, simulator: "sim-1", mismatches: [] } },
      "/api/v1/backtests/b1": { body: state({}, done) },
    }));
    renderWithProviders(<BacktestPage />, { route: "/backtest/b1", path: "/backtest/:id" });
    const res = await screen.findByTestId("backtest-results");
    expect(res).toHaveTextContent("+$81.00");
    expect(res).toHaveTextContent("too few to judge an edge");
    expect(res).toHaveTextContent("not evidence of future results");
    expect(screen.queryByRole("form", { name: "Order ticket" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Re-run and verify" }));
    expect(await screen.findByTestId("verify-result")).toHaveTextContent("Reproducible: 2 fills match (sim-1)");
  });
});

describe("new backtest form", () => {
  it("rejects a bad balance and posts the chosen window", async () => {
    vi.setSystemTime(new Date("2024-02-01T12:00:00Z"));
    const calls = mockFetch({
      "/api/v1/marketdata/provider": { body: { enabled: true, provider, timeframes: ["1m", "5m"], symbols: ["EURUSD", "GBPUSD"] } },
      "/api/v1/backtests": { status: 201, body: session() },
    });
    renderWithProviders(<NewBacktest />);
    const form = await screen.findByRole("form", { name: "New backtest" });
    const f = within(form);
    const bal = f.getByLabelText(/Starting balance/);
    await userEvent.clear(bal);
    await userEvent.type(bal, "-5");
    await userEvent.click(f.getByRole("button", { name: "Start backtest" }));
    expect(form).toHaveTextContent("Enter a positive amount");
    await userEvent.clear(bal);
    await userEvent.type(bal, "5000");
    await userEvent.selectOptions(f.getByLabelText("Symbol"), "GBPUSD");
    await userEvent.click(f.getByRole("button", { name: "Start backtest" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/backtest/b1"));
    const post = calls.find((c) => c.init?.method === "POST")!;
    expect(JSON.parse(String(post.init?.body))).toMatchObject({
      symbol: "GBPUSD", timeframe: "5m", start_at: "2024-01-31T00:00:00.000Z", end_at: "2024-02-01T00:00:00.000Z", starting_balance: "5000",
    });
    vi.useRealTimers();
  });
});
