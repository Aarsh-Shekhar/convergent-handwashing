import { useEffect, useState, type FormEvent } from "react";
import { send, setParentToken, useApi, type ApiError, type Child, type ParentState, type Routine, type Settings as S } from "../../api";
import { Creature } from "../../components/Creature";
import { Icon } from "../../components/icons";
import { Button, InlineError, PageHead, Pending, Sheet, Stepper, Toggle } from "../../components/ui";
import { useLive } from "../../live";
import { PinField, useParentGate } from "../../parent";
import { go } from "../../router";
import { KidSheet } from "../KidSheet";
import { pretty, RoutineSheet } from "./RoutineSheet";

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
        {again.length >= 4 && !ok && <p className="alert" role="alert">The two PINs are different.</p>}
        {error && <InlineError error={error} />}
        <div className="actions">
          <Button type="submit" wide disabled={!ok}>Save PIN</Button>
          {state.pin_set && <Button tone="quiet" wide onClick={() => send("DELETE", "/api/v1/app/parent/pin").then(() => { setParentToken(null); onClose(); }, setError)}>Remove the PIN</Button>}
        </div>
      </form>
    </Sheet>
  );
}

export default function Settings() {
  const { data: s, error, reload } = useApi<S>("/api/v1/app/settings");
  const { data: kids } = useApi<Child[]>("/api/v1/app/children");
  const { data: parent, reload: reloadParent } = useApi<ParentState>("/api/v1/app/parent");
  const { refresh } = useLive();
  const gate = useParentGate();
  const [sheet, setSheet] = useState<"pin" | "delete" | "kid" | Child | { remove: Child } | { routine: Routine | null } | null>(null);
  const [failed, setFailed] = useState<ApiError | null>(null);
  const [name, setName] = useState("");
  useEffect(() => { if (s) setName(s.parent_name); }, [s]);
  const active = kids?.find((k) => k.active);
  const guarded = async (next: typeof sheet) => { if (await gate.ask()) setSheet(next); };
  const close = () => { setSheet(null); reloadParent(); };
  const done = () => { setSheet(null); refresh(); };
  const save = (changes: Partial<S>) => send("PUT", "/api/v1/app/settings", changes).then(refresh, (e: ApiError) => { setFailed(e); reload(); });
  const setRoutines = (routines: Routine[]) => save({ routines });

  return (
    <div className="page">
      <PageHead title="Settings" sub="Family, routines and privacy" />
      {!s ? <Pending error={error} retry={reload} blocks={3} /> : (
        <div className="grid2">
          <div className="stack">
            {failed && <InlineError error={failed} />}
            <section className="card">
              <h2 className="h2">Family</h2>
              <div className="rows">
                <form className="row" onSubmit={(e) => { e.preventDefault(); save({ parent_name: name.trim() }); }}>
                  <label className="grow"><span className="sr-only">Your name</span><input className="input" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} placeholder="Your name" /></label>
                  {name.trim() !== s.parent_name && <Button small type="submit">Save</Button>}
                </form>
                {kids?.map((k) => (
                  <div className="row" key={k.id}>
                    <Creature id={k.buddy} size={36} />
                    <span className="grow"><span className="name">{k.name}</span><span className="sub">Age {k.age_band}{k.active ? ", showing now" : ""}</span></span>
                    <button type="button" className="icon-btn" aria-label={`Edit ${k.name}`} onClick={() => setSheet(k)}><Icon name="pencil" size={18} /></button>
                    <button type="button" className="icon-btn" aria-label={`Remove ${k.name}`} onClick={() => guarded({ remove: k })}><Icon name="trash" size={18} /></button>
                  </div>
                ))}
                <button type="button" className="row" onClick={() => setSheet("kid")}><span className="glyph"><Icon name="plus" size={18} /></span><span className="grow name">Add a kid</span></button>
                <button type="button" className="row" onClick={() => guarded("pin")}><span className="glyph"><Icon name="lock" size={18} /></span><span className="grow"><span className="name">Parent PIN</span><span className="sub">{parent?.pin_set ? "On. The grown-up view and its actions ask for it" : "Off. Anyone with this app can open the grown-up view"}</span></span><Icon name="chevron" size={18} /></button>
                {parent?.pin_set && <button type="button" className="row" onClick={() => { gate.lock(); reloadParent(); go("/kid"); }}><span className="glyph"><Icon name="out" size={18} /></span><span className="grow"><span className="name">Lock and go to the kid view</span><span className="sub">Hand the device back to a kid</span></span></button>}
              </div>
            </section>

            <section className="card">
              <h2 className="h2">Routines</h2>
              <div className="rows">
                {s.routines.map((r) => (
                  <div className="row" key={r.id}>
                    <button type="button" className="row grow" style={{ padding: 0, minHeight: 44, border: 0 }} onClick={() => setSheet({ routine: r })} aria-label={`Edit ${r.name}`}>
                      <span className="grow"><span className="name">{r.name}</span><span className="sub">{r.time ? `Around ${pretty(r.time)}` : "Any time of day"}</span></span>
                    </button>
                    <Toggle on={r.on} label={`${r.name} routine`} onChange={(on) => setRoutines(s.routines.map((x) => (x.id === r.id ? { ...x, on } : x)))} />
                  </div>
                ))}
                <button type="button" className="row" onClick={() => setSheet({ routine: null })}><span className="glyph"><Icon name="plus" size={18} /></span><span className="grow name">Add routine</span></button>
                <div className="row"><span className="grow"><span className="name">Daily goal</span><span className="sub">Washes a day that earn points</span></span><Stepper value={s.daily_goal} min={1} max={12} label="daily goal" onChange={(daily_goal) => save({ daily_goal })} /></div>
              </div>
              <p className="note">A wash within an hour of a routine's time is named after it. The station does not know why a child is washing.</p>
            </section>
          </div>

          <div className="stack">
            <section className="card">
              <h2 className="h2">Privacy</h2>
              <p><b>Only wash results reach this app.</b> The camera picture is analysed on the station's laptop. Per wash the app keeps seconds per scrubbing step, the score and a few quality numbers. No picture, no video, no hand outline.</p>
              <p className="note">A child is a nickname, an age band and a buddy. The station never recognizes who is washing: you pick the child in the app. On the station laptop itself, a run started with --save-results also keeps hand-point files in its runs folder, and video recording is a separate setting that is off by default. Neither is sent to this app.</p>
              <div className="rows" style={{ marginTop: 8 }}>
                <button type="button" className="row" onClick={() => go("/station")}><span className="grow name">See exactly what is sent</span><Icon name="chevron" size={18} /></button>
                <button type="button" className="row" onClick={() => guarded("delete")}><span className="grow"><span className="name" style={{ color: "var(--bad)" }}>Delete {active ? `${active.name}'s` : ""} wash history</span><span className="sub">Removes washes and what they earned</span></span><Icon name="chevron" size={18} /></button>
              </div>
            </section>
            <section className="card">
              <h2 className="h2">Not available yet</h2>
              <div className="rows">
                <div className="row"><span className="grow"><span className="name">Reminders at the station</span><span className="sub">The station cannot show reminders</span></span><Toggle on={false} disabled label="Station reminder (not available)" onChange={() => {}} /></div>
                <div className="row"><span className="grow"><span className="name">Tell me if a wash is skipped</span><span className="sub">This app cannot send notifications</span></span><Toggle on={false} disabled label="Skipped wash alert (not available)" onChange={() => {}} /></div>
                <div className="row"><span className="grow"><span className="name">Timer, difficulty, sounds</span><span className="sub">Set on the station laptop. See Station for the current values</span></span></div>
              </div>
              <p className="note">There are no accounts yet: the app is served by the station laptop to devices on its network.</p>
            </section>
          </div>
        </div>
      )}
      {sheet === "pin" && parent && <PinSheet state={parent} onClose={close} />}
      {sheet === "kid" && <KidSheet onClose={() => setSheet(null)} />}
      {sheet && typeof sheet === "object" && "id" in sheet && <KidSheet kid={sheet} onClose={() => setSheet(null)} />}
      {sheet && typeof sheet === "object" && "remove" in sheet && (
        <Sheet title={`Remove ${sheet.remove.name}?`} lede={`This deletes ${sheet.remove.name}'s washes, points, germs and reward requests. It cannot be undone.`} onClose={() => setSheet(null)}>
          <div className="actions">
            <Button tone="danger" wide icon="trash" onClick={() => send("DELETE", `/api/v1/app/children/${sheet.remove.id}`).then(done, (e: ApiError) => { setFailed(e); setSheet(null); })}>Remove {sheet.remove.name}</Button>
            <Button tone="quiet" wide onClick={() => setSheet(null)}>Keep</Button>
          </div>
        </Sheet>
      )}
      {sheet && typeof sheet === "object" && "routine" in sheet && s && (
        <RoutineSheet routine={sheet.routine} onClose={() => setSheet(null)}
          onSave={(r) => { setRoutines(sheet.routine ? s.routines.map((x) => (x.id === r.id ? r : x)) : [...s.routines, r]); setSheet(null); }}
          onRemove={sheet.routine ? () => { setRoutines(s.routines.filter((x) => x.id !== sheet.routine!.id)); setSheet(null); } : undefined} />
      )}
      {sheet === "delete" && (
        <Sheet title="Delete wash history?" onClose={() => setSheet(null)}
          lede={<>Every wash {active ? `of ${active.name}` : ""} is deleted. Points, zaps, germs, badges, the map and reward requests are worked out from washes, so they reset to zero too. Rewards you set up and the child's profile stay. This cannot be undone.</>}>
          <div className="actions">
            <Button tone="danger" wide icon="trash" onClick={() => send("DELETE", "/api/v1/app/washes").then(done, (e: ApiError) => { setFailed(e); setSheet(null); })}>Delete history</Button>
            <Button tone="quiet" wide onClick={() => setSheet(null)}>Keep it</Button>
          </div>
        </Sheet>
      )}
    </div>
  );
}
