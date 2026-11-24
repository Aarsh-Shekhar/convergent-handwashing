import { useState, type FormEvent } from "react";
import { requestId, send, useApi, type ApiError, type Child, type Redemption, type Reward, type RewardIcon, type RewardsPage } from "../api";
import { Chest, Coin, Medal } from "../art/treasure";
import { Icon } from "../components/icons";
import { Bar, GameButton, IconButton, InlineError, Pending, Sheet, TopBar } from "../components/ui";
import { useLive } from "../live";
import { useParentGate } from "../parent";
import "./Rewards.css";

const ICONS: RewardIcon[] = ["gift", "book", "movie", "park", "treat", "game"];

/** One family reward: what it is, how close the child is, and the way to ask for it. */
function RewardRow({ r, points, waiting, onAsk, onEdit }: { r: Reward; points: number; waiting: boolean; onAsk: () => void; onEdit: () => void }) {
  return (
    <li className={`reward-row panel ${r.affordable ? "ready" : ""} ${r.enabled ? "" : "off"}`}>
      <span className="medallion"><Icon name={r.icon} size={28} /></span>
      <div className="body">
        <b>{r.title}</b>
        <div className="cost"><Coin size={18} /><span className="num">{r.cost.toLocaleString()}</span>{!r.enabled && <span className="tag">Paused</span>}</div>
        {r.enabled && !r.affordable && <Bar value={points / r.cost} label={`Progress to ${r.title}`} />}
      </div>
      <div className="side">
        {waiting ? <span className="tag gold">Asked</span>
          : r.affordable ? <GameButton small tone="gold" onClick={onAsk}>Redeem</GameButton>
          : r.enabled ? <span className="togo num">{r.to_go.toLocaleString()} to go</span> : null}
        <button type="button" className="edit" aria-label={`Edit ${r.title}`} onClick={onEdit}><Icon name="pencil" size={18} /></button>
      </div>
    </li>
  );
}

function RewardForm({ reward, onClose }: { reward: Reward | null; onClose: () => void }) {
  const { refresh } = useLive();
  const [title, setTitle] = useState(reward?.title ?? "");
  const [cost, setCost] = useState(String(reward?.cost ?? 300));
  const [icon, setIcon] = useState<RewardIcon>(reward?.icon ?? "gift");
  const [error, setError] = useState<ApiError | null>(null);
  const n = Number(cost);
  const valid = title.trim().length > 0 && Number.isInteger(n) && n >= 1 && n <= 100000;
  const done = () => { refresh(); onClose(); };
  const save = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    const body = { title: title.trim(), cost: n, icon };
    (reward ? send("PUT", `/api/v1/app/family-rewards/${reward.id}`, body) : send("POST", "/api/v1/app/family-rewards", body)).then(done, setError);
  };
  return (
    <Sheet title={reward ? "Edit reward" : "New family reward"} lede="Something real your family does together." onClose={onClose}>
      <form onSubmit={save}>
        <label className="field"><span>Reward</span><input className="input" value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} placeholder="Extra bedtime story" required /></label>
        <label className="field"><span>Points needed</span><input className="input" inputMode="numeric" value={cost} onChange={(e) => setCost(e.target.value.replace(/\D/g, ""))} aria-invalid={!valid && cost !== ""} /></label>
        <div className="field"><span id="icon-label">Picture</span>
          <div className="chips" role="radiogroup" aria-labelledby="icon-label">
            {ICONS.map((i) => <button key={i} type="button" role="radio" aria-checked={icon === i} aria-label={i} className="chip icon-chip" onClick={() => setIcon(i)}><Icon name={i} /></button>)}
          </div>
        </div>
        {error && <InlineError error={error} />}
        <div className="actions">
          <GameButton type="submit" wide disabled={!valid}>{reward ? "Save" : "Add reward"}</GameButton>
          {reward && <GameButton tone="quiet" wide onClick={() => send("PUT", `/api/v1/app/family-rewards/${reward.id}`, { enabled: !reward.enabled }).then(done, setError)}>{reward.enabled ? "Pause this reward" : "Offer it again"}</GameButton>}
          {reward && <GameButton tone="danger" wide icon="trash" onClick={() => send("DELETE", `/api/v1/app/family-rewards/${reward.id}`).then(done, setError)}>Remove reward</GameButton>}
        </div>
      </form>
    </Sheet>
  );
}

function Request({ q, onDecide }: { q: Redemption; onDecide: (approve: boolean) => void }) {
  const when = new Date(q.requested).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return (
    <li className={`request ${q.status}`}>
      <div className="grow"><b>{q.title}</b><span className="faint num">{when} · {q.cost.toLocaleString()} pts</span></div>
      {q.status === "requested" ? (
        <div className="decide">
          <GameButton small tone="quiet" onClick={() => onDecide(false)}>Decline</GameButton>
          <GameButton small onClick={() => onDecide(true)}>Approve</GameButton>
        </div>
      ) : <span className={`tag ${q.status === "approved" ? "good" : ""}`}>{q.status === "approved" ? "Approved" : "Declined, points returned"}</span>}
    </li>
  );
}

