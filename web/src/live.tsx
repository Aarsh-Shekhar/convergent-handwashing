// One WebSocket to the backend's live feed (/ws/v1/observations), shared by every page.
//   saved      the latest wash the station saved (`wash_saved`)
//   epoch      goes up whenever pages should load again: a wash was saved, the active child changed,
//              or the connection came back after a drop (washes may have landed meanwhile)
//   liveAt     when the wash software last sent a `live` update (it sends 5 a second while it runs)
// If the socket cannot stay open, pages still catch up by polling every 20 s.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { WashView } from "./api";

type LiveState = { connected: boolean; liveAt: number; saved: WashView | null; epoch: number };
type Live = LiveState & { refresh: () => void };

const Ctx = createContext<Live>({ connected: false, liveAt: 0, saved: null, epoch: 0, refresh: () => {} });
export const useLive = () => useContext(Ctx);

const POLL_MS = 20_000;

export function LiveProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LiveState>({ connected: false, liveAt: 0, saved: null, epoch: 0 });
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
        const msg = JSON.parse(e.data as string) as { type: string; wash?: WashView };
        if (msg.type === "live") setState((s) => ({ ...s, liveAt: Date.now() }));
        else if (msg.type === "wash_saved" && msg.wash) setState((s) => ({ ...s, saved: msg.wash!, epoch: s.epoch + 1 }));
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

/** True while the wash software is sending live updates (none for 2.5 s means it stopped). */
export function useStationActive(): boolean {
  const { liveAt } = useLive();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return now - liveAt < 2500;
}
