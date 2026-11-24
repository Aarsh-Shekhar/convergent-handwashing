// Typed calls to the laptop backend (/api/v1/app/*). All progress maths happens there; the app only draws it.
import { useCallback, useEffect, useState } from "react";
import { useLive } from "./live";

export type Zone = "palms" | "between_fingers" | "thumbs" | "nails" | "backs" | "wrists";
export const ZONES: Zone[] = ["palms", "between_fingers", "thumbs", "nails", "backs", "wrists"];
export const ZONE_NAMES: Record<Zone, string> = {
  palms: "Palms", between_fingers: "Between fingers", thumbs: "Thumbs", nails: "Nails & tips", backs: "Backs", wrists: "Wrists",
};

export type Child = { name: string; buddy: string; age_band: string };
export type WashView = {
  wash_id: string; ended: string; day: string; time: string; label: string;
  stars: number; points: number; finished: boolean; steps_done: number; zaps: number; seconds_total: number;
  coverage: Record<Zone, number>; missed: Zone[];
};
export type WashDetail = WashView & {
  seconds: Record<string, number>; duration_s: number; soap_seen: boolean | null; step_min_s: number; total_min_s: number;
};
export type Spot = { zone: Zone; name: string; missed: number };
export type Home = {
  today: number; goal: number; avg_score: number | null; clean_washes: number; latest: WashView | null; tip: Spot | null;
  parent_name: string; child: Child | null;
};
export type DayProgress = { period: "day"; date: string; washes: number; goal: number; avg_score: number | null; zones: Record<Zone, number> };
export type WeekProgress = {
  period: "week"; start: string; washes: number; per_day: number[]; goal: number; avg_score: number | null; avg_change: number | null;
  clean_washes: number; trouble_spots: Spot[];
};
export type MonthProgress = {
  period: "month"; year: number; month: number; first_weekday: number; washes: number; goal: number;
  days: { day: number; washes: number; fill: number }[];
};
export type Settings = {
  parent_name: string; timezone: string; daily_goal: number; onboarded: boolean;
  routines: { id: string; name: string; detail: string; time: string | null; on: boolean }[];
  toggles: Record<string, boolean>;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!r.ok) {
    const body = await r.json().catch(() => null);
    throw new Error(body?.error ?? `${r.status} ${r.statusText}`);
  }
  return r.json() as Promise<T>;
}

/** Fetch a page's data, and fetch it again whenever the station saves a new wash. */
export function useApi<T>(path: string) {
  const { savedCount } = useLive();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api<T>(path).then((d) => { setData(d); setError(null); }, (e: Error) => setError(e.message));
  }, [path]);
  useEffect(load, [load, savedCount]);
  return { data, error, reload: load };
}

/** Today's date (YYYY-MM-DD) in the browser's timezone, to label "Today" and "Yesterday". */
export function localIso(offsetDays = 0): string {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return d.toLocaleDateString("en-CA");
}
