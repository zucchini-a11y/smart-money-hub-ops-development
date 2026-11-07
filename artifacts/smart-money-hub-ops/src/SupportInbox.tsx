import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  getGetPortalCaseQueryKey,
  getGetPortalDashboardQueryKey,
  getGetPortalWebsiteSupportConversationQueryKey,
  getGetPortalWebsiteSupportSettingsQueryKey,
  getListPortalCasesQueryKey,
  getListPortalStaffQueryKey,
  getListPortalWebsiteSupportConversationsQueryKey,
  useAcceptPortalWebsiteSupportConversation,
  useAddPortalCaseNote,
  useAssignPortalCase,
  useAssignPortalWebsiteSupportConversation,
  useClosePortalCase,
  useClosePortalWebsiteSupportConversation,
  useCreatePortalCaseReply,
  useGetPortalCase,
  useGetPortalWebsiteSupportConversation,
  useGetPortalWebsiteSupportSettings,
  useListPortalCases,
  useListPortalStaff,
  useListPortalWebsiteSupportConversations,
  useReplyPortalWebsiteSupportConversation,
  useUpdatePortalWebsiteSupportAvailability,
  useUpdatePortalWebsiteSupportEligibility,
  useUpdatePortalWebsiteSupportSettings,
} from '@workspace/api-client-react';
import type { PortalCaseSummary, PortalSession, PortalWebsiteConversationSummary, PortalWebsiteSupportSettings } from '@workspace/api-client-react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Activity, ArrowLeft, ArrowUpRight, Bot, Check, CheckCircle2, Clock3,
  FileText, Inbox, MessageCircle, MessageSquareText, RefreshCw, Search,
  Send, ShieldCheck, UserRound,
} from 'lucide-react';
import { trackEvent } from '@/lib/analytics';

type InboxItem =
  | { kind: 'case'; key: string; data: PortalCaseSummary }
  | { kind: 'website'; key: string; data: PortalWebsiteConversationSummary };

type InboxStatusFilter = 'needs_attention' | 'all' | 'active' | 'closed';
type InboxSourceFilter = 'all' | 'case' | 'website';

const newRequestId = () => (
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `portal-${Date.now()}-${Math.random().toString(36).slice(2)}`
);

const readableError = (error: unknown, fallback: string) => (
  error instanceof Error && error.message ? error.message : fallback
);

const statusText = (status: string) => status.replaceAll('_', ' ');
const statusClass = (status: string) => status.toLowerCase().replaceAll('_', '-');
const itemKey = (item: InboxItem) => item.key;

function itemUpdatedAt(item: InboxItem) {
  return item.kind === 'case' ? item.data.updated : item.data.lastMessageAt;
}

function itemIsClosed(item: InboxItem) {
  return item.data.status === 'closed';
}

