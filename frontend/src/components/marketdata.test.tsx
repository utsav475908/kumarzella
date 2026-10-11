import "../test/chartMock";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TradeChartPanel } from "./TradeChartPanel";
import { ReplayPlayerPage } from "../pages/Replay";
import { chartCalls } from "../test/chartMock";
import { tradeDetailFixture } from "../test/fixtures";
import { mockFetch, renderWithProviders } from "../test/utils";

const provider = {
  name: "dukascopy", display_name: "Dukascopy", asset_classes: ["forex"], granularity: "1-minute candles", sides: ["bid", "ask"],
  attribution: "Historical prices: Dukascopy Bank SA", licence_note: "personal use", volume_note: "Dukascopy volume",
};
const bar = (t: number, c = "1.09") => ({ t, o: "1.09", h: "1.091", l: "1.089", c, v: "1.5" });
const T0 = 1705399200; // 2024-01-16 10:00 UTC
const coverage = { status: "ready", pending_days: [], failed_days: [], unpublished_days: [] };

describe("trade chart panel", () => {
  it("falls back to the fills chart and says why when the provider does not cover the instrument", async () => {
    mockFetch({ "/api/v1/trades/t1/chart": { body: { status: "unsupported", reason: "Dukascopy covers forex only; AAPL (stock) has no candles yet.", provider, bars: [], markers: [] } } });
    renderWithProviders(<TradeChartPanel d={tradeDetailFixture} />);
    expect(await screen.findByTestId("chart-unsupported")).toHaveTextContent("covers forex only");
    expect(screen.getByTestId("execution-chart")).toBeInTheDocument();
  });

  it("shows a loading state while the server downloads data", async () => {
    mockFetch({ "/api/v1/trades/t1/chart": { status: 202, body: { status: "pending", provider, coverage: { ...coverage, status: "pending", pending_days: ["2024-01-16"] }, bars: [], markers: [] } } });
    renderWithProviders(<TradeChartPanel d={tradeDetailFixture} />);
    expect(await screen.findByText(/Downloading Dukascopy data for 1 day/)).toBeInTheDocument();
  });

  it("draws candles with fills and shows MAE/MFE from the server", async () => {
    chartCalls.markers.length = 0;
    mockFetch({
      "/api/v1/trades/t1/chart": { body: {
        status: "ready", provider, symbol: "EURUSD", timeframe: "1m", side: "bid", coverage,
        bars: [bar(T0), bar(T0 + 60), bar(T0 + 120)], gaps: [],
        markers: [{ t: T0 + 30, ts: "2024-01-16T10:00:30Z", side: "buy", quantity: "10000", price: "1.09" }],
        planned_stop_price: null, planned_target_price: null,
        excursions: { mae: "-5.00000000", mfe: "8.00000000", source: "dukascopy 1m bid/ask", computed_at: null, r: null, precision: "1-minute bars." },
        notes: ["Prices are Dukascopy bid quotes."],
      } },
    });
    renderWithProviders(<TradeChartPanel d={tradeDetailFixture} />);
    expect(await screen.findByTestId("trade-candles")).toHaveAttribute("data-bars", "3");
    const ex = screen.getByTestId("trade-excursions");
    expect(ex).toHaveTextContent("-$5.00");
    expect(ex).toHaveTextContent("$8.00");
    // the 10:00:30 fill is snapped onto the 10:00 candle
    await waitFor(() => expect(chartCalls.markers.at(-1)).toEqual([expect.objectContaining({ time: T0, shape: "arrowUp" })]));
  });
});

describe("replay player", () => {
  const session = {
    id: "r1", mode: "blind", trade_id: null, title: "Blind EURUSD", provider: "dukascopy", symbol: "EURUSD", timeframe: "1m",
    side: "bid", start_at: "2024-01-16T10:00:00Z", end_at: "2024-01-16T10:10:00Z", cursor_at: "2024-01-16T10:02:00Z",
    speed: 1, completed: false, progress: 0.2, created_at: "2024-01-17T00:00:00Z", updated_at: "2024-01-17T00:00:00Z",
  };

  it("reveals the next bars from the server when stepping in blind mode", async () => {
    const calls = mockFetch({
      "/api/v1/replay/sessions/r1/bars": { body: { ...session, status: "ready", coverage, provider, bars: [bar(T0), bar(T0 + 60)], markers: [], overlay: null } },
      "/api/v1/replay/sessions/r1/advance": { body: { ...session, cursor_at: "2024-01-16T10:03:00Z", progress: 0.3, bars: [bar(T0 + 120)] } },
      "/api/v1/replay/sessions/r1/annotations": { body: [] },
      "/api/v1/auth/csrf": { body: { csrf_token: "x" } },
    });
    renderWithProviders(<ReplayPlayerPage />, { route: "/replay/r1", path: "/replay/:id" });
    expect(await screen.findByTestId("replay-chart")).toHaveAttribute("data-bars", "2");
    expect(screen.getByTestId("replay-state")).toHaveTextContent("ready");
    await userEvent.click(screen.getByRole("button", { name: "Step" }));
    await waitFor(() => expect(screen.getByTestId("replay-chart")).toHaveAttribute("data-bars", "3"));
    expect(screen.getByTestId("replay-state")).toHaveTextContent("paused");
    const adv = calls.find((c) => c.url.pathname.endsWith("/advance"));
    expect(JSON.parse(String(adv?.init?.body))).toEqual({ steps: 1 });
  });

  it("shows an error state with retry when the replay cannot load", async () => {
    mockFetch({ "/api/v1/replay/sessions/r1/bars": { status: 404, body: { error: { code: "not_found", message: "Replay session not found" } } } });
    renderWithProviders(<ReplayPlayerPage />, { route: "/replay/r1", path: "/replay/:id" });
    expect(await screen.findByText("Replay session not found")).toBeInTheDocument();
  });
});
