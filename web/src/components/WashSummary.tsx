// One wash at a glance: used for Home's latest wash and for each row of the history.
import { ZONE_NAMES, type WashView } from "../api";
import { Link } from "../router";
import { CaveScene } from "../art/scenes";
import { Creature, germFor } from "./Creature";
import { Icon } from "./icons";
import { ProgressRing } from "./ui";
import "./WashSummary.css";

/**
 * What a wash missed. "Perfect scrub" only when every zone reached its full time; a wash where nothing
 * was recognized says so instead of listing six misses.
 */
export function MissedTags({ w, max = 2 }: { w: WashView; max?: number }) {
  if (w.stars === 0) return <span className="tag">Nothing recognized</span>;
  if (!w.missed.length) return <span className="tag good"><Icon name="sparkle" size={13} />Perfect scrub</span>;
  if (w.missed.length > max) return <span className="tag missed"><Icon name="hand" size={13} />Missed {w.missed.length} spots</span>;
  return <>{w.missed.map((z) => <span key={z} className="tag missed"><Icon name="hand" size={13} />Missed {ZONE_NAMES[z].toLowerCase()}</span>)}</>;
}

export const washPath = (w: Pick<WashView, "wash_id">) => `/history/${encodeURIComponent(w.wash_id)}`;

/** Home's latest wash: a wide illustrated row with the germ that got away. */
export function LatestWash({ w }: { w: WashView }) {
  const germ = w.missed.length && w.stars > 0 ? germFor(w.missed[0]) : "bubbles";
  return (
    <Link to={washPath(w)} className="panel violet illustrated latest-wash" aria-label={`${w.label}, ${w.time}, score ${w.points}. Open wash details`}>
      <div className="scene" aria-hidden="true"><CaveScene /></div>
      <div className="content">
        <div className="what">{w.label}</div>
        <div className="meta"><span>{w.time}</span><i />{Math.round(w.seconds_total)} sec<i />{w.points} pts</div>
        <div className="tags"><MissedTags w={w} /></div>
      </div>
      <Creature id={germ} size={104} className="who" />
    </Link>
  );
}

/** A history row: score ring, routine, time and what was missed. */
export function WashRow({ w }: { w: WashView }) {
  const tone = w.stars === 0 ? "#7f8ab8" : w.missed.length ? "var(--gold)" : "var(--mint)";
  return (
    <Link to={washPath(w)} className="panel flat wash-row">
      <ProgressRing value={w.points / 100} size={56} stroke={7} color={tone} label={`Score ${w.points} of 100`}>
        <span className="score num">{w.points}</span>
      </ProgressRing>
      <div className="body">
        <div className="what">{w.label}</div>
        <div className="meta"><span>{w.time}</span><i />{Math.round(w.seconds_total)} sec</div>
        <div className="tags"><MissedTags w={w} /></div>
      </div>
      <span className="go"><Icon name="chevron" size={20} /></span>
    </Link>
  );
}
