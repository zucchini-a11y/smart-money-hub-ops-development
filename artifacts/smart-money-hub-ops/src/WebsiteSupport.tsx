import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  getGetWebsiteSupportConversationQueryKey, getGetWebsiteSupportAvailabilityQueryKey,
  getGetWebsiteSupportConversationByIdQueryKey, getListPortalWebsiteSupportConversationsQueryKey,
  getGetPortalWebsiteSupportConversationQueryKey, getGetPortalWebsiteSupportSettingsQueryKey,
  useCreateWebsiteSupportSession, useGetWebsiteSupportConversation, useGetWebsiteSupportAvailability,
  useCreateWebsiteSupportConversation, useCreateWebsiteSupportMessage, useHandoffWebsiteSupportConversation,
  useGetWebsiteSupportConversationById, useListPortalWebsiteSupportConversations,
  useGetPortalWebsiteSupportConversation, useAcceptPortalWebsiteSupportConversation,
  useReplyPortalWebsiteSupportConversation, useAssignPortalWebsiteSupportConversation,
  useClosePortalWebsiteSupportConversation, useGetPortalWebsiteSupportSettings,
  useUpdatePortalWebsiteSupportSettings, useUpdatePortalWebsiteSupportEligibility,
  useUpdatePortalWebsiteSupportAvailability,
} from '@workspace/api-client-react';
import type { PortalSession } from '@workspace/api-client-react';
import { useQueryClient } from '@tanstack/react-query';
import { Bot, Check, ChevronLeft, CircleHelp, Clock3, Headphones, MessageCircle, Send, ShieldCheck, X } from 'lucide-react';

const newRequestId = () => crypto.randomUUID();
const friendlyError = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong. Please try again.';
const WELCOME_DISMISSED_KEY = 'smh-public-support-welcome-dismissed';

function hasDismissedWelcome() {
  try { return window.sessionStorage.getItem(WELCOME_DISMISSED_KEY) === '1'; }
  catch { return false; }
}

