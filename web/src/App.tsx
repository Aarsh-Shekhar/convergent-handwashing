import { useEffect, useState } from "react";
import { api, type Settings, type WashView } from "./api";
import { Germ, germFor } from "./components/germs";
import { Empty, Icon, PageHead } from "./components/ui";
import { LiveProvider, useLive } from "./live";
import Germdex from "./pages/Germdex";
import Home from "./pages/Home";
import Live from "./pages/Live";
import Progress from "./pages/Progress";
import Rewards from "./pages/Rewards";
import WashDetail from "./pages/WashDetail";
import Washes from "./pages/Washes";
import { Link, usePath } from "./router";

const TABS = [
  ["/", "home", "Home"], ["/progress", "chart", "Progress"], ["/rewards", "gift", "Rewards"],
  ["/germdex", "germ", "Germ-dex"], ["/settings", "gear", "Settings"],
] as const;

function Soon({ title }: { title: string }) {
  return (
    <div className="page fade-in">
      <PageHead title={title} />
      <Empty title="Coming soon">This screen is being built next.</Empty>
    </div>
  );
}

function Screen({ path }: { path: string }) {
  const wash = path.match(/^\/washes\/(.+)$/);
  if (wash) return <WashDetail id={decodeURIComponent(wash[1])} />;
  switch (path) {
    case "/washes": return <Washes />;
    case "/live": return <Live />;
    case "/progress": return <Progress />;
    case "/rewards": return <Rewards />;
    case "/germdex": return <Germdex />;
    case "/settings": return <Soon title="Settings" />;
    default: return <Home />;
  }
}

/** A short note when the station saves a wash, on whatever screen is open. */
function WashToast({ path }: { path: string }) {
  const { saved, savedCount } = useLive();
  const [shown, setShown] = useState<WashView | null>(null);
  useEffect(() => {
    if (!saved) return;
    setShown(saved);
    const t = window.setTimeout(() => setShown(null), 4500);
    return () => clearTimeout(t);
  }, [saved, savedCount]);
  if (!shown || path === "/live") return null; // the live page shows the result itself
  return (
    <Link to={`/washes/${encodeURIComponent(shown.wash_id)}`} className="toast" role="status" style={{ textDecoration: "none" }}>
      <Germ id={shown.missed.length ? germFor(shown.missed[0]) : "scrubby"} size={36} />
      <span><b>New wash saved!</b><br />{shown.points} pts{shown.zaps ? ` · +${shown.zaps} zaps` : shown.capped ? " · daily zaps done" : ""} · {shown.missed.length ? `${shown.missed.length} spots to practice` : "perfect scrub"}</span>
    </Link>
  );
}

/** Days are counted in the family's timezone: keep the saved one in step with this browser. */
function useTimezoneSync() {
  useEffect(() => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    api<Settings>("/api/v1/app/settings").then((s) => {
      if (tz && s.timezone !== tz) api("/api/v1/app/settings", { method: "PUT", body: JSON.stringify({ timezone: tz }) }).catch(() => {});
    }, () => {});
  }, []);
}

function Shell() {
  const path = usePath();
  useTimezoneSync();
  const tab = path.startsWith("/washes") || path === "/live" ? "/" : path;
  return (
    <div className="app">
      <Screen path={path} />
      <WashToast path={path} />
      <nav className="tabs" aria-label="Main">
        {TABS.map(([to, icon, label]) => (
          <Link key={to} to={to} aria-current={tab === to ? "page" : undefined}><Icon name={icon} />{label}</Link>
        ))}
      </nav>
    </div>
  );
}

export default function App() {
  return <LiveProvider><Shell /></LiveProvider>;
}
