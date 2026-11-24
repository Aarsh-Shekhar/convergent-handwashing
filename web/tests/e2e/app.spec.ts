import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { TOKEN } from "../../playwright.config";
import { expectNoSidewaysScroll, stationLive, stationSends, tile, washRecord, watchConsole } from "./helpers";
import { seed } from "./seed";

const SHOTS = "../docs/qa/screens";
mkdirSync(SHOTS, { recursive: true });
test.describe.configure({ mode: "serial" });

const SCREENS: [name: string, path: string, landmark: string][] = [
  ["kid-home", "/kid", "Today's washes"], ["kid-live", "/kid/live", "Waiting for the station"], ["kid-map", "/kid/map", "Bubble Bay"],
  ["kid-germs", "/kid/germs", "Boss of the week"], ["kid-rewards", "/kid/rewards", "Your points"],
  ["parent-overview", "/", "Average score per day"], ["parent-washes", "/washes", "Every wash recorded for Mia"], ["parent-insights", "/insights", "Hand heatmap"],
  ["parent-rewards", "/rewards", "How points are earned"], ["parent-station", "/station", "What is never sent"], ["parent-settings", "/settings", "Privacy"],
];
const kidHomeCount = async (page: Page) => Number((await page.getByRole("img", { name: /of 6 washes today/ }).getAttribute("aria-label"))!.split(" ")[0]);

test.describe("every screen in both views", () => {
  for (const width of [320, 390, 430, 1280]) {
    test(`renders at ${width}px without sideways scroll or console noise`, async ({ page }) => {
      const noise = watchConsole(page);
      await page.setViewportSize({ width, height: width === 1280 ? 860 : 844 });
      for (const [name, path, landmark] of SCREENS) {
        await page.goto(path);
        await expect(page.getByText(landmark).first()).toBeVisible();
        await expectNoSidewaysScroll(page);
        await expect(page.getByRole("navigation", { name: "Main" })).toBeInViewport();
        await page.waitForTimeout(250);
        await page.screenshot({ path: `${SHOTS}/${name}-${width}.png` });
      }
      expect(noise).toEqual([]);
    });
  }

  test("touch targets on a phone are at least 44px", async ({ page }) => {
    for (const [, path] of SCREENS) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const small = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("button, a[href], input, select, [role=switch]")]
        .filter((el) => el.offsetParent !== null)
        .map((el) => ({ el: el.outerHTML.slice(0, 90), r: el.getBoundingClientRect() }))
        .filter(({ r }) => r.width < 44 || r.height < 43.5).map(({ el, r }) => `${Math.round(r.width)}x${Math.round(r.height)} ${el}`));
      expect(small, path).toEqual([]);
    }
  });
});

test("the two switches: kid or grown-up, phone or desktop", async ({ page }) => {
  const noise = watchConsole(page);
  await page.setViewportSize({ width: 1280, height: 860 });
  await page.goto("/");
  await expect(page.locator(".app")).toHaveAttribute("data-layout", "desktop");   // a wide screen starts as desktop
  await expect(page.locator(".app")).toHaveAttribute("data-view", "parent");
  await page.getByRole("group", { name: "Who is using the app" }).getByRole("button", { name: "Kid" }).click();
  await expect(page).toHaveURL(/\/kid$/);
  await expect(page.locator(".app")).toHaveAttribute("data-view", "kid");
  await expect(page.getByRole("heading", { name: "Hi Mia!" })).toBeVisible();

  // phone: the same app inside a phone outline
  await page.getByRole("group", { name: "Layout" }).getByRole("button", { name: "Phone" }).click();
  const phone = page.frameLocator("iframe[title='Scrubble on a phone']");
  await expect(phone.getByRole("heading", { name: "Hi Mia!" })).toBeVisible();
  await expect(phone.locator(".app")).toHaveAttribute("data-layout", "phone");
  await phone.getByRole("link", { name: "Germs" }).click();
  await expect(phone.getByText("Boss of the week")).toBeVisible();
  await expect(page).toHaveURL(/\/kid\/germs$/);        // the outer address follows, so a reload stays on this screen
  await page.screenshot({ path: `${SHOTS}/switch-phone-preview.png` });
  await page.reload();
  await expect(page.frameLocator("iframe[title='Scrubble on a phone']").getByText("Boss of the week")).toBeVisible();
  await page.getByRole("group", { name: "Layout" }).getByRole("button", { name: "Desktop" }).click();
  await expect(page.locator(".app")).toHaveAttribute("data-layout", "desktop");

  // a real phone has no layout switch
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".app")).toHaveAttribute("data-layout", "phone");
  await expect(page.getByRole("group", { name: "Layout" })).toHaveCount(0);
  expect(noise).toEqual([]);
});

