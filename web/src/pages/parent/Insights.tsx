import { useState } from "react";
import { useApi, ZONE_MOVES, type Child, type Insights as Data } from "../../api";
import { TargetRow } from "../../components/charts";
import { heatFill } from "../../components/HandFigure";
import { KidPicker } from "../../components/Nav";
import { EmptyState, PageHead, Pending, SegmentedTabs } from "../../components/ui";
import { HeatHands, pct, RANGES, type Range } from "./Overview";

const MIN_N = 3; // washes before a pattern is worth naming
const hours = (from: number, to: number) => `${from}:00 to ${to}:00`;

export default function Insights() {
  const [range, setRange] = useState<Range>("14");
  const { data: ins, error, reload } = useApi<Data>(`/api/v1/app/insights?days=${range}`);
  const { data: kid } = useApi<Child | null>("/api/v1/app/child");
  const worst = ins && ins.n >= MIN_N ? [...ins.zones].sort((a, b) => (a.coverage ?? 1) - (b.coverage ?? 1))[0] : null;
  const busiest = ins ? [...ins.by_time].sort((a, b) => b.washes - a.washes)[0] : null;
  const lowTime = ins ? [...ins.by_time].filter((b) => b.washes >= MIN_N && b.avg_score !== null).sort((a, b) => a.avg_score! - b.avg_score!)[0] : null;

  return (
    <div className="page">
      <PageHead title="Insights" sub={ins ? `${kid?.name ?? "Your child"}: ${ins.n} measured washes, ${new Date(`${ins.from}T12:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" })} to ${new Date(`${ins.to}T12:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" })}` : undefined}>
        <KidPicker />
        <SegmentedTabs label="Period" options={RANGES} value={range} onChange={setRange} />
      </PageHead>
      {!ins ? <Pending error={error} retry={reload} blocks={3} /> : ins.n === 0 ? (
        <EmptyState title="Nothing to measure yet">There are no recognized washes in this period. Pick a longer period, or wash at the sink.</EmptyState>
      ) : (
        <div className="stack">
          {ins.n < MIN_N && <p className="alert" style={{ background: "var(--butter-tint)", color: "#6b4a00" }}>Only {ins.n} {ins.n === 1 ? "wash" : "washes"} in this period. Averages from so few washes move a lot; read them as a first look.</p>}

          <section className="card">
            <h2 className="h2">Hand heatmap</h2>
            <div className="grid2">
              <div><HeatHands ins={ins} /></div>
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Zone</th><th className="r">Avg scrub time</th><th className="r">Full</th><th className="r">Partial</th><th className="r">Missed</th></tr></thead>
                  <tbody>
                    {[...ins.zones].sort((a, b) => (a.coverage ?? 0) - (b.coverage ?? 0)).map((z) => (
                      <tr key={z.zone}><td><i className="swatch" style={{ background: heatFill(z.coverage) }} />{z.name}</td>
                        <td className="r">{z.coverage === null ? "–" : `${Math.round(z.coverage * 100)}%`}</td><td className="r">{z.full}</td><td className="r">{z.partial}</td><td className="r">{z.missed}</td></tr>
                    ))}
                  </tbody>
                </table>
                <p className="note">
                  Avg scrub time is the mean share of the 3 seconds each zone needs, across {ins.n} washes. Full, partial and missed count washes.
                  {worst && worst.coverage !== null && worst.coverage < 1 && <> Lowest: <b>{worst.name.toLowerCase()}</b>. The move: {ZONE_MOVES[worst.zone]}.</>}
                </p>
              </div>
            </div>
          </section>

          <div className="grid2">
            <section className="card">
              <h2 className="h2">Seconds per scrubbing step</h2>
              {ins.techniques.map((t) => <TargetRow key={t.technique} name={t.name} value={t.mean_s} target={3} max={6} unit=" s" note={`Reached 3 s in ${t.done} of ${t.n} washes.`} />)}
              <p className="note">The black tick is the 3 second target. Bars show the mean over {ins.n} washes. A step is recognized from hand motion by the camera.</p>
            </section>
            <section className="card">
              <h2 className="h2">Time of day</h2>
              <table className="data">
                <thead><tr><th>When</th><th className="r">Washes</th><th className="r">Share</th><th className="r">Avg score</th></tr></thead>
                <tbody>
                  {ins.by_time.map((b) => (
                    <tr key={b.block}><td>{b.block}<span className="sub">{hours(b.from_hour, b.to_hour)}</span></td><td className="r">{b.washes}</td><td className="r">{pct(b.washes, ins.n)}</td><td className="r">{b.avg_score ?? "–"}</td></tr>
                  ))}
                </tbody>
              </table>
              <p className="note">
                {busiest && busiest.washes > 0 && <>Most washes happen in the {busiest.block.toLowerCase()}. </>}
                {lowTime && busiest && lowTime.block !== busiest.block && <>The lowest average score is in the {lowTime.block.toLowerCase()} ({lowTime.avg_score}). </>}
                Averages are shown for any number of washes; treat rows with fewer than {MIN_N} as a first look.
              </p>
            </section>
          </div>

          <section className="card">
            <h2 className="h2">Summary figures</h2>
            <table className="data">
              <thead><tr><th>Measure</th><th className="r">Value</th><th>How it is worked out</th></tr></thead>
              <tbody>
                <tr><td>Average score</td><td className="r">{ins.score.mean ?? "–"}</td><td>Mean of the wash scores (0 to 100). Median {ins.score.median ?? "–"}, best {ins.score.best ?? "–"}.</td></tr>
                <tr><td>Change</td><td className="r">{ins.score.change === null ? "–" : `${ins.score.change > 0 ? "+" : ""}${ins.score.change}`}</td><td>{ins.score.previous_n ? `Against a mean of ${ins.score.previous_mean} over the ${ins.days} days before (${ins.score.previous_n} washes).` : "No washes in the period before."}</td></tr>
                <tr><td>Finished washes</td><td className="r">{pct(ins.finished, ins.n)}</td><td>{ins.finished} of {ins.n} had 5 of 7 steps done and 20 s of scrubbing.</td></tr>
                <tr><td>Reached 20 s</td><td className="r">{pct(ins.scrub.reached_goal, ins.n)}</td><td>{ins.scrub.reached_goal} of {ins.n}. Mean scrub time {ins.scrub.mean_s} s.</td></tr>
                <tr><td>Days at the daily goal</td><td className="r">{ins.days_goal_met} / {ins.days}</td><td>Days with at least {ins.goal} washes. {ins.days_with_wash} days had any wash.</td></tr>
                <tr><td>Not measured</td><td className="r">{ins.not_recognized}</td><td>Washes where no scrubbing was recognized. They are listed under Washes and left out of every average.</td></tr>
              </tbody>
            </table>
            <p className="note">These numbers describe recognized scrubbing motion. Accuracy has been measured on adult test videos, not yet on children at a real sink, so use them to spot habits, not to grade a child.</p>
          </section>
        </div>
      )}
    </div>
  );
}