export default function Rewards() {
  const { data: p, error, reload } = useApi<RewardsPage>("/api/v1/app/family-rewards");
  const { data: kid } = useApi<Child | null>("/api/v1/app/child");
  const { refresh } = useLive();
  const gate = useParentGate();
  const [asking, setAsking] = useState<Reward | null>(null);
  const [askId, setAskId] = useState("");
  const [form, setForm] = useState<Reward | "new" | null>(null);
  const [failed, setFailed] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const name = kid?.name ?? "Your child";

  const openForm = async (r: Reward | "new") => { if (await gate.ask()) setForm(r); };
  const startAsk = (r: Reward) => { setAskId(requestId()); setFailed(null); setAsking(r); };
  const confirmAsk = () => {
    if (!asking || busy) return;
    setBusy(true);
    // the id was made when the sheet opened, so a double tap or a retry is one request on the server
    send("POST", "/api/v1/app/redemptions", { reward_id: asking.id, request_id: askId })
      .then(() => { setAsking(null); refresh(); }, setFailed).finally(() => setBusy(false));
  };
  const decide = async (q: Redemption, approve: boolean) => {
    if (!(await gate.ask())) return;
    send("POST", `/api/v1/app/redemptions/${q.id}/decide`, { approve }).then(refresh, setFailed);
  };

  return (
    <div className="page rewards">
      <TopBar title="Rewards" right={<IconButton icon="plus" label="Add a family reward" tone="violet" onClick={() => openForm("new")} />} />
      {!p ? <Pending error={error} retry={reload} blocks={3} /> : (
        <>
          <section className="panel violet illustrated vault">
            <div className="content">
              <div>
                <div className="caps-line">{name}'s points</div>
                <div className="balance num">{p.points.toLocaleString()}</div>
                {p.next ? (
                  <><p className="next">{p.next.to_go.toLocaleString()} more for <b>{p.next.title}</b></p>
                    <Bar value={p.points / (p.points + p.next.to_go)} label="Progress to the next reward" /></>
                ) : <p className="next">{p.rewards.some((r) => r.affordable) ? "Enough for every reward on the list." : "Add a family reward to save up for."}</p>}
              </div>
              <div className="chest"><Chest /></div>
            </div>
          </section>

          {failed && !asking && <InlineError error={failed} />}
          <h2 className="section">Family rewards</h2>
          {p.rewards.length ? (
            <ul className="reward-list">
              {p.rewards.map((r) => (
                <RewardRow key={r.id} r={r} points={p.points} waiting={p.requests.some((q) => q.reward_id === r.id && q.status === "requested")}
                  onAsk={() => startAsk(r)} onEdit={() => openForm(r)} />
              ))}
            </ul>
          ) : <div className="panel deep empty"><h3>No rewards yet</h3><p>Add something your family does together, like an extra bedtime story.</p><GameButton icon="plus" onClick={() => openForm("new")}>Add a reward</GameButton></div>}

          {p.requests.length > 0 && (
            <>
              <h2 className="section">Requests</h2>
              <ul className="panel deep requests">{p.requests.slice(0, 6).map((q) => <Request key={q.id} q={q} onDecide={(a) => decide(q, a)} />)}</ul>
            </>
          )}

          <h2 className="section">Badges</h2>
          <ul className="badges">
            {p.badges.map((b) => (
              <li key={b.id} className={b.earned ? "earned" : ""} aria-label={`${b.name}: ${b.earned ? "earned" : `${b.have} of ${b.need}`}`}>
                <span className="medal"><Medal id={b.id} earned={b.earned} /></span>
                <b>{b.name}</b>
                <small className="num">{b.earned ? "Earned" : `${b.have}/${b.need}`}</small>
              </li>
            ))}
          </ul>

          <p className="faint rule">
            A wash earns its score as points (up to {p.rule.max_per_wash}) for the first {p.rule.rewarded_washes_per_day} washes of a day.
            Extra washes after that earn nothing, and a missed day takes nothing away.
          </p>
        </>
      )}

      {asking && p && (
        <Sheet title={`Ask for ${asking.title}?`} onClose={() => setAsking(null)}
          lede={<>This holds <b>{asking.cost.toLocaleString()}</b> of {name}'s {p.points.toLocaleString()} points until a grown-up says yes or no.</>}>
          {failed && <InlineError error={failed} />}
          <div className="actions">
            <GameButton tone="gold" wide disabled={busy} onClick={confirmAsk}>Yes, ask for it</GameButton>
            <GameButton tone="quiet" wide onClick={() => setAsking(null)}>Not now</GameButton>
          </div>
        </Sheet>
      )}
      {form && <RewardForm reward={form === "new" ? null : form} onClose={() => setForm(null)} />}
    </div>
  );
}