export function PublicSupportWidget() {
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState(hasDismissedWelcome);
  const [welcome, setWelcome] = useState(false);
  const [screen, setScreen] = useState<'choices'|'chat'|'handoff'>('choices');
  const [initialized, setInitialized] = useState(false);
  const [conversationId, setConversationId] = useState('');
  const [name, setName] = useState('');
  const [reason, setReason] = useState('');
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const widgetRef = useRef<HTMLDivElement>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const sessionStarted = useRef(false);
  const openRef = useRef(open);
  const dismissedRef = useRef(dismissed);
  openRef.current = open;
  dismissedRef.current = dismissed;
  const session = useCreateWebsiteSupportSession();
  const start = useCreateWebsiteSupportConversation();
  const send = useCreateWebsiteSupportMessage();
  const handoff = useHandoffWebsiteSupportConversation();
  const availability = useGetWebsiteSupportAvailability({ query: { queryKey: getGetWebsiteSupportAvailabilityQueryKey(), refetchInterval: open ? 15000 : false } });
  const state = useGetWebsiteSupportConversation({
    query: { queryKey: getGetWebsiteSupportConversationQueryKey(), enabled: open && initialized, refetchInterval: open ? 4000 : false },
  });
  const detail = useGetWebsiteSupportConversationById(conversationId, {
    query: { enabled: open && !!conversationId, queryKey: getGetWebsiteSupportConversationByIdQueryKey(conversationId), refetchInterval: open ? 4000 : false },
  });
  const conversation = detail.data?.conversation ?? state.data?.conversation;
  const messages = detail.data?.messages ?? state.data?.messages ?? [];

  useEffect(() => {
    if (state.data?.conversation?.conversationId) {
      setConversationId(state.data.conversation.conversationId);
      setScreen('chat');
    }
  }, [state.data?.conversation?.conversationId]);
  useEffect(() => {
    if (open && !initialized && !sessionStarted.current && !session.isPending) {
      sessionStarted.current = true;
      session.mutate(undefined, {
        onSuccess: (result) => {
          setInitialized(true);
          if (result.conversation) {
            setConversationId(result.conversation.conversationId);
            setScreen('chat');
          }
        },
        onError: (failure) => { sessionStarted.current = false; setError(friendlyError(failure)); },
      });
    }
  }, [open, initialized]);
  useEffect(() => {
    const timer = window.setTimeout(() => { if (!dismissedRef.current && !openRef.current) setWelcome(true); }, 1800);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages.length, screen]);
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); setWelcome(false); }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);
  const dismissWelcome = () => {
    setDismissed(true);
    setWelcome(false);
    try { window.sessionStorage.setItem(WELCOME_DISMISSED_KEY, '1'); } catch {}
  };
  const openWidget = () => { setOpen(true); setWelcome(false); setError(''); };
  const createConversation = (mode: 'assistant'|'human', initialMessage?: string, visitorName?: string) => {
    setError('');
    start.mutate({ data: { mode, requestId: newRequestId(), ...(visitorName ? { name: visitorName } : {}), ...(initialMessage ? { initialMessage } : {}) } }, {
      onSuccess: (created) => {
        setConversationId(created.conversation.conversationId);
        if (mode === 'human' && visitorName && initialMessage) {
          setScreen('chat');
          setReason('');
        } else setScreen(mode === 'assistant' ? 'chat' : 'handoff');
      },
      onError: (failure) => setError(friendlyError(failure)),
    });
  };
  const submitMessage = (event: FormEvent) => {
    event.preventDefault();
    const clean = text.trim();
    if (!clean || !conversation?.conversationId || send.isPending) return;
    setText('');
    send.mutate({ conversationId: conversation.conversationId, data: { text: clean, requestId: newRequestId() } }, {
      onError: (failure) => { setText(clean); setError(friendlyError(failure)); },
    });
  };
  const submitHandoff = (event: FormEvent) => {
    event.preventDefault();
    const cleanName = name.trim(); const cleanReason = reason.trim();
    if (!cleanName || cleanReason.length < 3) return;
    if (!conversationId) {
      createConversation('human', cleanReason, cleanName);
      return;
    }
    handoff.mutate({ conversationId, data: { name: cleanName, reason: cleanReason, requestId: newRequestId() } }, {
      onSuccess: () => { setScreen('chat'); setReason(''); },
      onError: (failure) => setError(friendlyError(failure)),
    });
  };
  const beginHuman = () => setScreen('handoff');
  return <div className="ws-widget-root" ref={widgetRef}>
    {welcome && !open && <div className="ws-welcome" role="status">
      <button type="button" className="ws-welcome-close" onClick={dismissWelcome} aria-label="Dismiss welcome message"><X size={15}/></button>
      Need help? Chat with us.
    </div>}
    {open && <section id="ws-panel" className="ws-panel" role="dialog" aria-modal="false" aria-labelledby="ws-title">
      <header className="ws-panel-head">
        <div className="ws-brand-icon"><Headphones size={18}/></div>
        <div className="ws-panel-title"><strong id="ws-title">Smart Money Hub</strong><span>Website support</span></div>
        <button type="button" className="ws-icon-button" onClick={() => { setOpen(false); setWelcome(false); }} aria-label="Close support chat"><X size={17}/></button>
      </header>
      <div className="ws-panel-content" ref={feedRef} aria-live="polite">
        {!initialized && session.isPending && <div className="ws-loading"><i/><i/><i/> Connecting securely</div>}
        {state.isError && <div className="ws-error" role="alert">{friendlyError(state.error)} <button type="button" onClick={() => void state.refetch()}>Retry</button></div>}
        {error && <div className="ws-error" role="alert">{error}{!initialized && <button type="button" onClick={() => { sessionStarted.current = false; setOpen(false); window.setTimeout(() => setOpen(true), 30); }}>Retry connection</button>}</div>}
        {screen === 'choices' && <>
          <div className="ws-greeting"><span className="ws-message-label"><Bot size={12}/> Support assistant</span>Hello! Welcome to Smart Money Hub. How can we help you today?</div>
          <p className="ws-privacy">AI messages may be processed by Google Gemini. This assistant offers general site navigation and trading education only, not live market advice or promises of results.</p>
          {availability.isLoading && <p className="ws-availability"><Clock3 size={13}/> Checking support availability. Your request will remain pending until an authorized agent accepts.</p>}
          {availability.isError && <p className="ws-availability"><Clock3 size={13}/> Support availability cannot be confirmed right now. A request may take time; keep this browser session open.</p>}
          {availability.data?.humanAvailable && <p className="ws-availability"><Clock3 size={13}/> Human support availability has been confirmed. A conversation remains pending until an authorized agent accepts.</p>}
          <button type="button" className="ws-choice" onClick={() => { if (conversationId) setScreen('chat'); else createConversation('assistant'); }} disabled={start.isPending}><Bot size={16}/> Chat with AI Assistant</button>
          <button type="button" className="ws-choice ws-choice-human" onClick={beginHuman}><Headphones size={16}/> Talk to a Female Support Agent</button>
          {availability.data && !availability.data.humanAvailable && <p className="ws-availability"><Clock3 size={13}/> No eligible agent is available right now. A response may take time; keep this browser session open.</p>}
        </>}
        {screen === 'chat' && <>
          <button type="button" className="ws-back" onClick={() => setScreen('choices')}><ChevronLeft size={14}/> Support options</button>
          <p className="ws-privacy">AI messages are labeled and may be processed by Google Gemini. This is general education, not live market advice.</p>
          {!messages.length && <div className="ws-greeting"><span className="ws-message-label"><Bot size={12}/> AI Assistant</span>Ask about navigating the website or general trading education. I cannot check prices, live market conditions, specific course availability, or predict results.</div>}
          {messages.map((item) => <article key={item.messageId} className={`ws-bubble ws-${item.senderType}`}>
            {item.senderType !== 'visitor' && <span className="ws-message-label">{item.senderType === 'assistant' ? <><Bot size={12}/> AI Assistant</> : item.senderType === 'staff' ? <><Headphones size={12}/> Support agent</> : 'Update'}</span>}
            <p>{item.text}</p>
          </article>)}
          {conversation?.mode === 'human' && conversation.status !== 'closed' && <div className="ws-queue-note"><Clock3 size={14}/><span>{conversation.agentJoined ? 'A support agent has joined the conversation.' : 'Your request is pending until an authorized agent accepts. A response may take time; keep this browser session available.'}</span></div>}
          {conversation?.status === 'closed' && <div className="ws-queue-note">This conversation is closed.</div>}
          <button type="button" className="ws-escalate" onClick={() => setScreen('handoff')}><CircleHelp size={14}/> Not sure? Request a support agent</button>
        </>}
        {screen === 'handoff' && <form className="ws-handoff-form" onSubmit={submitHandoff}>
          <button type="button" className="ws-back" onClick={() => setScreen(conversationId ? 'chat' : 'choices')}><ChevronLeft size={14}/> Back</button>
          <h3>Request a support agent</h3>
          <p>Tell us who you are and what you need help with. Your request stays pending until an authorized agent accepts.</p>
          <label htmlFor="ws-name">Your name</label><input id="ws-name" required maxLength={80} value={name} onChange={(event) => setName(event.target.value)}/>
          <label htmlFor="ws-reason">How can we help?</label><textarea id="ws-reason" required minLength={3} maxLength={2000} rows={4} value={reason} onChange={(event) => setReason(event.target.value)}/>
          {!availability.data?.humanAvailable && <div className="ws-availability"><Clock3 size={13}/> No eligible agent is available right now. A response may take time; keep this browser session open.</div>}
          <button className="ws-submit" type="submit" disabled={start.isPending || handoff.isPending}>{start.isPending || handoff.isPending ? 'Sending request…' : 'Send handoff request'} <Send size={14}/></button>
        </form>}
      </div>
      {screen === 'chat' && conversation?.status !== 'closed' && <form className="ws-composer" onSubmit={submitMessage}>
        <input aria-label="Message support" value={text} onChange={(event) => setText(event.target.value)} maxLength={2000} placeholder="Write a message…" />
        <button type="submit" disabled={!text.trim() || send.isPending} aria-label="Send message"><Send size={16}/></button>
      </form>}
      <footer className="ws-panel-foot"><ShieldCheck size={12}/> Education first · Not financial advice</footer>
    </section>}
    <button type="button" className={`ws-launcher ${open ? 'is-open' : ''}`} onClick={open ? () => setOpen(false) : openWidget} aria-label={open ? 'Close support chat' : 'Open website support chat'} aria-expanded={open} aria-controls="ws-panel">
      {open ? <X size={20}/> : <MessageCircle size={21}/>}
    </button>
  </div>;
}

