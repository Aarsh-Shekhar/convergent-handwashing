# Art manifest

| Asset | Where used | Source | Conversion | Rights |
| --- | --- | --- | --- | --- |
| `web/src/assets/scrubby.png` (Bubbles), `gunky.png`, `prickle.png`, `smudge.png`, `sneezel.png` | every screen | Team Figma, frames "Chibi Monster Sticker Squad 1 to 6" | Cut out by Andrew (commit `ceab9da`), unchanged here | **Team to confirm.** The frame name suggests a generated or stock sticker set. Confirm origin and licence before public use. |
| King Prickle, King Sneeze, King Gunk, Rainbow Sneezel | Germ-dex, boss, map | Base germ art + CSS colour shift + an SVG crown drawn here (`components/Creature.tsx`) | Colour filter at render time, original files untouched | Stand-ins. **Art gap:** the design team should draw these four. |
| Buddy colours (mint, berry, sunny) | child profiles | Bubbles art + CSS colour shift | Render time only | Same as Bubbles |
| Bay scene, cave scene | Home, wash rows, boss panel | Original SVG, `web/src/art/scenes.tsx` | Hand-written for this app | Ours |
| Adventure map | Progress | Original isometric SVG, `web/src/art/WorldMap.tsx` | Hand-written | Ours |
| Chest, coin, medals | Rewards | Original SVG, `web/src/art/treasure.tsx` | Hand-written | Ours |
| Station drawing | Onboarding | Original SVG, `web/src/art/station.tsx` | Hand-written | Ours |
| Hand diagram | Wash detail | Original SVG after the team's lofi mitten diagram, `components/RegionHandMap.tsx` | Redrawn with separate zones | Ours |
| Icons (39) | everywhere | Original SVG, `components/icons.tsx` | Hand-written | Ours |
| Nunito Variable | all text | `@fontsource-variable/nunito` 5.2.7 | Bundled locally by Vite | SIL OFL 1.1 |

Not used, on purpose: `image 3.pdf` and `image 5.pdf` (Duolingo screenshots, reference only), the
`visual-target.png` screenshot (style reference only, nothing copied from it), the "scrubby" wordmark image
(`Section 1.pdf`; the app is named Scrubble and sets its name in type).

The hand-written SVG was written by an AI model for this project. No image generator and no outside assets were used.
