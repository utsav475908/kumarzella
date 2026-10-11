import { expect, test } from "@playwright/test";

/**
 * Needs the API started against the generated EURUSD test candles for 2024-01-16 (synthetic fixtures, not market
 * history); see README "End-to-end tests". The fixture day only has candles from 09:58 to 10:20, so the session opens
 * with no bars and the first step reveals the 09:55 bar. Expected numbers: a market buy of 10,000 then fills at the
 * 10:00 open on the ask (1.09010) plus 0.2 pip slippage = 1.09012; the 1.0905 target is first reached by the 10:03 bid
 * high, so it fills at 1.0905 in the same 5-minute bar. Gross (1.0905 - 1.09012) x 10,000 = 3.80, commission
 * 2 x 0.35 = 0.70, net 3.10.
 */
test("manual backtest: blind bars, a bracket order, results and a verified re-run", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Name").fill("Backtester");
  await page.getByLabel("Email").fill(`bt-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("e2e-password-1");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Performance" })).toBeVisible();

  await page.getByRole("link", { name: "Backtest" }).click();
  const form = page.getByRole("form", { name: "New backtest" });
  await form.getByLabel("Start date (UTC)").fill("2024-01-16");
  await form.getByRole("button", { name: "Start backtest" }).click();
  await expect(page.getByRole("heading", { name: /EURUSD/ })).toBeVisible();
  await expect(page.getByText("simulated", { exact: true })).toBeVisible();
  await expect(page.getByTestId("backtest-chart")).toHaveAttribute("data-bars", "0");
  await page.getByRole("button", { name: "Step", exact: true }).click();
  await expect(page.getByTestId("backtest-chart")).toHaveAttribute("data-bars", "1");
  await expect(page.getByTestId("backtest-account")).toContainText("Last bid 1.09 · ask 1.0901");

  const ticket = page.getByRole("form", { name: "Order ticket" });
  await ticket.getByRole("textbox", { name: "Units" }).fill("10000");
  await ticket.getByLabel(/^Stop-loss/).fill("1.0870");
  await ticket.getByLabel(/^Take-profit/).fill("1.0905");
  await ticket.getByRole("button", { name: "Buy" }).click();
  await expect(page.getByTestId("backtest-orders")).toContainText("buy market");

  // At 1 bar a second each tick reveals one bar, so playback pauses on the bar where the orders fill. (At 16 bars a
  // second this short fixture day would be over in one tick.)
  await page.getByLabel("Speed").selectOption("1");
  await page.getByRole("button", { name: "Play" }).click();
  const fills = page.getByTestId("backtest-fills");
  await expect(fills).toContainText("buy 10,000 @ 1.09012");
  await expect(fills).toContainText("sell 10,000 @ 1.0905");
  await expect(page.getByTestId("backtest-state")).toHaveText("paused");
  await expect(page.getByTestId("backtest-trades")).toContainText("+$3.10");
  await expect(page.getByTestId("backtest-orders")).toContainText("cancelled"); // the stop-loss (one cancels other)
  await page.screenshot({ path: "test-results/backtest-session.png", fullPage: true });

  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Finish session" }).click();
  await expect(page.getByTestId("backtest-state")).toHaveText("finished");
  const results = page.getByTestId("backtest-results");
  await expect(results).toContainText("+$3.10");
  await expect(results).toContainText("Small sample: 1 closed simulated trade.");
  await expect(results).toContainText("not evidence of future results");
  await page.getByRole("button", { name: "Re-run and verify" }).click();
  await expect(page.getByTestId("verify-result")).toContainText("Reproducible: 2 fills match (sim-1)");
  await page.screenshot({ path: "test-results/backtest-results.png", fullPage: true });

  // Simulated trades stay out of the real journal.
  await page.getByRole("link", { name: "← Backtests" }).click();
  await expect(page.getByTestId("backtest-list")).toContainText("completed");
  await page.getByRole("link", { name: "Journal", exact: true }).click();
  await expect(page.getByText("EURUSD")).toHaveCount(0);
});
