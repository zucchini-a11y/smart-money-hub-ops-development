import { useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  getGetPortalSignalActionQueryKey,
  getGetPortalSignalControlQueryKey,
  useCancelPortalSignalAction,
  useConfirmPortalSignalAction,
  useCreatePortalSignalAction,
  useGetPortalSignalAction,
  useGetPortalSignalControl,
} from '@workspace/api-client-react';
import type { PortalSignalAction, PortalSignalActionInputAction, PortalSignalActionValues } from '@workspace/api-client-react';
import {
  AlertTriangle, ArrowRight, Check, CircleHelp, Clock3, Database, FileText,
  LockKeyhole, MessageSquareText, Plus, Radio, RefreshCw, Send, ShieldCheck,
  Sparkles, Target, X,
} from 'lucide-react';
import './signals.css';

const human = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
const formatDate = (value?: string | number | null) => {
  if (value === null || value === undefined || value === '') return 'Not set';
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
};
const freshRequestId = () => globalThis.crypto?.randomUUID?.() ?? 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (character) => {
  const random = Math.floor(Math.random() * 16);
  return (character === 'x' ? random : (random & 0x3) | 0x8).toString(16);
});
const safeTelegramPreview = (text: string) => text.split(/(<b>[\s\S]*?<\/b>)/g).map((part, index) => {
  const bold = part.match(/^<b>([\s\S]*)<\/b>$/);
  return bold ? <strong key={index}>{bold[1]}</strong> : part;
});
const mayHaveReachedServer = (error: unknown) => !error || typeof error !== 'object' || typeof (error as { status?: number }).status !== 'number' || (error as { status: number }).status >= 500;
const errorMessage = (error: unknown, fallback: string) => error && typeof error === 'object' && 'message' in error && typeof error.message === 'string' ? error.message : fallback;

const publishActions: PortalSignalActionInputAction[] = ['publish_zone', 'publish_signal', 'publish_analysis'];

function SignalSkeleton() {
  return <div className="signals-skeleton" aria-label="Loading signal controls" data-testid="signals-loading">
    <div className="signals-skeleton-head"><i/><i/></div><div className="signals-skeleton-grid"><i/><i/><i/></div><i className="signals-skeleton-wide"/>
  </div>;
}

