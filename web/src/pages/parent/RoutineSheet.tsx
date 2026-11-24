import { useState } from "react";
import type { Routine } from "../../api";
import { Button, Sheet } from "../../components/ui";

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
export const pretty = (t: string) => new Date(`2000-01-01T${t}:00`).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
const slug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 32) || "routine";

export function RoutineSheet({ routine, onSave, onRemove, onClose }: { routine: Routine | null; onSave: (r: Routine) => void; onRemove?: () => void; onClose: () => void }) {
  const [name, setName] = useState(routine?.name ?? "");
  const [time, setTime] = useState(routine?.time ?? "");
  const valid = name.trim().length > 0 && (time === "" || HHMM.test(time));
  return (
    <Sheet title={routine ? "Edit routine" : "New routine"} lede="A routine names the washes that happen around its time." onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (valid) onSave({ id: routine?.id ?? `${slug(name)}_${Date.now().toString(36)}`, name: name.trim(), detail: time ? "Daily" : "Any time", time: time || null, on: routine?.on ?? true }); }}>
        <label className="field"><span>Name</span><input className="input" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} placeholder="After school" required /></label>
        <label className="field"><span>Usual time (optional)</span><input className="input" type="time" value={time} onChange={(e) => setTime(e.target.value)} /></label>
        <div className="actions">
          <Button type="submit" wide disabled={!valid}>Save</Button>
          {onRemove && <Button tone="danger" wide icon="trash" onClick={onRemove}>Remove routine</Button>}
        </div>
      </form>
    </Sheet>
  );
}

