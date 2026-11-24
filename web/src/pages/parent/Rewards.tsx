// Grown-up side of rewards: what the family offers, what has been asked for, and how points are earned.
import { useState } from "react";
import { send, useApi, type ApiError, type Child, type Redemption, type Reward, type RewardsPage } from "../../api";
import { Icon } from "../../components/icons";
import { KidPicker } from "../../components/Nav";
import { Button, InlineError, PageHead, Pending } from "../../components/ui";
import { useLive } from "../../live";
import { useParentGate } from "../../parent";
import { RewardForm } from "../RewardForm";

const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export default function Rewards() {
  const { data: p, error, reload } = useApi<RewardsPage>("/api/v1/app/family-rewards");
  const { data: kid } = useApi<Child | null>("/api/v1/app/child");
  const { refresh } = useLive();
  const gate = useParentGate();
  const [form, setForm] = useState<Reward | "new" | null>(null);
  const [failed, setFailed] = useState<ApiError | null>(null);
  const name = kid?.name ?? "Your child";
  const openForm = async (r: Reward | "new") => { if (await gate.ask()) setForm(r); };
  const decide = async (q: Redemption, approve: boolean) => {
    if (!(await gate.ask())) return;
    send("POST", `/api/v1/app/redemptions/${q.id}/decide`, { approve }).then(refresh, setFailed);
  };
  const waiting = p?.requests.filter((q) => q.status === "requested") ?? [];
  const decided = p?.requests.filter((q) => q.status !== "requested") ?? [];

  return (
    <div className="page">
      <PageHead title="Rewards" sub={`What ${name} can trade points for`}>
        <KidPicker />
        <Button icon="plus" onClick={() => openForm("new")}>Add a reward</Button>
      </PageHead>
      {failed && <InlineError error={failed} />}
      {!p ? <Pending error={error} retry={reload} blocks={3} /> : (
        <>
          <dl className="kpis">
            <div className="kpi"><dt>Points to spend</dt><dd>{p.points.toLocaleString()}</dd><p>{name}'s balance now</p></div>
            <div className="kpi"><dt>Earned in all</dt><dd>{p.earned.toLocaleString()}</dd><p>sum of rewarded wash scores</p></div>
            <div className="kpi"><dt>Spent or held</dt><dd>{p.held.toLocaleString()}</dd><p>approved or waiting requests</p></div>
            <div className="kpi"><dt>Waiting for you</dt><dd>{waiting.length}</dd><p>{waiting.length ? "decide below" : "nothing to decide"}</p></div>
            <div className="kpi"><dt>Next reward</dt><dd>{p.next ? p.next.to_go.toLocaleString() : "–"}</dd><p>{p.next ? `points to go for ${p.next.title}` : "all are in reach"}</p></div>
          </dl>

          {waiting.length > 0 && (
            <section className="card" style={{ marginBottom: 16 }}>
              <h2 className="h2">Requests to decide</h2>
              <div className="rows">
                {waiting.map((q) => (
                  <div className="row" key={q.id} style={{ flexWrap: "wrap" }}>
                    <span className="grow"><span className="name">{q.title}</span><span className="sub num">{name} asked on {day(q.requested)}. {q.cost.toLocaleString()} points are held.</span></span>
                    <Button small tone="quiet" onClick={() => decide(q, false)}>Decline</Button>
                    <Button small onClick={() => decide(q, true)}>Approve</Button>
                  </div>
                ))}
              </div>
            </section>
          )}

          <div className="grid2">
            <section className="card">
              <h2 className="h2">Family rewards</h2>
              {p.rewards.length ? (
                <div className="table-wrap">
                  <table className="data">
                    <thead><tr><th>Reward</th><th className="r">Points</th><th>For {name}</th><th /></tr></thead>
                    <tbody>
                      {p.rewards.map((r) => (
                        <tr key={r.id}>
                          <td>{r.title}{!r.enabled && <span className="sub">Paused</span>}</td>
                          <td className="r">{r.cost.toLocaleString()}</td>
                          <td>{!r.enabled ? "–" : r.affordable ? <span className="tag good">In reach</span> : <span className="num">{r.to_go.toLocaleString()} to go</span>}</td>
                          <td className="r"><button type="button" className="icon-btn" aria-label={`Edit ${r.title}`} onClick={() => openForm(r)}><Icon name="pencil" size={18} /></button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="lede">No rewards yet. Add something your family does together, like an extra bedtime story.</p>}
              <p className="note">{name} asks for a reward in the kid view. The points are held until you approve or decline. Declining gives them back.</p>
            </section>
            <div className="stack">
              <section className="card">
                <h2 className="h2">How points are earned</h2>
                <ul className="ticks">
                  <li>A wash earns its score as points, up to {p.rule.max_per_wash}.</li>
                  <li>Only the first {p.rule.rewarded_washes_per_day} washes of a day earn points, so there is no reason to wash extra.</li>
                  <li>A missed day takes nothing away.</li>
                </ul>
              </section>
              {decided.length > 0 && (
                <section className="card">
                  <h2 className="h2">Earlier requests</h2>
                  <div className="rows">
                    {decided.slice(0, 6).map((q) => (
                      <div className="row" key={q.id}><span className="grow"><span className="name">{q.title}</span><span className="sub num">{day(q.requested)}, {q.cost.toLocaleString()} points</span></span>
                        <span className={`tag ${q.status === "approved" ? "good" : ""}`}>{q.status === "approved" ? "Approved" : "Declined, points returned"}</span></div>
                    ))}
                  </div>
                </section>
              )}
            </div>
          </div>
        </>
      )}
      {form && <RewardForm reward={form === "new" ? null : form} onClose={() => setForm(null)} />}
    </div>
  );
}
