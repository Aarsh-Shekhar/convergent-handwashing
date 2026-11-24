// One place on the map. Its path has one level for every rewarded wash: tap a finished level to see that wash.
import { useApi, ZONE_MOVES, ZONE_NAMES, type Adventure, type GermDex, type Level, type Stage } from "../../api";
import bubbles from "../../assets/scrubby.png";
import { Creature } from "../../components/Creature";
import { Icon } from "../../components/icons";
import { Button, EmptyState, Pending } from "../../components/ui";
import { GERM_NAMES, HIDES } from "../../germs";
import { go, Link } from "../../router";
import { placePath } from "./KidMap";

const COLS = 5, DX = 64, DY = 74, X0 = 40, Y0 = 44, W = X0 * 2 + DX * (COLS - 1);
/** Levels snake left to right, then right to left, like a board game. */
const spot = (i: number): [number, number] => {
  const row = Math.floor(i / COLS), col = i % COLS;
  return [X0 + (row % 2 ? COLS - 1 - col : col) * DX, Y0 + row * DY];
};
const route = (n: number) => Array.from({ length: n }, (_, i) => spot(i).join(",")).join(" ");

function Chest({ open }: { open: boolean }) {
  return (
    <g className={open ? "chest open" : "chest"} transform="translate(-9 -34)">
      <rect className="box" x="0" y="7" width="18" height="11" rx="2" /><path className="lid" d={open ? "M0 6 2-1h14l2 7z" : "M0 7a9 6 0 0 1 18 0z"} /><rect className="latch" x="7.5" y="6" width="3" height="5" rx="1" />
    </g>
  );
}

function Path({ stage, levels, done }: { stage: Stage; levels: Level[]; done: number }) {
  const total = stage.last_level - stage.unlock_at;
  const lit = Math.max(0, Math.min(done - stage.unlock_at, total));
  const rows = Math.ceil(total / COLS);
  return (
    <svg className="levelpath" viewBox={`0 0 ${W} ${Y0 + (rows - 1) * DY + 40}`} role="list" aria-label={`${stage.name}: ${lit} of ${total} levels done`}>
      <polyline className="rail" points={route(total)} />
      {lit > 0 && <polyline className="rail lit" points={route(Math.min(lit + (stage.unlocked && lit < total ? 1 : 0), total))} />}
      {Array.from({ length: total }, (_, i) => {
        const n = stage.unlock_at + i + 1;
        const [x, y] = spot(i);
        const lv = levels[n - 1];
        const next = stage.unlocked && n === done + 1;
        const chest = n % 5 === 0;
        const body = (
          <>
            <circle className="base" cx={x} cy={y} r="22.5" />
            {lv ? (
              <>
                <text x={x} y={y + 1}>{lv.stars}</text>
                <path className="mini" transform={`translate(${x - 5} ${y + 4})`} d="m5 0 1.5 3.1 3.4.5-2.5 2.4.6 3.4L5 7.8 2 9.4l.6-3.4L.1 3.6l3.4-.5z" />
              </>
            ) : <text x={x} y={y + 5}>{n}</text>}
            {chest && <g transform={`translate(${x} ${y})`}><Chest open={!!lv} /></g>}
          </>
        );
        if (lv) {
          return (
            <a key={n} role="listitem" className={`node done ${lv.perfect ? "perfect" : ""}`} href={`/kid/wash/${encodeURIComponent(lv.wash_id)}`}
              aria-label={`Level ${n}: ${lv.stars} of 5 stars${lv.perfect ? ", every spot scrubbed" : ""}${chest ? ", chest opened" : ""}. See this wash.`}
              onClick={(e) => { e.preventDefault(); go(`/kid/wash/${encodeURIComponent(lv.wash_id)}`); }}>{body}</a>
          );
        }
        return (
          <g key={n} role="listitem" className={next ? "node next" : "node"} aria-label={next ? `Level ${n}: your next wash lands here` : `Level ${n}: not reached yet${chest ? ", has a chest" : ""}`}>
            {body}
            {next && <image href={bubbles} x={x - 20} y={y - 52} width="40" height="36" preserveAspectRatio="xMidYMax meet" />}
          </g>
        );
      })}
    </svg>
  );
}

export default function KidPlace({ id }: { id: string }) {
  const { data: a, error, reload } = useApi<Adventure>("/api/v1/app/adventure");
  const { data: dex } = useApi<GermDex>("/api/v1/app/germdex");
  if (!a) return <div className="page"><Pending error={error} retry={reload} /></div>;
  const at = a.stages.findIndex((s) => s.id === id);
  const stage = a.stages[at];
  if (!stage) return <div className="page"><EmptyState title="No such place" creature="smudge" action={<Button onClick={() => go("/kid/map")}>Back to the map</Button>}>That place is not on the map.</EmptyState></div>;
  const total = stage.last_level - stage.unlock_at;
  const left = stage.unlock_at - a.rewarded_washes;
  const zones = [...new Set(stage.germs.map((g) => dex?.germs.find((d) => d.id === g)?.zone).filter((z) => !!z))] as (keyof typeof ZONE_NAMES)[];
  return (
    <div className="page" data-place={stage.id}>
      <div className="place-nav">
        <Link to="/kid/map" className="back"><Icon name="back" size={20} />Map</Link>
        <span style={{ display: "inline-flex", gap: 6 }}>
          {at > 0 && <Button small tone="quiet" onClick={() => go(placePath(a.stages[at - 1].id))}>{a.stages[at - 1].name}</Button>}
          {at < a.stages.length - 1 && <Button small tone="quiet" onClick={() => go(placePath(a.stages[at + 1].id))}>{a.stages[at + 1].name}</Button>}
        </span>
      </div>
      <header className="place-head">
        <div>
          <h1>{stage.name}</h1>
          <p>{stage.unlocked ? `${stage.levels_done} of ${total} levels done` : `Opens in ${left} more ${left === 1 ? "wash" : "washes"}`}</p>
        </div>
        <div className="crew">{stage.germs.map((g) => <Creature key={g} id={g} size={64} locked={!stage.unlocked} />)}</div>
      </header>

      <div className="stack" style={{ marginTop: 12 }}>
        {!stage.unlocked && <p className="locked-note"><Icon name="lock" size={22} />Keep washing at the sink. This place opens at {stage.unlock_at} washes, and you have {a.rewarded_washes}.</p>}
        <section className="card path-card">
          <Path stage={stage} levels={a.levels} done={a.rewarded_washes} />
          <p className="path-key" aria-hidden="true">
            <span><i />Washed, with its stars</span><span><i className="perfect" />Every spot scrubbed</span><span><i className="todo" />Still to come</span>
          </p>
        </section>
        <section className="card">
          <h2 className="h2">Who lives here</h2>
          <div className="residents">
            {stage.germs.map((g) => {
              const d = dex?.germs.find((x) => x.id === g);
              return (
                <Link key={g} to="/kid/germs" className="resident">
                  <Creature id={g} size={72} locked={!!d && !d.owned} />
                  <b>{GERM_NAMES[g]}</b>
                  <small>{d ? (d.owned ? `Hides ${HIDES[d.zone]}` : "Not in your collection yet") : ""}</small>
                </Link>
              );
            })}
          </div>
        </section>
        {zones.length > 0 && (
          <section className="card">
            <h2 className="h2">Moves to practise here</h2>
            <ul className="checklist">{zones.map((z) => <li key={z}>{ZONE_NAMES[z]}: {ZONE_MOVES[z]}</li>)}</ul>
          </section>
        )}
      </div>
    </div>
  );
}
