import { useState, type FormEvent } from "react";
import {
  ArrowLeft,
  CalendarDays,
  FileText,
  MessageCircle,
  Send,
  ShieldCheck,
  RotateCcw,
  Info,
  LockKeyhole,
} from "lucide-react";
import "./_group.css";

type ChatLine = { role: "user" | "assistant"; content: string };

const exampleConversation: ChatLine[] = [
  {
    role: "user",
    content: "I keep moving my stop after entering. What should I reflect on before I do that?",
  },
  {
    role: "assistant",
    content:
      "A useful place to start is the reason behind the change. Was your original invalidation point based on a clear idea, or did discomfort with the risk take over?\n\nYou could review what you planned before entry, what changed in the market, and whether the adjustment fits your written risk rules. I can help you examine the decision process, but I can’t tell you where to place a stop or whether to stay in a trade.",
  },
];

function CoachMark() {
  return (
    <span className="mx-coach-bot is-compact" aria-hidden="true">
      <span className="mx-coach-bot-halo" />
      <span className="mx-coach-bot-orbit"><i /></span>
      <svg className="mx-coach-bot-art" viewBox="0 0 128 128" fill="none">
        <path className="mx-coach-bot-antenna" d="M64 19v12" />
        <circle className="mx-coach-bot-signal" cx="64" cy="15" r="4" />
        <path className="mx-coach-bot-ear" d="M25 54h-9v22h9m78-22h9v22h-9" />
        <rect className="mx-coach-bot-shell" x="25" y="31" width="78" height="67" rx="22" />
        <rect className="mx-coach-bot-face" x="34" y="41" width="60" height="45" rx="15" />
        <circle className="mx-coach-bot-eye" cx="50" cy="60" r="4" />
        <circle className="mx-coach-bot-eye" cx="78" cy="60" r="4" />
        <path className="mx-coach-bot-smile" d="M53 72q11 10 22 0" />
        <path className="mx-coach-bot-neck" d="M64 98v7" />
        <rect className="mx-coach-bot-base" x="43" y="103" width="42" height="12" rx="6" />
        <circle className="mx-coach-bot-light" cx="52" cy="109" r="2" />
        <circle className="mx-coach-bot-light" cx="64" cy="109" r="2" />
        <circle className="mx-coach-bot-light" cx="76" cy="109" r="2" />
      </svg>
    </span>
  );
}

