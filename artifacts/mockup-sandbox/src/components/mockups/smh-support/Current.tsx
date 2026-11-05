import { useState } from "react";
import {
  ArrowLeft,
  Bot,
  Check,
  Clock3,
  LogOut,
  RefreshCw,
  Send,
  UserRound,
  Users,
} from "lucide-react";
import "./_group.css";

type SupportMessage = {
  id: string;
  sender: "member" | "staff";
  displayName: string;
  created: string;
  status: string;
  text: string;
};

type SupportCase = {
  caseId: string;
  sourceBot: string;
  updated: string;
  created: string;
  question: string;
  workflowStatus: string;
  priority: string;
  status: string;
  messages: SupportMessage[];
  note: string;
  event: string;
};

const caseData: SupportCase[] = [
  {
    caseId: "case-01",
    sourceBot: "Coach",
    updated: "Today, 10:42 AM",
    created: "Today, 9:18 AM",
    question: "I’m trying to compare two savings options. How should I think about the difference between a fixed rate and an account that can change its rate?",
    workflowStatus: "in_progress",
    priority: "normal",
    status: "open",
    messages: [
      {
        id: "message-01",
        sender: "member",
        displayName: "Member",
        created: "Today, 9:18 AM",
        status: "received",
        text: "I’m trying to compare two savings options. How should I think about the difference between a fixed rate and an account that can change its rate?",
      },
      {
        id: "message-02",
        sender: "staff",
        displayName: "Support team",
        created: "Today, 9:36 AM",
        status: "delivered",
        text: "A fixed rate stays the same for the agreed term, while a variable rate may move over time. It can help to compare the access rules, fees, and what happens when the term ends as well as the advertised rate.",
      },
      {
        id: "message-03",
        sender: "member",
        displayName: "Member",
        created: "Today, 10:42 AM",
        status: "received",
        text: "That helps. Is there a simple way to compare them if I might need access to the money sooner?",
      },
    ],
    note: "Follow up with the liquidity and early-access comparison guide.",
    event: "workflow_status_changed",
  },
  {
    caseId: "case-02",
    sourceBot: "Signals",
    updated: "Today, 10:08 AM",
    created: "Today, 8:54 AM",
    question: "Could you explain why a market signal can change after it first appears?",
    workflowStatus: "new",
    priority: "normal",
    status: "open",
    messages: [
      {
        id: "message-04",
        sender: "member",
        displayName: "Member",
        created: "Today, 8:54 AM",
        status: "received",
        text: "Could you explain why a market signal can change after it first appears?",
      },
      {
        id: "message-05",
        sender: "staff",
        displayName: "Support team",
        created: "Today, 9:14 AM",
        status: "delivered",
        text: "Signals reflect the information and conditions available at a given time. If those conditions change, the signal can update too; it’s best used as context rather than a guarantee.",
      },
    ],
    note: "Share the short guide on how signal updates are calculated.",
    event: "case_created",
  },
  {
    caseId: "case-03",
    sourceBot: "Coach",
    updated: "Yesterday, 4:26 PM",
    created: "Yesterday, 2:51 PM",
    question: "I missed a scheduled lesson this week. Can I pick up where I left off?",
    workflowStatus: "waiting_for_member",
    priority: "low",
    status: "open",
    messages: [
      {
        id: "message-06",
        sender: "member",
        displayName: "Member",
        created: "Yesterday, 2:51 PM",
        status: "received",
        text: "I missed a scheduled lesson this week. Can I pick up where I left off?",
      },
      {
        id: "message-07",
        sender: "staff",
        displayName: "Support team",
        created: "Yesterday, 3:10 PM",
        status: "delivered",
        text: "Absolutely. Your lesson history stays available, so you can continue with the next lesson whenever you’re ready.",
      },
    ],
    note: "Waiting to hear whether the lesson link worked.",
    event: "assigned",
  },
  {
    caseId: "case-04",
    sourceBot: "Signals",
    updated: "Yesterday, 1:12 PM",
    created: "Yesterday, 11:06 AM",
    question: "Where can I find the explanation behind a comparison in the weekly recap?",
    workflowStatus: "resolved",
    priority: "normal",
    status: "closed",
    messages: [
      {
        id: "message-08",
        sender: "member",
        displayName: "Member",
        created: "Yesterday, 11:06 AM",
        status: "received",
        text: "Where can I find the explanation behind a comparison in the weekly recap?",
      },
      {
        id: "message-09",
        sender: "staff",
        displayName: "Support team",
        created: "Yesterday, 11:34 AM",
        status: "delivered",
        text: "Open the recap item and choose “Why this comparison?” to see its sources and a plain-language explanation.",
      },
    ],
    note: "Resolved with recap navigation instructions.",
    event: "workflow_status_changed",
  },
  {
    caseId: "case-05",
    sourceBot: "Coach",
    updated: "Mon, 3:48 PM",
    created: "Mon, 3:02 PM",
    question: "Can I adjust how often I receive my learning reminders?",
    workflowStatus: "assigned",
    priority: "normal",
    status: "open",
    messages: [
      {
        id: "message-10",
        sender: "member",
        displayName: "Member",
        created: "Mon, 3:02 PM",
        status: "received",
        text: "Can I adjust how often I receive my learning reminders?",
      },
      {
        id: "message-11",
        sender: "staff",
        displayName: "Support team",
        created: "Mon, 3:26 PM",
        status: "delivered",
        text: "Yes. You can change the reminder schedule in your Coach preferences, including pausing reminders for a while.",
      },
    ],
    note: "Check that the reminder settings are clear in the next release.",
    event: "assigned",
  },
];

