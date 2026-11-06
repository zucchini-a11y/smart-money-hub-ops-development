import { ArrowLeft, CalendarDays, FileText, MessageCircle, Send, ShieldCheck } from "lucide-react";
import "./_group.css";

function CoachBotAnimation() {
  return <span className="mx-coach-bot is-compact" aria-hidden="true">
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
  </span>;
}

export function Current() {
  return <main className="smh-coach-chat">
    <div className="mx-dashboard-shell">
      <header className="mx-dashboard-header">
        <a className="mx-wordmark" href="#">
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
        <p>A learning conversation for concepts, context, and disciplined decision-making—not a source of trade instructions.</p>
      </section>

      <div className="mx-coach-layout">
        <section className="mx-feature-panel mx-chat-panel" aria-label="Educational coach conversation">
          <div className="mx-chat-topline">
            <div><span className="mx-card-kicker">CONVERSATION</span><p>Ask about a trading concept or your decision process.</p></div>
            <button className="mx-button" type="button" disabled>Clear chat</button>
          </div>
          <div className="mx-chat-thread">
            <div className="mx-chat-welcome">
              <CoachBotAnimation />
              <span className="mx-card-kicker">IN-APP AI COACH</span>
              <h2>Bring a question, not a trade call.</h2>
              <p>Ask about a trading concept or your decision process. The Coach teaches; the separate PRO Signals bot delivers authorized signals.</p>
            </div>
          </div>
          <form className="mx-chat-form" onSubmit={(event) => event.preventDefault()}>
            <label className="mx-field" htmlFor="current-coach-message">Your question</label>
            <div className="mx-chat-input-wrap">
              <textarea id="current-coach-message" rows={3} placeholder="Ask a focused learning question…" />
              <button className="mx-button mx-button-gold" type="button">Send <Send size={14} /></button>
            </div>
            <small>0/1200 · Do not include personal account details.</small>
          </form>
        </section>

        <aside className="mx-coach-aside">
          <section className="mx-coach-notice">
            <span className="mx-card-kicker">IMPORTANT CONTEXT</span>
            <h2>Education, not advice.</h2>
            <p>The Coach is not financial advice and cannot verify live prices, market conditions, or entry confirmations. It does not decide whether you should trade.</p>
          </section>
          <section className="mx-coach-notice mx-coach-privacy">
            <span className="mx-card-kicker">PRIVACY NOTE</span>
            <h2>Keep details general.</h2>
            <p>Do not send personal account details. Free-tier messages may be processed by Google. This conversation is temporary and is not saved by this interface.</p>
          </section>
          <div className="mx-coach-disclaimer"><ShieldCheck size={16} /><span>Use your own judgment, verify information independently, and keep risk controls in your own hands.</span></div>
        </aside>
      </div>

      <footer className="mx-dashboard-footer"><span>VAYDA SMART MONEY HUB · PROCESS OVER PREDICTION</span><span>Learning only. Trading involves risk.</span></footer>
    </div>
  </main>;
}
