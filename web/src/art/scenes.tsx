// Flat, hand-cut backdrops (original SVG, made for Scrubble). Decorative: the panel that hosts them hides them from screen readers.

/** The bay where Bubbles lives: an evening sky, two hills, water and a low sun. Bubbles stands on the sand at the right. */
export function BayScene({ wide }: { wide?: boolean }) {
  // On a wide panel the picture keeps its size at the right edge and the sky, water and waves run on to the left.
  const wave = (y: number, from: number) => `M${from} ${y}` + Array.from({ length: Math.ceil((360 - from) / 180) }, () => "c30-8 60 8 90 0s60-8 90 0").join("");
  return (
    <svg viewBox="0 0 360 200" preserveAspectRatio={wide ? "xMaxYMax meet" : "xMidYMax slice"} width="100%" height="100%" overflow="visible">
      <rect x="-1800" width="2160" height="200" fill="#3a56b4" />
      <circle cx="222" cy="66" r="22" fill="#ffe59a" />
      <path d="M0 132c36-34 74-46 112-34 30 10 48 30 70 34H0z" fill="#3f9d8f" />
      <path d="M120 132c40-44 96-56 150-30 36 18 62 26 90 30H120z" fill="#2f8580" />
      <path d="M-1800 130h2160v70h-2160z" fill="#2fa3d8" />
      <path d={wave(144, -1800)} fill="none" stroke="#fff" strokeOpacity="0.7" strokeWidth="3" strokeLinecap="round" />
      <path d={wave(166, -1710)} fill="none" stroke="#fff" strokeOpacity="0.4" strokeWidth="3" strokeLinecap="round" />
      <path d="M210 200c8-26 40-40 82-40 36 0 58 12 68 22v18z" fill="#f3d594" />
      {[[196, 104, 4], [330, 92, 6]].map(([x, y, r]) => (
        <g key={`${x}-${y}`}><circle cx={x} cy={y} r={r} fill="#fff" fillOpacity="0.45" stroke="#fff" strokeWidth="1.5" /><circle cx={x - r * 0.3} cy={y - r * 0.3} r={r * 0.22} fill="#fff" /></g>
      ))}
    </svg>
  );
}
