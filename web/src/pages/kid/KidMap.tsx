import { useApi, type Adventure, type Stage } from "../../api";
import { WorldMap } from "../../art/WorldMap";
import { Bar, Pending } from "../../components/ui";
import { Icon } from "../../components/icons";
import { go, Link } from "../../router";

export const placePath = (id: Stage["id"]) => `/kid/map/${id}`;
/** The place the next wash lands in. */
export const currentPlace = (a: Adventure): Stage => [...a.stages].reverse().find((s) => s.unlocked) ?? a.stages[0];

export default function KidMap() {
  const { data: a, error, reload } = useApi<Adventure>("/api/v1/app/adventure");
  return (
    <div className="page">
      <h1 className="h1" style={{ marginBottom: 4 }}>Adventure map</h1>
      <p className="muted" style={{ marginBottom: 12 }}>Tap a place to go in. Every wash at the sink is one level.</p>
      {!a ? <Pending error={error} retry={reload} /> : (
        <div className="stack">
          <section className="card map-card">
            <WorldMap data={a} onOpen={(id) => go(placePath(id))} />
            <div className="place-list">
              {a.stages.map((s) => {
                const total = s.last_level - s.unlock_at;
                return (
                  <Link key={s.id} to={placePath(s.id)} className={`place-chip ${s.unlocked ? "" : "shut"}`} data-place={s.id}>
                    <b>{s.name}{!s.unlocked && <Icon name="lock" size={16} />}</b>
                    {s.unlocked ? <Bar value={s.levels_done / total} label={`${s.name} levels`} /> : null}
                    <span>{s.unlocked ? `${s.levels_done} of ${total} levels` : `Opens at ${s.unlock_at} washes`}</span>
                  </Link>
                );
              })}
            </div>
          </section>
          <section className="card stack">
            {a.next ? (
              <>
                <b>{a.next.name} opens in {a.next.washes_left} more {a.next.washes_left === 1 ? "wash" : "washes"}</b>
                <Bar value={a.rewarded_washes / (a.rewarded_washes + a.next.washes_left)} tone="gold" label="Progress to the next place" />
              </>
            ) : <b>Every place on the map is open.</b>}
            <p className="muted">The map moves with real washes at the sink: {a.rewarded_washes} so far. Washes past the daily goal don't count, so there is no need to wash extra.</p>
          </section>
        </div>
      )}
    </div>
  );
}
