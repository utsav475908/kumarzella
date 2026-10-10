import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { DashboardPage } from "./Dashboard";
import { MonthCalendar } from "../components/MonthCalendar";
import { mockFetch, renderWithProviders } from "../test/utils";
import { dashboardPayload } from "../test/fixtures";

const page = (items: unknown[] = []) => ({ items, total: items.length, page: 1, page_size: 8 });

describe("Dashboard", () => {
  it("renders KPI values exactly as returned by the analytics API", async () => {
    mockFetch({ "/api/v1/analytics/dashboard": { body: dashboardPayload() }, "/api/v1/trades": { body: page() } });
    renderWithProviders(<DashboardPage />);
    const kpis = await screen.findByTestId("kpis");
    expect(within(kpis).getByText("+$9.00")).toBeInTheDocument();
    expect(within(kpis).getByText("50.0%")).toBeInTheDocument();
    expect(within(kpis).getByText("1.90")).toBeInTheDocument();
    expect(within(kpis).getByText("$10.00")).toBeInTheDocument();
  });

  it("shows an explicit error state when the API fails", async () => {
    mockFetch({ "/api/v1/analytics/dashboard": { status: 500, body: { error: { code: "internal_error", message: "Database unavailable" } } }, "/api/v1/trades": { body: page() } });
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("Could not load this data")).toBeInTheDocument();
    expect(screen.getByText("Database unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("kpis")).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no closed trades", async () => {
    const empty = dashboardPayload({ summary: { ...dashboardPayload().summary, closed_trades: 0 }, open_trades: 2 });
    mockFetch({ "/api/v1/analytics/dashboard": { body: empty }, "/api/v1/trades": { body: page() } });
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("No closed trades match these filters")).toBeInTheDocument();
    expect(screen.getByText(/2 open trades are not included/)).toBeInTheDocument();
  });

  it("rejects responses that do not match the schema instead of rendering bad numbers", async () => {
    mockFetch({ "/api/v1/analytics/dashboard": { body: { summary: { net_pnl: 12 } } }, "/api/v1/trades": { body: page() } });
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("The server returned data in an unexpected shape.")).toBeInTheDocument();
  });

  it("changing a filter updates the URL and refetches every panel with the same filter", async () => {
    const calls = mockFetch({ "/api/v1/analytics/dashboard": { body: dashboardPayload() }, "/api/v1/trades": { body: page() } });
    renderWithProviders(<DashboardPage />, { route: "/?symbol=AAA" });
    await screen.findByTestId("kpis");
    fireEvent.change(screen.getByLabelText("Direction"), { target: { value: "short" } });
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/?symbol=AAA&direction=short"));
    await waitFor(() => {
      const dash = calls.filter((c) => c.url.pathname === "/api/v1/analytics/dashboard").at(-1)!;
      const trades = calls.filter((c) => c.url.pathname === "/api/v1/trades").at(-1)!;
      for (const c of [dash, trades]) {
        expect(c.url.searchParams.get("direction")).toBe("short");
        expect(c.url.searchParams.get("symbol")).toBe("AAA");
      }
    });
  });
});

describe("MonthCalendar", () => {
  it("drills into a day and disables days without trades", () => {
    const picked: string[] = [];
    renderWithProviders(
      <MonthCalendar month="2024-03" currency="USD" onSelect={(d) => picked.push(d)}
        days={[{ date: "2024-03-05", net_pnl: "-202.00", gross_pnl: "-200.00", fees: "2.00", trades: 1, wins: 0, losses: 1, cumulative: "-202.00" }]} />,
    );
    const cell = screen.getByTitle(/2024-03-05: -\$202.00/);
    fireEvent.click(cell);
    expect(picked).toEqual(["2024-03-05"]);
    expect(screen.getByTitle("2024-03-06")).toBeDisabled();
  });
});
