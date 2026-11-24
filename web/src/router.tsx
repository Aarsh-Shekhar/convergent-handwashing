// A tiny router: the app has a handful of screens, so the browser history API is all it needs.
import { useSyncExternalStore, type AnchorHTMLAttributes } from "react";

const subscribe = (cb: () => void) => {
  window.addEventListener("popstate", cb);
  return () => window.removeEventListener("popstate", cb);
};
const here = () => window.location.pathname + window.location.search;

/** The current path. Query strings are left to the page that owns them. */
export function usePath(): string {
  return useSyncExternalStore(subscribe, () => window.location.pathname);
}
export function useQuery(key: string): string | null {
  return useSyncExternalStore(subscribe, () => new URLSearchParams(window.location.search).get(key));
}

export function go(path: string, replace = false) {
  if (path === here()) return;
  const samePage = path.split("?")[0] === window.location.pathname;
  history[replace ? "replaceState" : "pushState"]({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
  if (!samePage) window.scrollTo(0, 0);
}

export function Link({ to, ...rest }: { to: string } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a
      href={to}
      {...rest}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return; // let the browser open a new tab
        e.preventDefault();
        go(to);
      }}
    />
  );
}
