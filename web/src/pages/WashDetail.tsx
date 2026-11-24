import { useState } from "react";
import { send, useApi, ZONE_MOVES, ZONE_NAMES, ZONES, type ApiError, type WashDetail as Detail, type Zone } from "../api";
import { CaveScene } from "../art/scenes";
import { Creature, germFor } from "../components/Creature";
import { Icon } from "../components/icons";
import { RegionHandMap, zoneState } from "../components/RegionHandMap";
import { Bar, EmptyState, GameButton, InlineError, Pending, TopBar } from "../components/ui";
import { go } from "../router";
import "./WashDetail.css";

function Stars({ n }: { n: number }) {
  return (
    <div className="stars" role="img" aria-label={`${n} of 5 stars`}>
      {[1, 2, 3, 4, 5].map((i) => <span key={i} className={i <= n ? "on" : ""} style={{ animationDelay: `${120 + i * 90}ms` }}><Icon name="star" size={i === 3 ? 34 : 28} /></span>)}
    </div>
  );
}

/** The zone to practise next: the least-washed one. None when everything reached its full time. */
function weakest(w: Detail): Zone | null {
  const z = [...ZONES].sort((a, b) => w.coverage[a] - w.coverage[b])[0];
  return w.coverage[z] < 1 ? z : null;
}

function HighFive({ w, onDone }: { w: Detail; onDone: () => void }) {
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  if (w.high_fived) {
    return <p className="fived" role="status"><Icon name="heart" size={20} />High-five saved. It shows on this wash in the app.</p>;
  }
  const give = () => {
    setBusy(true);
    send("POST", `/api/v1/app/washes/${encodeURIComponent(w.wash_id)}/high-five`).then(onDone, (e: ApiError) => { setError(e); setBusy(false); });
  };
  return (
    <>
      <GameButton tone="gold" wide icon="hand" disabled={busy} onClick={give}>Give a high-five</GameButton>
      <p className="faint center">Saved with this wash in the app. It is not sent to the sink station.</p>
      {error && <InlineError error={error} />}
    </>
  );
}

export default function WashDetail({ id }: { id: string }) {
  const { data: w, error, reload } = useApi<Detail>(`/api/v1/app/washes/${encodeURIComponent(id)}`);
  if (!w) {
    return (
      <div className="page">
        <TopBar title="Wash" back="/history" />
        {error?.status === 404
          ? <EmptyState title="Wash not found" creature="smudge" action={<GameButton onClick={() => go("/history")}>Open history</GameButton>}>
              It may belong to another child or was deleted with the wash history.
            </EmptyState>
          : <Pending error={error} retry={reload} blocks={3} />}
      </div>
    );
  }
  const recognized = w.stars > 0;
  const weak = recognized ? weakest(w) : null;
  const goalMet = w.seconds_total >= w.total_min_s;
  const synced = new Date(w.received).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });
  const hero = !recognized ? "smudge" : weak ? germFor(weak) : "bubbles";
  const headline = !recognized ? "No scrubbing seen" : !w.missed.length ? "Perfect scrub!" : w.finished ? "Great scrub!" : "Good start!";

  return (
    <div className="page detail">
      <TopBar title={`${w.label} · ${w.time}`} back="/history" />

      <section className="panel violet illustrated result">
        <div className="scene" aria-hidden="true"><CaveScene tint="#f6c64f" /></div>
        <div className="content">
          <Creature id={hero} size={96} className="pop" />
          <Stars n={w.stars} />
          <h2>{headline}</h2>
          <div className="score"><b className="num">{w.points}</b><span>score<br />out of 100</span></div>
          <div className="tags earned">
            {w.reward_points > 0 && <span className="tag gold"><Icon name="coin" size={14} />+{w.reward_points} points</span>}
            {w.zaps > 0 && <span className="tag gold"><Icon name="bolt" size={14} />+{w.zaps} zaps</span>}
            {recognized && w.reward_points === 0 && <span className="tag">Daily goal already met: no extra points</span>}
            {w.source === "demo" && <span className="tag demo">Demo data</span>}
          </div>
        </div>
      </section>

      <dl className="trio">
        <div className="panel flat">
          <dt>Scrub time</dt>
          <dd><b className="num">{Math.round(w.seconds_total)}s</b>{goalMet && <span className="ok"><Icon name="check" size={14} /></span>}</dd>
          <small>of {w.total_min_s}s goal</small>
        </div>
        <div className="panel flat">
          <dt>Steps done</dt>
          <dd><b className="num">{w.steps_done}/7</b></dd>
          <small>{w.steps_required} needed</small>
        </div>
        <div className="panel flat">
          <dt>At the sink</dt>
          <dd><b className="num">{Math.round(w.duration_s)}s</b></dd>
          <small>hands in view</small>
        </div>
      </dl>

      <section className="panel">
        <h3>Where the germs got zapped</h3>
        <RegionHandMap coverage={w.coverage} recognized={recognized} />
        <ul className="zones">
          {ZONES.map((z) => {
            const st = zoneState(w.coverage[z], recognized);
            const got = Math.min(w.coverage[z] * w.step_min_s, w.step_min_s);
            return (
              <li key={z} className={st}>
                <span className="zname">{ZONE_NAMES[z]}</span>
                <Bar value={recognized ? w.coverage[z] : 0} tone={st === "washed" ? "mint" : st === "missed" ? "coral" : "gold"} label={`${ZONE_NAMES[z]} scrubbing`} />
                <span className="zval num">{st === "unknown" ? "not seen" : st === "missed" ? "missed" : `${got.toFixed(1)}s`}</span>
              </li>
            );
          })}
        </ul>
        <p className="faint how">
          A zone counts as washed after {w.step_min_s}s of its scrubbing motion, as recognized by the camera.
          This is an estimate of motion time. It does not measure germs or how clean the hands are.
        </p>
      </section>

      {weak && (
        <section className="panel deep coach">
          <Creature id={germFor(weak)} size={60} />
          <p><b>Next time: {ZONE_NAMES[weak].toLowerCase()}</b>Show the move together: {ZONE_MOVES[weak]}. Count to three out loud.</p>
        </section>
      )}

      <section className="highfive"><HighFive w={w} onDone={reload} /></section>

      <footer className="proof">
        <span className="tag good"><Icon name="check" size={13} />Synced {synced}</span>
        {w.soap_seen !== null && <span className="tag">{w.soap_seen ? "Lather seen (rough check)" : "No lather seen (rough check)"}</span>}
        <code>Wash ID {w.wash_id}</code>
      </footer>
    </div>
  );
}
