import { send, useApi, ZONE_MOVES, ZONE_NAMES, type Child, type Home, type WeekProgress } from "../../api";
import { BayScene } from "../../art/scenes";
import { Creature, germFor } from "../../components/Creature";
import { Bar, Button, EmptyState, Pending, Stars } from "../../components/ui";
import { GERM_NAMES } from "../../germs";
import { useLive, useWashStage } from "../../live";
import { go, Link } from "../../router";

const DOW = ["M", "T", "W", "T", "F", "S", "S"];

export default function KidHome() {
  const { data: h, error, reload } = useApi<Home>("/api/v1/app/home");
  const { data: kids } = useApi<Child[]>("/api/v1/app/children");
  const { data: week } = useApi<WeekProgress>("/api/v1/app/progress?period=week");
  const { refresh } = useLive();
  const { stage } = useWashStage();
  const kid = h?.child;
  const todayIdx = (new Date().getDay() + 6) % 7;
  const w = h?.latest;
  const practise = w && w.stars > 0 && w.missed.length ? w.missed[0] : null;

  return (
    <div className="page">
      <section className="scene">
        <BayScene />
        <h1>Hi {kid?.name ?? "there"}!</h1>
        <p>{h && h.today >= h.goal ? "You hit today's goal. Nice work!" : "Ready to zap some germs?"}</p>
        <Creature id={kid?.buddy ?? "bubbles"} size={132} className="buddy" bob />
      </section>

      {kids && kids.length > 1 && (
        <div className="kidpills" role="radiogroup" aria-label="Who is washing">
          {kids.map((k) => (
            <button key={k.id} type="button" role="radio" aria-checked={!!k.active} className="kidpill" onClick={() => !k.active && send("POST", `/api/v1/app/children/${k.id}/activate`).then(refresh, refresh)}>
              <Creature id={k.buddy} size={30} />{k.name}
            </button>
          ))}
        </div>
      )}

      {stage !== "off" && (
        <Link to="/kid/live" className="banner">
          <Creature id="bubbles" size={40} />
          <span className="grow">{stage === "scrubbing" ? "Washing right now!" : stage === "result" ? "Wash done!" : "The sink station is on"}<small>Watch it live</small></span>
        </Link>
      )}

      {!h ? <div style={{ marginTop: 12 }}><Pending error={error} retry={reload} blocks={2} /></div> : (
        <div className="kid-grid">
          <div className="stack">
            <section className="card">
              <h2 className="h2">Today's washes</h2>
              <div className="bubbles" role="img" aria-label={`${h.today} of ${h.goal} washes today`}>
                {Array.from({ length: h.goal }, (_, i) => <i key={i} className={i < h.today ? "done" : ""} />)}
              </div>
              <p className="muted">{h.today} of {h.goal} done{h.today > h.goal ? `, plus ${h.today - h.goal} extra` : ""}</p>
            </section>
            <div className="tiles">
              <div className="tile butter"><b>{h.points.toLocaleString()}</b><span>points</span></div>
              <div className="tile sky"><b>{h.zaps}</b><span>zaps</span></div>
              <div className="tile blush"><b>{h.streak}</b><span>{h.streak === 1 ? "day in a row" : "days in a row"}</span></div>
            </div>
            {week && (
              <section className="card">
                <h2 className="h2">This week</h2>
                <div className="week" role="img" aria-label={`Washes this week: ${week.per_day.map((n, i) => `${["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][i]} ${n}`).join(", ")}`}>
                  {week.per_day.map((n, i) => <span key={i} className={`${n > 0 ? "hit" : ""} ${i === todayIdx ? "today" : ""}`}><i>{n > 0 ? n : ""}</i>{DOW[i]}</span>)}
                </div>
              </section>
            )}
          </div>

          <div className="stack">
            {w ? (
              <section className="card">
                <h2 className="h2">Your last wash</h2>
                <div className="last">
                  <Stars n={w.stars} />
                  <Creature id={practise ? germFor(practise) : "bubbles"} size={84} className="who" />
                  <span className="score num">Score {w.points}</span>
                  <span className="muted">{w.label}, {w.time}</span>
                </div>
                {practise && <p style={{ margin: "10px 0 12px" }}><b>Next time, get the {ZONE_NAMES[practise].toLowerCase()}:</b> {ZONE_MOVES[practise]}.</p>}
                {!practise && w.stars > 0 && <p style={{ margin: "10px 0 12px" }}><b>Every spot got scrubbed.</b> That is a perfect wash!</p>}
                <Button wide tone="quiet" onClick={() => go(`/kid/wash/${encodeURIComponent(w.wash_id)}`)}>See my hands</Button>
              </section>
            ) : (
              <EmptyState title="No washes yet" creature="bubbles">Wash your hands at the sink station. Your stars will show up here.</EmptyState>
            )}
            <Link to="/kid/germs" className="card boss" aria-label={`Boss of the week: ${GERM_NAMES[h.boss.germ]}, ${h.boss.done} of ${h.boss.target}`}>
              <Creature id={h.boss.germ} size={64} />
              <span className="grow">
                <span className="line"><span>Boss: {GERM_NAMES[h.boss.germ]}</span><span className="num muted">{h.boss.done}/{h.boss.target}</span></span>
                <Bar value={h.boss.done / h.boss.target} tone="coral" label="Boss progress" />
                <span className="muted">Scrub your {ZONE_NAMES[h.boss.zone].toLowerCase()} to beat it</span>
              </span>
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