export function ChatFocused() {
  const [history, setHistory] = useState<ChatLine[]>(exampleConversation);
  const [message, setMessage] = useState("");

  const send = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = message.trim();
    if (!text) return;
    setHistory((current) => [...current, { role: "user", content: text }]);
    setMessage("");
  };

  const clear = () => {
    setHistory([]);
    setMessage("");
  };

  return (
    <main className="smh-coach-chat chat-focused">
      <style>{`
        .chat-focused { min-height: 100dvh; }
        .chat-focused .mx-dashboard-shell { width: min(1080px, calc(100% - 56px)); }
        .chat-focused .mx-dashboard-header { min-height: 72px; }
        .chat-focused .mx-feature-nav { padding: 9px 0; }
        .chat-focused .mx-feature-heading { padding: 28px 0 18px; }
        .chat-focused .mx-feature-heading h1 { font-size: clamp(30px, 4vw, 42px); }
        .chat-focused .mx-feature-heading > p { max-width: 650px; }
        .chat-focused .mx-chat-workspace { border: 1px solid var(--mx-border); background: rgba(23,30,28,.92); box-shadow: 0 24px 70px rgba(0,0,0,.2); }
        .chat-focused .mx-conversation-head { min-height: 62px; display:flex; align-items:center; justify-content:space-between; gap:16px; padding: 12px 20px; border-bottom:1px solid rgba(226,211,170,.1); }
        .chat-focused .mx-conversation-title { display:flex; align-items:center; gap:11px; min-width:0; }
        .chat-focused .mx-conversation-title .mx-coach-bot { width:38px; flex:0 0 auto; }
        .chat-focused .mx-conversation-title strong { display:block; color:var(--mx-text); font:600 12px "Manrope",sans-serif; }
        .chat-focused .mx-conversation-title small { display:block; margin-top:3px; color:var(--mx-dim); font:8px "DM Mono",monospace; letter-spacing:.08em; }
        .chat-focused .mx-chat-workspace .mx-button { cursor:pointer; transition:background .16s ease, border-color .16s ease, opacity .16s ease; }
        .chat-focused .mx-chat-workspace .mx-button:hover:not(:disabled) { border-color:rgba(210,185,120,.4); background:rgba(210,185,120,.08); }
        .chat-focused .mx-chat-workspace .mx-button-gold:hover:not(:disabled) { background:var(--mx-gold-light); }
        .chat-focused .mx-chat-workspace .mx-button:disabled { opacity:.45; cursor:not-allowed; }
        .chat-focused .mx-chat-thread { min-height:340px; max-height:490px; padding:26px clamp(16px,6vw,72px); gap:18px; }
        .chat-focused .mx-chat-line { max-width:min(76%, 650px); padding:13px 16px; border-radius:3px 12px 12px 12px; }
        .chat-focused .mx-chat-user { border-radius:12px 3px 12px 12px; }
        .chat-focused .mx-chat-line p { font-size:12px; }
        .chat-focused .mx-chat-form { padding:16px 20px 13px; border-top:1px solid rgba(226,211,170,.1); }
        .chat-focused .mx-chat-input-wrap { align-items:flex-end; padding:6px; border:1px solid rgba(226,211,170,.17); background:#121816; }
        .chat-focused .mx-chat-input-wrap:focus-within { border-color:rgba(210,185,120,.54); }
        .chat-focused .mx-chat-input-wrap textarea { min-height:50px; max-height:150px; padding:9px; border:0; background:transparent; outline:0; resize:vertical; font-size:12px; }
        .chat-focused .mx-chat-input-wrap .mx-button { min-height:38px; padding-inline:15px; }
        .chat-focused .mx-chat-form > small { padding-left:6px; }
        .chat-focused .mx-chat-disclosures { display:grid; grid-template-columns:1.1fr 1fr; gap:10px; margin-top:12px; }
        .chat-focused .mx-disclosure { display:flex; gap:11px; align-items:flex-start; padding:13px 15px; border:1px solid var(--mx-border); background:rgba(23,30,28,.58); }
        .chat-focused .mx-disclosure.education { border-left:2px solid rgba(210,185,120,.68); }
        .chat-focused .mx-disclosure.privacy { border-left:2px solid rgba(138,179,154,.68); }
        .chat-focused .mx-disclosure svg { flex:0 0 auto; margin-top:2px; color:var(--mx-gold); }
        .chat-focused .mx-disclosure.privacy svg { color:var(--mx-green); }
        .chat-focused .mx-disclosure strong { display:block; margin-bottom:3px; color:var(--mx-text); font:600 10px "Manrope",sans-serif; }
        .chat-focused .mx-disclosure p { margin:0; color:var(--mx-muted); font-size:9px; line-height:1.65; }
        .chat-focused .mx-example-label { display:flex; align-items:center; gap:7px; align-self:center; color:var(--mx-dim); font:8px "DM Mono",monospace; letter-spacing:.06em; text-transform:uppercase; }
        .chat-focused .mx-example-label::before, .chat-focused .mx-example-label::after { content:""; width:34px; height:1px; background:rgba(226,211,170,.14); }
        .chat-focused .mx-empty-thread { display:grid; min-height:290px; place-content:center; justify-items:center; padding:24px; text-align:center; }
        .chat-focused .mx-empty-thread h2 { margin:9px 0 5px; color:var(--mx-text); font:600 16px "Manrope",sans-serif; }
        .chat-focused .mx-empty-thread p { max-width:340px; margin:0; color:var(--mx-muted); font-size:10px; }
        .chat-focused .mx-dashboard-footer { padding-top:16px; }
        @media (max-width:700px) {
          .chat-focused .mx-dashboard-shell { width:calc(100% - 30px); }
          .chat-focused .mx-dashboard-header { min-height:64px; }
          .chat-focused .mx-feature-nav { align-items:flex-start; flex-direction:column; gap:7px; }
          .chat-focused .mx-feature-nav-links { width:100%; overflow-x:auto; }
          .chat-focused .mx-feature-nav-link { flex:0 0 auto; padding:0 8px; font-size:10px; }
          .chat-focused .mx-feature-heading { padding:24px 0 15px; }
          .chat-focused .mx-conversation-head { padding:10px 13px; }
          .chat-focused .mx-chat-thread { min-height:300px; max-height:52dvh; padding:20px 12px; }
          .chat-focused .mx-chat-line { max-width:94%; }
          .chat-focused .mx-chat-form { padding:13px 12px 11px; }
          .chat-focused .mx-chat-input-wrap { flex-direction:row; align-items:flex-end; }
          .chat-focused .mx-chat-input-wrap .mx-button { align-self:flex-end; }
          .chat-focused .mx-chat-disclosures { grid-template-columns:1fr; }
          .chat-focused .mx-dashboard-footer { gap:7px; flex-direction:column; }
        }
        @media (max-width:390px) {
          .chat-focused .mx-feature-private { font-size:0; gap:0; }
          .chat-focused .mx-feature-private svg { width:17px; height:17px; }
          .chat-focused .mx-chat-input-wrap { flex-direction:column; align-items:stretch; }
          .chat-focused .mx-chat-input-wrap .mx-button { align-self:flex-end; }
        }
      `}</style>

      <div className="mx-dashboard-shell">
        <header className="mx-dashboard-header">
          <a className="mx-wordmark" href="#" aria-label="VAYDA Smart Money Hub">
            <img className="mx-wordmark-image" src="/__mockup/images/vayda-logo.png" alt="" />
            <span><strong>VAYDA</strong><small>SMART MONEY HUB</small></span>
          </a>
          <span className="mx-feature-private"><ShieldCheck size={14} /> PRIVATE LEARNING SPACE</span>
        </header>

        <nav className="mx-feature-nav" aria-label="Member learning tools">
          <a className="mx-feature-back" href="#"><ArrowLeft size={14} /> Workspace</a>
          <div className="mx-feature-nav-links">
            <a className="mx-feature-nav-link" href="#"><CalendarDays size={17} /><span>Economic calendar</span></a>
            <a className="mx-feature-nav-link" href="#"><FileText size={17} /><span>Trade journal</span></a>
            <a className="mx-feature-nav-link is-active" href="#"><MessageCircle size={17} /><span>AI Coach</span></a>
          </div>
        </nav>

        <section className="mx-feature-heading">
          <div className="mx-overline"><span className="mx-live-mark" /> STUDY / GUIDED REFLECTION</div>
          <h1>AI Coach</h1>
          <p>A private learning conversation for trading concepts and decision reflection. Not a source of trade instructions.</p>
        </section>

        <section className="mx-chat-workspace" aria-label="Educational coach conversation">
          <header className="mx-conversation-head">
            <div className="mx-conversation-title">
              <CoachMark />
              <div><strong>VAYDA Coach</strong><small>CONCEPTS · CONTEXT · PROCESS</small></div>
            </div>
            <button className="mx-button" type="button" onClick={clear} disabled={!history.length} aria-label="Clear temporary chat">
              <RotateCcw size={13} /> Clear chat
            </button>
          </header>

          <div className="mx-chat-thread" aria-live="polite">
            {history.length > 0 && <div className="mx-example-label">Illustrative exchange · not saved</div>}
            {history.map((line, index) => (
              <article className={`mx-chat-line mx-chat-${line.role}`} key={`${index}-${line.role}`}>
                <span className="mx-chat-role">{line.role === "user" ? "YOU" : "COACH"}</span>
                <p>{line.content}</p>
              </article>
            ))}
            {!history.length && (
              <div className="mx-empty-thread">
                <CoachMark />
                <h2>What would you like to understand?</h2>
                <p>Ask about a concept or reflect on a decision. Keep the details general.</p>
              </div>
            )}
          </div>

          <form className="mx-chat-form" onSubmit={send}>
            <label className="mx-field" htmlFor="focused-coach-question">Your question</label>
            <div className="mx-chat-input-wrap">
              <textarea
                id="focused-coach-question"
                rows={2}
                maxLength={1200}
                value={message}
                onChange={(event) => setMessage(event.currentTarget.value)}
                placeholder="Ask a focused learning question…"
              />
              <button className="mx-button mx-button-gold" type="submit" disabled={!message.trim()}>
                Send <Send size={14} />
              </button>
            </div>
            <small>{message.length}/1200 · Do not include personal account details.</small>
          </form>
        </section>

        <div className="mx-chat-disclosures" aria-label="Important Coach information">
          <section className="mx-disclosure education">
            <Info size={15} />
            <div><strong>Education, not financial advice</strong><p>The Coach cannot verify live prices, market conditions, or entry confirmations, and does not decide whether you should trade. It is separate from the PRO Signals bot.</p></div>
          </section>
          <section className="mx-disclosure privacy">
            <LockKeyhole size={15} />
            <div><strong>Temporary conversation · keep details general</strong><p>This chat is not saved by this interface. Free-tier messages may be processed by Google. Avoid personal account details.</p></div>
          </section>
        </div>

        <footer className="mx-dashboard-footer">
          <span>VAYDA SMART MONEY HUB · PROCESS OVER PREDICTION</span>
          <span>Use your own judgment. Trading involves risk.</span>
        </footer>
      </div>
    </main>
  );
}
