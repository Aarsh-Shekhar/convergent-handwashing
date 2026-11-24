import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { expectNoSidewaysScroll, hudNumber, stationSends, washRecord, watchConsole } from "./helpers";
import { seed } from "./seed";

const SHOTS = "../docs/qa/screens";
mkdirSync(SHOTS, { recursive: true });
test.describe.configure({ mode: "serial" });

const ROUTES: [name: string, path: string, landmark: string][] = [
  ["home", "/", "Hi Sam!"], ["history", "/history", "Mia's washes"], ["progress", "/progress", "Washes per day"],
  ["map", "/progress?view=map", "Bubble Bay"], ["rewards", "/rewards", "Family rewards"], ["germ-dex", "/germ-dex", "Boss of the week"],
  ["routines", "/routines", "Daily goal"], ["settings", "/settings", "Sink station"],
];

test.describe("every screen, every width", () => {
  for (const width of [320, 360, 390, 430, 1280]) {
    test(`renders at ${width}px without sideways scroll, clipped nav or console noise`, async ({ page }) => {
      const noise = watchConsole(page);
      await page.setViewportSize({ width, height: width === 1280 ? 800 : 844 });
      for (const [name, path, landmark] of ROUTES) {
        await page.goto(path);
        await expect(page.getByText(landmark).first()).toBeVisible();
        await expectNoSidewaysScroll(page);
        const nav = await page.getByRole("navigation", { name: "Main" }).boundingBox();
        expect(nav!.y + nav!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
        expect(nav!.x).toBeGreaterThanOrEqual(0);
        await page.waitForTimeout(350); // entry animations settle before the picture
        await page.screenshot({ path: `${SHOTS}/${name}-${width}.png` });
      }
      expect(noise).toEqual([]);
    });
  }

  test("touch targets are at least 44px", async ({ page }) => {
    for (const [, path] of ROUTES) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const small = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("button, a[href], input, [role=switch]")]
        .filter((el) => el.offsetParent !== null)
        .map((el) => ({ el: el.outerHTML.slice(0, 80), r: el.getBoundingClientRect() }))
        .filter(({ r }) => r.width < 44 || r.height < 43.5).map(({ el, r }) => `${Math.round(r.width)}x${Math.round(r.height)} ${el}`));
      expect(small, path).toEqual([]);
    }
  });
});

