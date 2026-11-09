import { useEffect, useRef, useState, type ReactNode, type FormEvent, type ChangeEvent } from 'react';
import OperationsApp from './App';
import PublicSite from './public-site/PublicSite';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import {
  getGetPortalSessionQueryKey, getGetPortalDashboardQueryKey, getListPortalCasesQueryKey,
  getListPortalStaffQueryKey, usePortalLogin, useGetPortalSession,
  useListPortalCases, useListPortalStaff,
  usePortalLogout, useCreatePortalStaff,
  useUpdatePortalStaff, useChangePortalPassword,
  useListStaffTasks, useCreateStaffTask, useUpdateStaffTaskStatus, useListStaffTeams,
  useCreateStaffTeam, useSetStaffTeamMembers,
  useListStaffTaskNotifications, useMarkStaffTaskNotificationRead,
  getListStaffTaskNotificationsQueryKey, getListStaffTasksQueryKey,
  useListStaffReportNotifications, useMarkStaffReportNotificationRead,
  getListStaffReportNotificationsQueryKey,
   getGetMemberSessionQueryKey, getMemberSession,
   useGetMemberSession, useLinkMemberTelegram,
  useUpdateStaffTask, useListStaffActivityReports, useSubmitStaffActivityReport,
  useReviewStaffActivityReport, useGetStaffPerformance,
  getListStaffActivityReportsQueryKey, getGetStaffPerformanceQueryKey, getListStaffTeamsQueryKey,
  getGetPortalCommandCenterQueryKey,
  useGetPortalCommandCenter,
} from '@workspace/api-client-react';
import type { MemberSession, PortalSession, PortalStaff, StaffPerformanceRow, StaffTask, StaffTeam } from '@workspace/api-client-react';
import {
  Activity, ArrowLeft, ArrowUpRight, Check, CheckCircle2, ChevronLeft, ChevronRight, CircleHelp,
  Bell, Eye, EyeOff, FileText, KeyRound, LockKeyhole, LogOut, MessageSquareText,
  Plus, Search, ShieldCheck, Users, X, Gauge, RefreshCw, Radio, CircleAlert, Database, History, Bot, BrainCircuit, Clapperboard,
} from 'lucide-react';
import { Link, Route, Switch, Router as WouterRouter, useLocation, useParams } from 'wouter';
import { ClerkProvider, UserProfile, useAuth, useClerk, useSignIn, useSignUp } from '@clerk/react';
import { publishableKeyFromHost } from '@clerk/react/internal';
import { shadcn } from '@clerk/themes';
import { useToast } from '@/hooks/use-toast';
import NotFound from '@/pages/not-found';
import ProAccessReview from '@/components/pro-access-review';
import {
  MemberCalendarExperience,
  MemberCoachExperience,
  MemberDashboardExperience,
  MemberJournalExperience,
  MemberProSignalsAccessUnavailable,
  MemberProSignalsExperience,
  MemberSignupExperience,
} from '@/components/member-experience';
import { MemberLearningExperience } from '@/components/member-learning';
import { MemberCourseVideoLibrary, OwnerMemberCourseVideos } from '@/components/member-course-videos';
import { MemberNotificationsExperience } from '@/components/member-notifications';
import StaffAnnouncements from '@/components/staff-announcements';
import EducationVideos from '@/pages/education-videos';
import ChannelHistory from '@/pages/channel-history';
import TradeManagement from '@/pages/trades';
import Signals from '@/pages/signals';
import BotControl, { BotConnections } from '@/pages/bot-control';
import MemberAccessPage from '@/pages/member-access';
import OwnerMindMap from '@/pages/owner-mind-map';
import { trackEvent } from '@/lib/analytics';
import { SupportInbox } from './SupportInbox';
import { publicSiteLinks } from './public-site/config';
const brandLogoUrl = `${import.meta.env.BASE_URL}vayda-logo.png`;
const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');
const clerkPubKey = publishableKeyFromHost(
  window.location.hostname,
  import.meta.env.VITE_CLERK_PUBLISHABLE_KEY,
);
const clerkProxyUrl = import.meta.env.VITE_CLERK_PROXY_URL;

if (!clerkPubKey) throw new Error('Missing VITE_CLERK_PUBLISHABLE_KEY for member sign-in.');

function stripClerkBase(path: string): string {
  return basePath && path.startsWith(basePath) ? path.slice(basePath.length) || '/' : path;
}

const clerkAppearance = {
  theme: shadcn,
  cssLayerName: 'clerk',
  options: {
    logoPlacement: 'inside' as const,
    logoLinkUrl: basePath || '/',
  logoImageUrl: `${window.location.origin}${basePath}/vayda-logo.png`,
  },
  variables: {
    colorPrimary: '#d2b978',
    colorForeground: '#eeeae0',
    colorMutedForeground: '#a3aaa1',
    colorDanger: '#e7a99d',
    colorBackground: '#171e1c',
    colorInput: '#121816',
    colorInputForeground: '#eeeae0',
    colorNeutral: '#eeeae0',
    fontFamily: "'DM Sans', sans-serif",
    borderRadius: '2px',
  },
  elements: {
    rootBox: 'w-full flex justify-center',
    cardBox: 'bg-[#171e1c] rounded-none w-[480px] max-w-full overflow-hidden border border-[#383d35]',
    card: '!shadow-none !border-0 !bg-transparent !rounded-none',
    footer: '!shadow-none !border-0 !bg-transparent !rounded-none',
    headerTitle: 'text-[#eeeae0] font-semibold',
    headerSubtitle: 'text-[#a3aaa1]',
    socialButtonsBlockButtonText: 'text-[#eeeae0]',
    formFieldLabel: 'text-[#c5c9bf]',
    footerActionLink: 'text-[#e7d39b] font-semibold',
    footerActionText: 'text-[#a3aaa1]',
    dividerText: 'text-[#a3aaa1]',
    identityPreviewEditButton: 'text-[#e7d39b]',
    formFieldSuccessText: 'text-[#8ab39a]',
    alertText: 'text-[#e7a99d]',
    logoBox: 'mb-2',
    logoImage: 'max-h-12',
    socialButtonsBlockButton: 'border-[#4b5149] bg-[#121816]',
    formButtonPrimary: 'font-semibold',
    formFieldInput: 'text-[#eeeae0] bg-[#121816] border-[#4b5149]',
    footerAction: 'text-[#a3aaa1]',
    dividerLine: 'bg-[#383d35]',
    alert: 'bg-[#3b201d] border-[#793a31]',
    otpCodeFieldInput: 'text-[#eeeae0] bg-[#121816] border-[#4b5149]',
    formFieldRow: 'mb-4',
    main: 'gap-5',
  },
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Reuse recently loaded page data while navigating; active polling and
      // explicit mutation invalidations still keep shared data current.
      staleTime: 15_000,
      gcTime: 5 * 60_000,
    },
  },
});
const sessionKey = getGetPortalSessionQueryKey();

function errMessage(error: unknown, fallback = 'Something went wrong. Please try again.') {
  if (error && typeof error === 'object') {
    const candidate = error as { message?: string; status?: number };
    if (candidate.status === 401 || candidate.status === 403) return 'Your access is not authorized. Please sign in again or contact an administrator.';
    if (candidate.message) return candidate.message;
  }
  return fallback;
}

function taskStatusLabel(status: string) {
  if (status === 'assigned') return 'Assigned';
  if (status === 'accepted' || status === 'in_progress') return 'In Progress';
  if (status === 'submitted_for_review') return 'Submitted';
  if (status === 'approved') return 'Completed';
  if (status === 'revision_requested') return 'Changes Requested';
  if (status === 'cancelled') return 'Cancelled';
  return status.replaceAll('_', ' ');
}

function taskNoticeLabel(type: string) {
  if (type === 'submitted_for_review') return 'Work submitted for review';
  if (type === 'approved') return 'Task completed';
  if (type === 'revision_requested') return 'Changes requested';
  if (type === 'cancelled') return 'Task cancelled';
  return 'Task update';
}
function isUnauthorized(error: unknown) {
  return Boolean(error && typeof error === 'object' && [401, 403].includes((error as { status?: number }).status ?? 0));
}
const memberFeaturePaths = new Set(['/member/dashboard', '/member/learning', '/member/videos', '/member/calendar', '/member/journal', '/member/coach', '/member/pro-signals', '/member/settings']);
function safeMemberReturnTo(value: string | null | undefined) {
  return value && memberFeaturePaths.has(value) ? value : null;
}
function initials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? '').join('');
}
function prettyDate(value?: string | null) {
  if (!value) return 'Not yet';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}
function statusLabel(status: string) {
  return ({ open: 'Open', reply_sending: 'Sending reply', reply_uncertain: 'Delivery uncertain', replied: 'Replied', closed: 'Closed', queued: 'Queued', sending: 'Sending', sent: 'Sent', uncertain: 'Uncertain', failed: 'Failed' } as Record<string, string>)[status] ?? status;
}
function Status({ value }: { value: string }) {
  return <span className={`status status-${value}`} data-testid={`status-${value}`}>{statusLabel(value)}</span>;
}
function Brand() {
  return <div className="brand-mark"><img className="brand-symbol" src={brandLogoUrl} alt="" aria-hidden="true" /><span><span className="brand-name">VAYDA</span><span className="brand-sub">SMART MONEY HUB</span></span></div>;
}
function Empty({ title, children, icon = <MessageSquareText size={20} /> }: { title: string; children: ReactNode; icon?: ReactNode }) {
  return <div className="empty-state" data-testid="state-empty"><div className="empty-mark">{icon}</div><h3>{title}</h3><p>{children}</p></div>;
}
function ErrorState({ error, retry }: { error: unknown; retry: () => void }) {
  return <div className="empty-state" data-testid="state-error"><div className="empty-mark"><CircleHelp size={20} /></div><h3>We could not load this view</h3><p>{errMessage(error)}</p><button className="btn btn-outline" onClick={retry} style={{ marginTop: 16 }}>Try again</button></div>;
}
function LoadingRows() {
  return <div className="loading-list" aria-label="Loading cases" data-testid="state-loading">{[0, 1, 2, 3].map((item) => <div className="loading-row" key={item}><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>)}</div>;
}

function isConnectionFailure(failure: unknown): boolean {
  return failure instanceof TypeError
    || (failure instanceof Error && /load failed|failed to fetch|network error|network request failed/i.test(failure.message));
}

function clerkErrorCode(failure: unknown): string | undefined {
  if (!failure || typeof failure !== 'object') return undefined;
  const error = failure as { code?: unknown; errors?: unknown };
  if (typeof error.code === 'string') return error.code;
  if (!Array.isArray(error.errors)) return undefined;
  const first = error.errors.find((item) => item && typeof item === 'object') as { code?: unknown } | undefined;
  return typeof first?.code === 'string' ? first.code : undefined;
}

function passwordRecoveryErrorMessage(failure: unknown): string {
  if (isConnectionFailure(failure)) {
    return 'We could not connect to the recovery service. Please try again.';
  }
  const code = clerkErrorCode(failure);
  if (import.meta.env.DEV && code) {
    console.warn('Clerk password recovery error code:', code);
  }
  if (code && /(strategy|password|reset).*(not_enabled|disabled)|(not_enabled|disabled).*(strategy|password|reset)/i.test(code)) {
    return 'Member email recovery is not enabled in Development. This option cannot reset an Owner Portal password.';
  }
  if (code && /(too_many|rate_limit|request_throttled)/i.test(code)) {
    return 'Too many recovery requests. Wait a few minutes, then try again.';
  }
  return 'Member password recovery could not be started. Confirm this is a registered member account. Owner Portal passwords use a separate Development reset and cannot be changed here.';
}

