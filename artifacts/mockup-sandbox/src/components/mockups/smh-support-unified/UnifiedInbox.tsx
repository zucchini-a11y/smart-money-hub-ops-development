import { useMemo, useState } from "react";
import {
  Activity, ArrowDownLeft, Check, CheckCheck,
  CircleAlert, Clock3, Inbox, LockKeyhole, MessageCircle,
  MessageSquareText, MoreHorizontal, Paperclip, Search, Send, ShieldCheck,
  SlidersHorizontal, Sparkles, UserRound,
} from "lucide-react";
import "./_group.css";

type Source = "Telegram case" | "Website chat";
type Status = "Open" | "Reply uncertain" | "Replied" | "Closed" | "Queued" | "In progress";
type Message = { from: "member" | "staff"; text: string; time: string };
type Thread = {
  id: string; name: string; initials: string; source: Source; status: Status;
  subject: string; preview: string; time: string; age: string; assigned: string;
  priority?: "Needs attention"; messages: Message[]; context: string;
};

const seedThreads: Thread[] = [
  { id: "CASE-4812", name: "Maya Chen", initials: "MC", source: "Telegram case", status: "Open", subject: "Lesson not showing in my dashboard", preview: "I finished the position sizing lesson yesterday, but it still looks locked.", time: "9:18 AM", age: "12 min", assigned: "Unassigned", priority: "Needs attention", context: "Member asks about course access. No account identifiers shown in this prototype.", messages: [
    { from: "member", text: "Hi, I finished the position sizing lesson yesterday, but it still looks locked in my dashboard. Could you help me find the next lesson?", time: "9:18 AM" },
  ] },
  { id: "WEB-0271", name: "Nora Patel", initials: "NP", source: "Website chat", status: "Queued", subject: "Where do I change email preferences?", preview: "I only want the weekly learning recap, not daily reminders.", time: "9:12 AM", age: "18 min", assigned: "Unassigned", priority: "Needs attention", context: "Visitor started a public website conversation. Email preference changes are not handled in this demo.", messages: [
    { from: "member", text: "I only want the weekly learning recap, not daily reminders. Where can I change that?", time: "9:12 AM" },
  ] },
  { id: "CASE-4811", name: "Elliot Brooks", initials: "EB", source: "Telegram case", status: "Reply uncertain", subject: "Why did the signal change?", preview: "The weekly note mentioned a different market view this morning.", time: "8:54 AM", age: "36 min", assigned: "Sam Rivera", context: "A prior reply may not have reached the member. Confirm delivery in the live system before retrying.", messages: [
    { from: "member", text: "Could someone explain why the signal changed? The weekly note mentioned a different market view this morning.", time: "8:54 AM" },
    { from: "staff", text: "I’ll check the published explanation and make sure we point you to the right context.", time: "9:03 AM" },
  ] },
  { id: "WEB-0268", name: "Jules Martin", initials: "JM", source: "Website chat", status: "In progress", subject: "Getting started with the learning hub", preview: "Thanks, I found the beginner path. One more question…", time: "8:46 AM", age: "44 min", assigned: "Avery Cole", context: "Website visitor viewing the Getting started guide. This conversation is assigned to Avery Cole.", messages: [
    { from: "member", text: "I’m new to the hub. Which lesson should I start with?", time: "8:40 AM" },
    { from: "staff", text: "The Foundations path is a good place to begin. It starts with risk and position sizing.", time: "8:43 AM" },
    { from: "member", text: "Thanks, I found the beginner path. One more question about the practice journal…", time: "8:46 AM" },
  ] },
  { id: "CASE-4808", name: "Robin Ellis", initials: "RE", source: "Telegram case", status: "Replied", subject: "Weekly recap breakdown", preview: "Found it under Learn → Weekly recap. Appreciate the pointer.", time: "Yesterday", age: "1 day", assigned: "Sam Rivera", context: "The member was directed to the weekly recap in the Learn area.", messages: [
    { from: "member", text: "Where can I find the breakdown behind the weekly recap?", time: "Yesterday · 11:06 AM" },
    { from: "staff", text: "Open Learn, then choose Weekly recap. The breakdown is at the bottom of each recap.", time: "Yesterday · 11:24 AM" },
    { from: "member", text: "Found it under Learn → Weekly recap. Appreciate the pointer.", time: "Yesterday · 11:31 AM" },
  ] },
  { id: "WEB-0262", name: "Tess Morgan", initials: "TM", source: "Website chat", status: "Closed", subject: "Is the course suitable for beginners?", preview: "That makes sense. I’ll take a look at the Foundations section.", time: "Mon", age: "2 days", assigned: "Avery Cole", context: "Resolved: visitor was shown the Foundations section and chose to continue independently.", messages: [
    { from: "member", text: "Is the course suitable for beginners?", time: "Mon · 2:16 PM" },
    { from: "staff", text: "Yes. The Foundations section is designed as an introduction and can be followed at your own pace.", time: "Mon · 2:20 PM" },
  ] },
];