test("a wash is followed live, lands in both views without a reload, and its numbers add up", async ({ page, request }) => {
  const noise = watchConsole(page);
  // 1. the station is on and someone is scrubbing: both views show it as it happens
  await page.goto("/kid/live");
  await expect(page.getByText("Waiting for the station")).toBeVisible();
  await stationLive(request, "thumb_rubbing", { palm_to_palm: 4, thumb_rubbing: 1.5 });
  await expect(page.getByText("Thumbs!")).toBeVisible();
  await expect(page.getByRole("img", { name: "6 of 20 seconds" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/flow-1-kid-live.png` });
  await page.goto("/station");
  await stationLive(request, "fingertip_rubbing", { palm_to_palm: 4, thumb_rubbing: 3.2, fingertip_rubbing: 1 });
  await expect(page.getByText("Now: fingertips")).toBeVisible();
  await expect(page.getByRole("row", { name: /fingertips 1\.0 Scrubbing now/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /thumbs 3\.2 Done/ })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/flow-2-station-live.png`, fullPage: true });

  // 2. the wash ends: the kid's home moves on its own
  await page.goto("/kid");
  const before = { today: await kidHomeCount(page), points: await tile(page, "points"), zaps: await tile(page, "zaps") };
  const record = washRecord(`ses_e2e-w${Date.now()}`);
  const ack = await stationSends(request, record);
  expect(ack.status()).toBe(201);
  const saved = await ack.json();
  expect(saved).toMatchObject({ wash_id: record.wash_id, duplicate: false, missed: ["thumbs"], capped: false });
  await expect(page.getByRole("status").filter({ hasText: "New wash from the sink" })).toBeVisible();
  await expect.poll(() => kidHomeCount(page)).toBe(before.today + 1);
  expect(await tile(page, "points")).toBe(before.points + saved.reward_points);
  expect(await tile(page, "zaps")).toBe(before.zaps + saved.zaps);
  await expect(page.getByText("Next time, get the thumbs:")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/flow-3-kid-home-after-wash.png` });

  // a repeat of the same record (a retry after a lost answer) changes nothing
  expect((await stationSends(request, record)).status()).toBe(200);
  await page.reload();
  expect(await tile(page, "points")).toBe(before.points + saved.reward_points);

  // 3. the kid sees the hands; the map opened the next place (this was wash 25)
  await page.getByRole("button", { name: "See my hands" }).click();
  await expect(page).toHaveURL(new RegExp(`/kid/wash/${record.wash_id}$`));
  await expect(page.getByRole("img", { name: /Hand map\. Missed: thumbs\./ })).toBeVisible();
  await page.goto("/kid/map");
  await expect(page.getByRole("img", { name: /Open: Bubble Bay, Germ Jungle, Soap Canyon\./ })).toBeVisible();

  // 4. the grown-up view: same wash, with the arithmetic shown
  await page.goto("/washes");
  const first = page.getByRole("row").nth(1);
  await expect(first.getByRole("link")).toHaveAttribute("href", `/washes/${record.wash_id}`);
  await first.getByRole("link").click();
  await expect(page.getByText(`Wash ID ${record.wash_id}`)).toBeVisible();
  await expect(page.getByText("From the sink")).toBeVisible();
  await expect(page.getByText("Demo data")).toHaveCount(0);
  const points = await page.locator("table.data").first().locator("tbody tr td:last-child").allTextContents();
  const parts = points.slice(0, -1).map(Number);
  expect(Math.round(parts.reduce((a, b) => a + b, 0))).toBe(Number(points.at(-1)));   // the rows sum to the score
  expect(Number(points.at(-1))).toBe(saved.points);
  await expect(page.getByRole("row", { name: /Thumbs 0\.0 0% \(missed\) 0\.0/ })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/flow-4-parent-wash-detail.png`, fullPage: true });
  await page.getByRole("button", { name: "Give a high-five" }).click();
  await expect(page.getByText("High-five sent.")).toBeVisible();
  await page.goto(`/kid/wash/${record.wash_id}`);
  await expect(page.getByText("Your grown-up gave you a high-five!")).toBeVisible();

  // 5. the sync log shows where it came from and how long it took
  await page.goto("/station");
  const row = page.getByRole("row").filter({ hasText: "From the sink" }).first();
  await expect(row).toContainText(/\d+\.\d s/);
  await expect(page.getByText("1 from the sink, 24 demo")).toBeVisible();
  await page.getByText("See the actual record of the latest wash").click();
  await expect(page.locator("pre.record")).toContainText(record.wash_id);
  await expect(page.getByText("20 s total, 3 s per step")).toBeVisible();   // read from this real wash
  await page.screenshot({ path: `${SHOTS}/flow-5-station-sync.png`, fullPage: true });
  expect(noise).toEqual([]);
});

