// Live wash: what the station sees right now, from the wash software's live feed.
// Built on Andrew's Live page. Stages: off -> ready (no hands) -> scrubbing -> result (a wash was just saved).
import { useApi, ZONE_NAMES, type Child, type Zone } from "../../api";
import { Creature, germFor } from "../../components/Creature";
import { Icon } from "../../components/icons";
import { Button, Ring, Stars } from "../../components/ui";
import { useWashStage } from "../../live";
import { go } from "../../router";

const STEPS: [technique: string, label: string, zone: Zone][] = [
  ["palm_to_palm", "Palms", "palms"], ["back_of_hand", "Backs of hands", "backs"], ["interlaced_fingers", "Between fingers", "between_fingers"],
  ["backs_of_fingers", "Backs of fingers", "backs"], ["thumb_rubbing", "Thumbs", "thumbs"], ["fingertip_rubbing", "Fingertips", "nails"], ["wrist_rubbing", "Wrists", "wrists"],
];
const NAME = Object.fromEntries(STEPS.map(([t, n]) => [t, n]));

export default function KidLive() {
  const { stage, live, saved, now } = useWashStage();
  const { data: kid } = useApi<Child | null>("/api/v1/app/child");
  const score = live?.score;
  const goal = score?.total_min_s ?? 20;

  return (
    <div className="page">
      <h1 className="h1" style={{ marginBottom: 12 }}>Live wash</h1>
      {stage === "result" && saved ? (
        <section className="card result" key={saved.wash_id}>
          <Creature id={saved.missed.length && saved.stars ? germFor(saved.missed[0]) : "bubbles"} size={110} />
          <h1>{saved.stars === 0 ? "No scrubbing seen" : saved.missed.length ? "Great scrub!" : "Perfect scrub!"}</h1>
          <Stars n={saved.stars} size={30} />
          <div className="big num">{saved.points}<small>points</small></div>
          <p className="lede">
            {saved.stars === 0 ? "Try again with both hands in the light." : saved.missed.length
              ? <>Almost! The <b>{saved.missed.map((z) => ZONE_NAMES[z].toLowerCase()).join(", ")}</b> still had germs. Get them next time.</>
              : "Every part of the hands got scrubbed."}
          </p>
          <div className="tags" style={{ justifyContent: "center" }}>
            {saved.zaps > 0 && <span className="tag gold">+{saved.zaps} zaps</span>}
            {saved.capped && <span className="tag">Daily goal done. More points tomorrow</span>}
            <span className="tag">{Math.round(saved.seconds_total)} seconds</span>
          </div>
          <Button onClick={() => go(`/kid/wash/${encodeURIComponent(saved.wash_id)}`)}>See my hands</Button>
        </section>
      ) : stage === "off" ? (
        <section className="card result">
          <Creature id="bubbles" size={120} bob />
          <h1>Waiting for the station</h1>
          <p className="lede">Start the Scrubble station at the sink. This screen wakes up as soon as it sees hands.</p>
        </section>
      ) : stage === "ready" ? (
        <section className="card result">
          <Creature id="bubbles" size={120} bob />
          <h1>Hi {kid?.name ?? "there"}!</h1>
          <p className="lede">Wet your hands and add soap to start.</p>
          <div style={{ display: "flex", gap: 10 }}>{["prickle", "sneezel", "gunky", "smudge"].map((g) => <Creature key={g} id={g} size={44} />)}</div>
        </section>
      ) : (
        <div className="stack">
          <section className="card live-now">
            <Ring value={(score?.total_s ?? 0) / goal} size={108} stroke={12} color="var(--blue)" label={`${Math.round(score?.total_s ?? 0)} of ${goal} seconds`}>
              <div><b className="num" style={{ font: "900 24px/1 var(--font)" }}>{Math.round(score?.total_s ?? 0)}s</b><div className="muted">of {goal}s</div></div>
            </Ring>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="muted">{now ? "Scrubbing now" : live?.hands ? "Hands in view" : "Hands out of view"}</div>
              <div className="what">{now ? `${NAME[now] ?? now}!` : "Keep scrubbing"}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}><Stars n={score?.stars ?? 0} /><span className="muted num">{score?.points ?? 0} points</span></div>
            </div>
          </section>
          <section className="card">
            <h2 className="h2">Steps <span className="muted">{score?.steps_done ?? 0} of 7 done</span></h2>
            <div className="wash-steps">
              {STEPS.map(([t, label, zone]) => {
                const s = score?.steps.find((x) => x.technique === t);
                const secs = s?.seconds ?? 0;
                return (
                  <div key={t} className={`step ${now === t ? "now" : ""}`}>
                    <Ring value={secs / (score?.step_min_s ?? 3)} size={58} stroke={6} color={s?.done ? "var(--mint)" : "var(--blue)"}>
                      {s?.done ? <span style={{ color: "var(--good)" }}><Icon name="check" size={22} /></span> : <Creature id={germFor(zone)} size={30} />}
                    </Ring>
                    <span>{label}</span><span className="muted num">{secs.toFixed(1)}s</span>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      )}
      <p className="muted center" style={{ marginTop: 14 }}>Shows scrubbing recognized by the station, about a second behind. No video is sent to this screen.</p>
    </div>
  );
}
