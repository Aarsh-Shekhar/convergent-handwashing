import { useApi, ZONE_NAMES, ZONES, type WashDetail as Detail } from "../api";
import { HandMap } from "../components/HandMap";
import { Icon, Loading, Meter, PageHead } from "../components/ui";
import { MissedPills } from "../components/WashCard";
import { go } from "../router";

export default function WashDetail({ id }: { id: string }) {
  const { data: w, error } = useApi<Detail>(`/api/v1/app/washes/${encodeURIComponent(id)}`);
  const back = () => (history.length > 1 ? history.back() : go("/washes"));
  if (!w) return <div className="page"><PageHead title="Wash" back={back} /><Loading error={error} /></div>;
  const goalMet = w.seconds_total >= w.total_min_s;
  return (
    <div className="page fade-in">
      <PageHead title={`${w.label} · ${w.time}`} back={back} />
      <div className="card detail-stats">
        <div className="score"><b>{w.points}</b><span>score{w.zaps ? ` · +${w.zaps} zaps` : w.capped ? " · daily zaps done" : ""}</span></div>
        <div>
          <b>{Math.round(w.seconds_total)}s</b>
          <span>of {w.total_min_s}s goal {goalMet && <span className="up"><Icon name="check" size={11} /></span>}</span>
        </div>
        <div><b>{w.steps_done}/7</b><span>steps done</span></div>
      </div>

      <div className="card">
        <h3>Where the germs got zapped</h3>
        <HandMap coverage={w.coverage} />
        {ZONES.map((z) => (
          <Meter key={z} label={ZONE_NAMES[z]} value={w.coverage[z]} text={`${Math.round(w.coverage[z] * 100)}%`}
            kind={w.coverage[z] >= 1 ? "ok" : "missed"} />
        ))}
      </div>

      <div className="card">
        <div className="pill-row">
          <MissedPills w={w} max={6} />
          <span className="pill zaps" aria-label={`${w.stars} of 5 stars`}>{"★".repeat(w.stars)}{"☆".repeat(5 - w.stars)}</span>
          {w.soap_seen !== null && <span className="pill">{w.soap_seen ? "Soap seen" : "No soap seen"}</span>}
        </div>
        <p className="faint" style={{ margin: "10px 0 0" }}>
          A part counts as clean after {w.step_min_s} s of the right scrubbing motion. Scrubby measures motion, not germs.
        </p>
      </div>
    </div>
  );
}