function itemNeedsAttention(item: InboxItem) {
  if (item.kind === 'case') return item.data.status === 'open' || item.data.status === 'reply_uncertain';
  return item.data.status === 'queued';
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Time unavailable';
  const minutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60_000));
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1_440) return `${Math.floor(minutes / 60)}h ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function fullTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Time unavailable' : date.toLocaleString();
}

function SourceBadge({ item }: { item: InboxItem }) {
  const label = item.kind === 'case' ? 'Member case' : 'Website chat';
  const Icon = item.kind === 'case' ? Bot : MessageCircle;
  return <span className={`support-source support-source-${item.kind}`}><Icon size={12}/>{label}</span>;
}

function StatusBadge({ value }: { value: string }) {
  return <span className={`support-status support-status-${statusClass(value)}`}>{statusText(value)}</span>;
}

function caseTitle(item: PortalCaseSummary) {
  return item.question.trim() || 'Member support case';
}

function websiteTitle(item: PortalWebsiteConversationSummary) {
  return item.visitorName?.trim() || 'Website visitor';
}

function itemSearchText(item: InboxItem) {
  if (item.kind === 'case') {
    return `${item.data.caseId} ${item.data.memberId} ${item.data.question} ${item.data.category} ${item.data.priority}`;
  }
  return `${item.data.conversationId} ${item.data.visitorName ?? ''} ${item.data.mode} ${item.data.status}`;
}

export function SupportInbox({ session, initialCaseId }: { session: PortalSession; initialCaseId?: string }) {
  const client = useQueryClient();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<InboxStatusFilter>('needs_attention');
  const [sourceFilter, setSourceFilter] = useState<InboxSourceFilter>('all');
  const [selectedKey, setSelectedKey] = useState(initialCaseId ? `case:${initialCaseId}` : '');
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const [failure, setFailure] = useState('');

  const caseParams = useMemo(() => ({
    status: 'all' as const,
    search: search.trim() || undefined,
    limit: 100,
  }), [search]);
  const websiteParams = useMemo(() => ({ status: 'all' as const, limit: 100 }), []);
  const cases = useListPortalCases(caseParams, {
    query: {
      queryKey: getListPortalCasesQueryKey(caseParams),
      refetchInterval: 8_000,
      refetchIntervalInBackground: false,
    },
  });
  const websiteChats = useListPortalWebsiteSupportConversations(websiteParams, {
    query: {
      queryKey: getListPortalWebsiteSupportConversationsQueryKey(websiteParams),
      refetchInterval: 8_000,
      refetchIntervalInBackground: false,
    },
  });
  const settings = useGetPortalWebsiteSupportSettings({
    query: { queryKey: getGetPortalWebsiteSupportSettingsQueryKey(), staleTime: 30_000 },
  });
  const setAvailability = useUpdatePortalWebsiteSupportAvailability();

  const items = useMemo<InboxItem[]>(() => {
    const caseItems: InboxItem[] = (cases.data?.cases ?? []).map((data) => ({
      kind: 'case',
      key: `case:${data.caseId}`,
      data,
    }));
    const websiteItems: InboxItem[] = (websiteChats.data?.conversations ?? []).map((data) => ({
      kind: 'website',
      key: `website:${data.conversationId}`,
      data,
    }));
    return [...caseItems, ...websiteItems].sort(
      (left, right) => new Date(itemUpdatedAt(right)).getTime() - new Date(itemUpdatedAt(left)).getTime(),
    );
  }, [cases.data?.cases, websiteChats.data?.conversations]);

  const visibleItems = useMemo(() => items.filter((item) => {
    const matchesSource = sourceFilter === 'all' || item.kind === sourceFilter;
    const matchesSearch = !search.trim() || itemSearchText(item).toLowerCase().includes(search.trim().toLowerCase());
    const matchesStatus = statusFilter === 'all'
      || (statusFilter === 'needs_attention' && itemNeedsAttention(item))
      || (statusFilter === 'active' && !itemIsClosed(item))
      || (statusFilter === 'closed' && itemIsClosed(item));
    return matchesSource && matchesSearch && matchesStatus;
  }), [items, search, sourceFilter, statusFilter]);
  const visibleCaseCount = visibleItems.filter((item) => item.kind === 'case').length;
  const visibleWebsiteCount = visibleItems.length - visibleCaseCount;

  useEffect(() => {
    if (initialCaseId) {
      setSelectedKey(`case:${initialCaseId}`);
      setMobileDetailOpen(true);
    }
  }, [initialCaseId]);

  useEffect(() => {
    if (cases.isLoading || websiteChats.isLoading || initialCaseId) return;
    if (selectedKey && visibleItems.some((item) => itemKey(item) === selectedKey)) return;
    setSelectedKey(visibleItems[0] ? itemKey(visibleItems[0]) : '');
    setMobileDetailOpen(false);
  }, [cases.isLoading, websiteChats.isLoading, initialCaseId, selectedKey, visibleItems]);

  const selected = items.find((item) => itemKey(item) === selectedKey);
  const attentionCount = items.filter(itemNeedsAttention).length;
  const visibleAttentionCount = visibleItems.filter(itemNeedsAttention).length;

  const refreshAll = async () => {
    setFailure('');
    await Promise.all([cases.refetch(), websiteChats.refetch(), settings.refetch()]);
  };
  const invalidateInbox = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: getListPortalCasesQueryKey() }),
      client.invalidateQueries({ queryKey: getGetPortalDashboardQueryKey() }),
      client.invalidateQueries({ queryKey: getListPortalWebsiteSupportConversationsQueryKey() }),
      client.invalidateQueries({ queryKey: getGetPortalWebsiteSupportSettingsQueryKey() }),
    ]);
  };
  const selectItem = (item: InboxItem) => {
    setSelectedKey(itemKey(item));
    setMobileDetailOpen(true);
    setFailure('');
  };

  return <main className={`page support-inbox-page ${mobileDetailOpen ? 'support-inbox-mobile-detail-open' : ''}`} data-testid="support-inbox">
    <header className="support-inbox-heading">
      <div>
        <div className="eyebrow">VAYDA OPERATIONS / MEMBER CARE</div>
        <h1>Support inbox</h1>
        <p className="subheading">Member cases and website chats, together in one workspace.</p>
        <div className="support-inbox-counts" aria-label="Visible inbox source counts">
          <span><MessageSquareText size={13}/> {visibleCaseCount} member cases</span>
          <span><MessageCircle size={13}/> {visibleWebsiteCount} website chats</span>
          <span><Inbox size={13}/> {visibleItems.length} visible</span>
        </div>
      </div>
      <div className="support-inbox-actions">
        {session.role === 'agent' && <button
          type="button"
          className={`btn ${settings.data?.self.available ? 'btn-primary' : 'btn-outline'}`}
          disabled={!settings.data?.self.eligible || setAvailability.isPending}
          title={!settings.data?.self.eligible ? 'An owner must confirm your opt-in before you can be available.' : undefined}
          onClick={() => setAvailability.mutate(
            { data: { available: !settings.data?.self.available } },
            { onSuccess: () => void invalidateInbox(), onError: (error) => setFailure(readableError(error, 'Availability could not be updated.')) },
          )}
          data-testid="toggle-website-availability"
        >
          {setAvailability.isPending ? 'Saving…' : !settings.data?.self.eligible ? 'Owner approval required' : settings.data.self.available ? 'Available · turn off' : 'Set available'}
        </button>}
        <button type="button" className="btn btn-outline support-refresh" onClick={() => void refreshAll()} disabled={cases.isFetching || websiteChats.isFetching} data-testid="button-refresh-support-inbox">
          <RefreshCw size={14} className={cases.isFetching || websiteChats.isFetching ? 'support-spin' : ''}/>
          {cases.isFetching || websiteChats.isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
        <span className="support-refresh-label"><span className="secure-dot"/>Auto-refreshes every 8 seconds</span>
      </div>
    </header>

    {failure && <div className="notice notice-error" role="alert" data-testid="status-support-inbox-error">{failure}</div>}
    {(cases.isError || websiteChats.isError) && <div className="notice notice-error" role="alert" data-testid="status-support-source-error">
      {cases.isError && websiteChats.isError
        ? 'Support sources could not be loaded.'
        : cases.isError
          ? 'Member cases could not be loaded. Website chats remain available.'
          : 'Website chats could not be loaded. Member cases remain available.'}
      <button className="btn btn-quiet" type="button" onClick={() => void refreshAll()} data-testid="button-retry-support-sources">Retry</button>
    </div>}

    <section className="support-inbox-summary" aria-label="Conversation summary">
      <div className="support-summary-main"><span className="support-summary-icon"><Inbox size={17}/></span><div><strong>{visibleAttentionCount}</strong><span>need attention in the current view</span></div></div>
      <div className="support-summary-note"><ShieldCheck size={15}/><span>Your staff role determines which conversations and actions the server returns.</span></div>
    </section>

    <section className="support-inbox-workspace">
      <div className="support-inbox-toolbar">
        <div className="support-filter-group" role="group" aria-label="Filter conversations by status">
          {([
            ['needs_attention', 'Needs attention'],
            ['all', 'All'],
            ['active', 'Active'],
            ['closed', 'Closed'],
          ] as const).map(([value, label]) => <button
            key={value}
            type="button"
            className={`support-filter-button ${statusFilter === value ? 'is-active' : ''}`}
            onClick={() => setStatusFilter(value)}
            data-testid={`filter-support-${value}`}
          >{label}{value === 'needs_attention' && <span>{attentionCount}</span>}</button>)}
        </div>
        <div className="support-inbox-search-tools">
          <label className="support-inbox-search">
            <Search size={15}/>
            <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search cases and chats" aria-label="Search support inbox" data-testid="input-support-inbox-search"/>
          </label>
          <select className="filter-select support-source-filter" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value as InboxSourceFilter)} aria-label="Filter conversations by source" data-testid="select-support-source">
            <option value="all">All sources</option>
            <option value="case">Member cases</option>
            <option value="website">Website chats</option>
          </select>
        </div>
      </div>

      <div className="support-inbox-columns">
        <section className="support-inbox-list" aria-label="Unified conversation list">
          <div className="support-inbox-list-head"><div><h2>Conversations</h2><p>{visibleItems.length} shown · most recent first</p></div><span className="support-inbox-total">{visibleItems.length}</span></div>
          {cases.isLoading || websiteChats.isLoading
            ? <div className="support-inbox-loading" aria-label="Loading support conversations">{[0, 1, 2, 3, 4].map((index) => <div className="support-inbox-skeleton" key={index}/>)}</div>
            : visibleItems.length
              ? <div className="support-inbox-list-items">{visibleItems.map((item) => <InboxRow
                key={itemKey(item)}
                item={item}
                selected={selectedKey === itemKey(item)}
                onSelect={() => selectItem(item)}
              />)}</div>
              : <div className="support-inbox-empty"><Search size={20}/><strong>No matching conversations</strong><span>Adjust the source or status filters, or try another search.</span></div>}
        </section>

        <section className="support-inbox-detail" aria-label="Selected conversation">
          {!selected && initialCaseId
            ? <BotCasePane session={session} caseId={initialCaseId} onBack={() => setMobileDetailOpen(false)} onMutated={invalidateInbox}/>
            : !selected
            ? <div className="support-inbox-empty support-inbox-detail-empty"><MessageSquareText size={21}/><strong>Select a conversation</strong><span>Choose a case or website chat to review its full history and available actions.</span></div>
            : selected.kind === 'case'
              ? <BotCasePane session={session} caseId={selected.data.caseId} onBack={() => setMobileDetailOpen(false)} onMutated={invalidateInbox}/>
              : <WebsiteConversationPane session={session} conversationId={selected.data.conversationId} settings={settings.data} settingsLoading={settings.isLoading} onBack={() => setMobileDetailOpen(false)} onMutated={invalidateInbox}/>}
        </section>
      </div>
    </section>

    <SupportRoutingSettings session={session} settings={settings.data} loading={settings.isLoading} error={settings.error} onRetry={() => void settings.refetch()} onMutated={invalidateInbox} />
  </main>;
}

function InboxRow({ item, selected, onSelect }: { item: InboxItem; selected: boolean; onSelect: () => void }) {
  const title = item.kind === 'case' ? caseTitle(item.data) : websiteTitle(item.data);
  const status = item.data.status;
  const description = item.kind === 'case'
    ? `${item.data.priority} priority · ${statusText(item.data.category)}`
    : `${item.data.mode === 'assistant' ? 'Assistant conversation' : 'Human support'} · ${item.data.assignedStaffId ? 'Assigned' : 'Unassigned'}`;
  const reference = item.kind === 'case' ? item.data.caseId : item.data.conversationId;
  return <button
    type="button"
    className={`support-inbox-row ${selected ? 'is-selected' : ''}`}
    onClick={onSelect}
    aria-current={selected ? 'true' : undefined}
    data-testid={`row-support-${item.kind}-${reference}`}
  >
    <div className="support-row-main">
      <span className={`support-row-avatar ${item.kind === 'website' ? 'is-website' : ''}`}>{item.kind === 'case' ? <Bot size={16}/> : <MessageCircle size={16}/>}</span>
      <span className="support-row-copy">
        <span className="support-row-title">{title}</span>
        <span className="support-row-description">{description}</span>
      </span>
      <time className="support-row-time" dateTime={itemUpdatedAt(item)}>{formatTime(itemUpdatedAt(item))}</time>
    </div>
    <div className="support-row-meta"><SourceBadge item={item}/><StatusBadge value={status}/><span className="support-row-assignee">{item.data.assignedStaffId ? 'Assigned' : 'Unassigned'}</span></div>
  </button>;
}

function BotCasePane({ session, caseId, onBack, onMutated }: { session: PortalSession; caseId: string; onBack: () => void; onMutated: () => Promise<void> }) {
  const client = useQueryClient();
  const [replyText, setReplyText] = useState('');
  const [noteText, setNoteText] = useState('');
  const [error, setError] = useState('');
  const [feedback, setFeedback] = useState('');
  const detail = useGetPortalCase(caseId, { query: { queryKey: getGetPortalCaseQueryKey(caseId), enabled: Boolean(caseId), refetchInterval: 8_000, refetchIntervalInBackground: false } });
  const reply = useCreatePortalCaseReply();
  const close = useClosePortalCase();
  const assign = useAssignPortalCase();
  const addNote = useAddPortalCaseNote();
  const canAssign = session.role === 'owner' || session.role === 'manager';
  const staff = useListPortalStaff({ query: { queryKey: getListPortalStaffQueryKey(), enabled: canAssign, staleTime: 30_000 } });
  const item = detail.data;

  const refreshDetail = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: getGetPortalCaseQueryKey(caseId) }),
      onMutated(),
    ]);
  };
  const sendReply = (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setFeedback('');
    const text = replyText.trim();
    if (text.length < 3 || text.length > 3_000) {
      setError('Your reply must be between 3 and 3,000 characters.');
      return;
    }
    reply.mutate({ caseId, data: { text, requestId: newRequestId() } }, {
      onSuccess: async () => {
        trackEvent('support_reply_queued');
        setReplyText('');
        setFeedback('Reply submitted. Delivery status will update when confirmed.');
        await refreshDetail();
      },
      onError: (failure) => setError(readableError(failure, 'Reply could not be submitted. Check the case before retrying.')),
    });
  };
  const closeCase = () => {
    if (!window.confirm('Close this support case? You can review the conversation, but cannot submit another reply.')) return;
    setError('');
    close.mutate({ caseId }, {
      onSuccess: async () => {
        trackEvent('support_case_closed');
        await refreshDetail();
      },
      onError: (failure) => setError(readableError(failure, 'The case could not be closed.')),
    });
  };
  const assignTo = (staffId: string) => {
    setError('');
    assign.mutate({ caseId, data: { assignedStaffId: staffId || null } }, {
      onSuccess: async () => {
        trackEvent('support_case_assigned', { has_assignee: Boolean(staffId) });
        await refreshDetail();
      },
      onError: (failure) => setError(readableError(failure, 'The case could not be assigned.')),
    });
  };
  const saveNote = (event: FormEvent) => {
    event.preventDefault();
    setError('');
    const text = noteText.trim();
    if (text.length < 3 || text.length > 3_000) {
      setError('Your private note must be between 3 and 3,000 characters.');
      return;
    }
    addNote.mutate({ caseId, data: { text } }, {
      onSuccess: async () => { setNoteText(''); await refreshDetail(); },
      onError: (failure) => setError(readableError(failure, 'The private note could not be saved.')),
    });
  };

  if (detail.isLoading) return <div className="support-detail-loading" aria-label="Loading member case"><div/><div/><div/></div>;
  if (detail.isError) return <div className="support-inbox-empty"><CircleError/><strong>Case unavailable</strong><span>{readableError(detail.error, 'This case is not available to your account.')}</span><button className="btn btn-outline" type="button" onClick={() => void detail.refetch()} data-testid="button-retry-case-detail">Retry</button></div>;
  if (!item) return <div className="support-inbox-empty"><CircleError/><strong>Case not found</strong><span>This case may have been removed or you may not have access.</span></div>;

  const isClosed = item.status === 'closed';
  return <div className="support-detail-content">
    <div className="support-detail-header">
      <button type="button" className="support-back-button" onClick={onBack} aria-label="Back to conversations" data-testid="button-back-to-inbox"><ArrowLeft size={15}/><span>Inbox</span></button>
      <div className="support-detail-heading">
        <div><div className="support-detail-overline">MEMBER CASE · {item.caseId}</div><h2>{caseTitle(item)}</h2></div>
        <div className="support-detail-controls"><StatusBadge value={item.status}/>{!isClosed && <button type="button" className="btn btn-outline" onClick={closeCase} disabled={close.isPending} data-testid="button-close-case">{close.isPending ? 'Closing…' : 'Close case'} <Check size={14}/></button>}</div>
      </div>
      <div className="support-detail-context">
        <span><UserRound size={13}/><strong>Member {item.memberId}</strong></span>
        <span><Clock3 size={13}/>Submitted {fullTime(item.created)}</span>
        <span><Activity size={13}/>Updated {formatTime(item.updated)}</span>
        <span><ShieldCheck size={13}/>{statusText(item.workflowStatus)}</span>
      </div>
    </div>

    {(error || feedback) && <div className={`notice ${error ? 'notice-error' : 'notice-info'}`} role={error ? 'alert' : 'status'} data-testid={error ? 'status-case-error' : 'status-reply-success'}>{error || feedback}</div>}

    <div className="support-case-meta-grid">
      <div><span>Priority</span><strong>{statusText(item.priority)}</strong></div>
      <div><span>Category</span><strong>{statusText(item.category)}</strong></div>
      <div><span>Assigned to</span>{canAssign
        ? <select className="filter-select" aria-label="Assign member case" value={item.assignedStaffId ?? ''} onChange={(event) => assignTo(event.target.value)} disabled={assign.isPending || staff.isLoading || staff.isError} data-testid="select-case-assignee">
            <option value="">Unassigned</option>{staff.data?.staff.filter((person) => person.active && person.role !== 'owner').map((person) => <option value={person.staffId} key={person.staffId}>{person.displayName} · {person.role}</option>)}
          </select>
        : <strong>{item.assignedStaffId === session.staffId ? 'You' : item.assignedStaffId ? 'Assigned' : 'Unassigned'}</strong>}</div>
    </div>

    <section className="support-thread" aria-label="Member case conversation">
      <div className="support-thread-title"><div><h3>Conversation</h3><p>Member request and staff replies</p></div><span>{item.replies.length} {item.replies.length === 1 ? 'reply' : 'replies'}</span></div>
      <article className="support-message support-message-member">
        <div className="support-message-head"><strong>Member {item.memberId}</strong><time>{fullTime(item.created)}</time></div><p>{item.question}</p>
      </article>
      {item.replies.map((entry) => <article className="support-message support-message-staff" key={entry.replyId} data-testid={`reply-${entry.replyId}`}>
        <div className="support-message-head"><strong>{entry.responderName}</strong><span><StatusBadge value={entry.status}/><time>{fullTime(entry.created)}</time></span></div><p>{entry.text}</p>
      </article>)}
      {!item.replies.length && <div className="support-inline-empty">No staff replies yet.</div>}
    </section>

    <details className="support-detail-disclosure">
      <summary>Private staff notes <span>{item.notes.length} saved</span></summary>
      {item.notes.map((note) => <article className="support-note" key={note.noteId} data-testid={`note-${note.noteId}`}><div><strong>{note.responderName}</strong><time>{fullTime(note.created)}</time></div><p>{note.text}</p></article>)}
      {!isClosed && <form onSubmit={saveNote} className="support-note-form"><label htmlFor={`support-note-${caseId}`}>Add an internal note</label><textarea id={`support-note-${caseId}`} value={noteText} onChange={(event) => setNoteText(event.target.value)} maxLength={3_000} placeholder="Visible only to authorized staff…" data-testid="input-private-note"/><div className="support-form-footer"><span>Not sent to the member</span><button type="submit" className="btn btn-outline" disabled={addNote.isPending || noteText.trim().length < 3} data-testid="button-save-private-note">{addNote.isPending ? 'Saving…' : 'Save note'}</button></div></form>}
    </details>

    <details className="support-detail-disclosure">
      <summary>Case activity <span>{item.events.length} events</span></summary>
      {item.events.length ? item.events.map((event) => <article className="support-note" key={event.eventId} data-testid={`case-event-${event.eventId}`}><div><strong>{event.actorName}</strong><time>{fullTime(event.created)}</time></div><p>{statusText(event.eventType)}{event.newValue ? ` · ${event.newValue}` : ''}</p></article>) : <div className="support-inline-empty">No case changes recorded yet.</div>}
    </details>

    {!isClosed
      ? <form className="support-reply-form" onSubmit={sendReply}>
          <label htmlFor={`support-reply-${caseId}`}>Reply to member</label>
          <textarea id={`support-reply-${caseId}`} value={replyText} onChange={(event) => setReplyText(event.target.value)} minLength={3} maxLength={3_000} placeholder="Write a clear, helpful response…" data-testid="input-reply-text"/>
          <div className="support-form-footer"><span>Sent under your staff display name · {replyText.length}/3,000</span><button type="submit" className="btn btn-primary" disabled={reply.isPending || replyText.trim().length < 3} data-testid="button-send-reply">{reply.isPending ? 'Submitting…' : 'Submit reply'} <ArrowUpRight size={14}/></button></div>
        </form>
      : <div className="support-closed-notice">This case is closed. The conversation remains available for review.</div>}
  </div>;
}

function WebsiteConversationPane({ session, conversationId, settings, settingsLoading, onBack, onMutated }: {
  session: PortalSession;
  conversationId: string;
  settings?: PortalWebsiteSupportSettings;
  settingsLoading: boolean;
  onBack: () => void;
  onMutated: () => Promise<void>;
}) {
  const client = useQueryClient();
  const [replyText, setReplyText] = useState('');
  const [error, setError] = useState('');
  const detail = useGetPortalWebsiteSupportConversation(conversationId, {
    query: { queryKey: getGetPortalWebsiteSupportConversationQueryKey(conversationId), enabled: Boolean(conversationId), refetchInterval: 5_000, refetchIntervalInBackground: false },
  });
  const accept = useAcceptPortalWebsiteSupportConversation();
  const respond = useReplyPortalWebsiteSupportConversation();
  const assign = useAssignPortalWebsiteSupportConversation();
  const close = useClosePortalWebsiteSupportConversation();
  const selected = detail.data?.conversation;
  const reload = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: getGetPortalWebsiteSupportConversationQueryKey(conversationId) }),
      onMutated(),
    ]);
  };
  const sendReply = (event: FormEvent) => {
    event.preventDefault();
    setError('');
    const text = replyText.trim();
    if (!text || text.length > 2_000) return;
    respond.mutate({ conversationId, data: { text, requestId: newRequestId() } }, {
      onSuccess: () => { setReplyText(''); void reload(); },
      onError: (failure) => setError(readableError(failure, 'Reply could not be sent.')),
    });
  };

  if (detail.isLoading) return <div className="support-detail-loading" aria-label="Loading website chat"><div/><div/><div/></div>;
  if (detail.isError) return <div className="support-inbox-empty"><CircleError/><strong>Website chat unavailable</strong><span>{readableError(detail.error, 'This conversation is not available to your account.')}</span><button type="button" className="btn btn-outline" onClick={() => void detail.refetch()} data-testid="button-retry-website-chat">Retry</button></div>;
  if (!selected) return <div className="support-inbox-empty"><CircleError/><strong>Conversation not found</strong><span>This chat may have been removed or you may not have access.</span></div>;

  const isClosed = selected.status === 'closed';
  const assignedToCurrentAgent = session.role === 'agent' && selected.assignedStaffId === session.staffId;
  const canAssign = (session.role === 'owner' || session.role === 'manager') && settings?.canAssign;
  const canReply = assignedToCurrentAgent && !isClosed;
  const closeChat = () => close.mutate({ conversationId }, {
    onSuccess: () => void reload(),
    onError: (failure) => setError(readableError(failure, 'The chat could not be closed.')),
  });

  return <div className="support-detail-content">
    <div className="support-detail-header">
      <button type="button" className="support-back-button" onClick={onBack} aria-label="Back to conversations" data-testid="button-back-to-inbox"><ArrowLeft size={15}/><span>Inbox</span></button>
      <div className="support-detail-heading">
        <div><div className="support-detail-overline">PUBLIC WEBSITE / {conversationId.slice(0, 12)}</div><h2>{selected.visitorName || 'Website visitor'}</h2></div>
        <div className="support-detail-controls"><StatusBadge value={selected.status}/>{!isClosed && <button type="button" className="btn btn-outline" onClick={closeChat} disabled={close.isPending} data-testid="button-close-website-chat">{close.isPending ? 'Closing…' : 'Close chat'} <Check size={14}/></button>}</div>
      </div>
      <div className="support-detail-context">
        <span><MessageCircle size={13}/><strong>{selected.mode === 'assistant' ? 'Assistant conversation' : 'Human support'}</strong></span>
        <span><Clock3 size={13}/>Started {fullTime(selected.created)}</span>
        <span><Activity size={13}/>Updated {formatTime(selected.lastMessageAt)}</span>
        <span><UserRound size={13}/>{selected.assignedStaffId ? 'Assigned' : 'Unassigned'}</span>
      </div>
    </div>

    {error && <div className="notice notice-error" role="alert" data-testid="status-website-chat-error">{error}</div>}
    {canAssign && selected.status !== 'closed' && <div className="support-assignment-strip">
      <label htmlFor={`website-assign-${conversationId}`}>Assign to available agent</label>
      <select id={`website-assign-${conversationId}`} className="filter-select" value={selected.assignedStaffId ?? ''} onChange={(event) => assign.mutate({ conversationId, data: { assignedStaffId: event.target.value || null } }, { onSuccess: () => void reload(), onError: (failure) => setError(readableError(failure, 'Assignment could not be changed.')) })} disabled={assign.isPending || settingsLoading} data-testid="select-website-chat-assignee">
        <option value="">Unassigned</option>{settings?.agents.filter((agent) => agent.eligible && agent.available).map((agent) => <option key={agent.staffId} value={agent.staffId}>{agent.displayName}</option>)}
      </select>
      {assign.isPending && <span>Saving…</span>}
    </div>}

    <section className="support-thread support-website-thread" aria-label="Website support conversation">
      <div className="support-thread-title"><div><h3>Conversation</h3><p>Website visitor and support history</p></div><span>{detail.data?.messages.length ?? 0} messages</span></div>
      {detail.data?.messages.length ? detail.data.messages.map((message) => {
        const isStaff = message.senderType === 'staff';
        const label = message.senderType === 'assistant' ? 'Assistant' : isStaff ? message.displayName || 'Support agent' : message.senderType === 'visitor' ? selected.visitorName || 'Visitor' : 'System';
        return <article className={`support-message ${isStaff ? 'support-message-staff' : 'support-message-member'}`} key={message.messageId}>
          <div className="support-message-head"><strong>{label}</strong><time>{fullTime(message.created)}</time></div><p>{message.text}</p>
        </article>;
      }) : <div className="support-inline-empty">No messages are available for this conversation.</div>}
    </section>

    {session.role === 'agent' && selected.status === 'queued' && <div className="support-accept-strip"><div><strong>This chat is waiting for an eligible agent.</strong><span>Accept it to take responsibility before replying.</span></div><button type="button" className="btn btn-primary" onClick={() => accept.mutate({ conversationId }, { onSuccess: () => void reload(), onError: (failure) => setError(readableError(failure, 'The chat could not be accepted.')) })} disabled={accept.isPending} data-testid="button-accept-website-chat">{accept.isPending ? 'Accepting…' : 'Accept conversation'} <Check size={14}/></button></div>}

    {canReply && <form className="support-reply-form" onSubmit={sendReply}>
      <label htmlFor={`website-reply-${conversationId}`}>Reply to visitor</label>
      <textarea id={`website-reply-${conversationId}`} value={replyText} onChange={(event) => setReplyText(event.target.value)} maxLength={2_000} rows={3} placeholder="Write a clear, helpful reply…" data-testid="input-website-chat-reply"/>
      <div className="support-form-footer"><span>Only assigned agents can reply to this chat.</span><button type="submit" className="btn btn-primary" disabled={!replyText.trim() || respond.isPending} data-testid="button-send-website-chat-reply">{respond.isPending ? 'Sending…' : 'Send reply'} <Send size={14}/></button></div>
    </form>}
    {!canReply && !isClosed && session.role === 'agent' && <div className="support-permission-note"><ShieldCheck size={15}/>Accept or select a conversation assigned to you to reply.</div>}
    {!canReply && !isClosed && (session.role === 'owner' || session.role === 'manager') && <div className="support-permission-note"><ShieldCheck size={15}/>Assign this website conversation to an eligible agent to enable replies.</div>}
    {isClosed && <div className="support-closed-notice">This chat is closed. The conversation remains available for review.</div>}
  </div>;
}

function SupportRoutingSettings({ session, settings, loading, error, onRetry, onMutated }: {
  session: PortalSession;
  settings?: PortalWebsiteSupportSettings;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  onMutated: () => Promise<void>;
}) {
  const [failure, setFailure] = useState('');
  const saveTeam = useUpdatePortalWebsiteSupportSettings();
  const eligibility = useUpdatePortalWebsiteSupportEligibility();
  const canSeeAgentControls = session.role === 'owner' || session.role === 'manager';

  return <details className="support-routing-settings">
    <summary><span><ShieldCheck size={16}/><span><strong>Website support routing & eligibility</strong><small>Team, agent opt-in, and availability controls</small></span></span><span className="support-settings-scope">Permission checked by the server</span></summary>
    {failure && <div className="notice notice-error" role="alert">{failure}</div>}
    {loading ? <div className="support-detail-loading"><div/></div> : error ? <div className="notice notice-error" role="alert">{readableError(error, 'Support settings could not be loaded.')} <button className="btn btn-quiet" type="button" onClick={onRetry}>Retry</button></div> : settings && <>
      <div className="support-settings-team">
        <label htmlFor="support-team-select">Support team</label>
        <select id="support-team-select" className="filter-select" value={settings.supportTeamId ?? ''} disabled={!settings.canManage || saveTeam.isPending} onChange={(event) => saveTeam.mutate({ data: { supportTeamId: event.target.value || null } }, { onSuccess: () => void onMutated(), onError: (failureValue) => setFailure(readableError(failureValue, 'Support team could not be saved.')) })} data-testid="select-support-team">
          <option value="">No team selected</option>{settings.teams.map((team) => <option key={team.teamId} value={team.teamId}>{team.name}</option>)}
        </select>
        {!settings.canManage && <p>Only the Owner can change the support team and agent eligibility.</p>}
      </div>
      {canSeeAgentControls && settings.canManage && <div className="support-agent-eligibility">
        <div className="support-agent-eligibility-head"><strong>Agent opt-in</strong><span>Eligibility is explicit and never inferred from a name.</span></div>
        {settings.agents.map((agent) => <AgentEligibility key={agent.staffId} agent={agent} owner={session.role === 'owner'} busy={eligibility.isPending} onSave={(eligible, consentConfirmed) => {
          setFailure('');
          eligibility.mutate({ staffId: agent.staffId, data: { eligible, consentConfirmed } }, { onSuccess: () => void onMutated(), onError: (failureValue) => setFailure(readableError(failureValue, 'Agent eligibility could not be saved.')) });
        }}/>)}
      </div>}
      {session.role === 'agent' && <p className="support-settings-agent-note"><ShieldCheck size={14}/>Availability is controlled above. An Owner must confirm eligibility first.</p>}
    </>}
  </details>;
}

function AgentEligibility({ agent, onSave, busy, owner }: {
  agent: { staffId: string; displayName: string; eligible: boolean; available: boolean };
  onSave: (eligible: boolean, consentConfirmed: boolean) => void;
  busy: boolean;
  owner: boolean;
}) {
  const [confirm, setConfirm] = useState(false);
  return <div className="support-agent-row">
    <div><strong>{agent.displayName}</strong><span>{agent.available ? 'Available' : 'Unavailable'} · {agent.eligible ? 'Eligible' : 'Not eligible'}</span></div>
    {owner && <div className="support-agent-controls"><label><input type="checkbox" checked={agent.eligible} disabled={busy} onChange={(event) => {
      if (event.target.checked) setConfirm(true);
      else onSave(false, false);
    }}/>Eligible</label>
      {confirm && <div className="support-opt-in-confirm"><p>Confirm this person self-identifies as a female support agent and has opted in to public chats. Do not infer eligibility from their name.</p><button type="button" className="btn btn-primary" disabled={busy} onClick={() => { onSave(true, true); setConfirm(false); }}>Confirm opt-in</button><button type="button" className="btn btn-quiet" onClick={() => setConfirm(false)}>Cancel</button></div>}
    </div>}
  </div>;
}

function CircleError() {
  return <span className="support-error-mark" aria-hidden="true">!</span>;
}
