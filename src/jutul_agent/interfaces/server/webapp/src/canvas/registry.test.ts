import { describe, expect, it } from "vitest";

import { hasOpenableUrl, registerPanel } from "./registry";
import type { View } from "../store";

function view(overrides: Partial<View>): View {
  return { id: "v1", url: "https://example.com/x.html", title: "x", kind: "report", nonce: 0, ...overrides };
}

describe("hasOpenableUrl", () => {
  it("is true for an image view", () => {
    expect(hasOpenableUrl(view({ kind: "image" }))).toBe(true);
  });

  it("is true for an iframe'd kind (no registered native panel)", () => {
    expect(hasOpenableUrl(view({ kind: "report" }))).toBe(true);
  });

  it("is false for a kind backed by a registered native panel", () => {
    // A native panel (e.g. the map) renders live component state the view's
    // `url` never reflects — it's a stub artifact, not a real page to open.
    registerPanel("native-test-kind", () => null as never);
    expect(hasOpenableUrl(view({ kind: "native-test-kind" }))).toBe(false);
  });
});
