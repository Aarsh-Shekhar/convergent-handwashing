// Rewards (kid-facing): zaps earned by washing, the germ playground, the germ shop and badges.
import { useEffect, useState } from "react";
import { api, useApi, ZONE_NAMES, type Child, type GermInfo, type Rarity, type Rewards as Data, type Zone } from "../api";
import { Germ } from "../components/germs";
import { Icon, Loading, PageHead } from "../components/ui";

const RARITY: [Rarity, string][] = [["common", "Common"], ["rare", "Rare"], ["legendary", "Legendary"]];
const BADGE_ICON: Record<string, string> = { first_clean: "spark", perfect_10: "star", thumb_pro: "hand" };
// where owned germs stand in the playground (left %, bottom %)
const SPOTS = [[14, 34], [74, 40], [40, 12], [86, 8], [8, 6], [58, 52], [28, 56], [64, 18]];

export const livesOn = (z: Zone) => (z === "between_fingers" ? "Hides between fingers" : `Hides on ${ZONE_NAMES[z].toLowerCase()}`);

function Bolt({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M13.5 2 4.5 13.5h6L9.5 22l9-11.5h-6z" fill="#f6b93b" stroke="#a86b00" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

function Playground({ owned }: { owned: GermInfo[] }) {
  const [jump, setJump] = useState<string | null>(null);
  return (
    <div className="playground" aria-label="Germ playground">
      <div className="bush b1" /><div className="bush b2" /><div className="bush b3" />
      <div className="scrubby-spot"><Germ id="scrubby" size={76} bob /></div>
      {owned.map((g, i) => {
        const [x, y] = SPOTS[i % SPOTS.length];
        return (
          <button key={g.id} className={`pg-germ ${jump === g.id ? "jump" : ""}`} style={{ left: `${x}%`, bottom: `${y}%` }}
            onClick={() => { setJump(g.id); window.setTimeout(() => setJump(null), 600); }} aria-label={g.name}>
            <Germ id={g.id} size={48} bob className={`delay${i % 4}`} />
          </button>
        );
      })}
      <span className="pg-label">{owned.length} {owned.length === 1 ? "germ" : "germs"} caught</span>
    </div>
  );
}

function ShopRow({ g, onBuy, asking, busy }: { g: GermInfo; onBuy: () => void; asking: boolean; busy: boolean }) {
  return (
    <div className={`shop-row ${g.owned ? "owned" : ""}`}>
      <Germ id={g.id} size={44} dim={!g.owned && !g.can_buy} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="title">{g.name}</div>
        <div className="faint">{livesOn(g.zone)}</div>
      </div>
      {g.owned ? <span className="pill perfect"><Icon name="check" size={12} />Caught</span>
        : g.price === null ? <span className="pill">Boss prize</span>
        : (
          <button className={`buy ${asking ? "confirm" : ""}`} disabled={!g.can_buy || busy} onClick={onBuy}
            aria-label={asking ? `Confirm: catch ${g.name} for ${g.price} zaps` : `Catch ${g.name} for ${g.price} zaps`}>
            {asking ? "Tap to catch!" : <><Bolt size={14} />{g.price}</>}
          </button>
        )}
    </div>
  );
}

export default function Rewards() {
  const { data, error, reload } = useApi<Data>("/api/v1/app/rewards");
  const { data: kid } = useApi<Child | null>("/api/v1/app/child");
  const [r, setR] = useState<Data | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => { if (data) setR(data); }, [data]);
  useEffect(() => { if (!note) return; const t = window.setTimeout(() => setNote(null), 3500); return () => clearTimeout(t); }, [note]);

  if (!r) return <div className="page"><PageHead title="Rewards" /><Loading error={error} /></div>;
  const owned = r.germs.filter((g) => g.owned);
  const buy = (g: GermInfo) => {
    if (asking !== g.id) { setAsking(g.id); return; } // second tap confirms: zaps can't be refunded
    setBusy(true);
    api<Data>("/api/v1/app/rewards/buy", { method: "POST", body: JSON.stringify({ germ: g.id }) })
      .then((next) => { setR(next); setNote(`${g.name} joined the playground!`); }, (e: Error) => { setNote(e.message); reload(); })
      .finally(() => { setBusy(false); setAsking(null); });
  };

  return (
    <div className="page fade-in">
      <PageHead title="Rewards" />
      <div className="card zap-card">
        <div>
          <div className="faint" style={{ color: "#cfe3f7" }}>{kid ? `${kid.name}'s zaps` : "Zaps"}</div>
          <div className="zap-total"><Bolt size={30} />{r.zaps}</div>
        </div>
        <div className="zap-germs">{owned.slice(0, 4).map((g) => <Germ key={g.id} id={g.id} size={34} />)}</div>
      </div>
      <p className="faint" style={{ margin: "8px 4px 0" }}>Earn zaps by washing: 1 for each step done, +3 for a finished wash, up to the daily goal.</p>

      <h2 className="section">Germ playground</h2>
      <Playground owned={owned} />

      <h2 className="section">Catch new germs</h2>
      <div className="card" style={{ padding: "6px 14px" }}>
        {RARITY.map(([rarity, label]) => {
          const list = r.germs.filter((g) => g.rarity === rarity);
          return list.length ? (
            <div key={rarity}>
              <div className={`rarity ${rarity}`}>{label}</div>
              {list.map((g) => <ShopRow key={g.id} g={g} asking={asking === g.id} busy={busy} onBuy={() => buy(g)} />)}
            </div>
          ) : null;
        })}
      </div>

      <h2 className="section">Badges</h2>
      <div className="card badges">
        {r.badges.map((b) => (
          <div key={b.id} className={`badge ${b.earned ? "earned" : ""}`}>
            <span className="medal"><Icon name={BADGE_ICON[b.id] ?? "star"} size={24} /></span>
            <span>{b.name}</span>
          </div>
        ))}
        <div className="badge"><span className="medal"><Icon name="lock" size={22} /></span><span>???</span></div>
      </div>

      {note && <div className="toast" role="status"><Bolt size={28} /><span><b>{note}</b></span></div>}
    </div>
  );
}
