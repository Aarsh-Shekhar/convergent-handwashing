// Add or edit a child: a nickname, a buddy and an age band. Nothing else is asked for or stored.
import { useState, type FormEvent } from "react";
import { send, type AgeBand, type ApiError, type Child } from "../api";
import { BUDDIES, Creature } from "../components/Creature";
import { Button, InlineError, Sheet } from "../components/ui";
import { useLive } from "../live";

export const AGES: AgeBand[] = ["3-4", "5-6", "7-8", "9+"];

export function KidFields({ name, setName, buddy, setBuddy, age, setAge }: {
  name: string; setName: (v: string) => void; buddy: string; setBuddy: (v: string) => void; age: AgeBand; setAge: (v: AgeBand) => void;
}) {
  return (
    <>
      <div className="field">
        <span id="buddy-label">Pick a buddy</span>
        <div className="buddies" role="radiogroup" aria-labelledby="buddy-label">
          {BUDDIES.map(([id, colour]) => (
            <button key={id} type="button" role="radio" aria-checked={buddy === id} aria-label={`${colour} Bubbles`} className="buddy-pick" onClick={() => setBuddy(id)}>
              <Creature id={id} size={54} />
            </button>
          ))}
        </div>
      </div>
      <label className="field">
        <span>Kid's nickname</span>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={24} placeholder="Mia" autoComplete="off" required />
      </label>
      <div className="field">
        <span id="age-label">Age</span>
        <div className="chips" role="radiogroup" aria-labelledby="age-label">
          {AGES.map((a) => <button key={a} type="button" role="radio" aria-checked={age === a} className="chip" onClick={() => setAge(a)}>{a}</button>)}
        </div>
      </div>
    </>
  );
}

export function KidSheet({ kid, onClose }: { kid?: Child; onClose: () => void }) {
  const { refresh } = useLive();
  const [name, setName] = useState(kid?.name ?? "");
  const [buddy, setBuddy] = useState(kid?.buddy ?? "scrubby");
  const [age, setAge] = useState<AgeBand>(kid?.age_band ?? "5-6");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const save = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    const body = { name: name.trim(), buddy, age_band: age };
    (kid ? send("PUT", `/api/v1/app/children/${kid.id}`, body) : send("POST", "/api/v1/app/children", body))
      .then(() => { refresh(); onClose(); }, (err: ApiError) => { setError(err); setBusy(false); });
  };
  return (
    <Sheet title={kid ? `Edit ${kid.name}` : "Who's busting germs?"} onClose={onClose}
      lede={kid ? undefined : "New washes from the station go to the child you pick on Home."}>
      <form onSubmit={save}>
        <KidFields {...{ name, setName, buddy, setBuddy, age, setAge }} />
        {error && <InlineError error={error} />}
        <div className="actions">
          <Button type="submit" wide disabled={!name.trim() || busy}>{kid ? "Save" : "Add kid"}</Button>
          <Button tone="quiet" wide onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Sheet>
  );
}
