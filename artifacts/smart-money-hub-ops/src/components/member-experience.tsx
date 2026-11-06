import { useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
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

function memberDisplayName(session: MemberSession) {
  const displayed = session.displayName.trim();
  if (displayed && !displayed.includes('@')) return displayed;
  const localPart = session.email.split('@')[0]?.split('+')[0] ?? '';
  const words = localPart.replace(/[._-]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  const derived = words.map((word) => `${word.charAt(0).toLocaleUpperCase()}${word.slice(1)}`).join(' ');
  return derived || 'Member';
}

function memberInitials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part.charAt(0).toLocaleUpperCase()).join('') || 'M';
}

function homeEventDate(event: MemberCalendarEvent) {
  const datePart = event.eventDate.slice(0, 10);
  const date = /^\d{4}-\d{2}-\d{2}$/.test(datePart) ? new Date(`${datePart}T00:00:00`) : new Date(event.eventDate);
  return Number.isNaN(date.getTime())
    ? ''
    : new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' }).format(date);
}

function homeEventTime(event: MemberCalendarEvent) {
  if (event.timeLabel && !/unverified|unavailable/i.test(event.timeLabel)) return event.timeLabel;
  if (!event.eventAt) return '';
  const instant = new Date(event.eventAt);
  if (Number.isNaN(instant.getTime())) return '';
  return `${new Intl.DateTimeFormat('en-NG', {
    timeZone: 'Africa/Lagos',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(instant)} WAT`;
}

