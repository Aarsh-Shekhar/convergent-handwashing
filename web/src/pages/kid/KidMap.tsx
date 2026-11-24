import { useApi, type Adventure } from "../../api";
import { WorldMap } from "../../art/WorldMap";
import { Bar, Pending } from "../../components/ui";

export default function KidMap() {
  const { data: a, error, reload } = useApi<Adventure>("/api/v1/app/adventure");
  return (
    <div className="page">
      <h1 className="h1" style={{ marginBottom: 12 }}>Adventure map</h1>
      {!a ? <Pending error={error} retry={reload} /> : (
        <div className="stack">
          <section className="card map-card">
            <WorldMap data={a} />
            <ol className="places">
              {a.stages.map((s) => <li key={s.id} className={s.unlocked ? "open" : ""}><b>{s.name}</b><span>{s.unlocked ? "Open" : `Opens at ${s.unlock_at} washes`}</span></li>)}
            </ol>
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
