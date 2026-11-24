// Palm and back of a hand with each washing zone drawn as its own shape (original SVG, after the team's
// lofi hand diagrams). The caller decides what a zone's colour means: a state in the kid view,
// a share from 0 to 100% in the grown-up heatmap.
import { useId, type ReactElement } from "react";
import { ZONE_NAMES, ZONES, type Zone } from "../api";
import { useMode } from "../mode";

export type ZoneState = "washed" | "partly" | "missed" | "unknown";
export function zoneState(cover: number | undefined | null, recognized: boolean): ZoneState {
  if (!recognized || cover === undefined || cover === null) return "unknown";
  return cover >= 1 ? "washed" : cover > 0 ? "partly" : "missed";
}
export const STATE_FILL: Record<ZoneState, string> = { washed: "#8fe0bd", partly: "#ffd766", missed: "#f59a96", unknown: "#dfe3ec" };

/** Five steps of one blue for a share from 0 to 1 (null = no data: neutral grey). */
export function heatFill(v: number | null): string {
  if (v === null) return "var(--seq-0)";
  return ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)"][Math.min(4, Math.floor(Math.max(0, v) * 5))];
}

const FINGERS: readonly (readonly [x: number, top: number])[] = [[36, 36], [58, 18], [80, 24], [102, 44]];
const FW = 19;
const KNUCKLE_Y = 96;

/** `plain` is the grown-up drawing: cells split by white gaps, no outline, no highlights. */
function Hand({ side, fill, hatched, hatch, plain }: { side: "palm" | "back"; fill: (z: Zone) => string; hatched: (z: Zone) => boolean; hatch: string; plain: boolean }) {
  const body: Zone = side === "palm" ? "palms" : "backs";
  const fingers: Zone = side === "palm" ? "between_fingers" : "backs";
  const part = (z: Zone, shape: ReactElement, key?: string) => (
    <g key={key}>
      <g fill={fill(z)} stroke={plain ? "var(--surface)" : "#141a40"} strokeWidth={plain ? 2 : 2.5} strokeLinejoin="round">{shape}</g>
      {hatched(z) && <g fill={`url(#${hatch})`}>{shape}</g>}
    </g>
  );
  return (
    <svg viewBox="-12 6 156 200" className={`hand hand-${side}`} aria-hidden="true">
      {part("wrists", <rect x="50" y="170" width="60" height="30" rx="9" />)}
      {part("thumbs", <rect x="6" y="84" width="22" height="58" rx="11" transform="rotate(-32 28 142)" />)}
      {FINGERS.map(([x, top]) => (
        <g key={x}>
          {part(fingers, <rect x={x} y={top + 18} width={FW} height={KNUCKLE_Y - top - 6} rx={5} />)}
          {part("nails", <path d={`M${x} ${top + 22}v-12.5a${FW / 2} ${FW / 2} 0 0 1 ${FW} 0v12.5z`} />)}
          {side === "back" && !plain && <rect x={x + 5} y={top + 11} width={FW - 10} height={8} rx={3.5} fill="#fff" opacity="0.55" />}
        </g>
      ))}
      {part(body, <path d="M34 92h89a8 8 0 0 1 8 8v40a34 34 0 0 1-34 34H62a34 34 0 0 1-34-34v-42a6 6 0 0 1 6-6z" />)}
      {side === "palm" && !plain && <path d="M48 124c16 12 40 12 62-2M52 146c14 8 30 8 44 2" fill="none" stroke="#27304f" strokeOpacity="0.25" strokeWidth="2.5" strokeLinecap="round" />}
    </svg>
  );
}

/** Both sides of a hand. `summary` is read by screen readers in place of the drawing. */
export function HandFigure({ fill, hatched = () => false, summary }: { fill: (z: Zone) => string; hatched?: (z: Zone) => boolean; summary: string }) {
  const hatch = useId();
  const plain = useMode().view === "parent";
  return (
    <figure className="hands" role="img" aria-label={summary}>
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
        <defs><pattern id={hatch} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(40)"><rect width="2.5" height="7" fill="rgba(125,36,32,0.5)" /></pattern></defs>
      </svg>
      <div><Hand side="palm" fill={fill} hatched={hatched} hatch={hatch} plain={plain} /><figcaption>Palm side</figcaption></div>
      <div><Hand side="back" fill={fill} hatched={hatched} hatch={hatch} plain={plain} /><figcaption>Back side</figcaption></div>
    </figure>
  );
}

/** One wash: each zone washed, partly or missed. Missed zones are also hatched, so colour is not the only cue. */
export function WashHands({ coverage, recognized }: { coverage: Record<Zone, number>; recognized: boolean }) {
  const st = (z: Zone) => zoneState(coverage[z], recognized);
  const list = (s: ZoneState) => ZONES.filter((z) => st(z) === s).map((z) => ZONE_NAMES[z].toLowerCase()).join(", ") || "nothing";
  const summary = recognized ? `Hand map. Missed: ${list("missed")}. Partly washed: ${list("partly")}. Everything else was washed.` : "Hand map. No scrubbing was recognized in this wash.";
  return (
    <>
      <HandFigure fill={(z) => STATE_FILL[st(z)]} hatched={(z) => st(z) === "missed"} summary={summary} />
      <ul className="legend" aria-hidden="true">
        <li><i style={{ background: STATE_FILL.washed }} />Washed</li><li><i style={{ background: STATE_FILL.partly }} />Partly</li>
        <li><i className="hatch" style={{ background: STATE_FILL.missed }} />Missed</li>{!recognized && <li><i style={{ background: STATE_FILL.unknown }} />Not seen</li>}
      </ul>
    </>
  );
}
