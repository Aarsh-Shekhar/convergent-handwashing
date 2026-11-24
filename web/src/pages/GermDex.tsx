import { useState } from "react";
import { send, useApi, ZONE_MOVES, ZONE_NAMES, type ApiError, type GermDex as Dex, type GermShop } from "../api";
import { CaveScene } from "../art/scenes";
import { Creature } from "../components/Creature";
import { Icon } from "../components/icons";
import { Bar, GameButton, InlineError, Pending, Sheet, TopBar } from "../components/ui";
import { GERM_NAMES, HIDES, RARITY, WHY } from "../germs";
import { useLive } from "../live";
import "./GermDex.css";

type Germ = Dex["germs"][number];

function GermSheet({ g, shop, onClose }: { g: Germ; shop: GermShop | null; onClose: () => void }) {
  const { refresh } = useLive();
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const offer = shop?.germs.find((x) => x.id === g.id);
  const buy = () => {
    setBusy(true);
    send("POST", "/api/v1/app/rewards/buy", { germ: g.id }).then(() => { refresh(); onClose(); }, (e: ApiError) => { setError(e); setBusy(false); });
  };
  return (
    <Sheet title={g.owned ? g.name : "Not met yet"} onClose={onClose}>
      <div className="germ-sheet">
        <Creature id={g.id} size={148} locked={!g.owned} bob={g.owned} />
        <div className="tags"><span className="tag">{RARITY[g.rarity]}</span><span className="tag">Hides {HIDES[g.zone]}</span></div>
        <p>{WHY[g.zone]}</p>
        <p className="how"><b>How to zap it:</b> {ZONE_MOVES[g.zone]}.</p>
        <p className="count"><b className="num">{g.zapped}</b> {g.zapped === 1 ? "wash" : "washes"} where {ZONE_NAMES[g.zone].toLowerCase()} got their full scrub</p>
        {!g.owned && (g.price === null
          ? <p className="faint">This one is a boss prize. Beat it as boss of the week to add it.</p>
          : <GameButton tone="gold" wide icon="bolt" disabled={busy || !offer?.can_buy} onClick={buy}>
              {offer?.can_buy ? `Add for ${g.price} zaps` : `${g.price} zaps needed (you have ${shop?.zaps ?? 0})`}
            </GameButton>)}
        {error && <InlineError error={error} />}
        <p className="faint">Germs here are game characters. The camera recognizes scrubbing motions, not real germs.</p>
      </div>
    </Sheet>
  );
}

export default function GermDex() {
  const { data: dex, error, reload } = useApi<Dex>("/api/v1/app/germdex");
  const { data: shop } = useApi<GermShop>("/api/v1/app/rewards");
  const [open, setOpen] = useState<string | null>(null);
  const picked = dex?.germs.find((g) => g.id === open);
  return (
    <div className="page dex">
      <TopBar title="Germ-dex" right={dex && <span className="dex-count num" aria-label={`${dex.owned} of ${dex.germs.length} germs collected`}>{dex.owned}/{dex.germs.length}</span>} />
      {!dex ? <Pending error={error} retry={reload} blocks={3} /> : (
        <>
          <section className="panel violet illustrated boss">
            <div className="scene" aria-hidden="true"><CaveScene tint="#f58fa0" /></div>
            <div className="content">
              <div className="words">
                <div className="caps-line">Boss of the week</div>
                <h2>{GERM_NAMES[dex.boss.germ]}</h2>
                <p>Hides {HIDES[dex.boss.zone]}. Give {ZONE_NAMES[dex.boss.zone].toLowerCase()} a full scrub in {dex.boss.target} washes this week to win.</p>
                <div className="boss-bar"><Bar value={dex.boss.done / dex.boss.target} label="Boss progress" /><span className="num">{dex.boss.done}/{dex.boss.target}</span></div>
                {dex.boss.won && <span className="tag gold"><Icon name="crown" size={14} />Beaten this week</span>}
              </div>
              <Creature id={dex.boss.germ} size={132} className="boss-art" bob />
            </div>
          </section>

          <div className="dex-head"><h2 className="section">Collection</h2>{shop && <span className="tag gold"><Icon name="bolt" size={14} />{shop.zaps} zaps to spend</span>}</div>
          <ul className="dex-grid">
            {dex.germs.map((g) => (
              <li key={g.id}>
                <button type="button" className={`creature-card ${g.owned ? "" : "locked"} ${g.rarity}`} onClick={() => setOpen(g.id)}
                  aria-label={g.owned ? `${g.name}, zapped ${g.zapped} times. Details` : `Germ not met yet. Hides ${HIDES[g.zone]}. Details`}>
                  <span className="pad"><Creature id={g.id} size={92} locked={!g.owned} /></span>
                  <b>{g.owned ? g.name : "???"}</b>
                  {g.owned
                    ? <small className="num">zapped ×{g.zapped}</small>
                    : <small><Icon name="lock" size={13} />{g.price === null ? "Boss prize" : `${g.price} zaps`}</small>}
                </button>
              </li>
            ))}
          </ul>
          <p className="faint note">"Zapped" counts the washes where that germ's part of the hand got its full scrub.</p>
        </>
      )}
      {picked && <GermSheet g={picked} shop={shop} onClose={() => setOpen(null)} />}
    </div>
  );
}
