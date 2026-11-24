// Hand-drawn backdrops (original SVG, made for Scrubble). They sit behind panel content and
// are decorative: aria-hidden is set by the panel that hosts them.
import { useId } from "react";

function Bubble({ x, y, r, o = 0.5 }: { x: number; y: number; r: number; o?: number }) {
  return (
    <g opacity={o}>
      <circle cx={x} cy={y} r={r} fill="rgba(170,225,255,0.14)" stroke="rgba(200,238,255,0.75)" strokeWidth={Math.max(1, r * 0.12)} />
      <path d={`M${x - r * 0.52} ${y - r * 0.2}a${r * 0.56} ${r * 0.56} 0 0 1 ${r * 0.42}-${r * 0.42}`} fill="none" stroke="#fff" strokeWidth={Math.max(1, r * 0.16)} strokeLinecap="round" opacity="0.9" />
    </g>
  );
}

function Leaf({ d, a, b }: { d: string; a: string; b: string }) {
  const id = useId();
  return (
    <>
      <defs><linearGradient id={id} x1="0" y1="0" x2="0.4" y2="1"><stop offset="0" stopColor={a} /><stop offset="1" stopColor={b} /></linearGradient></defs>
      <path d={d} fill={`url(#${id})`} />
    </>
  );
}

/** Bubble Bay at dusk: the home panel. Water, reeds and soap bubbles; Bubbles stands on the right rock. */
export function BayScene() {
  const id = useId();
  return (
    <svg viewBox="0 0 360 260" preserveAspectRatio="xMidYMax slice" width="100%" height="100%">
      <defs>
        <linearGradient id={`${id}sky`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#35579a" /><stop offset="0.55" stopColor="#27608f" /><stop offset="1" stopColor="#1f7f96" /></linearGradient>
        <radialGradient id={`${id}glow`} cx="0.72" cy="0.95" r="0.7"><stop offset="0" stopColor="#58e0d6" stopOpacity="0.55" /><stop offset="1" stopColor="#58e0d6" stopOpacity="0" /></radialGradient>
        <linearGradient id={`${id}far`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#2c6aa6" /><stop offset="1" stopColor="#235487" /></linearGradient>
        <linearGradient id={`${id}water`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#35b9c9" /><stop offset="1" stopColor="#1e7da3" /></linearGradient>
        <linearGradient id={`${id}rock`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#7d68c9" /><stop offset="1" stopColor="#4c3a94" /></linearGradient>
      </defs>
      <rect width="360" height="260" fill={`url(#${id}sky)`} />
      <rect width="360" height="260" fill={`url(#${id}glow)`} />
      {/* far shore: rounded pillars, like kelp towers */}
      <g fill={`url(#${id}far)`} opacity="0.75">
        <rect x="16" y="112" width="30" height="150" rx="15" /><rect x="52" y="84" width="38" height="180" rx="19" /><rect x="96" y="128" width="26" height="140" rx="13" />
        <rect x="236" y="96" width="34" height="170" rx="17" /><rect x="276" y="62" width="44" height="200" rx="22" /><rect x="326" y="120" width="30" height="150" rx="15" />
      </g>
      {/* water with two soft wave bands */}
      <path d="M0 190c40-16 80-16 120-4s80 14 120 2 80-16 120-2v74H0z" fill={`url(#${id}water)`} />
      <path d="M0 204c50-10 90 8 140 2s90-14 140-6 60 8 80 4" fill="none" stroke="#9af0f0" strokeOpacity="0.5" strokeWidth="3" strokeLinecap="round" />
      <path d="M20 226c40-8 70 6 110 2M210 232c40-8 70 4 120 0" fill="none" stroke="#9af0f0" strokeOpacity="0.32" strokeWidth="3" strokeLinecap="round" />
      {/* the rock Bubbles stands on */}
      <path d="M196 260c2-34 22-58 62-60 46-2 86 18 102 44v16z" fill={`url(#${id}rock)`} />
      <path d="M214 214c14-9 30-13 48-13 30 0 56 9 76 24" fill="none" stroke="#b7a6f3" strokeOpacity="0.7" strokeWidth="3.5" strokeLinecap="round" />
      {/* reeds and leaves, left */}
      <Leaf d="M-8 260c2-34 14-58 36-72-8 26-6 50 6 72z" a="#8be276" b="#2f9f6b" />
      <Leaf d="M30 260c4-24 16-40 34-48-8 18-8 34-2 48z" a="#5fd6a2" b="#1f8f7d" />
      <Leaf d="M-6 260c8-18 22-28 40-32-12 12-16 22-16 32z" a="#b7f08a" b="#4cb866" />
      <Bubble x={176} y={52} r={10} /><Bubble x={206} y={104} r={6} o={0.45} /><Bubble x={236} y={150} r={12} o={0.4} />
      <Bubble x={232} y={36} r={5} o={0.4} /><Bubble x={338} y={96} r={8} o={0.35} />
    </svg>
  );
}

/** A quiet violet cave wall for wash rows and tips: one glow and a few bubbles. */
export function CaveScene({ tint = "#b08cf2" }: { tint?: string }) {
  const id = useId();
  return (
    <svg viewBox="0 0 360 120" preserveAspectRatio="xMaxYMax slice" width="100%" height="100%">
      <defs><radialGradient id={id} cx="0.86" cy="0.9" r="0.6"><stop offset="0" stopColor={tint} stopOpacity="0.5" /><stop offset="1" stopColor={tint} stopOpacity="0" /></radialGradient></defs>
      <rect width="360" height="120" fill={`url(#${id})`} />
      <path d="M232 120c8-28 30-44 62-46 30-2 54 12 66 30v16z" fill="#fff" opacity="0.07" />
      <Bubble x={236} y={30} r={7} o={0.32} /><Bubble x={338} y={20} r={5} o={0.3} /><Bubble x={214} y={70} r={4} o={0.28} />
    </svg>
  );
}
