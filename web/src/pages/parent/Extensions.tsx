// Extensions: ways for a parent to use the wash data outside the app. Each one that is listed as working
// works here in the browser. The ones that need a partner are listed separately as not built.
import { useEffect, useState } from "react";
import { send, useApi, type ApiError, type Care, type Home, type Insights, type Settings, type WashView } from "../../api";
import { Icon } from "../../components/icons";
import { KidPicker } from "../../components/Nav";
import { Button, InlineError, PageHead, Pending, SegmentedTabs } from "../../components/ui";
import { download, routinesIcs, summaryText, washesCsv } from "../../report";

const PERIODS = [["14", "14 days"], ["30", "30 days"], ["90", "90 days"]] as const;
const TO = [["doctor", "Doctor"], ["caregiver", "School or caregiver"]] as const;
const PLANNED: readonly (readonly [title: string, what: string, missing: string])[] = [
  ["Video visit with a pediatric clinic", "Book a visit from the app at a member price, with the summary attached.", "Needs a partner clinic. None is signed, so no price is shown."],
  ["HSA and FSA receipt", "An itemized receipt for the station, for families who can claim it.", "Needs a check of what qualifies. Not done."],
  ["Classroom report", "A weekly summary a teacher can open for a class with a station at the sink.", "Needs accounts and consent from each family. Not built."],
  ["Soap refill reminder", "A nudge when the wash count suggests the soap is running low.", "The station cannot see the soap level. It would be an estimate."],
];
const blank: Care = { name: "", email: "", phone: "", booking_url: "" };

