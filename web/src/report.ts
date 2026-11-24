// Things a parent can take out of the app: a plain-text summary, a spreadsheet file and calendar reminders.
// Everything here is built in the browser from numbers the backend already worked out. Nothing is sent anywhere.
import type { Insights, Routine, WashView } from "./api";
import { ZONE_NAMES } from "./api";

export const ABOUT = "About these numbers: Scrubble is a handwashing trainer at the sink. A camera recognizes scrubbing motions and times them. "
  + "The score is recognized scrubbing time. It does not measure clean hands or germs, and it is not a medical record.";

const day = (iso: string) => new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

/** The summary a parent can email, copy or print. `note` is the parent's own words and is never saved. */
export function summaryText(ins: Insights, kid: string, to: "doctor" | "caregiver", note = ""): string {
  const lines = [`Handwashing summary for ${kid}`, `Period: ${day(ins.from)} to ${day(ins.to)} (${ins.days} days)`, ""];
  if (ins.n === 0) lines.push("No washes with recognized scrubbing were recorded in this period.");
  else {
    lines.push(
      `Washes recorded: ${ins.n} (${(ins.n / ins.days).toFixed(1)} a day, family goal ${ins.goal})`,
      `Days with at least one wash: ${ins.days_with_wash} of ${ins.days}`,
      `Average score: ${ins.score.mean === null ? "none" : Math.round(ins.score.mean)} of 100`,
      `Average scrubbing time: ${ins.scrub.mean_s === null ? "none" : Math.round(ins.scrub.mean_s)} s (goal ${ins.scrub.goal_s} s)`,
      `Washes with every zone scrubbed: ${ins.perfect} of ${ins.n}`, "",
      "Zones scrubbed least often (fully scrubbed = 3 s of that motion):",
      ...[...ins.zones].sort((a, b) => a.full - b.full).slice(0, 3).map((z) => `- ${z.name}: fully scrubbed in ${z.full} of ${z.n} washes`),
    );
  }
  if (note.trim()) lines.push("", `${to === "doctor" ? "What we have noticed at home" : "Note from the family"}: ${note.trim()}`);
  lines.push("", ABOUT);
  return lines.join("\n");
}

const cell = (v: string | number) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));

/** One row per wash, for a spreadsheet. */
export function washesCsv(washes: WashView[]): string {
  const head = ["wash_id", "date", "time", "label", "score", "stars", "steps_done", "scrub_seconds", "finished", "missed_zones", "source"];
  const rows = washes.map((w) => [w.wash_id, w.day, w.time, w.label, w.points, w.stars, w.steps_done, w.seconds_total, w.finished ? "yes" : "no",
    w.missed.map((z) => ZONE_NAMES[z]).join("; "), w.wash_id.startsWith("demo-") ? "demo" : "sink"]);
  return [head, ...rows].map((r) => r.map(cell).join(",")).join("\r\n") + "\r\n";
}

/** A calendar file with one daily reminder for each switched-on routine that has a time. */
export function routinesIcs(routines: Routine[], kid: string, stamp = new Date()): string {
  const z = (n: number) => String(n).padStart(2, "0");
  const ymd = `${stamp.getFullYear()}${z(stamp.getMonth() + 1)}${z(stamp.getDate())}`;
  const utc = stamp.toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
  const events = routines.filter((r) => r.on && r.time).map((r) => {
    const [h, m] = r.time!.split(":").map(Number);
    return ["BEGIN:VEVENT", `UID:scrubble-${r.id}@scrubble.local`, `DTSTAMP:${utc}`, `DTSTART:${ymd}T${z(h)}${z(m)}00`, "DURATION:PT5M", "RRULE:FREQ=DAILY",
      `SUMMARY:${`${r.name}: ${kid} washes hands`.replace(/([,;\\])/g, "\\$1")}`, "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Time to wash hands", "TRIGGER:PT0M", "END:VALARM", "END:VEVENT"].join("\r\n");
  });
  return ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Scrubble//Routines//EN", ...events, "END:VCALENDAR"].join("\r\n") + "\r\n";
}

export function download(name: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
