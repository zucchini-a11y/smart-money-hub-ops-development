import { useMemo, useState, type FormEvent } from "react";
import {
  ArrowDownUp,
  ArrowLeft,
  Bot,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Inbox,
  LockKeyhole,
  LogOut,
  MessageCircle,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  Users,
} from "lucide-react";
import "./PortalLook.css";

type Source = "Coach" | "Signals";
type Status = "new" | "assigned" | "in_progress" | "waiting_for_member" | "resolved" | "closed";
type Message = {
  id: number;
  sender: "member" | "staff";
  name: string;
  time: string;
  text: string;
};
type SupportCase = {
  id: string;
  source: Source;
  time: string;
  created: string;
  question: string;
  status: Status;
  priority: "normal" | "low" | "high";
  messages: Message[];
  assignee: string;
  notes: string[];
  history: string[];
};

const seedCases: SupportCase[] = [
  {
    id: "CASE-1042",
    source: "Coach",
    time: "10:42 AM",
    created: "Today, 9:18 AM",
    question: "I’m comparing two savings options. How should I think about a fixed rate versus an account that can change its rate?",
    status: "in_progress",
    priority: "normal",
    assignee: "Avery Chen",
    messages: [
      { id: 1, sender: "member", name: "Member · redacted", time: "9:18 AM", text: "I’m comparing two savings options. How should I think about a fixed rate versus an account that can change its rate?" },
      { id: 2, sender: "staff", name: "Avery Chen", time: "9:36 AM", text: "A fixed rate stays the same for the agreed term, while a variable rate may move over time. It can help to compare access rules and fees alongside the advertised rate." },
      { id: 3, sender: "member", name: "Member · redacted", time: "10:42 AM", text: "That helps. Is there a simple way to compare them if I might need access to the money sooner?" },
    ],
    notes: ["Follow up with the liquidity and early-access comparison guide."],
    history: ["Avery Chen moved case to in progress · Today, 9:22 AM", "Case received from Coach · Today, 9:18 AM"],
  },
  {
    id: "CASE-1041",
    source: "Signals",
    time: "10:08 AM",
    created: "Today, 8:54 AM",
    question: "Could you explain why a market signal can change after it first appears?",
    status: "new",
    priority: "normal",
    assignee: "Unassigned",
    messages: [
      { id: 4, sender: "member", name: "Member · redacted", time: "8:54 AM", text: "Could you explain why a market signal can change after it first appears?" },
      { id: 5, sender: "staff", name: "Support team", time: "9:14 AM", text: "Signals reflect the information and conditions available at a given time. If those conditions change, the signal can update too; it’s best used as context rather than a guarantee." },
    ],
    notes: ["Share the short guide on how signal updates are calculated."],
    history: ["Case received from Signals · Today, 8:54 AM"],
  },
  {
    id: "CASE-1039",
    source: "Coach",
    time: "Yesterday",
    created: "Yesterday, 2:51 PM",
    question: "I missed a scheduled lesson this week. Can I pick up where I left off?",
    status: "waiting_for_member",
    priority: "low",
    assignee: "Jordan Lee",
    messages: [
      { id: 6, sender: "member", name: "Member · redacted", time: "2:51 PM", text: "I missed a scheduled lesson this week. Can I pick up where I left off?" },
      { id: 7, sender: "staff", name: "Jordan Lee", time: "3:10 PM", text: "Absolutely. Your lesson history stays available, so you can continue with the next lesson whenever you’re ready." },
    ],
    notes: ["Waiting to hear whether the lesson link worked."],
    history: ["Jordan Lee changed status to waiting for member · Yesterday, 3:12 PM"],
  },
  {
    id: "CASE-1037",
    source: "Signals",
    time: "Yesterday",
    created: "Yesterday, 11:06 AM",
    question: "Where can I find the explanation behind a comparison in the weekly recap?",
    status: "resolved",
    priority: "normal",
    assignee: "Avery Chen",
    messages: [
      { id: 8, sender: "member", name: "Member · redacted", time: "11:06 AM", text: "Where can I find the explanation behind a comparison in the weekly recap?" },
      { id: 9, sender: "staff", name: "Avery Chen", time: "11:34 AM", text: "Open the recap item and choose “Why this comparison?” to see its sources and a plain-language explanation." },
    ],
    notes: ["Resolved with recap navigation instructions."],
    history: ["Avery Chen resolved case · Yesterday, 11:38 AM"],
  },
  {
    id: "CASE-1035",
    source: "Coach",
    time: "Mon",
    created: "Mon, 3:02 PM",
    question: "Can I adjust how often I receive my learning reminders?",
    status: "assigned",
    priority: "normal",
    assignee: "Morgan Patel",
    messages: [
      { id: 10, sender: "member", name: "Member · redacted", time: "3:02 PM", text: "Can I adjust how often I receive my learning reminders?" },
      { id: 11, sender: "staff", name: "Morgan Patel", time: "3:26 PM", text: "Yes. You can change the reminder schedule in your Coach preferences, including pausing reminders for a while." },
    ],
    notes: ["Check that reminder settings are clear in the next release."],
    history: ["Morgan Patel assigned case to self · Mon, 3:08 PM"],
  },
];

