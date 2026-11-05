import { useState } from "react";
import { getGetPortalChannelHistoryQueryKey, useGetPortalChannelHistory } from "@workspace/api-client-react";
import { History, RefreshCw, Paperclip, ChevronLeft, ChevronRight } from "lucide-react";
import { Link } from "wouter";

const pageSize = 25;
const destinations = [
  { value: "all", label: "All destinations" },
  { value: "signals", label: "PRO Signals" },
  { value: "analysis", label: "Market Analysis" },
  { value: "education", label: "Education video topic" },
] as const;
const botSources = [
  { value: "main", label: "Main bot — Development" },
  { value: "test", label: "Private test bot" },
] as const;

function labelEvent(event: string) {
  const labels: Record<string, string> = {
    setup: "Active zone",
    signal: "Trade signal",
    update: "Trade update",
    analysis: "Analysis post",
    edit: "Signal edit",
    posted: "Manual Telegram post",
    edited: "Manual Telegram edit",
    education_video: "Video lesson",
  };
  return labels[event] ?? event.replaceAll("_", " ");
}

function labelStatus(status: string) {
  const labels: Record<string, string> = {
    done: "Published",
    received: "Recorded",
    queued: "Queued",
    sending: "Sending",
    uncertain: "Needs reconciliation",
    failed: "Failed",
    blocked: "Blocked",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

export default function ChannelHistory() {
  const [page, setPage] = useState(0);
  const [destination, setDestination] = useState<(typeof destinations)[number]["value"]>("all");
  const [bot, setBot] = useState<(typeof botSources)[number]["value"]>("main");
  const history = useGetPortalChannelHistory(
    { page, limit: pageSize, destination, bot },
    { query: {
      queryKey: getGetPortalChannelHistoryQueryKey({ page, limit: pageSize, destination, bot }),
      staleTime: 15_000,
      refetchInterval: 30_000,
      refetchOnWindowFocus: false,
    } },
  );

  const changeDestination = (value: (typeof destinations)[number]["value"]) => {
    setDestination(value);
    setPage(0);
  };
  const changeBot = (value: (typeof botSources)[number]["value"]) => {
    setBot(value);
    setPage(0);
  };
  const botLabel = bot === "main" ? "Main bot — Development" : "Private test bot";

  return <main className="page channel-history-page">
    <div className="page-heading">
      <div>
        <div className="eyebrow">OWNER TOOLS · DEVELOPMENT</div>
        <h1>Channel history</h1>
        <p className="subheading">Review stored posts from the main bot or private test bot, kept separate.</p>
      </div>
      <div className="history-heading-actions">
        <Link className="btn btn-outline" href="/command-center"><ChevronLeft size={15}/>Command center</Link>
        <button className="btn btn-outline" onClick={() => history.refetch()} disabled={history.isFetching} aria-label="Refresh channel history">
          <RefreshCw size={15} className={history.isFetching ? "spin" : ""}/>{history.isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </div>
    </div>

    <div className="notice notice-info" role="note">
      Showing {botLabel} records only. This Preview does not read a Production database or import older Telegram posts. Member conversations are not shown here.
    </div>
    <section className="section-panel history-panel">
      <div className="section-head history-toolbar">
        <div><h2 className="section-title">Posts and updates</h2><p className="section-note">Bot messages, chart/video attachment labels, and approved-channel posts.</p></div>
        <label className="history-filter-label">Bot
          <select className="filter-select" value={bot} onChange={(event) => changeBot(event.target.value as typeof bot)} aria-label="Filter by bot">
            {botSources.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
        <label className="history-filter-label">Destination
          <select className="filter-select" value={destination} onChange={(event) => changeDestination(event.target.value as typeof destination)} aria-label="Filter by destination">
            {destinations.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
      </div>
      <div className="history-capture-note">
        Only records already saved in the selected Development database appear here. Older Telegram messages are not backfilled.
      </div>

      {history.isLoading ? <div className="history-loading" aria-label="Loading channel history"><div/><div/><div/></div>
        : history.isError ? <div className="history-error" role="alert"><strong>History could not be loaded.</strong><span>{history.error.message || "Please try again."}</span><button className="btn btn-outline" onClick={() => history.refetch()}>Try again</button></div>
        : history.data?.items.length ? <div className="history-list">
          {history.data.items.map((item, index) => <article className="history-item" key={`${item.recordedAt}-${index}`}>
            <div className="history-item-heading">
              <div className="history-item-title">
                <span className="history-type-icon"><History size={16}/></span>
                <div><h3>{labelEvent(item.eventType)}</h3><p>{item.destination}</p></div>
              </div>
              <div className="history-item-meta"><span className={`status status-${item.status}`}>{labelStatus(item.status)}</span><time>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(item.recordedAt))}</time></div>
            </div>
            <div className="history-item-source">{item.source === "bot" ? botLabel : "Posted manually in Telegram"}</div>
            {item.messageText && <p className="history-message">{item.messageText}</p>}
            {item.attachmentLabel !== "No attachment" && <div className="history-attachment"><Paperclip size={14}/>{item.attachmentLabel} <span>Media is not copied into the portal.</span></div>}
          </article>)}
        </div> : <div className="history-empty"><History size={22}/><strong>No saved posts for this bot and destination</strong><span>Posts appear after they are recorded in this Development database.</span></div>}

      {history.data && <div className="history-pagination">
        <span>Page {history.data.page + 1}</span>
        <div><button className="btn btn-outline" onClick={() => setPage((current) => Math.max(0, current - 1))} disabled={page === 0 || history.isFetching}><ChevronLeft size={15}/>Previous</button>
          <button className="btn btn-outline" onClick={() => setPage((current) => current + 1)} disabled={!history.data?.hasMore || history.isFetching}>Next<ChevronRight size={15}/></button></div>
      </div>}
    </section>
  </main>;
}