function Login() {
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [memberLoginStep, setMemberLoginStep] = useState<'credentials' | 'email-code' | 'mfa-email-code'>('credentials');
  const [memberLoginCode, setMemberLoginCode] = useState('');
  const [recoveryStep, setRecoveryStep] = useState<'closed' | 'code' | 'new-password'>('closed');
  const [recoveryCode, setRecoveryCode] = useState('');
  const [newMemberPassword, setNewMemberPassword] = useState('');
  const [, navigate] = useLocation();
  const returnTo = safeMemberReturnTo(new URLSearchParams(window.location.search).get('returnTo'));
  const client = useQueryClient();
  const login = usePortalLogin();
  const portalLogout = usePortalLogout();
  const clerk = useClerk();
  const { isLoaded: clerkLoaded, isSignedIn } = useAuth();
  const { signIn } = useSignIn();
  const staffSession = useGetPortalSession({
    query: { queryKey: sessionKey, refetchOnMount: 'always', retry: false, staleTime: 0 },
  });
  const memberSession = useGetMemberSession({
    query: {
      queryKey: getGetMemberSessionQueryKey(),
      enabled: clerkLoaded && isSignedIn === true,
      retry: false,
    },
  });
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (staffSession.data) {
      navigate(staffSession.data.mustChangePassword ? '/account/password' : staffSession.data.dashboardPath);
    } else if (memberSession.data?.learningDashboard) {
      navigate(returnTo ?? memberSession.data.dashboardPath);
    } else if (memberSession.data) {
      setError('This account does not currently have a member learning dashboard entitlement.');
    }
  }, [staffSession.data, memberSession.data, navigate, returnTo]);

  const finishMemberSignIn = async () => {
    await signIn.finalize();
    const member = await getMemberSession();
    if (!member.learningDashboard) {
      throw Object.assign(new Error('This account does not currently have a member learning dashboard entitlement.'), { status: 403 });
    }
    client.setQueryData(getGetMemberSessionQueryKey(), member);
    await client.invalidateQueries({ queryKey: getGetMemberSessionQueryKey() });
    navigate(returnTo ?? member.dashboardPath);
  };

  const sendMemberSignInCode = async (secondFactor = false) => {
    const result = secondFactor
      ? await signIn.mfa.sendEmailCode()
      : await signIn.emailCode.sendCode();
    if (result.error) {
      throw new Error('We could not send the email verification code. Try again or use the member password recovery option.');
    }
    setMemberLoginCode('');
    setMemberLoginStep(secondFactor ? 'mfa-email-code' : 'email-code');
    setNotice('A verification code was sent to the email on your member account.');
  };

  const completeMemberAccess = async () => {
    try {
      await finishMemberSignIn();
    } catch (failure) {
      await clerk.signOut().catch(() => undefined);
      const status = (failure as { status?: number })?.status;
      if (status === 403) {
        throw new Error('Sign-in succeeded, but this account is not currently eligible for the member dashboard. Verify the email used at registration, then contact the owner if access is still unavailable.');
      }
      throw new Error('Sign-in succeeded, but member access could not be checked. Please try again.');
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setNotice('');
    setBusy(true);
    let staffSignInUnavailable = false;
    try {
      if (isSignedIn) {
        await clerk.signOut();
        client.clear();
      }
      try {
        const session = await login.mutateAsync({ data: { identifier: identifier.trim(), password } });
        trackEvent('staff_login_succeeded', { password_change_required: session.mustChangePassword });
        client.setQueryData(sessionKey, session);
        await client.invalidateQueries({ queryKey: sessionKey });
        navigate(session.mustChangePassword ? '/account/password' : session.dashboardPath);
        return;
      } catch (staffFailure) {
        const status = (staffFailure as { status?: number })?.status;
        if (status !== 400 && status !== 401) {
          if (isConnectionFailure(staffFailure) || (typeof status === 'number' && status >= 500)) {
            staffSignInUnavailable = true;
          } else {
            throw staffFailure;
          }
        }
      }

      try {
        await portalLogout.mutateAsync();
      } catch {
        // No existing staff session is expected for member sign-in.
      }
      if (!clerkLoaded) throw new Error('Member sign-in is still loading. Try again in a moment.');
      const attempt = await signIn.password({ identifier: identifier.trim(), password }).catch((memberFailure) => {
        if (isConnectionFailure(memberFailure)) {
          throw new Error('We could not connect to sign-in. Check your connection and try again.');
        }
        throw memberFailure;
      });
      if (attempt.error) {
        if (staffSignInUnavailable) {
          throw new Error('Sign-in is temporarily unavailable. Please try again shortly.');
        }
        throw new Error('The email or password is incorrect. Use the email connected to your account, or choose “Forgot password?”');
      }
      if (signIn.status === 'needs_first_factor') {
        if (signIn.supportedFirstFactors.some((factor) => factor.strategy === 'email_code')) {
          await sendMemberSignInCode();
          return;
        }
        throw new Error('This account needs another verification step. Check your email or contact support.');
      }
      if (signIn.status === 'needs_second_factor') {
        if (signIn.supportedSecondFactors.some((factor) => factor.strategy === 'email_code')) {
          await sendMemberSignInCode(true);
          return;
        }
        throw new Error('This account requires an additional security check. Contact support for help.');
      }
      if (signIn.status !== 'complete') {
        throw new Error('This account needs another verification step. Check your account email and try again.');
      }
      await completeMemberAccess();
    } catch (failure) {
      setError(isConnectionFailure(failure)
        ? 'We could not connect to sign-in. Check your connection and try again.'
        : failure instanceof Error ? failure.message : 'Sign-in failed. Check your details and try again.');
    } finally {
      setBusy(false);
    }
  };

  const verifyMemberSignInCode = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const result = memberLoginStep === 'mfa-email-code'
        ? await signIn.mfa.verifyEmailCode({ code: memberLoginCode.trim() })
        : await signIn.emailCode.verifyCode({ code: memberLoginCode.trim() });
      if (result.error) {
        setError('That code could not be verified. Check it and try again, or request a new code.');
        return;
      }
      if (signIn.status !== 'complete') {
        setError('The code was accepted, but another security step is still required. Contact the owner for help.');
        return;
      }
      await completeMemberAccess();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Member sign-in could not be completed. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const resendMemberSignInCode = async () => {
    setError('');
    setNotice('');
    setBusy(true);
    try {
      await sendMemberSignInCode(memberLoginStep === 'mfa-email-code');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'A new verification code could not be sent.');
    } finally {
      setBusy(false);
    }
  };

  const startRecovery = async () => {
    setError('');
    setNotice('');
    if (!identifier.trim()) {
      setError('Enter your account email or username first.');
      return;
    }
    if (!clerkLoaded) {
      setError('Member password recovery is still loading. Try again in a moment.');
      return;
    }
    setBusy(true);
    try {
      const created = await signIn.create({ identifier: identifier.trim() });
      if (created.error) throw created.error;
      const sent = await signIn.resetPasswordEmailCode.sendCode();
      if (sent.error) throw sent.error;
      setRecoveryStep('code');
      setNotice('If password recovery is available for this account, a code has been sent to its registered email.');
    } catch (failure) {
      setRecoveryStep('closed');
      setRecoveryCode('');
      setError(passwordRecoveryErrorMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const resendRecoveryCode = async () => {
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const sent = await signIn.resetPasswordEmailCode.sendCode();
      if (sent.error) throw sent.error;
      setNotice('If password recovery is available for this account, a new code has been sent.');
    } catch (failure) {
      setError(passwordRecoveryErrorMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const verifyRecoveryCode = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const result = await signIn.resetPasswordEmailCode.verifyCode({ code: recoveryCode.trim() });
      if (result.error) throw result.error;
      setRecoveryStep('new-password');
    } catch {
      setError('That recovery code could not be verified. Request a new code and try again.');
    } finally {
      setBusy(false);
    }
  };

  const submitMemberPassword = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    if (newMemberPassword.length < 12) {
      setError('Use at least 12 characters for the new password.');
      return;
    }
    setBusy(true);
    try {
      const result = await signIn.resetPasswordEmailCode.submitPassword({ password: newMemberPassword });
      if (result.error) throw result.error;
      await finishMemberSignIn();
    } catch (failure) {
      await clerk.signOut().catch(() => undefined);
      setError(failure instanceof Error ? failure.message : 'The password could not be reset. Request a new code and try again.');
    } finally {
      setBusy(false);
    }
  };

  return <main className="login-screen">
    <section className="login-aside">
      <div className="login-brand"><Brand /></div>
      <div className="login-copy"><div className="eyebrow" style={{ color: '#d5b56f' }}>SMART MONEY HUB</div><h1>Welcome back.</h1><p>Sign in to continue to your account.</p></div>
    </section>
    <section className="login-panel"><div className="login-panel-content">
      <button type="button" className="login-home-link" onClick={() => navigate('/')} data-testid="button-login-home">
        <ArrowLeft size={15}/> Back to public home
      </button>
      <div className="login-form">
      <div className="eyebrow">WELCOME BACK</div><h2>Sign in</h2><p>Enter the email or username and password connected to your account.</p>
      {error && <div className="notice notice-error" role="alert" data-testid="status-login-error">{error}</div>}
      {notice && <div className="notice notice-info" role="status" data-testid="status-login-notice">{notice}</div>}
      {memberLoginStep !== 'credentials' ? <form onSubmit={verifyMemberSignInCode}>
        <div className="form-field"><label className="form-label" htmlFor="member-signin-code">Email verification code</label><input id="member-signin-code" className="field-input" inputMode="numeric" autoComplete="one-time-code" required maxLength={12} value={memberLoginCode} onChange={(event) => setMemberLoginCode(event.target.value)} /></div>
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Verifying…' : 'Verify and continue'} <ChevronRight size={15} /></button>
        <button className="login-link-button" type="button" onClick={() => void resendMemberSignInCode()} disabled={busy}>Resend code</button>
        <button className="login-link-button" type="button" onClick={() => { setMemberLoginStep('credentials'); setMemberLoginCode(''); setNotice(''); }} disabled={busy}>Back to sign in</button>
      </form> : recoveryStep === 'closed' ? <form onSubmit={submit}>
        <div className="form-field"><label className="form-label" htmlFor="login-identifier">Email or username</label><input id="login-identifier" className="field-input" type="text" autoComplete="username" required maxLength={254} value={identifier} onChange={(event) => setIdentifier(event.target.value)} data-testid="input-identifier" /></div>
        <div className="form-field"><label className="form-label" htmlFor="login-password">Password</label><div className="password-wrap"><input id="login-password" className="field-input" type={showPassword ? 'text' : 'password'} autoComplete="current-password" required maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} data-testid="input-password" /><button type="button" className="password-toggle" aria-label={showPassword ? 'Hide password' : 'Show password'} onClick={() => setShowPassword(!showPassword)} data-testid="button-toggle-password">{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button></div></div>
        <button className="btn btn-primary" type="submit" disabled={busy || login.isPending} data-testid="button-sign-in">{busy ? 'Signing in…' : 'Sign in'} <ChevronRight size={15} /></button>
        <button className="login-link-button" type="button" onClick={() => void startRecovery()} disabled={busy} data-testid="button-forgot-member-password">Forgot member password?</button>
        <p className="login-recovery-hint">For member accounts only. This does not reset an Owner Portal password.</p>
      </form> : recoveryStep === 'code' ? <form onSubmit={verifyRecoveryCode}>
        <div className="form-field"><label className="form-label" htmlFor="member-reset-code">Email recovery code</label><input id="member-reset-code" className="field-input" inputMode="numeric" autoComplete="one-time-code" required maxLength={12} value={recoveryCode} onChange={(event) => setRecoveryCode(event.target.value)} /></div>
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Checking code…' : 'Verify code'} <ChevronRight size={15} /></button>
        <button className="login-link-button" type="button" onClick={() => void resendRecoveryCode()} disabled={busy}>Resend recovery code</button>
        <button className="login-link-button" type="button" onClick={() => { setRecoveryStep('closed'); setRecoveryCode(''); setNewMemberPassword(''); setNotice(''); setError(''); }} disabled={busy}>Back to sign in</button>
      </form> : <form onSubmit={submitMemberPassword}>
        <div className="form-field"><label className="form-label" htmlFor="member-new-password">New password</label><input id="member-new-password" className="field-input" type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={newMemberPassword} onChange={(event) => setNewMemberPassword(event.target.value)} /></div>
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Updating password…' : 'Update password'} <ChevronRight size={15} /></button>
        <button className="login-link-button" type="button" onClick={() => setRecoveryStep('closed')}>Back to sign in</button>
      </form>}
      <div className="login-note" data-testid="status-member-signup-open">
        New to Smart Money Hub?{' '}
        <button className="login-link-button" type="button" onClick={() => navigate('/sign-up')} data-testid="button-login-create-account">
          Create an account
        </button>
      </div>
      </div>
    </div></section>
  </main>;
}

type TelegramWidgetUser = {
  id: number;
  auth_date: number;
  hash: string;
  first_name?: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
};

declare global {
  interface Window {
    onTelegramMemberAuth?: (user: TelegramWidgetUser) => void;
  }
}

function TelegramLinkWidget({ session }: { session: MemberSession }) {
  const client = useQueryClient();
  const link = useLinkMemberTelegram();
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const widgetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (session.telegramLinked || !widgetRef.current) return;
    const handleTelegramAuth = async (user: TelegramWidgetUser) => {
      setError('');
      setNotice('');
      try {
        const result = await link.mutateAsync({
          data: {
            id: String(user.id),
            authDate: user.auth_date,
            hash: user.hash,
            firstName: user.first_name,
            lastName: user.last_name,
            username: user.username,
            photoUrl: user.photo_url,
          },
        });
        const current = client.getQueryData<MemberSession>(getGetMemberSessionQueryKey());
        if (current) {
          client.setQueryData<MemberSession>(getGetMemberSessionQueryKey(), {
            ...current,
            telegramLinked: result.linked,
            telegramUsername: result.telegramUsername,
          });
        }
        setNotice('Your Telegram identity is linked. This does not grant PRO Signals access.');
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : 'Telegram identity could not be linked.');
      }
    };
    window.onTelegramMemberAuth = handleTelegramAuth;
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://telegram.org/js/telegram-widget.js?22';
    script.setAttribute('data-telegram-login', import.meta.env.DEV ? 'SMHProSignalsassistantbot' : 'SmartMoneyHubSignalsBot');
    script.setAttribute('data-size', 'large');
    script.setAttribute('data-userpic', 'false');
    script.setAttribute('data-onauth', 'onTelegramMemberAuth(user)');
    widgetRef.current.replaceChildren(script);
    return () => {
      if (window.onTelegramMemberAuth === handleTelegramAuth) delete window.onTelegramMemberAuth;
      script.remove();
    };
  }, [session.telegramLinked, client, link.mutateAsync]);

  return <div className="member-telegram-link">
    {session.telegramLinked
      ? <p>Linked Telegram account: <strong>{session.telegramUsername ? `@${session.telegramUsername}` : 'identity verified'}</strong></p>
      : <><p>Verify your Telegram identity with Telegram’s signed login widget. A username alone is not accepted as proof.</p><div ref={widgetRef} data-testid="telegram-link-widget" /></>}
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    {notice && <div className="notice notice-info" role="status">{notice}</div>}
    <a className="mx-button mx-button-quiet mx-telegram-bot-button" href={publicSiteLinks.proSignalsAssistant} target="_blank" rel="noreferrer">Open PRO Signals bot <ArrowUpRight size={14} /></a>
  </div>;
}

function MemberDashboardPage({ session }: { session: MemberSession }) {
  const clerk = useClerk();
  const portalLogout = usePortalLogout();
  const client = useQueryClient();
  const [, navigate] = useLocation();

  const signOut = async () => {
    try {
      await portalLogout.mutateAsync();
    } catch {
      // A member normally has no staff session to clear.
    }
    await clerk.signOut({ redirectUrl: `${basePath}/` });
    await client.clear();
    navigate('/');
  };

  return <MemberDashboardExperience
    session={session}
    onSignOut={() => void signOut()}
    onSettings={() => navigate('/member/settings')}
  />;
}

function MemberRoot() {
  const [location, navigate] = useLocation();
  const { isLoaded, isSignedIn } = useAuth();
  const clerk = useClerk();
  const staff = useGetPortalSession({ query: { queryKey: sessionKey, retry: false, staleTime: 0 } });
  const member = useGetMemberSession({
    query: { queryKey: getGetMemberSessionQueryKey(), enabled: isLoaded && isSignedIn === true, retry: false },
  });

  useEffect(() => {
    if (staff.data) navigate(staff.data.mustChangePassword ? '/account/password' : staff.data.dashboardPath);
    else if (isLoaded && isSignedIn !== true) {
      const destination = safeMemberReturnTo(location) ?? '/member/dashboard';
      navigate(`/login?returnTo=${encodeURIComponent(destination)}`);
    }
  }, [staff.data, isLoaded, isSignedIn, navigate, location]);

  if (staff.isLoading || !isLoaded || (isSignedIn && member.isLoading)) {
    return <main className="page"><div className="skeleton" style={{ width: 260, height: 28 }}/><div className="skeleton" style={{ width: '100%', maxWidth: 560, height: 180, marginTop: 24 }}/></main>;
  }
  if (staff.data) return null;
  if (!isSignedIn) return null;
  if (member.isError || !member.data) {
    const message = (member.error as { message?: string } | null)?.message ?? 'This account does not have member dashboard access.';
    return <main className="member-experience mx-signup-loading"><section className="mx-signup-panel mx-access-unavailable">
      <div className="mx-overline"><span className="mx-live-mark"/> ACCESS CHECK</div>
      <h1>Member access unavailable</h1>
      <p>{message}</p>
      <div className="mx-access-actions">
        <Link className="mx-button mx-button-quiet" href="/" data-testid="link-member-access-home">Return to the public website</Link>
        <button className="mx-button mx-button-gold" type="button" onClick={() => void clerk.signOut({ redirectUrl: `${basePath}/` })}>Sign out</button>
      </div>
    </section></main>;
  }
  if (!member.data.learningDashboard) {
    return <main className="member-experience mx-signup-loading"><section className="mx-signup-panel mx-access-unavailable" role="alert">
      <div className="mx-overline"><span className="mx-live-mark"/> ACCESS CHECK</div>
      <h1>Dashboard access not assigned</h1>
      <p>This account has no assigned member learning dashboard. Staff or PRO access will not be granted automatically.</p>
      <div className="mx-access-actions">
        <Link className="mx-button mx-button-quiet" href="/">Return to the public website</Link>
        <button className="mx-button mx-button-gold" type="button" onClick={() => void clerk.signOut({ redirectUrl: `${basePath}/` })}>Sign out</button>
      </div>
    </section></main>;
  }
  if (location === '/member/settings') return <MemberAccountSettingsPage session={member.data}/>;
  if (location === '/member/learning') return <MemberLearningExperience />;
  if (location === '/member/videos') return <MemberCourseVideoLibrary />;
  if (location === '/member/notifications') {
    if (import.meta.env.DEV) return <MemberNotificationsExperience />;
    return <main className="member-experience mx-signup-loading"><section className="mx-signup-panel mx-access-unavailable">
      <div className="mx-overline"><span className="mx-live-mark"/> DEVELOPMENT FEATURE</div>
      <h1>Notifications are not enabled here</h1>
      <p>The Development notification center is not available in this environment.</p>
      <Link className="mx-button mx-button-quiet" href={member.data.dashboardPath}>Return to your workspace</Link>
    </section></main>;
  }
  if (location === '/member/calendar') return <MemberCalendarExperience />;
  if (location === '/member/journal') return <MemberJournalExperience />;
  if (location === '/member/coach') return <MemberCoachExperience />;
  if (location === '/member/pro-signals') {
    return member.data.proSignalsAccess
      ? <MemberProSignalsExperience />
      : <MemberProSignalsAccessUnavailable />;
  }
  if (location !== member.data.dashboardPath) return null;
  return <MemberDashboardPage session={member.data}/>;
}

