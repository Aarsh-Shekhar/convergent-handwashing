import { useState } from "react";
import { localIso, useApi, ZONE_NAMES, ZONES, type Child, type DayProgress, type MonthProgress, type WeekProgress } from "../api";
import { Germ, germFor } from "../components/germs";
import { Empty, Loading, Meter, PageHead, Ring, Seg } from "../components/ui";

type Period = "day" | "week" | "month";
const DOW = ["M", "T", "W", "T", "F", "S", "S"];

function Day() {
  const { data: d, error } = useApi<DayProgress>("/api/v1/app/progress?period=day");
  if (!d) return <Loading error={error} />;
  return (
    <>
      <div className="card" style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <Ring value={d.washes / d.goal} size={112} stroke={12} color="var(--blue-btn)">
          <div className="ring-label"><b>{d.washes}/{d.goal}</b><span>washes</span></div>
        </Ring>
        <div>
          <div className="stat-big" style={{ font: "600 30px/1 var(--display)", color: "var(--blue)" }}>{d.avg_score ?? "-"}</div>
          <div className="faint">average score today</div>
        </div>
      </div>
      <div className="card">
        <h3>Parts washed today</h3>
        {d.washes ? ZONES.map((z) => (
          <Meter key={z} label={ZONE_NAMES[z]} value={d.zones[z]} text={`${Math.round(d.zones[z] * 100)}%`} kind={d.zones[z] >= 1 ? "ok" : undefined} />
        )) : <p className="muted" style={{ margin: 0 }}>No washes yet today.</p>}
      </div>
    </>
  );
}

function Week() {
  const { data: w, error } = useApi<WeekProgress>("/api/v1/app/progress?period=week");
  if (!w) return <Loading error={error} />;
  const top = Math.max(w.goal, ...w.per_day, 1);
  const today = localIso();
  const dayIso = (i: number) => new Date(new Date(`${w.start}T12:00:00`).getTime() + i * 86400000).toLocaleDateString("en-CA");
  return (
    <>
      <div className="tiles">
        <div className="tile"><b>{w.washes}</b><span>washes</span></div>
        <div className="tile">
          <b>{w.avg_score ?? "-"}</b>
          <span>avg score {w.avg_change ? <span className={w.avg_change > 0 ? "up" : "down"}>{w.avg_change > 0 ? "↑" : "↓"}{Math.abs(w.avg_change)}</span> : null}</span>
        </div>
        <div className="tile"><b>{w.clean_washes}</b><span>clean washes</span></div>
      </div>
      <div className="card">
        <h3>Washes per day</h3>
        <div style={{ position: "relative", height: 130, display: "flex", alignItems: "flex-end", gap: 10, padding: "0 4px" }}>
          <div style={{ position: "absolute", left: 0, right: 0, bottom: `${(w.goal / top) * 100}%`, borderTop: "2px dashed #c3d2e3" }} />
          {w.per_day.map((n, i) => {
            const iso = dayIso(i);
            return (
              <div key={i} title={`${n} washes`} style={{
                flex: 1, height: `${Math.max(n / top, 0.03) * 100}%`, borderRadius: 8, transition: "height 0.6s ease",
                background: iso === today ? "var(--blue-btn)" : iso > today ? "#e6edf5" : "var(--navy)",
              }} />
            );
          })}
        </div>
        <div style={{ display: "flex", gap: 10, padding: "6px 4px 0" }}>
          {DOW.map((d, i) => <span key={i} className="faint" style={{ flex: 1, textAlign: "center" }}>{d}</span>)}
        </div>
        <p className="faint" style={{ margin: "8px 0 0" }}>- - goal: {w.goal} a day</p>
      </div>
      <div className="card">
        <h3 style={{ marginBottom: 4 }}>Trouble spots this week</h3>
        <p className="faint" style={{ margin: "0 0 12px" }}>Share of washes that missed each part</p>
        {w.trouble_spots.length ? w.trouble_spots.slice(0, 4).map((s) => (
          <div key={s.zone} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Germ id={germFor(s.zone)} size={26} />
            <div style={{ flex: 1 }}><Meter label={s.name} value={s.missed} text={`${Math.round(s.missed * 100)}%`} kind="missed" /></div>
          </div>
        )) : <p className="muted" style={{ margin: 0 }}>{w.washes ? "No spots missed this week. Great scrubbing!" : "No washes this week yet."}</p>}
      </div>
    </>
  );
}

function Month() {
  const { data: m, error } = useApi<MonthProgress>("/api/v1/app/progress?period=month");
  if (!m) return <Loading error={error} />;
  const title = new Date(m.year, m.month - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const today = new Date();
  const isThisMonth = today.getFullYear() === m.year && today.getMonth() + 1 === m.month;
  return (
    <div className="card">
      <h3 style={{ textAlign: "center", color: "var(--blue)", fontFamily: "var(--display)", fontSize: 18 }}>{title}</h3>
      <div className="cal">
        {DOW.map((d, i) => <span key={i} className="dow">{d}</span>)}
        {Array.from({ length: m.first_weekday }, (_, i) => <span key={`pad${i}`} />)}
        {m.days.map((d) => (
          <div key={d.day} className={`day ${isThisMonth && d.day === today.getDate() ? "today" : ""}`} title={`${d.washes} washes`}>
            <Ring value={d.fill} size={30} stroke={5} color={d.fill >= 1 ? "#57c94a" : "var(--blue-btn)"} />
            {d.day}
          </div>
        ))}
      </div>
      <p className="faint" style={{ margin: "12px 0 0", textAlign: "center" }}>{m.washes} washes this month · a full ring is {m.goal} washes in a day</p>
    </div>
  );
}

export default function Progress() {
  const [period, setPeriod] = useState<Period>("week");
  const { data: kid } = useApi<Child | null>("/api/v1/app/child");
  const { data: overview } = useApi<WeekProgress>("/api/v1/app/progress?period=week");
  return (
    <div className="page fade-in">
      <PageHead title={kid ? `${kid.name}'s progress` : "Progress"} />
      <Seg options={[["day", "Day"], ["week", "Week"], ["month", "Month"]]} value={period} onChange={setPeriod} />
      {overview && !overview.washes && !overview.clean_washes ? (
        <Empty title="Progress starts with a wash">Run the Scrubby station. Charts fill in as washes come in.</Empty>
      ) : period === "day" ? <Day /> : period === "week" ? <Week /> : <Month />}
    </div>
  );
}
