// Palm and back of a hand, each part coloured clean (green) or missed (coral) for one wash.
import type { Zone } from "../api";

const CLEAN = "#c9efb6";
const MISSED = "#f59a8c";
const FINGERS = [ // x, top, height
  [33, 26, 50], [47, 14, 60], [61, 18, 56], [75, 32, 44],
];

function Hand({ coverage, back }: { coverage: Record<Zone, number>; back: boolean }) {
  const fill = (z: Zone) => (coverage[z] >= 1 ? CLEAN : MISSED);
  const fingerZone: Zone = back ? "backs" : "between_fingers";
  const bodyZone: Zone = back ? "backs" : "palms";
  return (
    <svg width="112" height="140" viewBox="-10 0 130 162" role="img"
      aria-label={`${back ? "Back" : "Palm"} of hand`} style={{ transform: back ? "scaleX(-1)" : undefined }}>
      <g stroke="#26395a" strokeWidth="2.2" strokeLinejoin="round">
        <rect x="38" y="128" width="44" height="28" rx="5" fill={fill("wrists")} />
        <rect x="18" y="70" width="14" height="48" rx="7" fill={fill("thumbs")} transform="rotate(-28 32 118)" />
        {FINGERS.map(([x, y, h]) => (
          <g key={x}>
            <rect x={x} y={y} width="12" height={h} rx="6" fill={fill(fingerZone)} />
            <path d={`M${x} ${y + 12} v-6 a6 6 0 0 1 12 0 v6 z`} fill={fill("nails")} />
          </g>
        ))}
        <rect x="29" y="66" width="62" height="68" rx="18" fill={fill(bodyZone)} />
      </g>
      <text x="60" y="104" textAnchor="middle" fontSize="11" fontWeight="700" fill="#26395a" fontFamily="Inter Variable, sans-serif"
        style={{ transform: back ? "scaleX(-1)" : undefined, transformOrigin: "60px 100px" }}>{back ? "BACK" : "PALM"}</text>
    </svg>
  );
}

export function HandMap({ coverage }: { coverage: Record<Zone, number> }) {
  return (
    <>
      <div className="hands">
        <figure><Hand coverage={coverage} back={false} /></figure>
        <figure><Hand coverage={coverage} back /></figure>
      </div>
      <div className="legend"><span><i style={{ background: CLEAN }} />Clean</span><span><i style={{ background: MISSED }} />Missed</span></div>
    </>
  );
}