test("the grown-up overview and insights show figures that match the wash list", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 860 });
  await page.goto("/insights");
  await page.getByRole("tab", { name: "30 days" }).click();
  await expect(page.getByText(/Mia: 25 measured washes/)).toBeVisible();
  const thumbs = page.getByRole("row", { name: /Thumbs/ }).first();
  const [, , full, partial, missed] = (await thumbs.getByRole("cell").allTextContents()).map((t) => Number(t.replace("%", "")));
  expect(full + partial + missed).toBe(25);
  await expect(page.getByRole("img", { name: /Average share of each zone's scrub time over 25 washes/ })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/parent-insights-1280-full.png`, fullPage: true });
  await page.goto("/washes");
  await page.getByRole("tab", { name: "All", exact: true }).last().click();
  await expect(page.getByText("25 shown.")).toBeVisible();
  await page.getByRole("tab", { name: "Missed a zone" }).click();
  await expect(page.getByText("All zones washed")).toHaveCount(0);
  // a chart mark answers the keyboard with the exact value
  await page.goto("/");
  await page.locator(".plot.bars .col").last().focus();
  await expect(page.locator(".plot.bars .col").last().locator(".tip")).toBeVisible();
});

test("switching child swaps every number in both views", async ({ page, request }) => {
  await page.goto("/kid");
  const mia = await tile(page, "points");
  await page.getByRole("radio", { name: "Leo" }).click();
  await expect(page.getByRole("heading", { name: "Hi Leo!" })).toBeVisible();
  const leo = await tile(page, "points");
  expect(leo).not.toBe(mia);
  const saved = await (await stationSends(request, washRecord(`ses_e2e-leo${Date.now()}`, []))).json();   // a wash now belongs to Leo
  await expect.poll(() => tile(page, "points")).toBe(leo + saved.reward_points);
  await page.goto("/washes");
  await expect(page.getByText(/Every wash recorded for Leo/)).toBeVisible();
  await page.getByLabel("Child").selectOption({ label: "Mia" });
  await expect(page.getByText(/Every wash recorded for Mia/)).toBeVisible();
  await page.goto("/kid");
  expect(await tile(page, "points")).toBe(mia);
});

test("a kid asks for a reward once and a grown-up approves it", async ({ page }) => {
  await page.goto("/kid/rewards");
  const balance = page.locator(".balance");
  const start = Number((await balance.textContent())!.replace(/,/g, ""));
  await page.getByRole("button", { name: "Ask for it" }).first().click();
  const sheet = page.getByRole("dialog", { name: /Ask for Extra bedtime story/ });
  await sheet.getByRole("button", { name: "Yes, ask for it" }).dblclick();   // a double tap is still one request
  await expect(sheet).toBeHidden();
  await expect(balance).toHaveText((start - 300).toLocaleString());
  await expect(page.getByText("Asked")).toBeVisible();

  await page.goto("/");
  await page.getByRole("link", { name: /1 reward request waiting for you/ }).click();
  await expect(page.getByText("300 points are held.")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Requests to decide")).toHaveCount(0);
  await expect(page.locator(".row", { hasText: "Extra bedtime story" }).getByText("Approved")).toBeVisible();
  await page.goto("/kid/rewards");
  await expect(balance).toHaveText((start - 300).toLocaleString());
});

test("a grown-up adds a reward, and bad input cannot be saved", async ({ page }) => {
  await page.goto("/rewards");
  await page.getByRole("button", { name: "Add a reward" }).click();
  const sheet = page.getByRole("dialog", { name: "New family reward" });
  await expect(sheet.getByRole("button", { name: "Add reward" })).toBeDisabled();
  await sheet.getByLabel("Reward").fill("Zoo day");
  await sheet.getByLabel("Points needed").fill("0");
  await expect(sheet.getByRole("button", { name: "Add reward" })).toBeDisabled();
  await sheet.getByLabel("Points needed").fill("9000");
  await sheet.getByRole("button", { name: "Add reward" }).click();
  await expect(page.getByRole("row", { name: /Zoo day 9,000/ })).toContainText("to go");
  await page.goto("/kid/rewards");
  await expect(page.locator(".reward", { hasText: "Zoo day" }).getByRole("button")).toHaveCount(0);
});

test("a germ is added to the collection with zaps", async ({ page }) => {
  await page.goto("/kid/germs");
  const count = page.getByLabel(/of 8 germs collected/);
  const had = Number((await count.textContent())!.split("/")[0]);
  await page.getByRole("button", { name: /Germ not met yet\. Hides on thumbs/ }).first().click();
  await page.getByRole("dialog", { name: "Not met yet" }).getByRole("button", { name: /Add for 50 zaps/ }).click();
  await expect(count).toHaveText(`${had + 1}/8`);
  await page.getByRole("button", { name: /^Prickle, zapped/ }).click();
  await expect(page.getByRole("dialog", { name: "Prickle" })).toContainText("most often missed");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("routines and the daily goal are saved, and unavailable features say so", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("button", { name: "Raise daily goal" }).click();
  await expect(page.getByRole("group", { name: "daily goal" }).getByRole("status")).toHaveText("7");
  await page.getByRole("switch", { name: "After playing outside routine" }).click();
  await expect(page.getByRole("switch", { name: /Station reminder/ })).toBeDisabled();
  await page.getByRole("button", { name: "Add routine" }).click();
  const routine = page.getByRole("dialog", { name: "New routine" });
  await routine.getByLabel("Name").fill("After school");
  await routine.getByLabel(/Usual time/).fill("15:30");
  await routine.getByRole("button", { name: "Save" }).click();
  await page.reload();
  await expect(page.getByRole("group", { name: "daily goal" }).getByRole("status")).toHaveText("7");
  await expect(page.getByRole("switch", { name: "After playing outside routine" })).toBeChecked();
  await expect(page.getByText("After school")).toBeVisible();
  await page.getByRole("button", { name: "Lower daily goal" }).click();
  await expect(page.getByRole("group", { name: "daily goal" }).getByRole("status")).toHaveText("6");
});

test("the keyboard reaches the navigation and tabs, and reduced motion is honoured", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Insights" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/insights$/);
  const tabs = page.getByRole("tablist", { name: "Period" });
  await tabs.getByRole("tab", { name: "14 days" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "30 days" })).toHaveAttribute("aria-selected", "true");
  await page.goto("/kid");
  const running = await page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running" && (a.effect?.getTiming().iterations ?? 1) === Infinity).length);
  expect(running).toBe(0);
});

test("a failed request shows an error with a retry that works, and an unknown wash says so", async ({ page }) => {
  await page.route("**/api/v1/app/home", (r) => r.abort());
  await page.goto("/kid");
  await expect(page.getByRole("alert")).toContainText("Can't reach Scrubble");
  await page.unroute("**/api/v1/app/home");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByText("Today's washes")).toBeVisible();
  await page.goto("/washes/no-such-wash");
  await expect(page.getByText("Wash not found")).toBeVisible();
  await page.goto("/nowhere");
  await expect(page.getByText("That page does not exist.")).toBeVisible();
});

