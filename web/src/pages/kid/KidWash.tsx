// One wash, for the kid: stars, the hands, and the one thing to try next time.
import { useApi, ZONE_MOVES, ZONE_NAMES, type WashDetail } from "../../api";
import { Creature, germFor } from "../../components/Creature";
import { WashHands } from "../../components/HandFigure";
import { Button, EmptyState, Pending, Stars } from "../../components/ui";
import { go } from "../../router";
import { weakest } from "../parent/WashDetail";

export default function KidWash({ id }: { id: string }) {
  const { data: w, error, reload } = useApi<WashDetail>(`/api/v1/app/washes/${encodeURIComponent(id)}`);
  if (!w) {
    return <div className="page">{error?.status === 404
      ? <EmptyState title="Wash not found" creature="smudge" action={<Button onClick={() => go("/kid")}>Back home</Button>}>This wash is not in your list.</EmptyState>
      : <Pending error={error} retry={reload} blocks={2} />}</div>;
  }
  const recognized = w.stars > 0;
  const weak = recognized ? weakest(w) : null;
  return (
    <div className="page">
      <button type="button" className="back" onClick={() => go("/kid")}>Back home</button>
      <div className="kid-grid" style={{ marginTop: 0 }}>
        <section className="card result">
          <Creature id={!recognized ? "smudge" : weak ? germFor(weak) : "bubbles"} size={104} />
          <h1>{!recognized ? "No scrubbing seen" : !w.missed.length ? "Perfect scrub!" : w.finished ? "Great scrub!" : "Good start!"}</h1>
          <Stars n={w.stars} size={30} />
          <div className="big num">{w.points}<small>points</small></div>
          <div className="tags" style={{ justifyContent: "center" }}>
            {w.reward_points > 0 && <span className="tag gold">+{w.reward_points} reward points</span>}
            {w.zaps > 0 && <span className="tag gold">+{w.zaps} zaps</span>}
            {w.capped && <span className="tag">Daily goal done. More tomorrow</span>}
            {w.source === "demo" && <span className="tag demo">Demo data</span>}
          </div>
          {w.high_fived && <p className="banner" style={{ marginTop: 6 }}>Your grown-up gave you a high-five!</p>}
        </section>
        <div className="stack">
          <section className="card">
            <h2 className="h2">Your hands</h2>
            <WashHands coverage={w.coverage} recognized={recognized} />
          </section>
          {weak && (
            <section className="card boss">
              <Creature id={germFor(weak)} size={60} />
              <p><b>Next time, get the {ZONE_NAMES[weak].toLowerCase()}.</b> {ZONE_MOVES[weak][0].toUpperCase() + ZONE_MOVES[weak].slice(1)}, and count to three.</p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
