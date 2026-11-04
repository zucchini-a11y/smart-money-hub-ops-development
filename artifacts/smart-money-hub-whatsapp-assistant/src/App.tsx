import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { Link, Route, Switch, useLocation, Router as WouterRouter } from 'wouter';
import {
  Activity, ArrowLeft, ArrowUpRight, BookOpen, Check, CheckCheck, CircleHelp,
  Clock3, ExternalLink, FileText, Filter, Headphones, KeyRound, LayoutDashboard,
  LockKeyhole, LogOut, MessageCircle, MessageSquareText, MoreHorizontal, Pause, Play,
  RefreshCw, Search, Send, Settings2, ShieldCheck, ShieldOff, Users, Wifi,
  X, Zap,
} from 'lucide-react';
import {
  getGetWhatsAppAuthStatusQueryKey, getGetWhatsAppDashboardQueryKey, getGetWhatsAppActivityQueryKey,
  getListWhatsAppConversationsQueryKey, getGetWhatsAppConversationQueryKey,
  getListWhatsAppEducationModulesQueryKey, getGetWhatsAppSettingsQueryKey, getGetWhatsAppHealthQueryKey, setBaseUrl,
  useGetWhatsAppAuthStatus, useLoginWhatsAppAdmin, useLogoutWhatsAppAdmin,
  useGetWhatsAppDashboard, useGetWhatsAppActivity, useGetWhatsAppHealth, useListWhatsAppConversations,
  useGetWhatsAppConversation, useReplyToWhatsAppConversation, useListWhatsAppEducationModules,
  useUpdateWhatsAppEducationModule, useGetWhatsAppSettings, useUpdateWhatsAppSettings,
} from '@workspace/api-client-react';
import type { WhatsAppActivity, WhatsAppConversation, WhatsAppMessage } from '@workspace/api-client-react';

const base = import.meta.env.BASE_URL.replace(/\/$/, '');
setBaseUrl(base);
const client = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 12_000 } } });
const req = { credentials: 'include' as const };
const pathFor = (p: string) => p;

function IconButton({ children, onClick, label, className = '', disabled = false }: { children: ReactNode; onClick?: () => void; label: string; className?: string; disabled?: boolean }) {
  return <button type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled} data-testid={`button-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`} className={`icon-button ${className}`}>{children}</button>;
}

function Button({ children, onClick, type = 'button', variant = 'primary', disabled = false, className = '' }: { children: ReactNode; onClick?: () => void; type?: 'button' | 'submit'; variant?: 'primary' | 'quiet' | 'danger' | 'outline'; disabled?: boolean; className?: string }) {
  return <button type={type} onClick={onClick} disabled={disabled} data-testid="button-action" className={`button button-${variant} ${className}`}>{children}</button>;
}

function Notice({ tone = 'info', children }: { tone?: 'info' | 'success' | 'warning' | 'error'; children: ReactNode }) {
  return <div className={`notice notice-${tone}`} role="status">{children}</div>;
}

function Skeleton({ className = '' }: { className?: string }) { return <div className={`skeleton ${className}`} aria-hidden="true" />; }

function QueryState({ loading, error, retry, children }: { loading: boolean; error: unknown; retry: () => void; children: ReactNode }) {
  if (loading) return <div className="stack-gap"><Skeleton className="h-28" /><Skeleton className="h-52" /></div>;
  if (error) return <div className="empty-state"><div className="empty-mark"><Wifi size={20} /></div><h2>We couldn’t reach the workspace</h2><p>{error instanceof Error ? error.message : 'The service did not respond. Your session and content are unchanged.'}</p><Button variant="outline" onClick={retry}><RefreshCw size={15} /> Try again</Button></div>;
  return <>{children}</>;
}

const navItems = [
  { href: '/', label: 'Overview', icon: LayoutDashboard },
  { href: '/conversations', label: 'Conversations', icon: MessageCircle },
  { href: '/education', label: 'Education library', icon: BookOpen },
  { href: '/settings', label: 'Assistant settings', icon: Settings2 },
];

