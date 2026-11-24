// Scrubble's hand-built controls and surfaces. Styles live in styles/controls.css.
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { ApiError } from "../api";
import { useLive, useStationActive } from "../live";
import { go } from "../router";
import { Creature } from "./Creature";
import { Icon, type IconName } from "./icons";

type Tone = "aqua" | "violet" | "gold" | "quiet" | "danger";

export function GameButton({ tone = "aqua", wide, small, icon, children, className = "", ...rest }: {
  tone?: Tone; wide?: boolean; small?: boolean; icon?: IconName; children: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" {...rest} className={`gbtn ${tone === "aqua" ? "" : tone} ${wide ? "wide" : ""} ${small ? "small" : ""} ${className}`}>
      {icon && <Icon name={icon} size={small ? 18 : 20} />}{children}
    </button>
  );
}

export function IconButton({ icon, label, tone = "aqua", small, ...rest }: {
  icon: IconName; label: string; tone?: "aqua" | "violet" | "quiet"; small?: boolean;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" {...rest} aria-label={label} className={`ibtn ${tone === "aqua" ? "" : tone} ${small ? "small" : ""}`}>
      <Icon name={icon} size={small ? 20 : 24} />
    </button>
  );
}

/** Top bar of an inner screen: back, centred title, optional round action on the right. */
export function TopBar({ title, back, right }: { title: string; back?: string | (() => void); right?: ReactNode }) {
  const onBack = typeof back === "string" ? () => (history.length > 1 ? history.back() : go(back)) : back;
  return (
    <header className="topbar">
      {onBack ? <IconButton icon="back" label="Back" onClick={onBack} /> : <span className="lead-none" />}
      <h1>{title}</h1>
      {right ?? <span className="lead-none" />}
    </header>
  );
}

export function SegmentedTabs<T extends string>({ options, value, onChange, label }: {
  options: readonly (readonly [T, string])[]; value: T; onChange: (v: T) => void; label: string;
}) {
  const move = (dir: number) => {
    const i = options.findIndex(([v]) => v === value);
    onChange(options[(i + dir + options.length) % options.length][0]);
  };
  return (
    <div className="seg" role="tablist" aria-label={label}
      onKeyDown={(e) => { if (e.key === "ArrowRight") move(1); else if (e.key === "ArrowLeft") move(-1); }}>
      {options.map(([v, text]) => (
        <button key={v} type="button" role="tab" aria-selected={v === value} tabIndex={v === value ? 0 : -1} onClick={() => onChange(v)}>{text}</button>
      ))}
    </div>
  );
}

export function Toggle({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return <button type="button" role="switch" className="toggle" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)} />;
}

export function Stepper({ value, min, max, onChange, label }: { value: number; min: number; max: number; onChange: (v: number) => void; label: string }) {
  return (
    <div className="stepper" role="group" aria-label={label}>
      <button type="button" aria-label={`Lower ${label}`} disabled={value <= min} onClick={() => onChange(value - 1)}><Icon name="minus" size={20} /></button>
      <output aria-live="polite">{value}</output>
      <button type="button" aria-label={`Raise ${label}`} disabled={value >= max} onClick={() => onChange(value + 1)}><Icon name="plus" size={20} /></button>
    </div>
  );
}

/** A ring that fills clockwise from the top. `children` sit in the middle. */
export function ProgressRing({ value, size = 96, stroke = 11, color = "var(--gold)", label, children }: {
  value: number; size?: number; stroke?: number; color?: string; label?: string; children?: ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const id = useId();
  return (
    <div className="ring" style={{ width: size, height: size }} role={label ? "img" : undefined} aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#fff" stopOpacity="0.55" /><stop offset="0.5" stopColor="#fff" stopOpacity="0" /></linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(12,14,46,0.5)" strokeWidth={stroke} />
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          <circle className="ring-fill" cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
            strokeDasharray={c} strokeDashoffset={c * (1 - v)} opacity={v === 0 ? 0 : 1} />
          <circle className="ring-fill" cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`url(#${id})`} strokeWidth={stroke * 0.4} strokeLinecap="round"
            strokeDasharray={c} strokeDashoffset={c * (1 - v)} opacity={v === 0 ? 0 : 1} />
        </g>
      </svg>
      <div className="ring-mid">{children}</div>
    </div>
  );
}

export function Bar({ value, tone = "gold", label }: { value: number; tone?: "gold" | "mint" | "coral" | "aqua"; label: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return <div className={`bar ${tone === "gold" ? "" : tone}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}><i style={{ width: `${pct}%` }} /></div>;
}

/** One counter of the game HUD: a glossy token and a number. */
export function HudCounter({ kind, value, label }: { kind: "points" | "zaps" | "streak"; value: number; label: string }) {
  const icon: IconName = kind === "points" ? "coin" : kind === "zaps" ? "bolt" : "flame";
  return (
    <span className={`hud-counter ${kind}`} role="img" aria-label={`${value} ${label}`}>
      <span className="token"><Icon name={icon} size={17} /></span>
      <span className="num">{value.toLocaleString()}</span>
    </span>
  );
}

/** A large rounded panel that carries an illustration. */
export function IllustratedPanel({ tone = "blue", className = "", children, scene }: {
  tone?: "blue" | "violet" | "deep"; className?: string; children: ReactNode; scene?: ReactNode;
}) {
  return (
    <section className={`panel illustrated ${tone === "blue" ? "" : tone} ${className}`}>
      {scene && <div className="scene" aria-hidden="true">{scene}</div>}
      <div className="content">{children}</div>
    </section>
  );
}

export function EmptyState({ title, children, creature = "bubbles", action }: { title: string; children: ReactNode; creature?: string; action?: ReactNode }) {
  return (
    <div className="panel deep empty">
      <div className="art"><Creature id={creature} size={132} bob /></div>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}

export function InlineError({ error, retry }: { error: ApiError | Error; retry?: () => void }) {
  const offline = "status" in error && error.status === 0;
  return (
    <div className="inline-error" role="alert">
      <Icon name="info" />
      <span className="grow">{offline ? "Can't reach Scrubble. Check that the station laptop is on and on this Wi-Fi." : `Something went wrong: ${error.message}.`}</span>
      {retry && <GameButton small tone="quiet" icon="retry" onClick={retry}>Retry</GameButton>}
    </div>
  );
}

/** Loading or failed: skeleton blocks while waiting, an error with retry when the request failed. */
export function Pending({ error, retry, blocks = 2 }: { error: ApiError | null; retry: () => void; blocks?: number }) {
  if (error) return <InlineError error={error} retry={retry} />;
  return <div aria-busy="true" aria-label="Loading">{Array.from({ length: blocks }, (_, i) => <div key={i} className="skeleton" />)}</div>;
}

/** Is the station sending right now? Only what was actually received is shown, never a guess. */
export function SyncIndicator() {
  const { connected } = useLive();
  const active = useStationActive();
  const [cls, text] = !connected ? ["off", "Offline"] : active ? ["live", "Station live"] : ["", "Station idle"];
  return <span className={`sync ${cls}`} role="status"><i />{text}</span>;
}

/** A bottom sheet. Closes on Escape and on a tap outside; focus moves in and returns on close. */
export function Sheet({ title, lede, onClose, children }: { title: string; lede?: ReactNode; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", key);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", key); document.body.style.overflow = ""; before?.focus(); };
  }, [onClose]);
  return (
    <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={ref}>
        <div className="grip" />
        <h2 id={titleId}>{title}</h2>
        {lede && <p className="lede">{lede}</p>}
        {children}
      </div>
    </div>
  );
}
