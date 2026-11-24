import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { TOKEN } from "../../playwright.config";

const STEPS = ["palm_to_palm", "back_of_hand", "interlaced_fingers", "backs_of_fingers", "thumb_rubbing", "fingertip_rubbing", "wrist_rubbing"];

/** A wash record shaped like the station's (wash-record-v1), scored by the station's rules. */
export function washRecord(id: string, missed: string[] = ["thumb_rubbing"], each = 4.0) {
  const seconds = Object.fromEntries(STEPS.map((t) => [t, missed.includes(t) ? 0 : each]));
  const done = STEPS.filter((t) => seconds[t] >= 3).length;
  const total = STEPS.reduce((a, t) => a + seconds[t], 0);
  const finished = done >= 5 && total >= 20;
  const stars = finished ? (done === 7 ? 5 : done > 5 ? 4 : 3) : done >= 3 || total >= 10 ? 2 : total ? 1 : 0;
  const points = Math.round(STEPS.reduce((a, t) => a + 10 * Math.min(seconds[t] / 3, 1), 0) + 30 * Math.min(total / 20, 1));
  const ended = new Date(Date.now() - 2000);
  const took = total + 9;
  return {
    wash_id: id, session_id: "ses_e2e", started_utc: new Date(ended.getTime() - took * 1000).toISOString(), ended_utc: ended.toISOString(), duration_s: took,
    seconds, soap_seen: true, quality: { frames: 600, fps: 15 }, models: { temporal_v2: { version: "2.0.0" } }, schema_version: "wash-record-v1",
    score: { session_id: "ses_e2e", timestamp: took, steps: STEPS.map((t) => ({ technique: t, seconds: seconds[t], done: seconds[t] >= 3, points: 10 * Math.min(seconds[t] / 3, 1) })),
      steps_done: done, steps_required: 5, step_min_s: 3.0, total_s: total, total_min_s: 20.0, finished, finished_at_ts: finished ? total : null, next_step: null, points, stars, schema_version: "wash-score-v1" },
  };
}

/** Send a wash the way the station does. */
export async function stationSends(request: APIRequestContext, record: ReturnType<typeof washRecord>, token = TOKEN) {
  return request.post("/api/v1/washes", { data: record, headers: { Authorization: `Bearer ${token}` } });
}

/** Fail the test on any console error or warning, and on any uncaught page error. */
export function watchConsole(page: Page): string[] {
  const seen: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") seen.push(`${m.type()}: ${m.text()}`); });
  page.on("pageerror", (e) => seen.push(`pageerror: ${e.message}`));
  return seen;
}

/** Send what the wash software sends 5 times a second while someone scrubs. */
export async function stationLive(request: APIRequestContext, now: string | null, seconds: Record<string, number>, hands = 2) {
  const session = "ses_e2e_live";
  await request.post("/api/v1/sessions", { headers: { Authorization: `Bearer ${TOKEN}` }, data: { session_id: session, source_id: "cam", width: 640, height: 480, target_fps: 15, device_id: null, processing_config: {}, model_versions: {}, capture_clock: "monotonic" } });
  const steps = STEPS.map((t) => ({ technique: t, seconds: seconds[t] ?? 0, done: (seconds[t] ?? 0) >= 3 }));
  const total = steps.reduce((a, s) => a + s.seconds, 0);
  const r = await request.post(`/api/v1/sessions/${session}/live`, { headers: { Authorization: `Bearer ${TOKEN}` }, data: {
    ts: Date.now() / 1000, hands, fused: { status: now ? "valid" : "unknown", technique: now, confidence: 0.9 },
    score: { steps, steps_done: steps.filter((s) => s.done).length, total_s: total, points: Math.round(total * 2), stars: 2, finished: false, step_min_s: 3, total_min_s: 20 } } });
  expect(r.status()).toBe(202);
}

export async function expectNoSidewaysScroll(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
}

/** A number shown on a kid tile ("points", "zaps", "days in a row"). */
export const tile = async (page: Page, label: string) =>
  Number((await page.locator(".tile", { hasText: label }).locator("b").textContent())!.replace(/,/g, ""));
