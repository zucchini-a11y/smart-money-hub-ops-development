import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetSupportSessionQueryKey,
  getGetSupportCaseQueryKey,
  getListSupportCasesQueryKey,
  getListSupportStaffQueryKey,
  useAddSupportCaseNote,
  useAssignSupportCase,
  useBootstrapSupportOwner,
  useCreateSupportReply,
  useGetSupportCase,
  useGetSupportSession,
  useListSupportCases,
  useListSupportStaff,
  useLoginSupportStaff,
  useLogoutSupportStaff,
  useUpdateSupportCaseStatus,
} from "@workspace/api-client-react";
import {
  ArrowLeft, Bot, Check, Clock3, LogOut, MessageCircle, RefreshCw,
  Send, ShieldCheck, UserRound, Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from "@/components/ui/form";

type Credentials = { email: string; password: string };
type BootstrapValues = Credentials & { displayName: string };
type TextValues = { text: string };

function LoginCard({
  needsSetup,
  onLogin,
  onBootstrap,
  busy,
  failure,
}: {
  needsSetup: boolean;
  onLogin: (values: Credentials) => void;
  onBootstrap: (values: BootstrapValues) => void;
  busy: boolean;
  failure: string;
}) {
  const loginForm = useForm<Credentials>({ defaultValues: { email: "", password: "" } });
  const bootstrapForm = useForm<BootstrapValues>({
    defaultValues: { email: "", displayName: "", password: "" },
  });

  return (
    <main className="fade-up mx-auto max-w-2xl px-4 py-8 md:px-8">
      <section className="panel rounded-2xl p-6 sm:p-8">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl border border-emerald-300/20 bg-emerald-300/[.07] text-emerald-200">
            <ShieldCheck size={20} />
          </div>
          <div>
            <div className="mono text-[9px] tracking-[.18em] text-emerald-200">STAFF ACCESS</div>
            <h1 className="display mt-1 text-2xl text-slate-100">Support portal sign-in</h1>
          </div>
        </div>
        {failure && <div className="mb-4 rounded-lg border border-rose-300/20 bg-rose-300/[.06] p-3 text-sm text-rose-100" role="alert" data-testid="status-support-auth-error">{failure}</div>}
        {needsSetup ? (
          <>
            <p className="mb-5 text-sm leading-6 text-slate-400">Create the first owner account for this Development support portal. This one-time setup is unavailable in Production.</p>
            <Form {...bootstrapForm}>
              <form className="space-y-4" onSubmit={bootstrapForm.handleSubmit(onBootstrap)}>
                <FormField control={bootstrapForm.control} name="displayName" rules={{ required: "Enter your name." }} render={({ field }) => (
                  <FormItem><FormLabel className="text-slate-300">Display name</FormLabel><FormControl><Input autoComplete="name" {...field} data-testid="input-support-display-name" /></FormControl><FormMessage /></FormItem>
                )} />
                <FormField control={bootstrapForm.control} name="email" rules={{ required: "Enter your email.", pattern: { value: /^\S+@\S+\.\S+$/, message: "Enter a valid email." } }} render={({ field }) => (
                  <FormItem><FormLabel className="text-slate-300">Email</FormLabel><FormControl><Input type="email" autoComplete="email" {...field} data-testid="input-support-email" /></FormControl><FormMessage /></FormItem>
                )} />
                <FormField control={bootstrapForm.control} name="password" rules={{ required: "Choose a password.", minLength: { value: 12, message: "Use at least 12 characters." } }} render={({ field }) => (
                  <FormItem><FormLabel className="text-slate-300">Password</FormLabel><FormControl><Input type="password" autoComplete="new-password" {...field} data-testid="input-support-password" /></FormControl><FormMessage /></FormItem>
                )} />
                <Button type="submit" disabled={busy} className="w-full" data-testid="button-support-bootstrap">{busy ? "Setting up…" : "Create owner account"}</Button>
              </form>
            </Form>
          </>
        ) : (
          <Form {...loginForm}>
            <form className="space-y-4" onSubmit={loginForm.handleSubmit(onLogin)}>
              <FormField control={loginForm.control} name="email" rules={{ required: "Enter your email.", pattern: { value: /^\S+@\S+\.\S+$/, message: "Enter a valid email." } }} render={({ field }) => (
                <FormItem><FormLabel className="text-slate-300">Email</FormLabel><FormControl><Input type="email" autoComplete="username" {...field} data-testid="input-support-email" /></FormControl><FormMessage /></FormItem>
              )} />
              <FormField control={loginForm.control} name="password" rules={{ required: "Enter your password." }} render={({ field }) => (
                <FormItem><FormLabel className="text-slate-300">Password</FormLabel><FormControl><Input type="password" autoComplete="current-password" {...field} data-testid="input-support-password" /></FormControl><FormMessage /></FormItem>
              )} />
              <Button type="submit" disabled={busy} className="w-full" data-testid="button-support-login">{busy ? "Signing in…" : "Sign in"}</Button>
            </form>
          </Form>
        )}
      </section>
    </main>
  );
}

export default function SupportPage() {
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
  const login = useLoginSupportStaff();
  const bootstrap = useBootstrapSupportOwner();
  const logout = useLogoutSupportStaff();
  const reply = useCreateSupportReply();
  const addNote = useAddSupportCaseNote();
  const assign = useAssignSupportCase();
  const changeStatus = useUpdateSupportCaseStatus();
  const [failure, setFailure] = useState("");
  const [notice, setNotice] = useState("");
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

  if (session.isLoading) {
    return <main className="mx-auto max-w-7xl px-4 py-10 md:px-8"><div className="panel rounded-xl p-6 text-sm text-slate-400">Checking staff access…</div></main>;
  }
  if (!signedIn) {
    return <LoginCard
      needsSetup={Boolean(session.data?.needsSetup)}
      busy={login.isPending || bootstrap.isPending}
      failure={failure || (session.isError ? "Support access is unavailable. Check the Development API and test schema." : "")}
      onLogin={(values) => {
        setFailure("");
        login.mutate({ data: values }, {
          onSuccess: async () => { await client.invalidateQueries({ queryKey: getGetSupportSessionQueryKey() }); },
          onError: () => setFailure("Email or password is incorrect."),
        });
      }}
      onBootstrap={(values) => {
        setFailure("");
        bootstrap.mutate({ data: values }, {
          onSuccess: async () => { await client.invalidateQueries({ queryKey: getGetSupportSessionQueryKey() }); },
          onError: () => setFailure("Owner setup could not be completed. It may already be configured."),
        });
      }}
    />;
  }

  const selected = detail.data?.case;
  const messages = detail.data?.messages ?? [];
  const notes = detail.data?.notes ?? [];
  const events = detail.data?.events ?? [];
  const role = session.data?.staff?.role;
  const canManage = role === "owner" || role === "manager";

  return (
    <main className="fade-up mx-auto max-w-[1440px] px-4 py-7 md:px-8 md:py-9">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="mono text-[9px] tracking-[.2em] text-emerald-200">SHARED MEMBER SUPPORT</div>
          <h1 className="display mt-2 text-3xl text-slate-100">Support cases</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">Signals and Coach requests share one queue. Replies are delivered by the bot that received the case.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-400" data-testid="text-support-staff">
            {session.data?.staff?.displayName} · {role}
          </span>
          <Button variant="outline" size="sm" onClick={() => logout.mutate(undefined, { onSuccess: async () => { setSelectedId(""); await client.invalidateQueries({ queryKey: getGetSupportSessionQueryKey() }); } })} disabled={logout.isPending} data-testid="button-support-logout">
            <LogOut size={14} className="mr-2" /> Sign out
          </Button>
        </div>
      </header>

      {notice && <button onClick={() => setNotice("")} className="mb-4 w-full rounded-lg border border-emerald-300/20 bg-emerald-300/[.06] p-3 text-left text-sm text-emerald-100" role="status" data-testid="status-support-notification">{notice}</button>}
      {failure && <div className="mb-4 rounded-lg border border-rose-300/20 bg-rose-300/[.06] p-3 text-sm text-rose-100" role="alert" data-testid="status-support-error">{failure}</div>}

      <div className="grid gap-5 xl:grid-cols-[minmax(320px,0.78fr)_minmax(0,1.6fr)]">
        <section className="panel overflow-hidden rounded-xl">
          <div className="flex items-center justify-between border-b border-white/[.07] px-5 py-4">
            <div><div className="mono text-[9px] tracking-[.17em] text-slate-500">CASE QUEUE</div><h2 className="mt-1 text-sm font-semibold text-slate-100">{cases.data?.cases.length ?? 0} records</h2></div>
            <Button variant="ghost" size="icon" onClick={() => void refresh()} aria-label="Refresh support cases" data-testid="button-support-refresh"><RefreshCw size={15} className={cases.isFetching ? "animate-spin" : ""} /></Button>
          </div>
          {cases.isLoading ? <p className="p-5 text-sm text-slate-400">Loading cases…</p> : cases.isError ? <p className="p-5 text-sm text-rose-200">The case queue could not be loaded.</p> : !cases.data?.cases.length ? <div className="p-8 text-center"><MessageCircle className="mx-auto text-slate-600" size={24} /><p className="mt-3 text-sm text-slate-300">No support cases yet</p><p className="mt-1 text-xs text-slate-500">New cases from either bot will appear here.</p></div> : (
            <div className="max-h-[70vh] overflow-auto">
              {cases.data.cases.map((item) => (
                <button key={item.caseId} onClick={() => { setSelectedId(item.caseId); setFailure(""); setNotice(""); }} className={`block w-full border-b border-white/[.06] px-5 py-4 text-left transition hover:bg-white/[.035] ${selectedId === item.caseId ? "bg-emerald-300/[.06]" : ""}`} data-testid={`button-support-case-${item.caseId}`}>
                  <div className="flex items-center justify-between gap-3">
                    <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-cyan-200"><Bot size={12} /> {item.sourceBot}</span>
                    <span className="text-[10px] text-slate-500">{new Date(item.updated).toLocaleString()}</span>
                  </div>
                  <p className="mt-2 line-clamp-2 text-sm text-slate-200">{item.question}</p>
                  <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
                    <span>Member {item.memberId}</span><span>·</span><span>{item.workflowStatus.replaceAll("_", " ")}</span><span>·</span><span>{item.priority}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
          <p className="border-t border-white/[.07] px-5 py-3 text-[10px] text-slate-500">Queue refreshes every 15 seconds.</p>
        </section>

        {!selectedId ? (
          <section className="panel grid min-h-[420px] place-items-center rounded-xl p-8 text-center">
            <div><MessageCircle size={28} className="mx-auto text-slate-600" /><h2 className="mt-4 text-lg text-slate-200">Select a case</h2><p className="mt-2 max-w-sm text-sm leading-6 text-slate-500">Review the member’s messages, add a private note, or send a response through the originating bot.</p></div>
          </section>
        ) : detail.isLoading ? (
          <section className="panel rounded-xl p-6 text-sm text-slate-400">Loading case details…</section>
        ) : detail.isError || !selected ? (
          <section className="panel rounded-xl p-6 text-sm text-rose-200">This case is unavailable or you no longer have access.</section>
        ) : (
          <section className="panel overflow-hidden rounded-xl">
            <div className="border-b border-white/[.07] p-5 sm:p-6">
              <button onClick={() => setSelectedId("")} className="mb-4 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-100 xl:hidden" data-testid="button-support-back"><ArrowLeft size={13} /> Case queue</button>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div><div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-cyan-200"><Bot size={13} /> {selected.sourceBot} bot</div><h2 className="mt-2 text-lg font-semibold text-slate-100">Case conversation</h2></div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-white/10 px-2.5 py-1 text-[10px] text-slate-300">{selected.status}</span>
                  {canManage && <select value={selected.workflowStatus} onChange={(event) => changeStatus.mutate({ caseId: selected.caseId, data: { workflowStatus: event.target.value as "new" | "assigned" | "in_progress" | "waiting_for_member" | "resolved" | "closed" } }, { onSuccess: () => void invalidateCaseData(), onError: () => setFailure("Status could not be updated.") })} className="rounded-md border border-white/10 bg-[#111923] px-2.5 py-1.5 text-xs text-slate-200" aria-label="Workflow status" data-testid="select-support-status">
                    {["new", "assigned", "in_progress", "waiting_for_member", "resolved", "closed"].map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
                  </select>}
                </div>
              </div>
              <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-slate-200" data-testid="text-support-question">{selected.question}</p>
              <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-[10px] text-slate-500"><span className="inline-flex items-center gap-1"><UserRound size={12} /> Member {selected.memberId}</span><span className="inline-flex items-center gap-1"><Clock3 size={12} /> {new Date(selected.created).toLocaleString()}</span></div>
              {canManage && <label className="mt-4 flex max-w-sm items-center gap-2 text-xs text-slate-400"><Users size={13} /> Assign
                <select value={selected.assignedStaffId ?? ""} onChange={(event) => assign.mutate({ caseId: selected.caseId, data: { assignedStaffId: event.target.value || null } }, { onSuccess: () => void invalidateCaseData(), onError: () => setFailure("Assignment could not be updated.") })} className="min-w-40 rounded-md border border-white/10 bg-[#111923] px-2.5 py-1.5 text-xs text-slate-200" data-testid="select-support-assignee">
                  <option value="">Unassigned</option>
                  {(staff.data ?? []).map((person) => <option key={person.id} value={person.id}>{person.displayName} · {person.role}</option>)}
                </select>
              </label>}
            </div>

            <div className="max-h-[34vh] space-y-3 overflow-auto border-b border-white/[.07] p-5 sm:p-6" aria-live="polite">
              {messages.map((message) => (
                <article key={message.id} className={`rounded-lg border p-3 ${message.sender === "staff" ? "border-cyan-300/10 bg-cyan-300/[.035]" : "border-white/[.07] bg-white/[.02]"}`} data-testid={`card-support-message-${message.id}`}>
                  <div className="flex justify-between gap-3"><span className="text-xs font-medium text-slate-200">{message.displayName}</span><span className="text-[10px] text-slate-500">{new Date(message.created).toLocaleString()} · {message.status}</span></div>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-300">{message.text}</p>
                </article>
              ))}
            </div>

            <div className="grid gap-5 p-5 sm:p-6">
              <Form {...replyForm}>
                <form className="space-y-3" onSubmit={replyForm.handleSubmit((values) => {
                  setFailure(""); setNotice("");
                  const requestId = crypto.randomUUID();
                  reply.mutate({ caseId: selected.caseId, data: { text: values.text.trim(), requestId } }, {
                    onSuccess: async () => { replyForm.reset({ text: "" }); setNotice("Reply queued for delivery through the originating bot."); await invalidateCaseData(); },
                    onError: () => setFailure("Reply could not be queued. Check the case before retrying."),
                  });
                })}>
                  <FormField control={replyForm.control} name="text" rules={{ required: "Enter a reply.", minLength: { value: 3, message: "Use at least 3 characters." }, maxLength: { value: 3000, message: "Keep the reply under 3,000 characters." } }} render={({ field }) => (
                    <FormItem><FormLabel className="text-xs text-slate-300">Reply to member</FormLabel><FormControl><Textarea {...field} rows={3} placeholder="Write a reply. Never include passwords or verification codes." data-testid="input-support-reply" /></FormControl><FormMessage /></FormItem>
                  )} />
                  <Button type="submit" size="sm" disabled={reply.isPending || selected.workflowStatus === "closed"} data-testid="button-support-send-reply"><Send size={13} className="mr-2" />{reply.isPending ? "Queueing…" : "Queue reply"}</Button>
                </form>
              </Form>

              {canManage && <Form {...noteForm}>
                <form className="space-y-3 border-t border-white/[.07] pt-4" onSubmit={noteForm.handleSubmit((values) => {
                  setFailure("");
                  addNote.mutate({ caseId: selected.caseId, data: { text: values.text.trim() } }, {
                    onSuccess: async () => { noteForm.reset({ text: "" }); setNotice("Private note saved."); await invalidateCaseData(); },
                    onError: () => setFailure("Private note could not be saved."),
                  });
                })}>
                  <FormField control={noteForm.control} name="text" rules={{ required: "Enter a note.", minLength: { value: 3, message: "Use at least 3 characters." }, maxLength: { value: 3000, message: "Keep the note under 3,000 characters." } }} render={({ field }) => (
                    <FormItem><FormLabel className="text-xs text-slate-300">Private staff note</FormLabel><FormControl><Textarea {...field} rows={2} placeholder="Only support staff can see this note." data-testid="input-support-note" /></FormControl><FormMessage /></FormItem>
                  )} />
                  <Button type="submit" size="sm" variant="outline" disabled={addNote.isPending} data-testid="button-support-add-note"><Check size={13} className="mr-2" />Save private note</Button>
                </form>
              </Form>}

              {canManage && notes.length > 0 && <div className="border-t border-white/[.07] pt-4">
                <h3 className="mb-2 text-xs font-semibold text-slate-300">Private notes</h3>
                <div className="space-y-2">{notes.map((note) => <div key={note.id} className="rounded-md border border-amber-200/10 bg-amber-100/[.025] p-3" data-testid={`card-support-note-${note.id}`}><div className="text-[10px] text-amber-100">{note.staffName} · {new Date(note.created).toLocaleString()}</div><p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-slate-300">{note.text}</p></div>)}</div>
              </div>}

              {events.length > 0 && <div className="border-t border-white/[.07] pt-4">
                <h3 className="mb-2 text-xs font-semibold text-slate-300">Case history</h3>
                <div className="space-y-2">{events.map((event) => <div key={event.id} className="text-[11px] text-slate-500" data-testid={`text-support-event-${event.id}`}>{event.actorName} · {event.eventType.replaceAll("_", " ")} {event.oldValue && `(${event.oldValue} → ${event.newValue})`} · {new Date(event.created).toLocaleString()}</div>)}</div>
              </div>}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
