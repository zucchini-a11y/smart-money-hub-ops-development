import { useMemo, useState } from "react";
import {
  Activity,
  ArrowLeft,
  CalendarDays,
  Check,
  ChevronDown,
  Clock3,
  ExternalLink,
  Info,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import "./_group.css";

const sampleEvent = {
  id: "sample-calendar-event",
  title: "Example U.S. economic release",
  currency: "USD",
  eventDate: "2026-11-12",
  timeLabel: "8:30 AM ET",
  impact: "high",
  impactBasis: "source_verified",
  verificationStatus: "verified_schedule",
  timezoneStatus: "verified_source_timezone:America/New_York",
  previous: "—",
  forecast: "—",
  actual: "—",
  sourceName: "Official source (example)",
  sourceUrl: "",
  lastRetrievedAt: "2026-11-06T00:00:00.000Z",
};

function prettyStamp(value?: string | null) {
  if (!value) return "Not available";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("en-NG", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function readableImpactBasis(value: string) {
  if (value === "source_verified") return "Impact supplied by source";
  if (value === "smh_estimate") return "Impact is an SMH estimate";
  return "Impact basis not supplied";
}

function isVerifiedTimezone(value: string) {
  return value.startsWith("verified_source_timezone:");
}

function CalendarEventRow({ event }: { event: typeof sampleEvent }) {
  const date = new Date(`${event.eventDate}T00:00:00`);
  const dateLabel = Number.isNaN(date.getTime())
    ? event.eventDate
    : new Intl.DateTimeFormat("en-NG", { weekday: "short", month: "short", day: "numeric" }).format(date);
  const timezoneVerified = isVerifiedTimezone(event.timezoneStatus);

  return (
    <article className="mx-calendar-row" data-testid={`calendar-event-${event.id}`}>
      <div className="mx-event-date">
        <strong>{dateLabel}</strong>
        <span><Clock3 size={13} aria-hidden="true" /> {event.timeLabel || "Time unavailable"}</span>
        {timezoneVerified ? (
          <small style={{ color: "var(--mx-green)", fontSize: 9 }}>Source timezone checked</small>
        ) : (
          <span
            role="note"
            style={{
              display: "block",
              maxWidth: 190,
              padding: "6px 8px",
              borderLeft: "2px solid var(--mx-gold)",
              background: "rgba(210,185,120,.06)",
              color: "var(--mx-gold-light)",
              lineHeight: 1.5,
            }}
          >
            Timezone not verified. The time may not match your local timezone.
          </span>
        )}
      </div>

      <div className="mx-event-main">
        <div className="mx-event-title-line">
          <h3>{event.title}</h3>
          <span className={`mx-impact mx-impact-${event.impact}`}>
            {event.impact === "unavailable" ? "Impact not supplied" : `${event.impact} impact`}
          </span>
        </div>
        <div className="mx-event-meta">
          <span>{event.currency}</span>
          <span>{readableImpactBasis(event.impactBasis)}</span>
        </div>
      </div>

      <div className="mx-event-values" aria-label="Reported event values">
        {[
          ["Previous", event.previous],
          ["Forecast", event.forecast],
          ["Actual", event.actual],
        ].map(([label, value]) => (
          <span key={label}>
            <small>{label}</small>
            <strong>{value || "—"}</strong>
            {!value || value === "—" ? <small>Not supplied</small> : null}
          </span>
        ))}
      </div>

      <div className="mx-event-source">
        <small>
          Source: {event.sourceName || "Not supplied"}
          <br />
          Last updated: {prettyStamp(event.lastRetrievedAt)}
        </small>
        <button className="mx-button" type="button" disabled={!event.sourceUrl} aria-label="Source link unavailable in this sample">
          View source <ExternalLink size={13} aria-hidden="true" />
        </button>
      </div>

      <details
        style={{
          gridColumn: "1 / -1",
          borderTop: "1px solid rgba(226,211,170,.08)",
          paddingTop: 10,
          color: "var(--mx-muted)",
          fontSize: 10,
        }}
      >
        <summary style={{ display: "inline-flex", cursor: "pointer", alignItems: "center", gap: 7, color: "var(--mx-gold)" }}>
          <Info size={13} aria-hidden="true" /> Verification details
          <ChevronDown size={13} aria-hidden="true" />
        </summary>
        <div style={{ display: "grid", gap: 5, padding: "10px 0 2px", lineHeight: 1.65 }}>
          <span>
            Schedule: {event.verificationStatus === "verified_schedule" ? "Shown as verified by the example source" : "Not confirmed by the source"}
          </span>
          <span>
            Timezone: {timezoneVerified ? "Source timezone shown as America/New_York" : "Not verified by the source"}
          </span>
          <span>Impact: {readableImpactBasis(event.impactBasis)}</span>
          <span>This is illustrative sample data, not a live event feed.</span>
        </div>
      </details>
    </article>
  );
}

export function ClearView() {
  const [from, setFrom] = useState("2026-11-06");
  const [through, setThrough] = useState("2026-11-20");
  const [impact, setImpact] = useState("");
  const [refreshMessage, setRefreshMessage] = useState("");
  const [refreshCount, setRefreshCount] = useState(0);

  const visibleEvents = useMemo(() => {
    const inDateRange = (!from || sampleEvent.eventDate >= from) && (!through || sampleEvent.eventDate <= through);
    const matchesImpact = !impact || sampleEvent.impact === impact;
    return inDateRange && matchesImpact ? [sampleEvent] : [];
  }, [from, through, impact]);

  function refreshSampleView() {
    setRefreshCount((count) => count + 1);
    setRefreshMessage("Sample view checked locally. No live calendar feed was requested.");
  }

  return (
    <main className="smh-calendar mx-feature-page">
      <div className="mx-dashboard-shell">
        <header className="mx-dashboard-header">
          <a className="mx-wordmark" href="#" aria-label="Vayda Smart Money Hub">
            <img className="mx-wordmark-image" src="/__mockup/images/vayda-logo.png" alt="" />
            <span><strong>VAYDA</strong><small>SMART MONEY HUB</small></span>
          </a>
          <span className="mx-feature-private"><ShieldCheck size={14} aria-hidden="true" /> PRIVATE LEARNING SPACE</span>
        </header>

        <nav className="mx-feature-nav" aria-label="Member learning tools">
          <a className="mx-feature-back" href="#"><ArrowLeft size={14} aria-hidden="true" /> Workspace</a>
          <div className="mx-feature-nav-links">
            <a className="mx-feature-nav-link is-active" href="#"><CalendarDays size={16} aria-hidden="true" /><span>Economic calendar</span></a>
            <a className="mx-feature-nav-link" href="#"><Activity size={16} aria-hidden="true" /><span>Trade journal</span></a>
            <a className="mx-feature-nav-link" href="#"><span>AI Coach</span></a>
          </div>
        </nav>

        <section className="mx-feature-heading">
          <div className="mx-overline"><span className="mx-live-mark" /> STUDY / USD EVENTS</div>
          <h1>Economic calendar</h1>
          <p>
            Scheduled U.S. events, shown as supplied by their sources. Use this view to study context around USD and gold—not to make trading decisions.
          </p>
        </section>

        <section className="mx-feature-panel" aria-label="USD economic calendar">
          <div className="mx-panel-toolbar">
            <div>
              <span className="mx-card-kicker">USD EVENT SCHEDULE</span>
              <p>Event time, impact, reported values, and source are kept together.</p>
            </div>
            <button className="mx-button" type="button" onClick={refreshSampleView}>
              <RefreshCw size={14} aria-hidden="true" /> Refresh
            </button>
          </div>

          <div className="mx-filter-row">
            <label className="mx-filter-field">From
              <input type="date" value={from} onChange={(e) => setFrom(e.currentTarget.value)} />
            </label>
            <label className="mx-filter-field">Through
              <input type="date" value={through} onChange={(e) => setThrough(e.currentTarget.value)} />
            </label>
            <label className="mx-filter-field">Impact
              <select value={impact} onChange={(e) => setImpact(e.currentTarget.value)}>
                <option value="">All impacts</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
                <option value="unavailable">Not supplied</option>
              </select>
            </label>
            <span className="mx-calendar-clock"><Clock3 size={14} aria-hidden="true" /> Event time is shown exactly as supplied</span>
          </div>

          <div className="mx-sample-note" role="note">
            SAMPLE ONLY · This illustrative event and its values are not live market data.
          </div>

          <div className="mx-source-status mx-source-stale">
            <span><i /> Example feed · not live</span>
            <span>Last sample update: {prettyStamp(sampleEvent.lastRetrievedAt)}</span>
          </div>

          {refreshMessage ? (
            <p role="status" className="mx-inline-note" style={{ display: "flex", alignItems: "center", gap: 6, margin: "9px 0 0" }}>
              <Check size={13} aria-hidden="true" /> {refreshMessage}{refreshCount > 1 ? ` (${refreshCount})` : ""}
            </p>
          ) : null}

          {visibleEvents.length ? (
            <div className="mx-calendar-list" style={{ marginTop: 14 }}>
              {visibleEvents.map((event) => <CalendarEventRow key={event.id} event={event} />)}
            </div>
          ) : (
            <div className="mx-empty-panel">
              <CalendarDays size={21} aria-hidden="true" />
              <h2>No events in this view</h2>
              <p>The sample event does not match these filters. Adjust the date range or impact to see it.</p>
            </div>
          )}

          <details style={{ marginTop: 15, color: "var(--mx-muted)", fontSize: 10 }}>
            <summary style={{ display: "inline-flex", cursor: "pointer", alignItems: "center", gap: 7, color: "var(--mx-gold)" }}>
              <Info size={13} aria-hidden="true" /> About this sample view
              <ChevronDown size={13} aria-hidden="true" />
            </summary>
            <p style={{ maxWidth: 650, margin: "8px 0 0", lineHeight: 1.7 }}>
              This mockup contains one clearly labeled example record. A connected calendar should show only events, values, sources, and update statuses returned by its existing feed.
            </p>
          </details>
        </section>

        <p className="mx-feature-footnote">
          For learning and USD/gold study only. Schedules can change; check the named source. Nothing here is a recommendation to trade.
        </p>
        <footer className="mx-dashboard-footer">
          <span>VAYDA SMART MONEY HUB · PROCESS OVER PREDICTION</span>
          <span>Learning only. Trading involves risk.</span>
        </footer>
      </div>
    </main>
  );
}
