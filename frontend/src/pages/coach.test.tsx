import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CoachPage, TradeCoachPanel } from "./Coach";
import { tradeDetailFixture } from "../test/fixtures";
import { mockFetch, renderWithProviders } from "../test/utils";

const on = { enabled: true, model: "claude-opus-5-5", fallbacks: true, reason: null, limits: { requests_per_hour: 30, tool_rounds: 6 } };
const evidence = {
  ref: "E1", tool: "performance_summary", label: "Performance summary (all trades)", input: {}, filters: { direction: "short" },
  sample_size: 5, result: { currency: "USD", summary: { closed_trades: 5, net_pnl: "260.45", win_rate: "0.7500" } },
};
const review = (over: Record<string, unknown> = {}) => ({
  id: "r1", kind: "ask", trade_id: null, period_from: null, period_to: null, question: "How am I doing?",
  status: "ok", created_at: "2024-03-09T10:00:00Z",
  answer: "You made $260.45 net [E1].\n- Win rate was 75% [E1].", limitations: ["Small sample: 5 closed trades."],
  suggested_tags: [], cited: ["E1"], unsupported_numbers: [], model: "claude-opus-5-5",
  usage: { tool_calls: 1, input_tokens: 2400, output_tokens: 600, latency_ms: 4200 }, evidence: [evidence], ...over,
});

describe("AI coach page", () => {
  it("explains how to switch the coach on when no key is configured", async () => {
    mockFetch({ "/api/v1/ai/status": { body: { ...on, enabled: false, model: null, reason: "No Anthropic API key is configured on the server (EL_ANTHROPIC_API_KEY)." } } });
    renderWithProviders(<CoachPage />);
    const setup = await screen.findByTestId("coach-setup");
    expect(setup).toHaveTextContent("switched off");
    expect(setup).toHaveTextContent("ANTHROPIC_API_KEY=");
    expect(screen.queryByRole("form", { name: "Ask the coach" })).not.toBeInTheDocument();
  });

  it("asks a question and shows the answer with its evidence", async () => {
    const calls = mockFetch({
      "/api/v1/ai/status": { body: on },
      "/api/v1/ai/ask": { status: 201, body: review() },
      "/api/v1/ai/reviews/r1": { body: review() },
      "/api/v1/ai/reviews": { body: [] },
    });
    renderWithProviders(<CoachPage />);
    const form = await screen.findByRole("form", { name: "Ask the coach" });
    await userEvent.type(within(form).getByLabelText("Question"), "How am I doing?");
    await userEvent.click(within(form).getByRole("button", { name: "Ask" }));
    const answer = await screen.findByTestId("coach-answer");
    expect(answer).toHaveTextContent("You made $260.45 net");
    expect(answer).toHaveTextContent("Every figure checked");
    expect(answer).toHaveTextContent("Small sample: 5 closed trades.");
    const post = calls.find((c) => c.url.pathname === "/api/v1/ai/ask")!;
    expect(JSON.parse(String(post.init?.body))).toEqual({ question: "How am I doing?" });
    // a citation opens the evidence, with the figures the coach saw
    await userEvent.click(within(answer).getAllByRole("button", { name: "Evidence E1" })[0]);
    const ev = screen.getByTestId("coach-evidence");
    expect(ev).toHaveTextContent("filters: direction short");
    expect(ev).toHaveTextContent("+$260.45");
    expect(ev).toHaveTextContent("75.0%");
  });

  it("warns loudly when figures couldn't be traced", async () => {
    mockFetch({
      "/api/v1/ai/status": { body: on },
      "/api/v1/ai/reviews/r2": { body: review({ id: "r2", status: "ungrounded", answer: "You made $999 [E1] [E7].", unsupported_numbers: ["$999"] }) },
      "/api/v1/ai/reviews": { body: [{ id: "r2", kind: "ask", trade_id: null, period_from: null, period_to: null, question: "Old question", status: "ungrounded", created_at: "2024-03-09T10:00:00Z" }] },
    });
    renderWithProviders(<CoachPage />);
    await userEvent.click(await screen.findByRole("button", { name: /Old question/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be traced to your data, so don't rely on them: $999");
    expect(screen.getByTestId("coach-answer")).toHaveTextContent("E7?");
  });
});

describe("AI review on the trade page", () => {
  it("reviews the trade and adds a suggested tag only when clicked", async () => {
    const tagged = review({
      kind: "trade_review", trade_id: "t1", question: "Review of EURUSD long trade on 2024-01-16",
      suggested_tags: [
        { name: "FOMO", category: "emotion", tag_id: "g1", new: false, already_applied: false, reason: "Entered after a spike [E1]." },
        { name: "Late exit", category: "mistake", tag_id: null, new: true, already_applied: false, reason: "Held past target." },
      ],
    });
    const calls = mockFetch({
      "/api/v1/ai/status": { body: on },
      "/api/v1/ai/reviews": { body: [] },
      "/api/v1/ai/trades/t1/review": { status: 201, body: tagged },
      "/api/v1/tags": { status: 201, body: { id: "g2", name: "Late exit", category: "mistake", color: null, trade_count: 0 } },
      "/api/v1/trades/t1": { body: tradeDetailFixture },
    });
    renderWithProviders(<TradeCoachPanel d={tradeDetailFixture} />);
    await userEvent.click(await screen.findByRole("button", { name: "Review this trade" }));
    const tags = await screen.findByTestId("suggested-tags");
    expect(calls.some((c) => c.init?.method === "PATCH")).toBe(false);
    await userEvent.click(within(tags).getByRole("button", { name: "Add tag" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "PATCH")).toBe(true));
    expect(JSON.parse(String(calls.find((c) => c.init?.method === "PATCH")!.init?.body))).toEqual({ tag_ids: ["g1"] });
    expect(await within(tags).findByRole("button", { name: "Added" })).toBeDisabled();
    await userEvent.click(within(tags).getByRole("button", { name: "Create and add" }));
    await waitFor(() => expect(calls.filter((c) => c.init?.method === "PATCH")).toHaveLength(2));
    const created = calls.find((c) => c.url.pathname === "/api/v1/tags" && c.init?.method === "POST")!;
    expect(JSON.parse(String(created.init?.body))).toEqual({ name: "Late exit", category: "mistake" });
    expect(JSON.parse(String(calls.filter((c) => c.init?.method === "PATCH")[1].init?.body))).toEqual({ tag_ids: ["g1", "g2"] });
  });
});
