// Small shared pieces: icons, ring, segmented control, meters, empty state.
import type { ReactNode } from "react";
import scrubby from "../assets/scrubby.png";

const ICONS: Record<string, ReactNode> = {
  home: <path d="M4 11.5 12 5l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5h-5v5H5a1 1 0 0 1-1-1z" />,
  chart: <path d="M5 20V11M10 20V5M15 20v-7M20 20V8" />,
  gift: <path d="M4 10h16v3H4zM5 13h14v7H5zM12 10v10M12 10c-2.5 0-5-1-4.5-3s3.5-1 4.5 3zm0 0c2.5 0 5-1 4.5-3s-3.5-1-4.5 3z" />,
  germ: <><circle cx="12" cy="12" r="5" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" /></>,
  gear: <><circle cx="12" cy="12" r="3" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" /></>,
  right: <path d="m9 5 7 7-7 7" />,
  left: <path d="m15 5-7 7 7 7" />,
  spark: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" />,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  star: <path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" />,
  hand: <path d="M8 13V6.5a1.5 1.5 0 0 1 3 0V12m0-6.5v-1a1.5 1.5 0 0 1 3 0V12m0-6a1.5 1.5 0 0 1 3 0v7m0-4a1.5 1.5 0 0 1 3 0v5a6 6 0 0 1-6 6h-1.5a6 6 0 0 1-4.6-2.2L5 16.5a1.6 1.6 0 0 1 2.4-2.1L8 15" />,
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  wifi: <path d="M4 9.5a12 12 0 0 1 16 0M7 13a7.5 7.5 0 0 1 10 0M10 16.4a3 3 0 0 1 4 0M12 19.5h.01" />,
  trash: <path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12" />,
  shield: <path d="M12 3.5 5 6v5.5c0 4.2 3 7.6 7 9 4-1.4 7-4.8 7-9V6z" />,
  lock: <><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
};

export function Icon({ name, size = 22 }: { name: keyof typeof ICONS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

export function Ring({ value, size = 92, stroke = 10, color = "var(--navy)", track = "#e6edf5", children }: {
  value: number; size?: number; stroke?: number; color?: string; track?: string; children?: ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <div style={{ position: "relative", width: size, height: size, flex: "none" }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} stroke={track} strokeWidth={stroke} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={color} strokeWidth={stroke} fill="none" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - v)} style={{ transition: "stroke-dashoffset 0.8s ease" }} />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>{children}</div>
    </div>
  );
}

export function Seg<T extends string>({ options, value, onChange }: { options: [T, string][]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="seg" role="group">
      {options.map(([v, label]) => (
        <button key={v} aria-pressed={v === value} onClick={() => onChange(v)}>{label}</button>
      ))}
    </div>
  );
}

/** One labelled bar. `kind` colours it: missed (coral), ok (green) or plain (navy). */
export function Meter({ label, value, text, kind }: { label: string; value: number; text: string; kind?: "missed" | "ok" }) {
  return (
    <div className="meter">
      <span>{label}</span>
      <div className="track"><div className={`fill ${kind ?? ""}`} style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` }} /></div>
      <span className="val">{text}</span>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="card empty fade-in">
      <img src={scrubby} alt="" className="bob" />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

export function Loading({ error }: { error: string | null }) {
  return error ? <div className="err">Can't reach the Scrubby station: {error}. Is the backend running?</div> : <div className="skeleton" />;
}

export function PageHead({ title, back, right }: { title: string; back?: () => void; right?: ReactNode }) {
  return (
    <div className="page-head">
      {back ? <button className="back" onClick={back} aria-label="Back"><Icon name="left" /></button> : <span className="spacer" />}
      <h1>{title}</h1>
      {right ?? <span className="spacer" />}
    </div>
  );
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return <button className="toggle" role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)} />;
}

export function Stepper({ value, min, max, onChange, label }: { value: number; min: number; max: number; onChange: (v: number) => void; label: string }) {
  return (
    <div className="stepper" role="group" aria-label={label}>
      <button aria-label="Less" onClick={() => onChange(Math.max(min, value - 1))}>−</button>
      <b>{value}</b>
      <button aria-label="More" onClick={() => onChange(Math.min(max, value + 1))}>+</button>
    </div>
  );
}
