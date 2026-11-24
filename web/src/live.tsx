// One WebSocket to the backend's live feed (/ws/v1/observations), shared by every page.
//   live       the wash software's latest `live` message (5 a second while it runs): hands in view, the
//              move being scrubbed, the running score. This is what the "Live" screens draw.
//   saved      the latest wash the station saved (`wash_saved`)
//   epoch      goes up whenever pages should load again: a wash was saved, the active child changed,
//              or the connection came back after a drop (washes may have landed meanwhile)
// If the socket cannot stay open, pages still catch up by polling every 20 s.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { WashView } from "./api";

export type LiveMsg = {
  ts: number; hands: number;
  fused?: { status: string; technique: string | null; confidence: number | null };
  active?: { technique: string; supported_s: number; validated: boolean } | null;
  score?: { steps: { technique: string; seconds: number; done: boolean }[]; steps_done: number; total_s: number; points: number; stars: number; finished: boolean; step_min_s: number; total_min_s?: number } | null;
};
type LiveState = { connected: boolean; live: LiveMsg | null; liveAt: number; saved: WashView | null; savedAt: number; epoch: number };
type Live = LiveState & { refresh: () => void };

const START: LiveState = { connected: false, live: null, liveAt: 0, saved: null, savedAt: 0, epoch: 0 };
const Ctx = createContext<Live>({ ...START, refresh: () => {} });
export const useLive = () => useContext(Ctx);

const POLL_MS = 20_000;

export function LiveProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LiveState>(START);
  const refresh = useCallback(() => setState((s) => ({ ...s, epoch: s.epoch + 1 })), []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry = 1000;
    let timer = 0;
    let closed = false;
    let everOpen = false;
    const open = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/v1/observations`);
      ws.onopen = () => {
        retry = 1000;
        setState((s) => ({ ...s, connected: true, epoch: everOpen ? s.epoch + 1 : s.epoch }));
        everOpen = true;
      };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data as string) as LiveMsg & { type: string; wash?: WashView };
        if (msg.type === "live") setState((s) => ({ ...s, live: msg, liveAt: Date.now() }));
        else if (msg.type === "wash_saved" && msg.wash) setState((s) => ({ ...s, saved: msg.wash!, savedAt: Date.now(), epoch: s.epoch + 1 }));
      };
      ws.onclose = () => {
        setState((s) => ({ ...s, connected: false }));
        if (!closed) timer = window.setTimeout(open, retry);
        retry = Math.min(retry * 2, 8000);
      };
    };
    open();
    return () => { closed = true; clearTimeout(timer); ws?.close(); };
  }, []);

  useEffect(() => {
    if (state.connected) return;
    const t = window.setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [state.connected, refresh]);

  const value = useMemo(() => ({ ...state, refresh }), [state, refresh]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** A clock that ticks once a second, for "is it still live" checks. */
function useNow(): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

/** True while the wash software is sending live updates (none for 2.5 s means it stopped). */
export function useStationActive(): boolean {
  const { liveAt } = useLive();
  return useNow() - liveAt < 2500;
}

export type Stage = "off" | "ready" | "scrubbing" | "result";
/**
 * Where a wash is right now, from what actually arrived:
 * off (no live updates) -> ready (station on, no hands) -> scrubbing -> result (a wash was just saved, shown for 12 s).
 */
export function useWashStage(): { stage: Stage; live: LiveMsg | null; saved: WashView | null; now: string | null } {
  const { live, liveAt, saved, savedAt } = useLive();
  const t = useNow();
  const active = t - liveAt < 2500;
  const total = live?.score?.total_s ?? 0;
  const scrubbing = active && !!live && (live.hands > 0 || total > 0);
  const nextWash = liveAt > savedAt && !!live && live.hands > 0 && total > 0; // someone started again after the save
  const now = live?.active?.validated ? live.active.technique : live?.fused?.status === "valid" ? live.fused.technique ?? null : null;
  const stage: Stage = saved && t - savedAt < 12_000 && !nextWash ? "result" : !active ? "off" : scrubbing ? "scrubbing" : "ready";
  return { stage, live, saved, now };
}
