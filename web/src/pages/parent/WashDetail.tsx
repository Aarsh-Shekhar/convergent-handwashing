import { useState } from "react";
import { send, useApi, ZONE_MOVES, ZONE_NAMES, ZONES, type ApiError, type WashDetail as Detail, type Zone } from "../../api";
import { WashHands, zoneState } from "../../components/HandFigure";
import { Button, EmptyState, InlineError, PageHead, Pending, Stars } from "../../components/ui";
import { go } from "../../router";
import { clock, SourceTag, when } from "../../wash";

/** The zone to practise next: the least-washed one. None when everything reached its full time. */
export function weakest(w: Pick<Detail, "coverage">): Zone | null {
  const z = [...ZONES].sort((a, b) => w.coverage[a] - w.coverage[b])[0];
  return w.coverage[z] < 1 ? z : null;
}

function HighFive({ w, onDone }: { w: Detail; onDone: () => void }) {
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  if (w.high_fived) return <p className="tag good" role="status" style={{ whiteSpace: "normal" }}>High-five sent. It shows on this wash in the kid view.</p>;
  return (
    <>
      <Button icon="hand" disabled={busy} onClick={() => { setBusy(true); send("POST", `/api/v1/app/washes/${encodeURIComponent(w.wash_id)}/high-five`).then(onDone, (e: ApiError) => { setError(e); setBusy(false); }); }}>Give a high-five</Button>
      <p className="note">It appears on this wash in the kid view. Nothing is sent to the sink station.</p>
      {error && <InlineError error={error} />}
    </>
  );
}

export default function WashDetail({ id }: { id: string }) {
  const { data: w, error, reload } = useApi<Detail>(`/api/v1/app/washes/${encodeURIComponent(id)}`);
  if (!w) {
    return (
      <div className="page">
        <PageHead title="Wash" back={["Washes", "/washes"]} />
        {error?.status === 404
          ? <EmptyState title="Wash not found" action={<Button onClick={() => go("/washes")}>All washes</Button>}>It may belong to another child, or it was deleted with the wash history.</EmptyState>
          : <Pending error={error} retry={reload} blocks={3} />}
      </div>
    );
  }
  const recognized = w.stars > 0;
  const weak = recognized ? weakest(w) : null;
  const stepSum = w.steps.reduce((a, s) => a + s.points, 0);
  return (
    <div className="page">
      <PageHead title={`${w.label}, ${w.time}`} back={["Washes", "/washes"]} sub={when(w.ended)}>
        <SourceTag source={w.source} />
      </PageHead>

      <dl className="kpis">
        <div className="kpi"><dt>Score</dt><dd>{w.points}<small>/ 100</small></dd><p><Stars n={w.stars} size={16} /></p></div>
        <div className="kpi"><dt>Scrub time</dt><dd>{w.seconds_total.toFixed(1)}<small>s</small></dd><p>goal {w.total_min_s} s{w.seconds_total >= w.total_min_s ? ", reached" : ""}</p></div>
        <div className="kpi"><dt>Steps done</dt><dd>{w.steps_done}<small>/ 7</small></dd><p>{w.steps_required} needed to finish</p></div>
        <div className="kpi"><dt>At the sink</dt><dd>{Math.round(w.duration_s)}<small>s</small></dd><p>hands in view</p></div>
        <div className="kpi"><dt>Earned</dt><dd>{w.reward_points}<small>points</small></dd><p>{w.capped ? "Daily goal was already met" : `${w.zaps} zaps`}</p></div>
      </dl>

      <div className="grid2">
        <section className="card">
          <h2 className="h2">How the score adds up</h2>
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Scrubbing step</th><th className="r">Seconds</th><th className="r">Of {w.step_min_s} s</th><th className="r">Points</th></tr></thead>
              <tbody>
                {w.steps.map((s) => (
                  <tr key={s.technique}>
                    <td>{s.name}</td><td className="r">{s.seconds.toFixed(1)}</td>
                    <td className="r">{Math.round(Math.min(s.seconds / w.step_min_s, 1) * 100)}%{s.done ? "" : s.seconds > 0 ? " (short)" : " (missed)"}</td>
                    <td className="r">{s.points.toFixed(1)}</td>
                  </tr>
                ))}
                <tr><td>Total scrub time</td><td className="r">{w.seconds_total.toFixed(1)}</td><td className="r">{Math.round(Math.min(w.seconds_total / w.total_min_s, 1) * 100)}% of {w.total_min_s} s</td><td className="r">{w.time_points.toFixed(1)}</td></tr>
                <tr className="total"><td>Score</td><td /><td /><td className="r">{w.points}</td></tr>
              </tbody>
            </table>
          </div>
          <p className="formula" style={{ marginTop: 10 }}>
            each step: 10 × min(seconds ÷ {w.step_min_s}, 1) = {stepSum.toFixed(1)}<br />
            time: 30 × min(total ÷ {w.total_min_s}, 1) = {w.time_points.toFixed(1)}
          </p>
          <p className="note">Seconds are scrubbing motion recognized by the camera. The score measures motion time. It does not measure germs or how clean the hands are.</p>
        </section>

        <div className="stack">
          <section className="card">
            <h2 className="h2">Zones on the hands</h2>
            <WashHands coverage={w.coverage} recognized={recognized} />
            <table className="data" style={{ marginTop: 12 }}>
              <thead><tr><th>Zone</th><th className="r">Scrub time</th><th>Result</th></tr></thead>
              <tbody>
                {ZONES.map((z) => {
                  const st = zoneState(w.coverage[z], recognized);
                  return <tr key={z}><td>{ZONE_NAMES[z]}</td><td className="r">{recognized ? `${Math.round(w.coverage[z] * 100)}%` : "–"}</td>
                    <td><span className={`tag ${st === "washed" ? "good" : st === "missed" ? "miss" : st === "partly" ? "gold" : ""}`}>{st === "unknown" ? "Not seen" : st[0].toUpperCase() + st.slice(1)}</span></td></tr>;
                })}
              </tbody>
            </table>
            {weak && <p className="note"><b>To practise: {ZONE_NAMES[weak].toLowerCase()}.</b> Show the move together: {ZONE_MOVES[weak]}.</p>}
          </section>
          <section className="card">
            <h2 className="h2">How this wash got here</h2>
            <div className="rows">
              <div className="row"><span className="grow">Washing ended at the sink</span><span className="value num">{clock(w.ended)}</span></div>
              <div className="row"><span className="grow">Saved in the app</span><span className="value num">{clock(w.received)} ({w.lag_s < 90 ? `${w.lag_s.toFixed(1)} s later` : "loaded later"})</span></div>
              <div className="row"><span className="grow">Recognizer{w.soap_seen !== null ? ", lather check" : ""}</span><span className="value">{w.model?.version && w.model.version !== "demo" ? `v${w.model.version}` : "–"}{w.soap_seen !== null ? (w.soap_seen ? ", lather seen" : ", no lather seen") : ""}</span></div>
            </div>
            <p className="mono" style={{ marginTop: 8 }}>Wash ID {w.wash_id}</p>
          </section>
          <section className="card"><HighFive w={w} onDone={reload} /></section>
        </div>
      </div>
    </div>
  );
}
