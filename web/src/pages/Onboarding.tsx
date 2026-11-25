// First-run setup, from the design's onboarding flow: a kid-facing intro, then a short parent setup.
// Each step saves as it goes, so a reload never loses what was entered.
import { useEffect, useState, type ReactNode } from "react";
import { api, type Child, type Settings } from "../api";
import { GoalRow, KidForm, RoutineList } from "../components/forms";
import { Germ } from "../components/germs";
import { Icon } from "../components/ui";
import { useLive, useStationActive } from "../live";

type Station = { backend: string; devices: { device_id: string; status: string }[]; last_wash: string | null };
const SETUP = ["kid", "station", "camera", "routines"]; // the parent's 4 numbered steps

function SinkStation() {
  return (
    <div className="mini-station" aria-hidden="true">
      <div className="screen"><Germ id="prickle" size={40} /><Germ id="smudge" size={36} /></div>
      <div className="neck" />
      <div className="basin" />
    </div>
  );
}

function Top({ back, right }: { back?: () => void; right?: ReactNode }) {
  return (
    <div className="onb-top">
      {back ? <button className="back" onClick={back} aria-label="Back"><Icon name="left" /></button> : <span />}
      {right}
    </div>
  );
}

export default function Onboarding({ settings, onDone }: { settings: Settings; onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [parent, setParent] = useState(settings.parent_name);
  const [kid, setKid] = useState<Child>({ name: "", buddy: "scrubby", age_band: "5-6" });
  const [routines, setRoutines] = useState(settings.routines);
  const [goal, setGoal] = useState(settings.daily_goal);
  const [station, setStation] = useState<Station | null>(null);
  const [connected, setConnected] = useState(false);
  const [sawHands, setSawHands] = useState(false);
  const [busy, setBusy] = useState(false);
  const { live } = useLive();
  const running = useStationActive();
  const next = () => setStep((s) => s + 1);
  const back = () => setStep((s) => s - 1);
  const save = (path: string, body: object) => { setBusy(true); return api(path, { method: "PUT", body: JSON.stringify(body) }).finally(() => setBusy(false)); };

  useEffect(() => { api<Child | null>("/api/v1/app/child").then((c) => c && setKid(c), () => {}); }, []);
  useEffect(() => { if (step === 0) { const t = window.setTimeout(next, 1800); return () => clearTimeout(t); } }, [step]);
  useEffect(() => { if (step === 6) api<Station>("/api/v1/app/station").then(setStation, () => setStation(null)); }, [step]);
  useEffect(() => { if (live && live.hands > 0) setSawHands(true); }, [live]);

  const name = kid.name || "your kid";

  if (step === 0) {
    return (
      <div className="splash" onClick={next} role="button" aria-label="Start">
        <span className="corner" style={{ left: 18, top: 24 }}><Germ id="sneezel" size={56} bob /></span>
        <span className="corner" style={{ right: 18, top: 40 }}><Germ id="gunky" size={56} bob className="delay1" /></span>
        <span className="corner" style={{ left: 22, bottom: 40 }}><Germ id="smudge" size={54} bob className="delay2" /></span>
        <span className="corner" style={{ right: 22, bottom: 30 }}><Germ id="prickle" size={56} bob className="delay3" /></span>
        <div style={{ textAlign: "center" }}>
          <Germ id="scrubby" size={170} className="pop" />
          <div className="wordmark">Scrubby</div>
          <p className="muted" style={{ marginTop: 14 }}>Wash. Fight. <b>Win.</b></p>
        </div>
      </div>
    );
  }

  if (step <= 3) {
    const intro = [
      { title: "Germs are sneaky!", text: "They hide on palms, between fingers and around thumbs. Only a super scrub can stop them.",
        art: <div className="onb-art green"><div className="germ-grid">{["sneezel", "prickle", "gunky", "smudge"].map((g, i) => <Germ key={g} id={g} size={92} bob className={`delay${i}`} />)}</div></div> },
      { title: "Scrub to zap them", text: "The Scrubby Station at your sink watches your scrub and zaps germs off your palms, fingers and thumbs.",
        art: <div className="onb-art blue"><SinkStation /></div> },
      { title: "Earn zaps, build habits", text: "Kids earn zaps for great scrubs. Grown-ups see progress and the spots that get missed.",
        art: (
          <div className="onb-art green" style={{ gridTemplateColumns: "1fr 1fr", gap: 10, padding: 18 }}>
            <div style={{ display: "grid", justifyItems: "center", gap: 8 }}><Germ id="gunky" size={96} bob /><span className="pill zaps">+10 zaps</span></div>
            <div className="card" style={{ padding: 12 }}>
              <div className="faint">This week</div>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 5, height: 70, marginTop: 8 }}>
                {[3, 5, 4, 6, 5, 6, 4].map((h, i) => <div key={i} style={{ flex: 1, height: `${h * 15}%`, borderRadius: 4, background: i === 5 ? "var(--blue-btn)" : "#c9d6e4" }} />)}
              </div>
              <div className="faint" style={{ marginTop: 6 }}>12 clean washes</div>
            </div>
          </div>
        ) },
    ][step - 1];
    return (
      <div className="onb fade-in" key={step}>
        <Top back={step > 1 ? back : undefined} right={<button className="link-btn" onClick={() => setStep(4)}>Skip</button>} />
        {intro.art}
        <h1 className="onb-title">{intro.title}</h1>
        <p className="onb-text">{intro.text}</p>
        <div className="grow" />
        <div className="dots">{[1, 2, 3].map((i) => <i key={i} className={i === step ? "on" : ""} />)}</div>
        <button className="btn" onClick={next}>{step === 3 ? "Get started" : "Next"}</button>
      </div>
    );
  }

  if (step === 4) {
    return (
      <div className="onb fade-in">
        <Top back={back} />
        <h1 className="onb-title" style={{ textAlign: "left", color: "var(--ink)" }}>Hi grown-up!</h1>
        <p className="muted" style={{ marginTop: 0 }}>Set up Scrubby to see your kid's washes, rewards and the sink station.</p>
        <label className="field"><span>Your name</span>
          <input value={parent} placeholder="Sam" maxLength={64} autoComplete="given-name" onChange={(e) => setParent(e.target.value)} />
        </label>
        <label className="field"><span>Email <span className="soon">coming soon</span></span><input disabled placeholder="sam@email.com" /></label>
        <label className="field"><span>Password <span className="soon">coming soon</span></span><input disabled type="password" placeholder="••••••••" /></label>
        <button className="btn" disabled={!parent.trim() || busy} onClick={() => save("/api/v1/app/settings", { parent_name: parent.trim() }).then(next)}>Continue</button>
        <p className="faint" style={{ textAlign: "center", margin: "14px 0" }}>or</p>
        <div style={{ display: "grid", gap: 10 }}>
          <button className="btn outline" disabled>Continue with Apple <span className="soon">soon</span></button>
          <button className="btn outline" disabled>Continue with Google <span className="soon">soon</span></button>
        </div>
        <div className="grow" />
        <p className="faint" style={{ textAlign: "center", marginTop: 16 }}>Accounts come later. For now everything stays on this laptop.</p>
      </div>
    );
  }

  const n = step - 4; // 1..4 for the numbered parent setup, 5 = all set
  const head = (title: string) => (
    <>
      <div className="page-head" style={{ marginBottom: 6 }}>
        <button className="back" onClick={back} aria-label="Back"><Icon name="left" /></button>
        <h1>{title}</h1>
        <span className="faint" style={{ width: 36, textAlign: "right" }}>{n} of {SETUP.length}</span>
      </div>
      <div className="progress"><div style={{ width: `${(n / SETUP.length) * 100}%` }} /></div>
    </>
  );

  if (step === 5) {
    return (
      <div className="onb fade-in">
        {head("Add a kid")}
        <h2 className="onb-title" style={{ textAlign: "left", marginTop: 0 }}>Who's busting germs?</h2>
        <KidForm kid={kid} onChange={setKid} />
        <div className="grow" />
        <button className="btn dark" disabled={!kid.name.trim() || busy} onClick={() => save("/api/v1/app/child", { ...kid, name: kid.name.trim() }).then(next)}>Continue</button>
      </div>
    );
  }

  if (step === 6) {
    const pis = (station?.devices ?? []).filter((d) => d.status !== "unknown"); // sink devices say hello; camera runs on this laptop are "unknown"
    return (
      <div className="onb fade-in">
        {head("Connect station")}
        <div className="onb-art green" style={{ height: 200 }}><SinkStation /></div>
        <h2 className="onb-title" style={{ color: "var(--ink)", fontSize: 21 }}>{station ? (connected ? "Station connected!" : "Found your Scrubby Station") : "Looking for your Scrubby Station..."}</h2>
        <p className="onb-text">Today the station is this laptop and its camera. A sink device can join later the same way.</p>
        {station && (
          <div className="card" style={{ marginTop: 16, padding: "4px 14px" }}>
            <div className="row">
              <span className="row-icon"><Icon name="wifi" size={18} /></span>
              <div className="grow"><div className="title">Scrubby Station</div><div className="faint">This laptop · online</div></div>
              {connected ? <span className="pill perfect"><Icon name="check" size={12} />Connected</span>
                : <button className="btn dark" style={{ width: "auto", padding: "8px 16px", fontSize: 14 }} onClick={() => setConnected(true)}>Connect</button>}
            </div>
            {pis.map((d) => (
              <div className="row" key={d.device_id}>
                <span className="row-icon"><Icon name="wifi" size={18} /></span>
                <div className="grow"><div className="title">{d.device_id}</div><div className="faint">Sink device · {d.status}</div></div>
              </div>
            ))}
          </div>
        )}
        <div className="grow" />
        <button className="btn dark" disabled={!connected} onClick={next}>Continue</button>
      </div>
    );
  }

  if (step === 7) {
    return (
      <div className="onb fade-in">
        {head("Set up camera")}
        <div className="onb-art" style={{ background: "#26395a", height: 210, color: "#dbe5f3", textAlign: "center", padding: 20 }}>
          <div>
            <Germ id="scrubby" size={80} bob={!sawHands} />
            <p style={{ margin: "10px 0 0" }}>{sawHands ? "Hands seen!" : running ? "Hold both hands over the sink" : "Start the station to check the camera"}</p>
          </div>
        </div>
        <ul className="check-list">
          <li className={running ? "ok" : ""}><span className="dot"><Icon name="check" size={14} /></span>Station is running</li>
          <li className={sawHands ? "ok" : ""}><span className="dot"><Icon name="check" size={14} /></span>Both hands in view</li>
          <li><span className="dot" style={{ background: "none", color: "var(--ink-faint)" }}><Icon name="spark" size={14} /></span>Camera 30 to 60 cm above the hands, good light</li>
        </ul>
        <div className="privacy"><Icon name="shield" size={20} /><span><b>No video comes to this app.</b> The station only sends scores and missed spots.</span></div>
        <div className="grow" />
        <button className="btn dark" disabled={!sawHands} onClick={next}>Looks good</button>
        <button className="link-btn" style={{ marginTop: 8 }} onClick={next}>Skip for now</button>
      </div>
    );
  }

  if (step === 8) {
    return (
      <div className="onb fade-in">
        {head("Wash routines")}
        <h2 className="onb-title" style={{ textAlign: "left", marginTop: 0, color: "var(--ink)", fontSize: 22 }}>When should {name} wash?</h2>
        <RoutineList routines={routines} onChange={setRoutines} />
        <GoalRow goal={goal} onChange={setGoal} />
        <div className="grow" />
        <button className="btn dark" disabled={busy} onClick={() => save("/api/v1/app/settings", { routines, daily_goal: goal }).then(next)}>Finish setup</button>
      </div>
    );
  }

  return (
    <div className="splash" style={{ cursor: "default" }}>
      <span className="corner" style={{ left: 18, top: 30 }}><Germ id="sneezel" size={50} bob /></span>
      <span className="corner" style={{ right: 18, top: 44 }}><Germ id="gunky" size={50} bob className="delay1" /></span>
      <div style={{ textAlign: "center", padding: "0 24px" }}>
        <Germ id={kid.buddy} size={150} className="pop" />
        <h1 className="onb-title" style={{ color: "var(--ink)" }}>Ready to bust some germs, {name}!</h1>
        <p className="onb-text">Wash at the station and watch the germs pop. Every step scrubbed earns zaps.</p>
        <button className="btn dark" style={{ marginTop: 28 }} disabled={busy} onClick={() => save("/api/v1/app/settings", { onboarded: true }).then(onDone)}>Go to dashboard</button>
      </div>
    </div>
  );
}
