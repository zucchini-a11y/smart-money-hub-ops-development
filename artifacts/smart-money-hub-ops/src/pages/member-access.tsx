import { useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  getGetPortalApplicantFollowupQueryKey,
  getListPortalApplicantFollowupsQueryKey,
  getListPortalMemberApplicationsQueryKey,
  getUpdatePortalApplicantFollowupStatusMutationKey,
  useGetPortalApplicantFollowup,
  useListPortalApplicantFollowups,
  useListPortalMemberApplications,
  useUpdatePortalApplicantFollowupStatus,
} from '@workspace/api-client-react';
import type {
  ApplicantFollowupDelivery,
  ApplicantFollowupEvent,
  ApplicantFollowupState,
  MemberAccessApplication,
} from '@workspace/api-client-react';
import {
  ArrowUpRight, Bell, CalendarClock, Check, ChevronRight, CircleAlert, Clock3,
  Database, ExternalLink, Filter, History, LockKeyhole, Pause, Play, RefreshCw,
  ShieldCheck, UserRound, Users, X,
} from 'lucide-react';
import { Link } from 'wouter';

type Destination = 'all' | 'education' | 'analysis' | 'pro';
const dateLabel = (value?: string | null) => {
  if (!value) return 'Not scheduled';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
};
const humanize = (value?: string | null) => value ? value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()) : 'Not recorded';
const destinationName = (value: string) => ({ education: 'Education', analysis: 'Market Analysis', pro: 'PRO' } as Record<string, string>)[value] ?? humanize(value);
const errorText = (error: unknown) => error && typeof error === 'object' && 'message' in error ? String((error as { message?: unknown }).message ?? 'The request could not be completed.') : 'The request could not be completed.';

