import { useState } from "react";
import { useApi, type Child, type WashView } from "../api";
import { EmptyState, Pending, SegmentedTabs, TopBar } from "../components/ui";
import { WashRow } from "../components/WashSummary";

type Range = "today" | "week" | "month";
const DAYS: Record<Range, number> = { today: 1, week: 7, month: 31 };
const SHOW = 60; // rows drawn at once; a month at the daily goal is well past this

/** A date (YYYY-MM-DD) in the family's timezone, the same way the backend names a wash's day. */
function dayIso(offsetDays: number, tz: string): string {
  return new Date(Date.now() + offsetDays * 86400000).toLocaleDateString("en-CA", { timeZone: tz });
}
function dayTitle(iso: string, tz: string): string {
  if (iso === dayIso(0, tz)) return "Today";
  if (iso === dayIso(-1, tz)) return "Yesterday";
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}

export default function History() {
  const { data, error, reload } = useApi<WashView[]>("/api/v1/app/washes");
  const { data: kid } = useApi<Child | null>("/api/v1/app/child");
  const { data: settings } = useApi<{ timezone: string }>("/api/v1/app/settings");
  const [range, setRange] = useState<Range>("week");
  const [more, setMore] = useState(false);
  const tz = settings?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  const inRange = (data ?? []).filter((w) => w.day >= dayIso(1 - DAYS[range], tz));
  const shown = more ? inRange : inRange.slice(0, SHOW);
  const days = [...new Set(shown.map((w) => w.day))];
  return (
    <div className="page">
      <TopBar title={kid ? `${kid.name}'s washes` : "Washes"} back="/" />
      <SegmentedTabs label="Time range" options={[["today", "Today"], ["week", "Week"], ["month", "Month"]]} value={range}
        onChange={(v) => { setRange(v); setMore(false); }} />
      {!data ? <Pending error={error} retry={reload} blocks={4} /> : !shown.length ? (
        <EmptyState title="Nothing here yet">No washes in this time. A wash lands here the moment it ends at the sink.</EmptyState>
      ) : days.map((d) => (
        <section key={d} aria-label={dayTitle(d, tz)}>
          <h2 className="caps">{dayTitle(d, tz)}</h2>
          {shown.filter((w) => w.day === d).map((w) => <WashRow key={w.wash_id} w={w} />)}
        </section>
      ))}
      {!more && inRange.length > SHOW && (
        <p className="center" style={{ marginTop: 16 }}><button type="button" className="linkish" onClick={() => setMore(true)}>Show {inRange.length - SHOW} more</button></p>
      )}
    </div>
  );
}
