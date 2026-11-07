import './_group.css';
import { Activity, CircleAlert, CircleHelp, Database, FileText, Gauge, MessageSquareText, Radio, RefreshCw, ShieldCheck } from 'lucide-react';

const metrics = [
  ['Open support cases', '0', MessageSquareText],
  ['Uncertain replies', '0', CircleHelp],
  ['Overdue tasks', '0', CircleAlert],
  ['Recorded trades', '0', Activity],
  ['Trade events', '0', Activity],
  ['Unresolved publishing', '0', Radio],
  ['PRO awaiting final review', '0', ShieldCheck],
  ['PRO evidence requested', '0', FileText],
  ['PRO applications 7+ days', '0', CircleAlert],
] as const;

const statusRows = [
  ['Private test bot process', 'Unknown'],
  ['Bot health check', 'Unknown'],
  ['Telegram API', 'Unknown'],
  ['Database', 'Unknown'],
  ['Polling loop', 'Unknown'],
  ['Test publishing setting', 'Unknown'],
  ['Replit workflow control panel', 'Unknown'],
];

export function Current() {
  return <main className="owner-current">
    <div className="kicker"><span className="kicker-mark"><Gauge size={15}/></span><span>OWNER VIEW</span><i/>DEVELOPMENT · READ ONLY</div>
    <div className="heading">
      <div><div className="eyebrow">OPERATIONAL VISIBILITY</div><h1>Command center</h1><p className="subheading">A careful read of stored test records — not a live bot monitor.</p></div>
      <div className="actions"><button className="button"><ShieldCheck size={14}/>PRO access review</button><button className="button"><FileText size={14}/>Education videos</button><button className="button"><RefreshCw size={14}/>Refresh</button></div>
    </div>
    <section className="scope"><span className="scope-icon"><Database size={18}/></span><div><strong>Isolated Development data</strong><p>This view reads stored Development test data only. Production data is not connected.</p></div><span className="readonly">READ ONLY</span></section>
    <section className="metrics" aria-label="Stored data overview">{metrics.map(([label,value,Icon])=><article className="metric" key={label}><div className="metric-label"><span>{label}</span><span className="metric-icon"><Icon size={16}/></span></div><strong>{value}</strong><small>stored records</small></article>)}</section>
    <section className="panel live">
      <div className="panel-head"><div><div className="eyebrow">PRIVATE TEST BOT</div><h2>Live health status</h2></div><span className="count">Waiting for heartbeat</span></div>
      <p className="caveat">No recent isolated test-bot heartbeat is available. Health refreshes automatically every 30 seconds. Production is not connected.</p>
      <div className="rows">{statusRows.map(([label,value])=><div className="row" key={label}><span>?</span><span>{label}</span><strong>{value}</strong></div>)}<div className="row"><span>◷</span><span>Last health check</span><strong>Not yet</strong></div></div>
      <p className="caveat">The publishing row is the test configuration flag, not proof that a message was published. Channel access remains Unknown unless checked separately.</p>
    </section>
    <section className="panel">
      <div className="panel-head"><div><div className="eyebrow">BOT RECORDS</div><h2>Configured sources</h2><p>Production remains disconnected; test-bot health comes from its recent isolated heartbeat.</p></div><span className="count">2 sources</span></div>
      <div className="source-row"><span className="source-mark"><Radio size={17}/></span><div className="source-copy"><strong>Production bot</strong><span>Last recorded Telegram update · Not yet</span></div><div className="source-values"><span><small>Health</small><b>Unknown</b></span><span><small>Bot process</small><b>Not connected</b></span><span><small>Publishing setting</small><b>Unknown</b></span></div></div>
      <div className="source-row"><span className="source-mark"><Radio size={17}/></span><div className="source-copy"><strong>Private test bot</strong><span>Last recorded Telegram update · Not yet</span></div><div className="source-values"><span><small>Health</small><b>Unknown</b></span><span><small>Bot process</small><b>Unknown</b></span><span><small>Publishing setting</small><b>Unknown</b></span></div></div>
    </section>
    <p className="footer"><strong>Current reference · static UI preview.</strong> The live page reads stored Development test data. A Telegram message accepted is not proof of a broker order, execution, or profit.</p>
  </main>;
}
