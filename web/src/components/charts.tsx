// Small charts for the grown-up view, built from plain HTML and SVG. Each one: a single series in one
// colour, a quiet axis, a tooltip on hover or keyboard focus, and the same numbers as text for screen readers.
import type { ReactNode } from "react";

const shortDay = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
const tick = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });

function Mark({ tip, label, children, className = "", style }: { tip: ReactNode; label: string; children?: ReactNode; className?: string; style?: React.CSSProperties }) {
  return <div className={`mark ${className}`} style={style} tabIndex={0} role="img" aria-label={label}>{children}<span className="tip" aria-hidden="true">{tip}</span></div>;
}

/** Washes per day as thin columns, with the daily goal as a dashed line. */
export function DayBars({ days, goal }: { days: { date: string; washes: number }[]; goal: number }) {
  const top = Math.max(goal, ...days.map((d) => d.washes), 1);
  return (
    <figure className="chart" aria-label={`Washes per day. ${days.map((d) => `${tick(d.date)}: ${d.washes}`).join(", ")}. Goal ${goal} a day.`}>
      <div className="plot bars" style={{ ["--n" as string]: days.length }}>
        <div className="guide" style={{ bottom: `${(goal / top) * 100}%` }}><span>goal {goal}</span></div>
        {days.map((d) => (
          <Mark key={d.date} className="col" label={`${shortDay(d.date)}: ${d.washes} washes`} tip={<><b>{d.washes}</b> {d.washes === 1 ? "wash" : "washes"}<br />{shortDay(d.date)}</>}>
            <i className={d.washes >= goal ? "met" : ""} style={{ height: `${(d.washes / top) * 100}%` }} />
          </Mark>
        ))}
      </div>
      <Axis days={days} />
    </figure>
  );
}

function Axis({ days }: { days: { date: string }[] }) {
  const last = days.length - 1;
  const shown = new Set(days.length <= 7 ? days.map((_, i) => i) : [0, Math.round(last / 2), last]);
  const text = (iso: string) => (days.length <= 7 ? new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "short" }) : tick(iso));
  return <div className="axis" style={{ ["--n" as string]: days.length }}>{days.map((d, i) => <span key={d.date}>{shown.has(i) ? text(d.date) : ""}</span>)}</div>;
}

/** Average score per day, 0 to 100. Days with no wash leave a gap in the line: nothing is invented between them. */
export function ScoreLine({ days }: { days: { date: string; avg_score: number | null; washes: number }[] }) {
  const n = days.length;
  const x = (i: number) => ((i + 0.5) / n) * 100;
  const y = (v: number) => 100 - v;
  const runs: string[] = [];
  let run: string[] = [];
  days.forEach((d, i) => {
    if (d.avg_score === null) { if (run.length > 1) runs.push(run.join(" ")); run = []; } else run.push(`${x(i)},${y(d.avg_score)}`);
  });
  if (run.length > 1) runs.push(run.join(" "));
  const have = days.filter((d) => d.avg_score !== null);
  return (
    <figure className="chart" aria-label={have.length ? `Average score per day. ${have.map((d) => `${tick(d.date)}: ${d.avg_score}`).join(", ")}.` : "Average score per day. No washes in this period."}>
      <div className="plot line">
        {[100, 50, 0].map((v) => <div key={v} className="grid" style={{ bottom: `${v}%` }}><span>{v}</span></div>)}
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {runs.map((pts) => <polyline key={pts} points={pts} fill="none" stroke="var(--accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />)}
        </svg>
        {days.map((d, i) => d.avg_score === null ? null : (
          <Mark key={d.date} className="dot" style={{ left: `${x(i)}%`, bottom: `${d.avg_score}%` }} label={`${shortDay(d.date)}: average score ${d.avg_score} over ${d.washes} washes`}
            tip={<><b>{d.avg_score}</b> average<br />{d.washes} {d.washes === 1 ? "wash" : "washes"}, {shortDay(d.date)}</>} />
        ))}
      </div>
      <Axis days={days} />
    </figure>
  );
}

/** A value against a target on one shared scale, as a row: label, thin bar with a target tick, number. */
export function TargetRow({ name, value, target, max, unit, note }: { name: string; value: number | null; target: number; max: number; unit: string; note: string }) {
  const pct = value === null ? 0 : Math.min(value / max, 1) * 100;
  return (
    <div className="trow">
      <span className="tname">{name}</span>
      <Mark className="track" label={`${name}: ${value === null ? "no data" : `${value}${unit}`}, target ${target}${unit}. ${note}`} tip={<><b>{value === null ? "no data" : `${value}${unit}`}</b> average<br />target {target}{unit}. {note}</>}>
        <i style={{ width: `${pct}%` }} className={value !== null && value >= target ? "met" : ""} /><em style={{ left: `${(target / max) * 100}%` }} />
      </Mark>
      <span className="tval num">{value === null ? "–" : `${value.toFixed(1)}${unit}`}</span>
    </div>
  );
}