function Shell({ children, title, eyebrow }: { children: ReactNode; title: string; eyebrow: string }) {
  const [location, setLocation] = useLocation();
  const logout = useLogoutWhatsAppAdmin({ request: req });
  const qc = useQueryClient();
  const [mobileOpen, setMobileOpen] = useState(false);
  const logoutNow = () => logout.mutate(undefined, { onSuccess: () => { qc.setQueryData(getGetWhatsAppAuthStatusQueryKey(), { authenticated: false, passwordConfigured: true }); setLocation('/login'); } });
  return <div className="app-frame">
    <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>
      <div className="brand-lockup">
        <div className="brand-symbol"><span>SM</span><i /></div>
        <div><div className="brand-name">Smart Money Hub</div><div className="brand-product">WHATSAPP ASSISTANT</div></div>
      </div>
      <div className="workspace-label">WORKSPACE <span>PRIVATE</span></div>
      <nav className="side-nav" aria-label="Main navigation">
        {navItems.map(({ href, label, icon: Icon }) => <Link key={href} href={pathFor(href)} onClick={() => setMobileOpen(false)} className={`side-link ${location === href || (href !== '/' && location.startsWith(href)) ? 'side-link-active' : ''}`} data-testid={`link-nav-${label.toLowerCase().replaceAll(' ', '-')}`}><Icon size={17} strokeWidth={1.8} /><span>{label}</span>{href === '/conversations' && <span className="nav-dot" />}</Link>)}
      </nav>
      <div className="sidebar-spacer" />
      <div className="side-operator">
        <div className="operator-avatar">A</div>
        <div className="operator-copy"><strong>Workspace owner</strong><span>Administrator</span></div>
        <button type="button" className="logout-button" onClick={logoutNow} disabled={logout.isPending} aria-label="Sign out" data-testid="button-sign-out"><LogOut size={16} /></button>
      </div>
      <div className="sidebar-foot"><ShieldCheck size={14} /> Private admin workspace</div>
    </aside>
    {mobileOpen && <button aria-label="Close navigation" className="mobile-scrim" onClick={() => setMobileOpen(false)} />}
    <main className="main-column">
      <header className="topbar">
        <button className="mobile-menu" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><MoreHorizontal size={21} /></button>
        <div className="crumb"><span>WhatsApp assistant</span><span className="crumb-slash">/</span><strong>{eyebrow}</strong></div>
        <div className="topbar-right"><span className="live-indicator"><i /> Test environment</span><span className="topbar-date">{new Intl.DateTimeFormat('en', { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date())}</span></div>
      </header>
      <div className="page-wrap page-enter">
        <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1></div><div className="heading-tools"><span className="secure-tag"><LockKeyhole size={13} /> Owner access</span></div></div>
        {children}
      </div>
    </main>
  </div>;
}

function StatusPill({ paused, testMode = true }: { paused: boolean; testMode?: boolean }) {
  return <span className={`status-pill ${paused ? 'status-paused' : 'status-active'}`}><i />{paused ? 'Replies paused' : testMode ? 'Test replies active' : 'Replies active'}</span>;
}

function Metric({ label, value, note, icon: Icon, accent = 'gold' }: { label: string; value: number | string; note: string; icon: typeof MessageCircle; accent?: string }) {
  return <div className="metric-card"><div className="metric-top"><span>{label}</span><span className={`metric-icon metric-${accent}`}><Icon size={17} /></span></div><div className="metric-value">{value ?? '—'}</div><div className="metric-note">{note}</div></div>;
}

function ActivityRow({ item }: { item: WhatsAppActivity }) {
  const time = item.createdAt ? new Date(item.createdAt) : null;
  return <div className="activity-row"><div className="activity-mark"><Activity size={14} /></div><div className="activity-copy"><strong>{item.summary}</strong><span>{item.kind}</span></div><time>{time && !Number.isNaN(time.valueOf()) ? new Intl.DateTimeFormat('en', { hour: 'numeric', minute: '2-digit' }).format(time) : '—'}</time></div>;
}

function Dashboard() {
  const q = useGetWhatsAppDashboard({ query: { queryKey: getGetWhatsAppDashboardQueryKey() }, request: req });
  const activity = useGetWhatsAppActivity({ query: { queryKey: getGetWhatsAppActivityQueryKey() }, request: req });
  const d = q.data;
  const recent = activity.data ?? d?.recentActivity ?? [];
  return <Shell title="Good morning, owner." eyebrow="Overview">
    <QueryState loading={q.isLoading} error={q.error} retry={() => q.refetch()}>
      {d && <div className="dashboard-body">
        <div className={`hero-status ${d.paused ? 'hero-paused' : ''}`}>
          <div className="hero-orbit"><div className="orbit-line" /><MessageSquareText size={25} /></div>
          <div className="hero-copy"><div className="hero-kicker"><span className="signal-dot" /> ASSISTANT STATUS</div><h2>{d.paused ? 'Your assistant is paused.' : 'Your assistant is ready.'}</h2><p>{d.paused ? 'AI replies are on hold. Incoming conversations remain visible here.' : 'Replies are limited to approved test recipients. Every conversation stays reviewable.'}</p></div>
          <div className="hero-right"><StatusPill paused={d.paused} testMode={d.testMode} /><Link href={pathFor('/settings')} className="hero-settings">Manage settings <ArrowUpRight size={14} /></Link></div>
          <div className="hero-index">01 <span>/ 04</span></div>
        </div>
        {!d.testMode && <Notice tone="warning"><ShieldOff size={16} /> Test mode is not enabled. Review the connection and recipient settings before replying.</Notice>}
        <div className="metrics-grid">
          <Metric label="Conversations today" value={d.conversationsToday} note="Unique test-number threads" icon={Users} accent="teal" />
          <Metric label="Messages today" value={d.messagesToday} note="Inbound and assistant replies" icon={MessageCircle} accent="blue" />
          <Metric label="Open enquiries" value={d.openEnquiries} note="Conversations flagged for follow-up" icon={Headphones} accent="coral" />
          <Metric label="Test recipients" value={d.connection.allowedTestRecipients} note="Numbers currently allowlisted" icon={ShieldCheck} accent="gold" />
        </div>
        <div className="dashboard-lower">
          <section className="panel activity-panel"><div className="panel-header"><div><div className="panel-kicker">THE PAPER TRAIL</div><h2>Recent activity</h2></div><Link className="text-link" href={pathFor('/conversations')}>View conversations <ArrowUpRight size={14} /></Link></div>
            {activity.isLoading ? <div className="activity-skeleton"><Skeleton /><Skeleton /><Skeleton /></div> : activity.error ? <Notice tone="warning">Activity history is temporarily unavailable. <button className="inline-action" onClick={() => activity.refetch()}>Retry</button></Notice> : recent.length ? <div>{recent.slice(0, 6).map((item) => <ActivityRow key={item.id} item={item} />)}</div> : <div className="small-empty"><div className="empty-mark"><Activity size={17} /></div><strong>No activity yet</strong><span>System events will appear here as the assistant is used.</span></div>}
          </section>
          <section className="panel readiness-panel"><div className="panel-header"><div><div className="panel-kicker">CONNECTION CHECK</div><h2>Ready when you are</h2></div><span className="check-icon"><Check size={15} /></span></div><p className="readiness-description">A quick read on the assistant’s private test setup.</p>
            <div className="readiness-list"><Readiness label="WhatsApp credentials" ready={d.connection.credentialsConfigured} /><Readiness label="Webhook endpoint" ready={d.connection.webhookConfigured} /><Readiness label="Gemini configured" ready={d.connection.geminiConfigured} /></div>
            <Link href={pathFor('/settings')} className="readiness-link">Open connection settings <ArrowUpRight size={14} /></Link>
          </section>
        </div>
      </div>}
    </QueryState>
  </Shell>;
}

function Readiness({ label, ready }: { label: string; ready: boolean }) {
  return <div className="readiness-item"><span className={`readiness-state ${ready ? 'ready' : 'not-ready'}`}>{ready ? <Check size={12} /> : <X size={12} />}</span><span>{label}</span><strong>{ready ? 'Configured' : 'Missing'}</strong></div>;
}

function ConversationList() {
  const [search, setSearch] = useState('');
  const [enquiries, setEnquiries] = useState(false);
  const params = useMemo(() => ({ ...(search.trim() ? { search: search.trim() } : {}), ...(enquiries ? { enquiriesOnly: true } : {}) }), [search, enquiries]);
  const q = useListWhatsAppConversations(params, { query: { queryKey: getListWhatsAppConversationsQueryKey(params) }, request: req });
  const conversations = q.data ?? [];
  return <Shell title="Conversations" eyebrow="Inbox">
    <div className="inbox-toolbar"><label className="search-field"><Search size={17} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name, number, or message" aria-label="Search conversations" data-testid="input-search-conversations" /><kbd>⌘ K</kbd></label><button className={`filter-button ${enquiries ? 'filter-active' : ''}`} onClick={() => setEnquiries(!enquiries)} data-testid="button-enquiry-filter"><Filter size={15} /> Enquiries <span className="filter-check">{enquiries ? <Check size={12} /> : null}</span></button><IconButton label="Refresh conversations" onClick={() => q.refetch()}><RefreshCw size={15} /></IconButton></div>
    <div className="inbox-caption"><span>{enquiries ? 'ENQUIRIES ONLY' : 'TEST-NUMBER CONVERSATIONS'}</span><span>{q.isLoading ? 'Loading…' : `${conversations.length} ${conversations.length === 1 ? 'thread' : 'threads'}`}</span></div>
    <QueryState loading={q.isLoading} error={q.error} retry={() => q.refetch()}>
      {!conversations.length ? <div className="empty-state inbox-empty"><div className="empty-mark"><MessageCircle size={22} /></div><h2>{search || enquiries ? 'No matching conversations' : 'A clear inbox—for now'}</h2><p>{search || enquiries ? 'Try a different search or remove the enquiry filter.' : 'When a test recipient messages the assistant, the conversation will appear here. No customer messaging is enabled.'}</p>{(search || enquiries) && <Button variant="outline" onClick={() => { setSearch(''); setEnquiries(false); }}>Clear filters</Button>}</div> :
        <div className="conversation-list">{conversations.map((c) => <ConversationListRow key={c.id} c={c} />)}</div>}
    </QueryState>
    <div className="privacy-foot"><ShieldCheck size={15} /><span>This inbox only shows conversations from allowlisted test recipients.</span></div>
  </Shell>;
}

function ConversationListRow({ c }: { c: WhatsAppConversation }) {
  const display = c.displayName || c.waId;
  const initials = display.replace(/\D/g, '').length ? display.replace(/\D/g, '').slice(-2) : display.slice(0, 2).toUpperCase();
  return <Link href={pathFor(`/conversations/${c.id}`)} className="conversation-row" data-testid={`link-conversation-${c.id}`}>
    <div className={`contact-avatar ${c.isEnquiry ? 'contact-enquiry' : ''}`}>{initials}</div>
    <div className="conversation-info"><div className="conversation-title"><strong>{display}</strong>{c.isEnquiry && <span className="enquiry-tag">ENQUIRY</span>}</div><p>{c.lastMessagePreview || 'No message preview available'}</p></div>
    <div className="conversation-meta"><time>{formatTime(c.lastMessageAt)}</time><span className={`window-label ${c.replyWindowOpen ? 'window-open' : 'window-closed'}`}><Clock3 size={12} />{c.replyWindowOpen ? 'Reply window open' : 'Window closed'}</span></div>
    {c.unreadCount > 0 && <span className="unread-count">{c.unreadCount}</span>}<ArrowUpRight className="row-arrow" size={15} />
  </Link>;
}

function formatTime(date: string | null | undefined) {
  if (!date) return 'No recent activity';
  const d = new Date(date);
  if (Number.isNaN(d.valueOf())) return '—';
  const today = new Date();
  return d.toDateString() === today.toDateString() ? new Intl.DateTimeFormat('en', { hour: 'numeric', minute: '2-digit' }).format(d) : new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric' }).format(d);
}

function ConversationDetail({ id }: { id: string }) {
  const conversationId = Number(id);
  const queryClient = useQueryClient();
  const q = useGetWhatsAppConversation(conversationId, { query: { queryKey: getGetWhatsAppConversationQueryKey(conversationId), enabled: Number.isFinite(conversationId) }, request: req });
  const dashboard = useGetWhatsAppDashboard({ query: { queryKey: getGetWhatsAppDashboardQueryKey() }, request: req });
  const reply = useReplyToWhatsAppConversation({ request: req });
  const [text, setText] = useState('');
  const [sent, setSent] = useState(false);
  const detail = q.data;
  const c = detail?.conversation;
  const valid = !!c && !!dashboard.data?.testMode && !!dashboard.data.connection.credentialsConfigured && c.testRecipientAllowed && c.replyWindowOpen;
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid || !text.trim() || text.length > 4096) return;
    reply.mutate({ conversationId, data: { text: text.trim() } }, { onSuccess: (message) => {
      setText(''); setSent(true);
      queryClient.setQueryData(getGetWhatsAppConversationQueryKey(conversationId), (old: typeof detail) => old ? { ...old, messages: [...old.messages, message] } : old);
      queryClient.invalidateQueries({ queryKey: getGetWhatsAppDashboardQueryKey() });
      window.setTimeout(() => setSent(false), 3500);
    } });
  }
  return <Shell title={c?.displayName || 'Conversation'} eyebrow="Inbox / Conversation">
    <div className="detail-top"><Link href={pathFor('/conversations')} className="back-link"><ArrowLeft size={15} /> All conversations</Link><div className="detail-id">{c?.waId}</div></div>
    <QueryState loading={q.isLoading || dashboard.isLoading} error={q.error || dashboard.error} retry={() => { q.refetch(); dashboard.refetch(); }}>
      {detail && c && <div className="detail-layout">
        <section className="panel thread-panel">
          <div className="thread-header"><div className="contact-avatar large">{(c.displayName || c.waId).slice(0, 2).toUpperCase()}</div><div><h2>{c.displayName || 'Test recipient'}</h2><span>{c.waId}</span></div><div className="thread-header-tags">{c.isEnquiry && <span className="enquiry-tag">ENQUIRY</span>}<span className={`window-label ${c.replyWindowOpen ? 'window-open' : 'window-closed'}`}><Clock3 size={12} />{c.replyWindowOpen ? '24h window open' : '24h window closed'}</span></div></div>
          <div className="thread-notice"><ShieldCheck size={15} /><span>Private test conversation</span><span className="thread-notice-divider" /><span>{c.replyWindowOpen ? 'Customer-initiated reply window is open' : 'Reply window is closed'}</span></div>
          <div className="message-history">{detail.messages.length ? detail.messages.map((m) => <MessageBubble key={m.id} message={m} />) : <div className="thread-empty"><MessageSquareText size={22} /><strong>No messages to show</strong><span>Messages from this test conversation will appear here.</span></div>}</div>
          <form className="reply-box" onSubmit={submit}>
            {!dashboard.data?.testMode && <Notice tone="warning"><ShieldOff size={15} /> Manual replies are disabled because test mode is off.</Notice>}
            {c && !c.testRecipientAllowed && <Notice tone="warning"><ShieldOff size={15} /> This recipient is not on the configured test allowlist. Manual replies are disabled.</Notice>}
            {dashboard.data && !dashboard.data.connection.credentialsConfigured && <Notice tone="warning"><ShieldOff size={15} /> Meta test credentials are missing. Manual replies are disabled until they are configured.</Notice>}
            {dashboard.data?.paused && <Notice tone="info"><Pause size={15} /> Automated replies are paused. Manual replies still follow test-mode and 24-hour-window restrictions.</Notice>}
            {!c.replyWindowOpen && <Notice tone="warning"><Clock3 size={15} /> The 24-hour reply window has closed. WhatsApp replies are unavailable for this conversation.</Notice>}
            <label className="reply-label" htmlFor="reply-text">Manual reply <span>Test recipient only</span></label>
            <div className="reply-compose"><textarea id="reply-text" value={text} onChange={(e) => setText(e.target.value)} placeholder={valid ? 'Write a careful, helpful reply…' : 'Reply is unavailable for this conversation'} maxLength={4096} disabled={!valid || reply.isPending} data-testid="input-manual-reply" /><button type="submit" className="send-button" disabled={!valid || !text.trim() || reply.isPending} aria-label="Send reply" data-testid="button-send-reply">{reply.isPending ? <RefreshCw size={17} className="spin" /> : <Send size={17} />}</button></div>
            <div className="reply-foot">{reply.error && <span className="form-error">{reply.error instanceof Error ? reply.error.message : 'Reply could not be sent.'}</span>}{sent && <span className="form-success"><Check size={13} /> Reply sent to test recipient</span>}<span>{text.length}/4096</span></div>
            <p className="reply-disclaimer">Replies are sent only to this API-approved test recipient. No bulk or arbitrary-recipient messaging.</p>
          </form>
        </section>
        <aside className="panel detail-aside"><div className="panel-kicker">CONVERSATION DETAILS</div><div className="detail-fact"><span>Reply permission</span><strong className={c.replyWindowOpen ? 'fact-good' : 'fact-muted'}>{c.replyWindowOpen ? 'Within 24-hour window' : 'Window has closed'}</strong></div><div className="detail-fact"><span>Recipient scope</span><strong>Test allowlist</strong></div><div className="detail-fact"><span>Enquiry flag</span><strong>{c.isEnquiry ? 'Follow-up needed' : 'Not flagged'}</strong></div><div className="detail-fact"><span>Last message</span><strong>{formatTime(c.lastMessageAt)}</strong></div><div className="aside-safe"><LockKeyhole size={15} /><p>Manual replies follow WhatsApp’s customer-service window and stay in test mode.</p></div></aside>
      </div>}
    </QueryState>
  </Shell>;
}

