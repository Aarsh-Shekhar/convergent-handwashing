import { useApi, ZONE_MOVES, ZONE_NAMES, ZONES, type Adventure, type Child, type DayProgress, type MonthProgress, type WeekProgress } from "../api";
import { WorldMap } from "../art/WorldMap";
import { Creature, germFor } from "../components/Creature";
import { Bar, EmptyState, Pending, ProgressRing, SegmentedTabs, TopBar } from "../components/ui";
import { go, useQuery } from "../router";
import "./Progress.css";

type Period = "day" | "week" | "month";
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const TIP_MIN = 3; // washes before a pattern is worth naming (same rule as Home's tip)

function Figures({ items }: { items: [label: string, value: string, extra?: string][] }) {
  return (
    <dl className="figures">
      {items.map(([label, value, extra]) => <div key={label}><dd className="data">{value}{extra && <small className={extra.startsWith("↑") ? "up" : ""}>{extra}</small>}</dd><dt>{label}</dt></div>)}
    </dl>
  );
}

/** Washes per day with the goal line. The same numbers are given as text for screen readers. */
function WeekChart({ w }: { w: WeekProgress }) {
  const top = Math.max(w.goal, ...w.per_day, 1);
  const todayIdx = (new Date().getDay() + 6) % 7;
  const thisWeek = w.start === new Date(Date.now() - todayIdx * 86400000).toLocaleDateString("en-CA");
  const H = 132;
  const summary = `Washes per day this week: ${w.per_day.map((n, i) => `${DOW[i]} ${n}`).join(", ")}. The goal is ${w.goal} a day.`;
  return (
    <figure className="chart" role="img" aria-label={summary}>
      <div className="plot" style={{ height: H }}>
        <div className="goal" style={{ bottom: `${(w.goal / top) * 100}%` }}><span>goal {w.goal}</span></div>
        {w.per_day.map((n, i) => {
          const future = thisWeek && i > todayIdx;
          return (
            <div key={i} className={`col ${thisWeek && i === todayIdx ? "today" : ""} ${future ? "future" : ""} ${n >= w.goal ? "met" : ""}`}>
              {n > 0 && <b className="num">{n}</b>}
              <i style={{ height: `${Math.max(n / top, future ? 0 : 0.03) * 100}%` }} />
            </div>
          );
        })}
      </div>
      <div className="axis">{DOW.map((d, i) => <span key={d} className={thisWeek && i === todayIdx ? "today" : ""}>{d[0]}</span>)}</div>
    </figure>
  );
}

function Week({ streak }: { streak: number | undefined }) {
  const { data: w, error, reload } = useApi<WeekProgress>("/api/v1/app/progress?period=week");
  if (!w) return <Pending error={error} retry={reload} />;
  const change = w.avg_change ? `${w.avg_change > 0 ? "↑" : "↓"}${Math.abs(w.avg_change)}` : undefined;
  const top = w.trouble_spots[0];
  return (
    <>
      <Figures items={[["washes", String(w.washes)], ["avg score", w.avg_score === null ? "–" : String(w.avg_score), change], ["day streak", streak === undefined ? "–" : String(streak)]]} />
      <section className="panel"><h3>Washes per day</h3><WeekChart w={w} /></section>
      <section className="panel">
        <h3>Trouble spots this week</h3>
        {w.washes < TIP_MIN ? (
          <p className="soft">{w.washes === 0 ? "No washes this week yet." : `Only ${w.washes} ${w.washes === 1 ? "wash" : "washes"} so far. Patterns show after ${TIP_MIN}.`}</p>
        ) : !w.trouble_spots.length ? <p className="soft">Nothing missed in {w.washes} washes. Great scrubbing!</p> : (
          <>
            <ul className="spots">
              {w.trouble_spots.slice(0, 4).map((s) => (
                <li key={s.zone}>
                  <Creature id={germFor(s.zone)} size={34} />
                  <span className="sname">{s.name}</span>
                  <Bar value={s.missed} tone="coral" label={`${s.name} missed`} />
                  <span className="num sval">missed {Math.round(s.missed * w.washes)} of {w.washes}</span>
                </li>
              ))}
            </ul>
            <p className="faint how">Share of this week's {w.washes} washes where the zone did not get its full scrub.</p>
          </>
        )}
      </section>
      {top && w.washes >= TIP_MIN && (
        <section className="panel deep coach">
          <Creature id={germFor(top.zone)} size={56} />
          <p><b>Practice {top.name.toLowerCase()} together</b>Before the next wash, show the move: {ZONE_MOVES[top.zone]}.</p>
        </section>
      )}
    </>
  );
}

