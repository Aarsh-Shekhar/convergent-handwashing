import { useState, type FormEvent } from "react";
import { send, type ApiError, type Reward, type RewardIcon } from "../api";
import { Icon } from "../components/icons";
import { Button, InlineError, Sheet } from "../components/ui";
import { useLive } from "../live";

const ICONS: RewardIcon[] = ["gift", "book", "movie", "park", "treat", "game"];

export function RewardForm({ reward, onClose }: { reward: Reward | null; onClose: () => void }) {
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
            {ICONS.map((i) => <button key={i} type="button" role="radio" aria-checked={icon === i} aria-label={i} className="chip" onClick={() => setIcon(i)}><Icon name={i} /></button>)}
          </div>
        </div>
        {error && <InlineError error={error} />}
        <div className="actions">
          <Button type="submit" wide disabled={!valid}>{reward ? "Save" : "Add reward"}</Button>
          {reward && <Button tone="quiet" wide onClick={() => send("PUT", `/api/v1/app/family-rewards/${reward.id}`, { enabled: !reward.enabled }).then(done, setError)}>{reward.enabled ? "Pause this reward" : "Offer it again"}</Button>}
          {reward && <Button tone="danger" wide icon="trash" onClick={() => send("DELETE", `/api/v1/app/family-rewards/${reward.id}`).then(done, setError)}>Remove reward</Button>}
        </div>
      </form>
    </Sheet>
  );
}
