// Forms shared by onboarding and settings: the kid's profile and the wash routines.
import { useState } from "react";
import type { Child, Settings } from "../api";
import { Germ } from "./germs";
import { Icon, Stepper, Toggle } from "./ui";

const BUDDIES = ["scrubby", "gunky", "sneezel", "prickle", "smudge"];
const AGES = ["3-4", "5-6", "7-8", "9+"];

export function KidForm({ kid, onChange }: { kid: Child; onChange: (k: Child) => void }) {
  return (
    <>
      <div className="field">
        <span>Pick a buddy</span>
        <div className="buddies">
          {BUDDIES.map((b) => (
            <button key={b} className="buddy" aria-pressed={kid.buddy === b} aria-label={b} onClick={() => onChange({ ...kid, buddy: b })}>
              <Germ id={b} size={52} />
            </button>
          ))}
        </div>
      </div>
      <label className="field">
        <span>Kid's name</span>
        <input value={kid.name} maxLength={64} placeholder="Mia" autoComplete="off" onChange={(e) => onChange({ ...kid, name: e.target.value })} />
      </label>
      <div className="field">
        <span>Age</span>
        <div className="chip-row">
          {AGES.map((a) => <button key={a} className="chip" aria-pressed={kid.age_band === a} onClick={() => onChange({ ...kid, age_band: a })}>{a.replace("-", "–")}</button>)}
        </div>
        <span className="faint" style={{ fontWeight: 400 }}>Saved for later: age will set scrub time and game difficulty.</span>
      </div>
    </>
  );
}

type Routine = Settings["routines"][number];

export function RoutineList({ routines, onChange }: { routines: Routine[]; onChange: (r: Routine[]) => void }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [time, setTime] = useState("");
  const set = (i: number, patch: Partial<Routine>) => onChange(routines.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const add = () => {
    onChange([...routines, { id: `custom_${Date.now()}`, name: name.trim(), detail: time ? "Daily" : "Manual start", time: time || null, on: true }]);
    setAdding(false); setName(""); setTime("");
  };
  return (
    <div>
      {routines.map((r, i) => (
        <div className="row" key={r.id}>
          <span className="row-icon"><Icon name="clock" size={18} /></span>
          <div className="grow">
            <div className="title">{r.name}</div>
            <div className="faint">{r.time ? `${fmt(r.time)} · ${r.detail}` : r.detail}</div>
          </div>
          <Toggle on={r.on} label={r.name} onChange={(on) => set(i, { on })} />
        </div>
      ))}
      {adding ? (
        <div className="card" style={{ marginTop: 8, boxShadow: "none", background: "#f6f9fc" }}>
          <label className="field"><span>Name</span><input value={name} placeholder="Before bedtime" maxLength={40} onChange={(e) => setName(e.target.value)} /></label>
          <label className="field"><span>Time (optional)</span><input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></label>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn outline" onClick={() => setAdding(false)}>Cancel</button>
            <button className="btn" disabled={!name.trim()} onClick={add}>Add</button>
          </div>
        </div>
      ) : (
        <button className="link-btn" style={{ paddingLeft: 0 }} onClick={() => setAdding(true)}>+ Add routine</button>
      )}
    </div>
  );
}

export function GoalRow({ goal, onChange }: { goal: number; onChange: (g: number) => void }) {
  return (
    <div className="row">
      <div className="grow">
        <div className="title">Daily goal</div>
        <div className="faint">Washes a day. Zaps stop after this many.</div>
      </div>
      <Stepper value={goal} min={1} max={12} onChange={onChange} label="Daily goal" />
    </div>
  );
}

function fmt(t: string): string {
  const [h, m] = t.split(":").map(Number);
  return new Date(2000, 0, 1, h, m).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