function Day() {
  const { data: d, error, reload } = useApi<DayProgress>("/api/v1/app/progress?period=day");
  if (!d) return <Pending error={error} retry={reload} />;
  return (
    <>
      <section className="panel today-panel">
        <ProgressRing value={d.washes / d.goal} size={124} stroke={14} label={`${d.washes} of ${d.goal} washes today`}>
          <div><b className="data">{d.washes}<small>/{d.goal}</small></b><span className="faint">washes</span></div>
        </ProgressRing>
        <div><div className="data">{d.avg_score ?? "–"}</div><div className="soft">average score today</div></div>
      </section>
      <section className="panel">
        <h3>Zones washed today</h3>
        {d.washes ? (
          <ul className="spots plain">
            {ZONES.map((z) => (
              <li key={z}><span className="sname">{ZONE_NAMES[z]}</span><Bar value={d.zones[z]} tone={d.zones[z] >= 1 ? "mint" : "gold"} label={ZONE_NAMES[z]} /><span className="num sval">{Math.round(d.zones[z] * 100)}%</span></li>
            ))}
          </ul>
        ) : <p className="soft">No washes yet today.</p>}
        {d.washes > 0 && <p className="faint how">Average share of each zone's scrub time across today's {d.washes} {d.washes === 1 ? "wash" : "washes"}.</p>}
      </section>
    </>
  );
}

function Month() {
  const { data: m, error, reload } = useApi<MonthProgress>("/api/v1/app/progress?period=month");
  if (!m) return <Pending error={error} retry={reload} />;
  const title = new Date(m.year, m.month - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const now = new Date();
  const thisMonth = now.getFullYear() === m.year && now.getMonth() + 1 === m.month;
  return (
    <section className="panel">
      <h3 className="center">{title}</h3>
      <div className="cal" role="list" aria-label={`Washes per day in ${title}`}>
        {DOW.map((d) => <span key={d} className="dow" aria-hidden="true">{d[0]}</span>)}
        {Array.from({ length: m.first_weekday }, (_, i) => <span key={`pad${i}`} />)}
        {m.days.map((d) => (
          <div key={d.day} role="listitem" className={`day ${thisMonth && d.day === now.getDate() ? "today" : ""}`} aria-label={`${d.day}: ${d.washes} ${d.washes === 1 ? "wash" : "washes"}`}>
            <ProgressRing value={d.fill} size={32} stroke={5} color={d.fill >= 1 ? "var(--mint)" : "var(--gold)"} />
            <span className="num">{d.day}</span>
          </div>
        ))}
      </div>
      <p className="faint center how">{m.washes} washes this month. A full ring is {m.goal} in a day.</p>
    </section>
  );
}

function MapView({ a }: { a: Adventure }) {
  return (
    <>
      <section className="panel illustrated map-panel">
        <div className="content">
          <WorldMap data={a} />
          <ol className="places">
            {a.stages.map((s) => (
              <li key={s.id} className={s.unlocked ? "open" : ""}>
                <b>{s.name}</b><span>{s.unlocked ? "Open" : `Opens at ${s.unlock_at} washes`}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>
      <section className="panel deep next-stop">
        {a.next ? (
          <>
            <b>{a.next.name} opens in {a.next.washes_left} more {a.next.washes_left === 1 ? "wash" : "washes"}</b>
            <Bar value={a.rewarded_washes / (a.rewarded_washes + a.next.washes_left)} label="Progress to the next place" />
          </>
        ) : <b>Every place on the map is open.</b>}
        <p className="faint">The map moves with real washes at the sink: {a.rewarded_washes} so far. Washes past the daily goal don't count, so there is no reason to wash extra.</p>
      </section>
    </>
  );
}

export default function Progress() {
  const view = useQuery("view") === "map" ? "map" : "stats";
  const period = (useQuery("period") ?? "week") as Period;
  const { data: kid } = useApi<Child | null>("/api/v1/app/child");
  const { data: a, error, reload } = useApi<Adventure>("/api/v1/app/adventure");
  const set = (v: string, p: string) => go(`/progress?view=${v}&period=${p}`, true);
  return (
    <div className="page progress">
      <TopBar title={kid ? `${kid.name}'s progress` : "Progress"} />
      <SegmentedTabs label="Progress view" options={[["stats", "Trends"], ["map", "Adventure map"]]} value={view} onChange={(v) => set(v, period)} />
      {view === "map" ? (a ? <MapView a={a} /> : <Pending error={error} retry={reload} />) : a && a.rewarded_washes === 0 && a.streak.best === 0 ? (
        <EmptyState title="Progress starts with a wash">Charts and the map fill in as washes arrive from the sink.</EmptyState>
      ) : (
        <>
          <div className="period"><SegmentedTabs label="Time range" options={[["day", "Day"], ["week", "Week"], ["month", "Month"]]} value={period} onChange={(p) => set(view, p)} /></div>
          {period === "day" ? <Day /> : period === "month" ? <Month /> : <Week streak={a?.streak.current} />}
        </>
      )}
    </div>
  );
}
