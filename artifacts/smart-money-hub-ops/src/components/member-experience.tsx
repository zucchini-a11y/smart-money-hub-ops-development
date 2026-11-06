import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Link } from 'wouter';
import {
  getGetMemberCalendarQueryKey,
  getGetMemberProSignalsQueryKey,
  getListMemberJournalTradesQueryKey,
  useCreateMemberJournalTrade,
  useDeleteMemberJournalTrade,
  useGetMemberCalendar,
  useGetMemberProSignals,
  useListMemberJournalTrades,
  useSendMemberCoachMessage,
  useUpdateMemberJournalTrade,
} from '@workspace/api-client-react';
import type {
  CreateMemberJournalTrade,
  GetMemberCalendarParams,
  ListMemberJournalTradesParams,
  MemberCalendarEvent,
  MemberCoachMessage,
  MemberJournalTrade,
  MemberSession,
  UpdateMemberJournalTrade,
} from '@workspace/api-client-react';
import { useQueryClient } from '@tanstack/react-query';
import { useLocation } from 'wouter';
import {
  ArrowRight,
  ArrowUpRight,
  ArrowLeft,
  Activity,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronLeft,
  CircleHelp,
  Clock3,
  ExternalLink,
  FileText,
  History,
  MessageCircle,
  Pencil,
  Plus,
  RefreshCw,
  Radio,
  Send,
  ShieldCheck,
  Trash2,
  KeyRound,
  LockKeyhole,
  LogOut,
  Mail,
  Settings2,
  Sparkles,
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
            <h1>Your learning space</h1>
            <p>{session.email}<br/>A learning space for clearer thinking, careful observation, and deliberate decisions.</p>
            <div className="mx-member-seal"><ShieldCheck size={19} /><span><strong>VERIFIED MEMBER</strong><small>Identity confirmed</small></span></div>
          </div>
          <aside className="mx-coach-greeting" aria-label="Welcome from your AI Coach">
            <div className="mx-coach-greeting-art"><CoachBotAnimation /></div>
            <div className="mx-coach-greeting-copy">
              <div className="mx-coach-greeting-topline"><span className="mx-card-kicker">YOUR IN-APP AI COACH</span><span className="mx-coach-study-label">STUDY MODE</span></div>
              <p><strong>Welcome, {session.displayName}.</strong> I’m your AI Coach, separate from the PRO Signals bot. Ask me about trading concepts, market structure, or reviewing your decision process.</p>
              <Link className="mx-button mx-button-quiet" href="/member/coach" data-testid="button-chat-with-coach">Chat with AI Coach <ArrowRight size={14} /></Link>
            </div>
          </aside>
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
              <span>PRO Signals bot</span><strong className={session.proSignalsAccess ? 'mx-status-authorized' : 'mx-status-unassigned'}>{session.proSignalsAccess ? 'Authorized' : 'Not assigned'}</strong>
            </div>
            <p className="mx-access-note">Access to the separate PRO Signals bot is assigned by the service. Registration and Telegram identity do not grant it.</p>
            {session.proSignalsAccess && <Link className="mx-button mx-button-quiet mx-pro-open-button" href="/member/pro-signals" data-testid="link-member-pro-signals">
              Open PRO Signals <ArrowRight size={14} />
            </Link>}
            <div className="mx-card-divider" />
            <button className="mx-inline-action" type="button" onClick={onSettings}>Manage account settings <ArrowRight size={15} /></button>
          </section>

          <section className="mx-card mx-telegram-card" aria-labelledby="mx-telegram-title">
            <div className="mx-card-heading">
              <div><span className="mx-card-kicker">OPTIONAL / PRO SIGNALS ACCESS</span><h2 id="mx-telegram-title">Telegram connection</h2></div>
              <span className="mx-icon-stamp"><CheckCircle2 size={17} /></span>
            </div>
            <p className="mx-card-description">Optional for your member dashboard. The signed Telegram check verifies the account used for PRO Signals access checks. It is separate from the in-app AI Coach; linking alone does not grant PRO access.</p>
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

          <section className="mx-card mx-coach-preview-card" aria-labelledby="mx-coach-preview-title">
            <div className="mx-coach-preview-copy">
              <span className="mx-card-kicker">IN-APP AI COACH</span>
              <h2 id="mx-coach-preview-title">Study with your Coach</h2>
              <p>Ask about trading concepts, market structure, or your decision process. This learning assistant is separate from the PRO Signals bot.</p>
              <Link className="mx-button mx-button-quiet" href="/member/coach" data-testid="button-open-member-coach">Open AI Coach <ArrowRight size={14} /></Link>
            </div>
            <CoachBotAnimation />
          </section>
        </div>

        <section className="mx-tools-section" aria-labelledby="mx-tools-section-title">
          <div className="mx-tools-heading"><div><span className="mx-card-kicker">MEMBER WORKSPACE / DEVELOPMENT</span><h2 id="mx-tools-section-title">Choose a study path</h2></div><span>{session.proSignalsAccess ? 'Four tools. One deliberate process.' : 'Three tools. One deliberate process.'}</span></div>
          <MemberFeatureDashboardLinks proSignalsAccess={session.proSignalsAccess} />
        </section>

        <footer className="mx-dashboard-footer">
          <span>VAYDA SMART MONEY HUB <i /> EDUCATION FIRST</span>
          <span>Trading involves risk. Education is not financial advice.</span>
        </footer>
      </div>
    </main>
  );
}

