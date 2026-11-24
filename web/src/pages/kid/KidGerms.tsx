import { useState } from "react";
import { send, useApi, ZONE_MOVES, ZONE_NAMES, type ApiError, type GermDex as Dex, type GermShop } from "../../api";
import { Creature } from "../../components/Creature";
import { Icon } from "../../components/icons";
import { Bar, Button, InlineError, Pending, Sheet } from "../../components/ui";
import { GERM_NAMES, HIDES, RARITY, WHY } from "../../germs";
import { useLive } from "../../live";

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
        <Creature id={g.id} size={140} locked={!g.owned} />
        <div className="tags"><span className="tag">{RARITY[g.rarity]}</span><span className="tag">Hides {HIDES[g.zone]}</span></div>
        <p>{WHY[g.zone]}</p>
        <p><b>How to zap it:</b> {ZONE_MOVES[g.zone]}.</p>
        <p className="muted"><b className="num">{g.zapped}</b> {g.zapped === 1 ? "wash" : "washes"} where {ZONE_NAMES[g.zone].toLowerCase()} got their full scrub</p>
        {!g.owned && (g.price === null
          ? <p className="muted">This one is a boss prize. Beat it as boss of the week to add it.</p>
          : <Button tone="gold" wide icon="bolt" disabled={busy || !offer?.can_buy} onClick={buy}>
              {offer?.can_buy ? `Add for ${g.price} zaps` : `${g.price} zaps needed (you have ${shop?.zaps ?? 0})`}
            </Button>)}
        {error && <InlineError error={error} />}
        <p className="muted">Germs here are game characters. The camera recognizes scrubbing, not real germs.</p>
      </div>
    </Sheet>
  );
}

export default function KidGerms() {
  const { data: dex, error, reload } = useApi<Dex>("/api/v1/app/germdex");
  const { data: shop } = useApi<GermShop>("/api/v1/app/rewards");
  const [open, setOpen] = useState<string | null>(null);
  const picked = dex?.germs.find((g) => g.id === open);
  return (
    <div className="page">
      <header className="head">
        <h1 className="h1">Germ collection</h1>
        {dex && <span className="tag num" aria-label={`${dex.owned} of ${dex.germs.length} germs collected`}>{dex.owned}/{dex.germs.length}</span>}
      </header>
      {!dex ? <Pending error={error} retry={reload} blocks={3} /> : (
        <>
          <section className="card boss boss-panel">
            <Creature id={dex.boss.germ} size={104} />
            <div className="grow">
              <span className="muted">Boss of the week</span>
              <h2 style={{ font: "900 24px/1.1 var(--font)" }}>{GERM_NAMES[dex.boss.germ]}</h2>
              <p style={{ fontSize: 14 }}>Hides {HIDES[dex.boss.zone]}. Give {ZONE_NAMES[dex.boss.zone].toLowerCase()} a full scrub in {dex.boss.target} washes this week to win.</p>
              <span className="line"><Bar value={dex.boss.done / dex.boss.target} tone="coral" label="Boss progress" /></span>
              <span className="num muted">{dex.boss.done} of {dex.boss.target}{dex.boss.won ? ". Beaten this week!" : ""}</span>
            </div>
          </section>

          <div className="sec"><h2 className="h2">Your germs</h2>{shop && <span className="tag gold"><Icon name="bolt" size={14} />{shop.zaps} zaps to spend</span>}</div>
          <ul className="germ-grid">
            {dex.germs.map((g) => (
              <li key={g.id}>
                <button type="button" className={`germ-card ${g.owned ? "" : "locked"} ${g.rarity}`} onClick={() => setOpen(g.id)}
                  aria-label={g.owned ? `${g.name}, zapped ${g.zapped} times. Details` : `Germ not met yet. Hides ${HIDES[g.zone]}. Details`}>
                  <span className="pad"><Creature id={g.id} size={88} locked={!g.owned} /></span>
                  <b>{g.owned ? g.name : "???"}</b>
                  {g.owned ? <small className="num">zapped ×{g.zapped}</small> : <small><Icon name="lock" size={13} />{g.price === null ? "Boss prize" : `${g.price} zaps`}</small>}
                </button>
              </li>
            ))}
          </ul>
          <p className="muted center" style={{ marginTop: 14 }}>"Zapped" counts the washes where that germ's part of the hand got its full scrub.</p>
        </>
      )}
      {picked && <GermSheet g={picked} shop={shop} onClose={() => setOpen(null)} />}
    </div>
  );
}
