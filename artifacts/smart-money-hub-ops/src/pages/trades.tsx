import { useMemo, useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { Form } from '@/components/ui/form';
import {
  useListPortalTrades,
  useGetPortalTrade,
  useCreatePortalTradeAction,
  useGetPortalTradeAction,
  useConfirmPortalTradeAction,
  useCancelPortalTradeAction,
  getListPortalTradesQueryKey,
  getGetPortalTradeQueryKey,
  getGetPortalTradeActionQueryKey,
} from '@workspace/api-client-react';
import type { PortalTradeActionInputAction, PortalTradeActionValues } from '@workspace/api-client-react';
import {
  Activity, AlertTriangle, ArrowUpRight, Check, ChevronRight, CircleHelp,
  Clock3, Database, FileText, History, LockKeyhole, Plus, RefreshCw,
  ShieldCheck, Target, X,
} from 'lucide-react';

const ACTIONS: { value: PortalTradeActionInputAction; label: string; hint: string }[] = [
  { value: 'entry_bundle', label: 'Entry bundle', hint: 'Set entry, stop loss and first target.' },
  { value: 'sl_tp', label: 'Stop loss + target', hint: 'Update a stop loss and a target together.' },
  { value: 'sl', label: 'Stop loss', hint: 'Publish a stop-loss update.' },
  { value: 'tp', label: 'Target update', hint: 'Add or adjust a target.' },
  { value: 'hit', label: 'Mark target hit', hint: 'Record a target hit as partial or final.' },
  { value: 'partial', label: 'Partial close', hint: 'Record a confirmed partial close.' },
  { value: 'be', label: 'Move to breakeven', hint: 'Requires explicit confirmation that the stop moved.' },
  { value: 'trail', label: 'Trail stop', hint: 'Set the administrator-supplied trailing stop value.' },
  { value: 'close', label: 'Close trade', hint: 'Select the outcome before creating a draft.' },
  { value: 'cancel', label: 'Cancel unentered trade', hint: 'For a trade that has not been entered.' },
  { value: 'invalidate', label: 'Invalidate entered trade', hint: 'For a trade already entered; provide the reason.' },
  { value: 'custom', label: 'Custom message', hint: 'Supply the exact message text for review.' },
  { value: 'edit', label: 'Edit linked signal message', hint: 'Replace the exact text of the linked Telegram signal.' },
];

type InputField = 'entry' | 'stopLoss' | 'targetNumber' | 'targetPrice' | 'percentage' | 'reason' | 'note' | 'text' | 'exitPrice';
const labels: Record<InputField, string> = {
  entry: 'Entry price', stopLoss: 'Stop-loss price', targetNumber: 'Target number',
  targetPrice: 'Target price', percentage: 'Percentage closed', reason: 'Reason',
  note: 'Note', text: 'Exact message text', exitPrice: 'Exit price',
};

function fieldsFor(action: PortalTradeActionInputAction): InputField[] {
  switch (action) {
    case 'entry_bundle': return ['entry', 'stopLoss', 'targetNumber', 'targetPrice'];
    case 'sl_tp': return ['stopLoss', 'targetNumber', 'targetPrice'];
    case 'sl': case 'trail': return ['stopLoss'];
    case 'tp': return ['targetNumber', 'targetPrice'];
    case 'hit': return ['targetNumber'];
    case 'partial': return ['targetPrice', 'percentage'];
    case 'close': return ['exitPrice'];
    case 'cancel': case 'invalidate': return ['reason'];
    case 'custom': return ['text'];
    case 'edit': return ['text'];
    case 'be': return [];
  }
}

function human(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}
function date(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(parsed);
}
function statusTone(status: string) {
  const normalized = status.toLowerCase();
  if (['active', 'open', 'ready', 'completed', 'published', 'confirmed_buy', 'confirmed_sell'].includes(normalized)) return 'good';
  if (['uncertain', 'failed', 'stopped', 'migration_required', 'cancelled', 'invalidated'].includes(normalized)) return 'caution';
  return 'neutral';
}
function requestMayHaveReachedServer(error: unknown) {
  if (!error || typeof error !== 'object') return true;
  const status = (error as { status?: number }).status;
  return typeof status !== 'number' || status >= 500;
}
function errorText(error: unknown, fallback: string) {
  return error && typeof error === 'object' && 'message' in error &&
    typeof error.message === 'string' ? error.message : fallback;
}
function TradeLoading() {
  return <div className="trade-loading" data-testid="trade-loading" aria-label="Loading trade records">
    <div className="trade-loading-top"><span className="skeleton"/><span className="skeleton"/></div>
    {[0, 1, 2].map((item) => <div className="trade-skeleton-row" key={item}><span className="skeleton"/><span className="skeleton"/><span className="skeleton"/></div>)}
  </div>;
}

export default function TradeManagement() {
  const client = useQueryClient();
  const form = useForm<Record<string, string | boolean>>({ defaultValues: {} });
  const list = useListPortalTrades({ query: { queryKey: getListPortalTradesQueryKey(), staleTime: 10_000 } });
  const management = list.data;
  const trades = management?.trades ?? [];
  const [selectedTradeId, setSelectedTradeId] = useState('');
  const selectedTrade = useMemo(() => trades.find((trade) => trade.tradeId === selectedTradeId) ?? trades[0], [trades, selectedTradeId]);
  const activeTradeId = selectedTrade?.tradeId ?? '';
  const detail = useGetPortalTrade(activeTradeId, {
    query: { enabled: Boolean(activeTradeId), queryKey: getGetPortalTradeQueryKey(activeTradeId), staleTime: 10_000 },
  });

  const [action, setAction] = useState<PortalTradeActionInputAction>('entry_bundle');
  const [values, setValues] = useState<Record<string, string>>({});
  const [targetStatus, setTargetStatus] = useState<'partial' | 'final'>('partial');
  const [outcome, setOutcome] = useState<'Win' | 'Breakeven' | 'Loss' | 'Unrecorded'>('Win');
  const [stopMoved, setStopMoved] = useState(false);
  const [outcomeConfirmed, setOutcomeConfirmed] = useState(false);
  const [activeCommandId, setActiveCommandId] = useState('');
  const [feedback, setFeedback] = useState('');
  const [createUncertain, setCreateUncertain] = useState(false);
  const [operationUncertain, setOperationUncertain] = useState(false);
  const createAction = useCreatePortalTradeAction();
  const actionQuery = useGetPortalTradeAction(activeCommandId, {
    query: { enabled: Boolean(activeCommandId), queryKey: getGetPortalTradeActionQueryKey(activeCommandId), refetchInterval: (query) => {
      const current = query.state.data;
      return current && ['queued', 'processing'].includes(current.status) ? 2500 : false;
    } },
  });
  const confirmAction = useConfirmPortalTradeAction();
  const cancelAction = useCancelPortalTradeAction();
  const currentAction = actionQuery.data;
  const fieldList = fieldsFor(action);
  const selectedTradeOpen = Boolean(
    selectedTrade && ['ACTIVE', 'CONFIRMED_BUY', 'CONFIRMED_SELL'].includes(selectedTrade.state),
  );

  const invalidateRelated = (tradeId: string, commandId?: string) => {
    void client.invalidateQueries({ queryKey: getListPortalTradesQueryKey() });
    void client.invalidateQueries({ queryKey: getGetPortalTradeQueryKey(tradeId) });
    if (commandId) void client.invalidateQueries({ queryKey: getGetPortalTradeActionQueryKey(commandId) });
  };
  const setActionType = (next: PortalTradeActionInputAction) => {
    setAction(next);
    setValues({});
    setStopMoved(false);
    setOutcomeConfirmed(false);
    setFeedback('');
  };
  const actionValues = (): PortalTradeActionValues => {
    const clean: Record<string, string> = {};
    fieldList.forEach((field) => {
      const value = values[field]?.trim();
      if (value) clean[field] = value;
    });
    if (action === 'hit') clean.targetStatus = targetStatus;
    if (action === 'close') {
      clean.outcome = outcome;
      if (outcomeConfirmed) clean.outcomeConfirmed = 'true';
    }
    if (action === 'be' && stopMoved) clean.stopMoved = 'true';
    return Object.fromEntries(Object.entries(clean).map(([key, value]) => {
      if (key === 'stopMoved' || key === 'outcomeConfirmed') return [key, value === 'true'];
      return [key, value];
    })) as PortalTradeActionValues;
  };
  const missingRequired = fieldList.filter((field) => !(action === 'close' && field === 'exitPrice')).some((field) => !values[field]?.trim())
    || (action === 'hit' && !targetStatus)
    || (action === 'be' && !stopMoved)
    || (action === 'close' && !outcomeConfirmed)
    || (action === 'edit' && !fieldList.some((field) => values[field]?.trim()));
  const canCreateDraft = Boolean(
    activeTradeId && selectedTradeOpen && selectedTrade?.hasLinkedPost
      && management?.workerStatus === 'ready' && !missingRequired
      && !createAction.isPending && !createUncertain,
  );

  const createDraft = (_formValues: Record<string, string | boolean>) => {
    if (!canCreateDraft) return;
    setFeedback('');
    const requestId = globalThis.crypto?.randomUUID?.() ?? `trade-action-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    createAction.mutate({ tradeId: activeTradeId, data: { action, requestId, input: actionValues() } }, {
      onSuccess: (created) => {
        setActiveCommandId(created.commandId);
        setFeedback('Draft created. Review the server preview before taking any further action.');
        invalidateRelated(activeTradeId, created.commandId);
      },
      onError: (failure) => {
        const ambiguous = requestMayHaveReachedServer(failure);
        setCreateUncertain(ambiguous);
        setFeedback(ambiguous
          ? 'The request outcome could not be verified. Do not submit it again. Refresh the records and review the trade history before continuing.'
          : errorText(failure, 'The draft was not created. Check the fields and try again.'));
        invalidateRelated(activeTradeId);
      },
    });
  };
  const confirmPublish = () => {
    if (!currentAction || !selectedTrade || !canConfirm) return;
    confirmAction.mutate({ commandId: currentAction.commandId }, {
      onSuccess: (result) => {
        setFeedback(result.safeResult || `Action status: ${human(result.status)}.`);
        invalidateRelated(selectedTrade.tradeId, result.commandId);
      },
      onError: (failure) => {
        const ambiguous = requestMayHaveReachedServer(failure);
        setOperationUncertain(ambiguous);
        setFeedback(ambiguous
          ? 'Confirmation outcome could not be verified. Do not retry; refresh the action status and inspect the trade history.'
          : errorText(failure, 'The action was not confirmed. Review the latest status before continuing.'));
        invalidateRelated(selectedTrade.tradeId, currentAction.commandId);
      },
    });
  };
  const cancelDraft = () => {
    if (!currentAction?.canCancel || !selectedTrade) return;
    cancelAction.mutate({ commandId: currentAction.commandId }, {
      onSuccess: (result) => {
        setFeedback(result.safeResult || 'Draft cancelled.');
        invalidateRelated(selectedTrade.tradeId, result.commandId);
      },
      onError: (failure) => {
        const ambiguous = requestMayHaveReachedServer(failure);
        setOperationUncertain(ambiguous);
        setFeedback(ambiguous
          ? 'Draft cancellation could not be verified. Refresh the action status before taking further action.'
          : errorText(failure, 'The draft could not be cancelled. Refresh its status.'));
        invalidateRelated(selectedTrade.tradeId, currentAction.commandId);
      },
    });
  };
  const refreshActionStatus = async () => {
    const result = await actionQuery.refetch();
    if (result.data && !['uncertain', 'failed'].includes(result.data.status)) {
      setOperationUncertain(false);
      setFeedback('Latest action status loaded. Review it before deciding what to do next.');
    }
  };

  const canConfirm = Boolean(
    management?.workerStatus === 'ready'
    && management.publishingEnabled
    && management.destinationsVerified
    && selectedTradeOpen
    && currentAction?.canConfirm
    && selectedTrade?.hasLinkedPost
    && currentAction.status === 'preview_ready'
  );
  const gateReasons = [
    management?.workerStatus !== 'ready' ? `Worker ${human(management?.workerStatus ?? 'unknown')}` : '',
    !management?.publishingEnabled ? 'Publishing disabled' : '',
    !management?.destinationsVerified ? 'Destinations not verified' : '',
    !selectedTrade?.hasLinkedPost ? 'No linked post' : '',
    currentAction && !currentAction.canConfirm ? 'Action is not confirmable' : '',
    currentAction && currentAction.status !== 'preview_ready' ? `Status: ${human(currentAction.status)}` : '',
  ].filter(Boolean);

  if (list.isLoading) return <main className="page trade-page"><TradeLoading/></main>;
  if (list.isError) return <main className="page trade-page"><section className="trade-state-panel" data-testid="trade-load-error"><div className="trade-state-icon"><CircleHelp/></div><h1>Trade records unavailable</h1><p>{list.error instanceof Error ? list.error.message : 'We could not load records for this deployment environment.'}</p><button className="btn btn-outline" onClick={() => list.refetch()} data-testid="button-refresh-trades"><RefreshCw size={15}/>Refresh records</button></section></main>;

  return <main className="page trade-page">
    <header className="trade-page-heading">
      <div><div className="trade-kicker"><span><Activity size={14}/></span> OWNER OPERATIONS <i/> PRIVATE TRADE CONTROL</div>
        <h1>Trade management</h1>
        <p className="subheading">Review a signal, prepare a draft, then make an explicit publishing decision.</p>
      </div>
      <button className="btn btn-outline trade-refresh" onClick={() => list.refetch()} disabled={list.isFetching} data-testid="button-refresh-trades">
        <RefreshCw size={15} className={list.isFetching ? 'trade-refreshing' : ''}/>{list.isFetching ? 'Refreshing' : 'Refresh'}
      </button>
    </header>

    {management && <section className={`trade-environment ${management.environment === 'production' ? 'environment-production' : 'environment-development'}`} aria-label="Current deployment environment" data-testid="trade-environment">
      <div className="trade-environment-mark"><Database size={18}/></div>
      <div className="trade-environment-copy"><span className="trade-overline">FIXED BY THIS DEPLOYMENT</span><strong>{management.environment === 'development_test' ? 'Development · isolated test data' : 'Production data'}</strong><p>Environment cannot be changed from this portal. This page reads and acts only within the current deployment scope.</p></div>
      <span className={`trade-chip tone-${statusTone(management.workerStatus)}`} data-testid="trade-worker-status"><span className="chip-dot"/>{human(management.workerStatus)}</span>
    </section>}

    {management && <section className="trade-readiness" aria-label="Publishing readiness">
      <div className="readiness-heading"><div><span className="trade-overline">PUBLISHING GUARDRAILS</span><strong>All checks stay visible before confirmation</strong></div><span className="readiness-lock"><LockKeyhole size={14}/> Owner only</span></div>
      <div className="readiness-items">
        <div className={`readiness-item ${management.workerStatus === 'ready' ? 'ready' : ''}`} data-testid="readiness-worker"><span>{management.workerStatus === 'ready' ? <Check size={13}/> : <AlertTriangle size={13}/>}</span><div><small>Worker</small><strong>{human(management.workerStatus)}</strong></div></div>
        <div className={`readiness-item ${management.publishingEnabled ? 'ready' : ''}`} data-testid="readiness-publishing"><span>{management.publishingEnabled ? <Check size={13}/> : <X size={13}/>}</span><div><small>Publishing</small><strong>{management.publishingEnabled ? 'Enabled' : 'Disabled'}</strong></div></div>
        <div className={`readiness-item ${management.destinationsVerified ? 'ready' : ''}`} data-testid="readiness-destinations"><span>{management.destinationsVerified ? <Check size={13}/> : <AlertTriangle size={13}/>}</span><div><small>Destinations</small><strong>{management.destinationsVerified ? 'Verified' : 'Not verified'}</strong></div></div>
        <div className="readiness-item"><span><FileText size={13}/></span><div><small>Trade records</small><strong>{trades.length} {trades.length === 1 ? 'trade' : 'trades'}</strong></div></div>
      </div>
    </section>}

    {!trades.length ? <section className="trade-state-panel trade-empty" data-testid="trade-empty">
      <div className="trade-state-icon"><Target size={20}/></div><div className="trade-overline">NO RECORDS IN THIS ENVIRONMENT</div><h2>Nothing to manage yet</h2><p>Trade records for the current deployment will appear here. No environment switching or cross-environment data is available.</p>
    </section> : <div className="trade-workspace">
      <section className="trade-list-panel" aria-label="Trade list">
        <div className="trade-list-head"><div><span className="trade-overline">CURRENT ENVIRONMENT</span><h2>Trade records</h2></div><span className="trade-count" data-testid="trade-count">{trades.length.toString().padStart(2, '0')}</span></div>
        <div className="trade-list" data-testid="trade-list">
          {trades.map((trade) => <button
            type="button"
            className={`trade-list-item ${selectedTrade?.tradeId === trade.tradeId ? 'selected' : ''}`}
            key={trade.tradeId}
            onClick={() => { setSelectedTradeId(trade.tradeId); setActiveCommandId(''); setFeedback(''); }}
            data-testid={`button-select-trade-${trade.tradeId}`}
            aria-pressed={selectedTrade?.tradeId === trade.tradeId}
          >
            <span className="trade-symbol">{trade.symbol}</span><span className="trade-list-content"><span className="trade-list-title">{trade.direction} <i/> {human(trade.state)}</span><span className="trade-list-meta">{trade.entry ? `Entry ${trade.entry}` : 'Entry not set'} · Updated {date(trade.updated)}</span><span className="trade-list-tags"><span className={`trade-mini-state tone-${statusTone(trade.state)}`}>{human(trade.state)}</span>{trade.hasLinkedPost && <span className="linked-post"><Check size={11}/> Linked post</span>}</span></span><ChevronRight size={16} className="trade-list-arrow"/>
          </button>)}
        </div>
      </section>

      <section className="trade-detail-column">
        {selectedTrade && <article className="trade-detail-panel" data-testid="trade-detail">
          <div className="trade-detail-heading"><div><span className="trade-overline">SIGNAL OVERVIEW</span><h2>{selectedTrade.symbol}<span>{selectedTrade.direction}</span></h2></div><span className={`trade-chip tone-${statusTone(selectedTrade.state)}`} data-testid="trade-state">{human(selectedTrade.state)}</span></div>
          <div className="trade-levels">
            <div><span>Entry</span><strong>{selectedTrade.entry || 'Not set'}</strong></div><div><span>Stop loss</span><strong>{selectedTrade.stopLoss || 'Not set'}</strong></div>
            <div className="trade-targets"><span>Targets</span><div>{selectedTrade.targets.length ? selectedTrade.targets.map((target) => <span className={`target-pill ${target.hit ? 'target-hit' : ''}`} key={target.number} data-testid={`trade-target-${target.number}`}><b>T{target.number}</b>{target.price}{target.hit && <Check size={11}/>}</span>) : <strong>No targets</strong>}</div></div>
          </div>
          <div className="trade-record-meta"><span><Clock3 size={13}/> Updated {date(selectedTrade.updated)}</span><span><History size={13}/> {selectedTrade.eventCount} recorded events</span><span>Version {selectedTrade.version}</span><span>{selectedTrade.hasLinkedPost ? 'Linked post available' : 'No linked post'}</span></div>
          {detail.isLoading ? <div className="trade-detail-skeleton" data-testid="trade-detail-loading"><span className="skeleton"/><span className="skeleton"/><span className="skeleton"/></div> : detail.isError ? <div className="trade-inline-error" role="alert" data-testid="trade-detail-error"><span>Trade history could not be loaded.</span><button className="btn btn-quiet" onClick={() => detail.refetch()} data-testid="button-retry-trade-detail">Try again</button></div> : detail.data?.history?.length ? <div className="trade-history" data-testid="trade-history"><div className="trade-history-label"><History size={13}/> Recent history</div>{detail.data.history.map((event, index) => <div className="trade-history-row" key={`${event.created}-${index}`} data-testid={`trade-history-${index}`}><span className="history-line"/><p>{event.text}</p><time>{date(event.created)}</time></div>)}</div> : <div className="trade-history-empty" data-testid="trade-history-empty">No recorded history for this trade yet.</div>}
        </article>}

        <section className="trade-composer" aria-label="Create trade action draft">
          <div className="trade-composer-heading"><span className="trade-step">01</span><div><span className="trade-overline">PREPARE A CHANGE</span><h2>Create review draft</h2><p>Values are supplied by you; no prices or outcomes are inferred.</p></div></div>
          <Form {...form}><form className="trade-action-form" onSubmit={form.handleSubmit(createDraft)}>
            <div className="form-field"><label className="form-label" htmlFor="trade-action-select">Action type</label><select id="trade-action-select" className="field-select" value={action} onChange={(event) => setActionType(event.target.value as PortalTradeActionInputAction)} data-testid="select-trade-action">{ACTIONS.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select><span className="trade-field-hint">{ACTIONS.find((item) => item.value === action)?.hint}</span></div>
            {fieldList.length > 0 && <div className="trade-form-grid">{fieldList.map((field) => <div className="form-field" key={field}><label className="form-label" htmlFor={`trade-field-${field}`}>{labels[field]}{action === 'close' && field === 'exitPrice' ? ' (optional)' : ''}</label><input
              id={`trade-field-${field}`}
              className="field-input"
              type={field === 'percentage' ? 'number' : 'text'}
              inputMode={field === 'percentage' ? 'decimal' : 'text'}
              min={field === 'percentage' ? '0.01' : undefined}
              max={field === 'percentage' ? '100' : undefined}
              step={field === 'percentage' ? 'any' : undefined}
              maxLength={field === 'text' ? 3000 : field === 'reason' ? 300 : 100}
              required={action !== 'edit' && field !== 'exitPrice'}
              value={values[field] ?? ''}
              onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))}
              data-testid={`input-trade-${field}`}
            /></div>)}</div>}
            {action === 'hit' && <div className="form-field"><label className="form-label" htmlFor="trade-hit-classification">Hit classification</label><select id="trade-hit-classification" className="field-select" value={targetStatus} onChange={(event) => setTargetStatus(event.target.value as 'partial' | 'final')} data-testid="select-hit-classification"><option value="partial">Partial</option><option value="final">Final</option></select></div>}
            {action === 'close' && <div className="trade-form-grid"><div className="form-field"><label className="form-label" htmlFor="trade-close-outcome">Outcome</label><select id="trade-close-outcome" className="field-select" value={outcome} onChange={(event) => setOutcome(event.target.value as typeof outcome)} data-testid="select-close-outcome"><option value="Win">Win</option><option value="Breakeven">Breakeven</option><option value="Loss">Loss</option><option value="Unrecorded">Unrecorded</option></select></div><label className="trade-check-field"><input type="checkbox" checked={outcomeConfirmed} onChange={(event) => setOutcomeConfirmed(event.target.checked)} data-testid="checkbox-outcome-confirmed"/><span><strong>Outcome confirmed</strong><small>Confirm that this is the intended close outcome.</small></span></label></div>}
            {action === 'be' && <label className="trade-check-field trade-confirm-field"><input type="checkbox" checked={stopMoved} onChange={(event) => setStopMoved(event.target.checked)} data-testid="checkbox-stop-moved"/><span><strong>Stop has been moved to breakeven</strong><small>This confirmation is required before a draft can be created.</small></span></label>}
            {(action === 'cancel' || action === 'invalidate') && <div className="trade-action-caution" data-testid="trade-action-caution"><AlertTriangle size={15}/><span>{action === 'cancel' ? 'Use Cancel only when this trade was not entered.' : 'Use Invalidate only for a trade that was entered. This is distinct from cancelling an unentered setup.'}</span></div>}
            {action === 'edit' && <p className="trade-field-hint">Enter the exact replacement text for the linked signal. This does not change the recorded trade levels.</p>}
            {!selectedTradeOpen && <p className="trade-field-hint">Only open trades can be changed. Closed, cancelled, or invalidated records remain available as history.</p>}
            {selectedTradeOpen && !selectedTrade?.hasLinkedPost && <p className="trade-field-hint">This trade has no linked Telegram message, so updates are blocked.</p>}
            {management?.workerStatus !== 'ready' && <p className="trade-field-hint">The trade worker is not ready. Draft creation is paused until it reconnects.</p>}
            {feedback && <div className={`trade-feedback ${createUncertain ? 'is-caution' : ''}`} role="status" data-testid="trade-action-feedback">{feedback}</div>}
            <button className="btn btn-primary trade-create-button" type="submit" disabled={!canCreateDraft} data-testid="button-create-trade-draft"><Plus size={15}/>{createAction.isPending ? 'Preparing draft…' : 'Create review draft'}</button>
          </form></Form>
        </section>

        {currentAction && <section className="trade-preview-panel" aria-label="Trade action preview" data-testid="trade-action-preview">
          <div className="trade-preview-heading"><span className="trade-step">02</span><div><span className="trade-overline">SERVER-GENERATED PREVIEW</span><h2>Review before publishing</h2><p>This exact text is supplied by the server. No raw identifiers are shown.</p></div><span className={`trade-chip tone-${statusTone(currentAction.status)}`} data-testid="trade-action-status">{human(currentAction.status)}</span></div>
          {actionQuery.isError ? <div className="trade-inline-error" role="alert" data-testid="trade-action-error"><span>Action status could not be refreshed. Do not retry a publish.</span><button className="btn btn-quiet" onClick={() => actionQuery.refetch()} data-testid="button-refresh-action-status">Refresh status</button></div> : <pre className="trade-preview-text" data-testid="trade-preview-text">{currentAction.previewText || 'The server has not returned preview text.'}</pre>}
          {currentAction.safeResult && <p className="trade-safe-result" data-testid="trade-safe-result">{currentAction.safeResult}</p>}
          {['uncertain', 'failed'].includes(currentAction.status) && <div className="trade-action-caution" data-testid="trade-no-retry-notice"><AlertTriangle size={15}/><span>{currentAction.status === 'uncertain' ? 'Delivery is uncertain. Do not publish again; verify the channel and trade history first.' : 'This action failed. No automatic retry is available from this page.'}</span></div>}
          {operationUncertain && <div className="trade-action-caution" data-testid="trade-operation-uncertain"><AlertTriangle size={15}/><span>Last request outcome is unknown. Both action buttons are locked until you refresh and review the latest server status.</span><button type="button" className="btn btn-quiet" onClick={refreshActionStatus} disabled={actionQuery.isFetching} data-testid="button-refresh-action-status">{actionQuery.isFetching ? 'Checking…' : 'Refresh status'}</button></div>}
          {gateReasons.length > 0 && currentAction.status === 'preview_ready' && <div className="trade-gate-note" data-testid="trade-confirm-gate"><LockKeyhole size={14}/><span>Confirmation locked: {gateReasons.join(' · ')}.</span></div>}
          <div className="trade-preview-actions">
            <button className="btn btn-primary" onClick={confirmPublish} disabled={!canConfirm || confirmAction.isPending || actionQuery.isError || operationUncertain || ['uncertain', 'failed'].includes(currentAction.status)} data-testid="button-confirm-trade-publish"><ShieldCheck size={15}/>{confirmAction.isPending ? 'Confirming…' : 'Confirm publish'}</button>
            <button className="btn btn-outline" onClick={cancelDraft} disabled={!currentAction.canCancel || cancelAction.isPending || actionQuery.isError || operationUncertain || ['uncertain', 'failed'].includes(currentAction.status)} data-testid="button-cancel-trade-draft"><X size={15}/>{cancelAction.isPending ? 'Cancelling…' : 'Cancel draft'}</button>
            <span className="trade-preview-created">Updated {date(currentAction.updated)}</span>
          </div>
        </section>}
      </section>
    </div>}

    <footer className="trade-footnote" data-testid="trade-safety-note"><span><LockKeyhole size={14}/></span><p><strong>Operational safety.</strong> Draft creation never publishes. Confirmation is separately gated by worker readiness, publishing settings, verified destinations, server authorization, and a linked post. Telegram acceptance is not proof of broker execution or profit.</p><ArrowUpRight size={14}/></footer>
  </main>;
}
