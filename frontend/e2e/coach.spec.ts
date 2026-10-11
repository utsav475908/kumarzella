import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.resolve(here, "../../backend/tests/fixtures/fixture_a.csv");

/** Calls the API from the page, with the session cookie and CSRF header the app itself uses. */
async function call(page: Page, method: string, url: string, body?: unknown, file?: string) {
  const csv = file ? fs.readFileSync(file, "utf8") : null;
  return page.evaluate(async ({ method, url, body, csv }) => {
    const csrf = decodeURIComponent(document.cookie.match(/(?:^|; )el_csrf=([^;]*)/)?.[1] ?? "");
    const init: RequestInit = { method, credentials: "include", headers: { "X-CSRF-Token": csrf } };
    if (csv !== null) {
      const fd = new FormData();
      for (const [k, v] of Object.entries(body as Record<string, string>)) fd.append(k, v);
      fd.append("file", new Blob([csv], { type: "text/csv" }), "fixture_a.csv");
      init.body = fd;
    } else if (body !== undefined) {
      init.body = JSON.stringify(body);
      (init.headers as Record<string, string>)["Content-Type"] = "application/json";
    }
    const r = await fetch(url, init);
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, { method, url, body, csv });
}

async function registerAndImport(page: Page) {
  await page.goto("/register");
  await page.getByLabel("Name").fill("Coach E2E");
  await page.getByLabel("Email").fill(`coach-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("e2e-password-1");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Performance" })).toBeVisible();
  await call(page, "GET", "/api/v1/auth/csrf");
  const acct = await call(page, "POST", "/api/v1/accounts", { name: "Main" });
  const up = await call(page, "POST", "/api/v1/imports", { account_id: acct.body.id }, FIXTURE);
  expect(up.status).toBe(201);
  await call(page, "POST", `/api/v1/imports/${up.body.id}/preview`, { mapping: up.body.suggested_mapping, options: {} });
  expect((await call(page, "POST", `/api/v1/imports/${up.body.id}/commit`)).status).toBeLessThan(300);
}

/**
 * With no API key the coach must say it is switched off. With the API pointed at the scripted test server
 * (`python -m tests.fake_claude`, see README "AI coach"), the whole path runs: the real SDK call, the tool loop, the
 * evidence check, storage and the UI. The scripted server copies figures from the tool result; the expected numbers
 * are the hand-computed fixture values (net 260.45 over 5 closed trades, 75% win rate).
 */
test("AI coach: answers cite evidence from the journal, or the page explains how to turn it on", async ({ page }) => {
  await registerAndImport(page);
  const status = await call(page, "GET", "/api/v1/ai/status");
  await page.getByRole("link", { name: "AI coach" }).click();
  await expect(page.getByRole("heading", { name: "AI coach" })).toBeVisible();

  if (!status.body.enabled) {
    await expect(page.getByTestId("coach-setup")).toContainText("switched off");
    await page.goto("/trades");
    await page.getByRole("link", { name: "TSLA" }).click();
    await expect(page.getByTestId("coach-setup")).toBeVisible();
    return;
  }

  await page.getByLabel("Question").fill("How am I doing overall?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = page.getByTestId("coach-answer");
  await expect(answer).toContainText("Net P&L is $260.45 over 5 closed trades", { timeout: 30_000 });
  await expect(answer).toContainText("Win rate: 75.0%");
  await expect(answer).toContainText("Every figure checked");
  await answer.getByRole("button", { name: "Evidence E1" }).first().click();
  const ev = page.getByTestId("coach-evidence");
  await expect(ev).toContainText("Performance summary (all trades)");
  await expect(ev).toContainText("+$260.45");
  await expect(ev).toContainText("75.0%");
  await expect(page.getByTestId("coach-history")).toContainText("How am I doing overall?");
  await page.screenshot({ path: "test-results/coach.png", fullPage: true });

  // Trade page: the review is stored against the trade and shown again after a reload.
  await page.goto("/trades");
  await page.getByRole("link", { name: "TSLA" }).click();
  await page.getByRole("button", { name: "Review this trade" }).click();
  await expect(page.getByTestId("coach-answer")).toContainText("Net P&L is $260.45", { timeout: 30_000 });
  await page.reload();
  await expect(page.getByTestId("coach-answer")).toContainText("Review of TSLA short trade on 2024-03-05");
  await expect(page.getByRole("button", { name: "Review again" })).toBeVisible();
  await page.getByTestId("coach-answer").scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/coach-trade.png" });
});
