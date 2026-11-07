import {
  useGetPortalBotConnections,
  getGetPortalBotConnectionsQueryKey,
  useGetPortalCommandCenter,
  getGetPortalCommandCenterQueryKey,
} from '@workspace/api-client-react';
import type { PortalBotConnection, PortalCommandCenter } from '@workspace/api-client-react';
import {
  Activity, ArrowRight, ArrowUpRight, BellRing, Bot, Check, CircleAlert, Clock3, Database,
  FileText, Gauge, History, LockKeyhole, Radio, RefreshCw, ShieldCheck, Users, Wrench,
} from 'lucide-react';
import { Link } from 'wouter';

const formatDate = (value?: string | null) => {
  if (!value) return 'Not recorded';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
};
const human = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
const statusTone = (value: string) => ['healthy', 'running', 'enabled', 'true'].includes(value.toLowerCase()) ? 'good' : ['unknown', 'not_connected'].includes(value.toLowerCase()) ? 'neutral' : 'caution';
const statusText = (value: string, field: string, sourceId?: string) => {
  if (sourceId === 'production') return 'Outside Development';
  const normalized = value.toLowerCase();
  if (normalized === 'unknown' || normalized === 'not_recorded') {
    if (/process|polling|heartbeat/i.test(field)) return 'No heartbeat';
    if (/health|telegram|database/i.test(field)) return 'Not reported';
    return 'Not recorded';
  }
  if (normalized === 'not_connected') return 'Not connected here';
  if (normalized === 'not_configured') return 'Not configured';
  return human(value);
};
const identityLabel: Record<PortalBotConnection['identityStatus'], string> = {
  verified: 'Telegram accepted this token',
  not_configured: 'Not configured',
  invalid_credentials: 'Credentials rejected',
  identity_mismatch: 'Wrong bot identity',
  unavailable: 'Check unavailable',
};
const runtimeLabel: Record<PortalBotConnection['runtimeStatus'], string> = {
  running: 'Recent heartbeat',
  stale: 'Heartbeat is stale',
  unknown: 'No process heartbeat here',
};
const developmentSecretNames: Partial<Record<PortalBotConnection['id'], string>> = {
  test: 'SMH_TEST_TELEGRAM_BOT_TOKEN',
  coach: 'SMH_TEST_COACH_BOT_TOKEN',
  pro_signals: 'SMH_TEST_PRO_SIGNALS_BOT_TOKEN',
};

const portalControls = [
  { title: 'Trade management', detail: 'Review this deployment’s trade records and prepare guarded updates.', href: '/trades', label: 'Open trade management', icon: Activity, scope: 'Owner route' },
  { title: 'Signals & zones', detail: 'Prepare isolated Development previews and review before confirmation.', href: '/signals', label: 'Open Signals & zones', icon: Radio, scope: 'Development only' },
  { title: 'PRO access review', detail: 'Review eligibility and make an audited PRO access decision.', href: '/command-center/pro-access', label: 'Open PRO review', icon: ShieldCheck, scope: 'Owner route' },
  { title: 'Member access & follow-ups', detail: 'Review the active deployment’s requests and inspect applicant schedules.', href: '/command-center/member-access', label: 'Open member access', icon: Users, scope: 'Deployment-scoped' },
  { title: 'Education videos', detail: 'Create lesson drafts, upload videos, and publish where authorized.', href: '/command-center/education-videos', label: 'Open Education videos', icon: FileText, scope: 'Owner route' },
  { title: 'Channel history', detail: 'Inspect stored post records by bot and destination.', href: '/command-center/channel-history', label: 'Open channel history', icon: History, scope: 'Owner route' },
];

const telegramOnly = [
  'Applicant follow-ups',
  'Education onboarding and progress',
  'Member access requests and invites beyond the existing PRO review',
  'Gemini chart review, chart upload, and annotation',
  'Trade result screenshots and pips statistics',
  'Publishing verification and environment settings',
  'Backup, cleanup, operations retry, and reconcile',
  'FAQ assistant toggles',
  'Bot workflow start and restart',
];

