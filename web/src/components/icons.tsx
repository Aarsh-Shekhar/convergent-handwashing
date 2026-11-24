// Scrubble's icon family: one 24px grid, 2px rounded line icons.
// Drawn for this app so every screen shares one hand.
import type { ReactNode } from "react";

const soft = {} as const; // shapes that used to carry a tint are plain outlines now

const PATHS = {
  grid: <><rect x="4" y="4" width="6.5" height="6.5" rx="1.5" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" /><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" /><path d="M16.75 13.5v6.5M13.5 16.75H20" /></>,
  home: <><path {...soft} d="M4.5 11 12 4.5l7.5 6.5v7.2a1.8 1.8 0 0 1-1.8 1.8H6.3a1.8 1.8 0 0 1-1.8-1.8z" /><path d="M9.6 20v-4.4a2.4 2.4 0 0 1 4.8 0V20" /></>,
  chart: <><rect {...soft} x="4" y="11" width="4.2" height="9" rx="1.6" /><rect {...soft} x="9.9" y="5" width="4.2" height="15" rx="1.6" /><rect {...soft} x="15.8" y="8.5" width="4.2" height="11.5" rx="1.6" /></>,
  gift: <><rect {...soft} x="4.5" y="11" width="15" height="9" rx="2" /><rect x="3.5" y="7.5" width="17" height="3.8" rx="1.4" /><path d="M12 7.5V20M12 7.3C10.6 4 7 3.6 7 5.8c0 1.5 2.4 1.7 5 1.5zm0 0c1.4-3.3 5-3.7 5-1.5 0 1.5-2.4 1.7-5 1.5z" /></>,
  germ: <><circle {...soft} cx="12" cy="12" r="5.6" /><path d="M12 3.2v2.6M12 18.2v2.6M3.2 12h2.6M18.2 12h2.6M5.8 5.8l1.9 1.9M16.3 16.3l1.9 1.9M5.8 18.2l1.9-1.9M16.3 7.7l1.9-1.9" /><circle cx="10" cy="11" r="0.9" fill="currentColor" stroke="none" /><circle cx="14" cy="11" r="0.9" fill="currentColor" stroke="none" /></>,
  gear: <><path {...soft} d="M10.3 3.6h3.4l.5 2.3 1.9 1.1 2.2-.8 1.7 3-1.7 1.6v2.4l1.7 1.6-1.7 3-2.2-.8-1.9 1.1-.5 2.3h-3.4l-.5-2.3-1.9-1.1-2.2.8-1.7-3 1.7-1.6v-2.4L4 9.2l1.7-3 2.2.8 1.9-1.1z" /><circle cx="12" cy="12" r="2.6" /></>,
  back: <path d="M19 12H5.5M11 6l-6 6 6 6" />,
  next: <path d="M5 12h13.5M13 6l6 6-6 6" />,
  chevron: <path d="m9.5 6 6 6-6 6" />,
  plus: <path d="M12 5.5v13M5.5 12h13" />,
  minus: <path d="M5.5 12h13" />,
  check: <path d="m5 12.6 4.4 4.4L19 7.4" />,
  close: <path d="m6.5 6.5 11 11M17.5 6.5l-11 11" />,
  lock: <><rect {...soft} x="5.5" y="10.5" width="13" height="9.5" rx="2.6" /><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" /></>,
  bolt: <path {...soft} d="M13.4 3 5.6 13.2h5.2L9.8 21l8.6-11h-5.6z" />,
  coin: <><circle {...soft} cx="12" cy="12" r="8.2" /><path d="m12 7.6 1.3 2.8 3 .4-2.2 2.1.6 3-2.7-1.5-2.7 1.5.6-3-2.2-2.1 3-.4z" /></>,
  flame: <path {...soft} d="M12 3.2c.6 3.2 5.4 5 5.4 10.2A5.4 5.4 0 0 1 12 20.8a5.4 5.4 0 0 1-5.4-5.4c0-2.2 1.2-3.4 2.3-4.6.4 1.4 1 2 1.8 2.3-.3-3.4.2-6.9 1.3-9.9z" />,
  star: <path {...soft} d="m12 3.6 2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z" />,
  clock: <><circle {...soft} cx="12" cy="12" r="8.2" /><path d="M12 7.4V12l3 2" /></>,
  bell: <><path {...soft} d="M6.2 16.5V11a5.8 5.8 0 0 1 11.6 0v5.5l1.4 1.7H4.8z" /><path d="M10 20.2a2.2 2.2 0 0 0 4 0" /></>,
  hand: <path {...soft} d="M8.2 12.5V6.3a1.5 1.5 0 0 1 3 0V11m0-.5V4.8a1.5 1.5 0 0 1 3 0V11m0-.3V6a1.5 1.5 0 0 1 3 0v8.3c0 3.6-2.4 6.2-6 6.2-2.6 0-4-1-5.4-3.2L4.2 14a1.5 1.5 0 0 1 2.5-1.6l1.5 1.9" />,
  drop: <path {...soft} d="M12 3.4c3 3.8 5.8 6.8 5.8 10.4a5.8 5.8 0 0 1-11.6 0c0-3.6 2.8-6.6 5.8-10.4z" />,
  trash: <><path {...soft} d="M6.5 8h11l-.8 10.6a1.8 1.8 0 0 1-1.8 1.6H9.1a1.8 1.8 0 0 1-1.8-1.6z" /><path d="M4.5 8h15M9.5 8V5.6c0-.6.4-1 1-1h3c.6 0 1 .4 1 1V8" /></>,
  pencil: <><path {...soft} d="m5 19 .9-3.8L15.6 5.5a1.9 1.9 0 0 1 2.7 0l.2.2a1.9 1.9 0 0 1 0 2.7L8.8 18.1z" /><path d="m14 7.2 2.8 2.8" /></>,
  shield: <><path {...soft} d="M12 3.4 5.2 6v5.6c0 4.2 2.8 7.4 6.8 9 4-1.6 6.8-4.8 6.8-9V6z" /><path d="m9.2 12 2 2 3.6-3.8" /></>,
  station: <><rect {...soft} x="4" y="4.5" width="16" height="10.5" rx="2.6" /><path d="M12 15v3M7.5 19.5h9" /><circle cx="12" cy="9.7" r="1.5" /></>,
  map: <><path {...soft} d="m4 6.5 5-2 6 2 5-2v13l-5 2-6-2-5 2z" /><path d="M9 4.5v13M15 6.5v13" /></>,
  list: <><path d="M9 7h10.5M9 12h10.5M9 17h10.5" /><circle cx="5" cy="7" r="1.2" fill="currentColor" /><circle cx="5" cy="12" r="1.2" fill="currentColor" /><circle cx="5" cy="17" r="1.2" fill="currentColor" /></>,
  crown: <path {...soft} d="m4 8.5 4.2 3.7L12 6l3.8 6.2L20 8.5 18.5 18h-13z" />,
  heart: <path {...soft} d="M12 20s-7.5-4.4-7.5-9.7A4.2 4.2 0 0 1 12 7.7a4.2 4.2 0 0 1 7.5 2.6C19.5 15.6 12 20 12 20z" />,
  book: <><path {...soft} d="M5 5.5c2.6-.8 4.8-.5 7 1 2.2-1.5 4.4-1.8 7-1v12.5c-2.6-.8-4.8-.5-7 1-2.2-1.5-4.4-1.8-7-1z" /><path d="M12 6.5V19" /></>,
  movie: <><rect {...soft} x="4" y="6" width="16" height="13" rx="2.4" /><path d="m4 10 16-3M8.5 6.3l2 3M13.5 5.6l2 3" /></>,
  park: <><path {...soft} d="M12 3.5 6.5 11h3L6 16h12l-3.5-5h3z" /><path d="M12 16v4.5" /></>,
  treat: <><path {...soft} d="M7 10.5h10L15.5 20h-7z" /><path d="M6.5 10.5a5.5 5.5 0 0 1 11 0M12 5V3.5" /></>,
  game: <><rect {...soft} x="3.5" y="8" width="17" height="10" rx="5" /><path d="M8 11.5v3M6.5 13h3" /><circle cx="15" cy="12" r="1" fill="currentColor" /><circle cx="17.2" cy="14.2" r="1" fill="currentColor" /></>,
  sparkle: <path {...soft} d="M12 3.5 13.8 9l5.7 1.8-5.7 1.8L12 18.2l-1.8-5.6-5.7-1.8L10.2 9zM18.5 16l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" />,
  info: <><circle {...soft} cx="12" cy="12" r="8.2" /><path d="M12 11v5.2" /><circle cx="12" cy="7.9" r="1.1" fill="currentColor" stroke="none" /></>,
  kid: <><circle {...soft} cx="12" cy="9" r="4.2" /><path {...soft} d="M4.8 20a7.2 7.2 0 0 1 14.4 0z" /></>,
  retry: <><path d="M19 12a7 7 0 1 1-2.3-5.2" /><path d="M19.2 4.5v4h-4" /></>,
  phone: <><rect x="6.5" y="3" width="11" height="18" rx="2.6" /><path d="M10.5 18h3" /></>,
  desktop: <><rect x="3" y="4.5" width="18" height="12" rx="2" /><path d="M9 20h6M12 16.5V20" /></>,
  live: <><circle cx="12" cy="12" r="2.4" /><path d="M7.2 7.2a6.8 6.8 0 0 0 0 9.6M16.8 7.2a6.8 6.8 0 0 1 0 9.6M4.6 4.6a10.4 10.4 0 0 0 0 14.8M19.4 4.6a10.4 10.4 0 0 1 0 14.8" /></>,
  out: <><path d="M10 4.5H6.5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2H10" /><path d="M14.5 8l4 4-4 4M18.5 12H9.5" /></>,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 24 }: { name: IconName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {PATHS[name]}
    </svg>
  );
}
