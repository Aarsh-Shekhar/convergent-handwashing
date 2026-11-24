# Scrubble design spec and visual review

The app has two views of the same data and two layouts. Tokens: `web/src/styles/tokens.css`.
Shared rules: `styles/app.css`. Per view: `styles/kid.css`, `styles/parent.css`. Screenshots: `docs/qa/screens/`.

## The two switches

| Switch | Where | What it does |
| --- | --- | --- |
| Kid / Grown-up | side bar on desktop, top bar on phone | Kid = every route under `/kid`. Grown-up = everything else. Going to Grown-up asks for the parent PIN if one is set. |
| Phone / Desktop | same place, only on a wide screen | Desktop = side bar and wide pages. Phone = the same app inside a phone frame (an iframe of the same URL). Saved in the browser. A real phone always gets the phone layout. |

## Look

Third pass, 2026-11-24. The first version was glossy and over-rounded. The second was flat cream paper, which
read as plain. This one sits between them.

- Kid view: the night-ocean world of the first version (blue at the top, indigo below) with the flat panels of
  the second. Gold marks what can be pressed. Nunito, 16 px corners, buttons with a 3 px darker edge. No gloss,
  no glow, no glass.
- Grown-up view: no characters and no game colour. Inter, white, cool grey hairlines, 8 px corners, one blue.
  Plain wordmark. The hand heatmap is flat cells split by white gaps. Numbers use tabular figures.
- Germ art and the Phizzy material (names, zones, the story) are unchanged.
- Status is never colour alone: every state has a word or an icon next to it.

## Screens

| Route | View | What is on it |
| --- | --- | --- |
| `/kid` | Kid | Today's washes against the goal, Bubbles, zaps, points, streak, latest wash, boss |
| `/kid/live` | Kid | Waiting, scrubbing (step tiles fill from the live feed), result |
| `/kid/wash/:id` | Kid | Stars, hands with washed and missed zones, what it earned |
| `/kid` (also) | Kid | "Your next wash is Level N in Place", three daily quests |
| `/kid/map` | Kid | Adventure map. Tap a place on the drawing or in the list to go in. Places open at 0, 10, 25, 50 rewarded washes |
| `/kid/map/:place` | Kid | The place's path: one level per rewarded wash, with its stars. Tap a finished level to see that wash. A chest marks every fifth level. Who lives there, moves to practise. Locked places can be looked at |
| `/kid/germs` | Kid | Collection, buy with zaps, boss |
| `/kid/rewards` | Kid | Points, family rewards, ask for one, badges |
| `/` | Grown-up | Range picker, 4 figures, score per wash, washes per day, hand heatmap, recent washes |
| `/washes`, `/washes/:id` | Grown-up | Table of washes. Detail: the score arithmetic line by line, zones table, how the wash arrived, high-five |
| `/insights` | Grown-up | Heatmap with counts, seconds per step against the 3 s target, time of day, goal days |
| `/rewards` | Grown-up | Requests to approve, reward list, points ledger rule |
| `/station` | Grown-up | How a wash gets from the sink to the app (see below) |
| `/extensions` | Grown-up | Summary to email, copy or print. Saved doctor contact with call and booking link. Calendar file and CSV. A table of planned items marked not built |
| `/settings` | Grown-up | Family, routines, PIN, privacy, delete, what is not built |
| `/onboarding` | none | Tour and set-up, ends in the kid view |

## Station page: the sync story

Written so a judge can follow it without help. Top to bottom:

1. Four steps in a row: camera sees hands, laptop recognizes the steps, the wash record is sent, the app updates.
   Each step shows its real state now (for example "last message 0.4 s ago").
2. Live from the sink: seconds per step as they arrive, 5 times a second.
3. What is sent (score, seconds per step, times) and what is never sent (video, pictures, sound, names, faces).
4. The actual JSON of the newest wash record.
5. Sync log: each wash, where it came from (Sink or Demo), when it ended, when it arrived, the delay, the size.

## Honest-data rules in the UI

- A zone is washed at 3 s of its motion, partly below that, missed at 0.
- A wash with nothing recognized says so. It is not shown as six misses or as a perfect scrub, and is left out of averages (counted separately).
- Seeded and simulated washes carry a "Demo" tag everywhere they appear. Real ones say "Sink".
- The station status reflects messages that arrived, nothing else.
- Every chart has its numbers in a table or a sentence next to it. Heatmap cells show "washed in 9 of 12".
- Levels, chests and quests are worked out from saved washes. They give no extra zaps or points.
- Extensions: the app sends nothing by itself. Items that need a partner are in a separate table, each tagged "Not built".
- The heatmap uses one blue from light to dark. Charts with one series have no legend.

## Visual review

Looked at by screenshot at 390 and 1280 px in both views, and 320 and 430 px in the browser tests.
Fixed after looking: tables pushing the phone layout sideways, a class name clash that broke the heatmap scale
on desktop, switch buttons and the stepper under 44 px, the toast sitting off centre.

Remaining gaps, for the team's sign-off:

- The map and scene art are simple hand-written SVG.
- Kings and the rainbow germ are colour-shifted stand-ins.
- Contrast was checked by eye. No screen reader pass beyond roles and labels in tests.
- Only Chrome was available. Safari and a real phone are untested.
