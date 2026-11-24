// The team's characters (art from the design team's Figma export, see docs/art-manifest.md).
// Bubbles is the soap-bubble hero; each germ lives on one part of the hands.
import type { CSSProperties } from "react";
import type { Zone } from "../api";
import gunky from "../assets/gunky.png";
import prickle from "../assets/prickle.png";
import bubbles from "../assets/scrubby.png";
import smudge from "../assets/smudge.png";
import sneezel from "../assets/sneezel.png";
import "./Creature.css";

type Look = { art: string; filter?: string; crown?: boolean; ratio: number };
// width / height of each drawing, so a creature never shifts the layout while it loads
const BASE: Record<string, Look> = {
  bubbles: { art: bubbles, ratio: 360 / 274 },
  gunky: { art: gunky, ratio: 360 / 330 },
  prickle: { art: prickle, ratio: 345 / 360 },
  smudge: { art: smudge, ratio: 360 / 337 },
  sneezel: { art: sneezel, ratio: 344 / 360 },
};
// Kings and the rainbow germ are colour shifts of a base germ plus a crown drawn here,
// until the design team draws their own (listed as an art gap in docs/art-manifest.md).
const LOOKS: Record<string, Look> = {
  ...BASE,
  king_prickle: { ...BASE.prickle, filter: "saturate(1.25) hue-rotate(-24deg)", crown: true },
  king_sneeze: { ...BASE.sneezel, filter: "saturate(1.35) hue-rotate(-14deg)", crown: true },
  king_gunk: { ...BASE.gunky, filter: "saturate(1.2) hue-rotate(34deg)", crown: true },
  rainbow_sneezel: { ...BASE.sneezel, filter: "hue-rotate(150deg) saturate(1.5)" },
  // buddies a child can pick: Bubbles in four colours
  scrubby: BASE.bubbles,
  minty: { ...BASE.bubbles, filter: "hue-rotate(-48deg) saturate(1.05)" },
  berry: { ...BASE.bubbles, filter: "hue-rotate(72deg) saturate(1.1)" },
  sunny: { ...BASE.bubbles, filter: "hue-rotate(-170deg) saturate(1.5) brightness(1.12)" },
};
export const BUDDIES = [["scrubby", "Blue"], ["minty", "Mint"], ["berry", "Berry"], ["sunny", "Sunny"]] as const;

const ZONE_GERM: Record<Zone, string> = {
  palms: "gunky", between_fingers: "sneezel", thumbs: "prickle", nails: "smudge", backs: "rainbow_sneezel", wrists: "gunky",
};
export const germFor = (zone: Zone): string => ZONE_GERM[zone];

export function Crown({ size }: { size: number }) {
  return (
    <svg className="crown" width={size} height={size * 0.72} viewBox="0 0 50 36" aria-hidden="true">
      <path d="M4 12 14 22 25 4l11 18 10-10-3.5 20h-35z" fill="#f6c64f" stroke="#a97212" strokeWidth="2.6" strokeLinejoin="round" />
      <path d="M8.5 27h33" stroke="#fff3c4" strokeWidth="2.4" strokeLinecap="round" opacity="0.85" />
      <circle cx="25" cy="19" r="3" fill="#f58fa0" stroke="#a97212" strokeWidth="1.6" />
      <circle cx="4" cy="12" r="2.6" fill="#ffe08a" stroke="#a97212" strokeWidth="1.4" /><circle cx="46" cy="12" r="2.6" fill="#ffe08a" stroke="#a97212" strokeWidth="1.4" /><circle cx="25" cy="4" r="2.6" fill="#ffe08a" stroke="#a97212" strokeWidth="1.4" />
    </svg>
  );
}

/** A character. `locked` shows only its shape; `label` names it for screen readers (decorative when omitted). */
export function Creature({ id, size = 64, locked = false, bob = false, label, className = "", style }: {
  id: string; size?: number; locked?: boolean; bob?: boolean; label?: string; className?: string; style?: CSSProperties;
}) {
  const look = LOOKS[id] ?? BASE.bubbles;
  const w = look.ratio >= 1 ? size : size * look.ratio;
  const h = look.ratio >= 1 ? size / look.ratio : size;
  return (
    <span className={`creature ${bob ? "bob" : ""} ${locked ? "locked" : ""} ${className}`} style={{ width: size, height: size, ...style }}
      role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <img src={look.art} alt="" width={Math.round(w)} height={Math.round(h)} draggable={false}
        style={{ filter: locked ? undefined : look.filter }} />
      {look.crown && !locked && <Crown size={size * 0.44} />}
    </span>
  );
}
