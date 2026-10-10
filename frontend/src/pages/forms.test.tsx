import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { registerSchema } from "./Auth";
import { accountSchema, AccountsPage } from "./Accounts";
import { validateMapping } from "./ImportWizard";
import { LoginPage } from "./Auth";
import { mockFetch, renderWithProviders } from "../test/utils";

describe("form validation", () => {
  it("register schema enforces password strength", () => {
    expect(registerSchema.safeParse({ display_name: "A", email: "a@b.co", password: "abcdefghijkl" }).success).toBe(false);
    expect(registerSchema.safeParse({ display_name: "A", email: "a@b.co", password: "abcdefghij-1" }).success).toBe(true);
    expect(registerSchema.safeParse({ display_name: "", email: "nope", password: "x" }).error?.issues.map((i) => i.path[0])).toEqual(expect.arrayContaining(["display_name", "email", "password"]));
  });

  it("account schema rejects malformed numbers and currency", () => {
    const base = { name: "Main", broker: "", account_type: "live", base_currency: "USD", accounting_policy: "fifo", starting_balance: "", max_risk_per_trade: "", daily_loss_limit: "" };
    expect(accountSchema.safeParse(base).success).toBe(true);
    expect(accountSchema.safeParse({ ...base, starting_balance: "1,000" }).success).toBe(false);
    expect(accountSchema.safeParse({ ...base, base_currency: "usd" }).success).toBe(false);
  });

  it("import mapping requires symbol/qty/price, a timestamp and a side source", () => {
    expect(validateMapping({}, false)).toEqual(expect.arrayContaining([
      "Map a column to Symbol", "Map a column to Quantity", "Map a column to Price",
      "Map a date/time column (combined, or a separate date column)",
      "Map a side column, or derive side from the quantity sign",
    ]));
    expect(validateMapping({ timestamp: "T", symbol: "S", quantity: "Q", price: "P" }, true)).toEqual([]);
    expect(validateMapping({ timestamp: "T", symbol: "S", quantity: "Q", price: "Q", side: "X" }, false)).toContain("Each CSV column can only be mapped once");
  });

  it("login shows field errors without calling the API", async () => {
    const calls = mockFetch({});
    renderWithProviders(<LoginPage />);
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid email")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("login surfaces the server's error message", async () => {
    mockFetch({ "/api/v1/auth/login": { status: 401, body: { error: { code: "invalid_credentials", message: "Invalid email or password" } } } });
    renderWithProviders(<LoginPage />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.co" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
  });

  it("account form does not show success until the server confirms, and shows conflicts", async () => {
    mockFetch({
      "/api/v1/accounts": (_u, init) => init?.method === "POST"
        ? { status: 409, body: { error: { code: "conflict", message: "An account with this name already exists" } } }
        : { body: [] },
    });
    renderWithProviders(<AccountsPage />);
    expect(await screen.findByText("No accounts yet")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Main" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("already exists"));
  });
});
