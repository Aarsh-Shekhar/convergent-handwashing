# Art manifest

| Asset | Where used | Source | Conversion | Rights |
| --- | --- | --- | --- | --- |
| `web/src/assets/scrubby.png` (Bubbles), `gunky.png`, `prickle.png`, `smudge.png`, `sneezel.png` | every screen | Team Figma, frames "Chibi Monster Sticker Squad 1 to 6" | Cut out by Andrew (commit `ceab9da`), unchanged here | **Team to confirm.** The frame name suggests a generated or stock sticker set. Confirm origin and licence before public use. |
| King Prickle, King Sneeze, King Gunk, Rainbow Sneezel | Germ-dex, boss, map | Base germ art + CSS colour shift + an SVG crown drawn here (`components/Creature.tsx`) | Colour filter at render time, original files untouched | Stand-ins. **Art gap:** the design team should draw these four. |
| Buddy colours (mint, berry, sunny) | child profiles | Bubbles art + CSS colour shift | Render time only | Same as Bubbles |
| Bay scene (flat shapes) | Kid Home | Original SVG, `web/src/art/scenes.tsx` | Hand-written for this app | Ours |
| Adventure map | Kid Map | Original isometric SVG, `web/src/art/WorldMap.tsx` | Hand-written | Ours |
| Chest, coin, medals | Rewards | Original SVG, `web/src/art/treasure.tsx` | Hand-written | Ours |
| Station drawing | Onboarding | Original SVG, `web/src/art/station.tsx` | Hand-written | Ours |
| Hand diagram and heatmap | Kid wash, grown-up Overview, Insights, wash detail | Original SVG after the team's lofi mitten diagram, `components/HandFigure.tsx` | Redrawn with separate zones | Ours |
| Charts | Grown-up view | Original SVG, `components/charts.tsx` | Hand-written | Ours |
| Icons (42) | everywhere | Original SVG, `components/icons.tsx` | Hand-written | Ours |
| Nunito Variable | kid view | `@fontsource-variable/nunito` 5.2.7 | Bundled locally by Vite | SIL OFL 1.1 |
| Inter Variable | grown-up view | `@fontsource-variable/inter` 5.2.8 | Bundled locally by Vite | SIL OFL 1.1 |

Not used, on purpose: `image 3.pdf` and `image 5.pdf` (Duolingo screenshots, reference only), the
`visual-target.png` screenshot and the three kid-app screenshots Aarsh sent on 2026-11-24 (style reference only, nothing copied from them), the "scrubby" wordmark image
(`Section 1.pdf`; the app is named Scrubble and sets its name in type).

The hand-written SVG was written by an AI model for this project. No image generator and no outside assets were used.
