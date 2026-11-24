import { useState } from "react";
import { localIso, useApi, type Child, type WashView } from "../api";
import { Empty, Loading, PageHead, Seg } from "../components/ui";
import { WashCard } from "../components/WashCard";

type Range = "today" | "week" | "month";
const DAYS: Record<Range, number> = { today: 1, week: 7, month: 31 };

function dayTitle(iso: string): string {
  if (iso === localIso()) return "Today";
  if (iso === localIso(-1)) return "Yesterday";
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}

export default function Washes() {
  const { data, error } = useApi<WashView[]>("/api/v1/app/washes");
  const { data: kid } = useApi<Child | null>("/api/v1/app/child");
  const [range, setRange] = useState<Range>("week");
  const from = localIso(1 - DAYS[range]);
  const shown = (data ?? []).filter((w) => w.day >= from);
  const days = [...new Set(shown.map((w) => w.day))];
  return (
    <div className="page fade-in">
      <PageHead title={kid ? `${kid.name}'s washes` : "Washes"} back={() => history.back()} />
      <Seg options={[["today", "Today"], ["week", "Week"], ["month", "Month"]]} value={range} onChange={setRange} />
      {!data ? <Loading error={error} /> : !shown.length ? (
        <Empty title="Nothing here yet">No washes in this time. Washes from the station land here live.</Empty>
      ) : days.map((d) => (
        <section key={d}>
          <div className="label-caps">{dayTitle(d)}</div>
          {shown.filter((w) => w.day === d).map((w) => <WashCard key={w.wash_id} w={w} />)}
        </section>
      ))}
    </div>
  );
}
