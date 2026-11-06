import { useEffect, useRef, useState, type Dispatch, type FormEvent, type SetStateAction, type RefObject } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Bell,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileText,
  GraduationCap,
  LayoutDashboard,
  LockKeyhole,
  LogOut,
  MessageCircle,
  Menu,
  Plus,
  Radio,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  WalletCards,
  X,
} from "lucide-react";
import "./_group.css";

type VaydaState = "idle" | "blinking" | "breathing" | "listening" | "thinking" | "speaking";
type ConversationMessage = { role: "member" | "vayda"; text: string };
type MemberView = "Home" | "Economic Calendar" | "Trading Journal" | "AI Coach" | "PRO Signals" | "Education" | "Account Settings";
type MemberScenario = "Free member" | "PRO preview";

const memberNavigation: { label: MemberView; icon: typeof LayoutDashboard }[] = [
  { label: "Home", icon: LayoutDashboard },
  { label: "Economic Calendar", icon: CalendarDays },
  { label: "Trading Journal", icon: FileText },
  { label: "AI Coach", icon: MessageCircle },
  { label: "PRO Signals", icon: Radio },
  { label: "Education", icon: GraduationCap },
  { label: "Account Settings", icon: Settings2 },
];

const memberSampleEvents = [
  { title: "Illustrative CPI release", time: "08:30 local", currency: "USD", impact: "High", status: "Upcoming" },
  { title: "Example central bank remarks", time: "10:00 local", currency: "USD", impact: "High", status: "Upcoming" },
  { title: "Illustrative employment claims", time: "Tomorrow · 08:30 local", currency: "USD", impact: "Medium", status: "Upcoming" },
];

const memberSuggestedQuestions = [
  "Explain BOS and CHoCH",
  "What is a liquidity sweep?",
  "Help me calculate risk-to-reward",
  "Explain displacement",
  "Help me review my trading journal",
  "How can USD news affect gold?",
];

type MemberFeaturePanelProps = {
  activeView: Exclude<MemberView, "Home">;
  scenario: MemberScenario;
  preferences: { calendar: boolean; learning: boolean; product: boolean; signals: boolean };
  setPreferences: Dispatch<SetStateAction<{ calendar: boolean; learning: boolean; product: boolean; signals: boolean }>>;
  navigate: (view: MemberView) => void;
  setAssistantState: Dispatch<SetStateAction<VaydaState>>;
  sendPrompt: (prompt: string) => void;
  demoTradeCount: number;
  openTradeForm: () => void;
  onDemoNotice: (text: string) => void;
  assistantState: VaydaState;
  conversation: ConversationMessage[];
  isTyping: boolean;
  message: string;
  setMessage: (message: string) => void;
  submitPreview: (event: FormEvent<HTMLFormElement>) => void;
  chatLogRef: RefObject<HTMLDivElement | null>;
};

