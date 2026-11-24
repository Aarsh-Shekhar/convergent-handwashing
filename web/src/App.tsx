import { useEffect, useState, type ReactNode } from "react";
import { api, send, type Settings as FamilySettings, type WashView } from "./api";
import { Creature, germFor } from "./components/Creature";
import { Icon } from "./components/icons";
import { BottomTabs, Brand, DeviceSwitch, SideBar, ViewSwitch } from "./components/Nav";
import { Button, EmptyState } from "./components/ui";
import { LiveProvider, useLive } from "./live";
import { FRAMED, ModeProvider, useMode } from "./mode";
import { ParentProvider } from "./parent";
import { go, Link, usePath } from "./router";
import KidGerms from "./pages/kid/KidGerms";
import KidHome from "./pages/kid/KidHome";
import KidLive from "./pages/kid/KidLive";
import KidMap from "./pages/kid/KidMap";
import KidPlace from "./pages/kid/KidPlace";
import KidRewards from "./pages/kid/KidRewards";
import KidWash from "./pages/kid/KidWash";
import Onboarding from "./pages/Onboarding";
import Extensions from "./pages/parent/Extensions";
import Insights from "./pages/parent/Insights";
import Overview from "./pages/parent/Overview";
import Rewards from "./pages/parent/Rewards";
import Settings from "./pages/parent/Settings";
import Station from "./pages/parent/Station";
import WashDetail from "./pages/parent/WashDetail";
import Washes from "./pages/parent/Washes";

function Screen({ path }: { path: string }): ReactNode {
  const wash = path.match(/^\/washes\/(.+)$/);
  if (wash) return <WashDetail id={decodeURIComponent(wash[1])} />;
  const kidWash = path.match(/^\/kid\/wash\/(.+)$/);
  if (kidWash) return <KidWash id={decodeURIComponent(kidWash[1])} />;
  const place = path.match(/^\/kid\/map\/([a-z_]+)$/);
  if (place) return <KidPlace id={place[1]} />;
  switch (path) {
    case "/": return <Overview />;
    case "/washes": return <Washes />;
    case "/insights": return <Insights />;
    case "/rewards": return <Rewards />;
    case "/station": return <Station />;
    case "/settings": return <Settings />;
    case "/extensions": return <Extensions />;
    case "/kid": return <KidHome />;
    case "/kid/live": return <KidLive />;
    case "/kid/map": return <KidMap />;
    case "/kid/germs": return <KidGerms />;
    case "/kid/rewards": return <KidRewards />;
    case "/onboarding": return <Onboarding />;
    default:
      return <div className="page"><EmptyState title="Nothing here" creature="smudge" action={<Button onClick={() => go("/")}>Back to the start</Button>}>That page does not exist.</EmptyState></div>;
  }
}

/** A short note when the station saves a wash, on whatever screen is open. */
function WashToast() {
  const { saved, savedAt } = useLive();
  const { view } = useMode();
  const [shown, setShown] = useState<WashView | null>(null);
  useEffect(() => {
    if (!saved) return;
    setShown(saved);
    const t = window.setTimeout(() => setShown(null), 6000);
    return () => clearTimeout(t);
  }, [saved, savedAt]);
  if (!shown) return null;
  const missed = shown.missed.length && shown.stars ? `${shown.missed.length} ${shown.missed.length === 1 ? "spot" : "spots"} to practice` : "every spot scrubbed";
  return (
    <Link to={view === "kid" ? `/kid/wash/${encodeURIComponent(shown.wash_id)}` : `/washes/${encodeURIComponent(shown.wash_id)}`} className="toast" role="status">
      {view === "kid" ? <Creature id={shown.missed.length && shown.stars ? germFor(shown.missed[0]) : "bubbles"} size={44} /> : <span className="glyph"><Icon name="drop" size={18} /></span>}
      <span><b>New wash from the sink</b>Score {shown.points}, {missed}</span>
    </Link>
  );
}

/**
 * On start: keep the family's timezone in step with this browser (days are counted in it), and send a family
 * that has not been set up yet to the first-run tour.
 */
function useFirstLoad() {
  useEffect(() => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    api<FamilySettings>("/api/v1/app/settings").then((s) => {
      if (tz && s.timezone !== tz) send("PUT", "/api/v1/app/settings", { timezone: tz }).catch(() => {});
      if (!s.onboarded && window.location.pathname === "/") go("/onboarding", true);
    }, () => {});
  }, []);
}

/** The phone layout inside a phone outline, for looking at it on a laptop. It is this same app in an iframe. */
function PhonePreview({ path }: { path: string }) {
  const [start] = useState(path); // the iframe keeps its own history after the first load
  useEffect(() => {
    const onMsg = (e: MessageEvent) => {
      if (e.origin === window.location.origin && typeof e.data?.scrubblePath === "string") history.replaceState({}, "", e.data.scrubblePath);
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);
  return (
    <div className="preview">
      <div className="preview-bar"><Brand plain /><p>Phone preview. This is the same app a phone would show.</p><DeviceSwitch /></div>
      <div className="phone"><iframe title="Scrubble on a phone" src={`${start}?frame=1`} /></div>
    </div>
  );
}

function Shell() {
  const path = usePath();
  const { view, layout, canPickDevice, device } = useMode();
  useFirstLoad();
  // inside the phone outline: tell the outer page where we are, so a reload comes back to the same screen
  useEffect(() => { if (FRAMED && window.parent !== window) window.parent.postMessage({ scrubblePath: path }, window.location.origin); }, [path]);
  useEffect(() => { window.scrollTo(0, 0); }, [path]);

  if (canPickDevice && device === "phone") return <PhonePreview path={path} />;
  const bare = path.startsWith("/onboarding");
  if (bare) return <div className="app bare" data-view="kid" data-layout={layout}><main><Screen path={path} /></main></div>;
  return (
    <div className="app" data-view={view} data-layout={layout}>
      {layout === "desktop" ? <SideBar path={path} /> : (
        <header className="strip">
          <Brand />
          <span style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
            <ViewSwitch />
            {view === "parent" && <Link to="/extensions" className="icon-btn" aria-label="Extensions" aria-current={path === "/extensions" ? "page" : undefined}><Icon name="grid" size={22} /></Link>}
            {view === "parent" && <Link to="/settings" className="icon-btn" aria-label="Settings" aria-current={path === "/settings" ? "page" : undefined}><Icon name="gear" size={22} /></Link>}
          </span>
        </header>
      )}
      <main><Screen path={path} /></main>
      <WashToast />
      {layout === "phone" && <BottomTabs path={path} />}
    </div>
  );
}

export default function App() {
  return <LiveProvider><ModeProvider><ParentProvider><Shell /></ParentProvider></ModeProvider></LiveProvider>;
}
