// Original SVG: the sink station. A box above the sink looks down at the hands and lights germs onto them.
import { useId } from "react";

export function StationArt({ live = false }: { live?: boolean }) {
  const id = useId();
  return (
    <svg viewBox="0 0 300 230" width="100%" height="100%" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}beam`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#bff6ff" stopOpacity="0.75" /><stop offset="1" stopColor="#bff6ff" stopOpacity="0.08" /></linearGradient>
        <linearGradient id={`${id}sink`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#e8f1ff" /><stop offset="1" stopColor="#a9bbe6" /></linearGradient>
        <linearGradient id={`${id}box`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#8e6fe0" /><stop offset="1" stopColor="#5a3fa6" /></linearGradient>
      </defs>
      {/* wall arm and the station box */}
      <rect x="140" y="6" width="20" height="26" rx="6" fill="#3d4f86" />
      <rect x="98" y="24" width="104" height="44" rx="14" fill={`url(#${id}box)`} stroke="#2c1f66" strokeWidth="3" />
      <path d="M108 34h84" stroke="#fff" strokeOpacity="0.35" strokeWidth="3" strokeLinecap="round" />
      <circle cx="128" cy="50" r="9" fill="#1d1848" stroke="#cfc4ee" strokeWidth="3" /><circle cx="128" cy="50" r="3.5" fill="#58dcd8" />
      <rect x="150" y="43" width="34" height="14" rx="7" fill="#1d1848" stroke="#cfc4ee" strokeWidth="3" />
      <circle cx="190" cy="33" r="4" fill={live ? "#5fdcaa" : "#8f9bd0"} />
      {/* the light cone onto the hands */}
      <path d="M152 58h30l52 104H88z" fill={`url(#${id}beam)`} />
      {/* sink */}
      <path d="M36 164h228l-16 46a14 14 0 0 1-13 9H65a14 14 0 0 1-13-9z" fill={`url(#${id}sink)`} stroke="#5f73ad" strokeWidth="3" strokeLinejoin="round" />
      <ellipse cx="150" cy="166" rx="112" ry="13" fill="#7fd3ea" stroke="#5f73ad" strokeWidth="3" />
      <path d="M232 158v-30a14 14 0 0 0-28 0v6" fill="none" stroke="#c9d6f5" strokeWidth="9" strokeLinecap="round" />
      {/* two hands under the light, with germs on them */}
      <g stroke="#1a1746" strokeWidth="3" strokeLinejoin="round">
        <path d="M96 168c-4-18 2-34 16-40l6 14 6-22 8 2-2 22 10-18 7 4-8 22 12-12 6 6-22 30z" fill="#ffd9b8" />
        <path d="M204 168c4-18-2-34-16-40l-6 14-6-22-8 2 2 22-10-18-7 4 8 22-12-12-6 6 22 30z" fill="#ffd9b8" />
      </g>
      <g>
        <circle cx="118" cy="146" r="9" fill="#8de87b" stroke="#2f8a2a" strokeWidth="2.5" /><circle cx="115" cy="144" r="1.6" fill="#1a1746" /><circle cx="121" cy="144" r="1.6" fill="#1a1746" />
        <circle cx="182" cy="142" r="8" fill="#b08cf2" stroke="#5a3a9c" strokeWidth="2.5" /><circle cx="179.5" cy="140" r="1.5" fill="#1a1746" /><circle cx="184.5" cy="140" r="1.5" fill="#1a1746" />
        <path d="M150 116l2.5 6 6 2.5-6 2.5-2.5 6-2.5-6-6-2.5 6-2.5z" fill="#fff6cf" />
      </g>
    </svg>
  );
}
