// Live wash (beta): what the station sees right now, from the wash software's `live` feed.
// Stages: idle (station not running) -> ready (no hands) -> scrubbing -> results (a wash just saved).
import { useEffect, useState } from "react";
import { useApi, ZONE_NAMES, type Child, type Zone } from "../api";
import { Germ, germFor } from "../components/germs";
import { Icon, PageHead, Ring } from "../components/ui";
import { useLive, useStationActive } from "../live";
import { go } from "../router";

const STEPS: [string, string, Zone][] = [
  ["palm_to_palm", "Palms", "palms"], ["back_of_hand", "Backs of hands", "backs"], ["interlaced_fingers", "Between fingers", "between_fingers"],
  ["backs_of_fingers", "Backs of fingers", "backs"], ["thumb_rubbing", "Thumbs", "thumbs"], ["fingertip_rubbing", "Fingertips", "nails"],
  ["wrist_rubbing", "Wrists", "wrists"],
];
const NAME = Object.fromEntries(STEPS.map(([t, n]) => [t, n]));
const RESULT_S = 12;

function Stars({ n }: { n: number }) {
  return <span className="stars" aria-label={`${n} of 5 stars`}>{[1, 2, 3, 4, 5].map((i) => <span key={i} className={i <= n ? "on" : ""}>★</span>)}</span>;
}

export default function Live() {
  const { live, liveAt, saved, savedCount } = useLive();
  const active = useStationActive();
  const { data: kid } = useApi<Child | null>("/api/v1/app/child");
  const [savedAt, setSavedAt] = useState(0);
  const [, tick] = useState(0);
  useEffect(() => { if (saved) setSavedAt(Date.now()); }, [saved, savedCount]);
  useEffect(() => { const t = window.setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, []);

  const name = kid?.name ?? "there";
  const score = live?.score;
  const scrubbing = active && !!live && (live.hands > 0 || (score?.total_s ?? 0) > 0);
  // results stay up for RESULT_S, or until the next child starts scrubbing (live messages sent after the save)
  const nextWash = liveAt > savedAt && !!live && live.hands > 0 && (score?.total_s ?? 0) > 0;
  const showResult = saved && Date.now() - savedAt < RESULT_S * 1000 && !nextWash;
  const now = live?.active?.validated ? live.active.technique : live?.fused?.status === "valid" ? live.fused.technique : null;

  return (
    <div className="page fade-in">
      <PageHead title="Live wash (beta)" back={() => go("/")} />

      {showResult ? (
        <div className="card live-hero result fade-in" key={saved.wash_id}>
          <Germ id={saved.missed.length ? germFor(saved.missed[0]) : "scrubby"} size={96} className="pop" />
          <h2>{saved.missed.length ? "Great scrub!" : "Perfect scrub!"} +{saved.points}</h2>
          <Stars n={saved.stars} />
          <p className="muted">
            {saved.missed.length
              ? <>Almost! The <b>{saved.missed.map((z) => ZONE_NAMES[z].toLowerCase()).join(", ")}</b> still had germs. Get them next time.</>
              : "Every part of the hands got scrubbed. Germs zapped!"}
          </p>
          <div className="pill-row" style={{ justifyContent: "center" }}>
            {saved.zaps > 0 && <span className="pill zaps">+{saved.zaps} zaps</span>}
            <span className="pill">{Math.round(saved.seconds_total)} sec</span>
          </div>
          <button className="btn-ghost" onClick={() => go(`/washes/${encodeURIComponent(saved.wash_id)}`)}>See the hand map <Icon name="right" size={16} /></button>
        </div>
      ) : !active ? (
        <div className="card live-hero">
          <Germ id="scrubby" size={110} bob />
          <h2>Waiting for the station</h2>
          <p className="muted">Start the Scrubby station at the sink. This page wakes up as soon as it sees hands.</p>
        </div>
      ) : !scrubbing ? (
        <div className="card live-hero">
          <Germ id="scrubby" size={110} bob />
          <h2>Hi {name}!</h2>
          <p className="muted">Wet your hands and add soap to start.</p>
          <div className="waiting-germs">
            {["prickle", "sneezel", "gunky", "smudge"].map((g, i) => <Germ key={g} id={g} size={40} bob className={`delay${i}`} />)}
          </div>
        </div>
      ) : (
        <>
          <div className="card live-now">
            <Ring value={(score?.total_s ?? 0) / 20} size={104} stroke={11} color="var(--blue-btn)">
              <div className="ring-label"><b>{Math.round(score?.total_s ?? 0)}s</b><span>of 20s</span></div>
            </Ring>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="faint">{now ? "Scrubbing now" : live!.hands ? "Hands in view" : "Hands out of view"}</div>
              <div className="now-step">{now ? `${NAME[now] ?? now}!` : "Keep scrubbing"}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                <Stars n={score?.stars ?? 0} /><span className="faint">{score?.points ?? 0} pts</span>
              </div>
            </div>
          </div>
          <div className="card">
            <h3>Steps <span className="faint">({score?.steps_done ?? 0} of 7 done)</span></h3>
            <div className="step-grid">
              {STEPS.map(([t, label, zone]) => {
                const s = score?.steps.find((x) => x.technique === t);
                const secs = s?.seconds ?? 0;
                const min = score?.step_min_s ?? 3;
                return (
                  <div key={t} className={`step ${s?.done ? "done" : ""} ${now === t ? "now" : ""}`}>
                    <Ring value={secs / min} size={58} stroke={6} color={s?.done ? "#57c94a" : "var(--blue-btn)"}>
                      {s?.done ? <span className="tick"><Icon name="check" size={20} /></span> : <Germ id={germFor(zone)} size={30} />}
                    </Ring>
                    <span className="step-name">{label}</span>
                    <span className="faint">{secs.toFixed(1)}s</span>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}

      <p className="faint" style={{ textAlign: "center", margin: "14px 8px 0" }}>
        Beta: shows recognized scrubbing motion from the station, about a second behind. No video is sent to this page.
      </p>
    </div>
  );
}
