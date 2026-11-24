// Typed calls to the backend (/api/v1/app/*). Every number shown in the app is worked out there
// (scoring/progression.py); the app only draws it.
import { useCallback, useEffect, useRef, useState } from "react";
import { useLive } from "./live";

export type Zone = "palms" | "between_fingers" | "thumbs" | "nails" | "backs" | "wrists";
export const ZONES: Zone[] = ["palms", "between_fingers", "thumbs", "nails", "backs", "wrists"];
export const ZONE_NAMES: Record<Zone, string> = {
  palms: "Palms", between_fingers: "Between fingers", thumbs: "Thumbs", nails: "Nails & tips", backs: "Backs", wrists: "Wrists",
};
/** The scrubbing motion that washes each zone, in words a parent can say out loud. */
export const ZONE_MOVES: Record<Zone, string> = {
  palms: "rub palm on palm",
  between_fingers: "lace the fingers together and slide",
  thumbs: "wrap one hand around the other thumb and twist",
  nails: "scrub fingertips in the other palm",
  backs: "rub the back of each hand and the backs of the fingers",
  wrists: "twist a hand around each wrist",
};

export type AgeBand = "3-4" | "5-6" | "7-8" | "9+";
export type Child = { id: number; name: string; buddy: string; age_band: AgeBand; active?: boolean };
export type Boss = { germ: string; zone: Zone; done: number; target: number; won: boolean };
export type WashView = {
  wash_id: string; ended: string; day: string; time: string; label: string;
  stars: number; points: number; finished: boolean; steps_done: number; zaps: number; reward_points: number; capped: boolean; seconds_total: number;
  coverage: Record<Zone, number>; missed: Zone[];
};
export type WashDetail = WashView & {
  seconds: Record<string, number>; duration_s: number; soap_seen: boolean | null; step_min_s: number; total_min_s: number;
  steps_required: number; session_id: string; source: "station" | "demo"; received: string;
  model: { version?: string } | null; high_fived: string | null;
  steps: { technique: string; name: string; seconds: number; done: boolean; points: number }[]; time_points: number; started: string; lag_s: number;
};
export type Spot = { zone: Zone; name: string; missed: number };
export type Home = {
  today: number; zap_washes_today: number; goal: number; avg_score: number | null; clean_washes: number; latest: WashView | null; tip: Spot | null;
  parent_name: string; child: Child | null; streak: number; points: number; zaps: number; boss: Boss; onboarded: boolean;
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
export type Stage = {
  id: "bubble_bay" | "germ_jungle" | "soap_canyon" | "bacteria_castle"; name: string; unlock_at: number; unlocked: boolean; stones_lit: number;
  first_level: number; last_level: number; levels_done: number; germs: string[];
};
/** One rewarded wash = one level on the map path. */
export type Level = { n: number; wash_id: string; stars: number; points: number; perfect: boolean };
export type Quest = { id: "wash" | "stars" | "zone"; have: number; need: number; done: boolean; zone?: Zone; zone_name?: string };
export type Quests = { today: Quest[]; done_today: number; all_done: boolean; full_days_this_week: number };
export type Care = { name: string; email: string; phone: string; booking_url: string };
export type Adventure = {
  rewarded_washes: number; stones: number; stages: Stage[]; next: { id: Stage["id"]; name: string; washes_left: number } | null;
  levels: Level[]; chest_every: number; chests_opened: number; quests: Quests;
  streak: { current: number; best: number }; boss: Boss;
};
export type GermInfo = { id: string; name: string; rarity: "common" | "rare" | "legendary" | "boss"; price: number | null; zone: Zone; owned: boolean };
export type GermDex = { slots: number; owned: number; germs: (GermInfo & { zapped: number })[]; boss: Boss };
export type GermShop = { zaps: number; germs: (GermInfo & { can_buy: boolean })[]; boss: Boss };
export type Badge = { id: string; name: string; earned: boolean; have: number; need: number };
export type RewardIcon = "gift" | "book" | "movie" | "park" | "treat" | "game";
export type Reward = { id: number; title: string; cost: number; icon: RewardIcon; enabled: boolean; affordable: boolean; to_go: number };
export type Redemption = { id: number; request_id: string; reward_id: number | null; title: string; cost: number; status: "requested" | "approved" | "declined"; requested: string; decided: string | null };
export type RewardsPage = {
  points: number; earned: number; held: number; rewards: Reward[]; next: { id: number; title: string; to_go: number } | null;
  requests: Redemption[]; badges: Badge[]; rule: { max_per_wash: number; rewarded_washes_per_day: number };
};
export type Routine = { id: string; name: string; detail: string; time: string | null; on: boolean };
export type Settings = { parent_name: string; timezone: string; daily_goal: number; onboarded: boolean; routines: Routine[]; toggles: Record<string, boolean> };
export type Station = {
  backend: string; version: string; online: boolean; last_seen: string | null; last_wash: string | null; watching: number;
  devices: { device_id: string; status: string; last_seen: string | null }[];
  rules: { scrub_goal_s: number; step_min_s: number; steps_required: number; model: { version?: string } | null } | null;
  demo_mode: boolean;
};
export type Insights = {
  days: number; from: string; to: string; n: number; not_recognized: number; goal: number;
  score: { mean: number | null; median: number | null; best: number | null; previous_mean: number | null; previous_n: number; change: number | null };
  scrub: { mean_s: number | null; goal_s: number; reached_goal: number };
  finished: number; perfect: number; days_with_wash: number; days_goal_met: number;
  per_day: { date: string; washes: number; avg_score: number | null }[];
  zones: { zone: Zone; name: string; coverage: number | null; full: number; partial: number; missed: number; n: number }[];
  techniques: { technique: string; name: string; mean_s: number | null; done: number; n: number }[];
  by_time: { block: string; from_hour: number; to_hour: number; washes: number; avg_score: number | null }[];
};
export type SyncLog = {
  total: number; from_station: number; from_demo: number;
  log: { wash_id: string; session_id: string; source: "station" | "demo"; ended: string; received: string; lag_s: number; points: number; bytes: number }[];
  example: { wash_id: string; source: "station" | "demo"; record: Record<string, unknown> } | null;
};
export type ParentState = { pin_set: boolean; unlocked: boolean };

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

let parentToken: string | null = null;
export function setParentToken(token: string | null) { parentToken = token; }

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(parentToken ? { "X-Parent-Token": parentToken } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError("Can't reach Scrubble on this network", 0);
  }
  if (!r.ok) {
    const body = await r.json().catch(() => null) as { error?: string } | null;
    throw new ApiError(body?.error ?? `${r.status} ${r.statusText}`, r.status);
  }
  return r.json() as Promise<T>;
}
export const send = <T,>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown) =>
  api<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

/**
 * Load a page's data. It loads again when the station saves a wash, when the active child changes,
 * and when the live connection comes back. A slower answer to an older request never replaces a newer one.
 */
export function useApi<T>(path: string) {
  const { epoch } = useLive();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const seq = useRef(0);
  const load = useCallback(() => {
    const mine = ++seq.current;
    api<T>(path).then(
      (d) => { if (mine === seq.current) { setData(d); setError(null); } },
      (e: ApiError) => { if (mine === seq.current) setError(e); },
    );
  }, [path]);
  useEffect(() => { load(); return () => { seq.current++; }; }, [load, epoch]);
  return { data, error, reload: load };
}

/** A unique id for a write the server must apply once (a reward request). */
export function requestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