export default function Signals() {
  const client = useQueryClient();
  const panelQuery = useGetPortalSignalControl({
    query: { queryKey: getGetPortalSignalControlQueryKey(), staleTime: 8_000, refetchOnMount: 'always', refetchInterval: 20_000 },
  });
  const panel = panelQuery.data;
  const createAction = useCreatePortalSignalAction();
  const confirmAction = useConfirmPortalSignalAction();
  const cancelAction = useCancelPortalSignalAction();
  const [activeCommandId, setActiveCommandId] = useState('');
  const [feedback, setFeedback] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const [confirmChecked, setConfirmChecked] = useState(false);
  const [market, setMarket] = useState('');
  const [low, setLow] = useState('');
  const [high, setHigh] = useState('');
  const [timeframe, setTimeframe] = useState('15m');
  const [condition, setCondition] = useState('');
  const [observedConfirmation, setObservedConfirmation] = useState('');
  const [analysisText, setAnalysisText] = useState('');
  const [direction, setDirection] = useState<'BUY' | 'SELL'>('BUY');
  const [entryRange, setEntryRange] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [takeProfits, setTakeProfits] = useState('');
  const actionQuery = useGetPortalSignalAction(activeCommandId, {
    query: {
      enabled: Boolean(activeCommandId),
      queryKey: getGetPortalSignalActionQueryKey(activeCommandId),
      refetchInterval: (query) => query.state.data && ['queued', 'processing'].includes(query.state.data.status) ? 2500 : false,
    },
  });
  const action = actionQuery.data ?? panel?.commands.find((item) => item.commandId === activeCommandId);

  const refreshRelated = (commandId?: string) => {
    void client.invalidateQueries({ queryKey: getGetPortalSignalControlQueryKey() });
    if (commandId) void client.invalidateQueries({ queryKey: getGetPortalSignalActionQueryKey(commandId) });
  };
  const submitAction = (actionType: PortalSignalActionInputAction, input: PortalSignalActionValues) => {
    setFeedback('');
    setConfirmChecked(false);
    setUncertain(false);
    createAction.mutate({ data: { action: actionType, requestId: freshRequestId(), input } }, {
      onSuccess: (created) => {
        setActiveCommandId(created.commandId);
        setFeedback(created.safeResult || 'Action prepared. Review the latest status below.');
        refreshRelated(created.commandId);
      },
      onError: (failure) => {
        const ambiguous = mayHaveReachedServer(failure);
        setUncertain(ambiguous);
        setFeedback(ambiguous
          ? 'We could not verify whether this request was received. Do not submit it again. Refresh the panel and review recent actions first.'
          : errorMessage(failure, 'The action was not prepared. Check the details and try again.'));
        refreshRelated();
      },
    });
  };
  const prepareZone = (event: FormEvent) => {
    event.preventDefault();
    if (!market.trim() || !low.trim() || !high.trim() || !timeframe.trim() || !condition.trim()) return;
    submitAction('create_zone_draft', {
      market: market.trim(), low: low.trim(), high: high.trim(), timeframe: timeframe.trim(),
      condition: condition.trim(),
    });
  };
  const prepareSimple = (actionType: PortalSignalActionInputAction, input: PortalSignalActionValues) => submitAction(actionType, input);
  const confirm = () => {
    if (!action?.canConfirm || !panel || (isPublishAction && !canPublish) || !confirmChecked || !actionIsSafeToConfirm) return;
    confirmAction.mutate({ commandId: action.commandId }, {
      onSuccess: (result) => {
        setFeedback(result.safeResult || `Action status: ${human(result.status)}.`);
        setConfirmChecked(false);
        setUncertain(false);
        refreshRelated(result.commandId);
      },
      onError: (failure) => {
        setUncertain(mayHaveReachedServer(failure));
        setFeedback(mayHaveReachedServer(failure)
          ? 'Confirmation outcome could not be verified. Do not confirm again. Refresh the action status before deciding what to do next.'
          : errorMessage(failure, 'The action was not confirmed. Review its latest status.'));
        refreshRelated(action.commandId);
      },
    });
  };
  const cancel = () => {
    if (!action?.canCancel || uncertain) return;
    cancelAction.mutate({ commandId: action.commandId }, {
      onSuccess: (result) => {
        setFeedback(result.safeResult || 'Action cancelled.');
        setUncertain(false);
        refreshRelated(result.commandId);
      },
      onError: (failure) => {
        setUncertain(mayHaveReachedServer(failure));
        setFeedback(mayHaveReachedServer(failure)
          ? 'Cancellation outcome could not be verified. Refresh the action status before taking another step.'
          : errorMessage(failure, 'The action could not be cancelled. Refresh its status.'));
        refreshRelated(action.commandId);
      },
    });
  };
  const isPublishAction = Boolean(action && publishActions.includes(action.action as PortalSignalActionInputAction));
  const canPublish = panel?.workerStatus === 'ready' && panel.publishingEnabled && panel.destinationsVerified;
  const actionIsSafeToConfirm = Boolean(action && action.status === 'preview_ready' && action.canConfirm && !['failed', 'uncertain', 'stale', 'cancelled', 'completed'].includes(action.status));
  const gateReasons = [
    isPublishAction && panel?.workerStatus !== 'ready' ? `Worker ${human(panel?.workerStatus ?? 'unknown')}` : '',
    isPublishAction && !panel?.publishingEnabled ? 'Publishing is disabled' : '',
    isPublishAction && !panel?.destinationsVerified ? 'Destinations are not verified' : '',
    action && action.status !== 'preview_ready' ? `Status is ${human(action.status)}` : '',
    action && !action.canConfirm ? 'Server has not enabled confirmation' : '',
  ].filter(Boolean);
  const setCurrentAction = (command: PortalSignalAction) => {
    setActiveCommandId(command.commandId);
    setFeedback('');
    setConfirmChecked(false);
    setUncertain(false);
  };
  const refreshStatus = async () => {
    const result = await actionQuery.refetch();
    if (result.data) {
      setUncertain(false);
      setFeedback('Latest action status loaded. Review it before continuing.');
    }
  };
  const currentSetup = panel?.activeSetup;

  if (panelQuery.isLoading) return <main className="page signals-page"><SignalSkeleton/></main>;
  if (panelQuery.isError) return <main className="page signals-page">
    <section className="signals-state-panel" data-testid="signals-load-error"><span className="signals-state-icon"><CircleHelp size={20}/></span><span className="signals-overline">OWNER SIGNAL WORKSPACE</span><h1>Signals are unavailable</h1><p>{errorMessage(panelQuery.error, 'We could not load Development signal controls.')}</p><button className="signals-button secondary" onClick={() => panelQuery.refetch()} data-testid="button-retry-signals"><RefreshCw size={15}/>Try again</button></section>
  </main>;
  if (!panel) return <main className="page signals-page"><section className="signals-state-panel" data-testid="signals-empty"><span className="signals-state-icon"><Radio size={20}/></span><h1>No signal panel returned</h1><p>Refresh to check whether Development controls are available.</p><button className="signals-button secondary" onClick={() => panelQuery.refetch()} data-testid="button-retry-empty-signals"><RefreshCw size={15}/>Refresh</button></section></main>;

  const hasConfirmableAction = Boolean(action?.canConfirm && action.status === 'preview_ready');
  const canConfirm = Boolean(hasConfirmableAction && (!isPublishAction || canPublish) && confirmChecked && actionIsSafeToConfirm && !uncertain && !confirmAction.isPending);
  const recent = panel.commands ?? [];
  const statusTone = (value: string) => ['ready', 'completed', 'approved', 'preview_ready'].includes(value) ? 'good' : ['unknown', 'migration_required', 'failed', 'uncertain', 'stale', 'disabled'].includes(value) ? 'caution' : 'neutral';

  return <main className="page signals-page">
    <header className="signals-heading">
      <div><div className="signals-kicker"><span><Radio size={14}/></span> OWNER CONTROL <i/> DEVELOPMENT ONLY</div><h1>Signals &amp; zones</h1><p className="signals-intro">Prepare a post, review exactly what the server will send, then decide whether to publish.</p></div>
      <button className="signals-button secondary signals-refresh" onClick={() => panelQuery.refetch()} disabled={panelQuery.isFetching} data-testid="button-refresh-signals"><RefreshCw size={15} className={panelQuery.isFetching ? 'signals-rotate' : ''}/>{panelQuery.isFetching ? 'Refreshing' : 'Refresh'}</button>
    </header>

    <section className="signals-environment" aria-label="Environment scope" data-testid="signals-environment">
      <span className="signals-environment-icon"><Database size={19}/></span>
      <div className="signals-environment-copy"><span className="signals-overline">FIXED BY THIS DEPLOYMENT</span><strong>Development · isolated test controls</strong><p>This page is not connected to Production. It is separate from member support work.</p></div>
      <span className="signals-scope-tag">PRIVATE TEST</span>
    </section>

    <section className="signals-readiness" aria-label="Publishing readiness" data-testid="signals-readiness">
      <div className="signals-readiness-head"><div><span className="signals-overline">CHECK BEFORE YOU ACT</span><strong>Publishing safeguards</strong></div><span className="signals-updated"><Clock3 size={13}/> Updated {formatDate(panel.panelUpdated)}</span></div>
      <div className="signals-readiness-grid">
        <div className={`signals-readiness-item ${panel.workerStatus === 'ready' ? 'ready' : 'blocked'}`} data-testid="signals-worker-status"><span>{panel.workerStatus === 'ready' ? <Check size={14}/> : <AlertTriangle size={14}/>}</span><div><small>Private test worker</small><strong>{human(panel.workerStatus)}</strong></div></div>
        <div className={`signals-readiness-item ${panel.destinationsVerified ? 'ready' : 'blocked'}`} data-testid="signals-destinations-status"><span>{panel.destinationsVerified ? <Check size={14}/> : <AlertTriangle size={14}/>}</span><div><small>Destinations</small><strong>{panel.destinationsVerified ? 'Verified' : 'Not verified'}</strong></div></div>
        <div className={`signals-readiness-item ${panel.publishingEnabled ? 'ready' : 'blocked'}`} data-testid="signals-publishing-status"><span>{panel.publishingEnabled ? <Check size={14}/> : <LockKeyhole size={14}/>}</span><div><small>Publishing lock</small><strong>{panel.publishingEnabled ? 'Enabled' : 'Locked'}</strong></div></div>
      </div>
      {!canPublish && <p className="signals-guardrail" role="status" data-testid="signals-publishing-blocked"><LockKeyhole size={14}/> Publishing actions are paused until every check above is ready. Draft preparation remains available where safe.</p>}
    </section>

    <div className="signals-workspace">
      <section className="signals-compose">
        <div className="signals-section-head"><div className="signals-step">01</div><div><span className="signals-overline">PREPARE</span><h2>Build a zone draft</h2><p>Creating a draft does not publish anything.</p></div></div>
        <form className="signals-form" onSubmit={prepareZone}>
          <div className="signals-form-grid">
            <div className="signals-field"><label htmlFor="signals-market">Market</label><input id="signals-market" value={market} onChange={(event) => setMarket(event.target.value)} maxLength={80} required placeholder="For example, EURUSD" data-testid="input-zone-market"/></div>
            <div className="signals-field"><label htmlFor="signals-timeframe">Timeframe</label><input id="signals-timeframe" value={timeframe} onChange={(event) => setTimeframe(event.target.value)} maxLength={30} required placeholder="15m" data-testid="input-zone-timeframe"/></div>
            <div className="signals-field"><label htmlFor="signals-zone-low">Lower price</label><input id="signals-zone-low" inputMode="decimal" value={low} onChange={(event) => setLow(event.target.value)} maxLength={24} required placeholder="1.0820" data-testid="input-zone-low"/></div>
            <div className="signals-field"><label htmlFor="signals-zone-high">Upper price</label><input id="signals-zone-high" inputMode="decimal" value={high} onChange={(event) => setHigh(event.target.value)} maxLength={24} required placeholder="1.0840" data-testid="input-zone-high"/></div>
            <div className="signals-field signals-field-wide"><label htmlFor="signals-condition">Setup condition</label><input id="signals-condition" value={condition} onChange={(event) => setCondition(event.target.value)} maxLength={300} required placeholder="What needs to happen before this setup is valid?" data-testid="input-zone-condition"/></div>
          </div>
          <p className="signals-setup-hint">Zones remain active until you mark them expired.</p>
          <div className="signals-chart-note" data-testid="signals-chart-upload-note"><span><FileText size={15}/></span><p><strong>Chart uploads stay in Telegram.</strong> This page creates the zone draft only; add or replace its chart in the private test Telegram channel.</p></div>
          <button className="signals-button primary" type="submit" disabled={createAction.isPending} data-testid="button-create-zone-draft"><Plus size={15}/>{createAction.isPending ? 'Preparing draft…' : 'Create zone draft'}</button>
        </form>
      </section>

      <aside className="signals-side">
        {panel.zoneDraft && <section className="signals-draft-card" data-testid="signals-zone-draft">
          <div className="signals-side-heading"><div><span className="signals-overline">ZONE DRAFT</span><h2>Draft in progress</h2></div><span className={`signals-chip tone-${panel.zoneDraft.readyToPublish ? 'good' : 'neutral'}`}>{human(panel.zoneDraft.step)}</span></div>
          <div className="signals-setup-market"><Target size={17}/><strong>{panel.zoneDraft.market}</strong><span>{panel.zoneDraft.zone}</span></div>
          <dl className="signals-detail-list"><div><dt>Timeframe</dt><dd>{panel.zoneDraft.timeframe}</dd></div><div><dt>Condition</dt><dd>{panel.zoneDraft.condition || 'Not set'}</dd></div><div><dt>Chart</dt><dd>{panel.zoneDraft.hasChart ? 'Added' : 'Not added'}</dd></div><div><dt>Draft revision</dt><dd>{panel.zoneDraft.revision}</dd></div></dl>
          <div className="signals-draft-foot"><span className={`signals-draft-ready ${panel.zoneDraft.readyToPublish ? 'ready' : ''}`}>{panel.zoneDraft.readyToPublish ? 'Ready for review' : 'More setup needed'}</span><button className="signals-button secondary" onClick={() => prepareSimple('publish_zone', { draftRevision: panel.zoneDraft!.revision })} disabled={!panel.zoneDraft.readyToPublish || !canPublish || createAction.isPending} data-testid="button-prepare-zone-draft-publish"><Send size={14}/>Prepare PRO Signals zone post</button></div>
          <p className="signals-setup-hint">This page does not upload charts. Add the chart in Telegram before publishing.</p>
        </section>}
        <section className="signals-setup-card" data-testid="signals-active-setup">
          <div className="signals-side-heading"><div><span className="signals-overline">CURRENT SETUP</span><h2>Active setup</h2></div><span className={`signals-chip tone-${currentSetup ? statusTone(currentSetup.status) : 'neutral'}`}>{currentSetup ? human(currentSetup.status) : 'None'}</span></div>
          {currentSetup ? <>
            <div className="signals-setup-market"><Target size={17}/><strong>{currentSetup.market}</strong><span>{currentSetup.zone}</span></div>
            <dl className="signals-detail-list"><div><dt>Timeframe</dt><dd>{currentSetup.timeframe}</dd></div><div><dt>Condition</dt><dd>{currentSetup.condition || 'Not set'}</dd></div><div><dt>Expiry</dt><dd>{currentSetup.expires == null ? 'Manual — mark expired to close' : formatDate(currentSetup.expires)}</dd></div><div><dt>Chart</dt><dd>{currentSetup.hasChart ? 'Added' : 'Not added'}</dd></div><div><dt>Message</dt><dd>{currentSetup.hasMessage ? 'Available' : 'Not available'}</dd></div></dl>
          <div className="signals-setup-actions">
              <div className="signals-field signals-confirmation-field"><label htmlFor="signals-observed-confirmation">Observed setup confirmation</label><input id="signals-observed-confirmation" value={observedConfirmation} onChange={(event) => setObservedConfirmation(event.target.value)} maxLength={300} placeholder="Describe what you observed" data-testid="input-setup-confirmation"/></div>
              <button className="signals-button secondary" onClick={() => prepareSimple('record_confirmation', { setupId: currentSetup.setupId, confirmation: observedConfirmation.trim() })} disabled={createAction.isPending || !observedConfirmation.trim()} data-testid="button-record-setup-confirmation"><Check size={14}/>Record confirmation</button>
              <button className="signals-button text-danger" onClick={() => prepareSimple('cancel_setup', { setupId: currentSetup.setupId })} disabled={createAction.isPending} data-testid="button-prepare-cancel-setup"><X size={14}/>Prepare cancellation</button>
              <button className="signals-button text-danger" onClick={() => prepareSimple('expire_setup', { setupId: currentSetup.setupId })} disabled={createAction.isPending} data-testid="button-prepare-expire-setup"><X size={14}/>Mark zone expired</button>
            <div className="signals-signal-actions">
              <label>Private PRO signal review</label>
              <div className="signals-signal-fields">
                <div className="signals-field"><label htmlFor="signals-direction">Direction</label><select id="signals-direction" value={direction} onChange={(event) => setDirection(event.target.value as 'BUY' | 'SELL')} data-testid="select-signal-direction"><option value="BUY">BUY</option><option value="SELL">SELL</option></select></div>
                <div className="signals-field"><label htmlFor="signals-entry-range">Entry range</label><input id="signals-entry-range" inputMode="decimal" value={entryRange} onChange={(event) => setEntryRange(event.target.value)} maxLength={60} placeholder="4151-4154" data-testid="input-signal-entry-range"/></div>
                <div className="signals-field"><label htmlFor="signals-stop-loss">Stop Loss</label><input id="signals-stop-loss" inputMode="decimal" value={stopLoss} onChange={(event) => setStopLoss(event.target.value)} maxLength={24} placeholder="4140" data-testid="input-signal-stop-loss"/></div>
                <div className="signals-field"><label htmlFor="signals-take-profits">Take Profit(s)</label><input id="signals-take-profits" value={takeProfits} onChange={(event) => setTakeProfits(event.target.value)} maxLength={300} placeholder="4160, 4170" data-testid="input-signal-take-profits"/></div>
              </div>
              <div className="signals-signal-action-row">
                <button className="signals-button secondary" onClick={() => prepareSimple('publish_signal', {
                  setupId: currentSetup.setupId, direction, entryRange: entryRange.trim(),
                  stopLoss: stopLoss.trim(), takeProfits: takeProfits.trim(),
                })} disabled={!canPublish || createAction.isPending || !currentSetup.hasMessage || !entryRange.trim() || !stopLoss.trim() || !takeProfits.trim()} data-testid="button-prepare-signal"><ArrowRight size={14}/>Review {direction} NOW preview</button>
              </div>
            </div>
            </div>
            {(!currentSetup.hasChart || !currentSetup.hasMessage) && <p className="signals-setup-hint" data-testid="signals-setup-prerequisite">{!currentSetup.hasChart ? 'A chart must be added in Telegram before preparing a zone post.' : 'A setup message is not available yet.'}</p>}
          </> : <div className="signals-empty-setup" data-testid="signals-no-active-setup"><span><Target size={19}/></span><strong>No active setup</strong><p>Once a zone is ready, its current status and controls will appear here.</p></div>}
        </section>

        <section className="signals-analysis-card" aria-label="Prepare market analysis">
          <div className="signals-section-head compact"><span className="signals-analysis-icon"><Sparkles size={16}/></span><div><span className="signals-overline">PRIVATE TEST MARKET ANALYSIS</span><h2>Write exact text</h2><p>Review the server preview before any publish decision.</p></div></div>
          <label className="signals-sr-only" htmlFor="signals-analysis-text">Analysis message text</label>
          <textarea id="signals-analysis-text" value={analysisText} onChange={(event) => setAnalysisText(event.target.value)} maxLength={3000} rows={4} placeholder="Write the analysis exactly as you want it reviewed." data-testid="input-analysis-text"/>
          <div className="signals-analysis-foot"><span>{analysisText.length}/3000</span><button className="signals-button secondary" onClick={() => prepareSimple('publish_analysis', { text: analysisText.trim() })} disabled={!analysisText.trim() || !canPublish || createAction.isPending} data-testid="button-prepare-analysis"><MessageSquareText size={14}/>Prepare Market Analysis post</button></div>
        </section>
      </aside>
    </div>

    <section className="signals-review" aria-label="Action review" data-testid="signals-action-review">
      <div className="signals-review-head"><div className="signals-step">02</div><div><span className="signals-overline">REVIEW AND CONTROL</span><h2>Latest action</h2><p>Use the exact preview returned by the server. No message is sent from this screen until you confirm.</p></div>{action && <span className={`signals-chip tone-${statusTone(action.status)}`} data-testid="signals-action-status">{human(action.status)}</span>}</div>
      {action ? <ActionReview
        action={action}
        isPublishAction={isPublishAction}
        canPublish={Boolean(canPublish)}
        canConfirm={canConfirm}
        confirmChecked={confirmChecked}
        onConfirmChecked={setConfirmChecked}
        onConfirm={confirm}
        onCancel={cancel}
        onRefresh={refreshStatus}
        confirmPending={confirmAction.isPending}
        cancelPending={cancelAction.isPending}
        actionError={actionQuery.isError}
        actionFetching={actionQuery.isFetching}
        uncertain={uncertain}
        gateReasons={gateReasons}
      /> : <div className="signals-no-action" data-testid="signals-no-current-action"><span><ShieldCheck size={19}/></span><strong>No action selected</strong><p>Prepare an action or choose a recent command below to review its server status.</p></div>}
      {feedback && <div className={`signals-feedback ${uncertain ? 'caution' : ''}`} role="status" data-testid="signals-action-feedback">{uncertain && <AlertTriangle size={15}/>}<span>{feedback}</span></div>}
    </section>

    <section className="signals-history" aria-label="Recent action queue" data-testid="signals-recent-actions">
      <div className="signals-history-head"><div><span className="signals-overline">QUEUE STATUS</span><h2>Recent actions</h2><p>Stored commands for this isolated test workspace.</p></div><span className="signals-count" data-testid="signals-action-count">{recent.length.toString().padStart(2, '0')}</span></div>
      {recent.length ? <div className="signals-command-list">{recent.map((item) => <button className={`signals-command-row ${action?.commandId === item.commandId ? 'selected' : ''}`} type="button" onClick={() => setCurrentAction(item)} key={item.commandId} data-testid={`button-select-signal-action-${item.commandId}`} aria-pressed={action?.commandId === item.commandId}>
        <span className="signals-command-mark"><Radio size={15}/></span><span className="signals-command-copy"><strong>{human(item.action)}</strong><small>{formatDate(item.updated)} · {item.safeResult || 'No status note returned'}</small></span><span className={`signals-chip tone-${statusTone(item.status)}`}>{human(item.status)}</span><ArrowRight className="signals-command-arrow" size={15}/>
      </button>)}</div> : <div className="signals-history-empty" data-testid="signals-no-recent-actions"><span><Clock3 size={18}/></span><strong>No recent actions</strong><p>Prepared commands will appear here so you can review their status.</p></div>}
    </section>

    <footer className="signals-footnote" data-testid="signals-safety-note"><LockKeyhole size={15}/><p><strong>Private test controls only.</strong> This page does not connect to Production. A Telegram post is not a broker order, trade execution, or outcome record. Check every preview before confirming.</p></footer>
  </main>;
}

