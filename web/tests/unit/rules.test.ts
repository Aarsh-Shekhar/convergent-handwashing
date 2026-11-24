// The few rules that live in the browser (everything about scores and points is tested in Python).
import { describe, expect, it } from "vitest";
import { heatFill, zoneState } from "../../src/components/HandFigure";
import { currentItem } from "../../src/components/Nav";
import { viewOf } from "../../src/mode";
import { missedText } from "../../src/wash";

describe("zoneState", () => {
  it("is washed only at the full scrub time, partly below it, missed at zero", () => {
    expect(zoneState(1, true)).toBe("washed");
    expect(zoneState(0.999, true)).toBe("partly");
    expect(zoneState(0, true)).toBe("missed");
  });
  it("is unknown, never missed, when nothing was recognized or the value is absent", () => {
    expect(zoneState(0, false)).toBe("unknown");
    expect(zoneState(1, false)).toBe("unknown");
    expect(zoneState(undefined, true)).toBe("unknown");
  });
});

describe("heatFill", () => {
  it("gives no data its own neutral colour, different from 0%", () => {
    expect(heatFill(null)).toBe("var(--seq-0)");
    expect(heatFill(0)).toBe("var(--seq-1)");
  });
  it("steps from light to dark and stays in range at 100%", () => {
    expect([0.19, 0.2, 0.5, 0.99, 1].map(heatFill)).toEqual(["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-5)", "var(--seq-5)"]);
  });
});

describe("views and navigation", () => {
  it("takes the view from the address", () => {
    expect(viewOf("/kid")).toBe("kid");
    expect(viewOf("/kid/wash/ses_1-w001")).toBe("kid");
    expect(viewOf("/kidding")).toBe("parent");
    expect(viewOf("/")).toBe("parent");
  });
  it("keeps a wash under Washes, and a kid's wash under Home", () => {
    expect(currentItem("/washes/ses_1-w001", "parent")).toBe("/washes");
    expect(currentItem("/settings", "parent")).toBe("/settings");
    expect(currentItem("/kid/wash/ses_1-w001", "kid")).toBe("/kid");
    expect(currentItem("/kid/germs", "kid")).toBe("/kid/germs");
  });
});

describe("missedText", () => {
  it("never calls an unrecognized wash perfect or lists its zones as missed", () => {
    expect(missedText({ stars: 0, missed: ["palms", "thumbs"] })).toBe("Nothing recognized");
    expect(missedText({ stars: 3, missed: [] })).toBe("All zones washed");
    expect(missedText({ stars: 3, missed: ["thumbs", "nails"] })).toBe("Thumbs, Nails & tips");
  });
});
