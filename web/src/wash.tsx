// Small pieces every wash list shares: how a wash's result and origin are worded.
import { ZONE_NAMES, type WashView } from "./api";

/** What a wash missed, in words. "Nothing recognized" is never shown as six misses or as a perfect wash. */
export function missedText(w: Pick<WashView, "stars" | "missed">): string {
  if (w.stars === 0) return "Nothing recognized";
  if (!w.missed.length) return "All zones washed";
  return w.missed.map((z) => ZONE_NAMES[z]).join(", ");
}

export function MissedTags({ w, max = 2 }: { w: Pick<WashView, "stars" | "missed">; max?: number }) {
  if (w.stars === 0) return <span className="tag">Nothing recognized</span>;
  if (!w.missed.length) return <span className="tag good">All zones washed</span>;
  if (w.missed.length > max) return <span className="tag miss">Missed {w.missed.length} zones</span>;
  return <>{w.missed.map((z) => <span key={z} className="tag miss">Missed {ZONE_NAMES[z].toLowerCase()}</span>)}</>;
}

/** Where a wash came from. Seeded and simulated washes are always marked. */
export function SourceTag({ source }: { source: "station" | "demo" }) {
  return source === "station" ? <span className="tag sink">From the sink</span> : <span className="tag demo">Demo data</span>;
}

export const isDemoId = (washId: string) => washId.startsWith("demo-");
export const when = (iso: string) => new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
export const clock = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" });
