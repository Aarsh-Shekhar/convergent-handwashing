import { useEffect, useState } from "react";
import { api, send, type Settings as FamilySettings, type WashView } from "./api";
import { BottomNav } from "./components/BottomNav";
import { Creature, germFor } from "./components/Creature";
import { EmptyState, GameButton } from "./components/ui";
import { washPath } from "./components/WashSummary";
import { LiveProvider, useLive } from "./live";
import GermDex from "./pages/GermDex";
import History from "./pages/History";
import Home from "./pages/Home";
import Onboarding from "./pages/Onboarding";
import Progress from "./pages/Progress";
import Rewards from "./pages/Rewards";
import Routines from "./pages/Routines";
import Settings from "./pages/Settings";
import WashDetail from "./pages/WashDetail";
import { ParentProvider } from "./parent";
import { go, Link, usePath } from "./router";

function Screen({ path }: { path: string }) {
  const wash = path.match(/^\/history\/(.+)$/);
  if (wash) return <WashDetail id={decodeURIComponent(wash[1])} />;
  switch (path) {
    case "/history": return <History />;
    case "/progress": return <Progress />;
    case "/rewards": return <Rewards />;
    case "/germ-dex": return <GermDex />;
    case "/routines": return <Routines />;
    case "/settings": return <Settings />;
    case "/onboarding": return <Onboarding />;
    case "/": return <Home />;
    default: return <NotFound />;
  }
}

function NotFound() {
  return <div className="page"><EmptyState title="Nothing here" creature="smudge" action={<GameButton onClick={() => go("/")}>Back to Home</GameButton>}>That page does not exist.</EmptyState></div>;
}

/** A short note when the station saves a wash, on whatever screen is open. */
function WashToast() {
  const { saved } = useLive();
  const [shown, setShown] = useState<WashView | null>(null);
  useEffect(() => {
    if (!saved) return;
    setShown(saved);
    const t = window.setTimeout(() => setShown(null), 5000);
    return () => clearTimeout(t);
  }, [saved]);
  if (!shown) return null;
  const earned = shown.reward_points ? `+${shown.reward_points} pts` : `${shown.points} pts`;
  return (
    <Link to={washPath(shown)} className="toast" role="status">
      <Creature id={shown.missed.length && shown.stars ? germFor(shown.missed[0]) : "bubbles"} size={46} />
      <span><b>New wash synced</b>{earned} · {shown.missed.length ? `${shown.missed.length} ${shown.missed.length === 1 ? "spot" : "spots"} to practice` : "perfect scrub"}</span>
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

function Shell() {
  const path = usePath();
  useFirstLoad();
  const bare = path.startsWith("/onboarding");
  useEffect(() => { if (path === "/home") go("/", true); }, [path]);
  return (
    <div className={`world ${bare ? "bare" : ""}`}>
      <main><Screen path={path} /></main>
      {!bare && <WashToast />}
      {!bare && <BottomNav path={path} />}
    </div>
  );
}

export default function App() {
  return <LiveProvider><ParentProvider><Shell /></ParentProvider></LiveProvider>;
}