export function MemberDashboardExperience({
  session,
  onSignOut,
  onSettings,
}: MemberDashboardExperienceProps) {
  const name = memberDisplayName(session);
  const firstName = name.split(/\s+/)[0] || 'Member';
  const calendarParams = useMemo<GetMemberCalendarParams>(() => ({ currency: 'USD' }), []);
  const calendar = useGetMemberCalendar(calendarParams, {
    query: { queryKey: getGetMemberCalendarQueryKey(calendarParams), staleTime: 60_000 },
  });
  const journalParams = useMemo<ListMemberJournalTradesParams>(() => ({}), []);
  const journal = useListMemberJournalTrades(journalParams, {
    query: { queryKey: getListMemberJournalTradesQueryKey(journalParams), staleTime: 30_000 },
  });
  const calendarEvents = calendar.data?.events.slice(0, 3) ?? [];
  const latestTrade = journal.data?.trades[0];

  return (
    <main className="member-experience mx-dashboard mx-member-home" data-testid="member-dashboard">
      <div className="mx-dashboard-shell">
        <header className="mx-dashboard-header mx-home-header">
          <Link className="mx-wordmark" href="/" aria-label="Smart Money Hub home">
            <img className="mx-wordmark-image" src={`${import.meta.env.BASE_URL}vayda-logo.png`} alt="" aria-hidden="true" />
            <span><strong>VAYDA</strong><small>SMART MONEY HUB</small></span>
          </Link>
          <nav className="mx-home-nav" aria-label="Member navigation">
            <Link className="is-current" href="/member/dashboard">Home</Link>
            <Link href="/member/calendar">Calendar</Link>
            <Link href="/member/journal">Journal</Link>
            <Link href="/member/coach">AI Coach</Link>
            {session.proSignalsAccess && <Link href="/member/pro-signals">PRO Signals</Link>}
          </nav>
          <div className="mx-header-actions">
            <button className="mx-home-account" type="button" onClick={onSettings} aria-label={`Account settings for ${name}`} title="Account settings">
              <span className="mx-home-avatar" aria-hidden="true">{memberInitials(name)}</span><span>{name}</span><Settings2 size={15} />
            </button>
            <button className="mx-header-icon-button" type="button" onClick={onSignOut} aria-label="Sign out" title="Sign out"><LogOut size={17} /></button>
          </div>
        </header>

        <section className="mx-home-hero" aria-label="Member welcome">
          <div className="mx-home-hero-copy">
            <div className="mx-home-kicker"><span className="mx-live-mark" /> PRIVATE MEMBER SPACE</div>
            <h1>Welcome, {firstName}.</h1>
            <p>Keep your learning, market context, and trade reviews in one clear workspace.</p>
            <div className="mx-home-hero-actions">
              <Link className="mx-button mx-button-gold" href="/member/coach" data-testid="button-chat-with-coach"><Sparkles size={15} /> Ask Vayda <ArrowRight size={14} /></Link>
              <Link className="mx-button mx-button-quiet" href="/member/calendar" data-testid="button-open-member-calendar"><CalendarDays size={15} /> View calendar</Link>
            </div>
            <div className="mx-home-status-row">
              <span><ShieldCheck size={14} /> Member access active</span>
              <span className={session.proSignalsAccess ? 'is-authorized' : 'is-unassigned'}><Radio size={14} /> PRO Signals {session.proSignalsAccess ? 'authorized' : 'not assigned'}</span>
            </div>
          </div>
          <aside className="mx-home-vayda-card" aria-label="Vayda educational coach">
            <div className="mx-home-vayda-art"><VaydaPortrait state="idle" /></div>
            <div className="mx-home-vayda-copy">
              <div className="mx-home-vayda-name"><Sparkles size={14} /> VAYDA <span>STUDY MODE</span></div>
              <p>Let’s focus on what you observed and what you want to understand next.</p>
              <small>Educational support · not a signal service</small>
              <a className="mx-button mx-button-quiet mx-home-telegram" href={publicSiteLinks.primaryCommunity} target="_blank" rel="noreferrer" data-testid="button-coach-telegram">
                <Send size={13} /> Chat with Coach on Telegram <ArrowUpRight size={12} />
              </a>
            </div>
          </aside>
        </section>

        <section className="mx-principle-banner" aria-label="Smart Money Hub philosophy">
          <span className="mx-card-kicker">OUR RULE</span>
          <p>NO CONFIRMATION, NO ENTRY.</p>
        </section>

        <section className="mx-tools-section" aria-labelledby="mx-tools-section-title">
          <div className="mx-tools-heading"><div><h2 id="mx-tools-section-title">Your workspace</h2><p>Choose a tool to continue.</p></div></div>
          <MemberFeatureDashboardLinks proSignalsAccess={session.proSignalsAccess} />
        </section>

        <section className="mx-home-overview" aria-label="Member account overview">
          <article className="mx-home-panel mx-home-calendar">
            <div className="mx-home-panel-head"><div><span className="mx-card-kicker">USD EVENTS</span><h2>Economic calendar</h2></div><Link className="mx-home-panel-link" href="/member/calendar">Open calendar <ArrowUpRight size={14} /></Link></div>
            {calendar.isLoading ? <div className="mx-home-loading" role="status">Loading calendar…</div>
              : calendar.isError ? <div className="mx-home-empty" role="alert"><span>Calendar data could not be loaded.</span><button type="button" onClick={() => void calendar.refetch()} disabled={calendar.isFetching}>Try again</button></div>
                : calendarEvents.length ? <div className="mx-home-event-list">{calendarEvents.map((event) => {
                  const time = homeEventTime(event);
                  return <article className="mx-home-event" key={event.id}>
                    <div className="mx-home-event-time"><strong>{homeEventDate(event) || 'Scheduled'}</strong>{time && <small><Clock3 size={12} /> {time}</small>}</div>
                    <div className="mx-home-event-title"><strong>{event.title}</strong><small>USD{event.impact !== 'unavailable' ? ` · ${event.impact} impact` : ''}</small></div>
                  </article>;
                })}</div>
                  : <div className="mx-home-empty"><CalendarDays size={17} /><span>No releases are listed in the current calendar feed.</span></div>}
          </article>

          <article className="mx-home-panel mx-home-journal">
            <div className="mx-home-panel-head"><div><span className="mx-card-kicker">YOUR RECORDS</span><h2>Trading journal</h2></div><Link className="mx-home-panel-link" href="/member/journal">Open journal <ArrowUpRight size={14} /></Link></div>
            {journal.isLoading ? <div className="mx-home-loading" role="status">Loading your journal…</div>
              : journal.isError ? <div className="mx-home-empty" role="alert"><span>Your journal could not be loaded.</span><button type="button" onClick={() => void journal.refetch()} disabled={journal.isFetching}>Try again</button></div>
                : <div className="mx-home-journal-content">
                  <div className="mx-home-journal-stats"><span><small>SAVED RECORDS</small><strong>{journal.data?.summary.totalTrades ?? 0}</strong></span><span><small>OPEN</small><strong>{journal.data?.summary.openTrades ?? 0}</strong></span></div>
                  {latestTrade ? <div className="mx-home-latest-trade"><span>RECENT ENTRY</span><strong>{latestTrade.instrument} <i className={`mx-home-outcome is-${latestTrade.outcome}`} /> {latestTrade.outcome}</strong><small>{prettyStamp(latestTrade.entryAt)}</small></div>
                    : <div className="mx-home-empty"><FileText size={17} /><span>No trade records saved yet.</span></div>}
                </div>}
          </article>

          <article className="mx-home-panel mx-home-pro">
            <div className="mx-home-panel-head"><div><span className="mx-card-kicker">SEPARATE ENTITLEMENT</span><h2>PRO Signals</h2></div><Radio size={19} aria-hidden="true" /></div>
            <p>{session.proSignalsAccess ? 'This account is authorized to view the PRO Signals area.' : 'PRO access is not assigned to this account. Website registration does not grant signal access.'}</p>
            {session.proSignalsAccess
              ? <a className="mx-button mx-button-gold" href={publicSiteLinks.proSignalsAssistant} target="_blank" rel="noreferrer" data-testid="button-open-pro-signals-bot">Open PRO Signals Bot <ArrowUpRight size={14} /></a>
              : <Link className="mx-button mx-button-quiet" href="/member/pro-signals" data-testid="button-review-pro-access">Review access requirements <ArrowRight size={14} /></Link>}
          </article>

          <article className="mx-home-panel mx-home-learning">
            <div className="mx-home-panel-head"><div><span className="mx-card-kicker">LEARNING</span><h2>Learning progress</h2></div><Activity size={19} aria-hidden="true" /></div>
            <p>Lesson completion is not tracked in this dashboard, so no progress percentage is shown.</p>
            <Link className="mx-button mx-button-quiet" href="/education" data-testid="button-explore-trading-academy">Explore Trading Academy <ArrowRight size={14} /></Link>
          </article>
        </section>

        <footer className="mx-dashboard-footer">
          <span>VAYDA SMART MONEY HUB <i /> PROCESS OVER PREDICTION</span><span>Trading involves risk. Education is not financial advice.</span>
        </footer>
      </div>
    </main>
  );
}