export function BotConnections() {
  const query = useGetPortalBotConnections({
    query: {
      queryKey: getGetPortalBotConnectionsQueryKey(),
      staleTime: 15_000,
      refetchOnMount: 'always',
      refetchInterval: 60_000,
    },
  });

  const destinationFor = (connection: PortalBotConnection) => {
    if (connection.id === 'test') {
      return connection.username ? `https://t.me/${encodeURIComponent(connection.username)}` : null;
    }
    return connection.id === 'coach'
      ? 'https://t.me/SmartMoneyHubSignalsBot'
      : 'https://t.me/SMHProSignalsassistantbot';
  };

  return <section className="bot-connections-panel" aria-labelledby="bot-connections-title" data-testid="bot-live-connections">
    <div className="bot-section-heading">
      <div><span className="bot-overline">DEVELOPMENT · READ-ONLY CHECKS</span><h2 id="bot-connections-title">Bot connections</h2><p>Telegram token checks and process heartbeats are reported separately. A token check does not start a bot.</p></div>
      <button className="btn btn-outline" onClick={() => void query.refetch()} disabled={query.isFetching} aria-label="Refresh bot connections" data-testid="button-refresh-bot-connections"><RefreshCw size={14} className={query.isFetching ? 'bot-rotate' : ''}/>{query.isFetching ? 'Checking' : 'Check now'}</button>
    </div>
    {query.isLoading ? <div className="bot-connection-grid" aria-label="Checking bot connections">{[0, 1, 2].map((item) => <div className="bot-connection-card bot-connection-loading" key={item}><span className="skeleton"/><span className="skeleton"/><span className="skeleton"/></div>)}</div>
      : query.isError ? <div className="bot-connection-feedback" role="alert" data-testid="bot-connections-error"><CircleAlert size={17}/><span>{query.error instanceof Error ? query.error.message : 'Bot connection checks could not be loaded.'}</span><button className="btn btn-quiet" onClick={() => void query.refetch()}>Retry</button></div>
      : query.data ? <div className="bot-connection-grid">{query.data.connections.map((connection) => {
        const destination = destinationFor(connection);
        const identityTone = connection.identityStatus === 'verified' ? 'good'
          : connection.identityStatus === 'not_configured' ? 'neutral' : 'caution';
        const runtimeTone = connection.runtimeStatus === 'running' ? 'good'
          : connection.runtimeStatus === 'stale' ? 'caution' : 'neutral';
        return <article className="bot-connection-card" key={connection.id} data-testid={`bot-connection-${connection.id}`}>
          <div className="bot-connection-card-head"><span className={`bot-connection-icon connection-${connection.id}`}><Bot size={17}/></span><div><span className="bot-overline">{connection.id === 'test' ? 'PRIVATE INSTANCE' : 'TELEGRAM BOT'}</span><h3>{connection.label}</h3></div></div>
          <div className="bot-connection-states">
            <span className={`bot-connection-state tone-${identityTone}`}><i/>{identityLabel[connection.identityStatus]}</span>
            <span className={`bot-connection-state tone-${runtimeTone}`}><i/>{runtimeLabel[connection.runtimeStatus]}</span>
          </div>
          {connection.username && <p className="bot-connection-username">@{connection.username}</p>}
          <p className="bot-connection-note">{connection.identityStatus === 'not_configured'
            ? `Development secret ${developmentSecretNames[connection.id]} is not configured. Use a dedicated test identity; never reuse a live bot token.`
            : connection.identityStatus === 'invalid_credentials'
              ? `Telegram rejected ${developmentSecretNames[connection.id]}. Check the Development secret without pasting it into chat.`
              : connection.note}</p>
          <div className="bot-connection-foot">
            <span>{connection.lastHeartbeat ? `Heartbeat · ${formatDate(connection.lastHeartbeat)}` : 'No process heartbeat recorded'}</span>
            {destination && (connection.id !== 'test' || connection.identityStatus === 'verified') && <a className="btn btn-quiet bot-telegram-action" href={destination} target="_blank" rel="noreferrer" aria-label={`Open ${connection.label} in Telegram`}>Open {connection.id === 'pro_signals' ? 'PRO bot' : connection.id === 'coach' ? 'Coach bot' : 'test bot'} <ArrowUpRight size={14}/></a>}
          </div>
          {connection.id === 'test' && <Link className="btn btn-outline bot-connection-tool" href="/command-center">Open test command center <ArrowRight size={14}/></Link>}
          {connection.id === 'coach' && <Link className="btn btn-outline bot-connection-tool" href="/operations">Open service health <ArrowRight size={14}/></Link>}
          {connection.id === 'pro_signals' && <div className="bot-connection-tools"><Link className="btn btn-outline" href="/signals">Signals &amp; zones <ArrowRight size={14}/></Link><Link className="btn btn-outline" href="/command-center/pro-access">PRO access review <ArrowRight size={14}/></Link></div>}
        </article>;
      })}</div>
        : <div className="bot-connection-feedback">No Development bot connections were returned.</div>}
    <div className="bot-connection-safety"><LockKeyhole size={14}/><span>These checks only call Telegram’s read-only getMe endpoint. They do not poll for updates, send messages, publish, change permissions, or start a process. Coach and PRO runtime monitoring is not connected to this workspace.</span></div>
  </section>;
}

