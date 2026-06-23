import { describe, expect, it } from "vitest";

import { fmtNum, formatTokens, timeAgo } from "./format";

describe("formatTokens", () => {
  it("compacts thousands", () => {
    expect(formatTokens(500)).toBe("500");
    expect(formatTokens(1500)).toBe("1.5k");
    expect(formatTokens(10000)).toBe("10k");
    expect(formatTokens(24000)).toBe("24k");
  });
});

describe("fmtNum", () => {
  it("rounds floats to four significant digits, passes through non-numbers", () => {
    expect(fmtNum(3.14159)).toBe("3.142");
    expect(fmtNum(42)).toBe("42");
    expect(fmtNum("label")).toBe("label");
  });
});

describe("timeAgo", () => {
  it("describes recent times relatively", () => {
    expect(timeAgo(new Date().toISOString())).toBe("just now");
    expect(timeAgo(new Date(Date.now() - 5 * 60_000).toISOString())).toBe("5m ago");
    expect(timeAgo(new Date(Date.now() - 3 * 3_600_000).toISOString())).toBe("3h ago");
    expect(timeAgo(new Date(Date.now() - 2 * 86_400_000).toISOString())).toBe("2d ago");
  });
});
