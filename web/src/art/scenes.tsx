// Flat, hand-cut backdrops (original SVG, made for Scrubble). Decorative: the panel that hosts them hides them from screen readers.

/** The bay where Bubbles lives: flat sky, two hills, water and a sun. Bubbles stands on the sand at the right. */
export function BayScene() {
  return (
    <svg viewBox="0 0 360 200" preserveAspectRatio="xMidYMax slice" width="100%" height="100%">
      <rect width="360" height="200" fill="#cfe6fb" />
      <circle cx="222" cy="66" r="22" fill="#ffd766" />
      <path d="M0 132c36-34 74-46 112-34 30 10 48 30 70 34H0z" fill="#a8d5b5" />
      <path d="M120 132c40-44 96-56 150-30 36 18 62 26 90 30H120z" fill="#8cc8a4" />
      <path d="M0 130h360v70H0z" fill="#7cc4ee" />
      <path d="M0 144c30-8 60 8 90 0s60-8 90 0 60 8 90 0 60-8 90 0" fill="none" stroke="#fff" strokeOpacity="0.7" strokeWidth="3" strokeLinecap="round" />
      <path d="M0 166c30-8 60 8 90 0s60-8 90 0" fill="none" stroke="#fff" strokeOpacity="0.45" strokeWidth="3" strokeLinecap="round" />
      <path d="M210 200c8-26 40-40 82-40 36 0 58 12 68 22v18z" fill="#f6dfae" />
      {[[150, 96, 7], [176, 112, 4], [330, 92, 6], [24, 104, 5]].map(([x, y, r]) => (
        <g key={`${x}-${y}`}><circle cx={x} cy={y} r={r} fill="#fff" fillOpacity="0.45" stroke="#fff" strokeWidth="1.5" /><circle cx={x - r * 0.3} cy={y - r * 0.3} r={r * 0.22} fill="#fff" /></g>
      ))}
    </svg>
  );
}
