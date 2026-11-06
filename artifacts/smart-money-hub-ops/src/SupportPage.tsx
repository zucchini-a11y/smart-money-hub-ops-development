import { useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetSupportSessionQueryKey,
  getGetSupportCaseQueryKey,
  getListSupportCasesQueryKey,
  getListSupportStaffQueryKey,
  useAddSupportCaseNote,
  useAssignSupportCase,
  useCreateSupportReply,
  useGetSupportCase,
  useGetSupportSession,
  useListSupportCases,
  useListSupportStaff,
  useLogoutSupportStaff,
  usePortalLogout,
  useUpdateSupportCaseStatus,
} from "@workspace/api-client-react";
import {
  ArrowLeft,
  ArrowUpRight,
  Bot,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Inbox,
  LockKeyhole,
  LogOut,
  MessageCircle,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  Users,
} from "lucide-react";
import { Link, useLocation } from "wouter";
import { useClerk } from "@clerk/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from "@/components/ui/form";
import "./SupportPage.css";

type TextValues = { text: string };

const workflowOptions = ["new", "assigned", "in_progress", "waiting_for_member", "resolved", "closed"];
const workflowLabel = (value: string) => value.replaceAll("_", " ");

export default function SupportPage() {
  const clerk = useClerk();
  const [, navigate] = useLocation();
  const client = useQueryClient();
  const session = useGetSupportSession({
    query: { queryKey: getGetSupportSessionQueryKey(), retry: false, refetchInterval: 30_000 },
  });
  const signedIn = Boolean(session.data?.authenticated);
  const casesParams = { status: "all" as const };
  const cases = useListSupportCases(casesParams, {
    query: {
      queryKey: getListSupportCasesQueryKey(casesParams),
      enabled: signedIn,
      refetchInterval: 15_000,
      refetchIntervalInBackground: false,
    },
  });
  const staff = useListSupportStaff({
    query: { queryKey: getListSupportStaffQueryKey(), enabled: signedIn },
  });
  const [selectedId, setSelectedId] = useState("");
  const detail = useGetSupportCase(selectedId, {
    query: { queryKey: getGetSupportCaseQueryKey(selectedId), enabled: signedIn && Boolean(selectedId), refetchInterval: 15_000 },
  });
  const logout = useLogoutSupportStaff();
  const portalLogout = usePortalLogout();
  const reply = useCreateSupportReply();
  const addNote = useAddSupportCaseNote();
  const assign = useAssignSupportCase();
  const changeStatus = useUpdateSupportCaseStatus();
  const [failure, setFailure] = useState("");
  const [notice, setNotice] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchText, setSearchText] = useState("");
  const priorUpdated = useRef<Map<string, string> | null>(null);
  const replyForm = useForm<TextValues>({ defaultValues: { text: "" } });
  const noteForm = useForm<TextValues>({ defaultValues: { text: "" } });

  useEffect(() => {
    const current = cases.data?.cases;
    if (!current) return;
    const updated = new Map(current.map((item) => [item.caseId, item.updated]));
    if (priorUpdated.current) {
      const newCount = [...updated.keys()].filter((id) => !priorUpdated.current?.has(id)).length;
      const changedCount = current.filter((item) =>
        priorUpdated.current?.has(item.caseId) && priorUpdated.current.get(item.caseId) !== item.updated,
      ).length;
      if (newCount > 0) setNotice(`${newCount} new support case${newCount === 1 ? "" : "s"} received.`);
      else if (changedCount > 0) setNotice(`${changedCount} support case${changedCount === 1 ? "" : "s"} updated.`);
    }
    priorUpdated.current = updated;
  }, [cases.data?.cases]);

  const refresh = async () => {
    await Promise.all([cases.refetch(), selectedId ? detail.refetch() : Promise.resolve()]);
  };
  const invalidateCaseData = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: getListSupportCasesQueryKey(casesParams) }),
      client.invalidateQueries({ queryKey: getGetSupportCaseQueryKey(selectedId) }),
    ]);
  };

  const allCases = cases.data?.cases ?? [];
  const filteredCases = useMemo(() => allCases.filter((item) => {
    const sourceMatch = sourceFilter === "all" || item.sourceBot.toLowerCase() === sourceFilter;
    const statusMatch = statusFilter === "all" || item.workflowStatus === statusFilter;
    const searchMatch = `${item.caseId} ${item.question} ${item.sourceBot}`.toLowerCase().includes(searchText.toLowerCase().trim());
    return sourceMatch && statusMatch && searchMatch;
  }), [allCases, searchText, sourceFilter, statusFilter]);

  if (session.isLoading) {
    return <div className="sp-page sp-session-loading">
      <div className="sp-topbar"><div className="sp-brand"><div className="sp-brand-mark"><ShieldCheck size={19} /></div><div><div className="sp-brand-name">VAYDA</div><div className="sp-brand-sub">SMART MONEY HUB · SUPPORT</div></div></div><Link className="sp-operations-link" href="/operations"><ArrowUpRight size={14} /> Operations Center</Link></div>
      <main className="sp-loading-card" aria-label="Checking staff access"><div className="sp-skeleton sp-skeleton-title" /><div className="sp-skeleton sp-skeleton-row" /><div className="sp-skeleton sp-skeleton-row short" /></main>
    </div>;
  }

  if (!signedIn) {
    return <div className="sp-page sp-auth-page">
      <div className="sp-topbar">
        <div className="sp-brand"><div className="sp-brand-mark"><ShieldCheck size={19} /></div><div><div className="sp-brand-name">VAYDA</div><div className="sp-brand-sub">SMART MONEY HUB · SUPPORT</div></div></div>
        <Link className="sp-operations-link" href="/operations" data-testid="link-support-return-operations"><ArrowUpRight size={14} /> Back to Operations Center</Link>
      </div>
      <main className="sp-login-card">
        <div className="sp-eyebrow">SHARED ACCOUNT ACCESS</div><h2>Sign in to continue</h2>
        <p className="sp-login-intro">Support tools use the same staff account as the rest of the portal.</p>
        {session.isError && <div className="sp-error" role="alert">Support access is unavailable. Try again from the shared sign-in page.</div>}
        <Link className="sp-primary-button" href="/login" data-testid="link-support-shared-login">Go to shared sign-in <ArrowUpRight size={15}/></Link>
      </main>
    </div>;
  }

  const selected = detail.data?.case;
  const messages = detail.data?.messages ?? [];
  const notes = detail.data?.notes ?? [];
  const events = detail.data?.events ?? [];
  const role = session.data?.staff?.role;
  const canManage = role === "owner" || role === "manager";
  const openCount = allCases.filter((item) => !["resolved", "closed"].includes(item.workflowStatus)).length;
  const replyCount = allCases.filter((item) => ["new", "assigned"].includes(item.workflowStatus)).length;

  return (
    <div className="sp-page sp-support-shell">
      <aside className="sp-sidebar" aria-label="Support portal navigation">
        <div className="sp-sidebar-brand">
          <div className="sp-brand-mark"><ShieldCheck size={20} /></div>
          <div><div className="sp-brand-name">VAYDA</div><div className="sp-brand-sub">SMART MONEY HUB</div></div>
        </div>
        <div className="sp-sidebar-caption">STAFF WORKSPACE</div>
        <nav className="sp-sidebar-nav" aria-label="Staff navigation">
          <Link className="sp-sidebar-link is-active" href="/support" aria-current="page" data-testid="link-support-sidebar">
            <Inbox size={16} /><span className="sp-sidebar-link-label">Support cases</span><span className="sp-sidebar-count">{openCount}</span>
          </Link>
          <Link className="sp-sidebar-link" href="/operations" data-testid="link-support-operations">
            <ArrowUpRight size={16} /><span className="sp-sidebar-link-label">Operations Center</span>
          </Link>
        </nav>
        <div className="sp-sidebar-bottom">
          <div><ShieldCheck size={14} /><span>Private staff workspace</span></div>
          <p>Signals and Coach support, together in one queue.</p>
        </div>
      </aside>
      <div className="sp-content">
        <header className="sp-topbar">
          <div className="sp-mobile-brand">
            <div className="sp-brand-mark"><ShieldCheck size={17} /></div>
            <div><div className="sp-brand-name">VAYDA</div><div className="sp-brand-sub">SUPPORT PORTAL</div></div>
          </div>
        <div className="sp-top-actions">
          <span className="sp-session-status"><span /> Staff session active</span>
          <span className="sp-staff-pill" data-testid="text-support-staff"><span className="sp-staff-avatar">{session.data?.staff?.displayName?.split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("")}</span><span>{session.data?.staff?.displayName} <i>·</i> {role}</span></span>
          <Link className="sp-operations-link sp-mobile-operations-link" href="/operations" data-testid="link-support-mobile-operations"><ArrowUpRight size={14} /><span>Operations Center</span></Link>
          <Button variant="outline" size="sm" className="sp-signout" onClick={async () => { await portalLogout.mutateAsync().catch(() => undefined); await logout.mutateAsync().catch(() => undefined); await clerk.signOut().catch(() => undefined); client.clear(); setSelectedId(""); navigate("/login"); }} disabled={portalLogout.isPending || logout.isPending} data-testid="button-support-logout">
            <LogOut size={14} /> <span>{portalLogout.isPending || logout.isPending ? "Signing out…" : "Sign out"}</span>
          </Button>
        </div>
      </header>

      <main className="sp-main">
        <div className="sp-heading">
          <div><div className="sp-eyebrow">SHARED MEMBER SUPPORT</div><h1>Support cases</h1><p>Signals and Coach requests, together in one place. Replies are sent through the bot that received the case.</p></div>
          <div className="sp-heading-meta"><span className="sp-live-indicator"><i /> Queue live</span><span className="sp-meta-divider" /><span>Auto-sync <b>15 sec</b></span></div>
        </div>

        {notice && <button onClick={() => setNotice("")} className="sp-notice" role="status" data-testid="status-support-notification"><span className="sp-notice-icon"><Sparkles size={15} /></span><span>{notice}</span><span className="sp-dismiss">×</span></button>}
        {failure && <div className="sp-error sp-page-error" role="alert" data-testid="status-support-error">{failure}</div>}

        <div className="sp-workspace">
          <section className={`sp-queue ${selectedId ? "sp-mobile-hide" : ""}`} aria-label="Support case queue">
            <div className="sp-queue-header">
              <div><div className="sp-kicker">INBOX</div><h2>Case queue <span>{filteredCases.length}</span></h2></div>
              <Button variant="ghost" size="icon" className="sp-refresh" onClick={() => void refresh()} aria-label="Refresh support cases" data-testid="button-support-refresh"><RefreshCw size={15} className={cases.isFetching ? "animate-spin" : ""} /></Button>
            </div>
            <div className="sp-queue-stats"><span><b>{openCount}</b> open</span><i /><span><b>{replyCount}</b> need a reply</span><span className="sp-total-count">{allCases.length} total</span></div>
            <label className="sp-search"><Search size={15} /><input aria-label="Search support cases" placeholder="Search cases…" value={searchText} onChange={(event) => setSearchText(event.target.value)} /><kbd>/</kbd></label>
            <div className="sp-filter-row">
              <label className="sp-filter">
                <SlidersHorizontal size={13} />
                <select aria-label="Filter support cases by source" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
                  <option value="all">All sources</option><option value="coach">Coach</option><option value="signals">Signals</option>
                </select><ChevronDown size={12} />
              </label>
              <label className="sp-filter">
                <select aria-label="Filter support cases by status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  <option value="all">All statuses</option>{workflowOptions.map((value) => <option key={value} value={value}>{workflowLabel(value)}</option>)}
                </select><ChevronDown size={12} />
              </label>
            </div>

            {cases.isLoading ? (
              <div className="sp-case-list sp-case-loading" aria-label="Loading support cases">
                {[0, 1, 2, 3].map((row) => <div className="sp-case-skeleton" key={row}><span /><b /><i /></div>)}
              </div>
            ) : cases.isError ? (
              <div className="sp-queue-state sp-queue-error" role="alert"><CircleHelp size={22} /><strong>Queue unavailable</strong><span>Support cases could not be loaded.</span><Button variant="outline" size="sm" className="sp-secondary-button" onClick={() => void cases.refetch()}>Try again</Button></div>
            ) : !allCases.length ? (
              <div className="sp-queue-state"><Inbox size={24} /><strong>No support cases yet</strong><span>New requests from Signals or Coach will appear here.</span></div>
            ) : !filteredCases.length ? (
              <div className="sp-queue-state"><Search size={22} /><strong>No matching cases</strong><span>Adjust the filters or search term.</span><button type="button" className="sp-text-action" onClick={() => { setSourceFilter("all"); setStatusFilter("all"); setSearchText(""); }}>Clear filters</button></div>
            ) : (
              <div className="sp-case-list">
                {filteredCases.map((item) => (
                  <button key={item.caseId} type="button" onClick={() => { setSelectedId(item.caseId); setFailure(""); setNotice(""); }} className={`sp-case-row ${selectedId === item.caseId ? "is-selected" : ""}`} data-testid={`button-support-case-${item.caseId}`}>
                    <div className="sp-case-row-top">
                      <span className={`sp-source sp-source-${item.sourceBot.toLowerCase()}`}><Bot size={13} /> {item.sourceBot}</span>
                      <time>{new Date(item.updated).toLocaleString()}</time>
                    </div>
                    <p>{item.question}</p>
                    <div className="sp-case-row-meta"><span className={`sp-status-dot sp-status-${item.workflowStatus}`} /><span>{workflowLabel(item.workflowStatus)}</span><i>·</i><span>{item.assignedStaffId ? (staff.data ?? []).find((person) => person.id === item.assignedStaffId)?.displayName ?? "Assigned" : "Unassigned"}</span><span className={`sp-priority priority-${item.priority}`}>{item.priority}</span></div>
                  </button>
                ))}
              </div>
            )}
            <div className="sp-queue-footer"><span className="sp-sync-dot" /> Queue refreshes every 15 seconds</div>
          </section>

          {!selectedId ? (
            <section className="sp-detail sp-select-state"><div className="sp-select-state-inner"><span className="sp-select-icon"><MessageCircle size={20} /></span><div className="sp-kicker">CASE WORKSPACE</div><h2>Select a case</h2><p>Review the member conversation, assign a teammate, add an internal note, or reply through its originating bot.</p></div></section>
          ) : detail.isLoading ? (
            <section className="sp-detail sp-detail-loading"><div className="sp-kicker">LOADING CONVERSATION</div><div className="sp-skeleton sp-skeleton-title" /><div className="sp-skeleton sp-skeleton-row" /><div className="sp-skeleton sp-skeleton-row" /></section>
          ) : detail.isError || !selected ? (
            <section className="sp-detail sp-detail-error"><CircleHelp size={23} /><h2>Case unavailable</h2><p>This case is unavailable or you no longer have access.</p><Button variant="outline" size="sm" className="sp-secondary-button" onClick={() => void detail.refetch()}>Try again</Button></section>
          ) : (
            <section className="sp-detail" aria-label="Selected support case">
              <div className="sp-detail-header">
                <button type="button" onClick={() => setSelectedId("")} className="sp-back" data-testid="button-support-back"><ArrowLeft size={14} /> Case queue</button>
                <div className="sp-detail-head-row">
                  <div><div className="sp-case-identifier">{selected.caseId}<span>·</span><span className={`sp-source sp-source-${selected.sourceBot.toLowerCase()}`}><Bot size={13} /> {selected.sourceBot}</span></div><h2>Case conversation</h2></div>
                  <div className="sp-controls">
                    <span className={`sp-status-pill sp-status-pill-${selected.workflowStatus}`}><i className={`sp-status-dot sp-status-${selected.workflowStatus}`} />{workflowLabel(selected.workflowStatus)}</span>
                    {canManage && <label className="sp-control-select"><Users size={14} /><select value={selected.assignedStaffId ?? ""} onChange={(event) => assign.mutate({ caseId: selected.caseId, data: { assignedStaffId: event.target.value || null } }, { onSuccess: () => void invalidateCaseData(), onError: () => setFailure("Assignment could not be updated.") })} aria-label="Assigned support staff" data-testid="select-support-assignee">
                      <option value="">Unassigned</option>{(staff.data ?? []).map((person) => <option key={person.id} value={person.id}>{person.displayName} · {person.role}</option>)}
                    </select><ChevronDown size={12} /></label>}
                    {canManage && <label className="sp-control-select"><select value={selected.workflowStatus} onChange={(event) => changeStatus.mutate({ caseId: selected.caseId, data: { workflowStatus: event.target.value as "new" | "assigned" | "in_progress" | "waiting_for_member" | "resolved" | "closed" } }, { onSuccess: () => void invalidateCaseData(), onError: () => setFailure("Status could not be updated.") })} aria-label="Workflow status" data-testid="select-support-status">
                      {workflowOptions.map((value) => <option key={value} value={value}>{workflowLabel(value)}</option>)}
                    </select><ChevronDown size={12} /></label>}
                  </div>
                </div>
              </div>

              <div className="sp-question">
                <div className="sp-question-label"><CircleHelp size={14} /> MEMBER QUESTION</div>
                <p data-testid="text-support-question">{selected.question}</p>
                <div className="sp-question-meta"><span><UserRound size={13} /> Member {selected.memberId}</span><span><Clock3 size={13} /> Received {new Date(selected.created).toLocaleString()}</span><span><MessageCircle size={13} /> {messages.length} messages</span></div>
              </div>

              <div className="sp-thread-heading"><span>CONVERSATION</span><span>{messages.length} messages <i>·</i> Delivered by {selected.sourceBot}</span></div>
              <div className="sp-thread" aria-live="polite">
                {messages.map((message) => (
                  <article key={message.id} className={`sp-message ${message.sender === "staff" ? "sp-message-staff" : ""}`} data-testid={`card-support-message-${message.id}`}>
                    <span className="sp-message-avatar">{message.sender === "staff" ? <ShieldCheck size={14} /> : <UserRound size={14} />}</span>
                    <div className="sp-message-content"><div className="sp-message-meta"><strong>{message.displayName}</strong><time>{new Date(message.created).toLocaleString()}</time><span className={`sp-delivery sp-delivery-${message.status}`}>{message.status}</span></div><p>{message.text}</p></div>
                  </article>
                ))}
              </div>

              <div className="sp-composer">
                <div className="sp-composer-title"><span><Send size={14} /> Reply to member</span><span>Sent through {selected.sourceBot}</span></div>
                <Form {...replyForm}>
                  <form className="sp-form-body" onSubmit={replyForm.handleSubmit((values) => {
                    setFailure(""); setNotice("");
                    const requestId = crypto.randomUUID();
                    reply.mutate({ caseId: selected.caseId, data: { text: values.text.trim(), requestId } }, {
                      onSuccess: async () => { replyForm.reset({ text: "" }); setNotice("Reply queued for delivery through the originating bot."); await invalidateCaseData(); },
                      onError: () => setFailure("Reply could not be queued. Check the case before retrying."),
                    });
                  })}>
                    <FormField control={replyForm.control} name="text" rules={{ required: "Enter a reply.", minLength: { value: 3, message: "Use at least 3 characters." }, maxLength: { value: 3000, message: "Keep the reply under 3,000 characters." } }} render={({ field }) => (
                      <FormItem><FormControl><Textarea className="sp-textarea" {...field} rows={3} placeholder="Write a reply. Never include passwords or verification codes." data-testid="input-support-reply" /></FormControl><FormMessage /></FormItem>
                    )} />
                    <div className="sp-compose-footer"><span>Never include passwords or verification codes.</span><Button type="submit" size="sm" className="sp-primary-button sp-send-button" disabled={reply.isPending || selected.workflowStatus === "closed"} data-testid="button-support-send-reply"><Send size={13} />{reply.isPending ? "Queueing…" : "Queue reply"}</Button></div>
                  </form>
                </Form>
              </div>

              {canManage && <div className="sp-private-note">
                <div className="sp-note-title"><span><LockKeyhole size={14} /> Private staff note</span><span>Visible to staff only</span></div>
                <Form {...noteForm}>
                  <form className="sp-form-body" onSubmit={noteForm.handleSubmit((values) => {
                    setFailure("");
                    addNote.mutate({ caseId: selected.caseId, data: { text: values.text.trim() } }, {
                      onSuccess: async () => { noteForm.reset({ text: "" }); setNotice("Private note saved."); await invalidateCaseData(); },
                      onError: () => setFailure("Private note could not be saved."),
                    });
                  })}>
                    <FormField control={noteForm.control} name="text" rules={{ required: "Enter a note.", minLength: { value: 3, message: "Use at least 3 characters." }, maxLength: { value: 3000, message: "Keep the note under 3,000 characters." } }} render={({ field }) => (
                      <FormItem><FormControl><Textarea className="sp-textarea sp-note-textarea" {...field} rows={2} placeholder="Add context for the support team…" data-testid="input-support-note" /></FormControl><FormMessage /></FormItem>
                    )} />
                    <div className="sp-compose-footer"><span><LockKeyhole size={12} /> Only support staff can see this.</span><Button type="submit" size="sm" variant="outline" className="sp-note-button" disabled={addNote.isPending} data-testid="button-support-add-note"><Check size={13} />{addNote.isPending ? "Saving…" : "Save private note"}</Button></div>
                  </form>
                </Form>
              </div>}

              <div className="sp-records">
                {canManage && <section className="sp-record-section">
                  <div className="sp-record-heading"><span className="sp-record-icon sp-note-icon"><LockKeyhole size={13} /></span><h3>Private notes</h3><span className="sp-record-count">{notes.length}</span></div>
                  {notes.length ? <div className="sp-record-list">{notes.map((note) => <article key={note.id} className="sp-saved-note" data-testid={`card-support-note-${note.id}`}><div><strong>{note.staffName}</strong><time>{new Date(note.created).toLocaleString()}</time></div><p>{note.text}</p></article>)}</div> : <p className="sp-record-empty">Staff notes added to this case will appear here.</p>}
                </section>}
                <section className="sp-record-section">
                  <div className="sp-record-heading"><span className="sp-record-icon sp-history-icon"><Clock3 size={13} /></span><h3>Case history</h3><span className="sp-record-count">{events.length}</span></div>
                  {events.length ? <div className="sp-history-list">{events.map((event) => <div key={event.id} className="sp-history-event" data-testid={`text-support-event-${event.id}`}><span className="sp-history-dot" /><span>{event.actorName} · {event.eventType.replaceAll("_", " ")} {event.oldValue && `(${event.oldValue} → ${event.newValue})`}</span><time>{new Date(event.created).toLocaleString()}</time></div>)}</div> : <p className="sp-record-empty">Case updates will be recorded here.</p>}
                </section>
              </div>
            </section>
          )}
        </div>
        <footer className="sp-footer"><span><ShieldCheck size={13} /> Staff-only workspace</span><span>Support Portal <i>·</i> Member data is handled securely</span></footer>
      </main>
      </div>
    </div>
  );
}
