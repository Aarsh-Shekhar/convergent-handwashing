// The parent gate. Managing rewards, deciding requests, deleting history and removing a child are for
// grown-ups: once a PIN is set, those actions ask for it. The unlock lasts 15 minutes and lives in memory only.
import { createContext, useCallback, useContext, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, send, setParentToken, type ApiError, type ParentState } from "./api";
import { Button, Sheet } from "./components/ui";

type Gate = { ask: () => Promise<boolean>; lock: () => void };
const Ctx = createContext<Gate>({ ask: async () => true, lock: () => {} });
export const useParentGate = () => useContext(Ctx);

export function PinField({ value, onChange, label, autoFocus }: { value: string; onChange: (v: string) => void; label: string; autoFocus?: boolean }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input className="input pin" type="password" inputMode="numeric" autoComplete="off" pattern="[0-9]*" minLength={4} maxLength={8}
        value={value} onChange={(e) => onChange(e.target.value.replace(/\D/g, ""))} autoFocus={autoFocus} />
    </label>
  );
}

export function ParentProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const waiting = useRef<((ok: boolean) => void) | null>(null);

  const finish = useCallback((ok: boolean) => {
    waiting.current?.(ok);
    waiting.current = null;
    setOpen(false); setPin(""); setError(null);
  }, []);

  const ask = useCallback(async () => {
    const state = await api<ParentState>("/api/v1/app/parent").catch(() => null);
    if (state?.unlocked) return true;
    return new Promise<boolean>((resolve) => { waiting.current = resolve; setOpen(true); });
  }, []);

  const lock = useCallback(() => { send("POST", "/api/v1/app/parent/lock").catch(() => {}); setParentToken(null); }, []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    send<{ token: string }>("POST", "/api/v1/app/parent/unlock", { pin }).then(
      (r) => { setParentToken(r.token); finish(true); },
      (err: ApiError) => { setPin(""); setError(err.status === 429 ? "Too many tries. Wait a minute." : err.status === 403 ? "That PIN is not right." : err.message); },
    );
  };

  return (
    <Ctx.Provider value={{ ask, lock }}>
      {children}
      {open && (
        <Sheet title="Grown-ups only" lede="Enter the parent PIN to continue." onClose={() => finish(false)}>
          <form onSubmit={submit}>
            <PinField value={pin} onChange={setPin} label="Parent PIN" autoFocus />
            {error && <p className="alert" role="alert">{error}</p>}
            <div className="actions">
              <Button type="submit" wide disabled={pin.length < 4}>Unlock</Button>
              <Button tone="quiet" wide onClick={() => finish(false)}>Cancel</Button>
            </div>
          </form>
        </Sheet>
      )}
    </Ctx.Provider>
  );
}