function AppShell({ session, children }: { session: PortalSession; children: ReactNode }) {
  const [location, navigate] = useLocation();
  const client = useQueryClient();
  const logout = usePortalLogout();
  const clerk = useClerk();
  const { toast } = useToast();
  const knownOpenCases = useRef<Set<string> | null>(null);
  const knownTaskNoticeIds = useRef<Set<string> | null>(null);
  const knownReportNoticeIds = useRef<Set<string> | null>(null);
  const [scrollTarget, setScrollTarget] = useState('');
  const [activeScrollTarget, setActiveScrollTarget] = useState('');
  const notificationParams = { status: 'open' as const, limit: 100 };
  const notificationQuery = useListPortalCases(notificationParams, {
    query: {
      queryKey: getListPortalCasesQueryKey(notificationParams),
      refetchInterval: 15000,
      refetchIntervalInBackground: false,
      staleTime: 10_000,
    },
  });
  const taskNotificationQuery = useListStaffTaskNotifications({
    query: {
      queryKey: getListStaffTaskNotificationsQueryKey(),
      refetchInterval: 15000,
      refetchIntervalInBackground: false,
      staleTime: 10_000,
    },
  });
  const reportNotificationQuery = useListStaffReportNotifications({
    query: {
      queryKey: getListStaffReportNotificationsQueryKey(),
      refetchInterval: 15000,
      refetchIntervalInBackground: false,
      staleTime: 10_000,
    },
  });
  const navItems = session.role === 'agent'
    ? [
      { href: '/tasks', label: 'My Tasks', icon: <CheckCircle2 />, testId: 'link-my-tasks' },
      { href: '/staff/support', label: 'Support inbox', icon: <MessageSquareText />, testId: 'link-my-support-cases' },
      { href: '/tasks', label: 'Notifications', icon: <Bell />, testId: 'link-notifications', scrollTarget: 'notifications' },
      { href: '/tasks', label: 'Submit Work', icon: <FileText />, testId: 'link-submit-work', scrollTarget: 'submit-work' },
    ]
    : [
      { href: '/staff/support', label: 'Support inbox', icon: <MessageSquareText />, testId: 'link-support' },
      { href: '/tasks', label: 'Staff Tasks', icon: <CheckCircle2 />, testId: 'link-staff-tasks' },
      { href: '/staff', label: 'Staff', icon: <Users />, testId: session.role === 'owner' ? 'link-staff-accounts' : 'link-staff' },
      ...(import.meta.env.DEV ? [{ href: '/staff/announcements', label: 'Member announcements', icon: <Bell />, testId: 'link-member-announcements' }] : []),
      ...(session.role === 'owner' ? [
         { href: '/bot-control', label: 'Bot Control', icon: <Bot />, testId: 'link-owner-bot-control' },
         { href: '/operations', label: 'Operations Center', icon: <Gauge />, testId: 'link-owner-operations' },
         { href: '/command-center/mind-map', label: 'Mind map', icon: <BrainCircuit />, testId: 'link-owner-mind-map' },
         { href: '/command-center/member-access', label: 'Member access', icon: <Users />, testId: 'link-owner-member-access' },
         { href: '/command-center/member-course-videos', label: 'Member video lessons', icon: <Clapperboard />, testId: 'link-owner-member-course-videos' },
        { href: '/trades', label: 'Trade management', icon: <Activity />, testId: 'link-owner-trades' },
        ...(import.meta.env.DEV ? [{ href: '/signals', label: 'Signals & Zones', icon: <Radio />, testId: 'link-owner-signals' }] : []),
      ] : []),
    ];
  useEffect(() => {
    if (location !== '/tasks' || !scrollTarget) return;
    const timer = window.setTimeout(() => {
      document.getElementById(scrollTarget)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setActiveScrollTarget(scrollTarget);
      setScrollTarget('');
    }, 80);
    return () => window.clearTimeout(timer);
  }, [location, scrollTarget]);
  useEffect(() => {
    const cases = notificationQuery.data?.cases;
    if (!cases) return;
    const currentOpenCases = new Set(cases.filter((item) => item.status === 'open').map((item) => item.caseId));
    if (knownOpenCases.current) {
      const newCount = [...currentOpenCases].filter((caseId) => !knownOpenCases.current?.has(caseId)).length;
      if (newCount > 0) {
        toast({
          title: newCount === 1 ? 'New support request' : `${newCount} new support requests`,
          description: 'Open Support to review and respond.',
        });
        void Promise.all([
          client.invalidateQueries({ queryKey: getListPortalCasesQueryKey() }),
          client.invalidateQueries({ queryKey: getGetPortalDashboardQueryKey() }),
        ]);
      }
    }
    knownOpenCases.current = currentOpenCases;
  }, [notificationQuery.data?.cases, toast]);
  useEffect(() => {
    const current = taskNotificationQuery.data?.notifications;
    if (!current) return;
    const unreadIds = new Set(current.filter((notice) => !notice.readAt).map((notice) => notice.notificationId));
    if (knownTaskNoticeIds.current) {
      const newCount = [...unreadIds].filter((id) => !knownTaskNoticeIds.current?.has(id)).length;
      if (newCount > 0) {
        toast({
          title: newCount === 1 ? 'Task update' : `${newCount} task updates`,
          description: 'Open Staff tasks to review assignments or feedback.',
        });
        void client.invalidateQueries({ queryKey: getListStaffTasksQueryKey() });
      }
    }
    knownTaskNoticeIds.current = unreadIds;
  }, [taskNotificationQuery.data?.notifications, client, toast]);
  useEffect(() => {
    const current = reportNotificationQuery.data?.notifications;
    if (!current) return;
    const unreadIds = new Set(current.filter((notice) => !notice.readAt).map((notice) => notice.notificationId));
    if (knownReportNoticeIds.current) {
      const newCount = [...unreadIds].filter((id) => !knownReportNoticeIds.current?.has(id)).length;
      if (newCount > 0) {
        toast({
          title: newCount === 1 ? 'Activity report reviewed' : `${newCount} report updates`,
          description: 'Open Staff tasks to view the outcome and reviewer feedback.',
        });
      }
    }
    knownReportNoticeIds.current = unreadIds;
  }, [reportNotificationQuery.data?.notifications, toast]);
  const signOut = () => logout.mutate(undefined, { onSuccess: async () => { await clerk.signOut().catch(() => undefined); client.clear(); navigate('/login'); }, onError: () => client.invalidateQueries({ queryKey: sessionKey }) });
    return <div className={`portal-shell ${location.startsWith('/command-center') ? 'portal-owner-shell' : ''}`}>
    <aside className="sidebar"><Brand/><div className="nav-label">Main menu</div>{navItems.map((item) => <Link key={item.testId} href={item.href} onClick={() => item.scrollTarget && setScrollTarget(item.scrollTarget)} className={`nav-link ${(item.scrollTarget ? activeScrollTarget === item.scrollTarget : location === item.href) ? 'active' : ''}`} data-testid={item.testId}>{item.icon}{item.label}</Link>)}<div className="sidebar-bottom"><div className="person"><span className="person-avatar">{initials(session.displayName)}</span><div><div className="person-name">{session.displayName}</div><div className="person-role">{session.role === 'owner' ? 'Owner' : session.role === 'manager' ? 'Support Manager' : 'Support Agent'}</div></div></div>{session.role === 'owner' && <><Link className={`account-link owner-command-link ${location === '/command-center' ? 'selected' : ''}`} href="/command-center"><Gauge size={14}/>Command center <span>DEV</span></Link><Link className={`account-link owner-education-link ${location === '/command-center/education-videos' ? 'selected' : ''}`} href="/command-center/education-videos" data-testid="link-owner-education-videos"><FileText size={14}/>Education videos</Link><Link className={`account-link owner-history-link ${location === '/command-center/channel-history' ? 'selected' : ''}`} href="/command-center/channel-history" data-testid="link-owner-channel-history"><History size={14}/>Channel history</Link></>}<Link className="account-link" href="/account/password"><KeyRound size={14}/>Change password</Link><button className="signout" onClick={signOut} disabled={logout.isPending} data-testid="button-sign-out"><LogOut size={13} style={{ verticalAlign: 'middle', marginRight: 6 }} />{logout.isPending ? 'Signing out…' : 'Sign out'}</button></div></aside>
     <div className="main-column"><div className="mobile-top"><Brand/><div className="mobile-actions">{session.role === 'owner' && <><Link href="/bot-control" aria-label="Bot control center" data-testid="mobile-quick-bot-control"><Bot size={17}/></Link><Link href="/command-center" aria-label="Owner command center"><Gauge size={17}/></Link><Link href="/command-center/education-videos" aria-label="Education videos" data-testid="mobile-link-owner-education-videos"><FileText size={17}/></Link><Link href="/command-center/channel-history" aria-label="Channel history" data-testid="mobile-link-owner-channel-history"><History size={17}/></Link><Link href="/trades" aria-label="Trade management" data-testid="mobile-link-owner-trades"><Activity size={17}/></Link></>}<Link href="/account/password" aria-label="Change password"><KeyRound size={17}/></Link><button onClick={signOut} aria-label="Sign out"><LogOut size={17}/></button></div></div><nav className="mobile-nav" aria-label="Portal navigation">{navItems.map((item) => <Link key={item.testId} href={item.href} onClick={() => item.scrollTarget && setScrollTarget(item.scrollTarget)} className={`mobile-nav-link ${(item.scrollTarget ? activeScrollTarget === item.scrollTarget : location === item.href) ? 'active' : ''}`} data-testid={`mobile-${item.testId}`}>{item.icon}<span>{item.label}</span></Link>)}</nav><header className="topbar"><div className="crumb">{location === '/bot-control' ? 'Owner tools / Bot control center' : location.startsWith('/command-center') ? 'Owner tools / Command center' : location === '/trades' ? 'Owner tools / Trade management' : 'Staff Support Portal'}</div><div className="top-right"><span className="secure-label"><span className="secure-dot"/ >Private workspace</span><span>{session.displayName}</span></div></header>{children}</div>
  </div>;
}

