import { useEffect, useState } from "react";
import { send, useApi, type ApiError, type Routine, type Settings } from "../api";
import { Icon } from "../components/icons";
import { GameButton, InlineError, Pending, Sheet, Stepper, Toggle, TopBar } from "../components/ui";
import "./Routines.css";

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
const pretty = (t: string) => new Date(`2000-01-01T${t}:00`).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
const slug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 32) || "routine";

function RoutineSheet({ routine, onSave, onRemove, onClose }: { routine: Routine | null; onSave: (r: Routine) => void; onRemove?: () => void; onClose: () => void }) {
  const [name, setName] = useState(routine?.name ?? "");
  const [time, setTime] = useState(routine?.time ?? "");
  const valid = name.trim().length > 0 && (time === "" || HHMM.test(time));
  return (
    <Sheet title={routine ? "Edit routine" : "New routine"} lede="A routine names the washes that happen around its time." onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (valid) onSave({ id: routine?.id ?? `${slug(name)}_${Date.now().toString(36)}`, name: name.trim(), detail: time ? "Daily" : "Any time", time: time || null, on: routine?.on ?? true }); }}>
        <label className="field"><span>Name</span><input className="input" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} placeholder="After school" required /></label>
        <label className="field"><span>Usual time (optional)</span><input className="input" type="time" value={time} onChange={(e) => setTime(e.target.value)} /></label>
        <div className="actions">
          <GameButton type="submit" wide disabled={!valid}>Save</GameButton>
          {onRemove && <GameButton tone="danger" wide icon="trash" onClick={onRemove}>Remove routine</GameButton>}
        </div>
      </form>
    </Sheet>
  );
}

export default function Routines() {
  const { data, error, reload } = useApi<Settings>("/api/v1/app/settings");
  const [s, setS] = useState<Settings | null>(null);
  const [failed, setFailed] = useState<ApiError | null>(null);
  const [edit, setEdit] = useState<Routine | "new" | null>(null);
  useEffect(() => { if (data) setS(data); }, [data]);

  /** Show the change at once, save it, and fall back to the server's copy if saving fails. */
  const save = (changes: Partial<Settings>) => {
    if (!s) return;
    setS({ ...s, ...changes });
    setFailed(null);
    send<Settings>("PUT", "/api/v1/app/settings", changes).then(setS, (e: ApiError) => { setFailed(e); reload(); });
  };
  const setRoutines = (routines: Routine[]) => save({ routines });

  return (
    <div className="page routines">
      <TopBar title="Routines" back="/settings" />
      {!s ? <Pending error={error} retry={reload} /> : (
        <>
          {failed && <InlineError error={failed} />}
          <section className="panel">
            <div className="rows">
              {s.routines.map((r) => (
                <div className="row" key={r.id}>
                  <button type="button" className="row grow routine-open" onClick={() => setEdit(r)} aria-label={`Edit ${r.name}`}>
                    <span className="glyph"><Icon name="clock" size={22} /></span>
                    <span className="grow"><span className="name">{r.name}</span><span className="sub">{r.time ? `Around ${pretty(r.time)}` : "Any time of day"}</span></span>
                  </button>
                  <Toggle on={r.on} label={`${r.name} routine`} onChange={(on) => setRoutines(s.routines.map((x) => (x.id === r.id ? { ...x, on } : x)))} />
                </div>
              ))}
            </div>
            <button type="button" className="linkish add" onClick={() => setEdit("new")}><Icon name="plus" size={18} />Add routine</button>
          </section>
          <p className="faint note">A wash within an hour of a routine's time is named after it. The station does not know why a child is washing, so nothing here is detected automatically.</p>

          <section className="panel goal">
            <div className="grow"><div className="name">Daily goal</div><div className="sub">Washes a day that earn points and count for the ring</div></div>
            <Stepper value={s.daily_goal} min={1} max={12} label="daily goal" onChange={(daily_goal) => save({ daily_goal })} />
          </section>

          <h2 className="caps">Reminders</h2>
          <section className="panel deep">
            <div className="rows">
              <div className="row"><span className="grow"><span className="name">Station reminder</span><span className="sub">Not available yet: the station cannot show reminders</span></span><Toggle on={false} disabled label="Station reminder (not available)" onChange={() => {}} /></div>
              <div className="row"><span className="grow"><span className="name">Tell me if a wash is skipped</span><span className="sub">Not available yet: this app cannot send notifications</span></span><Toggle on={false} disabled label="Skipped wash alert (not available)" onChange={() => {}} /></div>
            </div>
          </section>
        </>
      )}
      {edit && s && (
        <RoutineSheet routine={edit === "new" ? null : edit} onClose={() => setEdit(null)}
          onSave={(r) => { setRoutines(edit === "new" ? [...s.routines, r] : s.routines.map((x) => (x.id === r.id ? r : x))); setEdit(null); }}
          onRemove={edit === "new" ? undefined : () => { setRoutines(s.routines.filter((x) => x.id !== edit.id)); setEdit(null); }} />
      )}
    </div>
  );
}
