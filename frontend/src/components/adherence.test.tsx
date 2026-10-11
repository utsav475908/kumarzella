import "../test/chartMock";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TradeAdherencePanel } from "./Adherence";
import { TradeChartPanel } from "./TradeChartPanel";
import { ReportsPage } from "../pages/Reports";
import { validateDraft } from "../pages/PlaybookRules";
import { chartCalls } from "../test/chartMock";
import { tradeDetailFixture } from "../test/fixtures";
import { mockFetch, renderWithProviders } from "../test/utils";

const assessment = (answer: boolean | null) => ({
  playbook_version_id: "v1", version: 1, outcome: answer === null ? "incomplete" : answer ? "followed" : "broken",
  verified: [
    { key: "instrument", label: "Instrument allowed", status: "pass", detail: "EURUSD is in EURUSD" },
    { key: "stop_respected", label: "Loss within planned risk", status: "unknown", detail: "Needs a closed trade with a known initial risk" },
  ],
  checklist: [{ id: "abc12345", phase: "pre", text: "Waited for the range", answer }],
  counts: {},
});

describe("trade adherence panel", () => {
  it("keeps verified rules and self-assessed answers apart and saves an answer", async () => {
    const calls = mockFetch({
      "/api/v1/trades/t1/adherence": { body: { trade_id: "t1", playbook_id: "p1", playbook_name: "ORB", current_version: 2, assessment: assessment(null) } },
      "/api/v1/trades/t1/checklist": (_u, init) => ({
        body: { trade_id: "t1", playbook_id: "p1", playbook_name: "ORB", current_version: 2,
                assessment: assessment(JSON.parse(String(init?.body)).answers[0].answer) },
      }),
    });
    renderWithProviders(<TradeAdherencePanel d={tradeDetailFixture} />);
    const panel = await screen.findByTestId("trade-adherence");
    expect(panel).toHaveTextContent("Incomplete");
    expect(panel).toHaveTextContent("Verified from trade data");
    expect(panel).toHaveTextContent("? unknown");
    expect(panel).toHaveTextContent("judged by version 1"); // the playbook moved on to v2
    const group = screen.getByRole("group", { name: "Waited for the range" });
    await userEvent.click(within(group).getByRole("button", { name: "No" }));
    await waitFor(() => expect(panel).toHaveTextContent("Broken"));
    const put = calls.find((c) => c.init?.method === "PUT")!;
    expect(JSON.parse(String(put.init?.body))).toEqual({ answers: [{ item_id: "abc12345", answer: false }] });
    expect(within(group).getByRole("button", { name: "No" })).toHaveAttribute("aria-pressed", "true");
  });

  it("explains what to do when no playbook is assigned", async () => {
    mockFetch({ "/api/v1/trades/t1/adherence": { body: { trade_id: "t1", playbook_id: null, playbook_name: null, assessment: null } } });
    renderWithProviders(<TradeAdherencePanel d={tradeDetailFixture} />);
    expect(await screen.findByText(/Assign a playbook/)).toBeInTheDocument();
  });
});

describe("playbook rules form validation", () => {
  const base = {
    instruments: "", timeframe: "", sessions: [], start: "", end: "", require_stop: false, max_risk: "", min_rr: "", max_trades: "",
    pre: [], post: [], change_note: "", entry_rules: "", exit_rules: "", stop_rules: "", target_rules: "", sizing_rules: "",
    invalidation: "", valid_examples: "", invalid_examples: "",
  };
  it("accepts an empty draft and rejects bad limits", () => {
    expect(validateDraft(base)).toEqual({});
    const e = validateDraft({ ...base, max_risk: "-5", min_rr: "0", max_trades: "1.5", start: "9", pre: [{ id: "", text: " " }] });
    expect(Object.keys(e).sort()).toEqual(["checklist", "max_risk", "max_trades", "min_rr", "window"]);
    expect(validateDraft({ ...base, start: "9", end: "9" }).window).toBe("The window is empty");
  });
});