function MemberFeaturePanel({
  activeView, scenario, preferences, setPreferences, navigate, setAssistantState, sendPrompt,
  demoTradeCount, openTradeForm, onDemoNotice, assistantState, conversation, isTyping,
  message, setMessage, submitPreview, chatLogRef,
}: MemberFeaturePanelProps) {
  const [calendarImpact, setCalendarImpact] = useState("All");
  const [journalOutcome, setJournalOutcome] = useState("All outcomes");
  const sampleJournal = [
    { instrument: "XAUUSD", side: "Buy", result: "Win", note: "Waited for confirmation before planning." },
    { instrument: "EURUSD", side: "Sell", result: "Loss", note: "Review: entered before the lower-timeframe break." },
    { instrument: "GBPUSD", side: "Buy", result: "Breakeven", note: "Followed the written invalidation plan." },
  ];

  const pageCopy: Record<Exclude<MemberView, "Home">, { kicker: string; title: string; description: string }> = {
    "Economic Calendar": { kicker: "MEMBER TOOL · SAMPLE EVENTS", title: "Economic Calendar", description: "Illustrative event schedule for study only. These are not live economic data." },
    "Trading Journal": { kicker: "MEMBER TOOL · DEMO ENTRIES", title: "Trading Journal", description: "Review the plan, outcome, emotional state, and lesson. Sample entries remain local to this prototype." },
    "AI Coach": { kicker: "VAYDA · SCRIPTED DEMO", title: "AI Coach", description: "Ask a general learning question. Replies are scripted; no live AI service or market feed is connected." },
    "PRO Signals": { kicker: "PRO MEMBERSHIP PREVIEW", title: "PRO Signals", description: "Illustrative examples only. Not a trade recommendation and not connected to MT5." },
    "Education": { kicker: "MEMBER LEARNING SPACE · SAMPLE PROGRESS", title: "Education", description: "A local preview of lessons, classes, and learning progress. Nothing is marked complete or saved." },
    "Account Settings": { kicker: "DEMO-ONLY PREFERENCES", title: "Account Settings", description: "Controls update this preview locally only. No settings are saved or delivered." },
  };
  const copy = pageCopy[activeView];

  return <div className="member-feature-content">
    <div className="member-feature-heading">
      <div><div className="member-section-kicker">{copy.kicker}</div><h1>{copy.title}</h1><p>{copy.description}</p></div>
      <button className="member-feature-back" type="button" onClick={() => navigate("Home")}><ArrowRight size={14} /> Home</button>
    </div>

    {activeView === "Economic Calendar" && <section className="member-feature-panel">
      <div className="member-feature-toolbar"><div><span className="member-feature-kicker">UPCOMING SAMPLE SCHEDULE</span><span className="member-sample-pill">SAMPLE · NOT LIVE</span></div>
        <div className="member-filter-pills">{["All", "High", "Medium"].map((impact) => <button type="button" key={impact} className={calendarImpact === impact ? "selected" : ""} onClick={() => setCalendarImpact(impact)}>{impact} impact</button>)}</div>
      </div>
      <div className="member-sample-event-list">{memberSampleEvents.filter((event) => calendarImpact === "All" || event.impact === calendarImpact).map((event) => <article className="member-sample-event" key={event.title}>
        <span className={`member-impact-marker ${event.impact === "High" ? "high" : ""}`} />
        <div className="member-sample-event-time"><strong>{event.time}</strong><small>Illustrative sample date</small></div>
        <div className="member-sample-event-detail"><strong>{event.title}</strong><small>{event.currency} · {event.impact} impact · {event.status}</small><small>Forecast — · Previous — · Actual —</small></div>
        <span className={`member-sample-impact ${event.impact === "High" ? "high" : ""}`}>{event.impact}</span>
      </article>)}</div>
      <p className="member-feature-disclaimer">Dates, times, event names, impact and values are demonstration content. No external calendar feed is connected.</p>
    </section>}

    {activeView === "Trading Journal" && <div className="member-feature-stack">
      <div className="member-journal-metrics">{[["DEMO ENTRIES", String(demoTradeCount)], ["WINS", "1"], ["LOSSES", "1"], ["WIN RATE", "33%"], ["AVG PLANNED R:R", "2.5:1"]].map(([label,value]) => <div className="member-journal-metric" key={label}><small>{label}</small><strong>{value}</strong><span>Sample view only</span></div>)}</div>
      <section className="member-feature-panel"><div className="member-feature-toolbar"><div><span className="member-feature-kicker">RECENT JOURNAL ACTIVITY</span><span className="member-sample-pill">DEMO DATA</span></div><div className="member-journal-toolbar"><select value={journalOutcome} onChange={(event) => setJournalOutcome(event.currentTarget.value)} aria-label="Filter journal outcome"><option>All outcomes</option><option>Win</option><option>Loss</option><option>Breakeven</option></select><button className="member-feature-action" type="button" onClick={openTradeForm}><Plus size={14} /> Add Trade</button></div></div>
        <div className="member-journal-list">{sampleJournal.filter((trade) => journalOutcome === "All outcomes" || trade.result === journalOutcome).map((trade) => <article className="member-journal-row" key={trade.instrument}><span className="member-journal-symbol">{trade.instrument}</span><span>{trade.side}</span><span className={trade.result === "Win" ? "member-outcome-win" : trade.result === "Loss" ? "member-outcome-loss" : ""}>{trade.result}</span><span>{trade.note}</span></article>)}{journalOutcome !== "All outcomes" && !sampleJournal.some((trade) => trade.result === journalOutcome) && <p className="member-feature-disclaimer">No entries in this outcome filter.</p>}</div>
        <p className="member-feature-disclaimer">Trades, outcomes, metrics, and notes are sample data. Add Trade updates only a local demo count; no account information or files are stored.</p>
      </section>
    </div>}

    {activeView === "AI Coach" && <section className="member-feature-panel member-feature-coach">
      <div className="member-feature-toolbar"><div className="member-feature-vayda"><span className="member-ask-avatar"><VaydaPortrait state={assistantState} /></span><span><strong>Vayda</strong><small>Scripted learning companion</small></span></div><span className={`member-coach-state state-label-${assistantState}`}><i />{assistantState}</span></div>
      <div className="member-feature-chat-log" ref={chatLogRef} role="log" aria-live="polite">{conversation.map((entry,index) => <div className={`member-chat-message ${entry.role === "member" ? "is-member" : "is-vayda"}`} key={`${entry.role}-${index}`}><p>{entry.text}</p></div>)}{isTyping && <div className="member-chat-message is-vayda member-typing" role="status"><p><i /><i /><i /></p></div>}</div>
      <div className="member-suggested-prompts">{memberSuggestedQuestions.map((question) => <button key={question} type="button" disabled={isTyping} onClick={() => sendPrompt(question)}>{question}</button>)}</div>
      <form className="member-ask-form" onSubmit={submitPreview}><label className="visually-hidden" htmlFor="ask-vayda-feature">Ask Vayda a question</label><input id="ask-vayda-feature" value={message} onChange={(event) => setMessage(event.currentTarget.value)} placeholder="Ask a general trading concept question…" maxLength={500} /><button type="submit" disabled={!message.trim() || isTyping} aria-label="Send scripted question"><Send size={16} /></button></form>
      <div className="member-ask-disclaimer"><ShieldCheck size={13} /><span>Scripted demo replies · No live AI · Nothing leaves this preview</span></div>
      <button className="member-listen-button" type="button" onClick={() => { setAssistantState("listening"); window.setTimeout(() => setAssistantState((state) => state === "listening" ? "idle" : state), 1600); }}><Activity size={13} /> Preview listening state</button>
    </section>}

    {activeView === "PRO Signals" && (scenario !== "PRO preview" ? <section className="member-restricted-panel">
      <span className="member-restricted-icon"><LockKeyhole size={22} /></span><span className="member-feature-kicker">ACCESS RESTRICTED</span><h2>PRO Signals are not available in this Free member preview.</h2>
      <p>PRO access is handled separately through verified funded-account status and active PRO entitlement. Registration alone does not grant access.</p>
      <button className="member-feature-action" type="button" onClick={() => onDemoNotice("PRO access cannot be activated by registration in this prototype.")}>Review PRO benefits <ArrowRight size={14} /></button>
    </section> : <section className="member-feature-panel">
      <div className="member-feature-toolbar"><span className="member-sample-pill">PRO PREVIEW · ILLUSTRATIVE ONLY</span><span className="member-feature-disclaimer">Not a recommendation · not connected to MT5</span></div>
      <article className="member-signal-example"><div className="member-signal-example-head"><span><strong>XAUUSD</strong><small>Illustrative Buy · 15 minute</small></span><span className="member-sample-pill">ACTIVE EXAMPLE</span></div><div className="member-signal-values"><span><small>ENTRY ZONE</small><strong>2,914–2,919</strong></span><span><small>STOP LOSS</small><strong className="member-outcome-loss">2,904</strong></span><span><small>TP1 / TP2 / TP3</small><strong>2,934 / 2,949 / 2,969</strong></span><span><small>PLANNED R:R</small><strong>1:1 / 1:2 / 1:3</strong></span></div><div className="member-feature-disclaimer">Sample publication time: 09:15 · illustrative status · historical entries are not live.</div></article>
    </section>)}

    {activeView === "Education" && <div className="member-feature-grid"><section className="member-feature-panel member-education-progress"><div className="member-feature-kicker">SAMPLE LEARNING PROGRESS</div><h2>Market Structure Foundations</h2><div className="member-feature-progress"><i /></div><div className="member-education-progress-meta"><span>4 of 10 lessons · 40%</span><span>DEMO ONLY</span></div><button className="member-feature-action" type="button" onClick={() => onDemoNotice("Lesson opened in demo preview; completion is not recorded.")}>Continue Learning <ArrowRight size={14} /></button></section><section className="member-feature-panel"><div className="member-feature-kicker">RECENT EDUCATION MATERIALS</div>{["BOS and CHoCH: a study guide", "Confirmation before execution", "Risk planning worksheet"].map((lesson,index) => <article className="member-detail-row" key={lesson}><span className="member-detail-time">0{index+1}</span><span><strong>{lesson}</strong><small>Sample learning material · not downloaded</small></span></article>)}</section><section className="member-feature-panel"><div className="member-feature-kicker">UPCOMING CLASS</div><h2>Structure study session</h2><p>Upcoming class placeholder. Date and time have not been scheduled.</p><span className="member-sample-pill">DEMO SCHEDULE</span></section></div>}

    {activeView === "Account Settings" && <div className="member-feature-grid"><section className="member-feature-panel"><div className="member-feature-kicker">NOTIFICATION PREFERENCES · DEMO</div>{[
      ["calendar","Calendar sample reminders","Local display preference only."],
      ["learning","Learning updates","No messages or reminders are sent."],
      ["product","Product announcements","No email subscription is created."],
      ["signals","PRO Signals assistant notifications","No bot connection or notification is enabled."],
    ].map(([key,label,detail]) => <label className="member-setting-row" key={key}><span><strong>{label}</strong><small>{detail}</small></span><input type="checkbox" checked={preferences[key as keyof typeof preferences]} onChange={() => setPreferences({ ...preferences, [key]: !preferences[key as keyof typeof preferences] })} /></label>)}
      <button className="member-feature-action" type="button" onClick={() => onDemoNotice("Settings preview changed locally; nothing was saved.")}>Preview settings <CheckCircle2 size={14} /></button></section><section className="member-feature-panel"><div className="member-feature-kicker">MEMBER PROFILE</div><div className="member-settings-profile"><span className="member-profile-avatar">AM</span><span><strong>Alex Morgan</strong><small>Sample member profile · {scenario}</small></span></div><p className="member-feature-disclaimer">Account details are fictional. This preview does not edit authentication or member records.</p></section></div>}
  </div>;
}

