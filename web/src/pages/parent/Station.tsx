// "Station": how a wash travels from the sink to this app, shown with what actually arrived.
import { useApi, type Station as StationData, type SyncLog } from "../../api";
import { Button, PageHead, Pending, StationStatus } from "../../components/ui";
import { useLive, useWashStage } from "../../live";
import { go, Link } from "../../router";
import { clock, SourceTag } from "../../wash";

const STEP_WORDS: Record<string, string> = {
  palm_to_palm: "palm to palm", back_of_hand: "back of hand", interlaced_fingers: "fingers interlaced", backs_of_fingers: "backs of fingers",
  thumb_rubbing: "thumbs", fingertip_rubbing: "fingertips", wrist_rubbing: "wrists",
};
function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function Station() {
  const { data: sync, error, reload } = useApi<SyncLog>("/api/v1/app/sync");
  const { data: st } = useApi<StationData>("/api/v1/app/station");
  const { connected } = useLive();
  const { stage, live, now } = useWashStage();
  const score = live?.score;
  const latest = sync?.log[0];

  return (
    <div className="page">
      <PageHead title="Station and sync" sub="How a wash gets from the sink to this app">
        <StationStatus />
      </PageHead>

      <section className="card" style={{ marginBottom: 16 }}>
        <ol className="flow">
          <li>
            <span className="where">At the sink</span><b>The camera watches the hands</b>
            <p>A small camera above the sink films only the hands while they scrub. A projector lights up germs on them.</p>
            <p className="state"><span className={`tag ${stage === "scrubbing" ? "good" : ""}`}>{stage === "scrubbing" ? `Hands in view: ${live?.hands ?? 0}` : stage === "off" ? "Station not running" : "Waiting for hands"}</span></p>
          </li>
          <li>
            <span className="where">On the station laptop</span><b>Each scrubbing move is recognized</b>
            <p>The laptop names the move (palms, thumbs, fingertips and four more) and times it. The picture never leaves the laptop.</p>
            <p className="state"><span className={`tag ${now ? "good" : ""}`}>{now ? `Now: ${STEP_WORDS[now] ?? now}` : stage === "scrubbing" ? "Watching for a move" : "Idle"}</span></p>
          </li>
          <li>
            <span className="where">When the hands leave</span><b>One small record is made</b>
            <p>Seconds per move, the score, start and end time. About 2 KB of numbers. It waits in a queue on the laptop until it is delivered, so nothing is lost if Wi-Fi drops.</p>
            <p className="state"><span className="tag">{stage === "scrubbing" ? `${Math.round(score?.total_s ?? 0)} s scrubbed, score ${score?.points ?? 0} so far` : latest ? `Last record: ${(latest.bytes / 1024).toFixed(1)} KB` : "No record yet"}</span></p>
          </li>
          <li>
            <span className="where">In this app</span><b>The wash is saved once and every screen updates</b>
            <p>The app checks the record, saves it for the child picked on the Overview, adds the points, and refreshes any open screen. No reload.</p>
            <p className="state"><span className={`tag ${connected ? "good" : "miss"}`}>{!connected ? "This screen is offline" : latest ? `Last saved ${ago(latest.received)}` : "Connected, waiting for a wash"}</span></p>
          </li>
        </ol>
      </section>

      {stage === "scrubbing" && score && (
        <section className="card" style={{ marginBottom: 16 }}>
          <h2 className="h2">Live from the sink</h2>
          <table className="data">
            <thead><tr><th>Scrubbing step</th><th className="r">Seconds so far</th><th>Status</th></tr></thead>
            <tbody>{score.steps.map((s) => <tr key={s.technique}><td>{STEP_WORDS[s.technique] ?? s.technique}</td><td className="r">{s.seconds.toFixed(1)}</td><td>{now === s.technique ? <span className="tag sink">Scrubbing now</span> : s.done ? <span className="tag good">Done</span> : ""}</td></tr>)}</tbody>
          </table>
          <p className="note">About a second behind the sink. These are the same numbers that go into the record when the wash ends.</p>
        </section>
      )}

      <div className="twocol" style={{ marginBottom: 16 }}>
        <section className="card">
          <h2 className="h2">What is sent to the app</h2>
          <ul className="ticks">
            <li>Seconds of each of the 7 scrubbing moves</li>
            <li>The score, stars and steps done</li>
            <li>When the wash started and ended</li>
            <li>The recognizer's version and a few quality numbers</li>
          </ul>
          {sync?.example && (
            <details>
              <summary>See the actual record of the latest wash</summary>
              <pre className="record">{JSON.stringify(sync.example.record, null, 1)}</pre>
            </details>
          )}
        </section>
        <section className="card">
          <h2 className="h2">What is never sent</h2>
          <ul className="ticks no">
            <li>Camera pictures or video</li>
            <li>The outline or position of the hands</li>
            <li>Who the child is: you pick the child in the app</li>
          </ul>
          <p className="note">On the laptop itself, a run started with the save option keeps hand-point files in its own folder. They stay on the laptop.</p>
        </section>
      </div>

      <section className="card">
        <div className="sec" style={{ margin: "0 0 4px" }}>
          <h2 className="h2">Sync log</h2>
          {sync && <span className="muted num">{sync.from_station} from the sink, {sync.from_demo} demo</span>}
        </div>
        {!sync ? <Pending error={error} retry={reload} blocks={1} /> : !sync.log.length ? (
          <p className="lede">No washes yet. Start the station and wash: the first row appears here a few seconds after the hands leave.</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Washed</th><th>Saved in the app</th><th className="r">Delay</th><th className="r wide-only">Size</th><th>Source</th><th className="r">Score</th><th className="wide-only">Wash ID</th></tr></thead>
              <tbody>
                {sync.log.map((r) => (
                  <tr key={r.wash_id} className="go" onClick={() => go(`/washes/${encodeURIComponent(r.wash_id)}`)}>
                    <td><Link to={`/washes/${encodeURIComponent(r.wash_id)}`} className="cell" onClick={(e) => e.stopPropagation()}>{new Date(r.ended).toLocaleDateString(undefined, { month: "short", day: "numeric" })}, {clock(r.ended)}</Link></td>
                    <td>{clock(r.received)}</td>
                    <td className="r">{r.source === "demo" ? "–" : r.lag_s < 120 ? `${r.lag_s.toFixed(1)} s` : `${Math.round(r.lag_s / 60)} min`}</td>
                    <td className="r wide-only">{(r.bytes / 1024).toFixed(1)} KB</td>
                    <td><SourceTag source={r.source} /></td>
                    <td className="r">{r.points}</td>
                    <td className="wide-only"><code>{r.wash_id}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="note">
          Delay is the time from the end of washing to the app saving it. It includes the 4 seconds the station waits to be sure the hands have left.
          A long delay means the laptop was offline and delivered the wash later from its queue. Demo rows were loaded by a script, not washed.
        </p>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h2 className="h2">Station details</h2>
        <div className="rows">
          <div className="row"><span className="grow">Last heard from</span><span className="value">{st?.online ? "now" : st?.last_seen ? ago(st.last_seen) : "not since the app's server started"}</span></div>
          <div className="row"><span className="grow">Last wash from the sink</span><span className="value">{ago(st?.last_wash ?? null)}</span></div>
          <div className="row"><span className="grow">Scrub goal and step time</span><span className="value">{st?.rules ? `${st.rules.scrub_goal_s} s total, ${st.rules.step_min_s} s per step` : "known after the first real wash"}</span></div>
          <div className="row"><span className="grow">Recognizer</span><span className="value">{st?.rules?.model?.version ? `v${st.rules.model.version}` : "known after the first real wash"}</span></div>
        </div>
        <p className="note">These are set on the station laptop. The app shows them; it cannot change them yet.</p>
        <p style={{ marginTop: 12 }}><Button tone="quiet" small onClick={() => go("/kid/live")}>Open the kid's live screen</Button></p>
      </section>
    </div>
  );
}
