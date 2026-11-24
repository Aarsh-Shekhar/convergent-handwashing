// First run: a short story for the kid (who the germs are, how scrubbing zaps them), then set-up for the
// grown-up. Ten steps, as in the design. Progress is kept on this device, so a reload continues where it was.
import { useEffect, useState, type ReactNode } from "react";
import { send, useApi, type AgeBand, type ApiError, type Child, type Settings, type Station } from "../api";
import { StationArt } from "../art/station";
import { Coin } from "../art/treasure";
import { Creature } from "../components/Creature";
import { Button, IconButton, InlineError, StationStatus, Stepper, Toggle } from "../components/ui";
import { useLive, useStationActive } from "../live";
import { PinField } from "../parent";
import { go } from "../router";
import { KidFields } from "./KidSheet";

const STEPS = ["splash", "germs", "scrub", "earn", "parent", "kid", "station", "camera", "routines", "done"] as const;
const SETUP_FROM = STEPS.indexOf("parent");
const KEY = "scrubble.onboarding.step";

function remembered(): number {
  try { return Math.min(Math.max(Number(localStorage.getItem(KEY)) || 0, 0), STEPS.length - 1); } catch { return 0; }
}
function remember(step: number) {
  try { localStorage.setItem(KEY, String(step)); } catch { /* private mode: the tour just starts over */ }
}

function Story({ art, title, children }: { art: ReactNode; title: string; children: ReactNode }) {
  return <div className="story"><div className="stage">{art}</div><h1 className="h1">{title}</h1><p className="lede">{children}</p></div>;
}

