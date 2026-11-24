import { useEffect, useState, type FormEvent } from "react";
import { send, setParentToken, useApi, type ApiError, type Child, type ParentState, type Settings as S, type Station } from "../api";
import { Creature } from "../components/Creature";
import { Icon, type IconName } from "../components/icons";
import { GameButton, InlineError, Pending, Sheet, TopBar } from "../components/ui";
import { useLive } from "../live";
import { PinField, useParentGate } from "../parent";
import { go, Link } from "../router";
import { KidSheet } from "./KidSheet";
import "./Routines.css";
import "./Settings.css";

function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function Fact({ icon, name, value, sub }: { icon: IconName; name: string; value?: string; sub?: string }) {
  return (
    <div className="row">
      <span className="glyph"><Icon name={icon} size={22} /></span>
      <span className="grow"><span className="name">{name}</span>{sub && <span className="sub">{sub}</span>}</span>
      {value && <span className="value">{value}</span>}
    </div>
  );
}

function PinSheet({ state, onClose }: { state: ParentState; onClose: () => void }) {
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const ok = pin.length >= 4 && pin === again;
  const save = (e: FormEvent) => {
    e.preventDefault();
    if (ok) send<{ token: string }>("PUT", "/api/v1/app/parent/pin", { pin }).then((r) => { setParentToken(r.token); onClose(); }, setError);
  };
  return (
    <Sheet title={state.pin_set ? "Change parent PIN" : "Set a parent PIN"} onClose={onClose}
      lede="Rewards, approvals, removing a child and deleting history will ask for it. It keeps kids out of the grown-up screens; it is not an account password.">
      <form onSubmit={save}>
        <PinField value={pin} onChange={setPin} label="New PIN (4 to 8 digits)" autoFocus />
        <PinField value={again} onChange={setAgain} label="Type it again" />
        {again.length >= 4 && !ok && <p className="inline-error" role="alert">The two PINs are different.</p>}
        {error && <InlineError error={error} />}
        <div className="actions">
          <GameButton type="submit" wide disabled={!ok}>Save PIN</GameButton>
          {state.pin_set && <GameButton tone="quiet" wide onClick={() => send("DELETE", "/api/v1/app/parent/pin").then(() => { setParentToken(null); onClose(); }, setError)}>Remove the PIN</GameButton>}
        </div>
      </form>
    </Sheet>
  );
}