const statusClass: Record<Status, string> = {
  Open: "open", "Reply uncertain": "uncertain", Replied: "replied", Closed: "closed",
  Queued: "queued", "In progress": "progress",
};

export function UnifiedInbox() {
  const [threads, setThreads] = useState(seedThreads);
  const [selectedId, setSelectedId] = useState(seedThreads[0]!.id);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("Needs attention");
  const [sourceFilter, setSourceFilter] = useState("All sources");
  const role = "Manager";
  const [reply, setReply] = useState("");
  const [toast, setToast] = useState("");
  const [mobileDetail, setMobileDetail] = useState(false);
  const selected = threads.find((thread) => thread.id === selectedId) ?? threads[0]!;
  const visible = useMemo(() => threads.filter((thread) => {
    const matchQuery = `${thread.name} ${thread.id} ${thread.subject} ${thread.preview}`.toLowerCase().includes(query.toLowerCase());
    const matchStatus = filter === "All conversations" || (filter === "Needs attention" ? ["Open", "Reply uncertain", "Queued"].includes(thread.status) : thread.status === filter);
    const matchSource = sourceFilter === "All sources" || thread.source === sourceFilter;
    return matchQuery && matchStatus && matchSource;
  }), [threads, query, filter, sourceFilter]);
  const countAttention = threads.filter((thread) => ["Open", "Reply uncertain", "Queued"].includes(thread.status)).length;
  const notice = (text: string) => { setToast(text); window.setTimeout(() => setToast(""), 2800); };
  const patchSelected = (updates: Partial<Thread>) => setThreads((all) => all.map((thread) => thread.id === selected.id ? { ...thread, ...updates } : thread));
  const sendReply = () => {
    if (!reply.trim()) return;
    patchSelected({ messages: [...selected.messages, { from: "staff", text: reply.trim(), time: "Now" }], preview: reply.trim(), status: selected.source === "Website chat" ? "In progress" : "Replied", time: "Now", age: "just now" });
    setReply("");
    notice("Demo reply added to this sample conversation.");
  };
  const selectThread = (id: string) => { setSelectedId(id); setMobileDetail(true); };
  const managerControls = true;

  return <div className="unified-inbox">
    <style>{`
      .unified-inbox{--ink:#203c37;--sub:#71817a;--paper:#f3f4ee;--panel:#fffefa;--line:#e3e7df;--green:#286655;--mint:#e9f3ed;--gold:#9b7736;min-height:100vh;background:var(--paper);color:var(--ink);font-family:'DM Sans',sans-serif;box-sizing:border-box}
      .unified-inbox *{box-sizing:border-box}.unified-inbox button,.unified-inbox input,.unified-inbox select,.unified-inbox textarea{font:inherit}.unified-inbox button{cursor:pointer}
      .ui-top{height:68px;background:#fffefa;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 clamp(18px,4vw,54px);gap:16px}
      .ui-brand{display:flex;align-items:center;gap:11px}.ui-mark{width:34px;height:34px;border-radius:10px;background:#244d45;color:#f6f3e9;display:grid;place-items:center}.ui-brand strong{font:700 14px Manrope,sans-serif;letter-spacing:-.03em}.ui-brand small{display:block;color:#8a9690;font:10px 'IBM Plex Mono',monospace;letter-spacing:.04em;margin-top:3px}
      .ui-top-right{display:flex;align-items:center;gap:14px}.ui-sample{display:inline-flex;align-items:center;gap:7px;border:1px solid #e8dfc8;background:#f8f2e3;color:#816b3c;border-radius:20px;padding:7px 10px;font-size:10px;font-weight:700;letter-spacing:.03em}.ui-sample i{width:6px;height:6px;border-radius:50%;background:#ba944a}
      .ui-role{border:1px solid var(--line);border-radius:8px;background:#fffefa;padding:7px 10px;color:#52645b;font-size:11px}
      .ui-shell{max-width:1500px;margin:0 auto;padding:27px clamp(16px,3vw,38px) 34px}.ui-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:20px}.ui-eyebrow{font:500 10px 'IBM Plex Mono',monospace;letter-spacing:.14em;color:#87948d;text-transform:uppercase}.ui-heading h1{margin:6px 0 4px;font:700 clamp(25px,3vw,33px) Manrope,sans-serif;letter-spacing:-.055em;color:#203c37}.ui-heading p{margin:0;color:#74837c;font-size:12px}.ui-ops{display:flex;align-items:center;gap:13px;color:#78877f;font-size:10px}.ui-live{width:7px;height:7px;border-radius:50%;background:#5a9a76;display:inline-block;margin-right:6px}
      .ui-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:16px}.ui-metric{background:#fffefa;border:1px solid var(--line);border-radius:10px;padding:12px 15px;display:flex;align-items:center;justify-content:space-between}.ui-metric-label{font-size:10px;color:#7e8c85}.ui-metric strong{display:block;font:700 22px Manrope,sans-serif;letter-spacing:-.04em;margin-top:4px}.ui-metric-icon{width:31px;height:31px;border-radius:9px;background:#eef4ef;color:#39745f;display:grid;place-items:center}.ui-metric.warn .ui-metric-icon{background:#f6f0df;color:#947636}
      .ui-workspace{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;box-shadow:0 7px 24px rgba(40,65,53,.035)}.ui-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 15px;border-bottom:1px solid var(--line);background:#fffefa}.ui-tabs{display:flex;align-items:center;gap:4px;min-width:0}.ui-tab{border:0;background:transparent;color:#7a8981;padding:8px 10px;border-radius:7px;font-size:11px;white-space:nowrap}.ui-tab.active{background:#eaf2ec;color:#2d634f;font-weight:700}.ui-tab b{font:500 9px 'IBM Plex Mono',monospace;background:#fff;border:1px solid #e2e8e1;padding:2px 5px;border-radius:9px;margin-left:5px}
      .ui-tool-actions{display:flex;align-items:center;gap:7px}.ui-search{height:33px;width:min(230px,26vw);display:flex;align-items:center;gap:7px;border:1px solid var(--line);border-radius:7px;padding:0 9px;color:#89958f;background:#fdfdfa}.ui-search input{border:0;outline:0;background:transparent;min-width:0;width:100%;font-size:11px;color:var(--ink)}.ui-search input::placeholder{color:#a0aaa4}.ui-filter{height:33px;border:1px solid var(--line);border-radius:7px;background:#fdfdfa;color:#596b62;font-size:10px;padding:0 9px}
      .ui-columns{display:grid;grid-template-columns:minmax(270px, .82fr) minmax(0,1.58fr);min-height:510px}.ui-list{border-right:1px solid var(--line);min-width:0}.ui-list-head{height:38px;padding:0 14px;display:flex;align-items:center;justify-content:space-between;background:#f8f9f5;color:#91a098;font:500 9px 'IBM Plex Mono',monospace;letter-spacing:.1em;text-transform:uppercase}.ui-list-body{max-height:555px;overflow:auto}.ui-row{width:100%;border:0;border-bottom:1px solid #eef0eb;background:#fffefa;padding:12px 13px;text-align:left;display:block;transition:background .16s}.ui-row:hover{background:#f7faf6}.ui-row.selected{background:#edf4ee;box-shadow:inset 3px 0 #34735c}.ui-row-top{display:flex;align-items:center;gap:9px}.ui-avatar{width:32px;height:32px;flex:none;border-radius:10px;background:#e8eee6;color:#426253;display:grid;place-items:center;font:600 10px Manrope,sans-serif}.ui-row.selected .ui-avatar{background:#d9e9dc}.ui-row-main{min-width:0;flex:1}.ui-row-name{display:flex;align-items:center;justify-content:space-between;gap:8px}.ui-row-name strong{font-size:11px;font-weight:700;color:#30473e;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ui-row-name time{font:9px 'IBM Plex Mono',monospace;color:#96a098;white-space:nowrap}.ui-source{display:flex;align-items:center;gap:5px;font-size:9px;color:#86938b;margin-top:3px}.ui-source svg{color:#6e8a78}.ui-row-subject{font-size:10px;font-weight:650;color:#4b5c53;margin:10px 0 3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ui-row-preview{font-size:10px;line-height:1.45;color:#8b9690;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ui-row-bottom{display:flex;align-items:center;justify-content:space-between;margin-top:9px}.ui-id{font:9px 'IBM Plex Mono',monospace;color:#a0aaa3}.ui-status{display:inline-flex;align-items:center;gap:5px;border-radius:20px;padding:4px 7px;font-size:8px;font-weight:700;white-space:nowrap}.ui-status:before{content:'';width:5px;height:5px;border-radius:50%;background:currentColor}.ui-status.open,.ui-status.queued{background:#f7f0df;color:#95743b}.ui-status.uncertain{background:#f8e9e4;color:#a25c46}.ui-status.replied,.ui-status.progress{background:#e7f1e8;color:#3c7659}.ui-status.closed{background:#eef0ec;color:#78827b}
      .ui-detail{min-width:0;display:flex;flex-direction:column}.ui-detail-head{padding:16px 20px 13px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:flex-start;gap:14px}.ui-person{display:flex;align-items:center;gap:11px;min-width:0}.ui-person-avatar{width:39px;height:39px;border-radius:12px;background:#e9efe8;color:#40654f;display:grid;place-items:center;font:700 12px Manrope,sans-serif;flex:none}.ui-person h2{font:700 15px Manrope,sans-serif;letter-spacing:-.025em;margin:0 0 5px}.ui-person-meta{display:flex;align-items:center;gap:7px;flex-wrap:wrap;color:#87948c;font-size:9px}.ui-detail-actions{display:flex;align-items:center;gap:6px;flex-wrap:wrap;justify-content:flex-end}.ui-btn{height:30px;display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:0 9px;border:1px solid #dfe5dd;border-radius:7px;background:#fffefa;color:#586b60;font-size:9px;font-weight:650}.ui-btn.primary{background:#2e6b55;border-color:#2e6b55;color:white}.ui-btn:hover{filter:brightness(.97)}.ui-icon-btn{width:30px;padding:0}
      .ui-contextbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:9px 20px;border-bottom:1px solid #eff1ec;background:#fbfcf9;color:#7c8a82;font-size:9px}.ui-contextbar span{display:inline-flex;align-items:center;gap:5px}.ui-contextbar strong{color:#4e6559;font-weight:650}.ui-contextbar .attention{color:#a36e43}
      .ui-thread{padding:20px;display:flex;flex-direction:column;gap:14px;min-height:278px;flex:1;overflow:auto;background:linear-gradient(180deg,#fffefa 0%,#fdfdfa 100%)}.ui-day{display:flex;align-items:center;gap:10px;color:#a0aaa3;font:9px 'IBM Plex Mono',monospace;letter-spacing:.04em}.ui-day:before,.ui-day:after{content:'';height:1px;background:#edf0ea;flex:1}.ui-message{max-width:min(78%,540px);border:1px solid #e6ebe3;background:#f5f7f3;border-radius:11px 11px 11px 3px;padding:10px 12px;align-self:flex-start}.ui-message.staff{align-self:flex-end;background:#eaf3ec;border-color:#dbe9dd;border-radius:11px 11px 3px 11px}.ui-msg-label{display:flex;align-items:center;justify-content:space-between;gap:12px;color:#829087;font-size:9px;font-weight:700}.ui-message.staff .ui-msg-label{color:#4a775d}.ui-message p{margin:6px 0 0;font-size:11px;line-height:1.6;color:#43584c;white-space:pre-wrap;overflow-wrap:anywhere}.ui-message time{font:9px 'IBM Plex Mono',monospace;color:#9aa59e}
      .ui-thread-foot{padding:11px 20px;border-top:1px solid #edf0e9;display:flex;justify-content:space-between;align-items:center;color:#8b9790;font-size:9px}.ui-reply{border-top:1px solid var(--line);padding:13px 18px 14px;background:#fffefa}.ui-replybox{border:1px solid #dfe6dd;border-radius:9px;background:#fff;padding:10px 11px}.ui-replybox textarea{display:block;width:100%;min-height:54px;border:0;outline:0;resize:vertical;background:transparent;color:#334b40;font-size:11px;line-height:1.5}.ui-replybox textarea::placeholder{color:#a4aea7}.ui-reply-controls{display:flex;align-items:center;justify-content:space-between;margin-top:8px}.ui-reply-hint{display:flex;align-items:center;gap:6px;color:#9aa49d;font-size:9px}.ui-send{border:0;border-radius:7px;background:#2c6953;color:white;padding:8px 11px;display:flex;align-items:center;gap:7px;font-size:10px;font-weight:700}.ui-compose-notice{display:flex;align-items:center;gap:6px;color:#718077;font-size:9px;margin:0 0 8px}.ui-footer{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:11px 15px;border-top:1px solid var(--line);background:#f8f9f5;color:#88958d;font-size:9px}.ui-footer strong{color:#596d60}.ui-toast{position:fixed;right:20px;bottom:20px;z-index:5;background:#244d45;color:#fff;padding:11px 14px;border-radius:9px;box-shadow:0 8px 22px #203c3728;font-size:11px}
      .ui-empty{padding:40px 18px;text-align:center;color:#87948c;font-size:11px}.ui-empty strong{display:block;color:#53685c;font-size:13px;margin:9px}
      @media(max-width:800px){.ui-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.ui-columns{grid-template-columns:minmax(235px,.85fr) minmax(0,1.2fr)}.ui-detail-head{padding:14px}.ui-contextbar{padding:9px 14px}.ui-thread{padding:15px}.ui-reply{padding:12px}.ui-detail-actions .hide-small{display:none}}
      @media(max-width:620px){.ui-top{height:58px;padding:0 14px}.ui-brand small{font-size:8px}.ui-top-right{gap:7px}.ui-sample{font-size:8px;padding:6px 8px}.ui-role{font-size:10px;max-width:105px}.ui-shell{padding:18px 12px 24px}.ui-heading{align-items:flex-start;flex-direction:column;gap:8px;margin-bottom:14px}.ui-ops{font-size:9px}.ui-metrics{gap:7px}.ui-metric{padding:10px}.ui-metric strong{font-size:20px}.ui-toolbar{align-items:flex-start;flex-direction:column;padding:9px}.ui-tabs{max-width:100%;overflow:auto;width:100%}.ui-tab{padding:7px}.ui-tool-actions{width:100%}.ui-search{width:auto;flex:1}.ui-filter{max-width:46%}.ui-columns{display:block;min-height:0}.ui-list{border-right:0}.ui-list-body{max-height:330px}.ui-detail{display:none;border-top:1px solid var(--line)}.ui-detail.mobile-show{display:flex}.ui-list.mobile-hide{display:none}.ui-row{padding:11px 12px}.ui-detail-head{padding:13px}.ui-person h2{font-size:14px}.ui-detail-actions .desktop-action{display:none}.ui-thread{min-height:250px;max-height:48vh}.ui-message{max-width:90%}.ui-footer{align-items:flex-start;flex-direction:column}.ui-back{display:inline-flex!important}}
      .ui-back{display:none}
    `}</style>
    <header className="ui-top">
      <div className="ui-brand"><span className="ui-mark"><MessageSquareText size={17}/></span><div><strong>Smart Money Hub</strong><small>PRIVATE SUPPORT WORKSPACE</small></div></div>
      <div className="ui-top-right"><span className="ui-sample"><i/>PROTOTYPE · SAMPLE DATA</span><span className="ui-role">Manager view · demo</span></div>
    </header>
    <main className="ui-shell">
      <div className="ui-heading"><div><div className="ui-eyebrow">SUPPORT / UNIFIED INBOX</div><h1>One place for support.</h1><p>Member cases and website conversations, together.</p></div><div className="ui-ops"><span><span className="ui-live"/>Demo workspace</span><span>·</span><span>Local prototype interactions</span></div></div>
      <section className="ui-metrics" aria-label="Sample inbox summary">
        <article className="ui-metric"><div><div className="ui-metric-label">Needs attention</div><strong>{countAttention}</strong></div><span className="ui-metric-icon"><Inbox size={16}/></span></article>
        <article className="ui-metric warn"><div><div className="ui-metric-label">Delivery uncertain</div><strong>{threads.filter((t) => t.status === "Reply uncertain").length}</strong></div><span className="ui-metric-icon"><CircleAlert size={16}/></span></article>
        <article className="ui-metric"><div><div className="ui-metric-label">Website chats</div><strong>{threads.filter((t) => t.source === "Website chat" && t.status !== "Closed").length}</strong></div><span className="ui-metric-icon"><MessageCircle size={16}/></span></article>
        <article className="ui-metric"><div><div className="ui-metric-label">Resolved today</div><strong>{threads.filter((t) => t.status === "Replied").length}</strong></div><span className="ui-metric-icon"><CheckCheck size={16}/></span></article>
      </section>
      <section className="ui-workspace">
        <div className="ui-toolbar">
          <nav className="ui-tabs" aria-label="Conversation filters">
            {["Needs attention", "All conversations", "Open", "Replied", "Closed"].map((tab) => <button key={tab} className={`ui-tab ${filter === tab ? "active" : ""}`} onClick={() => setFilter(tab)}>{tab}{tab === "Needs attention" && <b>{countAttention}</b>}</button>)}
          </nav>
          <div className="ui-tool-actions"><label className="ui-search"><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search inbox" aria-label="Search inbox"/></label>
            <select className="ui-filter" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} aria-label="Filter by source"><option>All sources</option><option>Telegram case</option><option>Website chat</option></select>
            <button className="ui-btn ui-icon-btn" aria-label="More filters" onClick={() => notice("Status and source filters are available in this prototype.")}><SlidersHorizontal size={14}/></button>
          </div>
        </div>
        <div className="ui-columns">
          <div className={`ui-list ${mobileDetail ? "mobile-hide" : ""}`}>
            <div className="ui-list-head"><span>Conversation</span><span>{visible.length} shown</span></div>
            <div className="ui-list-body">
              {visible.length ? visible.map((thread) => <button key={thread.id} className={`ui-row ${thread.id === selected.id ? "selected" : ""}`} onClick={() => selectThread(thread.id)}>
                <div className="ui-row-top"><span className="ui-avatar">{thread.initials}</span><span className="ui-row-main"><span className="ui-row-name"><strong>{thread.name}</strong><time>{thread.time}</time></span><span className="ui-source">{thread.source === "Telegram case" ? <ArrowDownLeft size={11}/> : <MessageCircle size={11}/>} {thread.source}</span></span></div>
                <div className="ui-row-subject">{thread.subject}</div><div className="ui-row-preview">{thread.preview}</div>
                <div className="ui-row-bottom"><span className="ui-id">{thread.id} · {thread.assigned}</span><span className={`ui-status ${statusClass[thread.status]}`}>{thread.status}</span></div>
              </button>) : <div className="ui-empty"><Search size={20}/><strong>No matching conversations</strong>Try another search or filter.</div>}
            </div>
          </div>
          <div className={`ui-detail ${mobileDetail ? "mobile-show" : ""}`}>
            <div className="ui-detail-head">
              <div className="ui-person"><button className="ui-btn ui-icon-btn ui-back" onClick={() => setMobileDetail(false)} aria-label="Back to inbox"><ArrowDownLeft size={15}/></button><span className="ui-person-avatar">{selected.initials}</span><div><h2>{selected.name}</h2><div className="ui-person-meta"><span>{selected.source}</span><span>·</span><span>{selected.id}</span><span>·</span><span className={`ui-status ${statusClass[selected.status]}`}>{selected.status}</span></div></div></div>
              <div className="ui-detail-actions">
                {managerControls && selected.status !== "Closed" && <label title="Manager and Owner demo control"><select className="ui-btn desktop-action" value={selected.assigned} onChange={(event) => { patchSelected({ assigned: event.target.value }); notice(`Sample assignment set to ${event.target.value}.`); }} aria-label="Assign conversation"><option>Unassigned</option><option>Avery Cole</option><option>Sam Rivera</option><option>Jordan Lee</option></select></label>}
                {selected.status !== "Closed" && <button className="ui-btn desktop-action" onClick={() => { patchSelected({ status: selected.source === "Website chat" ? "Closed" : "Closed" }); notice("Sample conversation marked closed."); }}><Check size={13}/> Close</button>}
                {managerControls && <button className="ui-btn ui-icon-btn" aria-label="More conversation actions" onClick={() => notice("Manager / Owner controls are demo-only.")}><MoreHorizontal size={15}/></button>}
              </div>
            </div>
            <div className="ui-contextbar"><span><UserRound size={12}/> Assigned: <strong>{selected.assigned}</strong></span><span><Clock3 size={12}/> Updated <strong>{selected.age} ago</strong></span><span className={selected.priority ? "attention" : ""}><ShieldCheck size={12}/><strong>{selected.priority ?? "Standard priority"}</strong></span></div>
            <div className="ui-thread" aria-live="polite">
              <div className="ui-day">CONVERSATION · SAMPLE</div>
              {selected.messages.map((message, index) => <article className={`ui-message ${message.from === "staff" ? "staff" : ""}`} key={`${selected.id}-${index}`}>
                <div className="ui-msg-label"><span>{message.from === "member" ? selected.name : "Support team"}</span><time>{message.time}</time></div><p>{message.text}</p>
              </article>)}
            </div>
            <div className="ui-thread-foot"><span><LockKeyhole size={12}/> Context visible to authorized staff in this sample</span><button className="ui-btn" onClick={() => notice("Conversation history is sample content only.")}><Activity size={12}/> History</button></div>
            <div className="ui-reply">
              <p className="ui-compose-notice"><Sparkles size={12}/> No AI connection · write and send a local demo reply</p>
              <div className="ui-replybox"><textarea value={reply} onChange={(event) => setReply(event.target.value)} placeholder={`Reply to ${selected.name}…`} aria-label="Write a prototype reply" onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) sendReply(); }}/>
                <div className="ui-reply-controls"><span className="ui-reply-hint"><Paperclip size={13}/> Attachments unavailable in prototype</span><button className="ui-send" onClick={sendReply} disabled={!reply.trim()}><Send size={13}/> Send demo reply</button></div>
              </div>
            </div>
          </div>
        </div>
        <footer className="ui-footer"><span><strong>Prototype / sample data.</strong> Fictional conversations; no live backend, member records, or AI connection.</span><span>Role shown: <strong>{role}</strong>{managerControls ? " · assignment controls are local demo interactions" : " · Agent permissions only"}</span></footer>
      </section>
      {toast && <div role="status" className="ui-toast">{toast}</div>}
    </main>
  </div>;
}