const states: { id: VaydaState; label: string }[] = [
  { id: "idle", label: "Idle" },
  { id: "blinking", label: "Blinking" },
  { id: "breathing", label: "Breathing" },
  { id: "listening", label: "Listening" },
  { id: "thinking", label: "Thinking" },
  { id: "speaking", label: "Speaking" },
];

function VaydaPortrait({ state }: { state: VaydaState }) {
  return (
    <div className={`vayda-portrait state-${state}`} aria-hidden="true">
      <div className="vayda-portrait-glow" />
      <div className="vayda-orbit vayda-orbit-one" />
      <div className="vayda-orbit vayda-orbit-two" />
      <svg className="vayda-face" viewBox="0 0 220 250" fill="none">
        <defs>
          <linearGradient id="vayda-hair" x1="54" y1="42" x2="174" y2="140" gradientUnits="userSpaceOnUse">
            <stop stopColor="#C59B49" />
            <stop offset="1" stopColor="#293448" />
          </linearGradient>
          <linearGradient id="vayda-skin" x1="78" y1="76" x2="155" y2="166" gradientUnits="userSpaceOnUse">
            <stop stopColor="#F2D9BE" />
            <stop offset="1" stopColor="#C79B7A" />
          </linearGradient>
          <linearGradient id="vayda-jacket" x1="53" y1="177" x2="172" y2="245" gradientUnits="userSpaceOnUse">
            <stop stopColor="#344158" />
            <stop offset="1" stopColor="#C59B49" />
          </linearGradient>
        </defs>
        <path className="vayda-shoulders" d="M28 239c7-38 34-61 82-61s75 23 82 61" fill="url(#vayda-jacket)" />
        <path d="M91 167h38v28c-5 12-33 12-38 0v-28Z" fill="#C7B5E9" />
        <path className="vayda-neckline" d="m79 189 31 28 31-28" stroke="#E8D7B0" strokeWidth="4" strokeLinecap="round" />
        <path d="M60 97c0-37 23-63 53-63 32 0 55 24 55 63v26c0 34-24 60-55 60-31 0-53-26-53-60V97Z" fill="url(#vayda-skin)" />
        <path className="vayda-hair-shape" d="M53 107c-9-42 7-78 36-91 35-16 84 1 91 42 4 20-2 40-6 49-7-22-17-39-33-49-22 19-50 27-85 25l-3 24Z" fill="url(#vayda-hair)" />
        <path d="M56 113c-8-5-13 1-10 14 2 9 7 14 14 14m101-28c8-5 13 1 10 14-2 9-7 14-14 14" stroke="#C59B49" strokeWidth="4" strokeLinecap="round" />
        <path className="vayda-eye vayda-eye-left" d="M78 118c5-5 12-5 17 0" stroke="#1E2755" strokeWidth="4" strokeLinecap="round" />
        <path className="vayda-eye vayda-eye-right" d="M126 118c5-5 12-5 17 0" stroke="#1E2755" strokeWidth="4" strokeLinecap="round" />
        <path d="M109 123v15" stroke="#8A71B8" strokeWidth="3" strokeLinecap="round" />
        <path className="vayda-mouth" d="M95 150c8 9 21 9 29 0" stroke="#725A9D" strokeWidth="3.5" strokeLinecap="round" />
        <path className="vayda-ear-light" d="M55 126h8m102 0h8" stroke="#20B889" strokeWidth="4" strokeLinecap="round" />
        <circle className="vayda-cheek" cx="78" cy="139" r="6" fill="#E45C65" opacity=".18" />
        <circle className="vayda-cheek" cx="143" cy="139" r="6" fill="#E45C65" opacity=".18" />
        <path d="M83 207h54" stroke="#E0D8FF" strokeOpacity=".55" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <div className="vayda-speaking-bars"><i /><i /><i /><i /><i /></div>
      <div className="vayda-thinking-dots"><i /><i /><i /></div>
    </div>
  );
}