export default function Onboarding() {
  const [step, setStep] = useState(remembered);
  const { data: settings } = useApi<Settings>("/api/v1/app/settings");
  const { data: kids } = useApi<Child[]>("/api/v1/app/children");
  const { data: station } = useApi<Station>("/api/v1/app/station");
  const { refresh, connected } = useLive();
  const live = useStationActive();
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [parentName, setParentName] = useState("");
  const [pin, setPin] = useState("");
  const [name, setName] = useState("");
  const [buddy, setBuddy] = useState("scrubby");
  const [age, setAge] = useState<AgeBand>("5-6");
  const [goal, setGoal] = useState(6);
  useEffect(() => { if (settings) { setParentName((n) => n || settings.parent_name); setGoal(settings.daily_goal); } }, [settings]);
  useEffect(() => remember(step), [step]);

  const kid = kids?.find((k) => k.active) ?? kids?.[0];
  const id = STEPS[step];
  const next = () => { setError(null); setStep((s) => Math.min(s + 1, STEPS.length - 1)); };
  const back = () => { setError(null); setStep((s) => Math.max(s - 1, 0)); };
  /** Save, then move on. A failed save keeps the step open with the reason. */
  const saveThen = (work: () => Promise<unknown>) => {
    setBusy(true);
    work().then(() => { refresh(); next(); }, setError).finally(() => setBusy(false));
  };
  const finish = () => saveThen(() => send("PUT", "/api/v1/app/settings", { onboarded: true }).then(() => { remember(0); go("/kid", true); }));

  let body: ReactNode;
  let action: ReactNode;
  switch (id) {
    case "splash":
      body = (
        <div className="story splash">
          <div className="stage">
            <Creature id="smudge" size={62} className="peek p1" /><Creature id="gunky" size={62} className="peek p2" />
            <Creature id="prickle" size={62} className="peek p3" /><Creature id="sneezel" size={62} className="peek p4" />
            <Creature id="bubbles" size={190} bob label="Bubbles, the soap-bubble hero" />
          </div>
          <h1 className="wordmark">Scrubble</h1>
          <p className="lede">Wash. Fight. Win.</p>
        </div>
      );
      action = <Button wide onClick={next}>Start</Button>;
      break;
    case "germs":
      body = <Story title="Germs are sneaky!" art={<div className="crew">{["sneezel", "prickle", "gunky", "smudge"].map((g) => <Creature key={g} id={g} size={104} />)}</div>}>
        In this game they hide on palms, between fingers and around thumbs. Only a super scrub can zap them.</Story>;
      action = <Button wide onClick={next}>Next</Button>;
      break;
    case "scrub":
      body = <Story title="Scrub to zap them" art={<div className="station-art"><StationArt live /></div>}>
        The station at your sink watches how hands scrub and lights up germs on them. Each one pops as its spot gets a good scrub.
        <span className="tags" style={{ justifyContent: "center", marginTop: 10 }}>{["Palms", "Fingers", "Thumbs", "Nails"].map((z) => <span key={z} className="tag">{z}</span>)}</span></Story>;
      action = <Button wide onClick={next}>Next</Button>;
      break;
    case "earn":
      body = <Story title="Earn points, build habits" art={<div className="earn-art"><Creature id="gunky" size={120} /><span className="earn-pill"><Coin size={26} />+82 pts</span></div>}>
        Kids earn points for great scrubs. Grown-ups see progress and the spots that keep getting missed.</Story>;
      action = <Button wide onClick={next}>Get started</Button>;
      break;
    case "parent":
      body = (
        <div className="setup">
          <h1 className="h1">Hi grown-up!</h1>
          <p className="lede">Two quick things so the app knows who is in charge.</p>
          <label className="field"><span>Your name</span><input className="input" value={parentName} maxLength={40} onChange={(e) => setParentName(e.target.value)} placeholder="Sam" autoComplete="given-name" /></label>
          <PinField value={pin} onChange={setPin} label="Parent PIN, 4 to 8 digits (optional)" />
          <p className="muted">The PIN keeps kids out of rewards and settings. There are no online accounts: this app runs on your station's laptop and stays on your home network.</p>
        </div>
      );
      action = <Button wide disabled={busy || !parentName.trim() || (pin.length > 0 && pin.length < 4)}
        onClick={() => saveThen(async () => {
          await send("PUT", "/api/v1/app/settings", { parent_name: parentName.trim() });
          if (pin) await send("PUT", "/api/v1/app/parent/pin", { pin });
        })}>Continue</Button>;
      break;
    case "kid":
      body = (
        <div className="setup">
          <h1 className="h1">{kid ? `${kid.name} is ready` : "Who's busting germs?"}</h1>
          {kid ? <div className="kid-ready"><Creature id={kid.buddy} size={120} bob /><p className="lede">Age {kid.age_band}. You can add brothers and sisters later in Settings.</p></div>
            : <><p className="lede">A nickname is enough. No birthday, no photo.</p><KidFields {...{ name, setName, buddy, setBuddy, age, setAge }} /></>}
        </div>
      );
      action = kid ? <Button wide onClick={next}>Continue</Button>
        : <Button wide disabled={busy || !name.trim()} onClick={() => saveThen(() => send("POST", "/api/v1/app/children", { name: name.trim(), buddy, age_band: age }))}>Continue</Button>;
      break;
    case "station":
      body = (
        <div className="setup">
          <h1 className="h1">Your sink station</h1>
          <div className="station-art small"><StationArt live={live} /></div>
          <div className={`card check ${connected ? "ok" : ""}`}><b>{connected ? "This app is connected to the station laptop" : "Not connected to the station laptop"}</b>
            <p>{connected ? "You opened Scrubble from the laptop that runs the station, so there is nothing to pair." : "Open this app from the address the station laptop shows, on the same Wi-Fi."}</p></div>
          <p className="muted">Pairing by code is not built yet. The laptop, camera and projector are set up from docs/HARDWARE_DAY_RUNBOOK.md.</p>
        </div>
      );
      action = <Button wide onClick={next}>Continue</Button>;
      break;
    case "camera":
      body = (
        <div className="setup">
          <h1 className="h1">Camera check</h1>
          <div className="check-line"><StationStatus /><span className="muted">{live ? "The wash software is running and sending updates." : "Start the wash software on the laptop to see it go live here."}</span></div>
          <ul className="checklist">
            <li>Projector about 60 cm above the hands</li>
            <li>Good, even light over the sink</li>
            <li>Both hands inside the lit area</li>
          </ul>
          <div className="card check ok"><b>The picture stays on the station</b><p>The camera picture is analysed on the laptop. This app only receives each wash's times and score{station?.last_wash ? "" : " once a wash is done"}.</p></div>
          <p className="muted">The live camera view is on the laptop screen, not here.</p>
        </div>
      );
      action = <Button wide onClick={next}>Looks good</Button>;
      break;
    case "routines":
      body = (
        <div className="setup">
          <h1 className="h1">When should {kid?.name ?? "your kid"} wash?</h1>
          <div className="card"><div className="rows">
            {settings?.routines.map((r) => (
              <div className="row" key={r.id}><span className="grow name">{r.name}</span>
                <Toggle on={r.on} label={r.name} onChange={(on) => send("PUT", "/api/v1/app/settings", { routines: settings.routines.map((x) => (x.id === r.id ? { ...x, on } : x)) }).then(refresh, setError)} /></div>
            ))}
          </div></div>
          <div className="card goal-row"><span className="grow"><b>Daily goal</b><small>washes a day</small></span><Stepper value={goal} min={1} max={12} label="daily goal" onChange={setGoal} /></div>
        </div>
      );
      action = <Button wide disabled={busy} onClick={() => saveThen(() => send("PUT", "/api/v1/app/settings", { daily_goal: goal }))}>Finish setup</Button>;
      break;
    case "done":
      body = <Story title={`Ready to bust some germs${kid ? `, ${kid.name}` : ""}!`} art={<Creature id={kid?.buddy ?? "bubbles"} size={190} bob />}>
        Wash at the sink and your stars show up here the moment you finish. Grown-ups: switch to the grown-up view at the top for the numbers.</Story>;
      action = <Button wide tone="gold" disabled={busy} onClick={finish}>Start playing</Button>;
      break;
  }

  const inSetup = step >= SETUP_FROM && id !== "done";
  return (
    <div className={`page onboarding step-${id}`}>
      <header className="ob-top">
        {step > 0 ? <IconButton icon="back" label="Back" onClick={back} /> : <span />}
        {inSetup ? <span className="muted num">Step {step - SETUP_FROM + 1} of {STEPS.length - 1 - SETUP_FROM}</span>
          : <div className="dots" aria-hidden="true">{[1, 2, 3].map((i) => <i key={i} className={step === i ? "on" : ""} />)}</div>}
        {step < SETUP_FROM ? <button type="button" className="link" onClick={() => setStep(SETUP_FROM)}>Skip intro</button> : <span />}
      </header>
      <div className="ob-body">{body}</div>
      <footer className="ob-foot">{error && <InlineError error={error} />}{action}</footer>
    </div>
  );
}
