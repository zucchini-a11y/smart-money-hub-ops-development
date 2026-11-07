import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation } from 'wouter';
import {
  getGetMemberNotificationsQueryKey,
  useGetMemberNotifications,
  useMarkAllMemberNotificationsRead,
  useMarkMemberNotificationRead,
  useUpdateMemberNotificationPreferences,
} from '@workspace/api-client-react';
import type { MemberNotification, MemberNotificationPreferencesInput } from '@workspace/api-client-react';
import { useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  Bell,
  BookOpen,
  Check,
  CheckCheck,
  Clock3,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react';
import './member-notifications.css';

const daysOfWeek = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

type NotificationFilter = 'all' | 'unread';

function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function formatNotificationDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Date unavailable';
  return new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

function validTimezone(value: string) {
  try {
    return Boolean(value.trim()) && Intl.DateTimeFormat(undefined, { timeZone: value.trim() }).resolvedOptions().timeZone.length > 0;
  } catch {
    return false;
  }
}

function NotificationSkeleton() {
  return (
    <div className="mn-skeleton-list" aria-label="Loading notifications">
      {[0, 1, 2].map((item) => (
        <div className="mn-skeleton-row" key={item} aria-hidden="true">
          <span />
          <div><i /><i /><i /></div>
        </div>
      ))}
    </div>
  );
}

export function MemberNotificationsExperience() {
  const client = useQueryClient();
  const [, navigate] = useLocation();
  const queryKey = getGetMemberNotificationsQueryKey();
  const query = useGetMemberNotifications({
    query: { queryKey, retry: false, staleTime: 15_000 },
  });
  const markRead = useMarkMemberNotificationRead();
  const markAllRead = useMarkAllMemberNotificationsRead();
  const updatePreferences = useUpdateMemberNotificationPreferences();

  const initialTimezone = useMemo(browserTimezone, []);
  const [preferences, setPreferences] = useState<MemberNotificationPreferencesInput>({
    learningRemindersEnabled: false,
    reminderDayOfWeek: 0,
    reminderLocalTime: '09:00',
    timezone: initialTimezone,
  });
  const initialized = useRef(false);
  const [filter, setFilter] = useState<NotificationFilter>('all');
  const [busyNotificationIds, setBusyNotificationIds] = useState<Set<string>>(() => new Set());
  const [feedback, setFeedback] = useState<{ kind: 'success' | 'error'; message: string } | null>(null);
  const [timezoneError, setTimezoneError] = useState('');

  useEffect(() => {
    if (!query.data || initialized.current) return;
    initialized.current = true;
    const stored = query.data.preferences;
    setPreferences({
      learningRemindersEnabled: stored.learningRemindersEnabled ?? false,
      reminderDayOfWeek: stored.reminderDayOfWeek ?? 0,
      reminderLocalTime: stored.reminderLocalTime || '09:00',
      timezone: stored.updatedAt ? stored.timezone : initialTimezone,
    });
  }, [query.data, initialTimezone]);

  const notifications = query.data?.notifications ?? [];
  const unreadCount = query.data?.unreadCount ?? 0;
  const visibleNotifications = filter === 'unread'
    ? notifications.filter((notification) => !notification.readAt)
    : notifications;

  const setPreference = <K extends keyof MemberNotificationPreferencesInput>(
    key: K,
    value: MemberNotificationPreferencesInput[K],
  ) => {
    setPreferences((current) => ({ ...current, [key]: value }));
    setFeedback(null);
  };

  const refresh = async () => {
    setFeedback(null);
    await query.refetch();
  };

  const persistRead = async (notification: MemberNotification) => {
    if (notification.readAt || busyNotificationIds.has(notification.notificationId)) return;
    setBusyNotificationIds((current) => new Set(current).add(notification.notificationId));
    setFeedback(null);
    try {
      await markRead.mutateAsync({ notificationId: notification.notificationId });
      await client.invalidateQueries({ queryKey });
    } catch (failure) {
      setFeedback({
        kind: 'error',
        message: failure instanceof Error ? failure.message : 'This notification could not be marked as read. Try again.',
      });
    } finally {
      setBusyNotificationIds((current) => {
        const next = new Set(current);
        next.delete(notification.notificationId);
        return next;
      });
    }
  };

  const openNotification = async (notification: MemberNotification) => {
    if (!notification.readAt) {
      setBusyNotificationIds((current) => new Set(current).add(notification.notificationId));
      try {
        await markRead.mutateAsync({ notificationId: notification.notificationId });
        await client.invalidateQueries({ queryKey });
      } catch (failure) {
        setFeedback({
          kind: 'error',
          message: failure instanceof Error ? failure.message : 'This notification could not be opened. Try again.',
        });
        setBusyNotificationIds((current) => {
          const next = new Set(current);
          next.delete(notification.notificationId);
          return next;
        });
        return;
      }
    }
    navigate(notification.targetPath);
  };

  const handleMarkAllRead = async () => {
    setFeedback(null);
    try {
      await markAllRead.mutateAsync();
      await client.invalidateQueries({ queryKey });
      setFeedback({ kind: 'success', message: 'All notifications are marked as read.' });
    } catch (failure) {
      setFeedback({
        kind: 'error',
        message: failure instanceof Error ? failure.message : 'Notifications could not be marked as read. Try again.',
      });
    }
  };

  const savePreferences = async () => {
    const timezone = preferences.timezone.trim();
    if (!validTimezone(timezone)) {
      setTimezoneError('Enter a valid IANA timezone, such as America/New_York.');
      return;
    }
    setTimezoneError('');
    setFeedback(null);
    const payload = { ...preferences, timezone };
    try {
      const result = await updatePreferences.mutateAsync({ data: payload });
      setPreferences({
        learningRemindersEnabled: result.preferences.learningRemindersEnabled,
        reminderDayOfWeek: result.preferences.reminderDayOfWeek,
        reminderLocalTime: result.preferences.reminderLocalTime,
        timezone: result.preferences.timezone,
      });
      client.setQueryData(queryKey, (current: typeof query.data) => current
        ? { ...current, preferences: result.preferences }
        : current);
      setFeedback({ kind: 'success', message: 'Reminder preferences saved.' });
    } catch (failure) {
      setFeedback({
        kind: 'error',
        message: failure instanceof Error ? failure.message : 'Your preferences could not be saved. Try again.',
      });
    }
  };

  return (
    <main className="member-notifications">
      <div className="mn-shell">
        <header className="mn-header">
          <Link className="mn-brand" href="/member/dashboard" aria-label="Smart Money Hub member workspace">
            <span className="mn-brand-mark"><Bell size={17} strokeWidth={1.7} /></span>
            <span><strong>VAYDA</strong><small>SMART MONEY HUB</small></span>
          </Link>
          <nav className="mn-nav" aria-label="Member navigation">
            <Link href="/member/dashboard">Workspace</Link>
            <Link href="/member/learning">Learning</Link>
            <span className="is-current" aria-current="page">Notifications</span>
          </nav>
          <span className="mn-private-label"><ShieldCheck size={14} /> PRIVATE MEMBER SPACE</span>
        </header>

        <section className="mn-page-heading" aria-labelledby="mn-title">
          <div className="mn-overline"><span /> MEMBER / INBOX</div>
          <div className="mn-title-row">
            <div>
              <h1 id="mn-title">Notifications</h1>
              <p>Learning updates, kept in one quiet place.</p>
            </div>
            <div className="mn-unread-counter" aria-live="polite">
              <span className="mn-counter-number">{query.isLoading ? '—' : unreadCount}</span>
              <span>UNREAD</span>
            </div>
          </div>
        </section>

        {feedback && (
          <div className={`mn-feedback is-${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'}>
            {feedback.kind === 'success' ? <Check size={15} /> : <span className="mn-feedback-mark" aria-hidden="true">!</span>}
            <span>{feedback.message}</span>
            <button type="button" aria-label="Dismiss message" onClick={() => setFeedback(null)}>Dismiss</button>
          </div>
        )}

        <div className="mn-content-grid">
          <section className="mn-inbox-panel" aria-labelledby="mn-inbox-heading">
            <div className="mn-panel-heading">
              <div>
                <span className="mn-kicker">YOUR ACTIVITY</span>
                <h2 id="mn-inbox-heading">Recent notifications</h2>
              </div>
              <div className="mn-panel-actions">
                <button className="mn-icon-action" type="button" onClick={() => void refresh()} disabled={query.isFetching} aria-label="Refresh notifications" title="Refresh">
                  <RefreshCw size={15} className={query.isFetching ? 'is-refreshing' : ''} />
                </button>
                <button className="mn-mark-all" type="button" onClick={() => void handleMarkAllRead()} disabled={!unreadCount || markAllRead.isPending}>
                  <CheckCheck size={14} /> {markAllRead.isPending ? 'Marking…' : 'Mark all read'}
                </button>
              </div>
            </div>
            <div className="mn-list-toolbar">
              <span>{query.isLoading ? 'Checking your inbox' : `${notifications.length} ${notifications.length === 1 ? 'notification' : 'notifications'}`}</span>
              <div className="mn-filter-tabs" role="group" aria-label="Filter notifications">
                <button type="button" className={filter === 'all' ? 'is-selected' : ''} onClick={() => setFilter('all')} aria-pressed={filter === 'all'}>All</button>
                <button type="button" className={filter === 'unread' ? 'is-selected' : ''} onClick={() => setFilter('unread')} aria-pressed={filter === 'unread'}>Unread{unreadCount > 0 ? ` · ${unreadCount}` : ''}</button>
              </div>
            </div>

            {query.isLoading ? <NotificationSkeleton /> : query.isError ? (
              <div className="mn-state mn-error-state" role="alert">
                <span className="mn-state-icon"><RefreshCw size={19} /></span>
                <h3>Inbox unavailable</h3>
                <p>Your notifications could not be loaded. Check your connection and try again.</p>
                <button type="button" className="mn-button-secondary" onClick={() => void refresh()} disabled={query.isFetching}>Try again</button>
              </div>
            ) : visibleNotifications.length === 0 ? (
              <div className="mn-state">
                <span className="mn-state-icon">{filter === 'unread' ? <CheckCheck size={20} /> : <Bell size={20} />}</span>
                <h3>{filter === 'unread' ? 'You are all caught up' : 'Your inbox is clear'}</h3>
                <p>{filter === 'unread' ? 'There are no unread notifications right now.' : 'When there is a learning update, it will appear here.'}</p>
                {filter === 'unread' && notifications.length > 0 && <button className="mn-text-action" type="button" onClick={() => setFilter('all')}>View all notifications <ArrowRight size={13} /></button>}
              </div>
            ) : (
              <div className="mn-notification-list" aria-live="polite">
                {visibleNotifications.map((notification, index) => (
                  <article className={`mn-notification${notification.readAt ? ' is-read' : ' is-unread'}`} key={notification.notificationId} style={{ animationDelay: `${Math.min(index, 5) * 45}ms` }} data-testid={`notification-${notification.notificationId}`}>
                    <span className="mn-notification-marker" aria-hidden="true">{notification.kind === 'learning_reminder' ? <BookOpen size={15} /> : <Bell size={15} />}</span>
                    <div className="mn-notification-copy">
                      <div className="mn-notification-meta">
                        <span className="mn-notification-kind">{notification.kind === 'learning_reminder' ? 'LEARNING REMINDER' : 'ANNOUNCEMENT'}</span>
                        {!notification.readAt && <span className="mn-new-label">NEW</span>}
                        <time dateTime={notification.createdAt}><Clock3 size={12} /> {formatNotificationDate(notification.createdAt)}</time>
                      </div>
                      <h3>{notification.title}</h3>
                      <p>{notification.message}</p>
                      <div className="mn-notification-actions">
                        <button type="button" className="mn-open-action" onClick={() => void openNotification(notification)} disabled={busyNotificationIds.has(notification.notificationId)} data-testid={`button-open-notification-${notification.notificationId}`}>
                          {busyNotificationIds.has(notification.notificationId) ? 'Opening…' : notification.targetPath === '/member/learning' ? 'Open learning' : 'Open workspace'} <ArrowRight size={13} />
                        </button>
                        {!notification.readAt && <button type="button" className="mn-read-action" onClick={() => void persistRead(notification)} disabled={busyNotificationIds.has(notification.notificationId)} data-testid={`button-mark-read-${notification.notificationId}`}>Mark read</button>}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>

          <aside className="mn-preferences-panel" aria-labelledby="mn-preferences-heading">
            <div className="mn-preferences-heading">
              <span className="mn-preferences-icon"><SlidersHorizontal size={16} /></span>
              <div><span className="mn-kicker">YOUR SETTINGS</span><h2 id="mn-preferences-heading">Learning reminders</h2></div>
            </div>
            {query.isLoading ? (
              <div className="mn-preferences-skeleton" role="status" aria-label="Loading reminder preferences"><i /><i /><i /></div>
            ) : query.isError ? (
              <p className="mn-preferences-unavailable">Reminder settings are unavailable until your inbox loads.</p>
            ) : (
              <>
                <p className="mn-preferences-intro">A weekly nudge to return to your lessons. Reminders are optional and stay inside Smart Money Hub.</p>
                <label className="mn-toggle-row">
                  <span><strong>Weekly learning reminder</strong><small>{preferences.learningRemindersEnabled ? 'Enabled for this member account' : 'Off until you choose to enable it'}</small></span>
                  <input
                    type="checkbox"
                    checked={preferences.learningRemindersEnabled}
                    onChange={(event) => setPreference('learningRemindersEnabled', event.currentTarget.checked)}
                    aria-label="Enable weekly learning reminders"
                    data-testid="input-learning-reminders-enabled"
                  />
                </label>
                <div className={`mn-preference-fields${preferences.learningRemindersEnabled ? '' : ' is-disabled'}`} aria-disabled={!preferences.learningRemindersEnabled}>
                  <label className="mn-field">
                    <span>Reminder day</span>
                    <select value={preferences.reminderDayOfWeek} onChange={(event) => setPreference('reminderDayOfWeek', Number(event.currentTarget.value))} disabled={!preferences.learningRemindersEnabled} data-testid="select-reminder-day">
                      {daysOfWeek.map((day, index) => <option value={index} key={day}>{day}</option>)}
                    </select>
                  </label>
                  <label className="mn-field">
                    <span>Local time</span>
                    <input type="time" value={preferences.reminderLocalTime} onChange={(event) => setPreference('reminderLocalTime', event.currentTarget.value)} disabled={!preferences.learningRemindersEnabled} data-testid="input-reminder-time" />
                  </label>
                  <label className="mn-field mn-timezone-field">
                    <span>Timezone</span>
                    <input
                      type="text"
                      value={preferences.timezone}
                      onChange={(event) => {
                        setPreference('timezone', event.currentTarget.value);
                        if (timezoneError) setTimezoneError('');
                      }}
                      placeholder="America/New_York"
                      autoComplete="off"
                      spellCheck={false}
                      disabled={!preferences.learningRemindersEnabled}
                      aria-describedby={timezoneError ? 'mn-timezone-error' : 'mn-timezone-help'}
                      data-testid="input-reminder-timezone"
                    />
                    {timezoneError
                      ? <small id="mn-timezone-error" className="mn-field-error">{timezoneError}</small>
                      : <small id="mn-timezone-help">IANA timezone · detected as {initialTimezone}</small>}
                  </label>
                </div>
                <button className="mn-save-button" type="button" onClick={() => void savePreferences()} disabled={updatePreferences.isPending} data-testid="button-save-reminder-preferences">
                  {updatePreferences.isPending ? 'Saving preferences…' : 'Save preferences'} <ArrowRight size={14} />
                </button>
                <div className="mn-preferences-footnote"><ShieldCheck size={13} /><span>In-app only. No email, push, or external delivery.</span></div>
              </>
            )}
          </aside>
        </div>

        <footer className="mn-footer"><span>VAYDA SMART MONEY HUB <i /> PROCESS OVER PREDICTION</span><span>Learning only. Trading involves risk.</span></footer>
      </div>
    </main>
  );
}