function ActionReview({
  action, isPublishAction, canPublish, canConfirm, confirmChecked, onConfirmChecked, onConfirm, onCancel, onRefresh,
  confirmPending, cancelPending, actionError, actionFetching, uncertain, gateReasons,
}: {
  action: PortalSignalAction;
  isPublishAction: boolean;
  canPublish: boolean;
  canConfirm: boolean;
  confirmChecked: boolean;
  onConfirmChecked: (checked: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
  onRefresh: () => void;
  confirmPending: boolean;
  cancelPending: boolean;
  actionError: boolean;
  actionFetching: boolean;
  uncertain: boolean;
  gateReasons: string[];
}) {
  return <div className="signals-action-detail">
    {actionError ? <div className="signals-action-error" role="alert" data-testid="signals-action-error"><span>Action details could not be refreshed. Do not repeat a publish.</span><button className="signals-button secondary" onClick={onRefresh} data-testid="button-refresh-signal-action"><RefreshCw size={14}/>Refresh status</button></div> : <>
      {isPublishAction && <div className="signals-preview-label"><span><MessageSquareText size={14}/></span><div><strong>Exact server preview · {action.action === 'publish_analysis' ? 'Private test Market Analysis' : 'Private test PRO Signals'}</strong><small>Read this message as it will be sent. It has not been published.</small></div></div>}
      <pre className="signals-preview-text" data-testid="signals-preview-text">{safeTelegramPreview(action.previewText || 'The server has not returned preview text.')}</pre>
      {action.safeResult && <p className="signals-safe-result" data-testid="signals-safe-result">{action.safeResult}</p>}
      {['uncertain', 'failed', 'stale'].includes(action.status) && <div className="signals-action-warning" data-testid="signals-no-retry-notice"><AlertTriangle size={15}/><span>{action.status === 'uncertain' ? 'The result is uncertain. Do not publish again; refresh and verify the channel before continuing.' : action.status === 'failed' ? 'This action failed. Review the server status; no automatic retry is available here.' : 'This action is stale. Prepare a new action only after reviewing the current setup.'}</span></div>}
      {uncertain && <div className="signals-action-warning" data-testid="signals-operation-uncertain"><AlertTriangle size={15}/><span>The last request outcome is unknown. Refresh the action status before taking another step.</span><button className="signals-button secondary" onClick={onRefresh} disabled={actionFetching} data-testid="button-refresh-uncertain-signal">{actionFetching ? 'Checking…' : 'Refresh status'}</button></div>}
      {action.canConfirm && action.status === 'preview_ready' && <div className="signals-confirm-area" data-testid="signals-explicit-confirm">
        <label className="signals-confirm-check"><input type="checkbox" checked={confirmChecked} onChange={(event) => onConfirmChecked(event.target.checked)} disabled={(!canPublish && isPublishAction) || uncertain || actionError} data-testid="checkbox-confirm-signal-publish"/><span><strong>{isPublishAction ? 'I reviewed this exact message and want to publish it to the private test destination.' : `I reviewed this ${human(action.action).toLowerCase()} action and want to continue.`}</strong><small>This is a separate confirmation; preparing the preview did not send it.</small></span></label>
        {gateReasons.length > 0 && <p className="signals-gate-note" data-testid="signals-confirm-gate"><LockKeyhole size={13}/> Confirmation locked: {gateReasons.join(' · ')}.</p>}
        {!canPublish && <p className="signals-gate-note"><LockKeyhole size={13}/> Publishing is unavailable until worker, destination, and publishing checks are all ready.</p>}
      </div>}
    </>}
    <div className="signals-action-footer">
      <span className="signals-action-time"><Clock3 size={13}/> Updated {formatDate(action.updated)}</span>
      <div className="signals-action-buttons">
        {action.canConfirm && <button className="signals-button primary" onClick={onConfirm} disabled={!canConfirm || actionError || confirmPending || uncertain} data-testid="button-confirm-signal-action"><ShieldCheck size={14}/>{confirmPending ? 'Confirming…' : isPublishAction ? 'Confirm publish' : 'Confirm action'}</button>}
        {action.canCancel && <button className="signals-button secondary" onClick={onCancel} disabled={cancelPending || actionError || uncertain} data-testid="button-cancel-signal-action"><X size={14}/>{cancelPending ? 'Cancelling…' : 'Cancel action'}</button>}
      </div>
    </div>
  </div>;
}