function commandLabel(value: string | boolean | null | undefined) {
  if (value === null || value === undefined || value === '') return 'Not recorded';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (value.toLowerCase() === 'unknown') return 'No status reported';
  if (value.toLowerCase() === 'not_connected') return 'Not connected here';
  if (value.toLowerCase() === 'not_configured') return 'Not configured';
  const normalized = value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  return normalized;
}
function CommandCenter({ session }: { session: PortalSession }) {
  const query = useGetPortalCommandCenter({ query: { queryKey: getGetPortalCommandCenterQueryKey(), staleTime: 15_000, refetchOnMount: 'always', refetchInterval: 30_000 } });
  if (session.role !== 'owner') return <AccessDenied/>;
  const data = query.data;
  const testBot = data?.bots.find((bot) => bot.id === 'isolated_test');
  const refreshed = data?.refreshedAt ? new Date(data.refreshedAt) : null;
  const stale = query.isStale || Boolean(refreshed && Date.now() - refreshed.getTime() > 5 * 60_000);
  const timestamp = (value?: string | null) => prettyDate(value);
  const overviewItems = data ? [
    { label: 'Open support cases', value: data.overview.openSupportCases, icon: <MessageSquareText size={17}/>, tone: 'green' },
    { label: 'Uncertain replies', value: data.overview.uncertainSupportCases, icon: <CircleHelp size={17}/>, tone: 'amber' },
    { label: 'Overdue tasks', value: data.overview.overdueTasks, icon: <CircleAlert size={17}/>, tone: 'rose' },
    { label: 'Recorded trades', value: data.overview.recordedTrades, icon: <Activity size={17}/>, tone: 'green' },
    { label: 'Trade events', value: data.overview.recordedTradeEvents, icon: <Activity size={17}/>, tone: 'slate' },
    { label: 'Unresolved publishing', value: data.overview.unresolvedPublishingOperations, icon: <Radio size={17}/>, tone: 'amber' },
    { label: 'PRO awaiting final review', value: data.overview.proPendingReview, icon: <ShieldCheck size={17}/>, tone: 'green' },
    { label: 'PRO evidence requested', value: data.overview.proEvidenceRequested, icon: <FileText size={17}/>, tone: 'amber' },
    { label: 'PRO applications 7+ days', value: data.overview.staleProApplications, icon: <CircleAlert size={17}/>, tone: 'rose' },
  ] : [];
  const liveRows = testBot ? [
    { label: 'Private test bot process', value: testBot.processStatus },
    { label: 'Bot health check', value: testBot.healthStatus },
    { label: 'Telegram API', value: testBot.telegramStatus },
    { label: 'Database', value: testBot.databaseStatus },
    { label: 'Polling loop', value: testBot.pollingStatus },
    { label: 'Test publishing setting', value: testBot.publishingStatus },
    { label: 'Replit workflow control panel', value: testBot.workflowStatus },
  ] : [];
  return <main className="page command-page owner-modern">
    <div className="command-kicker"><span className="command-kicker-mark"><Gauge size={15}/></span><span>OWNER VIEW</span><i/>DEVELOPMENT · READ ONLY</div>
    <div className="command-heading"><div><div className="eyebrow">OPERATIONAL VISIBILITY</div><h1>Command center</h1><p className="subheading">A careful read of stored test records — not a live bot monitor.</p></div><div className="command-heading-actions"><Link className="btn btn-primary btn-large" href="/command-center/pro-access"><ShieldCheck size={15}/>PRO access review</Link><Link className="btn btn-outline btn-large" href="/command-center/education-videos" data-testid="link-education-videos"><FileText size={15}/>Education videos</Link>{data && <div className={`freshness ${stale ? 'is-stale' : 'is-fresh'}`}><span className="freshness-dot"/><div><strong>{stale ? 'Snapshot may be stale' : 'Snapshot recently checked'}</strong><span>Refreshed {timestamp(data.refreshedAt)}</span></div><button className="btn btn-outline" aria-label="Refresh command center data" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw size={14} className={query.isFetching ? 'refreshing' : ''}/><span>{query.isFetching ? 'Refreshing' : 'Refresh'}</span></button></div>}</div></div>
    {data && <section className="command-scope" aria-label="Data scope"><div className="scope-icon"><Database size={18}/></div><div><strong>{data.scope === 'development_isolated_test' ? 'Isolated Development data' : commandLabel(data.scope)}</strong><p>This view reads stored Development test data only. Production data is not connected.</p></div><span className="readonly-tag">{data.readOnly ? 'READ ONLY' : 'READ ONLY VIEW'}</span></section>}
    {query.isLoading ? <section className="command-loading" aria-label="Loading command center" data-testid="command-loading"><div className="command-loading-head"><div className="skeleton"/><div className="skeleton"/></div><div className="command-loading-grid">{[0,1,2,3,4,5].map(i=><div className="command-skeleton-card" key={i}><div className="skeleton"/><div className="skeleton"/></div>)}</div><div className="skeleton" style={{height:140,marginTop:18}}/></section> : query.isError ? <section className="section-panel command-feedback"><ErrorState error={query.error} retry={() => query.refetch()}/></section> : data ? <>
      <section className="command-metrics" aria-label="Stored data overview">{overviewItems.map(item=><article className={`command-metric metric-${item.tone}`} key={item.label}><div className="command-metric-top"><span>{item.label}</span><span className="command-metric-icon">{item.icon}</span></div><strong>{item.value}</strong><small>stored records</small></article>)}</section>
      <section className="command-panel live-panel"><div className="command-panel-head"><div><div className="eyebrow">PRIVATE TEST BOT</div><h2>Development heartbeat</h2></div><span className={`unknown-chip ${testBot?.processStatus === 'running' ? 'chip-live' : ''}`}>{testBot?.processStatus === 'running' ? 'Heartbeat received' : 'No heartbeat in this workspace'}</span></div><p className="live-intro">{testBot?.note ?? 'No recent process health report has been received in the isolated Development environment.'} Status refreshes automatically every 30 seconds. This does not monitor the VPS.</p><div className="unknown-grid">{liveRows.map(({ label, value })=>{const state=value.toLowerCase().replace(/[^a-z0-9]+/g,'-');return <div className={`unknown-row state-${state}`} key={label}><span className="unknown-indicator">{value === 'running' || value === 'healthy' || value === 'enabled' ? '✓' : value === 'unknown' || value === 'not_connected' ? '—' : '!'}</span><span>{label}</span><strong>{commandLabel(value)}</strong></div>})}<div className="unknown-row"><span className="unknown-indicator">◷</span><span>Last health check</span><strong>{timestamp(testBot?.healthCheckedAt)}</strong></div></div><p className="monitoring-caveat">Publishing is a configuration setting, not proof of delivery. The bot checks below test Telegram credentials only; they never send or publish a message.</p></section>
      <BotConnections/>
      <section className="command-panel" aria-label="Monitoring alerts" data-testid="command-alerts"><div className="command-panel-head"><div><div className="eyebrow">READ-ONLY MONITORING</div><h2>Alerts needing attention</h2><p>Stale bot heartbeats and recorded signal/analysis operation states, grouped to avoid repeats.</p></div><span className={`count-tag ${data.alerts.length ? 'alert-count' : ''}`}>{data.alerts.length ? `${data.alerts.length} alert${data.alerts.length === 1 ? '' : 's'}` : 'No active alerts'}</span></div>{data.alerts.length ? <div className="monitor-alert-list">{data.alerts.map((alert,index)=><article className={`monitor-alert severity-${alert.severity}`} key={`${alert.category}-${alert.destination}-${index}`}><span className="monitor-alert-icon"><CircleAlert size={16}/></span><div className="monitor-alert-copy"><strong>{alert.title}</strong><span>{commandLabel(alert.sourceBot)} · {alert.destination}{alert.count > 1 ? ` · ${alert.count} recorded operations` : ''}</span></div><time>{timestamp(alert.latestAt)}</time></article>)}</div> : <div className="command-empty">No supported monitoring alerts are active. This does not confirm current channel access.</div>}</section>
      <section className="command-panel"><div className="command-panel-head"><div><div className="eyebrow">BOT RECORDS</div><h2>Development snapshot sources</h2><p>Production is outside this dashboard. Test process fields appear only when a heartbeat has been recorded.</p></div><span className="count-tag">{data.bots.length} {data.bots.length === 1 ? 'source' : 'sources'}</span></div>{data.bots.length ? <div className="bot-list">{data.bots.map((bot,index)=><article className="bot-row" key={`${bot.label}-${index}`}><div className="bot-mark"><Radio size={17}/></div><div className="bot-copy"><strong>{bot.label}</strong><span>Last recorded Telegram update · {timestamp(bot.lastTelegramUpdate)}</span></div><div className="bot-statuses"><span><small>Health</small><b>{bot.id === 'production' ? 'Outside Development' : commandLabel(bot.healthStatus)}</b></span><span><small>Bot process</small><b>{bot.id === 'production' ? 'Not connected here' : bot.processStatus === 'unknown' ? 'No heartbeat' : commandLabel(bot.processStatus)}</b></span><span><small>Publishing setting</small><b>{bot.id === 'production' ? 'Outside Development' : commandLabel(bot.publishingStatus)}</b></span></div></article>)}</div> : <div className="command-empty">No bot records are stored in this snapshot.</div>}</section>
      <section className="command-panel"><div className="command-panel-head"><div><div className="eyebrow">DESTINATION RECORDS</div><h2>Channels</h2><p>Recorded activity may be old and does not confirm current access.</p></div><span className="count-tag">{data.channels.length} {data.channels.length === 1 ? 'destination' : 'destinations'}</span></div>{data.channels.length ? <div className="channel-grid">{data.channels.map((channel,index)=><article className="channel-record" key={`${channel.name}-${index}`}><div className="channel-heading"><div><span className="channel-source">{commandLabel(channel.sourceBot)}</span><h3>{commandLabel(channel.name)}</h3></div><span className="record-state">{commandLabel(channel.status)}</span></div><div className="channel-foot"><span>Latest recorded activity</span><strong>{timestamp(channel.latestRecordedActivity)}</strong></div></article>)}</div> : <div className="command-empty">No channel records are stored in this snapshot.</div>}</section>
      <section className="command-panel"><div className="command-panel-head"><div><div className="eyebrow">RECENT ACTIVITY</div><h2>Publishing operations</h2><p>Acceptance by Telegram is not evidence of broker execution or profit.</p></div><span className="count-tag">{data.recentOperations.length} records</span></div>{data.recentOperations.length ? <div className="ops-list">{data.recentOperations.map((operation,index)=><article className="operation-row" key={`${operation.recordedAt}-${index}`}><div className="operation-icon"><Activity size={16}/></div><div className="operation-main"><strong>{commandLabel(operation.operationType)}</strong><span>{commandLabel(operation.sourceBot)} <span className="operation-arrow">→</span> {commandLabel(operation.destination)}</span></div><span className={`operation-status op-${operation.status.toLowerCase().replace(/[^a-z0-9]+/g,'-')}`}>{commandLabel(operation.status)}</span><span className="operation-accepted">{operation.telegramAccepted ? 'Telegram accepted' : 'Not accepted / not confirmed'}</span><time>{timestamp(operation.recordedAt)}</time></article>)}</div> : <div className="command-empty">No publishing operation records are stored in this snapshot.</div>}</section>
      <section className="command-panel"><div className="command-panel-head"><div><div className="eyebrow">ERROR SUMMARY</div><h2>Recorded errors</h2><p>Category totals and latest recorded occurrence.</p></div><span className="count-tag">{data.recentErrors.length} categories</span></div>{data.recentErrors.length ? <div className="error-records">{data.recentErrors.map((error,index)=><article className="error-record" key={`${error.category}-${index}`}><div className="error-category"><CircleAlert size={15}/><strong>{commandLabel(error.category)}</strong></div><strong className="error-count">{error.count}<small> occurrences</small></strong><time>Latest · {timestamp(error.latestAt)}</time></article>)}</div> : <div className="command-empty">No error summaries are stored in this snapshot.</div>}</section>
      <footer className="command-footnote"><span className="footnote-mark">i</span><p><strong>Interpret records with care.</strong> This dashboard reflects stored Development test data. A Telegram message accepted is not proof of a broker order, execution, or profit. No credentials, raw messages, private case content, or member identifiers are shown.</p><span>Last Telegram update · {timestamp(data.lastTelegramUpdate)}</span></footer>
    </> : <section className="section-panel command-feedback"><Empty title="No snapshot available">The Development command center returned no stored snapshot. Refresh to check again.</Empty><div className="command-feedback-action"><button className="btn btn-outline" onClick={() => query.refetch()}><RefreshCw size={14}/>Retry</button></div></section>}
  </main>;
}

function Queue({ session }: { session: PortalSession }) {
  return <SupportInbox session={session}/>;
}

