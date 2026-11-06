import { Activity, ArrowLeft, CalendarDays, Clock3, ExternalLink, RefreshCw, ShieldCheck } from "lucide-react";
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
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("en-NG", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function CalendarEventRow() {
  const eventDate = new Date(`${sampleEvent.eventDate}T00:00:00`);
  const dateLabel = new Intl.DateTimeFormat("en-NG", { weekday: "short", month: "short", day: "numeric" }).format(eventDate);
  return <article className="mx-calendar-row">
    <div className="mx-event-date"><strong>{dateLabel}</strong><span><Clock3 size={12} /> {sampleEvent.timeLabel}</span></div>
    <div className="mx-event-main"><div className="mx-event-title-line"><h3>{sampleEvent.title}</h3><span className="mx-impact mx-impact-high">High impact</span></div>
      <div className="mx-event-meta"><span>{sampleEvent.currency} · {sampleEvent.impactBasis.replaceAll("_", " ")}</span><span>{sampleEvent.verificationStatus.replaceAll("_", " ")}</span><span>{sampleEvent.timezoneStatus.replaceAll("_", " ")}</span></div>
    </div>
    <div className="mx-event-values"><span><small>PREVIOUS</small><strong>{sampleEvent.previous}</strong></span><span><small>FORECAST</small><strong>{sampleEvent.forecast}</strong></span><span><small>ACTUAL</small><strong>{sampleEvent.actual}</strong></span></div>
    <div className="mx-event-source"><small>Source · {sampleEvent.sourceName} · Retrieved {prettyStamp(sampleEvent.lastRetrievedAt)}</small><button className="mx-button" type="button" disabled>View source <ExternalLink size={13} /></button></div>
  </article>;
}

export function Current() {
  return <main className="smh-calendar">
    <div className="mx-dashboard-shell">
      <header className="mx-dashboard-header">
        <a className="mx-wordmark" href="#"><img className="mx-wordmark-image" src="/__mockup/images/vayda-logo.png" alt="" /><span><strong>VAYDA</strong><small>SMART MONEY HUB</small></span></a>
        <span className="mx-feature-private"><ShieldCheck size={14} /> PRIVATE LEARNING SPACE</span>
      </header>
      <nav className="mx-feature-nav" aria-label="Member learning tools">
        <a className="mx-feature-back" href="#"><ArrowLeft size={14} /> Workspace</a>
        <div className="mx-feature-nav-links">
          <a className="mx-feature-nav-link is-active" href="#"><CalendarDays size={17} /><span>Economic calendar</span></a>
          <a className="mx-feature-nav-link" href="#"><Activity size={17} /><span>Trade journal</span></a>
          <a className="mx-feature-nav-link" href="#"><span>AI Coach</span></a>
        </div>
      </nav>
      <section className="mx-feature-heading">
        <div className="mx-overline"><span className="mx-live-mark" /> STUDY / USD EVENTS</div>
        <h1>Economic calendar</h1>
        <p>A source-aware view of scheduled USD releases relevant to USD and gold study. Timing and reported values are shown as supplied; this is not a trade signal.</p>
      </section>
      <section className="mx-feature-panel">
        <div className="mx-panel-toolbar">
          <div><span className="mx-card-kicker">OFFICIAL USD CALENDAR</span><p>Source status and retrieval time stay visible so you can judge context.</p></div>
          <button className="mx-button" type="button"><RefreshCw size={14} /> Refresh</button>
        </div>
        <div className="mx-filter-row">
          <label className="mx-filter-field">From<input type="date" defaultValue="2026-11-06" /></label>
          <label className="mx-filter-field">Through<input type="date" defaultValue="2026-11-20" /></label>
          <label className="mx-filter-field">Impact<select defaultValue=""><option value="">All impacts</option><option>High</option><option>Medium</option><option>Low</option></select></label>
          <span className="mx-calendar-clock"><Clock3 size={14} /> Times shown in source timezone where available</span>
        </div>
        <div className="mx-sample-note">EXAMPLE ONLY · Event and value data are illustrative, not live.</div>
        <div className="mx-source-status"><span><i /> Feed status</span><span>Refreshed {prettyStamp("2026-11-06T00:00:00.000Z")}</span></div>
        <div className="mx-source-list"><div className="mx-source-item"><strong>Official source (example)</strong><span className="mx-source-badge">Available</span><small>Sample source status · not live</small></div></div>
        <div className="mx-calendar-list"><CalendarEventRow /></div>
      </section>
      <p className="mx-feature-footnote">XAUUSD study context only. Market schedules may change; confirm details with the named source before relying on them.</p>
      <footer className="mx-dashboard-footer"><span>VAYDA SMART MONEY HUB · PROCESS OVER PREDICTION</span><span>Learning only. Trading involves risk.</span></footer>
    </div>
  </main>;
}