function Snapshot({ data, onRefresh, refreshing }: { data: PortalCommandCenter; onRefresh: () => void; refreshing: boolean }) {
  const metrics = [
    ['Open support', data.overview.openSupportCases],
    ['Uncertain replies', data.overview.uncertainSupportCases],
    ['Open tasks overdue', data.overview.overdueTasks],
    ['Recorded trades', data.overview.recordedTrades],
    ['Trade events', data.overview.recordedTradeEvents],
    ['Publishing unresolved', data.overview.unresolvedPublishingOperations],
    ['PRO pending review', data.overview.proPendingReview],
    ['PRO evidence requested', data.overview.proEvidenceRequested],
    ['Stale PRO applications', data.overview.staleProApplications],
  ] as const;
  return <>
    <section className="bot-scope" aria-label="Snapshot scope" data-testid="bot-control-scope">
      <span className="bot-scope-icon"><Database size={18}/></span>
      <div className="bot-scope-copy"><span className="bot-overline">DEPLOYMENT-OWNED DATA</span><strong>Development · isolated test snapshot</strong><p>Read-only stored test records only. This endpoint is not a Production connection or a live monitor.</p></div>
      <span className="bot-readonly"><LockKeyhole size={12}/> READ ONLY</span>
    </section>

    <section className="bot-snapshot-panel" aria-label="Snapshot overview">
      <div className="bot-section-heading"><div><span className="bot-overline">STORED RECORDS</span><h2>At a glance</h2><p>Counts belong to this isolated Development snapshot.</p></div><div className="bot-refresh-block"><span><Clock3 size={13}/> Refreshed {formatDate(data.refreshedAt)}</span><button className="btn btn-outline" onClick={onRefresh} disabled={refreshing} aria-label="Refresh bot control snapshot" data-testid="button-refresh-bot-control"><RefreshCw size={14} className={refreshing ? 'bot-rotate' : ''}/>{refreshing ? 'Refreshing' : 'Refresh'}</button></div></div>
      <div className="bot-metrics">{metrics.map(([label, value]) => <article className="bot-metric" key={label}><span>{label}</span><strong>{value}</strong></article>)}</div>
    </section>

    <section className="bot-snapshot-panel" aria-labelledby="bot-records-title">
      <div className="bot-section-heading"><div><span className="bot-overline">TELEMETRY RECORDS</span><h2 id="bot-records-title">Bot sources</h2><p>Reported values are persisted observations, not a live process check.</p></div><span className="bot-count">{data.bots.length} {data.bots.length === 1 ? 'source' : 'sources'}</span></div>
      {data.bots.length ? <div className="bot-source-list">{data.bots.map((bot, index) => {
        const readings = [
          ['Health', bot.healthStatus], ['Process', bot.processStatus], ['Telegram', bot.telegramStatus],
          ['Database', bot.databaseStatus], ['Polling', bot.pollingStatus], ['Publishing setting', bot.publishingStatus],
          ['Workflow', bot.workflowStatus],
        ];
        return <article className="bot-source-card" key={`${bot.id}-${index}`} data-testid={`bot-source-${bot.id}-${index}`}>
          <div className="bot-source-top"><span className="bot-source-mark"><Bot size={17}/></span><div><span className="bot-overline">{human(bot.id)}</span><h3>{bot.label}</h3></div><span className="bot-record-tag">Stored status</span></div>
          <p className="bot-source-note">{bot.note || 'No additional note recorded.'}</p>
          <div className="bot-readings">{readings.map(([label, value]) => <div className="bot-reading" key={label}><span>{label}</span><strong className={`tone-${statusTone(value)}`}>{statusText(value, label, bot.id)}</strong></div>)}</div>
          <div className="bot-source-foot"><span>Health checked · {formatDate(bot.healthCheckedAt)}</span><span>Last Telegram update · {formatDate(bot.lastTelegramUpdate)}</span></div>
        </article>;
      })}</div> : <div className="bot-empty">No bot source records are included in this snapshot.</div>}
    </section>

    <section className="bot-snapshot-panel">
      <div className="bot-section-heading"><div><span className="bot-overline">DESTINATION RECORDS</span><h2>Channels &amp; recent operations</h2><p>Recorded activity can be old and does not establish current Telegram access.</p></div></div>
       <div className="bot-channel-grid">{data.channels.length ? data.channels.map((channel, index) => <article className="bot-channel" key={`${channel.name}-${channel.sourceBot}-${index}`}><div className="bot-channel-title"><span>{human(channel.sourceBot)}</span><strong>{human(channel.name)}</strong></div><span className={`bot-status-pill tone-${statusTone(channel.status)}`}>{statusText(channel.status, 'channel')}</span><p>{channel.note}</p><small>Last recorded activity · {formatDate(channel.latestRecordedActivity)}</small></article>) : <div className="bot-empty">No channel records are included.</div>}</div>
       <div className="bot-operations">
        <div className="bot-subheading"><h3>Recent operations</h3><span>{data.recentOperations.length} records</span></div>
         {data.recentOperations.length ? data.recentOperations.slice(0, 5).map((operation, index) => <article className="bot-operation" key={`${operation.recordedAt}-${index}`}><span className="bot-operation-icon"><Activity size={15}/></span><div><strong>{human(operation.operationType)}</strong><small>{human(operation.sourceBot)} · {human(operation.destination)} · {formatDate(operation.recordedAt)}</small></div><span className="bot-operation-state">{statusText(operation.status, 'operation')}</span><span className="bot-operation-accepted">{operation.telegramAccepted ? 'Telegram accepted' : 'Not accepted / not confirmed'}</span></article>) : <div className="bot-empty">No recent operations are stored.</div>}
      </div>
      <div className="bot-last-update"><Clock3 size={14}/><span>Last Telegram update in snapshot</span><strong>{formatDate(data.lastTelegramUpdate)}</strong></div>
    </section>

    <section className="bot-alert-panel" aria-label="Snapshot alerts and errors">
      <div className="bot-section-heading"><div><span className="bot-overline">READ-ONLY REVIEW</span><h2>Alerts &amp; recorded errors</h2><p>Summaries from the Development isolated-test endpoint.</p></div></div>
      <div className="bot-alert-columns">
        <div><h3><BellRing size={14}/> Alerts <span>{data.alerts.length}</span></h3>{data.alerts.length ? data.alerts.map((alert, index) => <article className={`bot-alert-item severity-${alert.severity}`} key={`${alert.category}-${index}`}><CircleAlert size={15}/><div><strong>{alert.title}</strong><small>{human(alert.sourceBot)} · {alert.destination} · {alert.count} recorded</small></div><time>{formatDate(alert.latestAt)}</time></article>) : <p className="bot-empty-inline">No alert records. This does not confirm current channel access.</p>}</div>
        <div><h3><Wrench size={14}/> Error categories <span>{data.recentErrors.length}</span></h3>{data.recentErrors.length ? data.recentErrors.map((error, index) => <article className="bot-error-item" key={`${error.category}-${index}`}><strong>{human(error.category)}</strong><span>{error.count} recorded</span><small>Latest · {formatDate(error.latestAt)}</small></article>) : <p className="bot-empty-inline">No error summaries are stored.</p>}</div>
      </div>
    </section>
    <p className="bot-caveat"><ShieldCheck size={15}/><span><strong>Interpret with care.</strong> This read-only snapshot is scoped to isolated Development test data. It does not establish current bot availability, current destination access, Production status, or successful delivery. Telegram acceptance is not proof of execution or outcome.</span></p>
  </>;
}

