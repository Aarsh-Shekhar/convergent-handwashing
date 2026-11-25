// Germ-dex (kid-facing): the boss of the week and every germ, caught or not.
import { useApi, type Germdex as Data } from "../api";
import { Germ } from "../components/germs";
import { Loading, PageHead } from "../components/ui";
import { livesOn } from "./Rewards";

export default function Germdex() {
  const { data: d, error } = useApi<Data>("/api/v1/app/germdex");
  if (!d) return <div className="page"><PageHead title="Germ-dex" /><Loading error={error} /></div>;
  const boss = d.germs.find((g) => g.id === d.boss.germ)!;
  const locked = Math.max(0, d.slots - d.germs.length);
  return (
    <div className="page fade-in">
      <PageHead title="Germ-dex" right={<span className="faint" style={{ width: 36, textAlign: "right" }}>{d.owned}/{d.slots}</span>} />

      <div className={`card boss ${d.boss.won ? "won" : ""}`}>
        <Germ id={boss.id} size={74} bob={!d.boss.won} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="label-caps" style={{ margin: 0 }}>Boss of the week</div>
          <div className="boss-name">{boss.name}</div>
          <div className="faint">
            {d.boss.won ? `Beaten! ${boss.name} joined the team.` : `${livesOn(d.boss.zone)}. Scrub there ${d.boss.target} times this week to win!`}
          </div>
          <div className="boss-bar"><div style={{ width: `${(d.boss.done / d.boss.target) * 100}%` }} /></div>
          <div className="faint">{d.boss.done} / {d.boss.target}</div>
        </div>
      </div>

      <div className="dex">
        {d.germs.map((g) => (
          <div key={g.id} className={`card dex-cell ${g.owned ? "" : "unowned"}`}>
            <Germ id={g.id} size={64} dim={!g.owned} />
            <b>{g.name}</b>
            <span className="faint">{g.owned ? `zapped ×${g.zapped ?? 0}` : g.rarity === "boss" ? "Beat it to catch it" : `${g.price} zaps to catch`}</span>
          </div>
        ))}
        {Array.from({ length: locked }, (_, i) => (
          <div key={`lock${i}`} className="card dex-cell unowned">
            <div className="mystery">?</div>
            <b>???</b>
            <span className="faint">Coming soon</span>
          </div>
        ))}
      </div>
      <p className="faint" style={{ textAlign: "center", margin: "12px 8px 0" }}>"Zapped" counts the washes where that germ's spot was scrubbed long enough.</p>
    </div>
  );
}