function TaskCenter({ session }: { session: PortalSession }) {
  const client = useQueryClient();
  const [advancedReportsOpen, setAdvancedReportsOpen] = useState(false);
  const tasksQuery = useListStaffTasks();
  const teamsQuery = useListStaffTeams({ query: { queryKey: getListStaffTeamsQueryKey(), enabled: session.role === 'owner' } });
  const reportsQuery = useListStaffActivityReports({ query: { queryKey: getListStaffActivityReportsQueryKey(), enabled: advancedReportsOpen, staleTime: 30_000 } });
  const performanceQuery = useGetStaffPerformance({ query: { queryKey: getGetStaffPerformanceQueryKey(), enabled: advancedReportsOpen, staleTime: 30_000 } });
  const taskNotifications = useListStaffTaskNotifications({ query: { queryKey: getListStaffTaskNotificationsQueryKey() } });
  const markNotificationRead = useMarkStaffTaskNotificationRead();
  const reportNotifications = useListStaffReportNotifications({
    query: { queryKey: getListStaffReportNotificationsQueryKey(), staleTime: 10_000 },
  });
  const markReportNotificationRead = useMarkStaffReportNotificationRead();
  const staffQuery = useListPortalStaff({ query: { queryKey: getListPortalStaffQueryKey(), enabled: session.role === 'owner', staleTime: 30_000 } });
  const createTask = useCreateStaffTask();
  const submitReport = useSubmitStaffActivityReport();
  const reviewReport = useReviewStaffActivityReport();
  const changeStatus = useUpdateStaffTaskStatus();
  const [createOpen, setCreateOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [instructions, setInstructions] = useState('');
  const [priority, setPriority] = useState<'low'|'normal'|'high'|'urgent'>('normal');
  const [effortPoints, setEffortPoints] = useState(1);
  const [dueAt, setDueAt] = useState('');
  const [teamId, setTeamId] = useState('');
  const [assigneeId, setAssigneeId] = useState('');
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [failure, setFailure] = useState('');
  const [message, setMessage] = useState('');
  const [reportPeriod, setReportPeriod] = useState<'daily'|'weekly'>('daily');
  const [reportDate, setReportDate] = useState(new Date().toISOString().slice(0,10));
  const [completedWork, setCompletedWork] = useState('');
  const [outstandingWork, setOutstandingWork] = useState('');
  const [blockers, setBlockers] = useState('');
  const [plans, setPlans] = useState('');
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: getListStaffTasksQueryKey() }),
      client.invalidateQueries({ queryKey: getListStaffActivityReportsQueryKey() }),
      client.invalidateQueries({ queryKey: getListStaffReportNotificationsQueryKey() }),
      client.invalidateQueries({ queryKey: getGetStaffPerformanceQueryKey() }),
      client.invalidateQueries({ queryKey: ['/api/portal/teams'] }),
    ]);
  };
  const markRead = (notificationId: string) => {
    markNotificationRead.mutate({ notificationId }, {
      onSuccess: async () => {
        await client.invalidateQueries({ queryKey: getListStaffTaskNotificationsQueryKey() });
      },
    });
  };
  const submitTask = (event: FormEvent) => {
    event.preventDefault();
    setFailure(''); setMessage('');
    createTask.mutate({
      data: {
        requestId, title: title.trim(), instructions: instructions.trim(), priority,
        effortPoints,
        dueAt: dueAt ? new Date(dueAt).toISOString() : null,
        teamId: teamId || null, assignedStaffId: assigneeId || null,
      },
    }, {
      onSuccess: async () => {
        trackEvent('staff_task_created', { priority });
        setTitle(''); setInstructions(''); setDueAt(''); setAssigneeId(''); setTeamId(''); setPriority('normal'); setEffortPoints(1);
        setRequestId(crypto.randomUUID());
        setCreateOpen(false);
        setMessage('Task assigned.');
        await refresh();
      },
      onError: (error) => setFailure(errMessage(error, 'The task could not be created.')),
    });
  };
  const statusAction = (task: StaffTask, status: 'accepted'|'in_progress'|'submitted_for_review'|'revision_requested'|'approved'|'cancelled') => {
    let note = '';
    if (status === 'submitted_for_review') {
      note = window.prompt('Add a short completion note for review:')?.trim() ?? '';
      if (note.length < 3) return;
    } else if (status === 'revision_requested') {
      note = window.prompt('Explain what needs to be revised:')?.trim() ?? '';
      if (note.length < 3) return;
    } else if (status === 'cancelled' && !window.confirm('Cancel this task? This action will be recorded.')) {
      return;
    }
    setFailure(''); setMessage('');
    changeStatus.mutate({ taskId: task.taskId, data: { status, note } }, {
      onSuccess: async () => {
        trackEvent('staff_task_status_changed', { status });
        setMessage('Task updated.');
        await refresh();
      },
      onError: (error) => setFailure(errMessage(error, 'The task could not be updated.')),
    });
  };
  const submitActivityReport = (event: FormEvent) => {
    event.preventDefault(); setFailure(''); setMessage('');
    submitReport.mutate({
      data: { period: reportPeriod, periodStart: reportDate, completedWork: completedWork.trim(),
        outstandingWork: outstandingWork.trim(), blockers: blockers.trim(), plans: plans.trim() },
    }, {
      onSuccess: async (report) => {
        trackEvent('activity_report_saved', { period: reportPeriod });
        setCompletedWork(''); setOutstandingWork(''); setBlockers(''); setPlans('');
        setMessage(report.reviewStatus === 'submitted' ? 'Your report is saved for review.' : 'A report for that period already exists.');
        await refresh();
      },
      onError: (error) => setFailure(errMessage(error, 'The activity report could not be submitted.')),
    });
  };
  const reviewActivityReport = (reportId: string, status: 'reviewed'|'revision_requested') => {
    const note = window.prompt(status === 'reviewed' ? 'Add a review note:' : 'Explain what should be revised:')?.trim() ?? '';
    if (note.length < 3) return;
    reviewReport.mutate({ reportId, data: { status, note } }, {
      onSuccess: async () => {
        trackEvent('activity_report_reviewed', { outcome: status });
        setMessage(status === 'reviewed' ? 'Report reviewed.' : 'Revision requested.');
        await refresh();
      },
      onError: (error) => setFailure(errMessage(error, 'The report review could not be saved.')),
    });
  };
  const markReportRead = (notificationId: string) => markReportNotificationRead.mutate(
    { notificationId },
    {
      onSuccess: () => { void client.invalidateQueries({ queryKey: getListStaffReportNotificationsQueryKey() }); },
      onError: (error) => setFailure(errMessage(error, 'This report notice could not be marked as read.')),
    },
  );
  const activeStaff = (staffQuery.data?.staff ?? []).filter((person) => person.active);
  const isReviewer = session.role === 'owner' || session.role === 'manager';
  return <main className="page">
    <div className="page-heading">
      <div><div className="eyebrow">STAFF WORKSPACE</div><h1>{session.role === 'agent' ? 'My Tasks' : session.role === 'manager' ? 'Team Tasks' : 'Staff Tasks'}</h1><p className="subheading">See what needs doing, what is in progress, and what is ready to review.</p></div>
      {session.role === 'owner' && <button className="btn btn-primary btn-large" onClick={() => { setFailure(''); setCreateOpen(true); }} data-testid="button-open-create-task"><Plus/>Create Task</button>}
    </div>
    {failure && <div className="notice notice-error" role="alert">{failure}</div>}
    {message && <div className="notice notice-info" role="status">{message}</div>}
    <section className="section-panel notifications-panel" id="notifications" style={{marginBottom:20}}>
      <div className="section-head"><div><h2 className="section-title">Notifications</h2><p className="section-note">Task updates and report feedback for your account.</p></div></div>
      {reportNotifications.isError && <ErrorState error={reportNotifications.error} retry={() => reportNotifications.refetch()}/>}
      {taskNotifications.isError && <ErrorState error={taskNotifications.error} retry={() => taskNotifications.refetch()}/>}
      <div className="notification-list">
        {(reportNotifications.data?.notifications ?? []).map((notice)=><article className="report-card" key={notice.notificationId} data-testid={`report-notice-${notice.notificationId}`}>
          <div className="task-card-head"><div><div className="eyebrow">{notice.period.toUpperCase()} REPORT · {notice.periodStart}</div><h3>{notice.outcome==='approved'?'Report approved':'Changes requested'}</h3></div><span className={`status status-${notice.outcome}`}>{notice.readAt?'Read':'New'}</span></div>
          <p><b>Outcome:</b> {notice.outcome==='approved'?'Approved':'Returned for changes'}</p>
          <p><b>Feedback:</b> {notice.reviewerFeedback}</p>
          <div className="task-actions"><Link className="btn btn-outline" href={notice.href} data-testid={`link-report-notice-${notice.notificationId}`} onClick={()=>window.setTimeout(()=>{const reports=document.getElementById('advanced-reports') as HTMLDetailsElement|null;if(reports)reports.open=true;document.getElementById(`report-${notice.reportId}`)?.scrollIntoView({behavior:'smooth',block:'start'});},80)}>View report</Link>{!notice.readAt&&<button className="btn btn-quiet" onClick={()=>markReportRead(notice.notificationId)} disabled={markReportNotificationRead.isPending}>Mark as read</button>}</div>
          <div className="muted-small">{prettyDate(notice.created)}</div>
        </article>)}
        {(taskNotifications.data?.notifications ?? []).map((notice)=>{
          const linkedTask=tasksQuery.data?.tasks.find((task)=>task.taskId===notice.taskId);
          return <div className={`task-notice ${notice.readAt?'is-read':''}`} key={notice.notificationId} data-testid={`task-notice-${notice.notificationId}`}>
            <div><strong>{taskNoticeLabel(notice.type)}</strong><div className="muted-small">{linkedTask?.title ?? 'Your task'} · {prettyDate(notice.created)}</div></div>
            {!notice.readAt&&<button className="btn btn-quiet" onClick={()=>markRead(notice.notificationId)} disabled={markNotificationRead.isPending}>Mark read</button>}
          </div>;
        })}
        {!reportNotifications.isLoading&&!taskNotifications.isLoading&&!reportNotifications.data?.notifications.length&&!taskNotifications.data?.notifications.length&&<div className="notifications-empty"><Bell size={20}/><strong>You're all caught up</strong><span>New task and report updates will appear here.</span></div>}
      </div>
    </section>
    {session.role === 'owner' && createOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !createTask.isPending) setCreateOpen(false); }}><div className="modal task-create-modal" role="dialog" aria-modal="true" aria-labelledby="task-create-title">
      <button className="btn btn-quiet modal-close" onClick={() => setCreateOpen(false)} disabled={createTask.isPending} aria-label="Close"><X size={17}/></button>
      <div className="eyebrow">NEW TASK</div><h2 id="task-create-title">Create Task</h2><p className="modal-copy">Write clear instructions, choose a worker, and assign a deadline.</p>
      <form onSubmit={submitTask}>
        <div className="form-field"><label className="form-label" htmlFor="task-title">Task title</label><input id="task-title" className="field-input" required minLength={3} maxLength={120} value={title} onChange={(e)=>setTitle(e.target.value)} /></div>
        <div className="form-field"><label className="form-label" htmlFor="task-instructions">Instructions</label><textarea id="task-instructions" className="reply-area" required maxLength={4000} value={instructions} onChange={(e)=>setInstructions(e.target.value)} placeholder="Explain what needs to be done and what a complete result looks like." /></div>
        <div className="form-field"><label className="form-label" htmlFor="task-assignee">Worker</label><select id="task-assignee" className="field-select" value={assigneeId} onChange={(e)=>{setAssigneeId(e.target.value);if(e.target.value)setTeamId('');}}><option value="">Choose a worker</option>{activeStaff.filter((person)=>person.role==='agent').map((person)=><option key={person.staffId} value={person.staffId}>{person.displayName}</option>)}</select></div>
        <div className="form-grid"><div className="form-field"><label className="form-label" htmlFor="task-priority">Priority</label><select id="task-priority" className="field-select" value={priority} onChange={(e)=>setPriority(e.target.value as typeof priority)}><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select></div><div className="form-field"><label className="form-label" htmlFor="task-deadline">Deadline (optional)</label><input id="task-deadline" className="field-input" type="datetime-local" value={dueAt} onChange={(e)=>setDueAt(e.target.value)} /></div></div>
        <details className="advanced-options"><summary>More options: team assignment and difficulty</summary><div className="form-grid"><div className="form-field"><label className="form-label" htmlFor="task-team">Assign to a team instead</label><select id="task-team" className="field-select" value={teamId} onChange={(e)=>{setTeamId(e.target.value);if(e.target.value)setAssigneeId('');}}><option value="">No team</option>{(teamsQuery.data?.teams ?? []).map((team)=><option key={team.teamId} value={team.teamId}>{team.name}</option>)}</select></div><div className="form-field"><label className="form-label" htmlFor="task-effort">Estimated difficulty</label><select id="task-effort" className="field-select" value={effortPoints} onChange={(e)=>setEffortPoints(Number(e.target.value))}><option value={1}>Small</option><option value={2}>Light</option><option value={3}>Standard</option><option value={4}>Complex</option><option value={5}>High effort</option></select></div></div></details>
        <div className="modal-actions"><button type="button" className="btn btn-outline" onClick={()=>setCreateOpen(false)} disabled={createTask.isPending}>Cancel</button><button className="btn btn-primary btn-large" type="submit" disabled={createTask.isPending || (!teamId && !assigneeId)}>{createTask.isPending ? 'Assigning…' : 'Assign Task'}</button></div>
      </form>
    </div></div>}
    <section className="section-panel" id="submit-work">
      <div className="section-head"><div><h2 className="section-title">{session.role === 'agent' ? 'My Tasks' : session.role === 'manager' ? 'Team Tasks' : 'All Tasks'}</h2><p className="section-note">{tasksQuery.data ? `${tasksQuery.data.tasks.length} tasks` : 'Your tasks will appear here.'}</p></div></div>
      {tasksQuery.isLoading ? <LoadingRows/> : tasksQuery.isError ? <ErrorState error={tasksQuery.error} retry={()=>tasksQuery.refetch()}/> : tasksQuery.data?.tasks.length ? <div className="task-list">{tasksQuery.data.tasks.map((task)=><article className="task-card" key={task.taskId} data-testid={`task-${task.taskId}`}>
        <div className="task-card-head"><div><div className="eyebrow">{task.priority.toUpperCase()} PRIORITY</div><h3>{task.title}</h3></div><span className={`status status-${task.status}`}>{taskStatusLabel(task.status)}</span></div>
        <div className="task-meta"><span>{task.assigneeName ? `Assigned to ${task.assigneeName}` : 'Assigned to team'}</span><span>{task.dueAt ? `Due ${prettyDate(task.dueAt)}` : 'No deadline'}</span>{task.dueAt && Date.parse(task.dueAt)<Date.now() && !['approved','cancelled'].includes(task.status) && <strong className="task-overdue">Overdue</strong>}</div>
        <details className="task-open"><summary>Open task</summary><div className="task-detail-content">
          <h4>Instructions</h4><p className="task-instructions">{task.instructions}</p>
          {task.submissionNote && <div className="notice notice-info"><b>Worker submission</b><br/>{task.submissionNote}</div>}
          {task.reviewFeedback && <div className="notice notice-error"><b>Changes requested</b><br/>{task.reviewFeedback}</div>}
          <div className="task-actions">
            {!isReviewer && task.status==='assigned' && <button className="btn btn-primary btn-large" onClick={()=>statusAction(task,'accepted')}>Start Task</button>}
            {!isReviewer && task.status==='accepted' && <button className="btn btn-primary btn-large" onClick={()=>statusAction(task,'in_progress')}>Start Work</button>}
            {!isReviewer && task.status==='revision_requested' && <button className="btn btn-primary btn-large" onClick={()=>statusAction(task,'in_progress')}>Resume Work</button>}
            {!isReviewer && task.status==='in_progress' && <button className="btn btn-primary btn-large" onClick={()=>statusAction(task,'submitted_for_review')}>Submit Work</button>}
            {isReviewer && task.status==='submitted_for_review' && <><button className="btn btn-primary btn-large" onClick={()=>statusAction(task,'approved')}>Approve</button><button className="btn btn-outline btn-large" onClick={()=>statusAction(task,'revision_requested')}>Request Changes</button></>}
          </div>
          {session.role==='owner' && !['approved','cancelled','submitted_for_review'].includes(task.status) && <details className="advanced-options"><summary>More actions</summary><button className="btn btn-quiet" onClick={()=>statusAction(task,'cancelled')}>Cancel task</button></details>}
          {session.role==='owner' && !['approved','cancelled','submitted_for_review'].includes(task.status) && <TaskEditForm task={task} teams={teamsQuery.data?.teams ?? []} staff={activeStaff} onSaved={async()=>{setMessage('Task updated.');await refresh();}} onError={(text)=>setFailure(text)}/>}
          <details className="task-history"><summary>History and audit details</summary>{task.events.map((event)=><div className="task-event" key={event.eventId}><span><b>{event.actorName}</b> {event.eventType.replaceAll('_',' ')} {event.newValue}</span><time>{prettyDate(event.created)}</time>{event.feedback && <p>{event.feedback}</p>}</div>)}</details>
        </div></details>
      </article>)}</div> : <Empty title="No tasks yet">Assigned tasks will appear here.</Empty>}
    </section>
    <details className="advanced-section" id="advanced-reports" onToggle={(event) => setAdvancedReportsOpen(event.currentTarget.open)}>
      <summary>More: reports and performance</summary>
    <section className="section-panel" style={{marginTop:20}}><div className="section-head"><div><h2 className="section-title">Daily & weekly activity report</h2><p className="section-note">Submit your own report; a manager or owner can review it and request changes.</p></div></div><form className="report-form" onSubmit={submitActivityReport}><div className="form-grid"><div className="form-field"><label className="form-label" htmlFor="report-period">Report period</label><select id="report-period" className="field-select" value={reportPeriod} onChange={(e)=>setReportPeriod(e.target.value as typeof reportPeriod)}><option value="daily">Daily</option><option value="weekly">Weekly</option></select></div><div className="form-field"><label className="form-label" htmlFor="report-date">Period start date</label><input id="report-date" type="date" className="field-input" value={reportDate} max={new Date().toISOString().slice(0,10)} onChange={(e)=>setReportDate(e.target.value)} required/></div></div><div className="form-grid"><div className="form-field"><label className="form-label" htmlFor="report-completed">Completed work</label><textarea id="report-completed" className="reply-area" maxLength={3000} value={completedWork} onChange={(e)=>setCompletedWork(e.target.value)} required/></div><div className="form-field"><label className="form-label" htmlFor="report-outstanding">Outstanding work</label><textarea id="report-outstanding" className="reply-area" maxLength={3000} value={outstandingWork} onChange={(e)=>setOutstandingWork(e.target.value)} required/></div><div className="form-field"><label className="form-label" htmlFor="report-blockers">Blockers (optional)</label><textarea id="report-blockers" className="reply-area" maxLength={2000} value={blockers} onChange={(e)=>setBlockers(e.target.value)}/></div><div className="form-field"><label className="form-label" htmlFor="report-plans">Next steps (optional)</label><textarea id="report-plans" className="reply-area" maxLength={2000} value={plans} onChange={(e)=>setPlans(e.target.value)}/></div></div><button className="btn btn-primary" type="submit" disabled={submitReport.isPending}>{submitReport.isPending?'Submitting…':'Submit report'}</button></form></section>
    <section className="section-panel" style={{marginTop:20}}><div className="section-head"><div><h2 className="section-title">Activity reports</h2><p className="section-note">Only reports in your authorized scope appear here.</p></div></div>{reportsQuery.isLoading?<LoadingRows/>:reportsQuery.isError?<ErrorState error={reportsQuery.error} retry={()=>reportsQuery.refetch()}/>:reportsQuery.data?.reports.length?<div className="report-list">{reportsQuery.data.reports.map((report)=><article className="report-card" key={report.reportId} id={`report-${report.reportId}`} tabIndex={-1}><div className="task-card-head"><div><div className="eyebrow">{report.period.toUpperCase()} REPORT · {report.periodStart}</div><h3>{report.staffName}</h3></div><span className={`status status-${report.reviewStatus}`}>{report.reviewStatus.replaceAll('_',' ')}</span></div><p><b>Completed:</b> {report.completedWork}</p><p><b>Outstanding:</b> {report.outstandingWork}</p>{report.blockers&&<p><b>Blockers:</b> {report.blockers}</p>}{report.plans&&<p><b>Next steps:</b> {report.plans}</p>}{report.reviewNote&&<div className="notice notice-info">Review: {report.reviewNote}</div>}{(session.role==='owner'||session.role==='manager')&&report.staffId!==session.staffId&&report.reviewStatus==='submitted'&&<div className="task-actions"><button className="btn btn-primary" onClick={()=>reviewActivityReport(report.reportId,'reviewed')}>Mark reviewed</button><button className="btn btn-outline" onClick={()=>reviewActivityReport(report.reportId,'revision_requested')}>Request revision</button></div>}<details className="task-history"><summary>Report history · {report.events.length} events</summary>{report.events.map((event)=><div className="task-event" key={event.eventId}><span><b>{event.actorName}</b> {event.eventType.replaceAll('_',' ')}</span><time>{prettyDate(event.created)}</time>{event.feedback&&<p>{event.feedback}</p>}</div>)}</details></article>)}</div>:<Empty title="No reports yet">Daily and weekly reports you can access will appear here.</Empty>}</section>
    <section className="section-panel" style={{marginTop:20}}><div className="section-head"><div><h2 className="section-title">Performance & workload</h2><p className="section-note">Actual task and support records; effort points are estimates, not a performance score.</p></div></div>{performanceQuery.isLoading?<LoadingRows/>:performanceQuery.isError?<ErrorState error={performanceQuery.error} retry={()=>performanceQuery.refetch()}/>:<div className="performance-table-wrap"><table className="performance-table"><thead><tr><th>Staff</th><th>Active load</th><th>Approved</th><th>Overdue</th><th>On time</th><th>Revision requests</th><th>Support cases</th><th>Replies sent</th></tr></thead><tbody>{performanceQuery.data?.metrics.map((metric)=><tr key={metric.staffId}><td>{metric.staffName}</td><td>{metric.activeTasks} tasks · {metric.activeEffortPoints} effort</td><td>{metric.approvedTasks} tasks · {metric.approvedEffortPoints} effort</td><td>{metric.overdueTasks}</td><td>{metric.onTimeApprovals}</td><td>{metric.revisionRequests}</td><td>{metric.supportCases} total · {metric.openSupportCases} open</td><td>{metric.supportReplies}</td></tr>)}</tbody></table></div>}</section>
    </details>
  </main>;
}