function CoachBotAnimation({ compact = false }: { compact?: boolean }) {
  return <span className={`mx-coach-bot${compact ? ' is-compact' : ''}`} aria-hidden="true">
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

type MemberFeaturePath = '/member/calendar' | '/member/journal' | '/member/coach' | '/member/pro-signals';

const featureLinks: Array<{ href: Exclude<MemberFeaturePath, '/member/pro-signals'>; title: string; description: string; number: string; icon: ReactNode }> = [
  { href: '/member/calendar', title: 'Economic calendar', description: 'Review verified USD events with source and timing context.', number: '01 / OBSERVE', icon: <CalendarDays size={17} /> },
  { href: '/member/journal', title: 'Trade journal', description: 'Record your own decisions and reflect on saved outcomes.', number: '02 / REVIEW', icon: <FileText size={17} /> },
  { href: '/member/coach', title: 'AI Coach', description: 'Explore trading concepts through an educational conversation.', number: '03 / STUDY', icon: <MessageCircle size={17} /> },
];

const proSignalsFeatureLink = {
  href: '/member/pro-signals' as const,
  title: 'PRO Signals',
  description: 'View member signal updates when the authorized feed is connected.',
  number: '04 / MONITOR',
  icon: <Radio size={17} />,
};

function MemberFeatureNav({ active, proSignalsAccess = false }: { active: MemberFeaturePath; proSignalsAccess?: boolean }) {
  const visibleLinks = proSignalsAccess ? [...featureLinks, proSignalsFeatureLink] : featureLinks;
  return <nav className="mx-feature-nav" aria-label="Member learning tools">
    <Link className="mx-feature-back" href="/member/dashboard"><ArrowLeft size={14} /> Workspace</Link>
    <div className="mx-feature-nav-links">{visibleLinks.map((item) =>
      <Link key={item.href} className={`mx-feature-nav-link${item.href === active ? ' is-active' : ''}`} href={item.href} data-testid={`link-member-${item.href.split('/').pop()}`}>
        {item.icon}<span>{item.title}</span>
      </Link>,
    )}</div>
  </nav>;
}

function FeatureShell({ active, title, eyebrow, intro, children, proSignalsAccess = false }: { active: MemberFeaturePath; title: string; eyebrow: string; intro: string; children: ReactNode; proSignalsAccess?: boolean }) {
  return <main className="member-experience mx-dashboard mx-feature-page">
    <div className="mx-dashboard-shell">
      <header className="mx-dashboard-header">
        <Link className="mx-wordmark" href="/member/dashboard" aria-label="Member workspace">
          <img className="mx-wordmark-image" src={`${import.meta.env.BASE_URL}vayda-logo.png`} alt="" aria-hidden="true" />
          <span><strong>VAYDA</strong><small>SMART MONEY HUB</small></span>
        </Link>
        <span className="mx-feature-private"><ShieldCheck size={14} /> PRIVATE LEARNING SPACE</span>
      </header>
      <MemberFeatureNav active={active} proSignalsAccess={proSignalsAccess} />
      <section className="mx-feature-heading">
        <div className="mx-overline"><span className="mx-live-mark" /> {eyebrow}</div>
        <h1>{title}</h1>
        <p>{intro}</p>
      </section>
      {children}
      <footer className="mx-dashboard-footer"><span>VAYDA SMART MONEY HUB <i /> PROCESS OVER PREDICTION</span><span>Learning only. Trading involves risk.</span></footer>
    </div>
  </main>;
}

export function MemberProSignalsAccessUnavailable() {
  return <FeatureShell active="/member/pro-signals" eyebrow="ACCESS / PRO SIGNALS" title="PRO access not active" intro="This member account does not currently have active PRO Signals access.">
    <section className="mx-feature-panel mx-pro-access-panel" role="status" data-testid="pro-signals-access-unavailable">
      <div className="mx-empty-panel">
        <ShieldCheck size={24} />
        <h2>Access is checked securely</h2>
        <p>Access requires an approved PRO registration, verified funded-account status, and current active Telegram membership. Linking Telegram or creating a website account alone does not grant PRO access.</p>
        <Link className="mx-button mx-button-quiet" href="/member/dashboard">Return to your workspace <ArrowLeft size={14} /></Link>
      </div>
    </section>
  </FeatureShell>;
}

export function MemberProSignalsExperience() {
  const feed = useGetMemberProSignals({
    query: {
      queryKey: getGetMemberProSignalsQueryKey(),
      retry: false,
    },
  });
  const feedStatus = feed.data?.feedStatus ?? 'not_connected';
  const heartbeat = feed.data?.lastHeartbeatAt;

  return <FeatureShell active="/member/pro-signals" proSignalsAccess eyebrow="MEMBER / PRO SIGNALS" title="PRO Signals" intro="A private view of authorized signal updates. This page displays information only; it does not place or manage broker orders.">
    <section className="mx-feature-panel mx-pro-signals-panel" data-testid="member-pro-signals">
      <div className="mx-panel-toolbar">
        <div>
          <span className="mx-card-kicker">SIGNAL FEED STATUS</span>
          <p>Only server-verified, currently active PRO members can view this page and its API.</p>
        </div>
        <button className="mx-button mx-button-quiet" type="button" onClick={() => void feed.refetch()} disabled={feed.isFetching} data-testid="button-refresh-pro-signals">
          <RefreshCw size={14} className={feed.isFetching ? 'mx-spin' : ''} /> Refresh status
        </button>
      </div>

      {feed.isError ? (
        <div className="mx-pro-feed-error" role="alert">
          <Activity size={18} />
          <div><strong>Feed status unavailable</strong><p>{(feed.error as { message?: string } | null)?.message ?? 'The status request did not complete.'}</p></div>
        </div>
      ) : (
        <div className="mx-pro-status-grid">
          <article className="mx-pro-status-card">
            <span className="mx-card-kicker">CONNECTION</span>
            <strong className="mx-pro-status-value"><i className={feedStatus === 'not_connected' ? 'is-idle' : ''} />{feed.isLoading ? 'Checking…' : 'Not connected'}</strong>
            <p>The Development EA feed has not been connected, so no live or historical signals are shown.</p>
          </article>
          <article className="mx-pro-status-card">
            <span className="mx-card-kicker">LAST HEARTBEAT</span>
            <strong className="mx-pro-status-value">{heartbeat ? prettyStamp(heartbeat) : 'No heartbeat'}</strong>
            <p>A heartbeat will appear after the authorized Development feed is connected.</p>
          </article>
        </div>
      )}

      <div className="mx-pro-feed-sections">
        <section className="mx-pro-feed-list" aria-labelledby="mx-pro-active-heading">
          <div className="mx-panel-toolbar">
            <div><span className="mx-card-kicker">CURRENT</span><h2 id="mx-pro-active-heading">Active signals</h2></div>
            <span className="mx-pro-count">{feed.isLoading ? '…' : feed.isError ? '—' : '0'}</span>
          </div>
          <div className="mx-empty-panel"><Radio size={21} /><h2>{feed.isLoading ? 'Checking feed status' : feed.isError ? 'Unable to confirm signals' : 'No active signals'}</h2><p>{feed.isError ? 'Signal data could not be checked. Refresh the status before relying on this page.' : 'There is no connected Development signal feed. Signal content will not be invented or filled with sample data.'}</p></div>
        </section>
        <section className="mx-pro-feed-list" aria-labelledby="mx-pro-history-heading">
          <div className="mx-panel-toolbar">
            <div><span className="mx-card-kicker">ARCHIVE</span><h2 id="mx-pro-history-heading">Signal history</h2></div>
            <History size={16} aria-hidden="true" />
          </div>
          <div className="mx-empty-panel"><History size={21} /><h2>{feed.isLoading ? 'Checking signal history' : feed.isError ? 'History unavailable' : 'No history available'}</h2><p>{feed.isError ? 'Signal history could not be checked. Refresh the status before relying on this page.' : 'Historical updates will appear only after a real signal feed is connected.'}</p></div>
        </section>
      </div>
      <p className="mx-feature-footnote">PRO eligibility and feed authorization are checked by the server. Registration alone does not provide PRO access.</p>
    </section>
  </FeatureShell>;
}

function prettyStamp(value?: string | null) {
  if (!value) return 'Not available';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function isSafeSourceDestination(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:';
  } catch { return false; }
}

function CalendarEventRow({ event }: { event: MemberCalendarEvent }) {
  const eventDate = new Date(`${event.eventDate}T00:00:00`);
  const dateLabel = Number.isNaN(eventDate.getTime()) ? event.eventDate : new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' }).format(eventDate);
  return <article className="mx-calendar-row" data-testid={`calendar-event-${event.id}`}>
    <div className="mx-event-date"><strong>{dateLabel}</strong><span><Clock3 size={12} /> {event.timeLabel || 'Time unavailable'}</span></div>
    <div className="mx-event-main"><div className="mx-event-title-line"><h3>{event.title}</h3><span className={`mx-impact mx-impact-${event.impact}`}>{event.impact === 'unavailable' ? 'Impact unavailable' : `${event.impact} impact`}</span></div>
      <div className="mx-event-meta"><span>{event.currency} · {event.impactBasis.replaceAll('_', ' ')}</span><span>{event.verificationStatus.replaceAll('_', ' ')}</span><span>{event.timezoneStatus.replaceAll('_', ' ')}</span></div>
    </div>
    <div className="mx-event-values"><span><small>PREVIOUS</small><strong>{event.previous ?? '—'}</strong></span><span><small>FORECAST</small><strong>{event.forecast ?? '—'}</strong></span><span><small>ACTUAL</small><strong>{event.actual ?? '—'}</strong></span></div>
    <div className="mx-event-source"><small>Source · {event.sourceName || 'Unavailable'} · Retrieved {prettyStamp(event.lastRetrievedAt)}</small><button className="mx-button mx-button-quiet" type="button" onClick={() => { if (isSafeSourceDestination(event.sourceUrl)) window.open(event.sourceUrl, '_blank', 'noopener,noreferrer'); }} disabled={!isSafeSourceDestination(event.sourceUrl)} data-testid={`button-source-${event.id}`}>View source <ExternalLink size={13} /></button></div>
  </article>;
}

export function MemberCalendarExperience() {
  const [filters, setFilters] = useState<{ from: string; to: string; impact: GetMemberCalendarParams['impact'] | '' }>({ from: '', to: '', impact: '' });
  const params = useMemo<GetMemberCalendarParams>(() => ({
    ...(filters.from ? { from: filters.from } : {}),
    ...(filters.to ? { to: filters.to } : {}),
    ...(filters.impact ? { impact: filters.impact } : {}),
    currency: 'USD' as const,
  }), [filters.from, filters.to, filters.impact]);
  const calendar = useGetMemberCalendar(params, { query: { queryKey: getGetMemberCalendarQueryKey(params) } });
  return <FeatureShell active="/member/calendar" eyebrow="STUDY / USD EVENTS" title="Economic calendar" intro="A source-aware view of scheduled USD releases relevant to USD and gold study. Timing and reported values are shown as supplied; this is not a trade signal.">
    <section className="mx-feature-panel">
      <div className="mx-panel-toolbar">
        <div><span className="mx-card-kicker">OFFICIAL USD CALENDAR</span><p>Source status and retrieval time stay visible so you can judge context.</p></div>
        <button className="mx-button mx-button-quiet" type="button" onClick={() => void calendar.refetch()} disabled={calendar.isFetching} data-testid="button-refresh-calendar"><RefreshCw size={14} className={calendar.isFetching ? 'mx-spin' : ''} /> Refresh</button>
      </div>
      <div className="mx-filter-row">
        <label className="mx-filter-field">From<input type="date" value={filters.from} onChange={(event) => setFilters((old) => ({ ...old, from: event.currentTarget.value }))} data-testid="input-calendar-from" /></label>
        <label className="mx-filter-field">Through<input type="date" value={filters.to} onChange={(event) => setFilters((old) => ({ ...old, to: event.currentTarget.value }))} data-testid="input-calendar-to" /></label>
        <label className="mx-filter-field">Impact<select value={filters.impact} onChange={(event) => setFilters((old) => ({ ...old, impact: event.currentTarget.value as GetMemberCalendarParams['impact'] | '' }))} data-testid="select-calendar-impact"><option value="">All impacts</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option><option value="unavailable">Unavailable</option></select></label>
        <span className="mx-calendar-clock"><Clock3 size={14} /> Times shown in source timezone where available</span>
      </div>
      {calendar.isLoading ? <div className="mx-skeleton-stack" aria-label="Loading calendar">{[0, 1, 2].map((item) => <div className="mx-skeleton-card" key={item}><i /><span /><span /></div>)}</div>
        : calendar.isError ? <div className="mx-empty-panel" role="alert"><CircleHelp size={20} /><h2>Calendar unavailable</h2><p>We could not retrieve the official event feed. No event values are being substituted.</p><button className="mx-button mx-button-quiet" type="button" onClick={() => void calendar.refetch()}>Try again</button></div>
          : <>
            <div className={`mx-source-status mx-source-${calendar.data?.stale ? 'stale' : 'current'}`}>
              <span><i /> {calendar.data?.stale ? 'Feed may be stale' : 'Feed status'}</span>
              <span>{calendar.data?.refreshedAt ? `Refreshed ${prettyStamp(calendar.data.refreshedAt)}` : 'Refresh time unavailable'}</span>
            </div>
            {calendar.data?.sources?.length ? <div className="mx-source-list">{calendar.data.sources.map((source) => <div className="mx-source-item" key={source.id}><strong>{source.sourceName}</strong><span className={`mx-source-badge mx-source-badge-${source.status}`}>{source.status.replaceAll('_', ' ')}</span><small>{source.message}{source.checkedAt ? ` · Checked ${prettyStamp(source.checkedAt)}` : ''}</small></div>)}</div> : <p className="mx-inline-note">Source status has not been provided.</p>}
            {calendar.data?.events?.length ? <div className="mx-calendar-list">{calendar.data.events.map((event) => <CalendarEventRow key={event.id} event={event} />)}</div>
              : <div className="mx-empty-panel"><CalendarDays size={21} /><h2>No events in this view</h2><p>The feed returned no matching events for the selected dates.</p></div>}
          </>}
    </section>
    <p className="mx-feature-footnote">XAUUSD study context only. Market schedules may change; confirm details with the named source before relying on them.</p>
  </FeatureShell>;
}

type JournalDraft = {
  instrument: string; direction: 'long' | 'short'; entryPrice: string; stopLoss: string; takeProfit: string;
  positionSize: string; riskPercent: string; entryAt: string; exitAt: string; outcome: 'open' | 'win' | 'loss' | 'breakeven';
  realizedPnl: string; notes: string;
};

const blankDraft = (): JournalDraft => ({ instrument: '', direction: 'long', entryPrice: '', stopLoss: '', takeProfit: '', positionSize: '', riskPercent: '', entryAt: '', exitAt: '', outcome: 'open', realizedPnl: '', notes: '' });
function localDateTime(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}
function tradeDraft(trade: MemberJournalTrade): JournalDraft {
  return { instrument: trade.instrument, direction: trade.direction, entryPrice: String(trade.entryPrice), stopLoss: String(trade.stopLoss), takeProfit: String(trade.takeProfit), positionSize: String(trade.positionSize), riskPercent: trade.riskPercent == null ? '' : String(trade.riskPercent), entryAt: localDateTime(trade.entryAt), exitAt: localDateTime(trade.exitAt), outcome: trade.outcome, realizedPnl: trade.realizedPnl == null ? '' : String(trade.realizedPnl), notes: trade.notes ?? '' };
}
function draftPayload(draft: JournalDraft): CreateMemberJournalTrade {
  return {
    instrument: draft.instrument.trim(), direction: draft.direction, entryPrice: Number(draft.entryPrice), stopLoss: Number(draft.stopLoss),
    takeProfit: Number(draft.takeProfit), positionSize: Number(draft.positionSize),
    ...(draft.riskPercent !== '' ? { riskPercent: Number(draft.riskPercent) } : {}),
    entryAt: new Date(draft.entryAt).toISOString(), ...(draft.exitAt ? { exitAt: new Date(draft.exitAt).toISOString() } : {}),
    outcome: draft.outcome, ...(draft.realizedPnl !== '' ? { realizedPnl: Number(draft.realizedPnl) } : {}), notes: draft.notes.trim(),
  };
}

export function MemberJournalExperience() {
  const client = useQueryClient();
  const [filters, setFilters] = useState<{ instrument: string; outcome: ListMemberJournalTradesParams['outcome'] | '' }>({ instrument: '', outcome: '' });
  const journalParams = useMemo<ListMemberJournalTradesParams | undefined>(() => ({
    ...(filters.instrument.trim() ? { instrument: filters.instrument.trim() } : {}),
    ...(filters.outcome ? { outcome: filters.outcome } : {}),
  }), [filters.instrument, filters.outcome]);
  const journal = useListMemberJournalTrades(journalParams, { query: { queryKey: getListMemberJournalTradesQueryKey(journalParams) } });
  const createTrade = useCreateMemberJournalTrade();
  const updateTrade = useUpdateMemberJournalTrade();
  const deleteTrade = useDeleteMemberJournalTrade();
  const [draft, setDraft] = useState<JournalDraft>(blankDraft);
  const [editing, setEditing] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState('');
  const pending = createTrade.isPending || updateTrade.isPending;
  const reload = () => client.invalidateQueries({ queryKey: getListMemberJournalTradesQueryKey(journalParams) });
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError('');
    try {
      const payload = draftPayload(draft);
      if (editing) {
        const updatePayload: UpdateMemberJournalTrade = payload;
        await updateTrade.mutateAsync({ tradeId: editing, data: updatePayload });
      } else await createTrade.mutateAsync({ data: payload });
      await reload(); setDraft(blankDraft()); setEditing(null); setShowForm(false);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'This trade could not be saved.'); }
  };
  const edit = (trade: MemberJournalTrade) => { setEditing(trade.id); setDraft(tradeDraft(trade)); setShowForm(true); setError(''); };
  const remove = async (trade: MemberJournalTrade) => {
    if (!window.confirm(`Delete the ${trade.instrument} journal record? This cannot be undone.`)) return;
    setError('');
    try { await deleteTrade.mutateAsync({ tradeId: trade.id }); await reload(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'This record could not be deleted.'); }
  };
  const field = (key: keyof JournalDraft, value: string) => setDraft((old) => ({ ...old, [key]: value }));
  const summary = journal.data?.summary;
  return <FeatureShell active="/member/journal" eyebrow="REVIEW / YOUR RECORDS" title="Trade journal" intro="Save your plan and your own outcome data. Summaries below are derived only from records saved to your member journal.">
    <section className="mx-feature-panel">
      <div className="mx-panel-toolbar"><div><span className="mx-card-kicker">PERSONAL TRADE RECORDS</span><p>Realized P/L is entered by you; it is not connected to a broker or market feed.</p></div>
        <button className="mx-button mx-button-gold" type="button" onClick={() => { setDraft(blankDraft()); setEditing(null); setShowForm((value) => !value); setError(''); }} data-testid="button-add-trade"><Plus size={15} /> {showForm && !editing ? 'Close form' : 'Record a trade'}</button>
      </div>
      <div className="mx-journal-summary">
        <div><small>SAVED RECORDS</small><strong>{summary?.totalTrades ?? '—'}</strong></div><div><small>OPEN</small><strong>{summary?.openTrades ?? '—'}</strong></div>
        <div><small>WIN RATE</small><strong>{summary?.winRate == null ? '—' : `${summary.winRate}%`}</strong></div><div><small>RECORDED P/L · MEMBER-ENTERED</small><strong>{summary ? summary.totalRecordedPnl : '—'}</strong></div>
      </div>
      {showForm && <form className="mx-trade-form" onSubmit={(event) => void submit(event)}>
        <div className="mx-form-title"><div><span className="mx-card-kicker">{editing ? 'EDIT RECORD' : 'NEW RECORD'}</span><h2>{editing ? 'Update your trade notes' : 'Capture the decision'}</h2></div><button className="mx-icon-button" type="button" onClick={() => { setShowForm(false); setEditing(null); setError(''); }} aria-label="Close trade form"><ChevronLeft size={16} /></button></div>
        {error && <div className="mx-inline-error" role="alert">{error}</div>}
        <div className="mx-trade-fields">
          <label className="mx-field">Instrument<input value={draft.instrument} onChange={(event) => field('instrument', event.currentTarget.value)} required maxLength={24} placeholder="For example, XAUUSD" data-testid="input-trade-instrument" /></label>
          <label className="mx-field">Direction<select value={draft.direction} onChange={(event) => field('direction', event.currentTarget.value as JournalDraft['direction'])}><option value="long">Long</option><option value="short">Short</option></select></label>
          <label className="mx-field">Entry price<input type="number" min="0.000001" step="any" value={draft.entryPrice} onChange={(event) => field('entryPrice', event.currentTarget.value)} required /></label>
          <label className="mx-field">Stop loss<input type="number" min="0.000001" step="any" value={draft.stopLoss} onChange={(event) => field('stopLoss', event.currentTarget.value)} required /></label>
          <label className="mx-field">Take profit<input type="number" min="0.000001" step="any" value={draft.takeProfit} onChange={(event) => field('takeProfit', event.currentTarget.value)} required /></label>
          <label className="mx-field">Position size<input type="number" min="0.000001" step="any" value={draft.positionSize} onChange={(event) => field('positionSize', event.currentTarget.value)} required /></label>
          <label className="mx-field">Risk % <span className="mx-field-optional">optional</span><input type="number" min="0" max="100" step="any" value={draft.riskPercent} onChange={(event) => field('riskPercent', event.currentTarget.value)} /></label>
          <label className="mx-field">Entry time<input type="datetime-local" value={draft.entryAt} onChange={(event) => field('entryAt', event.currentTarget.value)} required /></label>
          <label className="mx-field">Exit time <span className="mx-field-optional">optional</span><input type="datetime-local" value={draft.exitAt} onChange={(event) => field('exitAt', event.currentTarget.value)} /></label>
          <label className="mx-field">Outcome<select value={draft.outcome} onChange={(event) => field('outcome', event.currentTarget.value as JournalDraft['outcome'])}><option value="open">Open</option><option value="win">Win</option><option value="loss">Loss</option><option value="breakeven">Breakeven</option></select></label>
          <label className="mx-field">Realized P/L <span className="mx-field-optional">entered by you</span><input type="number" step="any" value={draft.realizedPnl} onChange={(event) => field('realizedPnl', event.currentTarget.value)} /></label>
          <label className="mx-field mx-field-wide">Reflection notes<textarea value={draft.notes} onChange={(event) => field('notes', event.currentTarget.value)} maxLength={5000} rows={3} placeholder="What did you observe? What would you review next time?" /></label>
        </div>
        <p className="mx-upload-note"><span>CHART SCREENSHOTS</span> Temporarily unavailable in Development. This journal stores written records only.</p>
        <div className="mx-form-actions"><button className="mx-button mx-button-gold" type="submit" disabled={pending || deleteTrade.isPending}>{pending ? 'Saving record…' : editing ? 'Save changes' : 'Save trade'}</button><button className="mx-button mx-button-quiet" type="button" onClick={() => { setShowForm(false); setEditing(null); }}>Cancel</button></div>
      </form>}
      <div className="mx-filter-row mx-journal-filters">
        <label className="mx-filter-field">Instrument<input type="search" value={filters.instrument} onChange={(event) => setFilters((old) => ({ ...old, instrument: event.currentTarget.value }))} maxLength={24} placeholder="Search instrument" data-testid="input-journal-instrument" /></label>
        <label className="mx-filter-field">Outcome<select value={filters.outcome} onChange={(event) => setFilters((old) => ({ ...old, outcome: event.currentTarget.value as ListMemberJournalTradesParams['outcome'] | '' }))} data-testid="select-journal-outcome"><option value="">All outcomes</option><option value="open">Open</option><option value="win">Win</option><option value="loss">Loss</option><option value="breakeven">Breakeven</option></select></label>
        <span className="mx-calendar-clock">Only your saved records are shown.</span>
      </div>
      {journal.isLoading ? <div className="mx-skeleton-stack" aria-label="Loading journal">{[0, 1].map((item) => <div className="mx-skeleton-card" key={item}><i /><span /><span /></div>)}</div>
        : journal.isError ? <div className="mx-empty-panel" role="alert"><CircleHelp size={20} /><h2>Journal unavailable</h2><p>Your saved records could not be loaded. Please retry; no example trades are shown.</p><button className="mx-button mx-button-quiet" type="button" onClick={() => void journal.refetch()}>Try again</button></div>
          : journal.data?.trades.length ? <div className="mx-trade-list">{journal.data.trades.map((trade) => <article className="mx-trade-row" key={trade.id} data-testid={`journal-trade-${trade.id}`}>
            <div className="mx-trade-primary"><span className="mx-trade-direction">{trade.direction.toUpperCase()}</span><h3>{trade.instrument}</h3><span className={`mx-outcome mx-outcome-${trade.outcome}`}>{trade.outcome}</span><small>{prettyStamp(trade.entryAt)}</small></div>
            <div className="mx-trade-plan"><span><small>ENTRY</small><strong>{trade.entryPrice}</strong></span><span><small>STOP</small><strong>{trade.stopLoss}</strong></span><span><small>TARGET</small><strong>{trade.takeProfit}</strong></span><span><small>PLANNED R:R</small><strong>{trade.riskRewardRatio == null ? '—' : `${trade.riskRewardRatio.toFixed(2)} : 1`}</strong></span><span><small>YOUR P/L</small><strong>{trade.realizedPnl == null ? '—' : trade.realizedPnl}</strong></span></div>
            {trade.notes && <p className="mx-trade-notes">{trade.notes}</p>}
            <div className="mx-trade-actions"><button className="mx-icon-button" type="button" onClick={() => edit(trade)} aria-label={`Edit ${trade.instrument} record`} data-testid={`button-edit-trade-${trade.id}`}><Pencil size={14} /> Edit</button><button className="mx-icon-button mx-delete-button" type="button" onClick={() => void remove(trade)} disabled={deleteTrade.isPending} aria-label={`Delete ${trade.instrument} record`} data-testid={`button-delete-trade-${trade.id}`}><Trash2 size={14} /> Delete</button></div>
          </article>)}</div>
            : <div className="mx-empty-panel"><FileText size={21} /><h2>Your journal starts with a saved decision</h2><p>No trade records have been saved yet. Add one when you are ready to review your process.</p><button className="mx-button mx-button-quiet" type="button" onClick={() => setShowForm(true)}><Plus size={14} /> Record a trade</button></div>}
      {!!error && !showForm && <div className="mx-inline-error" role="alert">{error}</div>}
    </section>
  </FeatureShell>;
}

