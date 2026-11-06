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
import { publicSiteLinks } from '../public-site/config';
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
  onSignOut: () => void;
  onSettings: () => void;
}

export function MemberDashboardExperience({
  session,
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
            <button className="mx-header-icon-button" type="button" onClick={onSettings} aria-label="Account settings" title="Account settings"><Settings2 size={17} /></button>
            <button className="mx-header-icon-button" type="button" onClick={onSignOut} aria-label="Sign out" title="Sign out"><LogOut size={17} /></button>
          </div>
        </header>

        <section className="mx-welcome" aria-label="Member welcome">
          <aside className="mx-coach-greeting" aria-label="Welcome from your AI Coach">
            <div className="mx-coach-greeting-art"><CoachBotAnimation /></div>
            <div className="mx-coach-greeting-copy">
              <div className="mx-coach-greeting-topline"><span className="mx-card-kicker">IN-APP AI COACH</span><span className="mx-coach-study-label">STUDY MODE</span></div>
              <h1>Welcome, {session.displayName}.</h1>
              <p>I’m here to help you study trading concepts and review your decision process. I don’t send signals or place trades.</p>
              <div className="mx-coach-greeting-actions">
                <Link className="mx-button mx-button-gold" href="/member/coach" data-testid="button-chat-with-coach">Chat with AI Coach <ArrowRight size={14} /></Link>
                <button
                  className="mx-button mx-button-quiet mx-coach-telegram-button"
                  type="button"
                  onClick={() => window.open(publicSiteLinks.primaryCommunity, '_blank', 'noopener,noreferrer')}
                  aria-label="Chat with the Smart Money Hub Coach on Telegram"
                  data-testid="button-coach-telegram"
                >
                  <Send size={14} /> Chat with Coach on Telegram <ArrowUpRight size={13} />
                </button>
              </div>
              <div className="mx-welcome-status">
                <span><ShieldCheck size={13} /> Verified member</span>
                <span><Radio size={13} /> PRO Signals {session.proSignalsAccess ? 'authorized' : 'not assigned'}</span>
              </div>
            </div>
          </aside>
        </section>

        <section className="mx-principle-banner" aria-label="Smart Money Hub philosophy">
          <span className="mx-card-kicker">OUR RULE</span>
          <p>NO CONFIRMATION, NO ENTRY.</p>
        </section>

        <section className="mx-tools-section" aria-labelledby="mx-tools-section-title">
          <div className="mx-tools-heading"><h2 id="mx-tools-section-title">Your tools</h2></div>
          <MemberFeatureDashboardLinks proSignalsAccess={session.proSignalsAccess} />
        </section>

        <footer className="mx-dashboard-footer">
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
  const datePart = event.eventDate?.slice(0, 10);
  const eventDate = /^\d{4}-\d{2}-\d{2}$/.test(datePart ?? '')
    ? new Date(`${datePart}T00:00:00`)
    : new Date(event.eventDate);
  const dateLabel = Number.isNaN(eventDate.getTime())
    ? null
    : new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' }).format(eventDate);
  const eventInstant = event.eventAt ? new Date(event.eventAt) : null;
  const hasVerifiedInstant = Boolean(eventInstant && !Number.isNaN(eventInstant.getTime()));
  const verifiedTime = hasVerifiedInstant
    ? event.timeLabel && !/unverified|unavailable/i.test(event.timeLabel)
      ? event.timeLabel
      : `${new Intl.DateTimeFormat('en-NG', {
          timeZone: 'Africa/Lagos',
          hour: '2-digit',
          minute: '2-digit',
          hourCycle: 'h23',
        }).format(eventInstant!)} WAT`
    : null;
  const reportedValues = [
    { label: 'Previous', value: event.previous },
    { label: 'Forecast', value: event.forecast },
    { label: 'Actual', value: event.actual },
  ].filter((item): item is { label: string; value: string } => Boolean(item.value?.trim()));
  const impactLabel = event.impact === 'unavailable'
    ? null
    : `${event.impact.charAt(0).toUpperCase()}${event.impact.slice(1)} impact`;
  const hasSource = Boolean(event.sourceName?.trim());
  const hasSourceButton = isSafeSourceDestination(event.sourceUrl);

  return <article className="mx-calendar-row" data-testid={`calendar-event-${event.id}`}>
    {(dateLabel || verifiedTime) && <div className="mx-event-date">
      {dateLabel && <strong>{dateLabel}</strong>}
      {verifiedTime && <span><Clock3 size={12} /> {verifiedTime}</span>}
    </div>}
    <div className="mx-event-main">
      <div className="mx-event-title-line">
        <h3>{event.title}</h3>
        {impactLabel && <span className={`mx-impact mx-impact-${event.impact}`}>{impactLabel}</span>}
      </div>
    </div>
    {reportedValues.length > 0 && <div className="mx-event-values" aria-label="Reported event values">
      {reportedValues.map((item) => <span key={item.label}><small>{item.label}</small><strong>{item.value}</strong></span>)}
    </div>}
    {(hasSource || hasSourceButton) && <div className="mx-event-source">
      {hasSource && <small><strong>{event.sourceName}</strong></small>}
      {hasSourceButton && <button className="mx-button mx-button-quiet" type="button" onClick={() => { if (isSafeSourceDestination(event.sourceUrl)) window.open(event.sourceUrl, '_blank', 'noopener,noreferrer'); }} data-testid={`button-source-${event.id}`}>Official source <ExternalLink size={13} /></button>}
    </div>}
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
  return <FeatureShell active="/member/calendar" eyebrow="USD EVENTS" title="Economic calendar" intro="Upcoming U.S. releases for USD. Dates, verified release times, impact, and reported values.">
    <section className="mx-feature-panel mx-calendar-panel" aria-label="USD economic calendar">
      <div className="mx-panel-toolbar">
        <div><span className="mx-card-kicker">USD RELEASES</span><p>Check the event, timing, impact, and reported values.</p></div>
        <button className="mx-button mx-button-quiet" type="button" onClick={() => void calendar.refetch()} disabled={calendar.isFetching} data-testid="button-refresh-calendar"><RefreshCw size={14} className={calendar.isFetching ? 'mx-spin' : ''} /> Refresh</button>
      </div>
      <div className="mx-filter-row">
        <label className="mx-filter-field">From<input type="date" value={filters.from} onChange={(event) => setFilters((old) => ({ ...old, from: event.currentTarget.value }))} data-testid="input-calendar-from" /></label>
        <label className="mx-filter-field">Through<input type="date" value={filters.to} onChange={(event) => setFilters((old) => ({ ...old, to: event.currentTarget.value }))} data-testid="input-calendar-to" /></label>
        <label className="mx-filter-field">Impact<select value={filters.impact} onChange={(event) => setFilters((old) => ({ ...old, impact: event.currentTarget.value as GetMemberCalendarParams['impact'] | '' }))} data-testid="select-calendar-impact"><option value="">All impacts</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
      </div>
      {calendar.isLoading ? <div className="mx-skeleton-stack" aria-label="Loading calendar">{[0, 1, 2].map((item) => <div className="mx-skeleton-card" key={item}><i /><span /><span /></div>)}</div>
        : calendar.isError ? <div className="mx-empty-panel" role="alert"><CircleHelp size={20} /><h2>Calendar didn’t load</h2><p>Please try again in a moment.</p><button className="mx-button mx-button-quiet" type="button" onClick={() => void calendar.refetch()}>Try again</button></div>
          : <>
            {calendar.data?.events?.length ? <div className="mx-calendar-list">{calendar.data.events.map((event) => <CalendarEventRow key={event.id} event={event} />)}</div>
              : <div className="mx-empty-panel"><CalendarDays size={21} /><h2>No events in this date range</h2><p>Try changing the dates or impact filter.</p></div>}
          </>}
    </section>
    <p className="mx-feature-footnote">For learning only—not financial advice or a trade signal.</p>
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
  return <FeatureShell active="/member/coach" eyebrow="MEMBER CHAT" title="AI Coach" intro="Ask about a trading concept or reflect on your decision process.">
    <section className="mx-chat-workspace" aria-label="Educational Coach conversation" data-testid="member-coach-chat">
      <header className="mx-conversation-head">
        <div className="mx-conversation-title">
          <CoachBotAnimation compact />
          <div><strong>VAYDA Coach</strong><small>Learning mode · Temporary chat</small></div>
        </div>
        <button className="mx-chat-clear" type="button" onClick={clear} disabled={!history.length || assistantBusy} aria-label="Clear chat" title="Clear chat" data-testid="button-clear-coach">
          <Trash2 size={15} />
        </button>
      </header>
      <div className="mx-chat-thread"
        ref={threadRef}
        aria-live="off"
        onScroll={(event) => {
          const node = event.currentTarget;
          stickToBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48;
        }}
      >
        {!history.length && <div className="mx-chat-welcome">
          <span className="mx-chat-welcome-avatar"><CoachBotAnimation compact /></span>
          <div className="mx-chat-welcome-content">
            <div className="mx-chat-message-meta">VAYDA Coach</div>
            <div className="mx-chat-bubble"><p>Welcome. Ask me about a trading concept or a decision you’re reviewing. I can help you think it through—not tell you when to trade.</p></div>
          </div>
        </div>}
        {history.map((line, index) => {
          const isTyping = typingIndex === index;
          const visibleText = isTyping ? line.content.slice(0, typedLength) : line.content;
          return <article className={`mx-chat-line mx-chat-${line.role}`} key={`${index}-${line.role}`} data-testid={`coach-message-${index}`}>
            <div className="mx-chat-message-meta">
              {line.role === 'assistant' && <span className="mx-chat-message-avatar"><CoachBotAnimation compact /></span>}
              <span>{line.role === 'user' ? 'You' : 'VAYDA Coach'}</span>
            </div>
            <div className="mx-chat-bubble"><p>{visibleText}{isTyping && <span className="mx-chat-caret" aria-hidden="true" />}</p></div>
          </article>;
        })}
        {assistantBusy && <div className="mx-chat-pending" role="status" aria-label="Coach is typing">
          <span className="mx-chat-message-avatar"><CoachBotAnimation compact /></span>
          <div className="mx-chat-pending-bubble"><span>VAYDA Coach is typing</span><i /><i /><i /></div>
        </div>}
      </div>
      {responseDisclaimer && <p className="mx-response-disclaimer" role="note">{responseDisclaimer}</p>}
      {error && <div className="mx-inline-error" role="alert">{error}</div>}
      <form className="mx-chat-form" onSubmit={(event) => void send(event)}>
        <label className="mx-visually-hidden" htmlFor="coach-message">Message the AI Coach</label>
        <div className="mx-chat-input-wrap">
          <textarea id="coach-message" value={message} onChange={(event) => setMessage(event.currentTarget.value)} rows={2} maxLength={1200} placeholder="Message the Coach…" required disabled={assistantBusy} data-testid="input-coach-message" />
          <button className="mx-chat-send" type="submit" disabled={assistantBusy || !message.trim()} aria-label="Send message" title={coach.isPending ? 'Waiting for the Coach' : 'Send message'} data-testid="button-send-coach">
            <Send size={16} />
          </button>
        </div>
        <div className="mx-chat-input-meta"><small>{message.length}/1200</small><small>Keep account details private</small></div>
      </form>
    </section>
    <div className="mx-chat-assurance">
      <span><ShieldCheck size={13} /> Educational support only · Not financial advice</span>
      <details className="mx-chat-privacy">
        <summary><LockKeyhole size={13} /> Privacy</summary>
        <p>This conversation is temporary and is not saved by this interface. Free-tier messages may be processed by Google. Avoid personal account details.</p>
      </details>
    </div>
  </FeatureShell>;
}

export function MemberFeatureDashboardLinks({ proSignalsAccess = false }: { proSignalsAccess?: boolean }) {
  const quickLinks = [
    { href: '/member/calendar', title: 'Calendar', icon: <CalendarDays size={18} /> },
    { href: '/member/journal', title: 'Journal', icon: <FileText size={18} /> },
    { href: '/education', title: 'Trading Academy', icon: <Sparkles size={18} /> },
    { href: '/market-analysis', title: 'Market Analysis', icon: <Activity size={18} /> },
    ...(proSignalsAccess ? [{ href: '/member/pro-signals', title: 'PRO Signals', icon: <Radio size={18} /> }] : []),
  ];
  return <div className="mx-feature-dashboard-links">
    {quickLinks.map((item) => <Link className="mx-tool-card" href={item.href} key={item.href} aria-label={item.title} data-testid={`card-feature-${item.href.split('/').pop()}`}>
      <span className="mx-tool-icon">{item.icon}</span><span className="mx-tool-title">{item.title}</span><ArrowRight size={14} className="mx-tool-arrow" />
    </Link>)}
  </div>;
}