describe("chart notes", () => {
  it("adds a note at the clicked candle", async () => {
    const T0 = 1705399200;
    const calls = mockFetch({
      "/api/v1/trades/t1/chart": { body: {
        status: "ready", symbol: "EURUSD", timeframe: "1m", side: "bid", bars: [{ t: T0, o: "1.09", h: "1.091", l: "1.089", c: "1.0905", v: "1" }],
        markers: [], gaps: [], planned_stop_price: null, planned_target_price: null, excursions: null, notes: [],
        coverage: { status: "ready", pending_days: [], failed_days: [], unpublished_days: [] },
        provider: { name: "dukascopy", display_name: "Dukascopy", asset_classes: ["forex"], granularity: "1m", sides: ["bid"], attribution: "", licence_note: "", volume_note: "" },
      } },
      "/api/v1/trades/t1/annotations": (_u, init) => init?.method === "POST"
        ? { status: 201, body: { id: "n1", trade_id: "t1", created_at: "2024-01-16T11:00:00Z", price: "1.0905", ...JSON.parse(String(init.body)) } }
        : { body: [] },
    });
    renderWithProviders(<TradeChartPanel d={tradeDetailFixture} />);
    await screen.findByTestId("trade-candles");
    act(() => chartCalls.click!({ time: T0 }));
    await userEvent.type(await screen.findByLabelText(/Chart note at/), "Entered before the close");
    await userEvent.selectOptions(screen.getByLabelText("Note type"), "mistake");
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "POST")).toBe(true));
    const post = calls.find((c) => c.init?.method === "POST")!;
    expect(JSON.parse(String(post.init?.body))).toEqual({ bar_time: "2024-01-16T10:00:00.000Z", price: "1.0905", kind: "mistake", text: "Entered before the close" });
  });
});

describe("reports page", () => {
  it("renders strategy comparison and adherence from server figures", async () => {
    const stat = { closed_trades: 2, net_pnl: "-56.15", wins: 1, losses: 1, win_rate: "0.5000", profit_factor: "0.7220", expectancy: "-28.08", avg_r: null };
    mockFetch({
      "/api/v1/analytics/reports": { body: {
        currency: "USD", currencies_available: ["USD"], excluded_other_currency_trades: 0, open_trades: 0, includes_demo_data: false,
        warnings: ["Small sample: 2 closed trades. Treat ratios as unreliable."], summary: stat,
        playbooks: [{ ...stat, key: "p1", label: "ORB", avg_mae: null, avg_mfe: null, trades_with_excursions: 0,
                      adherence: { followed: 1, broken: 1, incomplete: 0, no_rules: 0 }, followed_rate: "0.5000" }],
        adherence: {
          assessed_trades: 2, unassessed_trades: 0, counts: { followed: 1, broken: 1, incomplete: 0, no_rules: 0 }, followed_rate: "0.5000",
          outcomes: [{ ...stat, closed_trades: 1, net_pnl: "145.85", outcome: "followed" }, { ...stat, closed_trades: 1, net_pnl: "-202.00", outcome: "broken" }],
          rules: [{ key: "instrument", label: "Instrument allowed", passed: 1, failed: 1, unknown: 0, fail_rate: "0.5000",
                    net_pnl_when_passed: "145.85", net_pnl_when_failed: "-202.00", avg_r_when_passed: null, avg_r_when_failed: null }],
          checklist: [], broken_trades: [{ trade_id: "t9", symbol: "TSLA", closed_at: "2024-03-05T16:20:00Z", net_pnl: "-202.00", r_multiple: null,
                                           playbook_name: "ORB", version: 1, failed_rules: ["Instrument allowed"], checklist_no: [] }],
          note: "Adherence measures whether a trade met its playbook's rules, not whether it made money.",
        },
        by_tag: [], by_holding_time: [], by_month: [], costs_by_symbol: [],
      } },
    });
    renderWithProviders(<ReportsPage />, { route: "/reports" });
    expect(await screen.findByText("Small sample: 2 closed trades. Treat ratios as unreliable.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ORB" })).toHaveAttribute("href", "/playbooks/p1");
    const adh = screen.getByTestId("adherence-summary");
    expect(adh).toHaveTextContent("50.0%");
    expect(adh).toHaveTextContent("-$202.00");
    expect(within(adh).getByRole("link", { name: /TSLA/ })).toHaveAttribute("href", "/trades/t9");
    expect(adh).toHaveTextContent("not whether it made money");
  });
});