function MessageBubble({ message }: { message: WhatsAppMessage }) {
  const outbound = message.direction === 'outbound';
  return <div className={`message-line ${outbound ? 'message-outbound' : ''}`}><div className="message-bubble"><p>{message.text}</p><div className="message-stamp"><time>{formatDateTime(message.createdAt)}</time>{outbound && <span>{message.status} <CheckCheck size={12} /></span>}</div></div></div>;
}

function formatDateTime(value: string) {
  const d = new Date(value);
  return Number.isNaN(d.valueOf()) ? '—' : new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(d);
}

function Education() {
  const q = useListWhatsAppEducationModules({ query: { queryKey: getListWhatsAppEducationModulesQueryKey() }, request: req });
  const qc = useQueryClient();
  const update = useUpdateWhatsAppEducationModule({ request: req });
  const [activeSlug, setActiveSlug] = useState('');
  const [form, setForm] = useState({ summary: '', content: '', published: false });
  const [saved, setSaved] = useState(false);
  const modules = q.data ?? [];
  const active = modules.find((m) => m.slug === activeSlug) ?? modules[0];
  useEffect(() => { if (active && active.slug !== activeSlug) setActiveSlug(active.slug); }, [active, activeSlug]);
  useEffect(() => { if (active) { setForm({ summary: active.summary, content: active.content, published: active.published }); setSaved(false); } }, [active?.slug, active?.updatedAt]);
  const dirty = !!active && (form.summary !== active.summary || form.content !== active.content || form.published !== active.published);
  const save = () => {
    if (!active) return;
    update.mutate({ slug: active.slug, data: form }, { onSuccess: (updated) => {
      qc.setQueryData(getListWhatsAppEducationModulesQueryKey(), (old: typeof modules) => old?.map((m) => m.slug === updated.slug ? updated : m));
      setSaved(true);
      window.setTimeout(() => setSaved(false), 3200);
    } });
  };
  return <Shell title="Education library" eyebrow="Approved content">
    <div className="education-intro"><div className="education-stamp"><BookOpen size={19} /></div><div><h2>Teach with a steady hand.</h2><p>Maintain the approved learning modules the assistant can draw from. Changes are saved to this workspace library.</p></div><div className="approved-count"><span>{modules.filter((m) => m.published).length.toString().padStart(2, '0')}</span><small>PUBLISHED</small></div></div>
    <QueryState loading={q.isLoading} error={q.error} retry={() => q.refetch()}>
      {!modules.length ? <div className="empty-state"><div className="empty-mark"><FileText size={21} /></div><h2>No education modules yet</h2><p>Approved modules provided by the workspace will appear here. This page does not create new topics.</p></div> :
        <div className="education-layout"><aside className="module-list panel"><div className="module-list-head"><span>MODULES</span><span>{modules.length.toString().padStart(2, '0')}</span></div>{modules.map((m, i) => <button key={m.slug} onClick={() => setActiveSlug(m.slug)} className={`module-choice ${active?.slug === m.slug ? 'module-choice-active' : ''}`} data-testid={`button-module-${m.slug}`}><span className="module-index">{String(i + 1).padStart(2, '0')}</span><span className="module-name">{m.title}<small>{m.slug}</small></span><i className={`publish-dot ${m.published ? 'publish-on' : ''}`} /></button>)}</aside>
          {active && <section className="panel module-editor"><div className="editor-head"><div><div className="panel-kicker">MODULE / {active.slug.toUpperCase()}</div><h2>{active.title}</h2></div><div className={`publish-state ${form.published ? 'is-published' : ''}`}><span />{form.published ? 'Published' : 'Unpublished'}</div></div>
            <label className="field-label">Short summary <span>{form.summary.length} / 2,000</span><textarea className="editor-summary" value={form.summary} maxLength={2000} onChange={(e) => setForm((s) => ({ ...s, summary: e.target.value }))} data-testid="input-module-summary" placeholder="A concise description of this lesson." /></label>
            <label className="field-label">Lesson content <span>{form.content.length.toLocaleString()} / 50,000</span><textarea className="editor-content" value={form.content} maxLength={50000} onChange={(e) => setForm((s) => ({ ...s, content: e.target.value }))} data-testid="input-module-content" placeholder="Write the approved lesson content…" /></label>
            <div className="editor-bottom"><label className="toggle-line"><input type="checkbox" checked={form.published} onChange={(e) => setForm((s) => ({ ...s, published: e.target.checked }))} data-testid="input-module-published" /><span className="toggle-track" /><span><strong>Published to assistant</strong><small>Only published material is available for answers.</small></span></label><div className="save-area">{saved && <span className="form-success"><Check size={13} /> Saved</span>}{update.error && <span className="form-error">Could not save changes.</span>}<Button onClick={save} disabled={!dirty || update.isPending}>{update.isPending ? <><RefreshCw size={15} className="spin" /> Saving</> : <><Check size={15} /> Save changes</>}</Button></div></div>
            <div className="last-updated">{active.updatedAt ? `Last updated ${formatDateTime(active.updatedAt)}` : 'No update timestamp available'}</div>
          </section>}
        </div>}
    </QueryState>
  </Shell>;
}