function MemberAccessPage() {
  const client = useQueryClient();
  const [destination, setDestination] = useState<Destination>('all');
  const [status, setStatus] = useState('all');
  const [selectedUser, setSelectedUser] = useState('');
  const [confirmTarget, setConfirmTarget] = useState<ApplicantFollowupState | null>(null);
  const [mutationError, setMutationError] = useState('');
  const params = useMemo(() => ({
    ...(destination !== 'all' ? { destination: destination as Exclude<Destination, 'all'> } : {}),
    ...(status !== 'all' ? { status } : {}),
    limit: 100,
  }), [destination, status]);
  const requests = useListPortalMemberApplications(params, {
    query: { queryKey: getListPortalMemberApplicationsQueryKey(params), staleTime: 15_000, refetchOnMount: 'always', refetchInterval: 30_000, refetchIntervalInBackground: false },
  });
  const followups = useListPortalApplicantFollowups({
    query: { queryKey: getListPortalApplicantFollowupsQueryKey(), staleTime: 15_000, refetchOnMount: 'always', refetchInterval: 30_000, refetchIntervalInBackground: false },
  });
  const detail = useGetPortalApplicantFollowup(selectedUser, {
    query: { enabled: !!selectedUser, queryKey: getGetPortalApplicantFollowupQueryKey(selectedUser), staleTime: 10_000, refetchOnMount: 'always', refetchInterval: 30_000, refetchIntervalInBackground: false },
  });
  const updateStatus = useUpdatePortalApplicantFollowupStatus({
    mutation: { mutationKey: getUpdatePortalApplicantFollowupStatusMutationKey() },
  });
  const applications = requests.data?.applications ?? [];
  const applicants = followups.data?.applicants ?? [];
  const isProductionScope = followups.data?.scope === 'production' || requests.data?.scope === 'production';
  const pendingCount = applications.filter((item) => ['pending_review', 'legacy_review', 'information_requested'].includes(item.status.toLowerCase())).length;
  const activeCount = applicants.filter((item) => item.status === 'active').length;
  const pausedCount = applicants.filter((item) => item.status === 'paused').length;

  const setFollowupStatus = (applicant: ApplicantFollowupState, next: 'active' | 'paused') => {
    setMutationError('');
    updateStatus.mutate({ userId: applicant.userId, data: { status: next, expectedUpdated: applicant.updated } }, {
      onSuccess: async () => {
        setConfirmTarget(null);
        await Promise.all([
          client.invalidateQueries({ queryKey: getListPortalApplicantFollowupsQueryKey() }),
          client.invalidateQueries({ queryKey: getGetPortalApplicantFollowupQueryKey(applicant.userId) }),
        ]);
      },
      onError: (error) => setMutationError(errorText(error)),
    });
  };

  return <main className="page member-access-page">
    <div className="member-access-kicker"><span className="member-access-kicker-icon"><Users size={15}/></span><span>OWNER OPERATIONS</span><i/> {isProductionScope ? 'PRODUCTION' : 'DEVELOPMENT · ISOLATED'}</div>
    <div className="member-access-heading">
      <div><div className="eyebrow">MEMBER ACCESS & FOLLOW-UPS</div><h1>Access desk</h1><p className="subheading">Review records from this deployment only; test and live data are never combined.</p></div>
      <div className="member-access-heading-meta"><span className="member-access-scope-pill"><Database size={13}/> {isProductionScope ? 'Production' : 'Development test'}</span><span className="member-access-private"><LockKeyhole size={13}/> Owner-only</span></div>
    </div>
    <div className="member-access-scope" data-testid="member-access-scope"><span className="member-access-scope-mark"><ShieldCheck size={18}/></span><div><strong>{isProductionScope ? 'Production records' : 'Isolated Development records'}</strong><p>Lists show minimized request data only; no answers, evidence identifiers, or private reply text are displayed.</p></div><span className="member-access-scope-tag">{isProductionScope ? 'LIVE DATA' : 'TEST DATA ONLY'}</span></div>

    <section className="access-overview" aria-label="Access desk counts">
      <div className="access-overview-title"><span className="eyebrow">AT A GLANCE</span><span className="fresh-check"><span/>Checks every 30 seconds</span></div>
      <div className="access-counts">
        <div className="access-count access-count-requests"><span>Requests to review</span><strong>{requests.isLoading ? '—' : pendingCount}</strong><small>member access queue</small></div>
        <div className="access-count access-count-active"><span>Schedules active</span><strong>{followups.isLoading ? '—' : activeCount}</strong><small>applicant follow-ups</small></div>
        <div className="access-count access-count-paused"><span>Schedules paused</span><strong>{followups.isLoading ? '—' : pausedCount}</strong><small>awaiting owner review</small></div>
      </div>
    </section>

    <section className="member-access-panel" aria-labelledby="requests-title">
      <header className="member-access-panel-head">
        <div className="member-access-title-wrap"><span className="member-access-section-icon"><UserRound size={17}/></span><div><div className="eyebrow">MINIMIZED REQUEST RECORDS</div><h2 id="requests-title">Member access requests</h2><p>Education access is self-service. Other decisions stay in their existing workflows.</p></div></div>
        <div className="member-access-filters"><label className="access-filter"><Filter size={14}/><span className="sr-only">Filter by destination</span><select value={destination} onChange={(event) => setDestination(event.target.value as Destination)} data-testid="filter-request-destination"><option value="all">All destinations</option><option value="education">Education</option><option value="analysis">Market Analysis</option><option value="pro">PRO</option></select></label><label className="access-filter"><span className="sr-only">Filter by request status</span><select value={status} onChange={(event) => setStatus(event.target.value)} data-testid="filter-request-status"><option value="all">All statuses</option><option value="pending_review">Pending review</option><option value="legacy_review">Legacy review</option><option value="information_requested">Information requested</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="not_yet_eligible">Not yet eligible</option><option value="revoked">Revoked</option></select></label></div>
      </header>
      {requests.isLoading ? <div className="member-access-skeleton" data-testid="member-access-requests-loading">{[0, 1, 2, 3].map((item) => <div className="member-skeleton-row" key={item}><span className="skeleton"/><span className="skeleton"/><span className="skeleton"/></div>)}</div>
        : requests.isError ? <div className="member-access-feedback" role="alert" data-testid="member-access-requests-error"><CircleAlert size={19}/><div><strong>Requests could not be loaded</strong><p>{errorText(requests.error)}</p></div><button className="btn btn-outline" onClick={() => requests.refetch()} data-testid="button-retry-member-requests"><RefreshCw size={14}/>Retry</button></div>
        : applications.length ? <div className="member-request-list">{applications.map((application) => <RequestRow key={application.requestId} application={application}/>)}</div>
        : <div className="member-access-empty" data-testid="member-access-requests-empty"><span><Users size={19}/></span><strong>No requests match this view</strong><p>Try another destination or status filter. Only Development request records are shown here.</p></div>}
    </section>

    <div className="followup-layout">
      <section className="member-access-panel followup-panel" aria-labelledby="followups-title">
        <header className="member-access-panel-head">
          <div className="member-access-title-wrap"><span className="member-access-section-icon followup-icon"><CalendarClock size={17}/></span><div><div className="eyebrow">SCHEDULE OVERSIGHT</div><h2 id="followups-title">Applicant follow-ups</h2><p>Inspect status and history; this site does not send messages.</p></div></div>
          <span className="member-access-count-tag">{applicants.length} {applicants.length === 1 ? 'applicant' : 'applicants'}</span>
        </header>
        {followups.data?.settings && <SettingsSummary settings={followups.data.settings}/>}
        {followups.isLoading ? <div className="member-access-skeleton" data-testid="applicant-followups-loading">{[0, 1, 2].map((item) => <div className="member-skeleton-row" key={item}><span className="skeleton"/><span className="skeleton"/><span className="skeleton"/></div>)}</div>
          : followups.isError ? <div className="member-access-feedback" role="alert" data-testid="applicant-followups-error"><CircleAlert size={19}/><div><strong>Follow-up schedules could not be loaded</strong><p>{errorText(followups.error)}</p></div><button className="btn btn-outline" onClick={() => followups.refetch()} data-testid="button-retry-followups"><RefreshCw size={14}/>Retry</button></div>
          : applicants.length ? <div className="followup-list">{applicants.map((applicant) => <FollowupRow key={applicant.userId} applicant={applicant} selected={selectedUser === applicant.userId} onSelect={() => setSelectedUser(applicant.userId)}/>)}</div>
            : <div className="member-access-empty compact" data-testid="applicant-followups-empty"><span><CalendarClock size={19}/></span><strong>No applicant schedules recorded</strong><p>There are no follow-up records in this deployment’s dataset.</p></div>}
      </section>
      <section className="member-access-panel followup-detail-panel" aria-labelledby="detail-title">
        <header className="member-access-panel-head detail-head"><div><div className="eyebrow">SAFE HISTORY</div><h2 id="detail-title">Schedule detail</h2></div>{selectedUser && <span className="detail-user-id">{selectedUser}</span>}</header>
        {!selectedUser ? <div className="detail-placeholder"><span><History size={20}/></span><strong>Select an applicant</strong><p>Delivery outcomes and schedule events will appear here without message contents.</p></div>
          : detail.isLoading ? <div className="member-access-skeleton detail-loading" data-testid="applicant-detail-loading"><span className="skeleton"/><span className="skeleton"/><span className="skeleton"/></div>
          : detail.isError ? <div className="member-access-feedback detail-error" role="alert" data-testid="applicant-detail-error"><CircleAlert size={18}/><div><strong>Schedule detail unavailable</strong><p>{errorText(detail.error)}</p></div><button className="btn btn-outline" onClick={() => detail.refetch()} data-testid="button-retry-applicant-detail">Retry</button></div>
          : detail.data ? <FollowupDetail applicant={detail.data.applicant} deliveries={detail.data.deliveries} events={detail.data.events} onToggle={() => setConfirmTarget(detail.data!.applicant)} /> : null}
      </section>
    </div>

    {confirmTarget && <div className="member-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !updateStatus.isPending) setConfirmTarget(null); }}>
      <section className="member-modal" role="dialog" aria-modal="true" aria-labelledby="followup-confirm-title" data-testid="dialog-followup-status">
        <button className="member-modal-close" aria-label="Close confirmation" onClick={() => setConfirmTarget(null)} disabled={updateStatus.isPending} data-testid="button-close-followup-confirm"><X size={17}/></button>
        <span className={`member-modal-icon ${confirmTarget.status === 'active' ? 'pause' : 'resume'}`}>{confirmTarget.status === 'active' ? <Pause size={18}/> : <Play size={18}/>}</span>
        <div className="eyebrow">SCHEDULE STATUS CHANGE</div>
        <h2 id="followup-confirm-title">{confirmTarget.status === 'active' ? 'Pause follow-ups?' : 'Resume follow-ups?'}</h2>
        <p className="member-modal-copy">{confirmTarget.status === 'active'
          ? `Pausing ${confirmTarget.username} stops this schedule from progressing until it is resumed.`
          : `Resuming ${confirmTarget.username} allows the schedule to continue if server-side safety checks pass.`}</p>
        <div className="member-action-caveat"><Bell size={15}/><span>No message is sent by this site action. Resuming changes schedule status only; the server may reject an unsafe resume.</span></div>
        {mutationError && <div className="notice notice-error" role="alert" data-testid="followup-mutation-error">{mutationError}</div>}
        <div className="modal-actions"><button className="btn btn-outline" onClick={() => setConfirmTarget(null)} disabled={updateStatus.isPending} data-testid="button-cancel-followup-status">Cancel</button><button className={`btn ${confirmTarget.status === 'active' ? 'btn-danger' : 'btn-primary'}`} onClick={() => setFollowupStatus(confirmTarget, confirmTarget.status === 'active' ? 'paused' : 'active')} disabled={updateStatus.isPending} data-testid="button-confirm-followup-status">{updateStatus.isPending ? 'Updating…' : confirmTarget.status === 'active' ? 'Pause schedule' : 'Resume schedule'}</button></div>
      </section>
    </div>}
  </main>;
}

