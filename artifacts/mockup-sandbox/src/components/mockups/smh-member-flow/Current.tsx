import { ArrowUpRight, Bot, LogOut, ShieldCheck } from "lucide-react";
import "./_group.css";

type MemberSession = {
  displayName: string;
  learningDashboard: boolean;
  proSignalsAccess: boolean;
  telegramLinked: boolean;
  telegramUsername?: string | null;
};

const memberSession: MemberSession = {
  displayName: "Alex Morgan",
  learningDashboard: true,
  proSignalsAccess: false,
  telegramLinked: false,
  telegramUsername: null,
};

function TelegramLinkWidget({ session }: { session: MemberSession }) {
  return (
    <div className="member-telegram-link">
      {session.telegramLinked ? (
        <p>
          Linked Telegram account:{" "}
          <strong>{session.telegramUsername ? `@${session.telegramUsername}` : "identity verified"}</strong>
        </p>
      ) : (
        <>
          <p>
            Verify your Telegram identity with Telegram’s signed login widget. A username alone is not accepted as proof.
          </p>
          <div data-testid="telegram-link-widget" />
        </>
      )}
      <a href="https://t.me/SmartMoneyHubSignalsBot" target="_blank" rel="noreferrer">
        Open the Smart Money Hub bot
      </a>
    </div>
  );
}

export function Current() {
  const session = memberSession;

  return (
    <div className="smh-member-group">
      <main className="page member-dashboard" data-testid="member-dashboard">
        <div className="page-heading">
          <div>
            <div className="eyebrow">MEMBER WORKSPACE</div>
            <h1>Welcome, {session.displayName}</h1>
            <p className="subheading">Your member account is verified and ready.</p>
          </div>
          <button className="btn btn-outline" type="button" data-testid="button-member-sign-out">
            <LogOut size={14} />
            Sign out
          </button>
        </div>
        <div className="member-dashboard-grid">
          <section className="section-panel">
            <div className="section-head">
              <div>
                <h2 className="section-title">Account access</h2>
                <p className="section-note">Access is assigned by the server for this account.</p>
              </div>
              <div className="stat-icon"><ShieldCheck size={17} /></div>
            </div>
            <div className="member-access-list">
              <div><span>Account</span><strong>Verified member</strong></div>
              <div><span>Learning dashboard</span><strong>{session.learningDashboard ? "Available" : "Not assigned"}</strong></div>
              <div><span>PRO Signals</span><strong>{session.proSignalsAccess ? "Authorized" : "Not assigned"}</strong></div>
            </div>
            {!session.proSignalsAccess && (
              <p className="member-access-note">Registration and Telegram identity do not grant PRO Signals access.</p>
            )}
            <a
              className="btn btn-primary"
              href="/education"
              onClick={(event) => event.preventDefault()}
              data-testid="link-member-learning"
            >
              Explore the learning approach <ArrowUpRight size={14} />
            </a>
          </section>
          <section className="section-panel">
            <div className="section-head">
              <div>
                <h2 className="section-title">Link Telegram</h2>
                <p className="section-note">Connect the Telegram identity you control.</p>
              </div>
              <div className="stat-icon"><Bot size={17} /></div>
            </div>
            <div className="member-telegram-body"><TelegramLinkWidget session={session} /></div>
          </section>
        </div>
      </main>
    </div>
  );
}
