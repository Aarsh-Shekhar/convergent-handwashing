# Scrubble design spec and visual review

Target: `references/visual-target.png` (style only). Structure: the team's Figma screens 01 to 18.
Tokens are in `web/src/styles/tokens.css`; controls in `styles/controls.css`. Screenshots: `docs/qa/screens/`.

## Screens

| Route | Figma | Composition | Notes |
| --- | --- | --- | --- |
| `/` | 11 Home | Greeting, child pills, purple HUD (points, zaps, streak), the day panel with Bubbles in Bubble Bay, four round shortcuts, latest wash, coach tip, boss strip | "5 days streak" moved into the HUD. The tip appears after 3 washes in the week. |
| `/history` | 12 | Today / Week / Month, rows grouped by local day with a score ring | Shows 60 rows, then "Show more" |
| `/history/:id` | 13 | Result panel (creature, stars, score, earned), three figures, palm and back hand map, zone bars, coach note, high-five, sync proof | "12/14 germs zapped" is replaced by steps done: germ counts are not recorded |
| `/progress` | 14 | Trends (Day / Week / Month) or Adventure map | Trouble spots say "missed 4 of 5", not a bare percent. Thumb Wrestle mode is left out: the station has no such mode. |
| `/rewards` | 15 | Vault with chest, family rewards, requests, badges, the points rule | Redeem asks; a grown-up approves |
| `/germ-dex` | 16 | Boss panel, 2-column collection, detail sheet | 8 defined germs. The 4 undefined slots of the lofi are not drawn. |
| `/routines` | 17 | Routines with toggles, daily goal, reminders | Both reminders are shown switched off and labelled not available |
| `/settings` | 18 | Station status, game facts, family, privacy, delete | Timer, step time and model are read-only |
| `/onboarding` | 01 to 10 | Splash, 3 story pages, parent, kid, station, camera, routines, done | No Apple or Google sign-in, no pairing: neither exists |

## Honest-data rules in the UI

- A zone is washed at 3 s of its motion, partly below that, missed at 0. Missed zones are coral, hatched and named.
- A wash with nothing recognized shows "Nothing recognized" and grey "Not seen" zones, never six misses or a perfect scrub.
- "Perfect scrub" needs every zone at full time.
- Seeded and simulated washes carry a "Demo data" tag on their detail page.
- "Station live / idle / offline" reflects messages that arrived, nothing else.

## Visual review (390 x 844 unless noted)

Checked against the target after each screen was built. Changes made after looking:

1. Home: reeds and bubbles covered the stats. Reeds lowered, bubbles moved right.
2. Wash detail: the three figure tiles were misaligned (stylesheet order). Fixed. Sync time used the wrong date. Fixed.
3. Map: the island sat small in a tall empty frame and the castle roof was cut off. Reframed. Closed places were near black; now dusk blue.
4. Progress: a falling average was shown in green. Now neutral; only a rise is green.
5. 320 px: Bubbles covered "Clean washes" on Home, and reward titles ran under the Redeem button. Both fixed.
6. "See all" was 29 px tall. Now 44 px.

Against the checklist: ocean-to-purple world yes; one hero per screen yes; rim-lit round controls and one icon
family yes; Figma hierarchy kept; each screen has its own layout; locked, loading, empty and error states exist.

Remaining gaps, for the team's sign-off:

- The target's illustration is richer than the hand-written SVG here, most visibly on the map and Home panel.
- Kings and the rainbow germ are colour-shifted stand-ins.
- Onboarding story pages are plain next to the main screens.
- Desktop keeps the phone column centred. There is no two-column layout.
- Contrast was checked by eye, not with a tool. No screen reader pass was done beyond roles and labels in tests.