function RequestRow({ application }: { application: MemberAccessApplication }) {
  const statusTone = ['approved', 'active', 'complete', 'completed'].includes(application.status.toLowerCase()) ? 'good' : ['rejected', 'failed', 'denied'].includes(application.status.toLowerCase()) ? 'bad' : 'waiting';
  return <article className="member-request-row" data-testid={`row-member-request-${application.requestId}`}>
    <div className="request-avatar">{application.username.trim().slice(0, 1).toUpperCase() || 'M'}</div>
    <div className="request-person"><strong data-testid={`text-request-username-${application.requestId}`}>{application.username || `Member ${application.userId}`}</strong><span>User ID {application.userId} <i/> Request {application.requestId}</span></div>
    <div className="request-destination"><small>DESTINATION</small><strong>{destinationName(application.destination)}</strong></div>
    <div className="request-status"><small>REQUEST STATUS</small><span className={`request-state tone-${statusTone}`} data-testid={`status-member-request-${application.requestId}`}>{humanize(application.status)}</span></div>
    <div className="request-registered"><small>REGISTRATION</small><span>{humanize(application.registrationStatus)}</span><small>FUNDING · {humanize(application.fundingStatus)}</small><small>SOURCE · {humanize(application.source)}</small></div>
    <div className="request-date"><small>UPDATED</small><time>{dateLabel(application.updated)}</time><span>Created {dateLabel(application.created)}</span></div>
    <RequestAction application={application}/>
  </article>;
}

