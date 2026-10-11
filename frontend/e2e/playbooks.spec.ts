import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.resolve(here, "../../backend/tests/fixtures/fixture_fx.csv");

test("versioned playbook rules, trade adherence with a checklist, and the reports page", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Name").fill("Playbook Trader");
  await page.getByLabel("Email").fill(`pb-${Date.now()}@example.com`);
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

  // Create a playbook and write version 1 of its rules
  await page.getByRole("link", { name: "Playbooks" }).click();
  await page.getByLabel("Setup name").fill("London breakout");
  await page.getByRole("button", { name: "Create playbook" }).click();
  await expect(page.getByRole("button", { name: "Save as version 2" })).toBeVisible(); // v1 is the empty first version
  await page.getByLabel("Instruments (comma separated, empty = any)").fill("EURUSD, GBPUSD");
  await page.getByLabel("Initial stop (or risk amount) required").check();
  await page.getByRole("button", { name: "+ Add item" }).first().click();
  await page.getByRole("textbox", { name: "Pre-trade checklist item 1" }).fill("Asian range marked before entry");
  await page.getByRole("textbox", { name: "Entry rules" }).fill("Enter on a 5-minute close outside the Asian range.");
  await page.getByLabel("What changed (optional)").fill("Initial rules");
  await page.getByRole("button", { name: "Save as version 2" }).click();
  const rules = page.getByTestId("rules-view");
  await expect(rules).toContainText("EURUSD, GBPUSD");
  await expect(rules).toContainText("Asian range marked before entry");
  await expect(page.getByTestId("playbook-versions")).toContainText("Initial rules");

  // Assign it to the trade, record the stop, and answer the checklist
  await page.getByRole("link", { name: "Journal", exact: true }).click();
  await page.getByRole("link", { name: "EURUSD" }).first().click();
  await page.getByLabel("Strategy playbook").selectOption({ label: "London breakout" });
  await page.getByLabel("Planned stop").fill("1.0895");
  await page.getByRole("button", { name: "Save journal" }).click();
  const adh = page.getByTestId("trade-adherence");
  await expect(adh).toContainText("rules v2");
  await expect(adh).toContainText("Incomplete");
  await expect(adh).toContainText("EURUSD is in EURUSD, GBPUSD");
  await page.getByRole("group", { name: "Asian range marked before entry" }).getByRole("button", { name: "Yes" }).click();
  await expect(adh).toContainText("Followed");
  await page.screenshot({ path: "test-results/trade-adherence.png", fullPage: true });

  // A new version does not re-judge the trade
  await page.getByRole("link", { name: "London breakout" }).click();
  await page.getByRole("tab", { name: "Rules" }).click();
  await page.getByRole("button", { name: "Edit rules" }).click();
  await page.getByLabel("Instruments (comma separated, empty = any)").fill("GBPUSD");
  await page.getByRole("button", { name: "Save as version 3" }).click();
  await expect(page.getByTestId("rules-view")).not.toContainText("EURUSD");
  await page.getByRole("tab", { name: "Report" }).click();
  await expect(page.getByTestId("adherence-summary")).toContainText("100.0%");

  // Reports page
  await page.getByRole("link", { name: "Reports" }).click();
  await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();
  const row = page.getByRole("row", { name: /London breakout/ });
  await expect(row).toContainText("+$4.00");
  await expect(row).toContainText("100.0% (1/1)");
  await expect(page.getByText("Trading costs by symbol")).toBeVisible();
  await page.screenshot({ path: "test-results/reports.png", fullPage: true });
});