type CoachLine = { role: 'user' | 'assistant'; content: string };
export function MemberCoachExperience() {
  const coach = useSendMemberCoachMessage();
  const [history, setHistory] = useState<CoachLine[]>([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [topic, setTopic] = useState('');
  const [responseDisclaimer, setResponseDisclaimer] = useState('');
  const [typingIndex, setTypingIndex] = useState<number | null>(null);
  const [typedLength, setTypedLength] = useState(0);
  const threadRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const assistantBusy = coach.isPending || typingIndex !== null;

  useEffect(() => {
    if (typingIndex === null) return;
    const line = history[typingIndex];
    if (!line) {
      setTypingIndex(null);
      setTypedLength(0);
      return;
    }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setTypingIndex(null);
      setTypedLength(0);
      return;
    }
    if (typedLength >= line.content.length) {
      setTypingIndex(null);
      setTypedLength(0);
      return;
    }

    const step = Math.max(1, Math.ceil(line.content.length / 120));
    const timer = window.setTimeout(() => {
      setTypedLength((current) => Math.min(line.content.length, current + step));
    }, 22);
    return () => window.clearTimeout(timer);
  }, [history, typingIndex, typedLength]);

  useEffect(() => {
    const thread = threadRef.current;
    if (thread && stickToBottomRef.current) thread.scrollTop = thread.scrollHeight;
  }, [history, typedLength, assistantBusy]);

  const send = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = message.trim();
    if (!text || assistantBusy) return;
    setError(''); setMessage('');
    stickToBottomRef.current = true;
    const previous = history.slice(-12) as MemberCoachMessage[];
    setHistory((items) => [...items, { role: 'user', content: text }]);
    try {
      const response = await coach.mutateAsync({ data: { message: text, history: previous } });
      setTopic(response.topic);
      setResponseDisclaimer(response.disclaimer);
      setHistory((items) => [...items, { role: 'assistant', content: response.reply }]);
      setTypedLength(0);
      setTypingIndex(history.length + 1);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The Coach could not respond. Please try again.');
    }
  };
  const clear = () => { setHistory([]); setTopic(''); setResponseDisclaimer(''); setError(''); setMessage(''); setTypingIndex(null); setTypedLength(0); stickToBottomRef.current = true; };
  return <FeatureShell active="/member/coach" eyebrow="STUDY / GUIDED REFLECTION" title="AI Coach" intro="A learning conversation for concepts, context, and disciplined decision-making—not a source of trade instructions.">
    <div className="mx-coach-layout">
      <section className="mx-feature-panel mx-chat-panel" aria-label="Educational coach conversation">
        <div className="mx-chat-topline"><div><span className="mx-card-kicker">CONVERSATION</span><p>{topic ? `Current topic · ${topic}` : 'Ask about a trading concept or your decision process.'}</p></div><button className="mx-button mx-button-quiet" type="button" onClick={clear} disabled={!history.length || assistantBusy} data-testid="button-clear-coach">Clear chat</button></div>
        <div
          ref={threadRef}
          className="mx-chat-thread"
          aria-live="off"
          onScroll={(event) => {
            const node = event.currentTarget;
            stickToBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48;
          }}
        >
          {!history.length && <div className="mx-chat-welcome"><CoachBotAnimation compact /><span className="mx-card-kicker">IN-APP AI COACH</span><h2>Bring a question, not a trade call.</h2><p>Ask about a trading concept or your decision process. The Coach teaches; the separate PRO Signals bot delivers authorized signals.</p></div>}
          {history.map((line, index) => {
            const isTyping = typingIndex === index;
            const visibleText = isTyping ? line.content.slice(0, typedLength) : line.content;
            return <article className={`mx-chat-line mx-chat-${line.role}`} key={`${index}-${line.role}`} data-testid={`coach-message-${index}`}>
              <span className="mx-chat-role">{line.role === 'user' ? 'YOU' : 'COACH'}</span>
              <p>{visibleText}{isTyping && <span className="mx-chat-caret" aria-hidden="true" />}</p>
            </article>;
          })}
          {assistantBusy && <div className="mx-chat-pending" role="status" aria-label="Coach is typing"><i /><i /><i /><span>Coach is typing…</span></div>}
        </div>
        {responseDisclaimer && <p className="mx-response-disclaimer" role="note">{responseDisclaimer}</p>}
        {error && <div className="mx-inline-error" role="alert">{error}</div>}
        <form className="mx-chat-form" onSubmit={(event) => void send(event)}>
          <label className="mx-field" htmlFor="coach-message">Your question</label>
          <div className="mx-chat-input-wrap"><textarea id="coach-message" value={message} onChange={(event) => setMessage(event.currentTarget.value)} rows={3} maxLength={1200} placeholder="Ask a focused learning question…" required disabled={assistantBusy} data-testid="input-coach-message" /><button className="mx-button mx-button-gold" type="submit" disabled={assistantBusy || !message.trim()} data-testid="button-send-coach">{coach.isPending ? 'Thinking…' : typingIndex !== null ? 'Typing…' : 'Send'} <Send size={14} /></button></div>
          <small>{message.length}/1200 · Do not include personal account details.</small>
        </form>
      </section>
      <aside className="mx-coach-aside">
        <section className="mx-coach-notice"><span className="mx-card-kicker">IMPORTANT CONTEXT</span><h2>Education, not advice.</h2><p>The Coach is not financial advice and cannot verify live prices, market conditions, or entry confirmations. It does not decide whether you should trade.</p></section>
        <section className="mx-coach-notice mx-coach-privacy"><span className="mx-card-kicker">PRIVACY NOTE</span><h2>Keep details general.</h2><p>Do not send personal account details. Free-tier messages may be processed by Google. This conversation is temporary and is not saved by this interface.</p></section>
        <div className="mx-coach-disclaimer"><ShieldCheck size={16} /><span>Use your own judgment, verify information independently, and keep risk controls in your own hands.</span></div>
      </aside>
    </div>
    {history.length > 0 && <p className="mx-feature-footnote">Chat history exists only in this page session and is sent as bounded context with your next message.</p>}
  </FeatureShell>;
}

export function MemberFeatureDashboardLinks({ proSignalsAccess = false }: { proSignalsAccess?: boolean }) {
  const visibleLinks = proSignalsAccess ? [...featureLinks, proSignalsFeatureLink] : featureLinks;
  return <div className="mx-feature-dashboard-links">
    {visibleLinks.map((item) => <Link className="mx-tool-card" href={item.href} key={item.href} data-testid={`card-feature-${item.href.split('/').pop()}`}>
      <span className="mx-tool-icon">{item.icon}</span><span className="mx-tool-number">{item.number}</span><h3>{item.title}</h3><p>{item.description}</p><span className="mx-tool-action">Open workspace <ArrowRight size={14} /></span>
    </Link>)}
  </div>;
}
