// Kid side of rewards: the points, what they can be traded for, and asking a grown-up.
import { useState } from "react";
import { requestId, send, useApi, type ApiError, type Reward, type RewardsPage } from "../../api";
import { Chest, Medal } from "../../art/treasure";
import { Icon } from "../../components/icons";
import { Bar, Button, EmptyState, InlineError, Pending, Sheet } from "../../components/ui";
import { useLive } from "../../live";

export default function KidRewards() {
  const { data: p, error, reload } = useApi<RewardsPage>("/api/v1/app/family-rewards");
  const { refresh } = useLive();
  const [asking, setAsking] = useState<Reward | null>(null);
  const [askId, setAskId] = useState("");
  const [failed, setFailed] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const startAsk = (r: Reward) => { setAskId(requestId()); setFailed(null); setAsking(r); };
  const confirmAsk = () => {
    if (!asking || busy) return;
    setBusy(true);
    // the id was made when the sheet opened, so a double tap or a retry is one request on the server
    send("POST", "/api/v1/app/redemptions", { reward_id: asking.id, request_id: askId })
      .then(() => { setAsking(null); refresh(); }, setFailed).finally(() => setBusy(false));
  };
  const offered = p?.rewards.filter((r) => r.enabled) ?? [];

  return (
    <div className="page">
      <h1 className="h1" style={{ marginBottom: 12 }}>Rewards</h1>
      {!p ? <Pending error={error} retry={reload} blocks={3} /> : (
        <div className="kid-grid" style={{ marginTop: 0 }}>
          <div className="stack">
            <section className="card jar">
              <div>
                <p>Your points</p>
                <div className="n balance">{p.points.toLocaleString()}</div>
                {p.next ? <p>{p.next.to_go.toLocaleString()} more for {p.next.title}</p> : offered.length ? <p>Enough for every reward!</p> : null}
              </div>
              <Chest />
            </section>
            <section className="card">
              <h2 className="h2">Badges</h2>
              <ul className="medals">
                {p.badges.map((b) => (
                  <li key={b.id} aria-label={`${b.name}: ${b.earned ? "earned" : `${b.have} of ${b.need}`}`}>
                    <span className="medal"><Medal id={b.id} earned={b.earned} /></span>{b.name}<small className="num">{b.earned ? "Earned" : `${b.have}/${b.need}`}</small>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <div className="stack">
            {!offered.length ? <EmptyState title="No rewards yet" creature="bubbles">Ask a grown-up to add a family reward.</EmptyState> : offered.map((r) => {
              const waiting = p.requests.some((q) => q.reward_id === r.id && q.status === "requested");
              return (
                <section key={r.id} className={`card reward ${r.affordable ? "ready" : ""}`}>
                  <span className="pic"><Icon name={r.icon} size={26} /></span>
                  <div><b>{r.title}</b><div className="cost">{r.cost.toLocaleString()} points</div></div>
                  {waiting ? <span className="tag gold">Asked</span> : r.affordable ? <Button small tone="gold" onClick={() => startAsk(r)}>Ask for it</Button> : <span className="muted num">{r.to_go.toLocaleString()} to go</span>}
                  {!r.affordable && <Bar value={p.points / r.cost} tone="gold" label={`Progress to ${r.title}`} />}
                </section>
              );
            })}
            {p.requests.some((q) => q.status === "requested") && <p className="muted center">A grown-up says yes or no in the grown-up view.</p>}
            <p className="muted">Every wash gives you its score as points, for your first {p.rule.rewarded_washes_per_day} washes each day.</p>
          </div>
        </div>
      )}
      {asking && p && (
        <Sheet title={`Ask for ${asking.title}?`} onClose={() => setAsking(null)}
          lede={<>This holds <b>{asking.cost.toLocaleString()}</b> of your {p.points.toLocaleString()} points until a grown-up says yes or no.</>}>
          {failed && <InlineError error={failed} />}
          <div className="actions">
            <Button tone="gold" wide disabled={busy} onClick={confirmAsk}>Yes, ask for it</Button>
            <Button tone="quiet" wide onClick={() => setAsking(null)}>Not now</Button>
          </div>
        </Sheet>
      )}
    </div>
  );
}
