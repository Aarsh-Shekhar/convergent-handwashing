// Original SVG treasure art for the rewards screen.
import { useId } from "react";

export function Coin({ size = 28 }: { size?: number }) {
  const id = useId();
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <defs><radialGradient id={id} cx="0.35" cy="0.28" r="0.8"><stop offset="0" stopColor="#fff3bf" /><stop offset="0.55" stopColor="#f6c64f" /><stop offset="1" stopColor="#d1901c" /></radialGradient></defs>
      <circle cx="16" cy="17.5" r="13" fill="#9a6a10" /><circle cx="16" cy="15" r="13" fill={`url(#${id})`} /><circle cx="16" cy="15" r="9.2" fill="none" stroke="#c98f1e" strokeWidth="1.6" />
      <path d="m16 8.8 1.9 4 4.3.5-3.2 3 .9 4.3L16 18.5l-3.9 2.1.9-4.3-3.2-3 4.3-.5z" fill="#fff6cf" stroke="#c98f1e" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  );
}

/** An open chest spilling coins and bubbles. */
export function Chest() {
  const id = useId();
  return (
    <svg viewBox="0 0 170 150" width="100%" height="100%" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}w`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#c98352" /><stop offset="1" stopColor="#8c5236" /></linearGradient>
        <linearGradient id={`${id}l`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#a8643f" /><stop offset="1" stopColor="#6f3f2c" /></linearGradient>
        <radialGradient id={`${id}g`} cx="0.5" cy="0.5" r="0.5"><stop offset="0" stopColor="#ffe9a8" stopOpacity="0.9" /><stop offset="1" stopColor="#ffe9a8" stopOpacity="0" /></radialGradient>
        <radialGradient id={`${id}c`} cx="0.35" cy="0.3" r="0.8"><stop offset="0" stopColor="#fff3bf" /><stop offset="0.6" stopColor="#f6c64f" /><stop offset="1" stopColor="#d1901c" /></radialGradient>
      </defs>
      <ellipse cx="85" cy="70" rx="80" ry="62" fill={`url(#${id}g)`} />
      <ellipse cx="86" cy="138" rx="62" ry="9" fill="#0b0a2c" opacity="0.4" />
      {/* lid, tipped back */}
      <path d="M30 62c2-30 24-46 56-46s54 16 56 46l-10 8H40z" fill={`url(#${id}l)`} stroke="#4a2a20" strokeWidth="3" strokeLinejoin="round" />
      <path d="M44 60c4-20 20-32 42-32s38 12 42 32" fill="none" stroke="#f6c64f" strokeWidth="5" strokeLinecap="round" />
      {/* coins heaped inside */}
      {[[52, 70, 13], [76, 62, 15], [102, 64, 14], [122, 72, 12], [64, 80, 12], [90, 78, 14], [112, 82, 12]].map(([x, y, r]) => (
        <g key={`${x}${y}`}><ellipse cx={x} cy={y + 2.5} rx={r} ry={r * 0.62} fill="#9a6a10" /><ellipse cx={x} cy={y} rx={r} ry={r * 0.62} fill={`url(#${id}c)`} /><ellipse cx={x} cy={y} rx={r * 0.6} ry={r * 0.34} fill="none" stroke="#c98f1e" strokeWidth="1.4" /></g>
      ))}
      {/* body */}
      <path d="M28 84h116v40a10 10 0 0 1-10 10H38a10 10 0 0 1-10-10z" fill={`url(#${id}w)`} stroke="#4a2a20" strokeWidth="3" strokeLinejoin="round" />
      <path d="M28 98h116" stroke="#4a2a20" strokeWidth="2" opacity="0.5" /><path d="M56 84v50M116 84v50" stroke="#f6c64f" strokeWidth="7" />
      <rect x="75" y="90" width="22" height="24" rx="6" fill="#f6c64f" stroke="#a97212" strokeWidth="2.5" /><circle cx="86" cy="100" r="3.5" fill="#4a2a20" /><path d="M86 101v7" stroke="#4a2a20" strokeWidth="3" strokeLinecap="round" />
      <path d="M33 88h106" stroke="#ffd9b0" strokeWidth="2.5" strokeLinecap="round" opacity="0.6" />
      {/* a sparkle and two bubbles */}
      <path d="M140 30l3 8 8 3-8 3-3 8-3-8-8-3 8-3z" fill="#fff6cf" /><circle cx="24" cy="38" r="7" fill="rgba(170,225,255,0.15)" stroke="#d8f2ff" strokeWidth="1.5" /><circle cx="150" cy="62" r="4" fill="rgba(170,225,255,0.15)" stroke="#d8f2ff" strokeWidth="1.2" />
    </svg>
  );
}

const BADGE_GLYPH: Record<string, JSX.Element> = {
  streak_5: <path d="M24 10c1 6 9 9 9 18a9 9 0 0 1-18 0c0-4 2-6 4-8 1 3 2 4 3 4-1-6 0-10 2-14z" />,
  first_clean: <path d="M24 9c5 7 10 12 10 18a10 10 0 0 1-20 0c0-6 5-11 10-18z" />,
  perfect_10: <path d="m24 9 4.4 9 9.8 1.4-7.1 6.9 1.7 9.8L24 31.5l-8.8 4.6 1.7-9.8-7.1-6.9 9.8-1.4z" />,
  thumb_pro: <path d="M15 22h5l5-11c3 0 4 2 4 4l-1 6h6c2 0 3 2 3 4l-2 9c-.5 2-2 3-4 3H15z" />,
};

/** A round medal. Earned medals are gold; the rest stay stone with a lock. */
export function Medal({ id, earned }: { id: string; earned: boolean }) {
  const g = useId();
  return (
    <svg viewBox="0 0 48 52" width="100%" height="100%" aria-hidden="true">
      <defs><radialGradient id={g} cx="0.35" cy="0.25" r="0.9">
        {earned ? <><stop offset="0" stopColor="#fff3bf" /><stop offset="0.55" stopColor="#f6c64f" /><stop offset="1" stopColor="#c98f1e" /></>
          : <><stop offset="0" stopColor="#56639c" /><stop offset="1" stopColor="#2b3364" /></>}
      </radialGradient></defs>
      <circle cx="24" cy="27" r="22" fill={earned ? "#9a6a10" : "#1c2150"} /><circle cx="24" cy="24" r="22" fill={`url(#${g})`} />
      <circle cx="24" cy="24" r="17" fill="none" stroke={earned ? "#fff6cf" : "#6b78b3"} strokeWidth="1.5" opacity="0.7" />
      <g fill={earned ? "#7a4d08" : "#8f9bd0"} opacity={earned ? 1 : 0.55} transform="translate(0 1)">{BADGE_GLYPH[id] ?? BADGE_GLYPH.perfect_10}</g>
    </svg>
  );
}
