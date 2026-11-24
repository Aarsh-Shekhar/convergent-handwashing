// Palm and back of a hand with each washing zone drawn as its own shape (original SVG, after the
// team's lofi hand diagrams). A zone's look comes from how much of its scrubbing time was recognized:
// washed, partly, or missed. Missed zones are also hatched and listed by name, so colour is never the only cue.
import { useId } from "react";
import { ZONE_NAMES, ZONES, type Zone } from "../api";
import "./RegionHandMap.css";

export type ZoneState = "washed" | "partly" | "missed" | "unknown";
export function zoneState(cover: number | undefined, recognized: boolean): ZoneState {
  if (!recognized || cover === undefined) return "unknown";
  return cover >= 1 ? "washed" : cover > 0 ? "partly" : "missed";
}

const FINGERS: readonly (readonly [x: number, top: number])[] = [[36, 36], [58, 18], [80, 24], [102, 44]];
const FINGER_W = 19;
const KNUCKLE_Y = 96;

function Hand({ side, state, hatch }: { side: "palm" | "back"; state: (z: Zone) => ZoneState; hatch: string }) {
  const body: Zone = side === "palm" ? "palms" : "backs";
  const fingers: Zone = side === "palm" ? "between_fingers" : "backs";
  const cls = (z: Zone) => `zone ${state(z)}`;
  const over = (z: Zone, shape: JSX.Element) => state(z) === "missed" ? <g fill={`url(#${hatch})`} className="hatch">{shape}</g> : null;
  const thumb = <rect x="6" y="84" width="22" height="58" rx="11" transform="rotate(-32 28 142)" />;
  const palm = <path d="M34 92h89a8 8 0 0 1 8 8v40a34 34 0 0 1-34 34H62a34 34 0 0 1-34-34v-42a6 6 0 0 1 6-6z" />;
  const wrist = <rect x="50" y="170" width="60" height="30" rx="9" />;
  return (
    <svg viewBox="-12 6 156 200" className={`hand ${side}`} aria-hidden="true">
      <g className={cls("wrists")}>{wrist}</g>{over("wrists", wrist)}
      <g className={cls("thumbs")}>{thumb}</g>{over("thumbs", thumb)}
      {FINGERS.map(([x, top]) => {
        const shaft = <rect x={x} y={top + 18} width={FINGER_W} height={KNUCKLE_Y - top - 6} rx={5} />;
        const tip = <path d={`M${x} ${top + 22}v-${12.5}a${FINGER_W / 2} ${FINGER_W / 2} 0 0 1 ${FINGER_W} 0v${12.5}z`} />;
        return (
          <g key={x}>
            <g className={cls(fingers)}>{shaft}</g>{over(fingers, shaft)}
            <g className={cls("nails")}>{tip}</g>{over("nails", tip)}
            {side === "back" && <rect x={x + 5} y={top + 11} width={FINGER_W - 10} height={8} rx={3.5} className="nail" />}
          </g>
        );
      })}
      <g className={cls(body)}>{palm}</g>{over(body, palm)}
      {side === "palm"
        ? <path d="M48 124c16 12 40 12 62-2M52 146c14 8 30 8 44 2" className="crease" />
        : <path d="M45 104h0M67 100h0M89 100h0M111 106h0" className="knuckles" />}
    </svg>
  );
}

/** The two hands, a legend, and a text summary for screen readers. */
export function RegionHandMap({ coverage, recognized }: { coverage: Record<Zone, number>; recognized: boolean }) {
  const hatch = useId();
  const state = (z: Zone) => zoneState(coverage[z], recognized);
  const missed = ZONES.filter((z) => state(z) === "missed").map((z) => ZONE_NAMES[z].toLowerCase());
  const partly = ZONES.filter((z) => state(z) === "partly").map((z) => ZONE_NAMES[z].toLowerCase());
  const summary = !recognized ? "No scrubbing was recognized in this wash."
    : `Missed: ${missed.join(", ") || "nothing"}. Partly washed: ${partly.join(", ") || "nothing"}. Everything else was washed.`;
  return (
    <figure className="handmap" role="img" aria-label={`Hand map. ${summary}`}>
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
        <defs>
          <pattern id={hatch} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(40)">
            <rect width="3" height="7" fill="rgba(110,20,50,0.45)" />
          </pattern>
        </defs>
      </svg>
      <div className="pair">
        <div><Hand side="palm" state={state} hatch={hatch} /><figcaption>Palm</figcaption></div>
        <div><Hand side="back" state={state} hatch={hatch} /><figcaption>Back</figcaption></div>
      </div>
      <ul className="legend" aria-hidden="true">
        <li><i className="washed" />Washed</li><li><i className="partly" />Partly</li><li><i className="missed" />Missed</li>
        {!recognized && <li><i className="unknown" />Not seen</li>}
      </ul>
    </figure>
  );
}