export default function Settings() {
  const { data: s, error, reload } = useApi<S>("/api/v1/app/settings");
  const { data: st } = useApi<Station>("/api/v1/app/station");
  const { data: kids } = useApi<Child[]>("/api/v1/app/children");
  const { data: parent, reload: reloadParent } = useApi<ParentState>("/api/v1/app/parent");
  const { refresh, connected } = useLive();
  const gate = useParentGate();
  const [sheet, setSheet] = useState<"pin" | "delete" | "kid" | Child | { remove: Child } | null>(null);
  const [failed, setFailed] = useState<ApiError | null>(null);
  const [name, setName] = useState("");
  useEffect(() => { if (s) setName(s.parent_name); }, [s]);
  const active = kids?.find((k) => k.active);
  const guarded = async (next: typeof sheet) => { if (await gate.ask()) setSheet(next); };
  const close = () => { setSheet(null); reloadParent(); };
  const done = () => { setSheet(null); refresh(); };

  return (
    <div className="page settings">
      <TopBar title="Settings" />
      {!s ? <Pending error={error} retry={reload} blocks={3} /> : (
        <>
          {failed && <InlineError error={failed} />}
          <section className={`panel station ${st?.online ? "on" : ""}`}>
            <span className="glyph big"><Icon name="station" size={30} /></span>
            <div className="grow">
              <div className="name">Sink station</div>
              <div className="sub">
                {!connected ? "This app is offline" : st?.online ? "Online: the wash software is running" : st?.last_seen ? `Idle. Last heard from ${ago(st.last_seen)}` : "Not heard from since the app's server started"}
              </div>
              <div className="sub">Last wash received: {ago(st?.last_wash ?? null)}</div>
            </div>
            <span className={`sync ${!connected ? "off" : st?.online ? "live" : ""}`}><i />{!connected ? "Offline" : st?.online ? "Online" : "Idle"}</span>
          </section>

          <h2 className="caps">Game</h2>
          <section className="panel"><div className="rows">
            <Fact icon="clock" name="Scrub timer" value={st?.rules ? `${st.rules.scrub_goal_s} sec` : "–"} sub="Set on the station. Shown from the latest real wash." />
            <Fact icon="hand" name="Step time" value={st?.rules ? `${st.rules.step_min_s} sec` : "–"} sub="Scrubbing a zone needs to count as washed" />
            <Fact icon="sparkle" name="Recognizer" value={st?.rules?.model?.version ? `v${st.rules.model.version}` : "–"} sub="The motion model that produced the latest wash" />
            <Link to="/routines" className="row"><span className="glyph"><Icon name="bell" size={22} /></span><span className="grow"><span className="name">Routines & daily goal</span><span className="sub">{s.routines.filter((r) => r.on).length} on · goal {s.daily_goal} a day</span></span><Icon name="chevron" size={20} /></Link>
          </div></section>
          <p className="faint note">Difficulty by age, sounds and music are not adjustable from the app yet: the station does not read settings from it.</p>

          <h2 className="caps">Family</h2>
          <section className="panel"><div className="rows">
            <form className="row" onSubmit={(e) => { e.preventDefault(); send("PUT", "/api/v1/app/settings", { parent_name: name.trim() }).then(refresh, setFailed); }}>
              <span className="glyph"><Icon name="kid" size={22} /></span>
              <label className="grow"><span className="sr-only">Your name</span><input className="input slim" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} placeholder="Your name" /></label>
              {name.trim() !== s.parent_name && <GameButton small type="submit">Save</GameButton>}
            </form>
            {kids?.map((k) => (
              <div className="row" key={k.id}>
                <Creature id={k.buddy} size={40} />
                <span className="grow"><span className="name">{k.name}</span><span className="sub">Age {k.age_band}{k.active ? " · showing now" : ""}</span></span>
                <button type="button" className="mini" aria-label={`Edit ${k.name}`} onClick={() => setSheet(k)}><Icon name="pencil" size={20} /></button>
                <button type="button" className="mini" aria-label={`Remove ${k.name}`} onClick={() => guarded({ remove: k })}><Icon name="trash" size={20} /></button>
              </div>
            ))}
            <button type="button" className="row" onClick={() => setSheet("kid")}><span className="glyph"><Icon name="plus" size={22} /></span><span className="grow name">Add a kid</span></button>
            <button type="button" className="row" onClick={() => guarded("pin")}><span className="glyph"><Icon name="lock" size={22} /></span><span className="grow"><span className="name">Parent PIN</span><span className="sub">{parent?.pin_set ? "On. Grown-up actions ask for it" : "Off. Anyone with this app can manage rewards"}</span></span><Icon name="chevron" size={20} /></button>
          </div></section>

          <h2 className="caps">Privacy</h2>
          <section className="panel deep privacy">
            <span className="glyph"><Icon name="shield" size={22} /></span>
            <div>
              <p><b>Only wash results reach this app.</b> The camera picture is analysed on the station's laptop. What is saved per wash: seconds per scrubbing step, the score, and quality numbers. No picture, no video, no hand outline.</p>
              <p className="faint">A child is a nickname, an age band and a buddy. The station never recognizes who is washing: you pick the child on Home. On the station laptop itself, a run started with --save-results also keeps hand-point files in its runs folder, and video recording is a separate setting that is off by default. Neither is sent to this app.</p>
            </div>
          </section>
          <section className="panel"><div className="rows">
            <button type="button" className="row danger" onClick={() => guarded("delete")}><span className="glyph"><Icon name="trash" size={22} /></span><span className="grow"><span className="name">Delete {active ? `${active.name}'s` : ""} wash history</span><span className="sub">Removes washes and what they earned</span></span><Icon name="chevron" size={20} /></button>
            {parent?.pin_set && <button type="button" className="row" onClick={() => { gate.lock(); reloadParent(); go("/"); }}><span className="glyph"><Icon name="out" size={22} /></span><span className="grow"><span className="name">Lock grown-up screens</span><span className="sub">Hand the tablet back to a kid</span></span></button>}
          </div></section>
          <p className="faint note">Scrubble {st?.version ? `server ${st.version}` : ""} · There are no accounts yet: the app is served by the station laptop to devices on its network.</p>
        </>
      )}

      {sheet === "pin" && parent && <PinSheet state={parent} onClose={close} />}
      {sheet === "kid" && <KidSheet onClose={() => setSheet(null)} />}
      {sheet && typeof sheet === "object" && "id" in sheet && <KidSheet kid={sheet} onClose={() => setSheet(null)} />}
      {sheet && typeof sheet === "object" && "remove" in sheet && (
        <Sheet title={`Remove ${sheet.remove.name}?`} lede={`This deletes ${sheet.remove.name}'s washes, points, germs and reward requests. It cannot be undone.`} onClose={() => setSheet(null)}>
          <div className="actions">
            <GameButton tone="danger" wide icon="trash" onClick={() => send("DELETE", `/api/v1/app/children/${sheet.remove.id}`).then(done, (e: ApiError) => { setFailed(e); setSheet(null); })}>Remove {sheet.remove.name}</GameButton>
            <GameButton tone="quiet" wide onClick={() => setSheet(null)}>Keep</GameButton>
          </div>
        </Sheet>
      )}
      {sheet === "delete" && (
        <Sheet title="Delete wash history?" onClose={() => setSheet(null)}
          lede={<>Every wash {active ? `of ${active.name}` : ""} is deleted. Points, zaps, germs, badges, the map and reward requests are worked out from washes, so they reset to zero too. Rewards you set up and the child's profile stay. This cannot be undone.</>}>
          <div className="actions">
            <GameButton tone="danger" wide icon="trash" onClick={() => send("DELETE", "/api/v1/app/washes").then(done, (e: ApiError) => { setFailed(e); setSheet(null); })}>Delete history</GameButton>
            <GameButton tone="quiet" wide onClick={() => setSheet(null)}>Keep it</GameButton>
          </div>
        </Sheet>
      )}
    </div>
  );
}