function RequestAction({ application }: { application: MemberAccessApplication }) {
  if (application.destination === 'education') return <span className="request-guidance"><Check size={13}/> Self-service</span>;
  if (application.destination === 'pro') return <Link className="request-review-link" href="/command-center/pro-access" data-testid={`link-review-pro-${application.requestId}`}>Open PRO review <ArrowUpRight size={13}/></Link>;
  return <span className="request-guidance"><ExternalLink size={13}/> Telegram admin flow</span>;
}

function SettingsSummary({ settings }: { settings: { enabled: boolean; reviewed: boolean; sampleReviewed: boolean; intervalDays: number[]; maxReminders: number; categories: string[] } }) {
  return <div className="followup-settings" data-testid="followup-settings-summary">
    <div className="settings-summary-head"><span className="eyebrow">READ-ONLY SETTINGS SUMMARY</span><span className={`settings-onoff ${settings.enabled ? 'on' : 'off'}`}>{settings.enabled ? 'Enabled' : 'Disabled'}</span></div>
    <div className="settings-facts"><span><b>Intervals</b>{settings.intervalDays.length ? settings.intervalDays.map((days) => `${days}d`).join(' · ') : 'None'}</span><span><b>Max reminders</b>{settings.maxReminders}</span><span><b>Reviewed</b>{settings.reviewed ? 'Yes' : 'No'}</span><span><b>Sample reviewed</b>{settings.sampleReviewed ? 'Yes' : 'No'}</span></div>
    <div className="settings-categories"><b>Categories</b>{settings.categories.length ? settings.categories.map((category) => <span key={category}>{humanize(category)}</span>) : <em>None recorded</em>}</div>
    <p className="settings-gate-note">These are stored settings only. The bot’s environment-level sending gate is separate and is not changed or reported by this page.</p>
  </div>;
}