function TaskEditForm({
  task, teams, staff, onSaved, onError,
}: {
  task: StaffTask;
  teams: StaffTeam[];
  staff: PortalStaff[];
  onSaved: () => void | Promise<void>;
  onError: (message: string) => void;
}) {
  const update = useUpdateStaffTask();
  const [title, setTitle] = useState(task.title);
  const [instructions, setInstructions] = useState(task.instructions);
  const [priority, setPriority] = useState(task.priority as 'low'|'normal'|'high'|'urgent');
  const [effortPoints, setEffortPoints] = useState(task.effortPoints);
  const [dueAt, setDueAt] = useState(task.dueAt ? new Date(task.dueAt).toISOString().slice(0,16) : '');
  const [teamId, setTeamId] = useState(task.teamId ?? '');
  const [assignedStaffId, setAssignedStaffId] = useState(task.assignedStaffId ?? '');
  useEffect(() => {
    setTitle(task.title); setInstructions(task.instructions);
    setPriority(task.priority as typeof priority); setEffortPoints(task.effortPoints);
    setDueAt(task.dueAt ? new Date(task.dueAt).toISOString().slice(0,16) : '');
    setTeamId(task.teamId ?? ''); setAssignedStaffId(task.assignedStaffId ?? '');
  }, [task.taskId, task.updated]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    update.mutate({ taskId: task.taskId, data: {
      expectedUpdatedAt: task.updated, title: title.trim(), instructions: instructions.trim(),
      priority, effortPoints, dueAt: dueAt ? new Date(dueAt).toISOString() : null,
      teamId: teamId || null, assignedStaffId: assignedStaffId || null,
    } }, {
      onSuccess: () => { void onSaved(); },
      onError: (error) => onError(errMessage(error, 'Task changes could not be saved.')),
    });
  };
  return <details className="task-edit-panel"><summary>Edit task details, assignment, deadline, or effort</summary><form onSubmit={submit} className="report-form">
    <div className="form-field"><label className="form-label">Title</label><input className="field-input" required minLength={3} maxLength={120} value={title} onChange={(e)=>setTitle(e.target.value)}/></div>
    <div className="form-field"><label className="form-label">Instructions</label><textarea className="reply-area" required maxLength={4000} value={instructions} onChange={(e)=>setInstructions(e.target.value)}/></div>
    <div className="form-grid">
      <div className="form-field"><label className="form-label">Priority</label><select className="field-select" value={priority} onChange={(e)=>setPriority(e.target.value as typeof priority)}><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select></div>
      <div className="form-field"><label className="form-label">Estimated effort / difficulty</label><select className="field-select" value={effortPoints} onChange={(e)=>setEffortPoints(Number(e.target.value))}>{[1,2,3,4,5].map((value)=><option key={value} value={value}>{value} / 5</option>)}</select></div>
      <div className="form-field"><label className="form-label">Team</label><select className="field-select" value={teamId} onChange={(e)=>setTeamId(e.target.value)}><option value="">No team</option>{teams.map((team)=><option key={team.teamId} value={team.teamId}>{team.name}</option>)}</select></div>
      <div className="form-field"><label className="form-label">Assigned agent</label><select className="field-select" value={assignedStaffId} onChange={(e)=>setAssignedStaffId(e.target.value)}><option value="">Team task</option>{staff.filter((person)=>person.active&&person.role==='agent').map((person)=><option key={person.staffId} value={person.staffId}>{person.displayName}</option>)}</select></div>
      <div className="form-field"><label className="form-label">Deadline</label><input className="field-input" type="datetime-local" value={dueAt} onChange={(e)=>setDueAt(e.target.value)}/></div>
    </div>
    <button className="btn btn-primary" type="submit" disabled={update.isPending}>{update.isPending?'Saving…':'Save changes'}</button>
  </form></details>;
}

function CaseDetail({ session }: { session: PortalSession }) {
  const { caseId = '' } = useParams<{ caseId: string }>();
  return <SupportInbox session={session} initialCaseId={caseId}/>;
}

function TeamAccessPanel() {
  const client = useQueryClient();
  const teamsQuery = useListStaffTeams();
  const staffQuery = useListPortalStaff({ query: { queryKey: getListPortalStaffQueryKey() } });
  const createTeam = useCreateStaffTeam();
  const saveMembers = useSetStaffTeamMembers();
  const [teamName, setTeamName] = useState('');
  const [selectedTeamId, setSelectedTeamId] = useState('');
  const [managerIds, setManagerIds] = useState<string[]>([]);
  const [workerIds, setWorkerIds] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const activeStaff = (staffQuery.data?.staff ?? []).filter((person) => person.active);
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['/api/portal/teams'] }),
      client.invalidateQueries({ queryKey: getListPortalStaffQueryKey() }),
    ]);
  };
  const membersFor = (setter: (ids: string[]) => void) => (event: ChangeEvent<HTMLSelectElement>) => {
    setter(Array.from(event.target.selectedOptions, (option) => option.value));
  };
  const addTeam = (event: FormEvent) => {
    event.preventDefault(); setError(''); setMessage('');
    createTeam.mutate({ data: { name: teamName.trim() } }, {
      onSuccess: async (team) => { setTeamName(''); setSelectedTeamId(team.teamId); setMessage('Team created. Choose its members below.'); await refresh(); },
      onError: (failure) => setError(errMessage(failure, 'The team could not be created.')),
    });
  };
  const saveTeam = (event: FormEvent) => {
    event.preventDefault();
    if (!selectedTeamId) return;
    const members = [
      ...managerIds.map((staffId) => ({ staffId, teamRole: 'manager' as const })),
      ...workerIds.map((staffId) => ({ staffId, teamRole: 'worker' as const })),
    ];
    setError(''); setMessage('');
    saveMembers.mutate({ teamId: selectedTeamId, data: { members } }, {
      onSuccess: async () => { setMessage('Team permissions saved.'); await refresh(); },
      onError: (failure) => setError(errMessage(failure, 'Team permissions could not be saved.')),
    });
  };
  return <details className="section-panel advanced-section staff-advanced" id="team-access">
    <summary>Manage teams and permissions</summary>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    {message && <div className="notice notice-info" role="status">{message}</div>}
    <div className="staff-advanced-body">
      <p className="section-note">Choose which managers and workers can access each team.</p>
      <form onSubmit={addTeam} className="create-team-form">
        <input className="field-input" aria-label="New team name" placeholder="New team name" maxLength={80} value={teamName} onChange={(event)=>setTeamName(event.target.value)} required/>
        <button className="btn btn-outline" type="submit" disabled={createTeam.isPending}>{createTeam.isPending ? 'Creating…' : 'Create team'}</button>
      </form>
      <form onSubmit={saveTeam}>
        <div className="form-field"><label className="form-label" htmlFor="team-select">Team</label><select id="team-select" className="field-select" value={selectedTeamId} onChange={(event)=>{const id=event.target.value;setSelectedTeamId(id);const team=teamsQuery.data?.teams.find((item)=>item.teamId===id);setManagerIds(team?.members.filter((member)=>member.teamRole==='manager').map((member)=>member.staffId) ?? []);setWorkerIds(team?.members.filter((member)=>member.teamRole==='worker').map((member)=>member.staffId) ?? []);}}><option value="">Choose a team</option>{(teamsQuery.data?.teams ?? []).map((team)=><option key={team.teamId} value={team.teamId}>{team.name}</option>)}</select></div>
        <div className="form-grid"><div className="form-field"><label className="form-label" htmlFor="team-managers">Authorized managers</label><select id="team-managers" className="field-select" multiple size={4} value={managerIds} onChange={membersFor(setManagerIds)}>{activeStaff.filter((person)=>person.role==='manager').map((person)=><option key={person.staffId} value={person.staffId}>{person.displayName}</option>)}</select></div><div className="form-field"><label className="form-label" htmlFor="team-workers">Team workers</label><select id="team-workers" className="field-select" multiple size={4} value={workerIds} onChange={membersFor(setWorkerIds)}>{activeStaff.filter((person)=>person.role==='agent').map((person)=><option key={person.staffId} value={person.staffId}>{person.displayName}</option>)}</select></div></div>
        <button className="btn btn-outline btn-large" type="submit" disabled={!selectedTeamId || saveMembers.isPending}>{saveMembers.isPending ? 'Saving…' : 'Save permissions'}</button>
      </form>
    </div>
  </details>;
}

function staffTaskCounts(staffId: string, tasks: StaffTask[], teams: StaffTeam[]) {
  const workerTeamIds = new Set(teams
    .filter((team) => team.members.some((member) => member.staffId === staffId && member.teamRole === 'worker'))
    .map((team) => team.teamId));
  const assigned = tasks.filter((task) => task.assignedStaffId === staffId
    || (!task.assignedStaffId && Boolean(task.teamId && workerTeamIds.has(task.teamId))));
  return {
    assigned: assigned.length,
    completed: assigned.filter((task) => task.status === 'approved').length,
    workload: assigned.filter((task) => !['approved', 'cancelled'].includes(task.status)).length,
  };
}

function StaffWorkloadPanel({ people, tasks, teams, loading, error, retry }: {
  people: StaffPerformanceRow[];
  tasks: StaffTask[];
  teams: StaffTeam[];
  loading: boolean;
  error: unknown;
  retry: () => void;
}) {
  if (loading) return <section className="section-panel"><div className="section-head"><h2 className="section-title">Team workload</h2></div><LoadingRows/></section>;
  if (error) return <section className="section-panel"><div className="section-head"><h2 className="section-title">Team workload</h2></div><ErrorState error={error} retry={retry}/></section>;
  return <section className="section-panel" data-testid="staff-workload">
    <div className="section-head"><div><h2 className="section-title">Team workload</h2><p className="section-note">Current task counts from the staff task records.</p></div></div>
    {!people.length ? <Empty title="No workers to show">Workers in your authorized scope will appear here.</Empty> : <div className="staff-workload-list">
      {people.map((person) => {
        const counts = staffTaskCounts(person.staffId, tasks, teams);
        return <article className="staff-workload-row" key={person.staffId} data-testid={`staff-workload-${person.staffId}`}>
          <div className="staff-workload-person"><span className="person-avatar">{initials(person.staffName)}</span><strong>{person.staffName}</strong></div>
          <div className="staff-workload-count"><span>Assigned tasks</span><strong>{counts.assigned}</strong></div>
          <div className="staff-workload-count"><span>Completed</span><strong>{counts.completed}</strong></div>
          <div className="staff-workload-count"><span>Current workload</span><strong>{counts.workload}</strong></div>
        </article>;
      })}
    </div>}
  </section>;
}

function TeamStaffOverview() {
  const performanceQuery = useGetStaffPerformance();
  const tasksQuery = useListStaffTasks();
  const teamsQuery = useListStaffTeams();
  const workerIds = new Set((teamsQuery.data?.teams ?? []).flatMap((team) =>
    team.members.filter((member) => member.teamRole === 'worker').map((member) => member.staffId)));
  const people = (performanceQuery.data?.metrics ?? []).filter((person) => workerIds.has(person.staffId));
  const error = performanceQuery.error ?? tasksQuery.error ?? teamsQuery.error;
  return <main className="page">
    <div className="page-heading"><div><div className="eyebrow">YOUR AUTHORIZED TEAM</div><h1>Staff</h1><p className="subheading">See the task load and completed work for workers in your teams.</p></div></div>
    <StaffWorkloadPanel people={people} tasks={tasksQuery.data?.tasks ?? []} teams={teamsQuery.data?.teams ?? []} loading={performanceQuery.isLoading || tasksQuery.isLoading || teamsQuery.isLoading} error={error} retry={()=>{void Promise.all([performanceQuery.refetch(),tasksQuery.refetch(),teamsQuery.refetch()]);}}/>
  </main>;
}

