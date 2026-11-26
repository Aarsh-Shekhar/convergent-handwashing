// The germ playground (Andrew's idea, in our night-ocean world): every germ in the collection hangs out on the
// shore. Tap one and it hops and says where it hides. Which germs are here comes from the backend.
import { useRef, useState } from "react";
import { type GermDex } from "../api";
import { HIDES } from "../germs";
import { Creature } from "./Creature";

// where germs stand (left %, bottom %), back row first so nearer ones overlap farther ones
const SPOTS = [[12, 40], [70, 44], [42, 34], [86, 22], [26, 12], [58, 10], [6, 6], [76, 4]];

export function Playground({ germs, buddy }: { germs: GermDex["germs"]; buddy: string }) {
  const owned = germs.filter((g) => g.owned);
  const [hop, setHop] = useState<string | null>(null);
  const timer = useRef(0);
  const poke = (id: string) => { clearTimeout(timer.current); setHop(id); timer.current = window.setTimeout(() => setHop(null), 2200); };
  const said = owned.find((g) => g.id === hop);
  return (
    <section className="playground" aria-label="Germ playground">
      <i className="pg-moon" /><i className="pg-hill h1" /><i className="pg-hill h2" /><i className="pg-shore" />
      <button type="button" className={`pg-germ ${hop === "_buddy" ? "hop" : ""}`} style={{ left: "44%", bottom: "50%" }} onClick={() => poke("_buddy")} aria-label="Your buddy. Tap to say hi">
        <Creature id={buddy} size={70} bob />
      </button>
      {owned.map((g, i) => {
        const [x, y] = SPOTS[i % SPOTS.length];
        return (
          <button type="button" key={g.id} className={`pg-germ ${hop === g.id ? "hop" : ""}`} style={{ left: `${x}%`, bottom: `${y}%`, zIndex: 10 - Math.round(y / 5) }}
            onClick={() => poke(g.id)} aria-label={`${g.name}. Tap to make it hop`}>
            <Creature id={g.id} size={54} bob style={{ animationDelay: `${-0.7 * i}s` }} />
          </button>
        );
      })}
      <p className="pg-say" role="status">{hop === "_buddy" ? "Hi! Tap a germ to make it hop." : said ? `${said.name}: "I hide ${HIDES[said.zone]}!"` : owned.length ? "Tap a germ" : "No germs here yet. Catch one with zaps."}</p>
      <span className="pg-count">{owned.length} {owned.length === 1 ? "germ" : "germs"} caught</span>
    </section>
  );
}