function FollowupRow({ applicant, selected, onSelect }: { applicant: ApplicantFollowupState; selected: boolean; onSelect: () => void }) {
  return <button type="button" className={`followup-row ${selected ? 'selected' : ''}`} onClick={onSelect} data-testid={`button-select-followup-${applicant.userId}`} aria-pressed={selected}>
    <span className="followup-avatar">{applicant.username.trim().slice(0, 1).toUpperCase() || 'A'}</span>
    <span className="followup-row-copy"><strong>{applicant.username || `Applicant ${applicant.userId}`}</strong><small>{applicant.destinations.map(destinationName).join(' · ') || 'No destination recorded'}</small></span>
    <span className={`followup-status status-${applicant.status}`}>{humanize(applicant.status)}</span>
    {applicant.hasRecentError && <span className="followup-error-mark" aria-label="Recent error"><CircleAlert size={14}/></span>}
    <ChevronRight size={15} className="followup-chevron"/>
  </button>;
}

function FollowupDetail({ applicant, deliveries, events, onToggle }: { applicant: ApplicantFollowupState; deliveries: ApplicantFollowupDelivery[]; events: ApplicantFollowupEvent[]; onToggle: () => void }) {
  return <div className="followup-detail" data-testid={`applicant-detail-${applicant.userId}`}>
    <div className="detail-applicant"><span className="followup-avatar large">{applicant.username.trim().slice(0, 1).toUpperCase() || 'A'}</span><div><strong>{applicant.username || `Applicant ${applicant.userId}`}</strong><span>{applicant.userId}</span></div><span className={`followup-status status-${applicant.status}`}>{humanize(applicant.status)}</span></div>
    <div className="detail-facts"><div><small>STAGE</small><strong>{humanize(applicant.stage)}</strong></div><div><small>PRIVATE STATUS</small><strong>{humanize(applicant.privateStatus)}</strong></div><div><small>REMINDERS SENT</small><strong>{applicant.remindersSent}</strong></div><div><small>NEXT FOLLOW-UP</small><strong>{dateLabel(applicant.nextFollowup)}</strong></div><div><small>CONSENT NOTICE</small><strong>{dateLabel(applicant.consentNoticeAt)}</strong></div><div><small>PAUSE REASON</small><strong>{humanize(applicant.pauseReason)}</strong></div></div>
    {applicant.hasRecentError && <div className="followup-warning"><CircleAlert size={15}/><span>A recent schedule error is recorded. Review history before changing status.</span></div>}
    {['active', 'paused'].includes(applicant.status) ? <button className={`btn followup-toggle ${applicant.status === 'active' ? 'btn-danger' : 'btn-primary'}`} onClick={onToggle} data-testid={`button-open-followup-status-${applicant.userId}`}>{applicant.status === 'active' ? <><Pause size={14}/> Pause schedule</> : <><Play size={14}/> Resume schedule</>}</button> : <p className="detail-updated">This schedule status does not support a website pause or resume action.</p>}
    <div className="history-block"><div className="history-heading"><Clock3 size={14}/><strong>Delivery history</strong><span>{deliveries.length}</span></div>{deliveries.length ? <div className="history-list">{deliveries.map((delivery) => <DeliveryRow key={delivery.deliveryId} delivery={delivery}/>)}</div> : <p className="history-empty">No delivery records are available.</p>}</div>
    <div className="history-block event-history"><div className="history-heading"><History size={14}/><strong>Schedule events</strong><span>{events.length}</span></div>{events.length ? <div className="history-list">{events.map((event) => <EventRow key={event.eventId} event={event}/>)}</div> : <p className="history-empty">No schedule events are available.</p>}</div>
    <p className="detail-updated">Record updated {dateLabel(applicant.updated)}</p>
  </div>;
}

function DeliveryRow({ delivery }: { delivery: ApplicantFollowupDelivery }) {
  return <div className="history-row" data-testid={`row-followup-delivery-${delivery.deliveryId}`}><span className="history-dot delivery-dot"/><div><strong>{humanize(delivery.category)}</strong><small>{humanize(delivery.status)}</small></div><time>{dateLabel(delivery.sentAt ?? delivery.updated)}</time></div>;
}
function EventRow({ event }: { event: ApplicantFollowupEvent }) {
  return <div className="history-row" data-testid={`row-followup-event-${event.eventId}`}><span className="history-dot event-dot"/><div><strong>{humanize(event.action)}</strong><small>Event {event.eventId}</small></div><time>{dateLabel(event.created)}</time></div>;
}

export default MemberAccessPage;
