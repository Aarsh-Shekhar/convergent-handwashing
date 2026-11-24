// Scrubble's shared controls. One set of components; the kid and grown-up looks come from styles/tokens.css.
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { ApiError } from "../api";
import { useLive, useStationActive } from "../live";
import { useMode } from "../mode";
import { go } from "../router";
import { Creature } from "./Creature";
import { Icon, type IconName } from "./icons";

export function Button({ tone = "primary", wide, small, icon, children, className = "", ...rest }: {
  tone?: "primary" | "gold" | "quiet" | "danger"; wide?: boolean; small?: boolean; icon?: IconName; children: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" {...rest} className={`btn ${tone === "primary" ? "" : tone} ${wide ? "wide" : ""} ${small ? "small" : ""} ${className}`}>
      {icon && <Icon name={icon} size={18} />}{children}
    </button>
  );
}

export function IconButton({ icon, label, solid, ...rest }: { icon: IconName; label: string; solid?: boolean } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" {...rest} aria-label={label} className={`icon-btn ${solid ? "solid" : ""}`}><Icon name={icon} size={22} /></button>;
}

/** Page heading with an optional way back and tools on the right. */
export function PageHead({ title, sub, back, children }: { title: string; sub?: ReactNode; back?: [label: string, to: string]; children?: ReactNode }) {
  return (
    <>
      {back && <button type="button" className="back" onClick={() => go(back[1])}><Icon name="back" size={18} />{back[0]}</button>}
      <header className="head">
        <div><h1 className="h1">{title}</h1>{sub && <p className="muted">{sub}</p>}</div>
        {children && <div className="tools">{children}</div>}
      </header>
    </>
  );
}

export function SegmentedTabs<T extends string>({ options, value, onChange, label, wide }: {
  options: readonly (readonly [T, string])[]; value: T; onChange: (v: T) => void; label: string; wide?: boolean;
}) {
  const move = (dir: number) => {
    const i = options.findIndex(([v]) => v === value);
    onChange(options[(i + dir + options.length) % options.length][0]);
  };
  return (
    <div className={`seg ${wide ? "wide" : ""}`} role="tablist" aria-label={label}
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
      <button type="button" aria-label={`Lower ${label}`} disabled={value <= min} onClick={() => onChange(value - 1)}><Icon name="minus" size={18} /></button>
      <output aria-live="polite">{value}</output>
      <button type="button" aria-label={`Raise ${label}`} disabled={value >= max} onClick={() => onChange(value + 1)}><Icon name="plus" size={18} /></button>
    </div>
  );
}

/** A flat ring that fills clockwise from the top. `children` sit in the middle. */
export function Ring({ value, size = 96, stroke = 10, color = "var(--accent)", label, children }: {
  value: number; size?: number; stroke?: number; color?: string; label?: string; children?: ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  return (
    <div className="ring" style={{ width: size, height: size }} role={label ? "img" : undefined} aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--sunken)" strokeWidth={stroke} />
        <circle className="ring-fill" cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`} strokeDasharray={c} strokeDashoffset={c * (1 - v)} opacity={v === 0 ? 0 : 1} />
      </svg>
      <div className="ring-mid">{children}</div>
    </div>
  );
}

export function Bar({ value, tone, label }: { value: number; tone?: "gold" | "mint" | "coral"; label: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0)) * 100);
  return <div className={`bar ${tone ?? ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}><i style={{ width: `${pct}%` }} /></div>;
}

export function EmptyState({ title, children, creature, action }: { title: string; children: ReactNode; creature?: string; action?: ReactNode }) {
  return (
    <div className="card empty">
      {creature && <Creature id={creature} size={96} />}
      <h3 className="h2">{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}

export function InlineError({ error, retry }: { error: ApiError | Error; retry?: () => void }) {
  const offline = "status" in error && error.status === 0;
  return (
    <div className="alert" role="alert">
      <Icon name="info" size={20} />
      <span className="grow">{offline ? "Can't reach Scrubble. Check that the station laptop is on and on this Wi-Fi." : `Something went wrong: ${error.message}.`}</span>
      {retry && <Button small tone="quiet" icon="retry" onClick={retry}>Retry</Button>}
    </div>
  );
}

/** Loading or failed: grey blocks while waiting, an error with retry when the request failed. */
export function Pending({ error, retry, blocks = 2 }: { error: ApiError | null; retry: () => void; blocks?: number }) {
  if (error) return <InlineError error={error} retry={retry} />;
  return <div aria-busy="true" aria-label="Loading">{Array.from({ length: blocks }, (_, i) => <div key={i} className="skeleton" />)}</div>;
}

/** Is the station sending right now? Only what was actually received is shown, never a guess. */
export function StationStatus() {
  const { connected } = useLive();
  const active = useStationActive();
  const [cls, text] = !connected ? ["off", "App offline"] : active ? ["live", "Station live"] : ["", "Station idle"];
  return <span className={`status ${cls}`} role="status"><i />{text}</span>;
}

/** A sheet from the bottom (a centred dialog on desktop). Closes on Escape and on a click outside; focus returns on close. */
export function Sheet({ title, lede, onClose, children }: { title: string; lede?: ReactNode; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("keydown", key); before?.focus(); };
  }, [onClose]);
  const { view, layout } = useMode();
  return (
    <div className="scrim" data-view={view} data-layout={layout} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={ref}>
        <h2 id={titleId}>{title}</h2>
        {lede && <p className="lede">{lede}</p>}
        {children}
      </div>
    </div>
  );
}

export function Stars({ n, size = 22 }: { n: number; size?: number }) {
  return (
    <span className="stars" role="img" aria-label={`${n} of 5 stars`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <svg key={i} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
          <path d="m12 2.8 2.8 5.8 6.4.9-4.6 4.5 1.1 6.4L12 17.4l-5.7 3 1.1-6.4L2.8 9.5l6.4-.9z" fill={i <= n ? "var(--sun)" : "var(--sunken)"} stroke={i <= n ? "var(--sun-edge)" : "var(--line)"} strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
      ))}
    </span>
  );
}
