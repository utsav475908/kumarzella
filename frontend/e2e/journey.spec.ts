import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.resolve(here, "../../backend/tests/fixtures/fixture_a.csv");

test("register, import a CSV, read the dashboard, drill into a losing day and journal a trade", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Name").fill("E2E Trader");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-password-1");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Performance" })).toBeVisible();
  await expect(page.getByText("No closed trades match these filters")).toBeVisible();

  // Account
  await page.getByRole("link", { name: "Accounts" }).click();
  await page.getByLabel("Name").fill("Main");
  await page.getByLabel("Max risk per trade").fill("500");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Main").first()).toBeVisible();

  // Import wizard
  await page.getByRole("link", { name: "Import", exact: true }).click();
  await page.getByLabel("CSV file").setInputFiles(FIXTURE);
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByText("Map columns · fixture_a.csv (14 rows)")).toBeVisible();
  await page.getByRole("button", { name: "Validate and preview" }).click();
  await expect(page.getByText("12 ready to import")).toBeVisible();
  await expect(page.getByText("1 rejected")).toBeVisible();
  await expect(page.getByText("1 duplicates (skipped)")).toBeVisible();
  await page.getByRole("button", { name: "Import 12 executions" }).click();
  await expect(page.getByText("Import complete.")).toBeVisible();
  await expect(page.getByText("Trades created: 6")).toBeVisible();

  // Dashboard figures come from the API (hand-computed fixture: net 260.45, 75% win rate)
  await page.getByRole("link", { name: "View dashboard" }).click();
  const kpis = page.getByTestId("kpis");
  await expect(kpis).toContainText("+$260.45");
  await expect(kpis).toContainText("75.0%");
  await expect(kpis).toContainText("2.29");
  await expect(kpis).toContainText("$202.00");
  await page.screenshot({ path: "test-results/dashboard.png", fullPage: true });

  // Drill-down: losing day in the calendar opens the journal for that day with filters preserved
  await page.getByRole("gridcell", { name: /^5/ }).first().click();
  await expect(page).toHaveURL(/date_from=2024-03-05&date_to=2024-03-05/);
  await expect(page.getByText("1 trades")).toBeVisible();
  await expect(page.getByRole("link", { name: "TSLA" })).toBeVisible();

  // Trade detail + journal
  await page.getByRole("link", { name: "TSLA" }).click();
  await expect(page.getByRole("heading", { name: /TSLA/ })).toBeVisible();
  await expect(page.getByText("-$202.00").first()).toBeVisible();
  await page.getByLabel("Planned stop").fill("202");
  await page.getByRole("button", { name: "Save journal" }).click();
  await expect(page.getByText("Saved")).toBeVisible();
  // risk = (202 - 200) * 50 = 100 ; R = -202 / 100 = -2.02
  await expect(page.getByText("-2.02R").first()).toBeVisible();
  await page.getByLabel("New note").fill("Shorted into support.");
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByText("Shorted into support.")).toBeVisible();
  await page.screenshot({ path: "test-results/trade.png", fullPage: true });

  // Filter consistency: short-only dashboard
  await page.goto("/?direction=short");
  await expect(page.getByTestId("kpis")).toContainText("-$81.20");
});

test("API failure is shown, not hidden", async ({ page }) => {
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ status: 500, body: JSON.stringify({ error: { code: "internal_error", message: "Boom", details: null } }) }));
  await page.goto("/");
  await expect(page.getByText("Could not load this data")).toBeVisible();
  await expect(page.getByText("Boom")).toBeVisible();
});