const statusLabels: Record<Status, string> = {
  new: "New",
  assigned: "Assigned",
  in_progress: "In progress",
  waiting_for_member: "Waiting on member",
  resolved: "Resolved",
  closed: "Closed",
};

export function PortalLook() {
  const [cases, setCases] = useState(seedCases);
  const [selectedId, setSelectedId] = useState(seedCases[0].id);
  const [sourceFilter, setSourceFilter] = useState("All sources");
  const [statusFilter, setStatusFilter] = useState("All statuses");
  const [search, setSearch] = useState("");
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");
  const [composeMode, setComposeMode] = useState<"reply" | "note">("reply");
  const [notice, setNotice] = useState("Queue synced just now · 2 cases need a reply");
  const [refreshed, setRefreshed] = useState(false);

  const selected = cases.find((item) => item.id === selectedId) ?? cases[0];
  const visibleCases = useMemo(
    () =>
      cases.filter((item) => {
        const matchesSource = sourceFilter === "All sources" || item.source === sourceFilter;
        const matchesStatus = statusFilter === "All statuses" || item.status === statusFilter;
        const matchesSearch = `${item.id} ${item.question} ${item.source}`.toLowerCase().includes(search.toLowerCase());
        return matchesSource && matchesStatus && matchesSearch;
      }),
    [cases, search, sourceFilter, statusFilter],
  );
  const openCount = cases.filter((item) => !["resolved", "closed"].includes(item.status)).length;

  const updateSelected = (patch: Partial<SupportCase>, historyText?: string) => {
    setCases((current) =>
      current.map((item) =>
        item.id === selected.id
          ? { ...item, ...patch, history: historyText ? [historyText, ...item.history] : item.history }
          : item,
      ),
    );
  };

  const sendMessage = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = reply.trim();
    if (!text) return;
    const now = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    updateSelected(
      { messages: [...selected.messages, { id: Date.now(), sender: "staff", name: "Avery Chen", time: now, text }] },
      `Avery Chen queued a reply · Today, ${now}`,
    );
    setReply("");
    setNotice("Reply queued for delivery through the originating bot.");
  };

  const saveNote = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = note.trim();
    if (!text) return;
    updateSelected({ notes: [text, ...selected.notes] }, "Avery Chen added a private note · Today, just now");
    setNote("");
    setNotice("Private note saved for the support team.");
  };

  const chooseStatus = (value: string) => {
    const status = value as Status;
    updateSelected({ status }, `Avery Chen changed status to ${statusLabels[status]} · Today, just now`);
  };

  return (
    <div className="portal-look">
      <header className="portal-topbar">
        <div className="portal-brand">
          <div className="portal-mark"><ShieldCheck size={19} strokeWidth={2.2} /></div>
          <div>
            <div className="portal-brand-name">smart money hub</div>
            <div className="portal-brand-sub">SUPPORT PORTAL <span>·</span> STAFF WORKSPACE</div>
          </div>
        </div>
        <div className="portal-top-actions">
          <div className="portal-secure"><span className="portal-secure-dot" /> Staff session active</div>
          <button className="portal-logout" type="button" onClick={() => setNotice("Demo workspace · sign out is disabled in this preview.")}>
            <LogOut size={15} /> <span>Sign out</span>
          </button>
          <div className="portal-user">
            <span className="portal-avatar">AC</span>
            <span className="portal-user-name">Avery Chen</span>
            <ChevronDown size={14} />
          </div>
        </div>
      </header>

      <main className="portal-main">
        <div className="portal-heading">
          <div>
            <div className="portal-eyebrow">SHARED MEMBER SUPPORT</div>
            <h1>Support cases</h1>
            <p>Signals and Coach requests, together in one place.</p>
          </div>
          <div className="portal-heading-meta">
            <span className="portal-live"><span /> Queue live</span>
            <span className="portal-heading-divider" />
            <span>Last sync <strong>just now</strong></span>
          </div>
        </div>

        <div className="portal-notice" role="status">
          <span className="portal-notice-icon"><Sparkles size={15} /></span>
          <span>{notice}</span>
          <button type="button" aria-label="Dismiss notification" onClick={() => setNotice("")}>×</button>
        </div>

        <section className="portal-workspace" aria-label="Support case workspace">
          <aside className={`portal-queue ${selectedId ? "portal-queue-mobile-hidden" : ""}`}>
            <div className="portal-queue-head">
              <div>
                <div className="portal-section-kicker">INBOX</div>
                <h2>Case queue <span>{visibleCases.length}</span></h2>
              </div>
              <button
                className={`portal-icon-button ${refreshed ? "is-refreshed" : ""}`}
                type="button"
                aria-label="Refresh support cases"
                onClick={() => { setRefreshed(true); setNotice("Queue refreshed · all cases are up to date."); window.setTimeout(() => setRefreshed(false), 700); }}
              >
                <RefreshCw size={16} />
              </button>
            </div>
            <div className="portal-queue-summary">
              <span><b>{openCount}</b> open</span>
              <span className="portal-summary-dot" />
              <span><b>2</b> awaiting reply</span>
            </div>
            <div className="portal-search">
              <Search size={15} />
              <input aria-label="Search cases" placeholder="Search cases…" value={search} onChange={(event) => setSearch(event.target.value)} />
              <kbd>⌘ K</kbd>
            </div>
            <div className="portal-filters">
              <label className="portal-filter-select">
                <SlidersHorizontal size={13} />
                <select aria-label="Filter by source" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
                  <option>All sources</option><option>Coach</option><option>Signals</option>
                </select>
                <ChevronDown size={12} />
              </label>
              <label className="portal-filter-select">
                <select aria-label="Filter by status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  <option>All statuses</option>
                  {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
                <ChevronDown size={12} />
              </label>
            </div>
            <div className="portal-case-list">
              {visibleCases.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`portal-case-row ${selected.id === item.id ? "is-selected" : ""}`}
                  onClick={() => { setSelectedId(item.id); setReply(""); setNote(""); }}
                >
                  <span className={`portal-case-source ${item.source === "Coach" ? "source-coach" : "source-signals"}`}>
                    <Bot size={13} /> {item.source}
                  </span>
                  <span className="portal-case-time">{item.time}</span>
                  <span className="portal-case-question">{item.question}</span>
                  <span className="portal-case-meta">
                    <span className={`portal-status-dot status-${item.status}`} />
                    <span>{statusLabels[item.status]}</span>
                    <span className="portal-meta-sep">·</span>
                    <span>{item.assignee === "Unassigned" ? "Unassigned" : item.assignee.split(" ")[0]}</span>
                  </span>
                  {item.priority === "low" && <span className="portal-priority">LOW</span>}
                </button>
              ))}
              {!visibleCases.length && (
                <div className="portal-empty">
                  <Inbox size={23} />
                  <strong>No cases match</strong>
                  <span>Try another source, status, or search.</span>
                  <button type="button" onClick={() => { setSearch(""); setSourceFilter("All sources"); setStatusFilter("All statuses"); }}>Clear filters</button>
                </div>
              )}
            </div>
            <div className="portal-queue-foot"><span className="portal-sync-mark" /> Auto-refreshes every 15 seconds</div>
          </aside>

          <section className={`portal-detail ${!selectedId ? "portal-detail-mobile-hidden" : ""}`}>
            <div className="portal-detail-head">
              <button className="portal-back" type="button" onClick={() => setSelectedId("")}><ArrowLeft size={15} /> Queue</button>
              <div className="portal-detail-titleline">
                <div>
                  <div className="portal-case-id">{selected.id}<span className="portal-detail-bullet">·</span><span className={`portal-inline-source ${selected.source === "Coach" ? "source-coach" : "source-signals"}`}><Bot size={13} /> {selected.source}</span></div>
                  <h2>Conversation</h2>
                </div>
                <div className="portal-case-controls">
                  <label className="portal-assignee">
                    <Users size={14} />
                    <select aria-label="Assigned staff" value={selected.assignee} onChange={(event) => updateSelected({ assignee: event.target.value }, `Case assigned to ${event.target.value} · Today, just now`)}>
                      <option>Unassigned</option><option>Avery Chen</option><option>Jordan Lee</option><option>Morgan Patel</option><option>Support team · manager</option>
                    </select>
                    <ChevronDown size={12} />
                  </label>
                  <label className="portal-status-control">
                    <span className={`portal-status-dot status-${selected.status}`} />
                    <select aria-label="Workflow status" value={selected.status} onChange={(event) => chooseStatus(event.target.value)}>
                      {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                    <ChevronDown size={12} />
                  </label>
                  <button className="portal-icon-button portal-more" type="button" title="Case actions" onClick={() => setNotice("Case actions are available in the full support portal.")}><ArrowDownUp size={15} /></button>
                </div>
              </div>
            </div>

            <div className="portal-question">
              <div className="portal-question-label"><CircleHelp size={15} /> MEMBER QUESTION</div>
              <p>{selected.question}</p>
              <div className="portal-question-meta">
                <span><UserRound size={13} /> Member · redacted</span>
                <span><Clock3 size={13} /> Received {selected.created}</span>
                <span><MessageCircle size={13} /> {selected.messages.length} messages</span>
              </div>
            </div>

            <div className="portal-thread-head">
              <span>THREAD</span>
              <span>{selected.messages.length} messages <span className="portal-thread-separator">·</span> Delivered by {selected.source}</span>
            </div>
            <div className="portal-thread" aria-live="polite">
              {selected.messages.map((message) => (
                <article key={message.id} className={`portal-message ${message.sender === "staff" ? "message-staff" : "message-member"}`}>
                  <div className="portal-message-avatar">{message.sender === "staff" ? "AC" : <UserRound size={14} />}</div>
                  <div className="portal-message-body">
                    <div className="portal-message-head">
                      <strong>{message.name}</strong><time>{message.time}</time>
                      {message.sender === "staff" && <span className="portal-delivered"><Check size={11} /> delivered</span>}
                    </div>
                    <p>{message.text}</p>
                  </div>
                </article>
              ))}
            </div>

            <div className="portal-compose">
              <div className="portal-compose-tabs" role="tablist" aria-label="Compose mode">
                <button type="button" role="tab" aria-selected={composeMode === "reply"} className={composeMode === "reply" ? "active" : ""} onClick={() => setComposeMode("reply")}><MessageCircle size={14} /> Reply</button>
                <button type="button" role="tab" aria-selected={composeMode === "note"} className={composeMode === "note" ? "active note-active" : ""} onClick={() => setComposeMode("note")}><LockKeyhole size={13} /> Private note</button>
                <span className="portal-compose-hint">{composeMode === "reply" ? `Sent through ${selected.source}` : "Visible to staff only"}</span>
              </div>
              {composeMode === "reply" ? (
                <form className="portal-compose-form" onSubmit={sendMessage}>
                  <textarea aria-label="Reply to member" value={reply} onChange={(event) => setReply(event.target.value)} placeholder="Write a thoughtful reply…" rows={3} />
                  <div className="portal-compose-bottom">
                    <span>Never include passwords or verification codes.</span>
                    <button className="portal-send" type="submit" disabled={!reply.trim() || selected.status === "closed"}><Send size={14} /> Queue reply</button>
                  </div>
                </form>
              ) : (
                <form className="portal-compose-form portal-note-form" onSubmit={saveNote}>
                  <textarea aria-label="Private staff note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Add context for the support team…" rows={3} />
                  <div className="portal-compose-bottom">
                    <span><LockKeyhole size={12} /> Only support staff can see this note.</span>
                    <button className="portal-note-save" type="submit" disabled={!note.trim()}><Check size={14} /> Save private note</button>
                  </div>
                </form>
              )}
            </div>

            <div className="portal-records">
              <section className="portal-record">
                <div className="portal-record-heading"><span className="portal-record-icon note-icon"><LockKeyhole size={13} /></span><h3>Private notes</h3><span className="portal-record-count">{selected.notes.length}</span></div>
                {selected.notes.map((item, index) => <p className="portal-note-item" key={`${item}-${index}`}><strong>Avery Chen</strong><span>Today · staff only</span>{item}</p>)}
              </section>
              <section className="portal-record portal-history">
                <div className="portal-record-heading"><span className="portal-record-icon history-icon"><Clock3 size={13} /></span><h3>Case history</h3><span className="portal-record-count">{selected.history.length}</span></div>
                {selected.history.slice(0, 3).map((item, index) => <p className="portal-history-item" key={`${item}-${index}`}><span className="portal-history-line" />{item}</p>)}
              </section>
            </div>
          </section>
        </section>
        <footer className="portal-footer"><span><ShieldCheck size={13} /> Staff-only workspace</span><span>Support Portal <i>·</i> Preview data is fictional and redacted</span></footer>
      </main>
    </div>
  );
}