export default function Extensions() {
  const [period, setPeriod] = useState<(typeof PERIODS)[number][0]>("14");
  const [to, setTo] = useState<(typeof TO)[number][0]>("doctor");
  const [note, setNote] = useState("");
  const [copied, setCopied] = useState(false);
  const { data: ins, error, reload } = useApi<Insights>(`/api/v1/app/insights?days=${period}`);
  const { data: home } = useApi<Home>("/api/v1/app/home");
  const { data: saved, reload: reloadCare } = useApi<Care>("/api/v1/app/care");
  const { data: settings } = useApi<Settings>("/api/v1/app/settings");
  const { data: washes } = useApi<WashView[]>("/api/v1/app/washes");
  const [care, setCare] = useState<Care>(blank);
  const [failed, setFailed] = useState<ApiError | null>(null);
  useEffect(() => { if (saved) setCare(saved); }, [saved]);

  const kid = home?.child?.name ?? "your child";
  const text = ins ? summaryText(ins, kid, to, note) : "";
  const subject = `Handwashing summary for ${kid}`;
  const mail = `mailto:${to === "doctor" ? encodeURIComponent(saved?.email ?? "") : ""}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(text)}`;
  const dirty = !!saved && (Object.keys(blank) as (keyof Care)[]).some((k) => care[k].trim() !== saved[k]);
  const timed = settings?.routines.filter((r) => r.on && r.time) ?? [];
  const field = (k: keyof Care, label: string, type: string, hint: string) => (
    <label className="field"><span>{label}</span><input className="input" type={type} value={care[k]} placeholder={hint} maxLength={k === "booking_url" ? 300 : 120} onChange={(e) => setCare({ ...care, [k]: e.target.value })} /></label>
  );
  const saveCare = () => send("PUT", "/api/v1/app/care", care).then(() => { setFailed(null); reloadCare(); }, setFailed);

  return (
    <div className="page">
      <PageHead title="Extensions" sub="Use your family's handwashing data outside the app"><KidPicker /></PageHead>
      <div className="grid-main">
        <section className="card">
          <h2 className="h2">Share a summary</h2>
          <p className="note" style={{ margin: "0 0 12px" }}>Useful at a check-up, or when your child keeps getting sick and the doctor asks about hygiene at home. You send it yourself. Scrubble sends nothing.</p>
          <div className="tools-row">
            <SegmentedTabs label="Send to" options={TO} value={to} onChange={setTo} />
            <SegmentedTabs label="Period" options={PERIODS} value={period} onChange={setPeriod} />
          </div>
          <label className="field" style={{ marginTop: 12 }}>
            <span>{to === "doctor" ? "What you have noticed (optional, not saved)" : "Note (optional, not saved)"}</span>
            <textarea className="input area" rows={2} maxLength={400} value={note} onChange={(e) => setNote(e.target.value)} placeholder={to === "doctor" ? "For example: third cold since September" : ""} />
          </label>
          {!ins ? <Pending error={error} retry={reload} blocks={1} /> : <pre className="record printable" aria-label="Summary text">{text}</pre>}
          <div className="tools-row" style={{ marginTop: 12 }}>
            <a className="btn" href={mail} aria-disabled={!ins}><Icon name="out" size={16} />Open in email</a>
            <Button tone="quiet" disabled={!ins} onClick={() => navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2500); })}>{copied ? "Copied" : "Copy text"}</Button>
            <Button tone="quiet" disabled={!ins} onClick={() => window.print()}>Print</Button>
          </div>
          {to === "doctor" && saved && !saved.email && <p className="note">Add your doctor's email on this page and the email opens already addressed.</p>}
        </section>

        <div className="stack">
          <section className="card">
            <h2 className="h2">Your doctor</h2>
            {failed && <InlineError error={failed} />}
            <form onSubmit={(e) => { e.preventDefault(); saveCare(); }}>
              {field("name", "Name or practice", "text", "Dr. Rivera, Austin Pediatrics")}
              {field("phone", "Phone", "tel", "(512) 555-0100")}
              {field("email", "Email", "email", "office@example.org")}
              {field("booking_url", "Online booking page", "url", "https://")}
              {(dirty || !saved) && <Button type="submit" disabled={!saved}>Save contact</Button>}
            </form>
            {saved && !dirty && (saved.phone || saved.booking_url) && (
              <div className="tools-row" style={{ marginTop: 4 }}>
                {saved.booking_url && <a className="btn" href={saved.booking_url} target="_blank" rel="noopener noreferrer">Book a visit</a>}
                {saved.phone && <a className="btn quiet" href={`tel:${saved.phone.replace(/[^0-9+]/g, "")}`}>Call {saved.phone}</a>}
              </div>
            )}
            <p className="note">"Book a visit" opens your doctor's own booking page. Scrubble does not book for you and shares nothing with the practice.</p>
          </section>

          <section className="card">
            <h2 className="h2">Take the data with you</h2>
            <div className="rows">
              <div className="row"><span className="grow"><span className="name">Calendar reminders</span><span className="sub">{timed.length ? `${timed.length} daily ${timed.length === 1 ? "reminder" : "reminders"} from your routines, for any calendar app` : "Switch on a routine with a time in Settings first"}</span></span>
                <Button small tone="quiet" disabled={!timed.length} onClick={() => download("scrubble-routines.ics", routinesIcs(settings!.routines, kid), "text/calendar")}>Download</Button></div>
              <div className="row"><span className="grow"><span className="name">All washes as a spreadsheet</span><span className="sub">{washes ? `${washes.length} ${washes.length === 1 ? "wash" : "washes"} for ${kid}, one row each (CSV)` : "Loading"}</span></span>
                <Button small tone="quiet" disabled={!washes?.length} onClick={() => download(`scrubble-washes-${kid.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.csv`, washesCsv(washes!), "text/csv")}>Download</Button></div>
            </div>
          </section>
        </div>
      </div>

      <section className="card" style={{ marginTop: 16 }}>
        <h2 className="h2">Planned, not built</h2>
        <p className="note" style={{ margin: "0 0 4px" }}>Ideas for what a subscription could include. None of these works today and no partner is signed.</p>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Extension</th><th>What it would do</th><th>What is missing</th></tr></thead>
            <tbody>{PLANNED.map(([t, what, missing]) => <tr key={t}><td><span className="cell-strong">{t}</span><span className="tag" style={{ marginLeft: 8 }}>Not built</span></td><td>{what}</td><td>{missing}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
