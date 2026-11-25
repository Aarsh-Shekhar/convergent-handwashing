// Settings and Routines: station status, routines and goal, the kid's profile, privacy, delete history.
import { useEffect, useState } from "react";
import { api, useApi, type Child, type Settings as Data } from "../api";
import { GoalRow, KidForm, RoutineList } from "../components/forms";
import { Germ } from "../components/germs";
import { Icon, Loading, PageHead, Toggle } from "../components/ui";
import { useStationActive } from "../live";
import { go, Link } from "../router";

type Station = { backend: string; devices: { device_id: string; status: string }[]; last_wash: string | null };

const put = (path: string, body: object) => api(path, { method: "PUT", body: JSON.stringify(body) });

export function Routines() {
  const { data, error } = useApi<Data>("/api/v1/app/settings");
  const [s, setS] = useState<Data | null>(null);
  useEffect(() => { if (data) setS(data); }, [data]);
  if (!s) return <div className="page"><PageHead title="Routines" back={() => go("/settings")} /><Loading error={error} /></div>;
  const update = (patch: Partial<Data>) => { const next = { ...s, ...patch }; setS(next); put("/api/v1/app/settings", patch).catch(() => {}); };
  return (
    <div className="page fade-in">
      <PageHead title="Routines" back={() => go("/settings")} />
      <div className="card" style={{ padding: "4px 16px 8px" }}>
        <RoutineList routines={s.routines} onChange={(routines) => update({ routines })} />
        <GoalRow goal={s.daily_goal} onChange={(daily_goal) => update({ daily_goal })} />
      </div>
      <div className="label-caps">Notifications</div>
      <div className="card" style={{ padding: "4px 16px" }}>
        {[["station_reminder", "Station reminder", "Bubbles wave on the sink screen"], ["skipped_alert", "Tell me if a wash is skipped", "Push notification"]].map(([k, title, sub]) => (
          <div className="row" key={k}>
            <div className="grow"><div className="title">{title}</div><div className="faint">{sub}</div></div>
            <Toggle on={!!s.toggles[k]} label={title} onChange={(v) => update({ toggles: { ...s.toggles, [k]: v } })} />
          </div>
        ))}
      </div>
      <p className="faint" style={{ margin: "10px 4px" }}>Routines name each wash in the history. Reminders and notifications are saved but not sent yet.</p>
    </div>
  );
}

function KidSheet({ kid, onClose }: { kid: Child; onClose: (saved: boolean) => void }) {
  const [k, setK] = useState(kid);
  return (
    <div className="modal-bg" onClick={() => onClose(false)}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Edit kid">
        <h3>Kid profile</h3>
        <KidForm kid={k} onChange={setK} />
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn outline" onClick={() => onClose(false)}>Cancel</button>
          <button className="btn dark" disabled={!k.name.trim()} onClick={() => put("/api/v1/app/child", { ...k, name: k.name.trim() }).then(() => onClose(true))}>Save</button>
        </div>
      </div>
    </div>
  );
}

function DeleteSheet({ count, onClose }: { count: number; onClose: (deleted: boolean) => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="modal-bg" onClick={() => onClose(false)}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="alertdialog" aria-label="Delete wash history">
        <h3>Delete wash history?</h3>
        <p className="muted">This deletes all {count} washes, every zap and every caught germ. It can't be undone. The kid's profile and routines stay.</p>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn outline" onClick={() => onClose(false)}>Keep it</button>
          <button className="btn danger" disabled={busy}
            onClick={() => { setBusy(true); api("/api/v1/app/washes", { method: "DELETE" }).then(() => onClose(true), () => setBusy(false)); }}>Delete</button>
        </div>
      </div>
    </div>
  );
}