test("with a PIN set, the grown-up view asks for it, and a wrong PIN is refused", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("button", { name: /Parent PIN/ }).click();
  await page.getByLabel(/New PIN/).fill("4821");
  await page.getByLabel("Type it again").fill("4821");
  await page.getByRole("button", { name: "Save PIN" }).click();
  await page.getByRole("button", { name: /Lock and go to the kid view/ }).click();
  await expect(page).toHaveURL(/\/kid$/);

  await page.getByRole("button", { name: "Grown-up" }).click();
  const gate = page.getByRole("dialog", { name: "Grown-ups only" });
  await gate.getByLabel("Parent PIN").fill("0000");
  await gate.getByRole("button", { name: "Unlock" }).click();
  await expect(gate.getByRole("alert")).toHaveText("That PIN is not right.");
  await expect(page).toHaveURL(/\/kid$/);                          // still in the kid view
  await gate.getByLabel("Parent PIN").fill("4821");
  await gate.getByRole("button", { name: "Unlock" }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.getByRole("link", { name: "Settings" }).click();      // moving inside the app keeps the unlock; a reload would lock again
  await page.getByRole("button", { name: /Delete Mia's wash history/ }).click();
  const confirm = page.getByRole("dialog", { name: "Delete wash history?" });
  await expect(confirm).toContainText("reset to zero");
  await confirm.getByRole("button", { name: "Delete history" }).click();
  await page.goto("/");
  await expect(page.getByText("No washes yet")).toBeVisible();
  await page.goto("/kid");
  expect(await tile(page, "points")).toBe(0);
});

test("first run: the tour, set-up, and an empty app that fills with the first wash", async ({ page, request }) => {
  const noise = watchConsole(page);
  expect((await request.post("/api/v1/app/demo/reset", { headers: { Authorization: `Bearer ${TOKEN}` } })).ok()).toBe(true);
  await page.goto("/");
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByRole("heading", { name: "Germs are sneaky!" })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.reload();                                               // progress is kept
  await expect(page.getByRole("heading", { name: "Scrub to zap them" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/onboarding-scrub.png` });
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Get started" }).click();
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();   // a name is needed
  await page.getByLabel("Your name").fill("Sam");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("radio", { name: "Mint Bubbles" }).click();
  await page.getByLabel("Kid's nickname").fill("Mia");
  await page.getByRole("radio", { name: "7-8" }).click();
  await page.screenshot({ path: `${SHOTS}/onboarding-kid.png` });
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("This app is connected to the station laptop")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Looks good" }).click();
  await page.getByRole("button", { name: "Finish setup" }).click();
  await expect(page.getByRole("heading", { name: "Ready to bust some germs, Mia!" })).toBeVisible();
  await page.getByRole("button", { name: "Start playing" }).click();
  await expect(page).toHaveURL(/\/kid$/);
  await expect(page.getByText("No washes yet")).toBeVisible();
  await stationSends(request, washRecord(`ses_first-w${Date.now()}`, []));
  await expect.poll(() => kidHomeCount(page)).toBe(1);
  await expect(page.getByText("Every spot got scrubbed.")).toBeVisible();
  expect(noise).toEqual([]);
  seed(); // leave the demo family in place for whoever looks next
});
