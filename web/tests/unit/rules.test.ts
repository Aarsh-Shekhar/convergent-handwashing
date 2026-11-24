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

import { routinesIcs, summaryText, washesCsv } from "../../src/report";
import type { Insights, WashView } from "../../src/api";

const INS = {
  days: 14, from: "2026-11-11", to: "2026-11-24", n: 24, not_recognized: 1, goal: 6,
  score: { mean: 76.6, median: 80, best: 100, previous_mean: null, previous_n: 0, change: null }, scrub: { mean_s: 21.2, goal_s: 20, reached_goal: 12 },
  finished: 14, perfect: 4, days_with_wash: 9, days_goal_met: 0, per_day: [], techniques: [], by_time: [],
  zones: [["thumbs", "Thumbs", 10], ["palms", "Palms", 22], ["backs", "Backs", 13], ["nails", "Nails & tips", 14]].map(([zone, name, full]) => ({ zone, name, coverage: 0.5, full, partial: 0, missed: 0, n: 24 })),
} as unknown as Insights;

describe("what a parent takes out of the app", () => {
  it("writes the summary from the numbers, least scrubbed zones first, and says what the score is not", () => {
    const t = summaryText(INS, "Mia", "doctor", "  third cold  ");
    expect(t).toContain("Washes recorded: 24 (1.7 a day, family goal 6)");
    expect(t).toContain("Average score: 77 of 100");
    expect(t.indexOf("Thumbs: fully scrubbed in 10 of 24")).toBeLessThan(t.indexOf("Backs: fully scrubbed in 13 of 24"));
    expect(t).not.toContain("Palms");
    expect(t).toContain("What we have noticed at home: third cold");
    expect(t).toContain("It does not measure clean hands or germs, and it is not a medical record.");
  });
  it("says so when there is nothing to report, with no made-up numbers", () => {
    const t = summaryText({ ...INS, n: 0 }, "Mia", "caregiver");
    expect(t).toContain("No washes with recognized scrubbing");
    expect(t).not.toContain("Average score");
  });
  it("quotes spreadsheet cells and marks demo washes", () => {
    const w = { wash_id: "demo-1", day: "2026-11-24", time: "12:13", label: 'Before "lunch", late', points: 48, stars: 2, steps_done: 3, seconds_total: 14.5, finished: false, missed: ["thumbs", "nails"] } as unknown as WashView;
    const rows = washesCsv([w]).trim().split("\r\n");
    expect(rows).toHaveLength(2);
    expect(rows[1]).toBe('demo-1,2026-11-24,12:13,"Before ""lunch"", late",48,2,3,14.5,no,Thumbs; Nails & tips,demo');
  });
  it("makes one daily reminder for each switched-on routine with a time", () => {
    const ics = routinesIcs([{ id: "a", name: "Before lunch", detail: "", time: "12:05", on: true }, { id: "b", name: "Bedtime", detail: "", time: "19:30", on: false }, { id: "c", name: "After play", detail: "", time: null, on: true }], "Mia", new Date(2026, 10, 24, 9));
    expect(ics.match(/BEGIN:VEVENT/g)).toHaveLength(1);
    expect(ics).toContain("DTSTART:20261124T120500");
    expect(ics).toContain("RRULE:FREQ=DAILY");
    expect(ics).toContain("SUMMARY:Before lunch: Mia washes hands");
  });
});
