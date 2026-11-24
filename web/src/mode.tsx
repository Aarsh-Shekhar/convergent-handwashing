// Two switches decide what the app looks like.
//   view    kid or grown-up. It follows the address: /kid/... is the kid view, everything else is the grown-up view.
//   device  phone or desktop. On a wide screen the person picks; a real phone is always the phone layout.
// Choosing "phone" on a wide screen shows the app inside a phone outline (an iframe of this same app),
// so it behaves exactly like it does on a real phone.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { usePath } from "./router";

export type View = "kid" | "parent";
export type Device = "phone" | "desktop";
type Mode = { view: View; layout: Device; canPickDevice: boolean; device: Device; setDevice: (d: Device) => void; framed: boolean };

const KEY = "scrubble.device";
const WIDE = "(min-width: 900px)";
export const FRAMED = typeof window !== "undefined" && (new URLSearchParams(window.location.search).has("frame") || window.self !== window.top);

function saved(): Device {
  try { return localStorage.getItem(KEY) === "phone" ? "phone" : "desktop"; } catch { return "desktop"; }
}

const Ctx = createContext<Mode>({ view: "parent", layout: "phone", canPickDevice: false, device: "desktop", setDevice: () => {}, framed: false });
export const useMode = () => useContext(Ctx);
export const viewOf = (path: string): View => (path === "/kid" || path.startsWith("/kid/") ? "kid" : "parent");

export function ModeProvider({ children }: { children: ReactNode }) {
  const path = usePath();
  const [wide, setWide] = useState(() => window.matchMedia(WIDE).matches);
  const [device, setDeviceState] = useState<Device>(saved);
  useEffect(() => {
    const mq = window.matchMedia(WIDE);
    const on = () => setWide(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  const value = useMemo<Mode>(() => ({
    view: viewOf(path),
    layout: FRAMED || !wide ? "phone" : device,
    canPickDevice: wide && !FRAMED,
    device,
    framed: FRAMED,
    setDevice: (d) => { try { localStorage.setItem(KEY, d); } catch { /* the choice just lasts until reload */ } setDeviceState(d); },
  }), [path, wide, device]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