export function Current() {
  const [assistantState, setAssistantState] = useState<VaydaState>("idle");
  const [activeView, setActiveView] = useState<MemberView>("Home");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [scenario, setScenario] = useState<MemberScenario>("Free member");
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [supportOpen, setSupportOpen] = useState(false);
  const [tradeModalOpen, setTradeModalOpen] = useState(false);
  const [demoTradeCount, setDemoTradeCount] = useState(3);
  const [preferences, setPreferences] = useState({ calendar: true, learning: false, product: true, signals: false });
  const [formNotice, setFormNotice] = useState("");
  const [message, setMessage] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [conversation, setConversation] = useState<ConversationMessage[]>([
    { role: "vayda" as const, text: "Hi, I’m Vayda. This is a scripted demo; no live AI is connected and nothing you type leaves this preview." },
  ]);
  const chatLogRef = useRef<HTMLDivElement>(null);
  const replyTimer = useRef<number | null>(null);
  const stateTimer = useRef<number | null>(null);

  useEffect(() => {
    if (chatLogRef.current) chatLogRef.current.scrollTop = chatLogRef.current.scrollHeight;
  }, [conversation, isTyping]);

  useEffect(() => () => {
    if (replyTimer.current !== null) window.clearTimeout(replyTimer.current);
    if (stateTimer.current !== null) window.clearTimeout(stateTimer.current);
  }, []);

  const scriptedReply = (prompt: string) => {
    if (/progress|lesson|learn|academy/i.test(prompt)) {
      return "This preview has no real lesson-progress data, so it won’t mark lessons complete. Learning progress can appear when actual tracking is available.";
    }
    if (/pro|access|entitlement/i.test(prompt)) {
      return "PRO Signals access is separate and is not assigned in this sample. Registering or opening Telegram does not grant PRO access.";
    }
    if (/signal|telegram|bot/i.test(prompt)) {
      return "The button opens the verified PRO Signals assistant. Opening it does not grant access to PRO content.";
    }
    return "This is a visual preview with scripted replies. No live AI service is connected, and your message stays in this page.";
  };

  const sendPrompt = (prompt: string) => {
    const trimmed = prompt.trim();
    if (!trimmed || isTyping) return;
    if (replyTimer.current !== null) window.clearTimeout(replyTimer.current);
    if (stateTimer.current !== null) window.clearTimeout(stateTimer.current);
    setConversation((current) => [...current, { role: "member", text: trimmed }]);
    setMessage("");
    setIsTyping(true);
    setAssistantState("thinking");
    replyTimer.current = window.setTimeout(() => {
      setConversation((current) => [...current, { role: "vayda", text: scriptedReply(trimmed) }]);
      setIsTyping(false);
      setAssistantState("speaking");
      stateTimer.current = window.setTimeout(() => setAssistantState("idle"), 1200);
    }, 850);
  };

  const submitPreview = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    sendPrompt(message);
  };

  const navigate = (view: MemberView) => {
    setActiveView(view);
    setMobileNavOpen(false);
    setNotificationsOpen(false);
    window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  };

  const addDemoTrade = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setDemoTradeCount((count) => count + 1);
    setTradeModalOpen(false);
    setFormNotice("Demo trade added to this page only. Nothing was saved or sent.");
    window.setTimeout(() => setFormNotice(""), 3000);
  };

  return (
    <div className="smh-member-group">
      <div className="member-prototype-banner">
        <CircleHelp size={14} />
        <span>VISUAL PROTOTYPE · SAMPLE MEMBER DATA · VAYDA IS NOT CONNECTED TO AI</span>
      </div>
      <div className="member-app">
        <aside className="member-sidebar">
          <button className="member-brand" type="button" onClick={() => navigate("Home")} aria-label="Smart Money Hub member home">
            <span className="member-brand-mark"><Sparkles size={18} /></span>
            <span><strong>SMART MONEY HUB</strong><small>Learn. Analyse. Track. Improve.</small></span>
          </button>
          <button
            className="member-mobile-menu"
            type="button"
            aria-label={mobileNavOpen ? "Close member navigation" : "Open member navigation"}
            aria-controls="member-navigation"
            aria-expanded={mobileNavOpen}
            onClick={() => setMobileNavOpen((open) => !open)}
            data-testid="button-mobile-member-navigation"
          >
            {mobileNavOpen ? <X size={17} /> : <Menu size={17} />}
          </button>
          <div className="member-nav-label">MEMBER HOME</div>
          <nav id="member-navigation" className={`member-nav ${mobileNavOpen ? "is-mobile-open" : ""}`} aria-label="Member dashboard navigation">
            {memberNavigation.map(({ label, icon: Icon }) => (
              <button
                className={`member-nav-item ${activeView === label ? "is-active" : ""}`}
                type="button"
                key={label}
                onClick={() => navigate(label)}
                aria-current={activeView === label ? "page" : undefined}
                data-testid={`nav-${label.toLowerCase().replaceAll(" ", "-")}`}
              >
                <Icon size={17} /><span>{label}</span>
                {label === "PRO Signals" && scenario !== "PRO preview" && <LockKeyhole size={13} />}
              </button>
            ))}
          </nav>
          <div className="member-sidebar-rule" />
          <div className="member-sidebar-status">
              <div className="member-sidebar-status-icon"><ShieldCheck size={17} /></div>
              <span><strong>{scenario} preview</strong><small>Sample account data</small></span>
              <CheckCircle2 className="member-sidebar-check" size={15} />
          </div>
          <div className="member-sidebar-bottom">
            <button className="member-nav-item" type="button" onClick={() => navigate("Account Settings")} data-testid="button-prototype-settings"><Settings2 size={17} /><span>Account settings</span></button>
            <button className="member-nav-item" type="button" onClick={() => setScenario("Free member")} data-testid="button-prototype-signout"><LogOut size={17} /><span>Reset demo to Free</span></button>
            <div className="member-profile">
              <span className="member-profile-avatar">AM</span>
              <span><strong>Alex Morgan</strong><small>Member · prototype</small></span>
              <button type="button" aria-label="Profile options" onClick={() => navigate("Account Settings")} data-testid="button-profile-options">···</button>
            </div>
          </div>
        </aside>

        <main className="member-main" id="dashboard" data-testid="member-dashboard">
          <header className="member-topbar">
            <div className="member-breadcrumb"><span>Member space</span><ChevronRight size={13} /><strong>{activeView}</strong></div>
            <div className="member-topbar-actions">
              <span className="member-prototype-mini">PREVIEW</span>
              <span className={`member-tier-badge ${scenario === "PRO preview" ? "is-pro" : ""}`}>{scenario === "PRO preview" ? "PRO · PREVIEW" : "FREE MEMBER"}</span>
              <label className="member-scenario-select">SCENARIO
                <select aria-label="Member preview scenario" value={scenario} onChange={(event) => setScenario(event.currentTarget.value as MemberScenario)}>
                  <option>Free member</option><option>PRO preview</option>
                </select>
              </label>
              <button className="member-icon-button" type="button" aria-label="Notifications" aria-expanded={notificationsOpen} onClick={() => setNotificationsOpen(!notificationsOpen)}><Bell size={17} /><i className="member-notification-dot" /></button>
              <button className="member-icon-button" type="button" aria-label="Account settings" onClick={() => navigate("Account Settings")}><Settings2 size={17} /></button>
            </div>
            {notificationsOpen && <section className="member-notifications" aria-label="Sample notifications">
              <div className="member-notifications-head"><strong>Notifications</strong><span className="member-prototype-mini">SAMPLE</span><button type="button" aria-label="Close notifications" onClick={() => setNotificationsOpen(false)}><X size={14} /></button></div>
              <article><span className="member-notification-type">CALENDAR · SAMPLE</span><p>Two illustrative high-impact USD events appear in your upcoming calendar.</p><button type="button" onClick={() => navigate("Economic Calendar")}>Open calendar <ArrowRight size={12} /></button></article>
              <article><span className="member-notification-type">LEARNING · DEMO</span><p>Your sample module “Market Structure Foundations” is ready to continue.</p><button type="button" onClick={() => navigate("Education")}>Continue learning <ArrowRight size={12} /></button></article>
            </section>}
          </header>

          <div className="member-content">
            {activeView === "Home" ? <>
            <section className="member-welcome" aria-labelledby="member-welcome-title">
              <div className="member-welcome-copy">
                <div className="member-eyebrow"><span className="member-eyebrow-dot" /> YOUR LEARNING SPACE</div>
                <h1 id="member-welcome-title">Welcome back,<br /><span>Alex.</span></h1>
                <p>Everything a disciplined trader needs, in one place.</p>
                <div className="member-welcome-tagline">Learn. Analyse. Track. Improve.</div>
                <div className="member-welcome-pills">
                  <span className="member-status-pill"><ShieldCheck size={14} /> Member preview</span>
                  <span className={`member-status-pill member-status-pill-muted ${scenario === "PRO preview" ? "is-pro" : ""}`}><span className="member-status-dot" /> {scenario === "PRO preview" ? "PRO illustrative preview" : "PRO access restricted"}</span>
                </div>
              </div>
              <div className="member-welcome-visual">
                <div className="member-welcome-visual-grid" />
                <div className="member-welcome-tag"><span className="member-live-dot" /> VAYDA · YOUR AI COACH</div>
                <div className="member-welcome-portrait"><VaydaPortrait state={assistantState} /></div>
                <div className="member-welcome-speech">
                  <span className="member-speech-spark"><Sparkles size={13} /></span>
                  <span><strong>Hi, Alex.</strong><small>Let’s make your next study session count.</small></span>
                </div>
              </div>
            </section>

            <section className="member-section" aria-labelledby="member-tools-heading">
              <div className="member-section-heading">
                <div><div className="member-section-kicker">A GOOD PLACE TO START</div><h2 id="member-tools-heading">Your learning tools</h2></div>
                <span className="member-section-caption">Choose a path for today</span>
              </div>
              <div className="member-tools-grid">
                <button className="member-tool-card member-tool-academy" type="button" onClick={() => navigate("AI Coach")} data-testid="card-trading-academy">
                  <span className="member-tool-icon"><MessageCircle size={20} /></span><span className="member-tool-meta">IMPROVE</span><strong>AI Coach · Vayda</strong><span className="member-tool-description">Explore concepts with a scripted demo companion.</span><span className="member-tool-link">Ask Vayda <ArrowRight size={14} /></span>
                </button>
                <button className="member-tool-card member-tool-video" type="button" onClick={() => navigate("Economic Calendar")} data-testid="card-video-lessons">
                  <span className="member-tool-icon"><CalendarDays size={19} /></span><span className="member-tool-meta">ANALYSE</span><strong>Economic Calendar</strong><span className="member-tool-description">Upcoming sample events and high-impact USD context.</span><span className="member-tool-link">Open calendar <ArrowRight size={14} /></span>
                </button>
                <button className="member-tool-card member-tool-analysis" type="button" onClick={() => navigate("Trading Journal")} data-testid="card-market-analysis">
                  <span className="member-tool-icon"><FileText size={19} /></span><span className="member-tool-meta">TRACK</span><strong>Trading Journal</strong><span className="member-tool-description">Capture your plan, decision, and lessons learned.</span><span className="member-tool-link">Open journal <ArrowRight size={14} /></span>
                </button>
              </div>
            </section>

            <section className="member-lower-grid" aria-label="Membership and learning overview">
              <article className="member-panel member-progress-panel" data-testid="card-learning-progress">
                <div className="member-panel-head">
                  <div><div className="member-section-kicker">YOUR JOURNEY</div><h2>Learning progress</h2></div>
                  <span className="member-panel-icon"><Clock3 size={17} /></span>
                </div>
                <div className="member-progress-sample">
                  <div className="member-progress-line"><span><strong>Market Structure Foundations</strong><small>Current sample module · Lesson 4 of 10</small></span><b>40%</b></div>
                  <div className="member-progress-track"><i /></div>
                  <div className="member-progress-line member-progress-caption"><span>4 lessons completed · demo progress only</span><span>Recent: BOS and CHoCH</span></div>
                  <button className="member-inline-action" type="button" onClick={() => navigate("Education")}>Continue learning <ArrowRight size={13} /></button>
                </div>
                <div className="member-progress-foot"><span>Sample progress · not saved</span><span>NO CONFIRMATION, NO ENTRY.</span></div>
              </article>

              <article className="member-panel member-pro-panel" data-testid="card-pro-access">
                <div className="member-panel-head">
                  <div><div className="member-section-kicker">PREMIUM PREVIEW</div><h2>PRO membership</h2></div>
                  <span className="member-panel-icon member-panel-icon-purple"><WalletCards size={17} /></span>
                </div>
                <div className="member-pro-status"><span className="member-pro-lock"><ShieldCheck size={18} /></span><span><strong>{scenario === "PRO preview" ? "Illustrative PRO preview" : "PRO access restricted"}</strong><small>No verified entitlement in this demo.</small></span></div>
                <p className="member-pro-copy">Full education library · advanced market breakdowns · PRO Signals · signal history and updates · priority support where available.</p>
                <span className="member-pro-note">Pricing to be announced</span>
                <button className="member-inline-action" type="button" onClick={() => navigate("PRO Signals")}>View PRO access state <ArrowRight size={13} /></button>
              </article>
            </section>

            <section className="member-connect-grid" aria-label="Vayda assistant and Signal Bot">
              <article className="member-ask-panel" data-testid="panel-ask-vayda">
                <div className="member-ask-head">
                  <div className="member-ask-title">
                    <span className="member-ask-avatar"><VaydaPortrait state={assistantState} /></span>
                    <span><span className="member-section-kicker">YOUR STUDY COMPANION</span><strong>Ask Vayda</strong><small>Concepts · Context · Process</small></span>
                  </div>
                  <span className={`member-coach-state state-label-${assistantState}`}><i />{assistantState}</span>
                </div>
                <div className="member-state-heading"><span>PREVIEW ANIMATION</span><span>Choose a state</span></div>
                <div className="member-state-controls" role="group" aria-label="Preview Vayda animation states">
                  {states.map((item) => <button key={item.id} className={assistantState === item.id ? "is-selected" : ""} type="button" onClick={() => setAssistantState(item.id)} aria-pressed={assistantState === item.id} data-testid={`button-vayda-state-${item.id}`}>{item.label}</button>)}
                </div>
                <div className="member-chat-log" ref={chatLogRef} role="log" aria-live="polite" aria-label="Scripted Vayda preview conversation">
                  {conversation.map((entry, index) => (
                    <div className={`member-chat-message ${entry.role === "member" ? "is-member" : "is-vayda"}`} key={`${entry.role}-${index}`}>
                      {entry.role === "vayda" && <span className="member-chat-mark"><Sparkles size={12} /></span>}
                      <p>{entry.text}</p>
                    </div>
                  ))}
                  {isTyping && <div className="member-chat-message is-vayda member-typing" role="status" aria-label="Vayda is typing"><span className="member-chat-mark"><Sparkles size={12} /></span><p><i /><i /><i /></p></div>}
                </div>
                <div className="member-suggested-prompts" aria-label="Suggested questions">
                  {memberSuggestedQuestions.map((question) => <button key={question} type="button" onClick={() => sendPrompt(question)} disabled={isTyping}>{question}</button>)}
                </div>
                <form className="member-ask-form" onSubmit={submitPreview}>
                  <label className="visually-hidden" htmlFor="ask-vayda-input">Type a question for Vayda</label>
                  <input id="ask-vayda-input" value={message} onChange={(event) => setMessage(event.currentTarget.value)} placeholder="Ask about this preview…" maxLength={500} data-testid="input-ask-vayda" />
                  <button type="submit" aria-label="Send preview question" disabled={!message.trim() || isTyping} data-testid="button-send-preview-question"><Send size={16} /></button>
                </form>
                <div className="member-ask-disclaimer"><ShieldCheck size={13} /><span>Scripted demo · No live AI · Nothing leaves this preview</span></div>
              </article>

              <article className="member-signal-panel" data-testid="card-signal-bot">
                <div className="member-signal-glow" />
                <span className="member-signal-icon"><Radio size={19} /></span>
                <div className="member-section-kicker">SIGNAL BOT · NOT CONNECTED</div>
                <h2>PRO Signals Bot</h2>
                <div className="member-bot-status-list"><span><i /> Bot connection <strong>Not connected</strong></span><span><i /> Telegram status <strong>Not connected</strong></span><span><i /> Latest signal <strong>Unavailable</strong></span></div>
                <p>No bot status or signal activity is available in this visual preview. The button opens the verified PRO Signals destination only.</p>
                <a className="member-signal-button" href="https://t.me/SMHProSignalsassistantbot" target="_blank" rel="noreferrer" data-testid="button-open-pro-signals-bot">Open Signal Bot <ArrowUpRight size={15} /></a>
                <button className="member-inline-action" type="button" onClick={() => navigate("Account Settings")}>Notification preferences <Settings2 size={13} /></button>
                <span className="member-signal-foot"><ShieldCheck size={13} /> Linking or opening the bot does not grant PRO access.</span>
              </article>
            </section>

            <section className="member-dashboard-detail-grid" aria-label="Member activity and upcoming items">
              <article className="member-panel">
                <div className="member-panel-head"><div><div className="member-section-kicker">UPCOMING · SAMPLE ONLY</div><h2>Economic events</h2></div><span className="member-panel-icon"><CalendarDays size={17} /></span></div>
                <div className="member-detail-list">{memberSampleEvents.slice(0, 2).map((event) => <div className="member-detail-row" key={event.title}><span className="member-detail-time">{event.time}</span><span><strong>{event.title}</strong><small>{event.currency} · {event.impact} impact · {event.status} · illustrative sample</small></span></div>)}</div>
                <button className="member-inline-action" type="button" onClick={() => navigate("Economic Calendar")}>Open Economic Calendar <ArrowRight size={13} /></button>
              </article>
              <article className="member-panel">
                <div className="member-panel-head"><div><div className="member-section-kicker">RECENT ACTIVITY · DEMO</div><h2>Trade journal</h2></div><span className="member-panel-icon"><FileText size={17} /></span></div>
                <div className="member-detail-list"><div className="member-detail-row"><span className="member-detail-time">Today</span><span><strong>XAUUSD · Buy · Win</strong><small>Waited for confirmation · sample entry</small></span></div><div className="member-detail-row"><span className="member-detail-time">Yesterday</span><span><strong>EURUSD · Sell · Loss</strong><small>Review: early entry · sample entry</small></span></div></div>
                <button className="member-inline-action" type="button" onClick={() => navigate("Trading Journal")}>Open Trading Journal <ArrowRight size={13} /></button>
              </article>
              <article className="member-panel">
                <div className="member-panel-head"><div><div className="member-section-kicker">LEARNING ACTIVITY · DEMO</div><h2>What’s next</h2></div><span className="member-panel-icon"><GraduationCap size={17} /></span></div>
                <div className="member-detail-list"><div className="member-detail-row"><span className="member-detail-time">NEWS</span><span><strong>Smart Money Hub announcement</strong><small>Sample announcement preview · no delivery</small></span></div><div className="member-detail-row"><span className="member-detail-time">CLASS</span><span><strong>Structure study session</strong><small>Upcoming class placeholder · time not scheduled</small></span></div><div className="member-detail-row"><span className="member-detail-time">GUIDE</span><span><strong>Confirmation checklist</strong><small>Sample education material · not downloaded</small></span></div></div>
                <button className="member-inline-action" type="button" onClick={() => navigate("Education")}>Browse education <ArrowRight size={13} /></button>
              </article>
            </section>

            <section className="member-support-strip">
              <div><div className="member-section-kicker">SMART MONEY HUB SUPPORT</div><strong>Need help finding your next step?</strong><small>Open a local support preview. Nothing is delivered.</small></div>
              <button className="member-support-action" type="button" onClick={() => setSupportOpen(true)}>Support shortcut <CircleHelp size={14} /></button>
            </section>

            <footer className="member-footer">
              <span>SMART MONEY HUB <i /> LEARN. ANALYSE. TRACK. IMPROVE.</span>
              <span>Trading involves risk. Education is not financial advice.</span>
            </footer>
            </> : <MemberFeaturePanel
              activeView={activeView}
              scenario={scenario}
              preferences={preferences}
              setPreferences={setPreferences}
              navigate={navigate}
              setAssistantState={setAssistantState}
              sendPrompt={sendPrompt}
              demoTradeCount={demoTradeCount}
              openTradeForm={() => setTradeModalOpen(true)}
              onDemoNotice={(text) => { setFormNotice(text); window.setTimeout(() => setFormNotice(""), 3000); }}
              assistantState={assistantState}
              conversation={conversation}
              isTyping={isTyping}
              message={message}
              setMessage={setMessage}
              submitPreview={submitPreview}
              chatLogRef={chatLogRef}
            />}
            {formNotice && <div className="member-form-notice" role="status">{formNotice}</div>}
          </div>
        </main>
      </div>
      {tradeModalOpen && <div className="member-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setTradeModalOpen(false); }}>
        <section className="member-modal" role="dialog" aria-modal="true" aria-labelledby="demo-trade-title">
          <div className="member-modal-head"><div><div className="member-section-kicker">LOCAL DEMO ONLY</div><h2 id="demo-trade-title">Record a sample trade</h2><p>Fields are illustrative; nothing is persisted or submitted.</p></div><button type="button" aria-label="Close trade modal" onClick={() => setTradeModalOpen(false)}><X size={17} /></button></div>
          <form onSubmit={addDemoTrade} className="member-modal-form">
            <label>Instrument<input required defaultValue="XAUUSD" /></label><label>Direction<select defaultValue="Buy"><option>Buy</option><option>Sell</option></select></label>
            <label>Entry<input required type="number" step="any" defaultValue="2900" /></label><label>Stop loss<input required type="number" step="any" defaultValue="2890" /></label>
            <label>Take profit<input required type="number" step="any" defaultValue="2920" /></label><label>Risk %<input required type="number" step="0.01" defaultValue="0.5" /></label>
            <label>Planned R:R<input value="2:1 · illustrative" readOnly /></label><label>Outcome<select defaultValue="Win"><option>Win</option><option>Loss</option><option>Breakeven</option></select></label>
            <label className="member-modal-wide">Emotional state<input placeholder="e.g. patient, focused" /></label>
            <label className="member-modal-wide">Notes and lessons<textarea placeholder="What did you observe? What will you take forward?" /></label>
            <span className="member-modal-attachment">Image attachment placeholder · no upload</span>
            <div className="member-modal-actions"><button type="button" onClick={() => setTradeModalOpen(false)}>Cancel</button><button type="submit">Add local demo entry <Plus size={14} /></button></div>
          </form>
        </section>
      </div>}
      {supportOpen && <div className="member-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSupportOpen(false); }}>
        <section className="member-modal member-support-modal" role="dialog" aria-modal="true" aria-labelledby="demo-support-title">
          <div className="member-modal-head"><div><div className="member-section-kicker">SUPPORT PREVIEW</div><h2 id="demo-support-title">Member support</h2><p>This is a local interface example. No message is sent or ticket created.</p></div><button type="button" aria-label="Close support preview" onClick={() => setSupportOpen(false)}><X size={17} /></button></div>
          <p>For this prototype, the best next step is to review your member learning tools or account preferences.</p>
          <div className="member-modal-actions"><button type="button" onClick={() => { setSupportOpen(false); navigate("Education"); }}>Browse education <ArrowRight size={13} /></button><button type="button" onClick={() => { setSupportOpen(false); navigate("Account Settings"); }}>Account settings <Settings2 size={13} /></button></div>
        </section>
      </div>}
    </div>
  );
}
