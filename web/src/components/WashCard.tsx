// One wash as a card (Home's latest wash) or a row (Wash history).
import { ZONE_NAMES, type WashView } from "../api";
import { Link } from "../router";
import { Germ, germFor } from "./germs";
import { Icon } from "./ui";

export function MissedPills({ w, max = 2 }: { w: WashView; max?: number }) {
  if (!w.missed.length) return <span className="pill perfect"><Icon name="spark" size={12} />Perfect scrub</span>;
  if (w.missed.length > max + 1) return <span className="pill missed">Missed {w.missed.length} spots</span>;
  return <>{w.missed.map((z) => <span key={z} className="pill missed">{ZONE_NAMES[z]}</span>)}</>;
}

export function WashCard({ w, hero = false }: { w: WashView; hero?: boolean }) {
  return (
    <Link to={`/washes/${encodeURIComponent(w.wash_id)}`} className={`card wash-card ${hero ? "hero" : ""}`}>
      {hero
        ? <Germ id={w.missed.length ? germFor(w.missed[0]) : "scrubby"} className="germ" size={52} />
        : <div className={`score-badge ${w.points >= 90 ? "top" : ""}`}>{w.points}</div>}
      <div className="body">
        <div className="title">{w.label} · {w.time}</div>
        <div className="sub">{Math.round(w.seconds_total)} sec · {w.points} pts{w.zaps ? ` · +${w.zaps} zaps` : ""}</div>
        <div className="pill-row"><MissedPills w={w} /></div>
      </div>
      <span className="chev"><Icon name="right" size={18} /></span>
    </Link>
  );
}
