import { describe, expect, it } from "vitest";
import { fmtDuration, fmtMoney, fmtPct, fmtR, sign, trimDecimal } from "./format";
import { filtersToSearch, readFilters } from "./filters";

describe("format", () => {
  it("formats API decimal strings without changing their value", () => {
    expect(fmtMoney("260.45")).toBe("$260.45");
    expect(fmtMoney("-202.00")).toBe("-$202.00");
    expect(fmtMoney("120.8", "USD", { sign: true })).toBe("+$120.80");
    expect(fmtMoney(null)).toBe("—");
    expect(fmtPct("0.75")).toBe("75.0%");
    expect(fmtR("-2.0200")).toBe("-2.02R");
    expect(fmtDuration(3300)).toBe("55m");
    expect(trimDecimal("202.0000000000")).toBe("202");
    expect(trimDecimal("0.2500")).toBe("0.25");
  });
  it("derives sign from strings, including negative zero", () => {
    expect(sign("-0.00")).toBe(0);
    expect(sign("0")).toBe(0);
    expect(sign("-1.5")).toBe(-1);
    expect(sign("3")).toBe(1);
  });
});

describe("filters", () => {
  it("round-trips multi-value filters through the URL", () => {
    const f = readFilters(new URLSearchParams("symbol=AAPL&symbol=TSLA&direction=short&page=3&foo=bar"));
    expect(f).toEqual({ symbol: ["AAPL", "TSLA"], direction: "short" });
    expect(filtersToSearch(f, { date_from: "2024-03-05" })).toBe("?symbol=AAPL&symbol=TSLA&direction=short&date_from=2024-03-05");
  });
});