type VaydaState = 'idle' | 'blinking' | 'breathing' | 'listening' | 'thinking' | 'speaking';

function VaydaPortrait({ state = 'idle', compact = false }: { state?: VaydaState; compact?: boolean }) {
  const id = useId().replace(/:/g, '');
  return <span className={`mx-vayda-portrait state-${state}${compact ? ' is-compact' : ''}`} aria-hidden="true">
    <span className="mx-vayda-glow" />
    <span className="mx-vayda-orbit mx-vayda-orbit-one" />
    <span className="mx-vayda-orbit mx-vayda-orbit-two" />
    <svg className="mx-vayda-face" viewBox="0 0 220 250" fill="none">
      <defs>
        <linearGradient id={`${id}-hair`} x1="54" y1="42" x2="174" y2="140" gradientUnits="userSpaceOnUse"><stop stopColor="#C59B49" /><stop offset="1" stopColor="#293448" /></linearGradient>
        <linearGradient id={`${id}-skin`} x1="78" y1="76" x2="155" y2="166" gradientUnits="userSpaceOnUse"><stop stopColor="#F2D9BE" /><stop offset="1" stopColor="#C79B7A" /></linearGradient>
        <linearGradient id={`${id}-jacket`} x1="53" y1="177" x2="172" y2="245" gradientUnits="userSpaceOnUse"><stop stopColor="#344158" /><stop offset="1" stopColor="#C59B49" /></linearGradient>
      </defs>
      <path d="M28 239c7-38 34-61 82-61s75 23 82 61" fill={`url(#${id}-jacket)`} />
      <path d="M91 167h38v28c-5 12-33 12-38 0v-28Z" fill="#C7B5E9" />
      <path d="m79 189 31 28 31-28" stroke="#E8D7B0" strokeWidth="4" strokeLinecap="round" />
      <path d="M60 97c0-37 23-63 53-63 32 0 55 24 55 63v26c0 34-24 60-55 60-31 0-53-26-53-60V97Z" fill={`url(#${id}-skin)`} />
      <path d="M53 107c-9-42 7-78 36-91 35-16 84 1 91 42 4 20-2 40-6 49-7-22-17-39-33-49-22 19-50 27-85 25l-3 24Z" fill={`url(#${id}-hair)`} />
      <path d="M56 113c-8-5-13 1-10 14 2 9 7 14 14 14m101-28c8-5 13 1 10 14-2 9-7 14-14 14" stroke="#C59B49" strokeWidth="4" strokeLinecap="round" />
      <path className="mx-vayda-eye mx-vayda-eye-left" d="M78 118c5-5 12-5 17 0" stroke="#1E2755" strokeWidth="4" strokeLinecap="round" />
      <path className="mx-vayda-eye mx-vayda-eye-right" d="M126 118c5-5 12-5 17 0" stroke="#1E2755" strokeWidth="4" strokeLinecap="round" />
      <path d="M109 123v15" stroke="#8A71B8" strokeWidth="3" strokeLinecap="round" />
      <path className="mx-vayda-mouth" d="M95 150c8 9 21 9 29 0" stroke="#725A9D" strokeWidth="3.5" strokeLinecap="round" />
      <path d="M55 126h8m102 0h8" stroke="#20B889" strokeWidth="4" strokeLinecap="round" />
      <circle cx="78" cy="139" r="6" fill="#E45C65" opacity=".18" /><circle cx="143" cy="139" r="6" fill="#E45C65" opacity=".18" />
      <path d="M83 207h54" stroke="#E0D8FF" strokeOpacity=".55" strokeWidth="2" strokeLinecap="round" />
    </svg>
    <span className="mx-vayda-speaking-bars"><i /><i /><i /><i /><i /></span>
    <span className="mx-vayda-thinking-dots"><i /><i /><i /></span>
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
  const [inputFocused, setInputFocused] = useState(false);
  const [topic, setTopic] = useState('');
  const [responseDisclaimer, setResponseDisclaimer] = useState('');
  const [typingIndex, setTypingIndex] = useState<number | null>(null);
  const [typedLength, setTypedLength] = useState(0);
  const threadRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const assistantBusy = coach.isPending || typingIndex !== null;
  const vaydaState: VaydaState = coach.isPending ? 'thinking' : typingIndex !== null ? 'speaking' : inputFocused ? 'listening' : 'idle';
  const vaydaStateLabel = { idle: 'Ready', blinking: 'Ready', breathing: 'Ready', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking' }[vaydaState];

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
    setError(''); setMessage(''); setInputFocused(false);
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
  const clear = () => { setHistory([]); setTopic(''); setResponseDisclaimer(''); setError(''); setMessage(''); setTypingIndex(null); setTypedLength(0); setInputFocused(false); stickToBottomRef.current = true; };
  return <FeatureShell active="/member/coach" eyebrow="MEMBER CHAT" title="AI Coach" intro="Ask about a trading concept or reflect on your decision process.">
    <section className="mx-chat-workspace" aria-label="Educational Coach conversation" data-testid="member-coach-chat">
      <header className="mx-conversation-head">
        <div className="mx-conversation-title">
          <VaydaPortrait state={vaydaState} compact />
          <div><strong>VAYDA Coach</strong><small>Learning mode · Temporary chat · {vaydaStateLabel}</small></div>
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
          <span className="mx-chat-welcome-avatar"><VaydaPortrait state="idle" compact /></span>
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
              {line.role === 'assistant' && <span className="mx-chat-message-avatar"><VaydaPortrait state={isTyping ? 'speaking' : 'idle'} compact /></span>}
              <span>{line.role === 'user' ? 'You' : 'VAYDA Coach'}</span>
            </div>
            <div className="mx-chat-bubble"><p>{visibleText}{isTyping && <span className="mx-chat-caret" aria-hidden="true" />}</p></div>
          </article>;
        })}
        {assistantBusy && <div className="mx-chat-pending" role="status" aria-label="Coach is typing">
          <span className="mx-chat-message-avatar"><VaydaPortrait state={coach.isPending ? 'thinking' : 'speaking'} compact /></span>
          <div className="mx-chat-pending-bubble"><span>VAYDA Coach is typing</span><i /><i /><i /></div>
        </div>}
      </div>
      {responseDisclaimer && <p className="mx-response-disclaimer" role="note">{responseDisclaimer}</p>}
      {error && <div className="mx-inline-error" role="alert">{error}</div>}
      <form className="mx-chat-form" onSubmit={(event) => void send(event)}>
        <label className="mx-visually-hidden" htmlFor="coach-message">Message the AI Coach</label>
        <div className="mx-chat-input-wrap">
          <textarea id="coach-message" value={message} onChange={(event) => setMessage(event.currentTarget.value)} onFocus={() => setInputFocused(true)} onBlur={() => setInputFocused(false)} rows={2} maxLength={1200} placeholder="Message the Coach…" required disabled={assistantBusy} data-testid="input-coach-message" />
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
    { href: '/member/calendar', title: 'Economic calendar', detail: 'Verified USD events', icon: <CalendarDays size={18} /> },
    { href: '/member/journal', title: 'Trading journal', detail: 'Your saved decisions', icon: <FileText size={18} /> },
    { href: '/member/coach', title: 'Ask Vayda', detail: 'Learn and reflect', icon: <MessageCircle size={18} /> },
    { href: '/education', title: 'Trading Academy', detail: 'Explore the curriculum', icon: <Sparkles size={18} /> },
    { href: '/market-analysis', title: 'Market Analysis', detail: 'Read market context', icon: <Activity size={18} /> },
    ...(proSignalsAccess ? [{ href: '/member/pro-signals', title: 'PRO Signals', detail: 'Authorized member feed', icon: <Radio size={18} /> }] : []),
  ];
  return <div className="mx-feature-dashboard-links">
    {quickLinks.map((item) => <Link className="mx-tool-card" href={item.href} key={item.href} aria-label={item.title} data-testid={`card-feature-${item.href.split('/').pop()}`}>
      <span className="mx-tool-icon">{item.icon}</span><span className="mx-tool-copy"><strong>{item.title}</strong><small>{item.detail}</small></span><ArrowRight size={14} className="mx-tool-arrow" />
    </Link>)}
  </div>;
}