function StaffManagement() {
  const client = useQueryClient();
  const staffQuery = useListPortalStaff({ query: { queryKey: getListPortalStaffQueryKey(), staleTime: 15_000 } });
  const performanceQuery = useGetStaffPerformance();
  const tasksQuery = useListStaffTasks();
  const teamsQuery = useListStaffTeams();
  const create = useCreatePortalStaff();
  const update = useUpdatePortalStaff();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<'manager' | 'agent'>('agent');
  const [createdPassword, setCreatedPassword] = useState('');
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [filter, setFilter] = useState('');
  const workerIds = new Set((staffQuery.data?.staff ?? []).filter((person) => person.role === 'agent').map((person) => person.staffId));
  const workloadPeople = (performanceQuery.data?.metrics ?? []).filter((person) => workerIds.has(person.staffId));
  const submit = (event: FormEvent) => {
    event.preventDefault(); setError(''); setInfo('');
    create.mutate({ data: { displayName: name.trim(), email: email.trim(), role } }, { onSuccess: async (result) => {
      trackEvent('staff_account_created', { role });
      setCreatedPassword(result.temporaryPassword); setName(''); setEmail(''); setRole('agent');
      await client.invalidateQueries({ queryKey: getListPortalStaffQueryKey() });
    }, onError: (failure) => setError(errMessage(failure, 'Staff account could not be created.')) });
  };
  const changeActive = (member: PortalStaff) => {
    const nextActive = !member.active;
    if (!window.confirm(`${nextActive ? 'Activate' : 'Deactivate'} ${member.displayName}'s staff account?`)) return;
    setError(''); setInfo('');
    update.mutate({ staffId: member.staffId, data: { active: nextActive } }, { onSuccess: async () => {
      trackEvent('staff_account_status_changed', { active: nextActive });
      setInfo(`${member.displayName}'s account is now ${nextActive ? 'active' : 'deactivated'}.`);
      await client.invalidateQueries({ queryKey: getListPortalStaffQueryKey() });
    }, onError: (failure) => setError(errMessage(failure, 'Account status could not be changed.')) });
  };
  const members = (staffQuery.data?.staff ?? []).filter((person) => `${person.displayName} ${person.email}`.toLowerCase().includes(filter.toLowerCase()));
  return <main className="page"><div className="page-heading"><div><div className="eyebrow">ADMINISTRATION</div><h1>Staff</h1><p className="subheading">Review workload, manage staff accounts, and set team permissions.</p></div><button className="btn btn-primary btn-large" onClick={() => { setCreatedPassword(''); setError(''); setOpen(true); }} data-testid="button-create-staff"><Plus size={15}/>Create staff account</button></div>
     {error && <div className="notice notice-error" role="alert" data-testid="status-staff-error">{error}</div>}{info && <div className="notice notice-info" role="status" data-testid="status-staff-success">{info}</div>}
    <StaffWorkloadPanel people={workloadPeople} tasks={tasksQuery.data?.tasks ?? []} teams={teamsQuery.data?.teams ?? []} loading={staffQuery.isLoading || performanceQuery.isLoading || tasksQuery.isLoading || teamsQuery.isLoading} error={staffQuery.error ?? performanceQuery.error ?? tasksQuery.error ?? teamsQuery.error} retry={()=>{void Promise.all([staffQuery.refetch(),performanceQuery.refetch(),tasksQuery.refetch(),teamsQuery.refetch()]);}}/>
    <details className="advanced-section" id="staff-account-management"><summary>Manage staff accounts</summary>
    <section className="section-panel"><div className="section-head"><div><h2 className="section-title">Staff accounts</h2><p className="section-note">{staffQuery.data ? `${staffQuery.data.staff.length} accounts` : 'Owner access only'}</p></div><div className="search-wrap"><Search/><input className="search-input" type="search" placeholder="Find staff" value={filter} onChange={(event) => setFilter(event.target.value)} data-testid="input-staff-search"/></div></div>
      {staffQuery.isLoading ? <LoadingRows/> : staffQuery.isError ? <ErrorState error={staffQuery.error} retry={() => staffQuery.refetch()}/> : members.length === 0 ? <Empty title={filter ? 'No staff found' : 'No staff accounts'}>{filter ? 'Try searching by another name or email address.' : 'Create an account to give a team member access to the support portal.'}</Empty> : <div className="table-wrap"><table className="case-table staff-table" data-testid="table-staff"><thead><tr><th>Staff member</th><th>Role</th><th>Account status</th><th>Last sign in</th><th>Created</th><th></th></tr></thead><tbody>{members.map((person) => <tr key={person.staffId} data-testid={`row-staff-${person.staffId}`}><td><div className="staff-row"><span className="person-avatar">{initials(person.displayName)}</span><div><div style={{fontWeight:600,color:'#35483e'}}>{person.displayName}</div><div className="muted-small">{person.email}</div></div></div></td><td><span className="role-pill">{person.role}</span>{person.mustChangePassword && <div className="muted-small">Password update required</div>}</td><td><span className={`active-state ${person.active ? '' : 'inactive'}`}>{person.active ? 'Active' : 'Deactivated'}</span></td><td>{prettyDate(person.lastLogin)}</td><td>{prettyDate(person.created)}</td><td><button className={`btn ${person.active ? 'btn-outline' : 'btn-primary'}`} onClick={() => changeActive(person)} disabled={update.isPending} data-testid={`button-toggle-staff-${person.staffId}`}>{person.active ? 'Deactivate' : 'Activate'}</button></td></tr>)}</tbody></table></div>}
    </section>
    </details>
    <TeamAccessPanel/>
     {open && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !create.isPending) setOpen(false); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title">
       {!createdPassword ? <><button className="btn btn-quiet" style={{float:'right',padding:5}} onClick={() => setOpen(false)} aria-label="Close" data-testid="button-close-create-staff"><X size={17}/></button><div className="eyebrow">NEW STAFF MEMBER</div><h2 id="create-title">Create an account</h2><p className="modal-copy">An administrator-created account is required to access the support portal. A temporary password will be shown once.</p>{error && <div className="notice notice-error">{error}</div>}<form onSubmit={submit}><div className="form-field"><label className="form-label" htmlFor="staff-name">Display name</label><input id="staff-name" className="field-input" required maxLength={80} value={name} onChange={(event)=>setName(event.target.value)} data-testid="input-staff-name"/></div><div className="form-field"><label className="form-label" htmlFor="staff-email">Work email</label><input id="staff-email" className="field-input" type="email" required maxLength={254} value={email} onChange={(event)=>setEmail(event.target.value)} data-testid="input-staff-email"/></div><div className="form-field"><label className="form-label" htmlFor="staff-role">Staff role</label><select id="staff-role" className="field-select" value={role} onChange={(event)=>setRole(event.target.value as 'manager' | 'agent')} data-testid="select-staff-role"><option value="agent">Support Agent</option><option value="manager">Support Manager</option></select></div><div className="modal-actions"><button type="button" className="btn btn-outline" onClick={()=>setOpen(false)} data-testid="button-cancel-create-staff">Cancel</button><button type="submit" className="btn btn-primary" disabled={create.isPending} data-testid="button-submit-create-staff">{create.isPending ? 'Creating…' : 'Create account'}</button></div></form></> : <><div className="empty-mark"><Check size={19}/></div><div className="eyebrow">ACCOUNT CREATED</div><h2 id="create-title">Share temporary password</h2><p className="modal-copy">Provide this password to the staff member through a secure channel. They will be asked to set a new password when they sign in.</p><div className="temp-password" data-testid="text-temporary-password">{createdPassword}</div><p className="modal-copy" style={{marginTop:12,marginBottom:0}}>This temporary password will not be shown again after you close this window.</p><div className="modal-actions"><button className="btn btn-primary" onClick={()=>setOpen(false)} data-testid="button-dismiss-temp-password">Done</button></div></>}
    </div></div>}
  </main>;
}

function PasswordPage({ session }: { session: PortalSession }) {
  const client = useQueryClient();
  const mutation = useChangePortalPassword();
  const [currentPassword, setCurrent] = useState('');
  const [newPassword, setNew] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const submit = (event: FormEvent) => {
    event.preventDefault(); setError(''); setSuccess('');
    if (newPassword.length < 12) { setError('Choose a password with at least 12 characters.'); return; }
    if (newPassword !== confirm) { setError('The new passwords do not match.'); return; }
    mutation.mutate({ data: { currentPassword, newPassword } }, { onSuccess: async (updated) => { client.setQueryData(sessionKey, updated); await client.invalidateQueries({ queryKey: sessionKey }); setCurrent(''); setNew(''); setConfirm(''); setSuccess('Your password has been changed.'); }, onError: (failure) => setError(errMessage(failure, 'Password could not be changed. Check your current password and try again.')) });
  };
  return <main className="page"><div className="page-heading"><div><div className="eyebrow">ACCOUNT SECURITY</div><h1>{session.mustChangePassword ? 'Set a new password' : 'Change password'}</h1><p className="subheading">{session.mustChangePassword ? 'Your administrator issued a temporary password. Replace it before continuing.' : 'Keep your staff account protected with a private password.'}</p></div></div>
    <section className="section-panel" style={{maxWidth:650}}><div className="section-head"><div><h2 className="section-title">Password details</h2><p className="section-note">Your new password must be at least 12 characters.</p></div><div className="stat-icon"><ShieldCheck size={17}/></div></div><form style={{padding:'22px 24px'}} onSubmit={submit}>
      {session.mustChangePassword && <div className="notice notice-info" data-testid="status-password-required">A password update is required to access support cases and staff tools.</div>}
      {error && <div className="notice notice-error" role="alert" data-testid="status-password-error">{error}</div>}{success && <div className="notice notice-info" role="status" data-testid="status-password-success">{success}</div>}
      <div className="form-field"><label className="form-label" htmlFor="current-password">Current password</label><input id="current-password" className="field-input" type="password" autoComplete="current-password" required maxLength={256} value={currentPassword} onChange={(event)=>setCurrent(event.target.value)} data-testid="input-current-password"/></div>
      <div className="form-field"><label className="form-label" htmlFor="new-password">New password</label><input id="new-password" className="field-input" type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={newPassword} onChange={(event)=>setNew(event.target.value)} data-testid="input-new-password"/></div>
      <div className="form-field"><label className="form-label" htmlFor="confirm-password">Confirm new password</label><input id="confirm-password" className="field-input" type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={confirm} onChange={(event)=>setConfirm(event.target.value)} data-testid="input-confirm-password"/></div>
      <div style={{display:'flex',justifyContent:'flex-end',marginTop:20}}><button className="btn btn-primary" type="submit" disabled={mutation.isPending} data-testid="button-change-password">{mutation.isPending ? 'Updating password…' : 'Update password'}<ChevronRight size={14}/></button></div>
    </form></section>
  </main>;
}

function AccessDenied({ returnPath = '/staff/support' }: { returnPath?: string }) {
  const [, navigate] = useLocation();
  return <main className="page"><div className="unauthorized"><div className="empty-mark"><ShieldCheck size={20}/></div><h1>Administrator access required</h1><p>This area is limited to administrator accounts. If you need staff access changed, contact your VAYDA administrator.</p><button className="btn btn-outline" onClick={()=>navigate(returnPath)} data-testid="button-return-queue"><ArrowLeft size={14}/>Return to your dashboard</button></div></main>;
}