export default function Settings({ onRestartSetup }: { onRestartSetup: () => void }) {
  const { data: s, error } = useApi<Data>("/api/v1/app/settings");
  const { data: kid, reload: reloadKid } = useApi<Child | null>("/api/v1/app/child");
  const { data: station } = useApi<Station>("/api/v1/app/station");
  const { data: washes, reload: reloadWashes } = useApi<unknown[]>("/api/v1/app/washes");
  const running = useStationActive();
  const [sheet, setSheet] = useState<"kid" | "delete" | null>(null);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => { if (!note) return; const t = window.setTimeout(() => setNote(null), 3000); return () => clearTimeout(t); }, [note]);
  if (!s) return <div className="page"><PageHead title="Settings" /><Loading error={error} /></div>;
  const last = station?.last_wash ? new Date(station.last_wash).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" }) : null;

  return (
    <div className="page fade-in">
      <PageHead title="Settings" />
      <Link to="/live" className="card wash-card">
        <span className="row-icon" style={{ width: 46, height: 46 }}><Icon name="wifi" /></span>
        <div className="body">
          <div className="title">Scrubby Station</div>
          <div className="sub" style={{ margin: 0 }}>
            <span className={`live-dot ${running ? "on" : ""}`}><i />{running ? "Running now" : station ? "Online, waiting" : "Offline"}</span>
            {last && <> · last wash {last}</>}
          </div>
        </div>
        <span className="chev"><Icon name="right" size={18} /></span>
      </Link>

      <div className="label-caps">Game</div>
      <div className="card" style={{ padding: "4px 16px" }}>
        <Link to="/routines" className="row">
          <span className="row-icon"><Icon name="clock" size={18} /></span>
          <div className="grow"><div className="title">Routines and daily goal</div><div className="faint">{s.routines.filter((r) => r.on).length} on · {s.daily_goal} washes a day</div></div>
          <span className="chev"><Icon name="right" size={18} /></span>
        </Link>
        <div className="row">
          <span className="row-icon"><Icon name="spark" size={18} /></span>
          <div className="grow"><div className="title">Scrub rules</div><div className="faint">3 s per step, 20 s and 5 of 7 steps to finish. Set on the station.</div></div>
        </div>
      </div>

      <div className="label-caps">Family</div>
      <div className="card" style={{ padding: "4px 16px" }}>
        <button className="row" style={{ width: "100%", border: 0, background: "none", textAlign: "left", cursor: "pointer" }} onClick={() => kid && setSheet("kid")} disabled={!kid}>
          {kid ? <Germ id={kid.buddy} size={34} /> : <span className="row-icon"><Icon name="home" size={18} /></span>}
          <div className="grow"><div className="title">Kid profile</div><div className="faint">{kid ? `${kid.name} · age ${kid.age_band.replace("-", "–")}` : "No kid added yet"}</div></div>
          <span className="chev"><Icon name="right" size={18} /></span>
        </button>
        <div className="row">
          <span className="row-icon"><Icon name="home" size={18} /></span>
          <div className="grow"><div className="title">Grown-up</div><div className="faint">{s.parent_name || "Not set"}</div></div>
        </div>
      </div>

      <div className="label-caps">Privacy</div>
      <div className="card" style={{ padding: "4px 16px" }}>
        <div className="row">
          <span className="row-icon"><Icon name="shield" size={18} /></span>
          <div className="grow"><div className="title">No video in the app</div><div className="faint">The station sends scores and missed spots only. Data stays on this laptop.</div></div>
        </div>
        <button className="row" style={{ width: "100%", border: 0, background: "none", textAlign: "left", cursor: "pointer", color: "#c4422f" }} onClick={() => setSheet("delete")}>
          <span className="row-icon" style={{ background: "#fde5e1", color: "#c4422f" }}><Icon name="trash" size={18} /></span>
          <div className="grow"><div className="title">Delete wash history</div><div className="faint">{washes ? `${washes.length} washes saved` : ""}</div></div>
        </button>
      </div>

      <button className="link-btn" style={{ display: "block", margin: "14px auto 0" }}
        onClick={() => put("/api/v1/app/settings", { onboarded: false }).then(onRestartSetup)}>Run setup again</button>

      {sheet === "kid" && kid && <KidSheet kid={kid} onClose={(saved) => { setSheet(null); if (saved) { reloadKid(); setNote("Profile saved"); } }} />}
      {sheet === "delete" && <DeleteSheet count={washes?.length ?? 0} onClose={(deleted) => { setSheet(null); if (deleted) { reloadWashes(); setNote("Wash history deleted"); } }} />}
      {note && <div className="toast" role="status"><Icon name="check" /><b>{note}</b></div>}
    </div>
  );
}
