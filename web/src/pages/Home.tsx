import { useApi, type Home as HomeData } from "../api";
import { ART, Germ, germFor } from "../components/germs";
import { Empty, Loading, Ring } from "../components/ui";
import { WashCard } from "../components/WashCard";
import { useStationActive } from "../live";
import { Link } from "../router";

export default function Home() {
  const { data: h, error } = useApi<HomeData>("/api/v1/app/home");
  const active = useStationActive();
  const date = new Date().toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const kid = h?.child?.name;
  return (
    <div className="page fade-in">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <p className="hello-date">{date}</p>
        <span className={`live-dot ${active ? "on" : ""}`}><i />{active ? "Station live" : "Station idle"}</span>
      </div>
      <h1 className="hello">Hi {h?.parent_name || "there"}!</h1>
      {kid && (
        <div className="chips">
          <span className="kid-chip"><img src={ART[h.child!.buddy] ?? ART.scrubby} alt="" />{kid}</span>
        </div>
      )}
      {!h ? <Loading error={error} /> : (
        <>
          <div className="card summary">
            <Ring value={h.today / h.goal} size={96} stroke={11}>
              <div className="ring-label"><b>{h.today}/{h.goal}</b><span>washes today</span></div>
            </Ring>
            <div>
              <div className="stat-row"><div className="stat-big">{h.avg_score ?? "-"}</div><div className="faint">avg score this week</div></div>
              <div className="stat-row"><div className="stat-big">{h.clean_washes}</div><div className="faint">clean washes so far</div></div>
            </div>
          </div>

          <h2 className="section">Latest wash {h.latest && <Link to="/washes">See all</Link>}</h2>
          {h.latest ? <WashCard w={h.latest} hero /> : (
            <Empty title="No washes yet">
              Start the Scrubby station and wash your hands. Each wash shows up here as soon as it ends.
            </Empty>
          )}

          {h.tip && (
            <div className="tip fade-in">
              <Germ id={germFor(h.tip.zone)} size={34} />
              <span><b>Tip:</b> {kid ?? "Your kid"} missed {h.tip.name.toLowerCase()} in {Math.round(h.tip.missed * 100)}% of washes this week.
                Try saying "{h.tip.name} next!" while they scrub.</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