test("a wash from the station shows up live and drives every screen", async ({ page, request }) => {
  const noise = watchConsole(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Mia's day" })).toBeVisible();
  const before = { points: await hudNumber(page, /reward points/), zaps: await hudNumber(page, /zaps/) };
  const today = Number((await page.locator(".goal-pill b").textContent())!.split("/")[0]);

  const record = washRecord(`ses_e2e-w${Date.now()}`);
  const ack = await stationSends(request, record);
  expect(ack.status()).toBe(201);
  const saved = await ack.json();
  expect(saved).toMatchObject({ wash_id: record.wash_id, duplicate: false, missed: ["thumbs"] });

  // no reload: the toast, the goal ring and the counters move on their own
  await expect(page.getByRole("status").filter({ hasText: "New wash synced" })).toBeVisible();
  await expect(page.locator(".goal-pill b")).toHaveText(`${today + 1}/6`);
  expect(await hudNumber(page, /reward points/)).toBe(before.points + saved.reward_points);
  expect(await hudNumber(page, /zaps/)).toBe(before.zaps + saved.zaps);
  await page.screenshot({ path: `${SHOTS}/flow-1-home-after-wash.png` });

  // the same wash sent again (a retry after a lost answer) changes nothing
  expect((await stationSends(request, record)).status()).toBe(200);
  await page.reload();
  expect(await hudNumber(page, /reward points/)).toBe(before.points + saved.reward_points);

  // Home's latest wash opens that very wash
  await page.getByRole("link", { name: /Open wash details/ }).click();
  await expect(page).toHaveURL(new RegExp(`/history/${record.wash_id}$`));
  await expect(page.getByText(`Wash ID ${record.wash_id}`)).toBeVisible();
  await expect(page.getByRole("img", { name: /Hand map\. Missed: thumbs\./ })).toBeVisible();
  await expect(page.getByText("Next time: thumbs")).toBeVisible();
  await expect(page.getByText(`+${saved.reward_points} points`)).toBeVisible();
  await expect(page.getByText("Demo data")).toHaveCount(0); // it came from the station, not the seed
  await page.screenshot({ path: `${SHOTS}/flow-2-wash-detail.png`, fullPage: true });

  // the detail survives a reload (deep link) and a high-five is saved once
  await page.reload();
  await page.getByRole("button", { name: "Give a high-five" }).click();
  await expect(page.getByText("High-five saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByText("High-five saved.")).toBeVisible();

  // it is first in the history, and it opened the next place on the map (wash 25)
  await page.goto("/history");
  await expect(page.getByRole("link").filter({ hasText: /sec/ }).first()).toHaveAttribute("href", `/history/${record.wash_id}`);
  await page.goto("/progress?view=map");
  await expect(page.getByRole("img", { name: /Open: Bubble Bay, Germ Jungle, Soap Canyon\./ })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/flow-3-map-after-wash.png` });
  await page.goto("/settings");
  await expect(page.getByText("20 sec")).toBeVisible(); // the scrub timer the station used, read from this real wash
  expect(noise).toEqual([]);
});

test("switching child swaps every number and stops the other child's washes reaching the page", async ({ page, request }) => {
  await page.goto("/");
  const mia = await hudNumber(page, /reward points/);
  await page.getByRole("radio", { name: "Leo" }).click();
  await expect(page.getByRole("heading", { name: "Leo's day" })).toBeVisible();
  const leo = await hudNumber(page, /reward points/);
  expect(leo).not.toBe(mia);
  await page.goto("/history");
  await expect(page.getByRole("heading", { name: "Leo's washes" })).toBeVisible();
  // a wash now belongs to Leo; Mia's numbers are untouched
  const saved = await (await stationSends(request, washRecord(`ses_e2e-leo${Date.now()}`, []))).json();
  await page.goto("/");
  await expect.poll(() => hudNumber(page, /reward points/)).toBe(leo + saved.reward_points);
  await page.getByRole("radio", { name: "Mia" }).click();
  await expect(page.getByRole("heading", { name: "Mia's day" })).toBeVisible();
  expect(await hudNumber(page, /reward points/)).toBe(mia);
});

test("a reward is asked for once, holds the points, and a grown-up approves it", async ({ page }) => {
  await page.goto("/rewards");
  const balance = page.locator(".balance");
  const start = Number((await balance.textContent())!.replace(/,/g, ""));
  await page.getByRole("button", { name: "Redeem" }).first().click();
  const sheet = page.getByRole("dialog", { name: /Ask for Extra bedtime story/ });
  await sheet.getByRole("button", { name: "Yes, ask for it" }).dblclick(); // a double tap is still one request
  await expect(sheet).toBeHidden();
  await expect(balance).toHaveText((start - 300).toLocaleString());
  await expect(page.getByText("Asked")).toBeVisible();
  await expect(page.locator(".request.requested")).toHaveCount(1);
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.locator(".request.approved").first()).toContainText("Extra bedtime story");
  await page.reload();
  await expect(balance).toHaveText((start - 300).toLocaleString());
});

test("a parent adds a reward that is out of reach, and bad input cannot be saved", async ({ page }) => {
  await page.goto("/rewards");
  await page.getByRole("button", { name: "Add a family reward" }).click();
  const sheet = page.getByRole("dialog", { name: "New family reward" });
  await expect(sheet.getByRole("button", { name: "Add reward" })).toBeDisabled();
  await sheet.getByLabel("Reward").fill("Zoo day");
  await sheet.getByLabel("Points needed").fill("0");
  await expect(sheet.getByRole("button", { name: "Add reward" })).toBeDisabled();
  await sheet.getByLabel("Points needed").fill("9000");
  await sheet.getByRole("button", { name: "Add reward" }).click();
  const row = page.getByRole("listitem").filter({ hasText: "Zoo day" });
  await expect(row).toContainText("to go");
  await expect(row.getByRole("button", { name: "Redeem" })).toHaveCount(0);
});

test("a germ is added to the Germ-dex with zaps", async ({ page }) => {
  await page.goto("/germ-dex");
  const count = page.getByLabel(/of 8 germs collected/);
  const had = Number((await count.textContent())!.split("/")[0]);
  await page.getByRole("button", { name: /Germ not met yet\. Hides on thumbs/ }).first().click();
  const sheet = page.getByRole("dialog", { name: "Not met yet" });
  await sheet.getByRole("button", { name: /Add for 50 zaps/ }).click();
  await expect(count).toHaveText(`${had + 1}/8`);
  await page.getByRole("button", { name: /^Prickle, zapped/ }).click();
  await expect(page.getByRole("dialog", { name: "Prickle" })).toContainText("most often missed");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("routines and the daily goal are saved, and unavailable reminders say so", async ({ page }) => {
  await page.goto("/routines");
  await page.getByRole("button", { name: "Raise daily goal" }).click();
  await page.getByRole("switch", { name: "After playing outside routine" }).click();
  await expect(page.getByRole("switch", { name: /Station reminder/ })).toBeDisabled();
  await page.getByRole("button", { name: "Add routine" }).click();
  await page.getByLabel("Name").fill("After school");
  await page.getByLabel(/Usual time/).fill("15:30");
  await page.getByRole("button", { name: "Save" }).click();
  await page.reload();
  await expect(page.getByRole("group", { name: "daily goal" }).getByRole("status")).toHaveText("7");
  await expect(page.getByRole("switch", { name: "After playing outside routine" })).toBeChecked();
  await expect(page.getByText("After school")).toBeVisible();
  await page.getByRole("button", { name: "Lower daily goal" }).click();
});

test("the app can be driven from the keyboard and honours reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("link", { name: "Progress", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/progress$/);
  const tabs = page.getByRole("tablist", { name: "Progress view" });
  await tabs.getByRole("tab", { name: "Trends" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "Adventure map" })).toHaveAttribute("aria-selected", "true");
  const running = await page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running" && (a.effect?.getTiming().iterations ?? 1) === Infinity).length);
  expect(running).toBe(0);
});

test("a failed request shows an error with a retry that works, and an unknown wash says so", async ({ page }) => {
  await page.route("**/api/v1/app/home", (r) => r.abort());
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Can't reach Scrubble");
  await page.unroute("**/api/v1/app/home");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("heading", { name: "Mia's day" })).toBeVisible();
  await page.goto("/history/no-such-wash");
  await expect(page.getByText("Wash not found")).toBeVisible();
});

test("with a PIN set, grown-up actions ask for it and a wrong PIN is refused", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("button", { name: /Parent PIN/ }).click();
  await page.getByLabel(/New PIN/).fill("4821");
  await page.getByLabel("Type it again").fill("4821");
  await page.getByRole("button", { name: "Save PIN" }).click();
  await page.getByRole("button", { name: /Lock grown-up screens/ }).click();
  await page.goto("/settings");
  await page.getByRole("button", { name: /Delete Mia's wash history/ }).click();
  const gate = page.getByRole("dialog", { name: "Grown-ups only" });
  await gate.getByLabel("Parent PIN").fill("0000");
  await gate.getByRole("button", { name: "Unlock" }).click();
  await expect(gate.getByRole("alert")).toHaveText("That PIN is not right.");
  await gate.getByLabel("Parent PIN").fill("4821");
  await gate.getByRole("button", { name: "Unlock" }).click();
  const confirm = page.getByRole("dialog", { name: "Delete wash history?" });
  await expect(confirm).toContainText("reset to zero");
  await confirm.getByRole("button", { name: "Delete history" }).click();
  await page.goto("/");
  await expect(page.getByText("No washes yet")).toBeVisible();
  expect(await hudNumber(page, /reward points/)).toBe(0);
  await page.screenshot({ path: `${SHOTS}/state-home-empty.png` });
});

test("first run: the tour, set-up, and an empty Home that fills with the first wash", async ({ page, request }) => {
  const noise = watchConsole(page);
  const wipe = await request.post("/api/v1/app/demo/reset", { headers: { Authorization: "Bearer e2e-token-not-a-secret" } });
  expect(wipe.ok()).toBe(true);
  await page.goto("/");
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.screenshot({ path: `${SHOTS}/onboarding-01-splash.png` });
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByRole("heading", { name: "Germs are sneaky!" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/onboarding-02-germs.png` });
  await page.getByRole("button", { name: "Next" }).click();
  await page.screenshot({ path: `${SHOTS}/onboarding-03-scrub.png` });
  await page.reload(); // progress is kept
  await expect(page.getByRole("heading", { name: "Scrub to zap them" })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.screenshot({ path: `${SHOTS}/onboarding-04-earn.png` });
  await page.getByRole("button", { name: "Get started" }).click();
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled(); // a name is needed
  await page.getByLabel("Your name").fill("Sam");
  await page.screenshot({ path: `${SHOTS}/onboarding-05-parent.png` });
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("radio", { name: "Mint Bubbles" }).click();
  await page.getByLabel("Kid's nickname").fill("Mia");
  await page.getByRole("radio", { name: "7-8" }).click();
  await page.screenshot({ path: `${SHOTS}/onboarding-06-kid.png` });
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("This app is connected to the station laptop")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/onboarding-07-station.png` });
  await page.getByRole("button", { name: "Continue" }).click();
  await page.screenshot({ path: `${SHOTS}/onboarding-08-camera.png` });
  await page.getByRole("button", { name: "Looks good" }).click();
  await page.screenshot({ path: `${SHOTS}/onboarding-09-routines.png` });
  await page.getByRole("button", { name: "Finish setup" }).click();
  await expect(page.getByRole("heading", { name: "Ready to bust some germs, Mia!" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/onboarding-10-done.png` });
  await page.getByRole("button", { name: "Go to Home" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText("No washes yet")).toBeVisible();
  await stationSends(request, washRecord(`ses_first-w${Date.now()}`, []));
  await expect(page.getByText("1/6")).toBeVisible();
  await expect(page.getByRole("link", { name: /Open wash details/ })).toContainText("Perfect scrub");
  expect(noise).toEqual([]);
  seed(); // leave the demo family in place for whoever looks next
});
