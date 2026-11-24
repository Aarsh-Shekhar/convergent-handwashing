import { useState } from "react";
import { useApi, type Home, type Insights, type RewardsPage, type Station, type WashView } from "../../api";
import { DayBars, ScoreLine } from "../../components/charts";
import { HandFigure, heatFill } from "../../components/HandFigure";
import { KidPicker } from "../../components/Nav";
import { Button, EmptyState, PageHead, Pending, SegmentedTabs, StationStatus } from "../../components/ui";
import { useWashStage } from "../../live";
import { go, Link } from "../../router";
import { isDemoId, MissedTags, SourceTag } from "../../wash";

export const RANGES = [["7", "7 days"], ["14", "14 days"], ["30", "30 days"]] as const;
export type Range = (typeof RANGES)[number][0];
export const pct = (part: number, whole: number) => (whole ? `${Math.round((part / whole) * 100)}%` : "–");

function Kpi({ label, value, unit, children }: { label: string; value: string; unit?: string; children?: React.ReactNode }) {
  return <div className="kpi"><dt>{label}</dt><dd>{value}{unit && <small>{unit}</small>}</dd>{children && <p>{children}</p>}</div>;
}

export function HeatHands({ ins }: { ins: Insights }) {
  const by = Object.fromEntries(ins.zones.map((z) => [z.zone, z.coverage])) as Record<string, number | null>;
  const summary = ins.n ? `Average share of each zone's scrub time over ${ins.n} washes. ${ins.zones.map((z) => `${z.name} ${Math.round((z.coverage ?? 0) * 100)}%`).join(", ")}.` : "No washes in this period.";
  return (
    <>
      <HandFigure fill={(z) => heatFill(by[z])} summary={summary} />
      <div className="scale" aria-hidden="true">0%<span className="steps">{[0.1, 0.3, 0.5, 0.7, 0.9].map((v) => <i key={v} style={{ background: heatFill(v) }} />)}</span>100% of scrub time</div>
    </>
  );
}

