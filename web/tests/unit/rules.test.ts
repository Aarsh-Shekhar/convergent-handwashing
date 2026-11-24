// The few rules that live in the browser (everything about scores and points is tested in Python).
import { describe, expect, it } from "vitest";
import { tabFor } from "../../src/components/BottomNav";
import { zoneState } from "../../src/components/RegionHandMap";

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

describe("tabFor", () => {
  it("keeps history and wash detail under Home, routines under Settings", () => {
    expect(tabFor("/history")).toBe("/");
    expect(tabFor("/history/ses_1-w001")).toBe("/");
    expect(tabFor("/routines")).toBe("/settings");
    expect(tabFor("/germ-dex")).toBe("/germ-dex");
    expect(tabFor("/nowhere")).toBe("/");
  });
});