function Settings() {
  const q = useGetWhatsAppSettings({ query: { queryKey: getGetWhatsAppSettingsQueryKey() }, request: req });
  const health = useGetWhatsAppHealth({ query: { queryKey: getGetWhatsAppHealthQueryKey() }, request: req });
  const qc = useQueryClient();
  const update = useUpdateWhatsAppSettings({ request: req });
  const [url, setUrl] = useState('');
  const [saved, setSaved] = useState(false);
  const [urlInitialized, setUrlInitialized] = useState(false);
  const settings = q.data;
  useEffect(() => { if (settings && !urlInitialized) { setUrl(settings.telegramCommunityUrl ?? ''); setUrlInitialized(true); } }, [settings, urlInitialized]);
  const saveUrl = () => {
    const trimmed = url.trim();
    if (trimmed && !/^https:\/\/t\.me\/[A-Za-z0-9_+/?=-]+$/.test(trimmed)) return;
    update.mutate({ data: { telegramCommunityUrl: trimmed || null } }, { onSuccess: (next) => { qc.setQueryData(getGetWhatsAppSettingsQueryKey(), next); qc.invalidateQueries({ queryKey: getGetWhatsAppDashboardQueryKey() }); setSaved(true); window.setTimeout(() => setSaved(false), 3000); } });
  };
  const togglePaused = () => settings && update.mutate({ data: { paused: !settings.paused } }, { onSuccess: (next) => { qc.setQueryData(getGetWhatsAppSettingsQueryKey(), next); qc.invalidateQueries({ queryKey: getGetWhatsAppDashboardQueryKey() }); } });
  const invalidUrl = !!url.trim() && !/^https:\/\/t\.me\/[A-Za-z0-9_+/?=-]+$/.test(url.trim());
  return <Shell title="Assistant settings" eyebrow="Control room">
    <QueryState loading={q.isLoading} error={q.error} retry={() => q.refetch()}>
      {settings && <div className="settings-layout">
        <section className={`control-card ${settings.paused ? 'control-paused' : ''}`}><div className="control-card-top"><div className="control-emblem">{settings.paused ? <Pause size={20} /> : <Zap size={20} />}</div><StatusPill paused={settings.paused} testMode={settings.testMode} /></div><div className="control-copy"><div className="panel-kicker">AI REPLY CONTROL</div><h2>{settings.paused ? 'Replies are paused.' : 'Replies are on.'}</h2><p>{settings.paused ? 'The assistant will not send automated replies. Incoming test-number conversations continue to be recorded.' : 'Automated replies are active for approved test recipients only.'}</p></div><Button variant={settings.paused ? 'primary' : 'outline'} onClick={togglePaused} disabled={update.isPending}>{settings.paused ? <><Play size={15} /> Resume AI replies</> : <><Pause size={15} /> Pause AI replies</>}</Button><div className="control-foot"><ShieldCheck size={14} /> This setting affects automated replies only. Manual replies remain subject to the 24-hour window.</div></section>
        <section className="panel connection-panel"><div className="panel-header"><div><div className="panel-kicker">SAFE BY DESIGN</div><h2>Test connection</h2></div><span className="test-only-badge"><LockKeyhole size={12} /> TEST MODE</span></div><p className="panel-lede">This workspace is isolated to test numbers. It does not expose customer broadcasts or general recipient entry.</p><div className="connection-checks"><div className="readiness-item" data-testid="status-whatsapp-health"><span className={`readiness-state ${health.data?.status === 'ok' ? 'ready' : 'not-ready'}`}>{health.data?.status === 'ok' ? <Check size={12} /> : <X size={12} />}</span><span>Assistant service health</span><strong>{health.isLoading ? 'Checking' : health.data?.status === 'ok' ? 'Operational' : 'Unavailable'}{health.isError && <> · <button className="inline-action" onClick={() => health.refetch()}>Retry</button></>}</strong></div><Readiness label="WhatsApp credentials" ready={settings.connection.credentialsConfigured} /><Readiness label="Webhook configured" ready={settings.connection.webhookConfigured} /><Readiness label="Gemini configured" ready={settings.connection.geminiConfigured} /></div><div className="connection-details"><div><span>Allowed test recipients</span><strong>{settings.connection.allowedTestRecipients}</strong></div><div className="webhook-row"><span>Webhook URL</span><code>{settings.webhookUrl || 'Not configured'}</code></div></div></section>
        <section className="panel telegram-panel"><div className="telegram-heading"><div className="telegram-icon"><ExternalLink size={17} /></div><div><div className="panel-kicker">COMMUNITY DESTINATION</div><h2>Telegram community link</h2><p>Set the approved invite destination referenced by the assistant.</p></div></div><label className="field-label">Community invite URL <span>https://t.me/…</span><div className="url-field"><ExternalLink size={15} /><input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://t.me/yourcommunity" type="url" data-testid="input-community-url" /></div></label>{invalidUrl && <p className="form-error url-error">Use a valid https://t.me/ invite URL.</p>}<div className="telegram-actions">{saved && <span className="form-success"><Check size={13} /> Link saved</span>}{update.error && <span className="form-error">Could not update the community link.</span>}<Button onClick={saveUrl} disabled={invalidUrl || update.isPending || url.trim() === (settings.telegramCommunityUrl ?? '')}>{update.isPending ? <><RefreshCw size={14} className="spin" /> Saving</> : 'Save link'}</Button></div></section>
        <div className="settings-footnote"><CircleHelp size={15} /><span>Connection status is read-only here. Secrets and webhook setup are managed outside this admin workspace.</span></div>
      </div>}
    </QueryState>
  </Shell>;
}

