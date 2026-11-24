// Navigation for both views, the Kid / Grown-up switch and the Phone / Desktop switch.
import { useApi, type Child } from "../api";
import bubbles from "../assets/scrubby.png";
import { useLive } from "../live";
import { useMode, type View } from "../mode";
import { useParentGate } from "../parent";
import { go, Link } from "../router";
import { send } from "../api";
import { Icon, type IconName } from "./icons";

type Item = readonly [path: string, icon: IconName, label: string];
export const KID_NAV: readonly Item[] = [["/kid", "home", "Home"], ["/kid/live", "live", "Live"], ["/kid/map", "map", "Map"], ["/kid/germs", "germ", "Germs"], ["/kid/rewards", "gift", "Rewards"]];
export const PARENT_NAV: readonly Item[] = [["/", "home", "Overview"], ["/washes", "list", "Washes"], ["/insights", "chart", "Insights"], ["/rewards", "gift", "Rewards"], ["/station", "station", "Station"]];

/** The nav item a path belongs to (a wash's page sits under Washes, a kid's wash result under Home). */
export function currentItem(path: string, view: View): string {
  if (view === "kid") return KID_NAV.map(([p]) => p).filter((p) => p !== "/kid").find((p) => path.startsWith(p)) ?? "/kid";
  if (path.startsWith("/washes")) return "/washes";
  return PARENT_NAV.some(([p]) => p === path) ? path : path === "/settings" ? "/settings" : "/";
}

export function Brand() {
  return <span className="brand"><img src={bubbles} alt="" width={30} height={23} />Scrubble</span>;
}

/** Kid or grown-up. Going to the grown-up side asks for the parent PIN when one is set. */
export function ViewSwitch() {
  const { view } = useMode();
  const gate = useParentGate();
  const pick = async (v: View) => {
    if (v === view) return;
    if (v === "parent" && !(await gate.ask())) return;
    go(v === "kid" ? "/kid" : "/");
  };
  return (
    <div className="switch" role="group" aria-label="Who is using the app">
      <button type="button" aria-pressed={view === "kid"} onClick={() => pick("kid")}>Kid</button>
      <button type="button" aria-pressed={view === "parent"} onClick={() => pick("parent")}>Grown-up</button>
    </div>
  );
}

/** Phone or desktop layout. Only offered on a screen wide enough for both. */
export function DeviceSwitch() {
  const { device, setDevice, canPickDevice } = useMode();
  if (!canPickDevice) return null;
  return (
    <div className="switch" role="group" aria-label="Layout">
      <button type="button" aria-pressed={device === "phone"} onClick={() => setDevice("phone")}><Icon name="phone" size={16} />Phone</button>
      <button type="button" aria-pressed={device === "desktop"} onClick={() => setDevice("desktop")}><Icon name="desktop" size={16} />Desktop</button>
    </div>
  );
}

/** Whose washes the app shows. The station cannot tell children apart, so a grown-up says who is washing. */
export function KidPicker() {
  const { data: kids } = useApi<Child[]>("/api/v1/app/children");
  const { refresh } = useLive();
  if (!kids || kids.length === 0) return null;
  const active = kids.find((k) => k.active);
  return (
    <label className="kid-picker">
      <span className="sr-only">Child</span>
      <select value={active?.id ?? ""} onChange={(e) => send("POST", `/api/v1/app/children/${e.target.value}/activate`).then(refresh, refresh)}>
        {kids.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
      </select>
    </label>
  );
}

export function BottomTabs({ path }: { path: string }) {
  const { view } = useMode();
  const current = currentItem(path, view);
  return (
    <nav className="tabs" aria-label="Main">
      {(view === "kid" ? KID_NAV : PARENT_NAV).map(([to, icon, label]) => (
        <Link key={to} to={to} aria-current={current === to ? "page" : undefined}><Icon name={icon} size={22} />{label}</Link>
      ))}
    </nav>
  );
}

export function SideBar({ path }: { path: string }) {
  const { view } = useMode();
  const current = currentItem(path, view);
  const items: readonly Item[] = view === "kid" ? KID_NAV : [...PARENT_NAV, ["/settings", "gear", "Settings"]];
  return (
    <aside className="side">
      <Brand />
      <ViewSwitch />
      <div className="label">{view === "kid" ? "Play" : "Family"}</div>
      <nav className="sidenav" aria-label="Main">
        {items.map(([to, icon, label]) => (
          <Link key={to} to={to} aria-current={current === to ? "page" : undefined}><Icon name={icon} size={19} />{label}</Link>
        ))}
      </nav>
      <div className="spacer" />
      <div className="label">Preview as</div>
      <DeviceSwitch />
    </aside>
  );
}
