// One WebSocket to the backend's live feed (/ws/v1/observations), shared by every page.
//   live        the wash software's latest `live` message (5 per second while it runs)
//   saved       the latest wash the station saved (`wash_saved`); savedCount makes pages refetch
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { WashView } from "./api";

export type LiveMsg = {
  ts: number; hands: number;
  fused?: { status: string; technique: string | null; confidence: number | null };
  active?: { technique: string; supported_s: number; validated: boolean } | null;
  score?: { steps: { technique: string; seconds: number; done: boolean }[]; steps_done: number; total_s: number; points: number; stars: number; finished: boolean; step_min_s: number } | null;
  wash?: unknown;
};
type LiveState = { connected: boolean; live: LiveMsg | null; liveAt: number; saved: WashView | null; savedCount: number };

const Ctx = createContext<LiveState>({ connected: false, live: null, liveAt: 0, saved: null, savedCount: 0 });
export const useLive = () => useContext(Ctx);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LiveState>({ connected: false, live: null, liveAt: 0, saved: null, savedCount: 0 });
  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry = 1000;
    let timer = 0;
    let closed = false;
    const open = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/v1/observations`);
      ws.onopen = () => { retry = 1000; setState((s) => ({ ...s, connected: true })); };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === "live") setState((s) => ({ ...s, live: msg, liveAt: Date.now() }));
        else if (msg.type === "wash_saved") setState((s) => ({ ...s, saved: msg.wash, savedCount: s.savedCount + 1 }));
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
  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}

/** True while the wash software is sending live messages (it stops 2 s after the last one). */
export function useStationActive(): boolean {
  const { liveAt } = useLive();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return now - liveAt < 2500;
}