export default function BotControl() {
  const isDevelopment = import.meta.env.DEV;
  const query = useGetPortalCommandCenter({ query: { enabled: isDevelopment, queryKey: getGetPortalCommandCenterQueryKey(), staleTime: 15_000, refetchOnMount: 'always', refetchInterval: isDevelopment ? 30_000 : false } });
  return <main className="page bot-control-page">
    <header className="bot-control-heading">
      <div><div className="bot-kicker"><span><Gauge size={14}/></span> OWNER OPERATIONS <i/> VAYDA SMART MONEY HUB</div><div className="eyebrow">PRIVATE CONTROL INDEX</div><h1>Bot control center</h1><p className="subheading">Check the bot identities, open each destination, and reach the owner tools that manage them.</p></div>
      {isDevelopment && <Link className="btn btn-outline bot-command-link" href="/command-center" data-testid="link-bot-control-command-center"><Gauge size={15}/>Open read-only command center<ArrowRight size={14}/></Link>}
    </header>

    <div className="bot-intro-band"><div className="bot-intro-mark"><ShieldCheck size={19}/></div><div><strong>Controls stay attached to their owning deployment.</strong><p>No environment switching, production toggles, credentials, bot-process controls, or Telegram admin actions are exposed here.</p></div><span>OWNER ONLY</span></div>

    {isDevelopment && <BotConnections/>}

    <section className="bot-portal-controls" aria-labelledby="portal-controls-title">
      <div className="bot-section-heading"><div><span className="bot-overline">AVAILABLE IN THIS PORTAL</span><h2 id="portal-controls-title">Website controls</h2><p>Each link opens an existing owner page; availability and scope are described at the destination.</p></div><span className="bot-count">{portalControls.length} routes</span></div>
      <div className="bot-control-list">{portalControls.map(({ title, detail, href, label, icon: Icon, scope }, index) => <Link className="bot-control-row" href={href} key={href} data-testid={`link-bot-control-${href.replaceAll('/', '-').replace(/^-/, '')}`}><span className="bot-control-index">{String(index + 1).padStart(2, '0')}</span><span className="bot-control-icon"><Icon size={17}/></span><span className="bot-control-copy"><strong>{title}</strong><small>{detail}</small></span><span className="bot-control-scope">{scope}</span><span className="bot-control-open" aria-label={label}><ArrowRight size={16}/></span></Link>)}</div>
    </section>

    <section className="bot-telegram-panel" aria-labelledby="telegram-only-title">
      <div className="bot-telegram-head"><div className="bot-telegram-symbol"><Radio size={18}/></div><div><span className="bot-overline">NOT CONTROLLED BY THE SITE</span><h2 id="telegram-only-title">Telegram-only / external operations</h2><p>These capabilities are not portal controls. Use their existing Telegram or Replit workflows only.</p></div><span className="bot-external-tag">EXTERNAL</span></div>
      <ul className="bot-telegram-list">{telegramOnly.map((area) => <li key={area}><span><Check size={12}/></span><span>{area}</span></li>)}</ul>
      <p className="bot-workflow-note"><LockKeyhole size={14}/><span>Bot workflow start and restart remain in Replit workflow controls, not the portal.</span></p>
    </section>

      {!isDevelopment ? <section className="bot-snapshot-error" data-testid="bot-control-production-scope"><span className="bot-error-mark"><LockKeyhole size={18}/></span><div><span className="bot-overline">ENVIRONMENT BOUNDARY</span><h2>Production snapshot is not connected here</h2><p>This page does not read Production bot records. The existing command-center endpoint is limited to isolated Development data.</p></div></section>
        : query.isLoading ? <section className="bot-snapshot-loading" aria-label="Loading Development snapshot" data-testid="bot-control-loading"><div className="bot-section-heading"><div><span className="skeleton" style={{ width: 90 }}/><span className="skeleton" style={{ width: 190, height: 20, marginTop: 12 }}/></div></div><div className="bot-loading-grid">{[0,1,2,3,4,5].map((item) => <div className="bot-loading-card" key={item}><span className="skeleton"/><span className="skeleton"/></div>)}</div><span className="skeleton" style={{ height: 110, marginTop: 15 }}/></section>
        : query.isError ? <section className="bot-snapshot-error" role="alert" data-testid="bot-control-error"><span className="bot-error-mark"><CircleAlert size={18}/></span><div><span className="bot-overline">SNAPSHOT UNAVAILABLE</span><h2>Development records could not be loaded</h2><p>{query.error instanceof Error ? query.error.message : 'Check the read-only endpoint and try again.'}</p></div><button className="btn btn-outline" onClick={() => query.refetch()} disabled={query.isFetching} data-testid="button-retry-bot-control"><RefreshCw size={14}/>{query.isFetching ? 'Checking' : 'Try again'}</button></section>
        : query.data ? <Snapshot data={query.data} onRefresh={() => { void query.refetch(); }} refreshing={query.isFetching}/>
        : <section className="bot-snapshot-error"><span className="bot-error-mark"><CircleAlert size={18}/></span><div><h2>No snapshot returned</h2><p>There is no stored Development snapshot to display yet.</p></div><button className="btn btn-outline" onClick={() => query.refetch()}><RefreshCw size={14}/>Retry</button></section>}
  </main>;
}
