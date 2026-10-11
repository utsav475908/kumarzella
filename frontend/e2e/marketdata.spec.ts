import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.resolve(here, "../../backend/tests/fixtures/fixture_fx.csv");

/**
 * Needs the API started with EL_DUKASCOPY_BASE_URL=file://<dir> where <dir> was written by
 * `python -m tests.make_mirror <dir>` (generated test candles, not market history). See README "End-to-end tests".
 */
test("forex trade chart, MAE/MFE and a review replay", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Name").fill("FX Trader");
  await page.getByLabel("Email").fill(`fx-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("e2e-password-1");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Performance" })).toBeVisible();

  await page.getByRole("link", { name: "Accounts" }).click();
  await page.getByLabel("Name").fill("FX");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("FX").first()).toBeVisible();

  await page.getByRole("link", { name: "Import", exact: true }).click();
  await page.getByLabel("CSV file").setInputFiles(FIXTURE);
  await page.getByRole("button", { name: "Upload" }).click();
  await page.getByLabel("Timezone of timestamps without an offset").selectOption("UTC");
  await page.getByRole("button", { name: "Validate and preview" }).click();
  await page.getByRole("button", { name: "Import 2 executions" }).click();
  await expect(page.getByText("Import complete.")).toBeVisible();

  await page.getByRole("link", { name: "Journal", exact: true }).click();
  await page.getByRole("link", { name: "EURUSD" }).first().click();
  await expect(page.getByTestId("trade-candles")).toHaveAttribute("data-bars", "10");
  const ex = page.getByTestId("trade-excursions");
  await expect(ex).toContainText("-$5.00");
  await expect(ex).toContainText("$8.00");
  await page.screenshot({ path: "test-results/trade-candles.png", fullPage: true });

  await page.getByRole("button", { name: "Replay this trade" }).click();
  await expect(page.getByText("Review mode")).toBeVisible();
  await expect(page.getByTestId("replay-state")).toHaveText("ready");
  await page.getByLabel("Speed").selectOption("16");
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.getByTestId("replay-state")).toHaveText("completed", { timeout: 15_000 });
  await expect(page.getByTestId("replay-chart")).toHaveAttribute("data-bars", "10");
  await page.screenshot({ path: "test-results/replay.png", fullPage: true });

  // Saved and resumable
  await page.getByRole("link", { name: "← Replays" }).click();
  await expect(page.getByTestId("replay-list")).toContainText("Review EURUSD long");
  await expect(page.getByTestId("replay-list")).toContainText("completed");
});