export default function Overview() {
  const [range, setRange] = useState<Range>("7");
  const { data: ins, error, reload } = useApi<Insights>(`/api/v1/app/insights?days=${range}`);
  const { data: home } = useApi<Home>("/api/v1/app/home");
  const { data: washes } = useApi<WashView[]>("/api/v1/app/washes");
  const { data: station } = useApi<Station>("/api/v1/app/station");
  const { data: rewards } = useApi<RewardsPage>("/api/v1/app/family-rewards");
  const { stage, live, now } = useWashStage();
  const kid = home?.child?.name;
  const waiting = rewards?.requests.filter((q) => q.status === "requested") ?? [];
  const weakest = ins ? [...ins.zones].filter((z) => z.coverage !== null).sort((a, b) => a.coverage! - b.coverage!).slice(0, 3) : [];

  return (
    <div className="page">
      <PageHead title={home?.parent_name ? `Hi ${home.parent_name}` : "Overview"} sub={kid ? `${kid}'s handwashing, last ${range} days` : "Add a child in Settings to begin"}>
        <KidPicker />
        <SegmentedTabs label="Period" options={RANGES} value={range} onChange={setRange} />
      </PageHead>

      {stage === "scrubbing" && (
        <Link to="/station" className="card live-line" style={{ marginBottom: 16 }}>
          <StationStatus />
          <span className="now">{kid ?? "Someone"} is washing now{now ? `: ${now.replace(/_/g, " ")}` : ""}</span>
          <span className="muted num">{Math.round(live?.score?.total_s ?? 0)} s scrubbed, score {live?.score?.points ?? 0} so far</span>
        </Link>
      )}

      {!ins ? <Pending error={error} retry={reload} blocks={3} /> : ins.n === 0 && !washes?.length ? (
        <EmptyState title="No washes yet" creature="bubbles" action={<Button onClick={() => go("/station")}>See how washes arrive</Button>}>
          When the station at the sink finishes a wash, it shows up here within a few seconds.
        </EmptyState>
      ) : (
        <>
          <dl className="kpis">
            <Kpi label="Washes" value={String(ins.n)}>{(ins.n / ins.days).toFixed(1)} a day, goal {ins.goal}</Kpi>
            <Kpi label="Average score" value={ins.score.mean === null ? "–" : ins.score.mean.toFixed(0)} unit="/ 100">
              {ins.score.change === null ? "No earlier period to compare" : <span className={ins.score.change >= 0 ? "up" : "down"}>{ins.score.change >= 0 ? "+" : ""}{ins.score.change} vs the {ins.days} days before</span>}
            </Kpi>
            <Kpi label="Average scrub time" value={ins.scrub.mean_s === null ? "–" : ins.scrub.mean_s.toFixed(0)} unit="s">{ins.scrub.reached_goal} of {ins.n} reached {ins.scrub.goal_s} s</Kpi>
            <Kpi label="All zones washed" value={pct(ins.perfect, ins.n)}>{ins.perfect} of {ins.n} washes</Kpi>
            <Kpi label="Days with a wash" value={`${ins.days_with_wash}`} unit={`/ ${ins.days}`}>{home ? `${home.streak}-day streak now` : ""}</Kpi>
          </dl>

          <div className="grid-main">
            <div className="stack">
              <section className="card"><h2 className="h2">Average score per day</h2><ScoreLine days={ins.per_day} /></section>
              <section className="card"><h2 className="h2">Washes per day</h2><DayBars days={ins.per_day} goal={ins.goal} /></section>
            </div>
            <div className="stack">
              <section className="card">
                <div className="sec" style={{ margin: "0 0 8px" }}><h2 className="h2">Where the scrubbing lands</h2><Link to="/insights" className="link">Details</Link></div>
                <HeatHands ins={ins} />
                {weakest.length > 0 && (
                  <table className="data" style={{ marginTop: 12 }}>
                    <thead><tr><th>Least scrubbed</th><th className="r">Avg time</th><th className="r">Missed</th></tr></thead>
                    <tbody>{weakest.map((z) => <tr key={z.zone}><td>{z.name}</td><td className="r">{Math.round(z.coverage! * 100)}%</td><td className="r">{z.missed} of {z.n}</td></tr>)}</tbody>
                  </table>
                )}
              </section>
              <section className="card">
                <div className="sec" style={{ margin: "0 0 4px" }}><h2 className="h2">Station</h2><Link to="/station" className="link">How sync works</Link></div>
                <div className="rows">
                  <div className="row"><span className="grow"><StationStatus /></span><span className="value">{station?.last_wash ? `Last wash ${new Date(station.last_wash).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}` : "No wash from the sink yet"}</span></div>
                  {waiting.length > 0 && <Link to="/rewards" className="row"><span className="grow name">{waiting.length} reward {waiting.length === 1 ? "request" : "requests"} waiting for you</span><span className="link">Review</span></Link>}
                </div>
              </section>
            </div>
          </div>

          <section className="card" style={{ marginTop: 16 }}>
            <div className="sec" style={{ margin: "0 0 4px" }}><h2 className="h2">Latest washes</h2><Link to="/washes" className="link">All washes</Link></div>
            <div className="table-wrap"><WashTable washes={(washes ?? []).slice(0, 5)} /></div>
          </section>
        </>
      )}
    </div>
  );
}

export function WashTable({ washes }: { washes: WashView[] }) {
  return (
    <table className="data">
      <thead><tr><th>When</th><th>Score</th><th className="r wide-only">Scrub time</th><th className="r wide-only">Steps</th><th>Result</th><th className="wide-only">Source</th></tr></thead>
      <tbody>
        {washes.map((w) => (
          <tr key={w.wash_id} className="go" onClick={() => go(`/washes/${encodeURIComponent(w.wash_id)}`)}>
            <td><Link to={`/washes/${encodeURIComponent(w.wash_id)}`} className="cell" onClick={(e) => e.stopPropagation()}>{w.label}<span className="sub">{new Date(w.ended).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}, {w.time}</span></Link></td>
            <td><span className="scorebar"><span>{w.points}</span><i style={{ ["--v" as string]: `${w.points}%` }} /></span></td>
            <td className="r wide-only">{Math.round(w.seconds_total)} s</td>
            <td className="r wide-only">{w.steps_done} / 7</td>
            <td><span className="tags"><MissedTags w={w} max={1} /></span></td>
            <td className="wide-only"><SourceTag source={isDemoId(w.wash_id) ? "demo" : "station"} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
