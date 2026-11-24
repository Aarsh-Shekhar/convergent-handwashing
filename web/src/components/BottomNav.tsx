import { Link } from "../router";
import { Icon, type IconName } from "./icons";
import "./BottomNav.css";

export const TABS: readonly (readonly [path: string, icon: IconName, label: string])[] = [
  ["/", "home", "Home"], ["/progress", "chart", "Progress"], ["/rewards", "gift", "Rewards"],
  ["/germ-dex", "germ", "Germ-dex"], ["/settings", "gear", "Settings"],
];

/** Which tab a path belongs to: history and wash detail sit under Home, routines under Settings. */
export function tabFor(path: string): string {
  if (path.startsWith("/history")) return "/";
  if (path.startsWith("/routines")) return "/settings";
  return TABS.some(([p]) => p === path) ? path : "/";
}

export function BottomNav({ path }: { path: string }) {
  const current = tabFor(path);
  return (
    <nav className="bottom-nav" aria-label="Main">
      {TABS.map(([to, icon, label]) => (
        <Link key={to} to={to} aria-current={current === to ? "page" : undefined}>
          <span className="orb"><Icon name={icon} size={24} /></span>
          <span className="label">{label}</span>
        </Link>
      ))}
    </nav>
  );
}
