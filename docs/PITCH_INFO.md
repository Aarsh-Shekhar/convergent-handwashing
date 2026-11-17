# Pitch deck material

Raw material for the pitch deck, not slides. Sources are in `RESEARCH.md` (2026-11-17 round) unless noted. Tags: [E] study or published data, [M] manufacturer claim, [R] reviews or press. Check every number against its source before it goes on a slide.

## One-liner

A smart sink trainer that turns handwashing into a game for kids aged 4 to 10. A camera recognizes each washing step, and germs projected onto the child's hands disappear as they scrub. No phone in the bathroom.

## Problem

- Kids rush handwashing and skip steps. Even with help, kids aged 4 to 6 do only 1 to 2 of the washing steps (song study, 2026, 47 children). [E]
- Existing kids' hygiene gadgets lose kids within weeks (see "Engagement stats").
- Why handwashing matters, CDC figures (from memory, not checked this session; verify at cdc.gov "Show Me the Science: Why Wash Your Hands" before use):
  - Handwashing education cuts diarrheal illness by 23 to 40%.
  - It cuts respiratory illnesses such as colds by 16 to 21%.
  - It cuts school absences from stomach illness by 29 to 57%.

## What we have built (demo-ready)

- Live recognition of all 7 WHO handwashing steps from a camera, on a laptop.
- Germ graphics projected onto the hands, popping as each part is scrubbed. Two game styles: dinos and coverage germs.
- A score per wash: points 0 to 100, 0 to 5 stars, seconds per step.
- Starts and ends automatically when hands arrive and leave, one record per wash.
- Works in poor light, filters out false hand detections, and has a backend that stores wash records.

Honest accuracy, for Q&A, not the headline:
- 75% of video frames correct on public test videos of adults.
- 59% on a laptop webcam.
- Not yet tested on children's hands or the final sink camera.

## Competitive landscape

| Product | Type | Where progress shows | Weak spots found |
| --- | --- | --- | --- |
| Philips Sonicare for Kids | Smart toothbrush + pet app | Parent's phone | Novelty wore off fast [R], sync issues, a bug broke a kid's streak, so engaging it delayed bedtime |
| Oral-B Disney Magic Timer | Timer app + stickers | Phone | Rewards tied to buying their products |
| GUM Playbrush | Sensor brush + phone games | Phone | Most games behind a subscription |
| Colgate Magik | AR game + parent dashboard | Phone | Freezes when small hands block sensors, misreads areas [R] |
| Grush | Gaming brush + parent app | Tablet in the bathroom | Calibration failures [R] |
| hum by Colgate (school program) | Smart brush + class dashboard | Phone | 29% of kids never connected it [E] |
| Light-up handwashing timers | 20-second timer | None | Only time, no technique. Kids would rather sing [R] |
| SureWash | Camera technique trainer | On device | Built for hospitals, not kids |
| Day care sink animation (research trial) | Sensor + tablet animation | Tablet at sink | Effect gone 2 weeks after removal [E] |

## What we do that others don't

1. **No phone needed.** Feedback is projected onto the child's own hands. Competitors need the parent's phone or a tablet in the bathroom, and that was the top barrier in a school study (29% never connected). [E]
2. **Progress lives on the device.** We found no kids' hygiene product that shows long-term progress on the device itself. The projector can show a kid's collection before and after every wash. (Planned)
3. **Technique, not just time.** Timers count 20 seconds. We recognize which of the 7 steps the child does and when.
4. **Works for kids who can't read yet.** Pictures on the hands now, plus a planned audio coach built on child-learning research: short one-step hints, and quiet for kids who already know the steps.
5. **Privacy by design.** The goal is no video stored, only wash results. (Planned, being designed with the data rules in mind)

## Engagement stats from kids' hygiene gadgets

- **Novelty fades:** no kids' hygiene device has published engagement beyond about 2 months. [E, review of 9 trials]
- **Use drops week by week:** in an 8-week toothbrush trial with toddlers, frequency fell week by week in every group. [E]
- **Surprise beats fixed rewards:** lottery-style rewards gave 6.0 vs 3.9 brushing sessions per week. [E]
- **Gains fade without the device:**
  - Brush Up pilot: brushing time 40 s to 109 s in 2 weeks, with no significant gain a year later without the app. [E]
  - Day care sink animation: soaping time +62% (8.5 s to 13.8 s) for 4 weeks, almost back to baseline 2 weeks after removal. [E]
- **The phone is a barrier:** hum school program, 409 kids aged 8 to 11. [E]
  - 29% never connected the brush.
  - 55% of the rest used it for more than 2 months.
  - Twice-daily brushing on only 48% of days.
- **Manufacturer claims** (self-funded, use with care):
  - Philips: "98% of parents" report longer brushing. [M]
  - Oral-B: "9 in 10 kids brush longer", from a 52-child study. [M]
  - Playbrush: 72% vs 56% twice-daily brushing over 6 weeks. [M]
- **Environment cues work:** painted footprints to the sink took handwashing with soap from 4% to 74%, and it held for months. [E]
- **Songs help young kids:** 22 s vs 5 s median washing time. [E, small study]
- **Habits take about 2 months:** a median of 59 to 66 days of repetition. [E]

## How we answer the retention problem (design story)

- Progress the kid can see at the sink, not hidden in a parent app.
- A growing collection with surprise unlocks and new germ sets every 1 to 2 weeks, not losable streaks.
- Rewards for washing well, not for washing more.
- Rewards fade after the habit forms (about 2 months), and praise takes over.
- An optional parent app with a one-screen summary for busy parents.

## Claims to avoid

- "Guarantees clean hands" or "kills germs". We measure washing motions, not cleanliness or soap contact.
- Accuracy claims about children. Not measured yet.
- Retention claims about our product. We have no long-term data yet. Say we plan to measure 8-week use.

## Still to find for the deck

- Market size: parents of kids aged 4 to 10, kids' smart toothbrush sales, home vs school.
- Price point and hardware cost (parts list in `CLAUDE.md`, prices not collected).
- A quote or pilot result from a parent or teacher.