function ProtectedRouter({ session }: { session: PortalSession }) {
  const [location, navigate] = useLocation();
  const shouldReturnToDashboard = !session.mustChangePassword
    && (location === '/' || location === '/support' || location === '/login' || location === '/staff/login');
  useEffect(() => {
    if (session.mustChangePassword && location !== '/account/password') navigate('/account/password');
    else if (shouldReturnToDashboard) navigate(session.dashboardPath);
  }, [session.mustChangePassword, shouldReturnToDashboard, session.dashboardPath, location, navigate]);
  if ((session.mustChangePassword && location !== '/account/password') || shouldReturnToDashboard) return <div className="page"><div className="skeleton" style={{width:220,height:24}}/></div>;
  if (location === '/operations' || location.startsWith('/operations/')) {
    const routeBase = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/operations`;
    return session.role === 'owner'
      ? <OperationsApp routeBase={routeBase} />
      : <AccessDenied returnPath={session.dashboardPath}/>;
  }
  if (!session.mustChangePassword && location === '/account/password') {
    // Password page remains reachable for voluntary changes.
  }
  return <AppShell session={session}><Switch>
    <Route path="/staff/support/website-chats">{() => <SupportInbox session={session}/>}</Route>
    <Route path="/staff/support">{() => <Queue session={session}/>}</Route>
    <Route path="/staff/announcements">{() => import.meta.env.DEV && (session.role === 'owner' || session.role === 'manager') ? <StaffAnnouncements session={session}/> : <AccessDenied/>}</Route>
    <Route path="/bot-control">{() => session.role === 'owner' ? <BotControl/> : <AccessDenied/>}</Route>
    <Route path="/command-center/member-access">{() => session.role === 'owner' ? <MemberAccessPage/> : <AccessDenied/>}</Route>
    <Route path="/command-center/pro-access">{() => session.role === 'owner' ? <ProAccessReview/> : <AccessDenied/>}</Route>
    <Route path="/command-center/education-videos">{() => session.role === 'owner' ? <EducationVideos/> : <AccessDenied/>}</Route>
    <Route path="/command-center/mind-map">{() => session.role === 'owner' ? <OwnerMindMap/> : <AccessDenied/>}</Route>
    <Route path="/command-center/member-course-videos">{() => session.role === 'owner' ? <OwnerMemberCourseVideos/> : <AccessDenied/>}</Route>
    <Route path="/command-center/channel-history">{() => session.role === 'owner' ? <ChannelHistory/> : <AccessDenied/>}</Route>
    <Route path="/trades">{() => session.role === 'owner' ? <TradeManagement/> : <AccessDenied/>}</Route>
    <Route path="/signals">{() => session.role === 'owner' && import.meta.env.DEV ? <Signals/> : <AccessDenied/>}</Route>
    <Route path="/command-center">{() => session.role === 'owner' ? <CommandCenter session={session}/> : <AccessDenied/>}</Route>
    <Route path="/tasks">{() => <TaskCenter session={session}/>}</Route>
    <Route path="/cases/:caseId">{() => <CaseDetail session={session}/>}</Route>
    <Route path="/staff">{session.role === 'owner' ? <StaffManagement/> : session.role === 'manager' ? <TeamStaffOverview/> : <AccessDenied/>}</Route>
    <Route path="/account/password"><PasswordPage session={session}/></Route>
    <Route component={NotFound}/>
  </Switch></AppShell>;
}

function PortalRoot() {
  const [, navigate] = useLocation();
  const session = useGetPortalSession({ query: { queryKey: sessionKey, refetchOnMount: 'always', retry: false, staleTime: 0 } });
  useEffect(() => {
    if (session.isError && isUnauthorized(session.error)) navigate('/login');
    else if (!session.isLoading && !session.isError && !session.data) navigate('/login');
  }, [session.isError, session.error, session.isLoading, session.data, navigate]);
  if (session.isLoading) return <div className="login-screen"><section className="login-aside"><div className="login-brand"><Brand/></div><div className="login-copy"><div className="eyebrow" style={{color:'#d5b56f'}}>STAFF SUPPORT PORTAL</div><h1>Clear answers.<br/>Thoughtful support.</h1></div></section><section className="login-panel"><div className="login-form"><div className="skeleton" style={{width:90}}/><div className="skeleton" style={{width:250,height:30,marginTop:17}}/><div className="skeleton" style={{width:'100%',height:43,marginTop:28}}/><div className="skeleton" style={{width:'100%',height:43,marginTop:12}}/></div></section></div>;
  if (session.isError) {
    if (isUnauthorized(session.error)) return null;
    return <div className="unauthorized"><h1>Portal unavailable</h1><p>{errMessage(session.error)}</p><button className="btn btn-outline" onClick={()=>session.refetch()} data-testid="button-retry-session">Try again</button></div>;
  }
  if (!session.data) return null;
  return <ProtectedRouter session={session.data}/>;
}

function RoutedErrorBoundary({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>;
}

function HomeRedirect() {
  const [, navigate] = useLocation();
  const { isLoaded, isSignedIn } = useAuth();
  const staff = useGetPortalSession({ query: { queryKey: sessionKey, refetchOnMount: 'always', retry: false, staleTime: 0 } });
  const member = useGetMemberSession({
    query: { queryKey: getGetMemberSessionQueryKey(), enabled: isLoaded && isSignedIn === true, retry: false },
  });
  useEffect(() => {
    if (staff.data) navigate(staff.data.mustChangePassword ? '/account/password' : staff.data.dashboardPath);
    else if (member.data?.learningDashboard) navigate(member.data.dashboardPath);
  }, [staff.data, member.data, navigate]);
  return <PublicSite/>;
}

function LegacyLoginRedirect() {
  const [, navigate] = useLocation();
  useEffect(() => navigate('/login', { replace: true }), [navigate]);
  return null;
}

function memberSignupError(value: unknown, fallback: string) {
  if (value instanceof Error && value.message) return value.message;
  if (value && typeof value === 'object') {
    const candidate = value as {
      message?: string;
      errors?: Array<{ longMessage?: string; message?: string }>;
    };
    return candidate.errors?.[0]?.longMessage
      ?? candidate.errors?.[0]?.message
      ?? candidate.message
      ?? fallback;
  }
  return fallback;
}

// The owner approved reopening member self-registration in Development and Production.
const MEMBER_SELF_SIGNUP_ENABLED = true;

function MemberSignUpPage() {
  return MEMBER_SELF_SIGNUP_ENABLED
    ? <MemberSignUpFlow />
    : <MemberSignUpPausedPage />;
}

function MemberSignUpPausedPage() {
  const [, navigate] = useLocation();
  return <main className="login-screen">
    <section className="login-aside">
      <div className="login-brand"><Brand /></div>
      <div className="login-copy">
        <div className="eyebrow" style={{ color: '#d5b56f' }}>MEMBER ACCESS</div>
        <h1>Registration is paused.</h1>
        <p>New member accounts are not being accepted right now. Existing members can continue to sign in.</p>
      </div>
    </section>
    <section className="login-panel">
      <div className="login-form">
        <div className="eyebrow">ACCOUNT CREATION</div>
        <h2>Sign-up is temporarily unavailable</h2>
        <p data-testid="status-member-signup-unavailable">Your existing account and access are unchanged. Sign in to continue.</p>
        <button className="btn btn-primary" type="button" onClick={() => navigate('/login')} data-testid="button-signup-paused-login">Sign in <ChevronRight size={15} /></button>
        <button className="login-link-button" type="button" onClick={() => navigate('/')} data-testid="button-signup-paused-home">Back to website</button>
      </div>
    </section>
  </main>;
}

function MemberSignUpFlow() {
  const [location, navigate] = useLocation();
  const { isLoaded, isSignedIn } = useAuth();
  const { signUp, fetchStatus } = useSignUp();
  const clerk = useClerk();
  const client = useQueryClient();
  const [step, setStep] = useState<'details' | 'verification'>('details');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const staff = useGetPortalSession({
    query: { queryKey: sessionKey, refetchOnMount: 'always', retry: false, staleTime: 0 },
  });
  const member = useGetMemberSession({
    query: {
      queryKey: getGetMemberSessionQueryKey(),
      enabled: isLoaded && isSignedIn === true,
      retry: false,
    },
  });

  useEffect(() => {
    if (staff.data) {
      navigate(staff.data.mustChangePassword ? '/account/password' : staff.data.dashboardPath);
    } else if (member.data?.learningDashboard) {
      navigate(member.data.dashboardPath);
    }
  }, [staff.data, member.data, navigate]);

  useEffect(() => {
    if (location !== '/sign-up/verify-email') return;
    if (busy) return;
    if (signUp.id && signUp.emailAddress) {
      setStep('verification');
      setEmail(signUp.emailAddress);
      return;
    }
    setStep('details');
    setNotice('This verification session is no longer available. Enter your details to start again.');
    navigate('/sign-up', { replace: true });
  }, [location, signUp.id, signUp.emailAddress, busy, navigate]);

  const setField = (field: 'fullName' | 'email' | 'password' | 'code', value: string) => {
    if (field === 'fullName') setFullName(value);
    else if (field === 'email') setEmail(value);
    else if (field === 'password') setPassword(value);
    else setCode(value);
    setError('');
  };

  const submitDetails = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setNotice('');

    // Reading the submitted controls also captures browser/mobile autofill values
    // that may not have triggered React's controlled-input change handler.
    const formData = new FormData(event.currentTarget);
    const submittedName = String(formData.get('name') ?? '').trim();
    const submittedEmail = String(formData.get('email') ?? '').trim().toLowerCase();
    const submittedPassword = String(formData.get('password') ?? '');
    setFullName(submittedName);
    setEmail(submittedEmail);
    setPassword(submittedPassword);

    const nameParts = submittedName.split(/\s+/).filter(Boolean);
    if (nameParts.length === 0) {
      setError('Enter your full name to continue.');
      return;
    }
    const emailInput = event.currentTarget.elements.namedItem('email');
    if (!submittedEmail || !(emailInput instanceof HTMLInputElement) || !emailInput.checkValidity()) {
      setError('Enter a valid email address to continue.');
      return;
    }
    if (!submittedPassword) {
      setError('Enter a password to create your member account.');
      return;
    }
    if (!isLoaded || fetchStatus === 'fetching') {
      setError('Account registration is still loading. Try again in a moment.');
      return;
    }

    setBusy(true);
    try {
      if (signUp.id) await signUp.reset();
      const result = await signUp.password({
        emailAddress: submittedEmail,
        password: submittedPassword,
        unsafeMetadata: { fullName: submittedName },
      });
      if (result.error) throw result.error;

      setPassword('');
      setCode('');
      setStep('verification');
      navigate('/sign-up/verify-email');

      const sent = await signUp.verifications.sendEmailCode();
      if (sent.error) throw sent.error;
      setNotice('A verification code has been sent. Your dashboard stays locked until your email is verified.');
    } catch (failure) {
      setError(memberSignupError(failure, 'We could not start registration. Check your details and try again.'));
    } finally {
      setBusy(false);
    }
  };

  const verifyEmail = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const verified = await signUp.verifications.verifyEmailCode({ code: code.trim() });
      if (verified.error) throw verified.error;

      const finalized = await signUp.finalize();
      if (finalized.error) throw finalized.error;

      const session = await getMemberSession();
      if (!session.learningDashboard) {
        throw Object.assign(new Error('This account does not currently have a member learning dashboard entitlement.'), { status: 403 });
      }
      client.setQueryData(getGetMemberSessionQueryKey(), session);
      await client.invalidateQueries({ queryKey: getGetMemberSessionQueryKey() });
      navigate(session.dashboardPath, { replace: true });
    } catch (failure) {
      const status = (failure as { status?: number })?.status;
      if (status === 401 || status === 403) {
        await clerk.signOut().catch(() => undefined);
        client.clear();
        setError('This account is not eligible for the member dashboard. Staff access is assigned separately by the owner; PRO access is never automatic.');
      } else {
        setError(memberSignupError(failure, 'That code could not be verified. Request a new code and try again.'));
      }
    } finally {
      setBusy(false);
    }
  };

  const resendCode = async () => {
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const sent = await signUp.verifications.sendEmailCode();
      if (sent.error) throw sent.error;
      setNotice('A new verification code has been sent. Check the email address shown above.');
    } catch (failure) {
      setError(memberSignupError(failure, 'The code could not be resent. Wait a moment and try again.'));
    } finally {
      setBusy(false);
    }
  };

  const returnToDetails = async () => {
    setError('');
    setNotice('');
    setCode('');
    setStep('details');
    navigate('/sign-up');
  };

  const changeDetails = async () => {
    setError('');
    setNotice('');
    setCode('');
    await signUp.reset();
    setStep('details');
    navigate('/sign-up');
  };

  if (staff.isLoading || !isLoaded || (isSignedIn && member.isLoading)) {
    return <main className="member-experience mx-signup-loading" aria-label="Checking account access"><div className="skeleton" style={{ width: 260, height: 28 }}/></main>;
  }
  if (staff.data || member.data?.learningDashboard) return null;
  if (member.data && !member.data.learningDashboard) {
    return <main className="member-experience mx-signup-loading"><section className="mx-signup-panel mx-access-unavailable" role="alert">
      <div className="mx-overline"><span className="mx-live-mark"/> ACCESS CHECK</div>
      <h1>Dashboard access not assigned</h1>
      <p>This account has no assigned member learning dashboard. Staff or PRO access will not be granted automatically.</p>
      <div className="mx-access-actions">
        <Link className="mx-button mx-button-quiet" href="/">Return to the public website</Link>
        <button className="mx-button mx-button-gold" type="button" onClick={() => void clerk.signOut({ redirectUrl: `${basePath}/` })}>Sign out</button>
      </div>
    </section></main>;
  }
  if (isSignedIn && member.isError) {
    return <main className="member-experience mx-signup-loading"><section className="mx-signup-panel mx-access-unavailable" role="alert">
      <div className="mx-overline"><span className="mx-live-mark"/> ACCESS CHECK</div>
      <h1>Member access unavailable</h1>
      <p>This account does not have member dashboard access. Staff access is assigned separately by the owner.</p>
      <div className="mx-access-actions">
        <Link className="mx-button mx-button-quiet" href="/">Return to the public website</Link>
        <button className="mx-button mx-button-gold" type="button" onClick={() => void clerk.signOut({ redirectUrl: `${basePath}/` })}>Sign out</button>
      </div>
    </section></main>;
  }

  return <MemberSignupExperience
    step={step}
    fullName={fullName}
    email={email}
    password={password}
    code={code}
    busy={busy || fetchStatus === 'fetching'}
    error={error}
    notice={notice}
    onFieldChange={setField}
    onSubmit={(event) => void submitDetails(event)}
    onVerify={(event) => void verifyEmail(event)}
    onResend={() => void resendCode()}
    onBack={() => void returnToDetails()}
    onChangeDetails={() => void changeDetails()}
  />;
}

function MemberAccountSettingsPage({ session }: { session: MemberSession }) {
  const [, navigate] = useLocation();
  const [telegramSettingsOpen, setTelegramSettingsOpen] = useState(false);
  return <main className="member-experience mx-settings-page">
    <div className="mx-settings-shell">
      <header className="mx-dashboard-header">
        <Link className="mx-wordmark" href="/" aria-label="Smart Money Hub home">
          <img className="mx-wordmark-image" src={`${basePath}/vayda-logo.png`} alt="" aria-hidden="true"/>
          <span><strong>VAYDA</strong><small>SMART MONEY HUB</small></span>
        </Link>
        <button className="mx-button mx-button-quiet" type="button" onClick={() => navigate('/member/dashboard')}><ChevronLeft size={15}/> Back to dashboard</button>
      </header>
      <section className="mx-settings-heading">
        <div className="mx-overline"><span className="mx-live-mark"/> MEMBER ACCOUNT</div>
        <h1>Account settings</h1>
        <p>Manage the email and security settings for {session.email}.</p>
      </section>
      <div className="mx-clerk-profile">
        <UserProfile routing="hash"/>
      </div>
      <details className="mx-settings-telegram" onToggle={(event) => setTelegramSettingsOpen(event.currentTarget.open)}>
        <summary>Optional Telegram link for PRO Signals</summary>
        <p>This is not needed for your member dashboard. It verifies the Telegram account used for PRO Signals checks; linking does not grant access.</p>
        {telegramSettingsOpen && <TelegramLinkWidget session={session}/>}
      </details>
    </div>
  </main>;
}

function ClerkQueryClientCacheInvalidator() {
  const { addListener } = useClerk();
  const client = useQueryClient();
  const previousUserId = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const unsubscribe = addListener(({ user }) => {
      const userId = user?.id ?? null;
      if (previousUserId.current !== undefined && previousUserId.current !== userId) client.clear();
      previousUserId.current = userId;
    });
    return unsubscribe;
  }, [addListener, client]);
  return null;
}

function Router() {
  const [location] = useLocation();
  const normalizedPath = location === '/' ? '/' : location.replace(/\/+$/, '');
  const publicRoutes = new Set([
    '/',
    '/about',
    '/education',
    '/market-analysis',
    '/philosophy',
    '/community',
    '/contact',
  ]);
  const isPublicRoute = publicRoutes.has(normalizedPath);

  useEffect(() => {
    const robots = document.querySelector<HTMLMetaElement>('meta[name="robots"]');
    if (robots) robots.content = isPublicRoute ? 'index, follow' : 'noindex, nofollow';
    if (!isPublicRoute) {
      document.title = normalizedPath === '/login' || normalizedPath === '/staff/login' || normalizedPath.startsWith('/sign-in')
        ? 'Sign In | VAYDA Smart Money Hub'
        : normalizedPath.startsWith('/sign-up')
          ? (MEMBER_SELF_SIGNUP_ENABLED
            ? 'Create Member Account | VAYDA Smart Money Hub'
            : 'Member Registration Paused | VAYDA Smart Money Hub')
        : normalizedPath === '/member/dashboard'
          ? 'Member Dashboard | VAYDA Smart Money Hub'
            : normalizedPath === '/member/learning'
              ? 'My Learning | VAYDA Smart Money Hub'
          : normalizedPath === '/member/calendar'
            ? 'Economic Calendar | VAYDA Smart Money Hub'
            : normalizedPath === '/member/journal'
              ? 'Trade Journal | VAYDA Smart Money Hub'
              : normalizedPath === '/member/coach'
                ? 'AI Coach | VAYDA Smart Money Hub'
                : normalizedPath === '/member/pro-signals'
                  ? 'PRO Signals | VAYDA Smart Money Hub'
          : normalizedPath === '/member/settings'
            ? 'Member Account Settings | VAYDA Smart Money Hub'
            : 'VAYDA Support Portal | Staff Workspace';
      document.querySelector('link[rel="canonical"]')?.remove();
      const description = document.querySelector<HTMLMetaElement>('meta[name="description"]');
      if (description) description.content = 'Private VAYDA account workspace. Access is assigned according to verified account permissions.';
    }
  }, [isPublicRoute, normalizedPath]);

  return <RoutedErrorBoundary><Switch>
    <Route path="/sign-in/*?" component={LegacyLoginRedirect}/>
    <Route path="/sign-up/*?" component={MemberSignUpPage}/>
    <Route path="/login" component={Login}/>
    <Route path="/staff/login" component={LegacyLoginRedirect}/>
    <Route path="/member/dashboard" component={MemberRoot}/>
    <Route path="/member/learning" component={MemberRoot}/>
    <Route path="/member/videos" component={MemberRoot}/>
    <Route path="/member/calendar" component={MemberRoot}/>
    <Route path="/member/journal" component={MemberRoot}/>
    <Route path="/member/coach" component={MemberRoot}/>
    <Route path="/member/pro-signals" component={MemberRoot}/>
    <Route path="/member/settings" component={MemberRoot}/>
    <Route>{() => isPublicRoute ? normalizedPath === '/' ? <HomeRedirect/> : <PublicSite/> : <PortalRoot/>}</Route>
  </Switch></RoutedErrorBoundary>;
}

function ClerkProviderWithRoutes() {
  const [, setLocation] = useLocation();
  return <ClerkProvider
    publishableKey={clerkPubKey}
    proxyUrl={clerkProxyUrl}
    appearance={clerkAppearance}
    signInUrl={`${basePath}/login`}
    signUpUrl={`${basePath}/sign-up`}
    localization={{
      signIn: { start: { title: 'Welcome back', subtitle: 'Sign in to access your account.' } },
      signUp: { start: { title: 'Create a member account', subtitle: 'Verified email is required for member access.' } },
    }}
    routerPush={(to) => setLocation(stripClerkBase(to))}
    routerReplace={(to) => setLocation(stripClerkBase(to), { replace: true })}
  >
    <ClerkQueryClientCacheInvalidator/>
    <Router/>
  </ClerkProvider>;
}
function App() {
  return <QueryClientProvider client={queryClient}><TooltipProvider><WouterRouter base={basePath}><ClerkProviderWithRoutes/></WouterRouter><Toaster/></TooltipProvider></QueryClientProvider>;
}
export default App;