export function WebsiteChats({ session }: { session: PortalSession }) {
  const client = useQueryClient();
  const [selectedId, setSelectedId] = useState('');
  const [filter, setFilter] = useState<'all'|'queued'|'assigned'|'in_progress'|'closed'>('all');
  const [reply, setReply] = useState('');
  const [failure, setFailure] = useState('');
  const params = { status: filter, limit: 100 } as const;
  const list = useListPortalWebsiteSupportConversations(params, { query: { queryKey: getListPortalWebsiteSupportConversationsQueryKey(params), refetchInterval: 5000, refetchIntervalInBackground: false } });
  const detail = useGetPortalWebsiteSupportConversation(selectedId, { query: { enabled: !!selectedId, queryKey: getGetPortalWebsiteSupportConversationQueryKey(selectedId), refetchInterval: 5000, refetchIntervalInBackground: false } });
  const settings = useGetPortalWebsiteSupportSettings({ query: { queryKey: getGetPortalWebsiteSupportSettingsQueryKey() } });
  const accept = useAcceptPortalWebsiteSupportConversation();
  const respond = useReplyPortalWebsiteSupportConversation();
  const assign = useAssignPortalWebsiteSupportConversation();
  const close = useClosePortalWebsiteSupportConversation();
  const saveTeam = useUpdatePortalWebsiteSupportSettings();
  const eligibility = useUpdatePortalWebsiteSupportEligibility();
  const availability = useUpdatePortalWebsiteSupportAvailability();
  const selected = detail.data?.conversation;
  const reload = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: getListPortalWebsiteSupportConversationsQueryKey(params) }),
      selectedId ? client.invalidateQueries({ queryKey: getGetPortalWebsiteSupportConversationQueryKey(selectedId) }) : Promise.resolve(),
      client.invalidateQueries({ queryKey: getGetPortalWebsiteSupportSettingsQueryKey() }),
    ]);
  };
  const reportError = (error: unknown) => setFailure(friendlyError(error));
  const run = (action: () => void) => { setFailure(''); action(); };
  const sendReply = (event: FormEvent) => {
    event.preventDefault();
    if (!reply.trim() || !selectedId) return;
    respond.mutate({ conversationId: selectedId, data: { text: reply.trim(), requestId: newRequestId() } }, { onSuccess: () => { setReply(''); void reload(); }, onError: reportError });
  };
  const acceptSelected = () => selectedId && accept.mutate({ conversationId: selectedId }, { onSuccess: () => void reload(), onError: reportError });
  return <main className="page ws-staff-page">
    <div className="page-heading"><div><div className="eyebrow">PUBLIC WEBSITE / INBOX</div><h1>Website Chats</h1><p className="subheading">Live conversations from the public support widget. Queue refreshes every five seconds.</p></div>
      {session.role === 'agent' && <button type="button" className={`btn ${settings.data?.self.available ? 'btn-primary' : 'btn-outline'}`} disabled={!settings.data?.self.eligible || availability.isPending} title={!settings.data?.self.eligible ? 'An owner must confirm your opt-in before you can be available.' : undefined} onClick={() => availability.mutate({ data: { available: !settings.data?.self.available } }, { onSuccess: () => void reload(), onError: reportError })} data-testid="toggle-website-availability">{availability.isPending ? 'Saving…' : !settings.data?.self.eligible ? 'Not opted in' : settings.data.self.available ? 'Available · turn off' : 'Set available'}</button>}
    </div>
    {failure && <div className="notice notice-error" role="alert">{failure}</div>}
    <div className="ws-staff-grid">
      <section className="section-panel ws-chat-list">
        <div className="section-head"><div><h2 className="section-title">Conversation queue</h2><p className="section-note">{list.data ? `${list.data.total} conversations` : 'Authorized conversations only'}</p></div><select className="filter-select" aria-label="Filter website chats" value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}><option value="all">All</option><option value="queued">Pending</option><option value="assigned">Assigned</option><option value="in_progress">In progress</option><option value="closed">Closed</option></select></div>
        {list.isLoading ? <div className="loading-list" aria-label="Loading website chats">{[0,1,2,3].map((i)=><div className="loading-row" key={i}><div className="skeleton"/><div className="skeleton"/></div>)}</div> : list.isError ? <div className="empty-state"><h3>Chats could not be loaded</h3><button className="btn btn-outline" onClick={() => void list.refetch()}>Retry</button></div> : list.data?.conversations.length ? <div className="ws-conversation-list">{list.data.conversations.map((item) => <button type="button" key={item.conversationId} className={`ws-conversation-row ${selectedId === item.conversationId ? 'is-selected' : ''}`} onClick={() => setSelectedId(item.conversationId)}>
          <span className="ws-conversation-avatar">{(item.visitorName || 'Visitor').slice(0,1).toUpperCase()}</span><span className="ws-row-copy"><strong>{item.visitorName || 'Website visitor'}</strong><small>{item.mode === 'assistant' ? 'AI conversation' : 'Human support'} · {new Date(item.lastMessageAt).toLocaleString()}</small><small className="ws-row-id">{item.conversationId}</small></span><span className={`ws-status ws-status-${item.status}`}>{item.status.replaceAll('_',' ')}</span>
        </button>)}</div> : <div className="empty-state"><div className="empty-mark"><MessageCircle size={20}/></div><h3>No chats in this view</h3><p>New public conversations will appear here when visitors contact support.</p></div>}
      </section>
      <section className="section-panel ws-chat-detail">
        {!selectedId ? <div className="empty-state"><div className="empty-mark"><MessageCircle size={20}/></div><h3>Select a conversation</h3><p>Choose a chat to review the live transcript and take an authorized action.</p></div>
          : detail.isLoading ? <div className="loading-list" aria-label="Loading conversation"><div className="loading-row"><div className="skeleton"/></div><div className="loading-row"><div className="skeleton"/></div></div>
          : detail.isError ? <div className="empty-state"><h3>Conversation unavailable</h3><p>{friendlyError(detail.error)}</p><button className="btn btn-outline" onClick={() => void detail.refetch()}>Retry</button></div>
          : selected && <><div className="section-head ws-detail-head"><div><h2 className="section-title">{selected.visitorName || 'Website visitor'}</h2><p className="section-note">{selected.mode === 'assistant' ? 'AI assistant' : 'Human support'} · {selected.status.replaceAll('_',' ')}</p></div>
            {selected.status !== 'closed' && <button type="button" className="btn btn-outline" onClick={() => close.mutate({ conversationId: selectedId }, { onSuccess: () => void reload(), onError: reportError })} disabled={close.isPending}>{close.isPending ? 'Closing…' : 'Close chat'}</button>}
          </div>
          <div className="ws-transcript" aria-live="polite">{detail.data?.messages.map((message) => <article key={message.messageId} className={`ws-staff-message ws-${message.senderType}`}><span>{message.senderType === 'assistant' ? 'AI Assistant' : message.senderType === 'staff' ? 'Support agent' : message.senderType === 'visitor' ? selected.visitorName || 'Visitor' : 'System'}</span><p>{message.text}</p><time>{new Date(message.created).toLocaleString()}</time></article>)}</div>
          <div className="ws-staff-actions">
            {session.role === 'agent' && selected.status === 'queued' && <button type="button" className="btn btn-primary" onClick={() => run(acceptSelected)} disabled={accept.isPending}>{accept.isPending ? 'Accepting…' : 'Accept conversation'}</button>}
            {(session.role === 'owner' || session.role === 'manager') && settings.data?.canAssign && selected.status !== 'closed' && <label className="ws-assign-label">Assign / transfer to<select className="filter-select" value={selected.assignedStaffId ?? ''} onChange={(event) => assign.mutate({ conversationId: selectedId, data: { assignedStaffId: event.target.value || null } }, { onSuccess: () => void reload(), onError: reportError })}><option value="">Unassigned</option>{settings.data.agents.filter((agent) => agent.eligible && agent.available).map((agent) => <option key={agent.staffId} value={agent.staffId}>{agent.displayName}</option>)}</select></label>}
          </div>
          {session.role === 'agent' && selected.assignedStaffId === session.staffId && selected.status !== 'closed' && <form className="ws-reply-form" onSubmit={sendReply}><textarea aria-label="Reply to website visitor" required maxLength={2000} rows={3} value={reply} onChange={(event) => setReply(event.target.value)} placeholder="Write a reply…"/><button type="submit" className="btn btn-primary" disabled={!reply.trim() || respond.isPending}>{respond.isPending ? 'Sending…' : 'Send reply'} <Send size={14}/></button></form>}
          </>}
      </section>
    </div>
    <section className="section-panel ws-settings">
      <div className="section-head"><div><h2 className="section-title">Support routing & availability</h2><p className="section-note">Settings and eligibility are controlled by server permissions.</p></div><ShieldCheck size={17}/></div>
      {settings.isLoading ? <div className="loading-row"><div className="skeleton"/></div> : settings.isError ? <div className="notice notice-error" role="alert">{friendlyError(settings.error)} <button className="btn btn-quiet" onClick={() => void settings.refetch()}>Retry</button></div> : settings.data && <>
        <div className="ws-settings-controls">
          <label className="ws-assign-label">Support team<select className="filter-select" value={settings.data.supportTeamId ?? ''} disabled={!settings.data.canManage || saveTeam.isPending} onChange={(event) => saveTeam.mutate({ data: { supportTeamId: event.target.value || null } }, { onSuccess: () => void reload(), onError: reportError })}><option value="">No team selected</option>{settings.data.teams.map((team) => <option key={team.teamId} value={team.teamId}>{team.name}</option>)}</select></label>
          {!settings.data.canManage && <p className="ws-settings-note">Only an owner can change the support team and agent eligibility.</p>}
        </div>
        {(session.role === 'owner' || session.role === 'manager') && settings.data.canManage && <div className="ws-agent-list">{settings.data.agents.map((agent) => <AgentEligibility key={agent.staffId} agent={agent} onSave={(eligible, consentConfirmed) => eligibility.mutate({ staffId: agent.staffId, data: { eligible, consentConfirmed } }, { onSuccess: () => void reload(), onError: reportError })} busy={eligibility.isPending} owner={session.role === 'owner'}/>)}</div>}
        {session.role === 'agent' && <p className="ws-settings-note"><Check size={14}/> Your availability is controlled above. Eligibility must be enabled by an owner.</p>}
      </>}
    </section>
  </main>;
}

function AgentEligibility({ agent, onSave, busy, owner }: { agent: { staffId: string; displayName: string; eligible: boolean; available: boolean }; onSave: (eligible: boolean, consentConfirmed: boolean) => void; busy: boolean; owner: boolean }) {
  const [confirm, setConfirm] = useState(false);
  return <div className="ws-agent-row"><div><strong>{agent.displayName}</strong><span>{agent.available ? 'Available' : 'Unavailable'} · {agent.eligible ? 'Eligible' : 'Not eligible'}</span></div>{owner && <div className="ws-agent-controls"><label><input type="checkbox" checked={agent.eligible} disabled={busy} onChange={(event) => {
    if (event.target.checked) setConfirm(true);
    else onSave(false, false);
  }}/> Eligible</label>{confirm && <div className="ws-optin-confirm"><p>Confirm this person self-identifies as a female support agent and has opted in to public chats. Do not infer eligibility from their name.</p><button type="button" className="btn btn-primary" disabled={busy} onClick={() => { onSave(true, true); setConfirm(false); }}>Confirm opt-in</button><button type="button" className="btn btn-quiet" onClick={() => setConfirm(false)}>Cancel</button></div>}</div>}</div>;
}
