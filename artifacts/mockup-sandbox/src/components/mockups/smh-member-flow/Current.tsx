import { useState, type FormEvent, type ReactNode } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  MessageCircle,
  Play,
  Radio,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  Video,
  WalletCards,
} from "lucide-react";
import "./_group.css";

type VaydaState = "idle" | "blinking" | "breathing" | "listening" | "thinking" | "speaking";

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
            <stop stopColor="#A88BFF" />
            <stop offset="1" stopColor="#536BFF" />
          </linearGradient>
          <linearGradient id="vayda-skin" x1="78" y1="76" x2="155" y2="166" gradientUnits="userSpaceOnUse">
            <stop stopColor="#F3D7E8" />
            <stop offset="1" stopColor="#B9B5FF" />
          </linearGradient>
          <linearGradient id="vayda-jacket" x1="53" y1="177" x2="172" y2="245" gradientUnits="userSpaceOnUse">
            <stop stopColor="#7D69E9" />
            <stop offset="1" stopColor="#26C6D7" />
          </linearGradient>
        </defs>
        <path className="vayda-shoulders" d="M28 239c7-38 34-61 82-61s75 23 82 61" fill="url(#vayda-jacket)" />
        <path d="M91 167h38v28c-5 12-33 12-38 0v-28Z" fill="#C7B5E9" />
        <path className="vayda-neckline" d="m79 189 31 28 31-28" stroke="#E8DEFF" strokeWidth="4" strokeLinecap="round" />
        <path d="M60 97c0-37 23-63 53-63 32 0 55 24 55 63v26c0 34-24 60-55 60-31 0-53-26-53-60V97Z" fill="url(#vayda-skin)" />
        <path className="vayda-hair-shape" d="M53 107c-9-42 7-78 36-91 35-16 84 1 91 42 4 20-2 40-6 49-7-22-17-39-33-49-22 19-50 27-85 25l-3 24Z" fill="url(#vayda-hair)" />
        <path d="M56 113c-8-5-13 1-10 14 2 9 7 14 14 14m101-28c8-5 13 1 10 14-2 9-7 14-14 14" stroke="#C8BDF6" strokeWidth="4" strokeLinecap="round" />
        <path className="vayda-eye vayda-eye-left" d="M78 118c5-5 12-5 17 0" stroke="#1E2755" strokeWidth="4" strokeLinecap="round" />
        <path className="vayda-eye vayda-eye-right" d="M126 118c5-5 12-5 17 0" stroke="#1E2755" strokeWidth="4" strokeLinecap="round" />
        <path d="M109 123v15" stroke="#8A71B8" strokeWidth="3" strokeLinecap="round" />
        <path className="vayda-mouth" d="M95 150c8 9 21 9 29 0" stroke="#725A9D" strokeWidth="3.5" strokeLinecap="round" />
        <path className="vayda-ear-light" d="M55 126h8m102 0h8" stroke="#62E1E8" strokeWidth="4" strokeLinecap="round" />
        <circle className="vayda-cheek" cx="78" cy="139" r="6" fill="#D78FC4" opacity=".28" />
        <circle className="vayda-cheek" cx="143" cy="139" r="6" fill="#D78FC4" opacity=".28" />
        <path d="M83 207h54" stroke="#E0D8FF" strokeOpacity=".55" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <div className="vayda-speaking-bars"><i /><i /><i /><i /><i /></div>
      <div className="vayda-thinking-dots"><i /><i /><i /></div>
    </div>
  );
}

function IconButton({ label, children }: { label: string; children: ReactNode }) {
  return <button className="member-icon-button" type="button" aria-label={label} title={label} data-testid={`button-${label.toLowerCase().replaceAll(" ", "-")}`}>{children}</button>;
}