function Login() {
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [location, setLocation] = useLocation();
  const q = useGetWhatsAppAuthStatus({ query: { queryKey: getGetWhatsAppAuthStatusQueryKey(), retry: false }, request: req });
  const login = useLoginWhatsAppAdmin({ request: req });
  const qc = useQueryClient();
  useEffect(() => { if (q.data?.authenticated) setLocation('/'); }, [q.data?.authenticated, setLocation]);
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!password.trim()) return;
    login.mutate({ data: { password } }, { onSuccess: (status) => { qc.setQueryData(getGetWhatsAppAuthStatusQueryKey(), status); if (status.authenticated) setLocation('/'); } });
  }
  return <div className="login-screen">
    <div className="login-visual"><div className="visual-grid" /><div className="login-brand"><div className="brand-symbol"><span>SM</span><i /></div><div><div className="brand-name">Smart Money Hub</div><div className="brand-product">WHATSAPP ASSISTANT</div></div></div><div className="visual-main"><div className="visual-topline"><span>PRIVATE OPERATIONS</span><span>01 — OWNER ACCESS</span></div><h1>Clear oversight.<br /><em>Careful answers.</em></h1><p>A considered workspace for the conversations, education, and controls behind your AI learning assistant.</p><div className="visual-diagram"><div className="diagram-node node-whatsapp"><MessageCircle size={18} /><span>TEST RECIPIENT</span></div><div className="diagram-path"><i /><i /><i /></div><div className="diagram-core"><span>SM</span><small>EDUCATION AI</small></div><div className="diagram-path reverse"><i /><i /><i /></div><div className="diagram-node node-owner"><ShieldCheck size={18} /><span>OWNER REVIEW</span></div></div></div><div className="visual-bottom"><span>TEST MODE ONLY</span><span>NO CUSTOMER BROADCASTS</span><span>PRIVATE SESSION</span></div></div>
    <div className="login-form-side"><div className="login-form-wrap"><div className="login-small-brand"><div className="brand-symbol"><span>SM</span><i /></div><span>SMART MONEY HUB</span></div><div className="login-lock"><KeyRound size={18} /></div><div className="login-eyebrow">OWNER SIGN IN</div><h2>Welcome back.</h2><p className="login-intro">Sign in to review the assistant’s private test workspace.</p>
      {q.data && !q.data.passwordConfigured && <Notice tone="warning"><ShieldOff size={15} /> Admin sign-in is not configured yet. Set the workspace password before accessing the console.</Notice>}
      {q.isError && <div className="login-api-note">Couldn’t verify your current session. You can still try signing in.</div>}
      <form onSubmit={submit} className="login-form"><label htmlFor="admin-password">Admin password</label><div className="password-field"><LockKeyhole size={16} /><input id="admin-password" type={show ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Enter your password" maxLength={256} required data-testid="input-admin-password" /><button type="button" onClick={() => setShow(!show)} data-testid="button-toggle-password">{show ? 'Hide' : 'Show'}</button></div>{login.error && <div className="login-error" role="alert">{login.error instanceof Error ? login.error.message : 'Sign in failed. Check your password and try again.'}</div>}<Button type="submit" className="login-submit" disabled={login.isPending || !password.trim() || q.data?.passwordConfigured === false}>{login.isPending ? <><RefreshCw size={15} className="spin" /> Checking credentials</> : <>Enter private workspace <ArrowUpRight size={15} /></>}</Button></form>
      <div className="login-assurance"><ShieldCheck size={15} /><span>Session protected · same-origin secure connection</span></div><div className="login-help">Need access restored? <span>Contact your workspace administrator.</span></div></div><div className="login-footer"><span>SMART MONEY HUB / ADMIN</span><span>ENCRYPTED SESSION</span></div></div>
  </div>;
}

