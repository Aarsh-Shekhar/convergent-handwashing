// The design team's characters. Each germ lives on one part of the hands.
import type { Zone } from "../api";
import gunky from "../assets/gunky.png";
import prickle from "../assets/prickle.png";
import scrubby from "../assets/scrubby.png";
import smudge from "../assets/smudge.png";
import sneezel from "../assets/sneezel.png";

export const ART: Record<string, string> = { gunky, prickle, scrubby, smudge, sneezel };
// germs drawn as a colour shift of a base germ until the design team draws their own
const VARIANT: Record<string, { art: string; filter?: string }> = {
  king_sneeze: { art: sneezel, filter: "saturate(1.4) hue-rotate(-12deg)" },
  king_gunk: { art: gunky, filter: "saturate(1.3) hue-rotate(28deg)" },
  king_prickle: { art: prickle, filter: "saturate(1.3) hue-rotate(-20deg)" },
  rainbow_sneezel: { art: sneezel, filter: "hue-rotate(150deg) saturate(1.5)" },
};
const ZONE_GERM: Record<Zone, string> = {
  palms: "gunky", between_fingers: "sneezel", thumbs: "prickle", nails: "smudge", backs: "rainbow_sneezel", wrists: "gunky",
};

export function germFor(zone: Zone): string {
  return ZONE_GERM[zone];
}

export function Germ({ id, size = 48, bob = false, dim = false, className = "" }: {
  id: string; size?: number; bob?: boolean; dim?: boolean; className?: string;
}) {
  const v = VARIANT[id] ?? { art: ART[id] ?? scrubby };
  const img = (
    <img src={v.art} alt="" width={size} height={size} className={`${bob ? "bob" : ""} ${className}`}
      style={{ objectFit: "contain", filter: dim ? "grayscale(1) opacity(0.35)" : v.filter }} />
  );
  if (!id.startsWith("king_")) return img;
  return ( // kings wear a crown until the design team draws them
    <span className="crowned" style={{ width: size, height: size }}>
      {img}
      <svg className="crown" width={size * 0.42} height={size * 0.3} viewBox="0 0 40 28" aria-hidden="true" style={{ opacity: dim ? 0.4 : 1 }}>
        <path d="M3 25 L6 7 L15 16 L20 3 L25 16 L34 7 L37 25 Z" fill="#f6b93b" stroke="#a86b00" strokeWidth="2" strokeLinejoin="round" />
      </svg>
    </span>
  );
}
