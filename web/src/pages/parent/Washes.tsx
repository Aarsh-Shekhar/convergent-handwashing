import { useState } from "react";
import { useApi, type Child, type WashView } from "../../api";
import { KidPicker } from "../../components/Nav";
import { EmptyState, PageHead, Pending, SegmentedTabs } from "../../components/ui";
import { WashTable } from "./Overview";

type Range = "today" | "week" | "month" | "all";
const DAYS: Record<Range, number> = { today: 1, week: 7, month: 31, all: 100000 };
const SHOW = 60; // rows drawn at once

/** A date (YYYY-MM-DD) in the family's timezone, the same way the backend names a wash's day. */
function dayIso(offsetDays: number, tz: string): string {
  return new Date(Date.now() + offsetDays * 86400000).toLocaleDateString("en-CA", { timeZone: tz });
}

export default function Washes() {
  const { data, error, reload } = useApi<WashView[]>("/api/v1/app/washes");
  const { data: kid } = useApi<Child | null>("/api/v1/app/child");
  const { data: settings } = useApi<{ timezone: string }>("/api/v1/app/settings");
  const [range, setRange] = useState<Range>("week");
  const [only, setOnly] = useState<"all" | "missed">("all");
  const [more, setMore] = useState(false);
  const tz = settings?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  const inRange = (data ?? []).filter((w) => w.day >= dayIso(1 - DAYS[range], tz)).filter((w) => only === "all" || (w.stars > 0 && w.missed.length > 0));
  const shown = more ? inRange : inRange.slice(0, SHOW);
  return (
    <div className="page">
      <PageHead title="Washes" sub={kid ? `Every wash recorded for ${kid.name}. ${inRange.length} shown.` : undefined}>
        <KidPicker />
        <SegmentedTabs label="Filter" options={[["all", "All"], ["missed", "Missed a zone"]]} value={only} onChange={setOnly} />
        <SegmentedTabs label="Time range" options={[["today", "Today"], ["week", "Week"], ["month", "Month"], ["all", "All"]]} value={range} onChange={(v) => { setRange(v); setMore(false); }} />
      </PageHead>
      {!data ? <Pending error={error} retry={reload} blocks={3} /> : !shown.length ? (
        <EmptyState title="No washes here">Nothing matches this time range and filter. A wash appears the moment it ends at the sink.</EmptyState>
      ) : (
        <section className="card"><div className="table-wrap"><WashTable washes={shown} /></div></section>
      )}
      {!more && inRange.length > SHOW && <p className="center"><button type="button" className="link" onClick={() => setMore(true)}>Show {inRange.length - SHOW} more</button></p>}
    </div>
  );
}