function NotFoundPage() {
  return <div className="not-found"><div className="brand-symbol"><span>SM</span><i /></div><div className="eyebrow">404 / NOT FOUND</div><h1>This page isn’t in the ledger.</h1><p>The address may have changed, or this workspace route does not exist.</p><Link href={pathFor('/')} className="button button-primary">Return to overview</Link></div>;
}

function AuthenticatedApp() {
  const [location, setLocation] = useLocation();
  const status = useGetWhatsAppAuthStatus({ query: { queryKey: getGetWhatsAppAuthStatusQueryKey(), retry: false }, request: req });
  useEffect(() => { if (!status.isLoading && !status.data?.authenticated && location !== '/login') setLocation('/login'); }, [status.isLoading, status.data?.authenticated, location, setLocation]);
  if (location === '/login') return <Login />;
  if (status.isLoading) return <div className="auth-loading"><Skeleton className="h-8 w-40" /><Skeleton className="h-48" /></div>;
  if (status.error || !status.data?.authenticated) return <Login />;
  return <Switch>
    <Route path="/" component={Dashboard} />
    <Route path="/conversations" component={ConversationList} />
    <Route path="/conversations/:id">{(params) => <ConversationDetail id={params.id} />}</Route>
    <Route path="/education" component={Education} />
    <Route path="/settings" component={Settings} />
    <Route component={NotFoundPage} />
  </Switch>;
}

function App() {
  return <QueryClientProvider client={client}><WouterRouter base={base}><AuthenticatedApp /></WouterRouter></QueryClientProvider>;
}

export default App;
