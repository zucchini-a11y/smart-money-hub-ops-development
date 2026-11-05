import type { FormEvent, ReactNode } from 'react';
import { Link } from 'wouter';
import type { MemberSession } from '@workspace/api-client-react';
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronLeft,
  CircleHelp,
  KeyRound,
  LockKeyhole,
  LogOut,
  Mail,
  Settings2,
  ShieldCheck,
  Sparkles,
  Video,
} from 'lucide-react';
import './member-experience.css';

type MemberSignupField = 'fullName' | 'email' | 'password' | 'code';

function maskEmailAddress(value: string) {
  const [local, domain] = value.split('@');
  if (!local || !domain) return value;
  return `${local.length < 3 ? '*' : `${local[0]}***${local.slice(-1)}`}@${domain}`;
}

interface MemberSignupExperienceProps {
  step: 'details' | 'verification';
  fullName: string;
  email: string;
  password: string;
  code: string;
  busy: boolean;
  error?: string | null;
  notice?: string | null;
  onFieldChange: (field: MemberSignupField, value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onVerify: (event: FormEvent<HTMLFormElement>) => void;
  onResend: () => void;
  onBack: () => void;
  onChangeDetails: () => void;
}

export function MemberSignupExperience({
  step,
  fullName,
  email,
  password,
  code,
  busy,
  error,
  notice,
  onFieldChange,
  onSubmit,
  onVerify,
  onResend,
  onBack,
  onChangeDetails,
}: MemberSignupExperienceProps) {
  const isVerification = step === 'verification';

  return (
    <main className="member-experience member-signup-experience">
      <div className="mx-signup-shell">
        <Link className="mx-wordmark" href="/" aria-label="Smart Money Hub home">
          <img className="mx-wordmark-image" src={`${import.meta.env.BASE_URL}vayda-logo.png`} alt="" aria-hidden="true" />
          <span><strong>VAYDA</strong><small>SMART MONEY HUB</small></span>
        </Link>

        <div className="mx-signup-layout">
          <aside className="mx-signup-aside" aria-label="Member account principles">
            <div className="mx-overline"><span className="mx-live-mark" /> MEMBER LEARNING SPACE</div>
            <p className="mx-aside-statement">A steadier way<br />to meet the markets.</p>
            <div className="mx-principle">
              <span className="mx-principle-index">THE PRINCIPLE</span>
              <blockquote>NO CONFIRMATION,<br />NO ENTRY.</blockquote>
              <p>Build understanding first. Make every decision your own.</p>
            </div>
            <div className="mx-aside-foot"><ShieldCheck size={15} /> Verified email is required for member access.</div>
          </aside>

          <section className="mx-signup-panel" aria-labelledby="mx-signup-title">
            <div className="mx-step-label"><span>01</span><i /> <span>{isVerification ? 'VERIFY EMAIL' : 'CREATE ACCOUNT'}</span></div>
            <h1 id="mx-signup-title">{isVerification ? 'Check your inbox.' : 'Start with the fundamentals.'}</h1>
            <p className="mx-panel-intro">
              {isVerification
                ? <>We sent a verification code to <strong>{maskEmailAddress(email)}</strong>. Enter it below to continue.</>
                : 'Create a member account to enter the Smart Money Hub learning space.'}
            </p>

            {error && <div className="mx-message mx-message-error" role="alert"><CircleHelp size={16} />{error}</div>}
            {notice && <div className="mx-message mx-message-notice" role="status"><CheckCircle2 size={16} />{notice}</div>}

            {!isVerification ? (
              <form className="mx-form" onSubmit={onSubmit}>
                <label className="mx-field">
                  <span>Full name</span>
                  <input autoComplete="name" name="name" value={fullName} onChange={(event) => onFieldChange('fullName', event.currentTarget.value)} required maxLength={120} />
                </label>
                <label className="mx-field">
                  <span>Email address</span>
                  <span className="mx-input-wrap"><Mail size={16} aria-hidden="true" /><input autoComplete="email" inputMode="email" name="email" type="email" value={email} onChange={(event) => onFieldChange('email', event.currentTarget.value)} required maxLength={254} /></span>
                </label>
                <label className="mx-field">
                  <span>Password</span>
                  <span className="mx-input-wrap"><LockKeyhole size={16} aria-hidden="true" /><input autoComplete="new-password" name="password" type="password" value={password} onChange={(event) => onFieldChange('password', event.currentTarget.value)} required maxLength={256} /></span>
                  <small>Choose a password you do not use elsewhere.</small>
                </label>
                <button className="mx-button mx-button-gold" type="submit" disabled={busy}>
                  {busy ? 'Creating account…' : 'Create account'} <ArrowRight size={16} />
                </button>
                <p className="mx-form-note"><KeyRound size={14} /> Email verification is part of creating your account.</p>
              </form>
            ) : (
              <form className="mx-form" onSubmit={onVerify}>
                <label className="mx-field">
                  <span>Verification code</span>
                  <input className="mx-code-input" autoComplete="one-time-code" inputMode="numeric" name="code" value={code} onChange={(event) => onFieldChange('code', event.currentTarget.value)} required maxLength={12} aria-describedby="mx-code-help" />
                  <small id="mx-code-help">Enter the code from your email.</small>
                </label>
                <button className="mx-button mx-button-gold" type="submit" disabled={busy}>
                  {busy ? 'Verifying…' : 'Verify email'} <Check size={16} />
                </button>
                <div className="mx-verify-actions">
                  <button className="mx-text-button" type="button" onClick={onResend} disabled={busy}>Resend code</button>
                  <button className="mx-text-button" type="button" onClick={onChangeDetails} disabled={busy}>Change email</button>
                </div>
                <button className="mx-back-button" type="button" onClick={onBack} disabled={busy}><ChevronLeft size={15} /> Back</button>
              </form>
            )}

            <div className="mx-signup-legal">Registration creates a member account; it does not grant PRO Signals access.</div>
            <p className="mx-signin-prompt">Already have an account? <Link href="/login">Sign in</Link></p>
          </section>
        </div>
        <footer className="mx-signup-footer">
          <span>EDUCATION FIRST · PROCESS OVER PREDICTION</span>
          <Link href="/education">Explore the learning approach <ArrowUpRight size={13} /></Link>
        </footer>
      </div>
    </main>
  );
}

interface MemberDashboardExperienceProps {
  session: MemberSession;
  telegramIdentityWidget: ReactNode;
  onSignOut: () => void;
  onSettings: () => void;
}

export function MemberDashboardExperience({
  session,
  telegramIdentityWidget,
  onSignOut,
  onSettings,
}: MemberDashboardExperienceProps) {
  return (
    <main className="member-experience mx-dashboard" data-testid="member-dashboard">
      <div className="mx-dashboard-shell">
        <header className="mx-dashboard-header">
          <Link className="mx-wordmark" href="/" aria-label="Smart Money Hub home">
            <img className="mx-wordmark-image" src={`${import.meta.env.BASE_URL}vayda-logo.png`} alt="" aria-hidden="true" />
            <span><strong>VAYDA</strong><small>SMART MONEY HUB</small></span>
          </Link>
          <div className="mx-header-actions">
            <button className="mx-button mx-button-quiet" type="button" onClick={onSettings}><Settings2 size={15} /> Account settings</button>
            <button className="mx-button mx-button-quiet" type="button" onClick={onSignOut}><LogOut size={15} /> Sign out</button>
          </div>
        </header>

        <section className="mx-welcome">
          <div className="mx-welcome-copy">
            <div className="mx-overline"><span className="mx-live-mark" /> MEMBER WORKSPACE</div>
            <h1>Welcome, <span>{session.displayName}</span></h1>
            <p>{session.email}<br/>A learning space for clearer thinking, careful observation, and deliberate decisions.</p>
          </div>
          <div className="mx-member-seal"><ShieldCheck size={19} /><span><strong>VERIFIED MEMBER</strong><small>Identity confirmed</small></span></div>
        </section>

        <section className="mx-principle-banner" aria-label="Smart Money Hub philosophy">
          <div className="mx-principle-label"><span>OUR PHILOSOPHY</span><i /></div>
          <p>NO CONFIRMATION,<br className="mx-mobile-break" /> NO ENTRY.</p>
          <span className="mx-principle-caption">Process over prediction. Every time.</span>
        </section>

        <div className="mx-dashboard-grid">
          <section className="mx-card mx-access-card" aria-labelledby="mx-access-title">
            <div className="mx-card-heading">
              <div><span className="mx-card-kicker">ACCOUNT</span><h2 id="mx-access-title">Your access</h2></div>
              <ShieldCheck size={18} aria-hidden="true" />
            </div>
            <div className="mx-access-row">
              <span>Member status</span><strong className="mx-status-verified"><i /> Verified</strong>
            </div>
            <div className="mx-access-row">
              <span>PRO Signals</span><strong className={session.proSignalsAccess ? 'mx-status-authorized' : 'mx-status-unassigned'}>{session.proSignalsAccess ? 'Authorized' : 'Not assigned'}</strong>
            </div>
            <p className="mx-access-note">PRO Signals access is assigned separately by the service. Registration and Telegram identity do not grant access.</p>
            <div className="mx-card-divider" />
            <button className="mx-inline-action" type="button" onClick={onSettings}>Manage account settings <ArrowRight size={15} /></button>
          </section>

          <section className="mx-card mx-telegram-card" aria-labelledby="mx-telegram-title">
            <div className="mx-card-heading">
              <div><span className="mx-card-kicker">IDENTITY</span><h2 id="mx-telegram-title">Telegram connection</h2></div>
              <span className="mx-icon-stamp"><CheckCircle2 size={17} /></span>
            </div>
            <p className="mx-card-description">Connect the Telegram identity you control to complete the member identity check.</p>
            <div className="mx-telegram-widget">{telegramIdentityWidget}</div>
          </section>

          <section className="mx-card mx-learning-card" aria-labelledby="mx-learning-title">
            <div className="mx-card-heading">
              <div><span className="mx-card-kicker">LEARNING SPACE</span><h2 id="mx-learning-title">Start with the method</h2></div>
              <Sparkles size={18} aria-hidden="true" />
            </div>
            <p className="mx-card-description">Study context, price action, confirmation, and disciplined execution—without promises or shortcuts.</p>
            <div className="mx-link-list">
               <Link className="mx-destination-link" href="/education"><span><small>01 / LEARN</small><strong>Trading Academy</strong></span><ArrowUpRight size={16} /></Link>
              <Link className="mx-destination-link" href="/market-analysis"><span><small>02 / OBSERVE</small><strong>Market analysis</strong></span><ArrowUpRight size={16} /></Link>
            </div>
          </section>

          <section className="mx-card mx-unavailable-card" aria-labelledby="mx-tools-title">
            <div className="mx-card-heading">
              <div><span className="mx-card-kicker">IN DEVELOPMENT</span><h2 id="mx-tools-title">More ways to learn</h2></div>
              <span className="mx-coming-soon">NOT AVAILABLE</span>
            </div>
            <div className="mx-module-row">
              <Video size={17} aria-hidden="true" /><span><strong>Video Lessons</strong><small>Not available yet</small></span><span className="mx-module-state">Unavailable</span>
            </div>
            <div className="mx-module-row">
              <Sparkles size={17} aria-hidden="true" /><span><strong>AI Coach</strong><small>Not available yet</small></span><span className="mx-module-state">Unavailable</span>
            </div>
          </section>
        </div>

        <footer className="mx-dashboard-footer">
          <span>VAYDA SMART MONEY HUB <i /> EDUCATION FIRST</span>
          <span>Trading involves risk. Education is not financial advice.</span>
        </footer>
      </div>
    </main>
  );
}