const workflowOptions = ["new", "assigned", "in_progress", "waiting_for_member", "resolved", "closed"];
const readableStatus = (value: string) => value.replaceAll("_", " ");

export function Current() {
  const [selectedId, setSelectedId] = useState("case-01");
  const selected = caseData.find((item) => item.caseId === selectedId) ?? caseData[0];

  return (
    <div className="smh-support-group dark min-h-screen">
      <main className="fade-up mx-auto max-w-[1440px] px-4 py-7 md:px-8 md:py-9">
        <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="mono text-[9px] tracking-[.2em] text-emerald-200">SHARED MEMBER SUPPORT</div>
            <h1 className="display mt-2 text-3xl text-slate-100">Support cases</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">Signals and Coach requests share one queue. Replies are delivered by the bot that received the case.</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-400" data-testid="text-support-staff">
              Support team · owner
            </span>
            <button type="button" className="inline-flex h-9 items-center rounded-md border border-white/10 px-3 text-xs text-slate-200 transition hover:bg-white/[.04]" data-testid="button-support-logout">
              <LogOut size={14} className="mr-2" /> Sign out
            </button>
          </div>
        </header>

        <div className="mb-4 w-full rounded-lg border border-emerald-300/20 bg-emerald-300/[.06] p-3 text-sm text-emerald-100" role="status" data-testid="status-support-notification">
          Queue synced just now · 2 cases need a reply
        </div>

        <div className="grid gap-5 xl:grid-cols-[minmax(320px,0.78fr)_minmax(0,1.6fr)]">
          <section className="panel overflow-hidden rounded-xl">
            <div className="flex items-center justify-between border-b border-white/[.07] px-5 py-4">
              <div><div className="mono text-[9px] tracking-[.17em] text-slate-500">CASE QUEUE</div><h2 className="mt-1 text-sm font-semibold text-slate-100">{caseData.length} records</h2></div>
              <button type="button" className="inline-grid h-9 w-9 place-items-center rounded-md text-slate-300 transition hover:bg-white/[.05]" aria-label="Refresh support cases" data-testid="button-support-refresh"><RefreshCw size={15} /></button>
            </div>
            <div className="max-h-[70vh] overflow-auto">
              {caseData.map((item) => (
                <button
                  type="button"
                  key={item.caseId}
                  onClick={() => setSelectedId(item.caseId)}
                  className={`block w-full border-b border-white/[.06] px-5 py-4 text-left transition hover:bg-white/[.035] ${selectedId === item.caseId ? "bg-emerald-300/[.06]" : ""}`}
                  data-testid={`button-support-case-${item.caseId}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-cyan-200"><Bot size={12} /> {item.sourceBot}</span>
                    <span className="text-[10px] text-slate-500">{item.updated}</span>
                  </div>
                  <p className="mt-2 line-clamp-2 text-sm text-slate-200">{item.question}</p>
                  <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
                    <span>Member · redacted</span><span>·</span><span>{readableStatus(item.workflowStatus)}</span><span>·</span><span>{item.priority}</span>
                  </div>
                </button>
              ))}
            </div>
            <p className="border-t border-white/[.07] px-5 py-3 text-[10px] text-slate-500">Queue refreshes every 15 seconds.</p>
          </section>

          <section className="panel overflow-hidden rounded-xl">
            <div className="border-b border-white/[.07] p-5 sm:p-6">
              <button type="button" onClick={() => setSelectedId("")} className="mb-4 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-100 xl:hidden" data-testid="button-support-back"><ArrowLeft size={13} /> Case queue</button>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div><div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-cyan-200"><Bot size={13} /> {selected.sourceBot} bot</div><h2 className="mt-2 text-lg font-semibold text-slate-100">Case conversation</h2></div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-white/10 px-2.5 py-1 text-[10px] text-slate-300">{selected.status}</span>
                  <select value={selected.workflowStatus} onChange={() => undefined} className="rounded-md border border-white/10 bg-[#111923] px-2.5 py-1.5 text-xs text-slate-200" aria-label="Workflow status" data-testid="select-support-status">
                    {workflowOptions.map((value) => <option key={value} value={value}>{readableStatus(value)}</option>)}
                  </select>
                </div>
              </div>
              <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-slate-200" data-testid="text-support-question">{selected.question}</p>
              <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-[10px] text-slate-500"><span className="inline-flex items-center gap-1"><UserRound size={12} /> Member · redacted</span><span className="inline-flex items-center gap-1"><Clock3 size={12} /> {selected.created}</span></div>
              <label className="mt-4 flex max-w-sm items-center gap-2 text-xs text-slate-400"><Users size={13} /> Assign
                <select defaultValue="support-owner" className="min-w-40 rounded-md border border-white/10 bg-[#111923] px-2.5 py-1.5 text-xs text-slate-200" data-testid="select-support-assignee">
                  <option value="">Unassigned</option>
                  <option value="support-owner">Support team · owner</option>
                  <option value="support-manager">Support team · manager</option>
                </select>
              </label>
            </div>

            <div className="max-h-[34vh] space-y-3 overflow-auto border-b border-white/[.07] p-5 sm:p-6" aria-live="polite">
              {selected.messages.map((message) => (
                <article key={message.id} className={`rounded-lg border p-3 ${message.sender === "staff" ? "border-cyan-300/10 bg-cyan-300/[.035]" : "border-white/[.07] bg-white/[.02]"}`} data-testid={`card-support-message-${message.id}`}>
                  <div className="flex justify-between gap-3"><span className="text-xs font-medium text-slate-200">{message.displayName}</span><span className="text-[10px] text-slate-500">{message.created} · {message.status}</span></div>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-300">{message.text}</p>
                </article>
              ))}
            </div>

            <div className="grid gap-5 p-5 sm:p-6">
              <form className="space-y-3" onSubmit={(event) => event.preventDefault()}>
                <label className="text-xs text-slate-300" htmlFor="support-reply">Reply to member</label>
                <textarea id="support-reply" rows={3} placeholder="Write a reply. Never include passwords or verification codes." className="flex w-full rounded-md border border-white/10 bg-[#111923] px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-300/50" data-testid="input-support-reply" />
                <button type="submit" className="inline-flex h-8 items-center rounded-md bg-emerald-300 px-3 text-xs font-medium text-[#0d1714] transition hover:bg-emerald-200" data-testid="button-support-send-reply"><Send size={13} className="mr-2" />Queue reply</button>
              </form>

              <form className="space-y-3 border-t border-white/[.07] pt-4" onSubmit={(event) => event.preventDefault()}>
                <label className="text-xs text-slate-300" htmlFor="support-note">Private staff note</label>
                <textarea id="support-note" rows={2} placeholder="Only support staff can see this note." className="flex w-full rounded-md border border-white/10 bg-[#111923] px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-300/50" data-testid="input-support-note" />
                <button type="submit" className="inline-flex h-8 items-center rounded-md border border-white/10 px-3 text-xs text-slate-200 transition hover:bg-white/[.04]" data-testid="button-support-add-note"><Check size={13} className="mr-2" />Save private note</button>
              </form>

              <div className="border-t border-white/[.07] pt-4">
                <h3 className="mb-2 text-xs font-semibold text-slate-300">Private notes</h3>
                <div className="space-y-2">
                  <div className="rounded-md border border-amber-200/10 bg-amber-100/[.025] p-3" data-testid="card-support-note-note-01">
                    <div className="text-[10px] text-amber-100">Support team · Today, 9:52 AM</div>
                    <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-slate-300">{selected.note}</p>
                  </div>
                </div>
              </div>

              <div className="border-t border-white/[.07] pt-4">
                <h3 className="mb-2 text-xs font-semibold text-slate-300">Case history</h3>
                <div className="space-y-2"><div className="text-[11px] text-slate-500" data-testid="text-support-event-event-01">Support team · {readableStatus(selected.event)} · Today, 9:22 AM</div></div>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