export function Current() {
  const [assistantState, setAssistantState] = useState<VaydaState>("idle");
  const [message, setMessage] = useState("");
  const [previewNotice, setPreviewNotice] = useState("");

  const submitPreview = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!message.trim()) return;
    setPreviewNotice("Visual prototype only — no message was sent and Vayda is not connected to an AI service.");
    setMessage("");
  };

  return (
    <div className="smh-member-group">
      <div className="member-prototype-banner">
        <CircleHelp size={14} />
        <span>VISUAL PROTOTYPE · VAYDA IS NOT CONNECTED TO AI</span>
      </div>
      <div className="member-app">
        <aside className="member-sidebar">
          <a className="member-brand" href="#" onClick={(event) => event.preventDefault()} aria-label="VAYDA Smart Money Hub">
            <span className="member-brand-mark"><Sparkles size={18} /></span>
            <span><strong>VAYDA</strong><small>SMART MONEY HUB</small></span>
          </a>
          <div className="member-nav-label">YOUR SPACE</div>
          <nav className="member-nav" aria-label="Member dashboard navigation">
            <a className="member-nav-item is-active" href="#dashboard" onClick={(event) => event.preventDefault()} data-testid="nav-member-dashboard"><LayoutDashboard size={17} /><span>Overview</span></a>
            <a className="member-nav-item" href="#academy" onClick={(event) => event.preventDefault()} data-testid="nav-trading-academy"><GraduationCap size={17} /><span>Trading Academy</span><ChevronRight size={14} /></a>
            <a className="member-nav-item" href="#videos" onClick={(event) => event.preventDefault()} data-testid="nav-video-lessons"><Video size={17} /><span>Video Lessons</span><ChevronRight size={14} /></a>
            <a className="member-nav-item" href="#analysis" onClick={(event) => event.preventDefault()} data-testid="nav-market-analysis"><Activity size={17} /><span>Market Analysis</span><ChevronRight size={14} /></a>
          </nav>
          <div className="member-sidebar-rule" />
          <div className="member-sidebar-status">
            <div className="member-sidebar-status-icon"><ShieldCheck size={17} /></div>
            <span><strong>Member account</strong><small>Verified access</small></span>
            <CheckCircle2 className="member-sidebar-check" size={15} />
          </div>
          <div className="member-sidebar-bottom">
            <button className="member-nav-item" type="button" data-testid="button-prototype-settings"><Settings2 size={17} /><span>Account settings</span></button>
            <button className="member-nav-item" type="button" data-testid="button-prototype-signout"><LogOut size={17} /><span>Sign out</span></button>
            <div className="member-profile">
              <span className="member-profile-avatar">AM</span>
              <span><strong>Alex Morgan</strong><small>Member · prototype</small></span>
              <button type="button" aria-label="Profile options" data-testid="button-profile-options">···</button>
            </div>
          </div>
        </aside>

        <main className="member-main" id="dashboard" data-testid="member-dashboard">
          <header className="member-topbar">
            <div className="member-breadcrumb"><span>Member space</span><ChevronRight size={13} /><strong>Overview</strong></div>
            <div className="member-topbar-actions">
              <span className="member-prototype-mini">PREVIEW</span>
              <IconButton label="Account settings"><Settings2 size={17} /></IconButton>
              <IconButton label="Sign out"><LogOut size={17} /></IconButton>
            </div>
          </header>

          <div className="member-content">
            <section className="member-welcome" aria-labelledby="member-welcome-title">
              <div className="member-welcome-copy">
                <div className="member-eyebrow"><span className="member-eyebrow-dot" /> YOUR LEARNING SPACE</div>
                <h1 id="member-welcome-title">Welcome back,<br /><span>Alex.</span></h1>
                <p>A clear place to learn, review, and build your trading process—one decision at a time.</p>
                <div className="member-welcome-pills">
                  <span className="member-status-pill"><ShieldCheck size={14} /> Verified member</span>
                  <span className="member-status-pill member-status-pill-muted"><span className="member-status-dot" /> PRO access not assigned</span>
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
                <a className="member-tool-card member-tool-academy" href="#academy" onClick={(event) => event.preventDefault()} data-testid="card-trading-academy">
                  <span className="member-tool-icon"><BookOpen size={20} /></span><span className="member-tool-meta">LEARN</span><strong>Trading Academy</strong><span className="member-tool-description">Build your foundation in structure and confirmation.</span><span className="member-tool-link">Explore learning <ArrowRight size={14} /></span>
                </a>
                <a className="member-tool-card member-tool-video" href="#videos" onClick={(event) => event.preventDefault()} data-testid="card-video-lessons">
                  <span className="member-tool-icon"><Play size={19} /></span><span className="member-tool-meta">WATCH</span><strong>Video Lessons</strong><span className="member-tool-description">Revisit concepts with focused, practical lessons.</span><span className="member-tool-link">Browse lessons <ArrowRight size={14} /></span>
                </a>
                <a className="member-tool-card member-tool-analysis" href="#analysis" onClick={(event) => event.preventDefault()} data-testid="card-market-analysis">
                  <span className="member-tool-icon"><Activity size={19} /></span><span className="member-tool-meta">OBSERVE</span><strong>Market Analysis</strong><span className="member-tool-description">Study context, structure, and confirmation.</span><span className="member-tool-link">View analysis <ArrowRight size={14} /></span>
                </a>
              </div>
            </section>

            <section className="member-lower-grid" aria-label="Membership and learning overview">
              <article className="member-panel member-progress-panel" data-testid="card-learning-progress">
                <div className="member-panel-head">
                  <div><div className="member-section-kicker">YOUR JOURNEY</div><h2>Learning progress</h2></div>
                  <span className="member-panel-icon"><Clock3 size={17} /></span>
                </div>
                <div className="member-progress-empty">
                  <span className="member-progress-orb"><GraduationCap size={21} /></span>
                  <div><strong>Progress tracking isn’t connected</strong><p>No lessons are marked complete in this preview. Your progress will appear here when real tracking is available.</p></div>
                </div>
                <div className="member-progress-foot"><span>Learn at your own pace</span><span>NO CONFIRMATION, NO ENTRY.</span></div>
              </article>

              <article className="member-panel member-pro-panel" data-testid="card-pro-access">
                <div className="member-panel-head">
                  <div><div className="member-section-kicker">SEPARATE APPROVAL</div><h2>PRO Signals access</h2></div>
                  <span className="member-panel-icon member-panel-icon-purple"><WalletCards size={17} /></span>
                </div>
                <div className="member-pro-status"><span className="member-pro-lock"><ShieldCheck size={18} /></span><span><strong>Not assigned</strong><small>Access is reviewed separately.</small></span></div>
                <p className="member-pro-copy">Creating a member account or linking Telegram does not activate PRO Signals.</p>
                <span className="member-pro-note">Account status · Member</span>
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
                <div className="member-coach-message">
                  <span className="member-coach-message-mark"><Sparkles size={13} /></span>
                  <p>What trading concept would you like to understand more clearly?</p>
                </div>
                <div className="member-state-heading"><span>PREVIEW ANIMATION</span><span>Choose a state</span></div>
                <div className="member-state-controls" role="group" aria-label="Preview Vayda animation states">
                  {states.map((item) => <button key={item.id} className={assistantState === item.id ? "is-selected" : ""} type="button" onClick={() => setAssistantState(item.id)} aria-pressed={assistantState === item.id} data-testid={`button-vayda-state-${item.id}`}>{item.label}</button>)}
                </div>
                <form className="member-ask-form" onSubmit={submitPreview}>
                  <label className="visually-hidden" htmlFor="ask-vayda-input">Type a question for Vayda</label>
                  <input id="ask-vayda-input" value={message} onChange={(event) => setMessage(event.currentTarget.value)} placeholder="Ask about a trading concept…" maxLength={500} data-testid="input-ask-vayda" />
                  <button type="submit" aria-label="Send preview question" disabled={!message.trim()} data-testid="button-send-preview-question"><Send size={16} /></button>
                </form>
                <div className="member-ask-disclaimer"><ShieldCheck size={13} /><span>Education only · No trade signals · AI not connected in this prototype</span></div>
                {previewNotice && <div className="member-preview-notice" role="status">{previewNotice}</div>}
              </article>

              <article className="member-signal-panel" data-testid="card-signal-bot">
                <div className="member-signal-glow" />
                <span className="member-signal-icon"><Radio size={19} /></span>
                <div className="member-section-kicker">TELEGRAM DESTINATION</div>
                <h2>PRO Signals Bot</h2>
                <p>Open the verified PRO Signals assistant in Telegram. Access to PRO content is checked separately.</p>
                <a className="member-signal-button" href="https://t.me/SMHProSignalsassistantbot" target="_blank" rel="noreferrer" data-testid="button-open-pro-signals-bot">Open Signal Bot <ArrowUpRight size={15} /></a>
                <span className="member-signal-foot"><ShieldCheck size={13} /> Linking or opening the bot does not grant PRO access.</span>
              </article>
            </section>

            <footer className="member-footer">
              <span>VAYDA SMART MONEY HUB <i /> PROCESS OVER PREDICTION</span>
              <span>Trading involves risk. Education is not financial advice.</span>
            </footer>
          </div>
        </main>
      </div>
    </div>
  );
}
