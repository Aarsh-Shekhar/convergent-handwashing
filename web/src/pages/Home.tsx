import { useState } from "react";
import { send, useApi, ZONE_MOVES, type Child, type Home as HomeData } from "../api";
import { BayScene } from "../art/scenes";
import { Creature, germFor } from "../components/Creature";
import { Icon, type IconName } from "../components/icons";
import { Bar, EmptyState, HudCounter, IconButton, IllustratedPanel, Pending, ProgressRing, SyncIndicator } from "../components/ui";
import { LatestWash } from "../components/WashSummary";
import { useLive } from "../live";
import { go, Link } from "../router";
import { KidSheet } from "./KidSheet";
import "./Home.css";

const GERM_NAMES: Record<string, string> = { king_prickle: "King Prickle", king_sneeze: "King Sneeze", king_gunk: "King Gunk" };
const SHORTCUTS: readonly (readonly [to: string, icon: IconName, label: string, tone: string])[] = [
  ["/history", "list", "History", "blue"], ["/progress?view=map", "map", "Map", "teal"],
  ["/routines", "clock", "Routines", "violet"], ["/germ-dex", "germ", "Germ-dex", "rose"],
];

/** Pick whose washes the app shows. The station cannot tell children apart, so the parent says who is washing. */
function KidSwitcher({ kids, onAdd }: { kids: Child[]; onAdd: () => void }) {
  const { refresh } = useLive();
  const pick = (id: number) => send("POST", `/api/v1/app/children/${id}/activate`).then(refresh, refresh);
  return (
    <div className="kids" role="radiogroup" aria-label="Whose washes to show">
      {kids.map((k) => (
        <button key={k.id} type="button" role="radio" aria-checked={!!k.active} className="kid" onClick={() => !k.active && pick(k.id)}>
          <Creature id={k.buddy} size={30} />{k.name}
        </button>
      ))}
      <button type="button" className="kid add" onClick={onAdd} aria-label="Add a child"><Icon name="plus" size={20} /></button>
    </div>
  );
}

export default function Home() {
  const { data: h, error, reload } = useApi<HomeData>("/api/v1/app/home");
  const { data: kids } = useApi<Child[]>("/api/v1/app/children");
  const [adding, setAdding] = useState(false);
  const date = new Date().toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
  const kid = h?.child?.name;

  return (
    <div className="page home">
      <div className="home-top"><span className="faint">{date}</span><SyncIndicator /></div>
      <h1 className="title">Hi {h?.parent_name || "there"}!</h1>
      {kids && <KidSwitcher kids={kids} onAdd={() => setAdding(true)} />}

      {!h ? <Pending error={error} retry={reload} blocks={3} /> : (
        <>
          <div className="hud" aria-label={`${kid ?? "Your child"}'s totals`}>
            <HudCounter kind="points" value={h.points} label="reward points" />
            <HudCounter kind="zaps" value={h.zaps} label="zaps" />
            <HudCounter kind="streak" value={h.streak} label={h.streak === 1 ? "day in a row" : "days in a row"} />
          </div>

          <IllustratedPanel className="day" scene={<BayScene />}>
            <div className="day-head">
              <h2>{kid ? `${kid}'s day` : "Today"}</h2>
              <IconButton icon="next" label="Open progress" onClick={() => go("/progress")} />
            </div>
            <div className="goal-pill">
              <ProgressRing value={h.today / h.goal} size={46} stroke={7} color="var(--gold)" />
              <div><b className="num">{h.today}<span>/{h.goal}</span></b><small>washes today</small></div>
            </div>
            <dl className="day-stats">
              <div><dt>Avg score</dt><dd className="num">{h.avg_score ?? "–"}</dd></div>
              <div><dt>Clean washes</dt><dd className="num">{h.clean_washes}</dd></div>
            </dl>
            <Creature id={h.child?.buddy ?? "bubbles"} size={150} className="hero" bob />
          </IllustratedPanel>

          <nav className="shortcuts" aria-label="Shortcuts">
            {SHORTCUTS.map(([to, icon, label, tone]) => (
              <Link key={to} to={to} className="shortcut"><span className={`orb ${tone}`}><Icon name={icon} size={30} /></span>{label}</Link>
            ))}
          </nav>

          <h2 className="section">Latest wash {h.latest && <Link to="/history">See all</Link>}</h2>
          {h.latest ? <LatestWash w={h.latest} /> : (
            <EmptyState title="No washes yet">
              Start the station and wash your hands. Each wash lands here the moment it ends.
            </EmptyState>
          )}

          {h.tip && (
            <IllustratedPanel className="tip">
              <Creature id={germFor(h.tip.zone)} size={58} />
              <p>
                <b>Coach tip</b>
                {kid ?? "Your child"} missed {h.tip.name.toLowerCase()} in {Math.round(h.tip.missed * 100)}% of this week's washes.
                Say "{h.tip.name.toLowerCase()} next" and show how: {ZONE_MOVES[h.tip.zone]}.
              </p>
            </IllustratedPanel>
          )}

          <Link to="/germ-dex" className="panel deep boss-strip" aria-label={`Boss of the week: ${GERM_NAMES[h.boss.germ]}, ${h.boss.done} of ${h.boss.target}`}>
            <Creature id={h.boss.germ} size={56} />
            <div className="grow">
              <div className="caps-line">Boss of the week</div>
              <div className="boss-name">{GERM_NAMES[h.boss.germ]} <span className="num">{h.boss.done}/{h.boss.target}</span></div>
              <Bar value={h.boss.done / h.boss.target} label="Boss progress" />
            </div>
          </Link>
        </>
      )}
      {adding && <KidSheet onClose={() => setAdding(false)} />}
    </div>
  );
}
