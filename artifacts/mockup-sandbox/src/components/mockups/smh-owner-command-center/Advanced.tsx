import './_group.css';
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  Bot,
  Building2,
  Check,
  CircleAlert,
  CircleHelp,
  Clock3,
  Database,
  FileText,
  Gauge,
  LockKeyhole,
  MessageSquareText,
  Radio,
  RefreshCw,
  ShieldCheck,
  Signal,
  Workflow,
} from 'lucide-react';

const metrics = [
  { label: 'Open support cases', value: '0', icon: MessageSquareText, note: 'stored records', tone: 'teal' },
  { label: 'Uncertain replies', value: '0', icon: CircleHelp, note: 'stored records', tone: 'amber' },
  { label: 'Overdue tasks', value: '0', icon: CircleAlert, note: 'stored records', tone: 'coral' },
  { label: 'Recorded trades', value: '0', icon: Activity, note: 'stored records', tone: 'teal' },
  { label: 'Trade events', value: '0', icon: Signal, note: 'stored records', tone: 'slate' },
  { label: 'Unresolved publishing', value: '0', icon: Radio, note: 'stored records', tone: 'amber' },
  { label: 'PRO awaiting final review', value: '0', icon: ShieldCheck, note: 'stored records', tone: 'teal' },
  { label: 'PRO evidence requested', value: '0', icon: FileText, note: 'stored records', tone: 'amber' },
  { label: 'PRO applications 7+ days', value: '0', icon: Clock3, note: 'stored records', tone: 'coral' },
] as const;

const healthRows = [
  ['Private test bot process', 'Not recorded'],
  ['Bot health check', 'Not recorded'],
  ['Telegram API', 'Not recorded'],
  ['Database', 'Not recorded'],
  ['Polling loop', 'Not recorded'],
  ['Test publishing setting', 'Not recorded'],
  ['Replit workflow control panel', 'Not recorded'],
] as const;

const sources = [
  {
    name: 'Production bot',
    badge: 'DISCONNECTED',
    note: 'Production telemetry is not available in this workspace.',
    values: [['Health', 'Not connected'], ['Process', 'Not connected'], ['Publishing', 'Not connected']],
    style: 'production',
  },
  {
    name: 'Private test bot',
    badge: 'DEVELOPMENT',
    note: 'No isolated heartbeat or status snapshot has been recorded.',
    values: [['Health', 'Not recorded'], ['Process', 'Not recorded'], ['Publishing', 'Not recorded']],
    style: 'test',
  },
] as const;

export function Advanced() {
  return (
    <main className="owner-advanced">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
        .owner-advanced{--oa-ink:#203b38;--oa-muted:#748680;--oa-line:#dfe7df;--oa-paper:#f3f6ef;--oa-card:#fbfcf8;--oa-teal:#397e72;--oa-gold:#9a7640;min-height:100vh;padding:24px clamp(14px,3vw,40px) 40px;color:var(--oa-ink);background:radial-gradient(ellipse at 92% 0%,#e2eee6 0,transparent 34%),var(--oa-paper);font:400 13px/1.5 'DM Sans',sans-serif;position:relative;overflow:hidden}
        .owner-advanced *{box-sizing:border-box}.owner-advanced:before{content:'';position:fixed;inset:0;pointer-events:none;opacity:.18;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.12'/%3E%3C/svg%3E")}
        .owner-advanced h1,.owner-advanced h2,.owner-advanced h3,.owner-advanced p{margin-top:0}.oa-shell{max-width:1480px;margin:0 auto;position:relative}.oa-topbar{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:2px 0 20px;border-bottom:1px solid #d9e2d9}
        .oa-brand{display:flex;align-items:center;gap:11px}.oa-brand-mark{display:grid;place-items:center;width:36px;height:36px;border-radius:10px;background:#dcebe1;color:#347469}.oa-brand-copy{display:grid;line-height:1.2}.oa-brand-copy strong{font:800 12px Manrope,sans-serif;letter-spacing:-.03em}.oa-brand-copy span{margin-top:4px;color:#84918a;font:500 8px 'DM Mono',monospace;letter-spacing:.11em;text-transform:uppercase}
        .oa-top-meta{display:flex;align-items:center;gap:12px}.oa-prototype{display:flex;align-items:center;gap:7px;padding:6px 9px;border:1px solid #d6c99f;border-radius:5px;background:#f8f2df;color:#826b3f;font:500 8px 'DM Mono',monospace;letter-spacing:.1em}.oa-prototype i{width:6px;height:6px;border-radius:50%;background:#b28e4e}.oa-owner{display:flex;align-items:center;gap:8px;padding-left:12px;border-left:1px solid #d9e2d9;color:#53645c;font-size:10px}.oa-avatar{width:27px;height:27px;border:1px solid #cbd9ce;border-radius:50%;display:grid;place-items:center;background:#e7efe8;color:#517767;font:500 9px 'DM Mono',monospace}
        .oa-layout{display:grid;grid-template-columns:190px minmax(0,1fr);gap:30px;padding-top:27px}.oa-rail{padding:6px 0}.oa-rail-label,.oa-eyebrow{color:#819088;font:500 8px 'DM Mono',monospace;letter-spacing:.13em;text-transform:uppercase}.oa-rail-nav{display:grid;gap:4px;margin-top:12px}.oa-rail-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:7px;color:#718079;font-size:10px}.oa-rail-item.selected{background:#e4eee5;color:#356a5f;font-weight:700}.oa-rail-item svg{flex:none}.oa-rail-item em{margin-left:auto;font:500 8px 'DM Mono',monospace;color:#9caaa1;font-style:normal}.oa-rail-rule{height:1px;background:#dce4dc;margin:18px 5px}.oa-rail-note{padding:12px 11px;border:1px solid #dce5dc;border-radius:8px;background:#f8faf5}.oa-rail-note strong{display:block;font-size:9px;color:#536b5f}.oa-rail-note p{margin:6px 0 0;color:#84918a;font-size:9px;line-height:1.55}
        .oa-main{min-width:0}.oa-crumb{display:flex;align-items:center;gap:8px;color:#83918a;font:500 8px 'DM Mono',monospace;letter-spacing:.09em;text-transform:uppercase}.oa-crumb b{color:#436f64;font-weight:500}.oa-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin:10px 0 20px}.oa-heading h1{margin:5px 0 5px;font:700 clamp(28px,3vw,38px)/1.1 Manrope,sans-serif;letter-spacing:-.055em;color:#203b38}.oa-heading p{margin:0;color:#7b8981;font-size:11px}.oa-heading-right{display:grid;justify-items:end;gap:8px}.oa-readonly{display:flex;align-items:center;gap:6px;padding:6px 9px;border:1px solid #d9e3d9;border-radius:5px;background:#f9fbf6;color:#718278;font:500 8px 'DM Mono',monospace;letter-spacing:.08em;white-space:nowrap}.oa-actions{display:flex;gap:7px}.oa-action{display:inline-flex;align-items:center;gap:7px;padding:8px 10px;border:1px solid #d8e1d9;border-radius:6px;background:#f8faf6;color:#73827a;font-size:9px;white-space:nowrap;cursor:default}.oa-action.primary{border-color:#bdd2c6;background:#e7f0e8;color:#456f60}
        .oa-scope{display:flex;align-items:center;gap:12px;padding:12px 15px;margin-bottom:14px;border:1px solid #cbded1;border-radius:9px;background:linear-gradient(100deg,#e7f1e8,#f1f6ec)}.oa-scope-mark{width:33px;height:33px;display:grid;place-items:center;flex:none;border-radius:8px;background:#d3e6d8;color:#367368}.oa-scope-copy{min-width:0}.oa-scope-copy strong{display:block;color:#355b4f;font-size:10px}.oa-scope-copy p{margin:3px 0 0;color:#75877b;font-size:9px}.oa-scope-tag{margin-left:auto;display:flex;align-items:center;gap:6px;color:#63806e;font:500 8px 'DM Mono',monospace;letter-spacing:.08em;white-space:nowrap}.oa-scope-tag:before{content:'';width:5px;height:5px;background:#6f9a7b;border-radius:50%}
        .oa-summary{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(230px,.8fr);gap:12px;margin-bottom:12px}.oa-snapshot,.oa-guardrail{border:1px solid var(--oa-line);border-radius:9px;background:var(--oa-card)}.oa-snapshot{padding:15px 16px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:5px 12px}.oa-snapshot .oa-eyebrow{grid-column:1/-1}.oa-snapshot strong{font:700 21px Manrope,sans-serif;letter-spacing:-.04em;color:#315c50}.oa-snapshot strong span{font:500 10px 'DM Mono',monospace;color:#89968d;letter-spacing:0}.oa-snapshot small{color:#88948c;font-size:9px}.oa-snapshot-badge{grid-column:2;grid-row:2/4;display:grid;place-items:center;width:48px;height:48px;border:1px solid #e4e9df;border-radius:50%;color:#91a298}.oa-guardrail{padding:13px 15px;display:flex;align-items:flex-start;gap:10px;background:#f9f7ef;border-color:#e7e0cf}.oa-guardrail svg{flex:none;color:#9a7e4e;margin-top:1px}.oa-guardrail strong{display:block;color:#6f6042;font-size:9px}.oa-guardrail p{margin:4px 0 0;color:#89836f;font-size:9px;line-height:1.5}
        .oa-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:14px}.oa-metric{position:relative;min-height:97px;padding:12px 13px;border:1px solid #e0e7df;border-radius:8px;background:#fbfcf8;transition:transform .2s ease,box-shadow .2s ease}.oa-metric:hover{transform:translateY(-2px);box-shadow:0 8px 18px #345d4c0d}.oa-metric-head{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;color:#78867e;font-size:9px;line-height:1.3}.oa-metric-head span:first-child{max-width:140px}.oa-metric-icon{display:grid;place-items:center;width:25px;height:25px;border-radius:7px;background:#e5f0e7;color:#438074;flex:none}.oa-metric.tone-amber .oa-metric-icon{background:#f4eedf;color:#9c7c47}.oa-metric.tone-coral .oa-metric-icon{background:#f5eae4;color:#aa705e}.oa-metric.tone-slate .oa-metric-icon{background:#e9eeeb;color:#77867e}.oa-metric strong{display:block;margin-top:7px;font:700 22px Manrope,sans-serif;letter-spacing:-.045em;color:#28453e}.oa-metric small{color:#9aa39b;font:400 8px 'DM Mono',monospace}
        .oa-section{margin-top:12px;border:1px solid #dfe6de;border-radius:9px;background:#fbfcf8;overflow:hidden}.oa-section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 16px;border-bottom:1px solid #e9eee7}.oa-section-title{display:flex;align-items:flex-start;gap:10px}.oa-section-icon{width:28px;height:28px;display:grid;place-items:center;border-radius:7px;background:#e7eee7;color:#557b6e;flex:none}.oa-section-head h2{margin:3px 0 0;font:700 13px Manrope,sans-serif;letter-spacing:-.025em;color:#2d4a41}.oa-section-head p{margin:3px 0 0;color:#89948c;font-size:9px}.oa-section-state{padding:5px 8px;border:1px solid #e8dfcb;border-radius:5px;background:#f8f3e8;color:#8e7548;font:500 8px 'DM Mono',monospace;white-space:nowrap}.oa-health-content{padding:12px 15px 13px}.oa-health-callout{display:flex;align-items:flex-start;gap:8px;padding:9px 10px;margin-bottom:9px;border-left:2px solid #c9ae79;background:#f8f4e9;color:#7e755e;font-size:9px}.oa-health-callout svg{flex:none;margin-top:1px;color:#a18450}.oa-health-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.oa-health-row{display:grid;grid-template-columns:19px minmax(0,1fr) auto;align-items:center;gap:8px;min-height:35px;padding:6px 9px;border:1px solid #ebeee6;border-radius:6px;background:#fdfdf9;color:#63736a;font-size:9px}.oa-status-dot{width:17px;height:17px;display:grid;place-items:center;border-radius:50%;background:#f1eee5;color:#987d4c}.oa-health-row strong{color:#927a4d;font:500 8px 'DM Mono',monospace;text-align:right}.oa-health-foot{margin:9px 0 0;color:#919b92;font-size:8px;line-height:1.5}
        .oa-source-list{display:grid}.oa-source{display:grid;grid-template-columns:34px minmax(150px,1.15fr) minmax(0,2fr);align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid #edf0e9}.oa-source:last-child{border-bottom:0}.oa-source-mark{width:31px;height:31px;display:grid;place-items:center;border-radius:8px;background:#e9efea;color:#688174}.oa-source.production .oa-source-mark{background:#f0eee8;color:#8e846a}.oa-source-main{min-width:0}.oa-source-main strong{display:block;color:#435a4e;font-size:10px}.oa-source-main span{display:block;margin-top:3px;color:#949d94;font-size:8px}.oa-source-pill{display:inline-block!important;width:max-content;margin-top:5px!important;padding:3px 5px;border:1px solid #e5e9e0;border-radius:4px;color:#7d8a81!important;font:500 7px 'DM Mono',monospace;letter-spacing:.06em}.oa-source.production .oa-source-pill{border-color:#e8dfcb;background:#f8f4e9;color:#8d754a!important}.oa-source-values{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.oa-source-values span{display:grid;gap:4px;min-width:0}.oa-source-values small{color:#929c93;font-size:8px}.oa-source-values b{color:#78867d;font:500 8px 'DM Mono',monospace;overflow-wrap:anywhere}
        .oa-records{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;padding:12px 15px}.oa-record{min-height:89px;padding:11px;border:1px solid #e9ede5;border-radius:7px;background:#fdfdf9}.oa-record-top{display:flex;align-items:center;justify-content:space-between;color:#819087;font-size:8px}.oa-record-top svg{color:#8a9a8e}.oa-record strong{display:block;margin-top:9px;color:#718078;font:500 9px 'DM Mono',monospace}.oa-record small{display:block;margin-top:3px;color:#a0a89f;font-size:8px}
        .oa-foot{display:grid;grid-template-columns:22px 1fr auto;align-items:start;gap:10px;margin-top:12px;padding:12px 14px;border:1px solid #dfe5d9;border-radius:8px;background:#ebf0e7}.oa-foot-icon{width:20px;height:20px;display:grid;place-items:center;border-radius:50%;background:#dce5d7;color:#657a68}.oa-foot p{margin:0;color:#77847a;font-size:8px;line-height:1.55}.oa-foot p strong{color:#526b5a}.oa-foot>span:last-child{color:#8c978d;font:500 7px 'DM Mono',monospace;text-align:right;white-space:nowrap}.oa-end{display:flex;justify-content:space-between;gap:12px;margin:12px 2px 0;color:#98a198;font:500 7px 'DM Mono',monospace;letter-spacing:.05em}
        @media(max-width:900px){.oa-layout{grid-template-columns:1fr;gap:12px}.oa-rail{display:flex;align-items:center;gap:10px;padding:0;overflow:auto}.oa-rail-label,.oa-rail-rule,.oa-rail-note{display:none}.oa-rail-nav{display:flex;gap:4px;margin:0;min-width:max-content}.oa-rail-item{padding:8px}.oa-rail-item em{display:none}.oa-summary{grid-template-columns:1.2fr 1fr}}
        @media(max-width:620px){.owner-advanced{padding:14px 13px 28px}.oa-topbar{padding-bottom:14px}.oa-brand-mark{width:32px;height:32px}.oa-brand-copy strong{font-size:10px}.oa-owner>span:last-child{display:none}.oa-owner{padding-left:8px}.oa-prototype{font-size:7px;padding:5px 6px}.oa-layout{padding-top:16px}.oa-heading{align-items:flex-start;flex-direction:column;margin:12px 0 14px;gap:12px}.oa-heading h1{font-size:30px}.oa-heading-right{justify-items:start;grid-template-columns:auto 1fr;align-items:center;width:100%}.oa-actions{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;width:100%}.oa-action{justify-content:center;padding:9px 7px;font-size:8px}.oa-readonly{justify-self:start}.oa-scope{align-items:flex-start;padding:11px;gap:9px}.oa-scope-copy p{font-size:8px}.oa-scope-tag{font-size:7px;align-self:center}.oa-summary{grid-template-columns:1fr;gap:8px}.oa-snapshot{min-height:90px}.oa-metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.oa-metric{min-height:88px;padding:10px}.oa-metric-head{font-size:8px}.oa-metric-head span:first-child{max-width:100px}.oa-metric strong{font-size:21px}.oa-section-head{padding:12px}.oa-section-head p{max-width:210px;line-height:1.45}.oa-section-state{font-size:7px;padding:5px 6px}.oa-health-content{padding:10px}.oa-health-grid{grid-template-columns:1fr}.oa-health-row{min-height:34px}.oa-health-callout{font-size:8px}.oa-source{grid-template-columns:29px minmax(0,1fr);gap:8px;padding:11px}.oa-source-mark{width:28px;height:28px}.oa-source-main{align-self:center}.oa-source-values{grid-column:2;gap:5px;padding-top:2px}.oa-source-values small{font-size:7px}.oa-source-values b{font-size:7px}.oa-records{grid-template-columns:1fr;padding:10px;gap:7px}.oa-record{min-height:68px}.oa-record strong{margin-top:6px}.oa-foot{grid-template-columns:20px 1fr;gap:8px;padding:11px}.oa-foot>span:last-child{grid-column:2;text-align:left;white-space:normal}.oa-end{flex-direction:column;gap:4px;font-size:6px}}
        @media(prefers-reduced-motion:reduce){.oa-metric{transition:none}.oa-metric:hover{transform:none}}
      `}</style>
      <div className="oa-shell">
        <header className="oa-topbar">
          <div className="oa-brand">
            <span className="oa-brand-mark"><Gauge size={17}/></span>
            <span className="oa-brand-copy"><strong>SMART MONEY HUB</strong><span>Owner operations</span></span>
          </div>
          <div className="oa-top-meta">
            <span className="oa-prototype"><i/>VISUAL PROTOTYPE</span>
            <span className="oa-owner"><span className="oa-avatar">OW</span><span>Owner workspace</span></span>
          </div>
        </header>

        <div className="oa-layout">
          <aside className="oa-rail" aria-label="Workspace sections">
            <span className="oa-rail-label">Workspace</span>
            <nav className="oa-rail-nav">
              <span className="oa-rail-item selected"><Gauge size={14}/>Command center<em>01</em></span>
              <span className="oa-rail-item"><ShieldCheck size={14}/>PRO access<em>02</em></span>
              <span className="oa-rail-item"><MessageSquareText size={14}/>Support<em>03</em></span>
              <span className="oa-rail-item"><Workflow size={14}/>Publishing<em>04</em></span>
              <span className="oa-rail-item"><Database size={14}/>Data scope<em>05</em></span>
            </nav>
            <div className="oa-rail-rule"/>
            <div className="oa-rail-note"><strong>Safe by default</strong><p>Read-only view. No credentials, member identifiers, or private case content are shown.</p></div>
          </aside>

          <div className="oa-main">
            <div className="oa-crumb"><span>Operations</span><span>/</span><b>Command center</b></div>
            <div className="oa-heading">
              <div><div className="oa-eyebrow">OPERATIONAL VISIBILITY · OWNER VIEW</div><h1>Command center</h1><p>Stored Development records, presented with their limits intact.</p></div>
              <div className="oa-heading-right">
                <span className="oa-readonly"><LockKeyhole size={12}/>DEVELOPMENT · READ ONLY</span>
                <div className="oa-actions">
                  <span className="oa-action primary" aria-label="Prototype control: PRO access review"><ShieldCheck size={13}/>PRO access review</span>
                  <span className="oa-action" aria-label="Prototype control: education videos"><FileText size={13}/>Education videos</span>
                  <span className="oa-action" aria-label="Prototype control: refresh"><RefreshCw size={13}/>Refresh snapshot</span>
                </div>
              </div>
            </div>

            <section className="oa-scope" aria-label="Data scope">
              <span className="oa-scope-mark"><Database size={17}/></span>
              <div className="oa-scope-copy"><strong>Isolated Development data</strong><p>This prototype reflects stored Development test data only. Production data and telemetry are not connected.</p></div>
              <span className="oa-scope-tag">READ ONLY SCOPE</span>
            </section>

            <div className="oa-summary">
              <section className="oa-snapshot">
                <span className="oa-eyebrow">STORED SNAPSHOT</span>
                <strong>Not recorded <span>· no timestamp</span></strong>
                <small>No freshness claim is available in this static prototype.</small>
                <span className="oa-snapshot-badge"><Clock3 size={19}/></span>
              </section>
              <section className="oa-guardrail">
                <Bell size={15}/>
                <div><strong>Context before confidence</strong><p>An empty record is not a healthy check. Unknown stays unknown until a check is recorded.</p></div>
              </section>
            </div>

            <section className="oa-metrics" aria-label="Stored data overview">
              {metrics.map(({ label, value, icon: Icon, note, tone }) => (
                <article className={`oa-metric tone-${tone}`} key={label}>
                  <div className="oa-metric-head"><span>{label}</span><span className="oa-metric-icon"><Icon size={14}/></span></div>
                  <strong>{value}</strong><small>{note}</small>
                </article>
              ))}
            </section>

            <section className="oa-section">
              <div className="oa-section-head">
                <div className="oa-section-title"><span className="oa-section-icon"><Bot size={15}/></span><div><div className="oa-eyebrow">PRIVATE TEST BOT · DEVELOPMENT</div><h2>Health evidence</h2><p>No heartbeat available; status fields remain unverified.</p></div></div>
                <span className="oa-section-state">NO HEARTBEAT</span>
              </div>
              <div className="oa-health-content">
                <div className="oa-health-callout"><CircleAlert size={13}/><span>Health refresh is not active in this visual prototype. No live check has been run.</span></div>
                <div className="oa-health-grid">
                  {healthRows.map(([label, value]) => <div className="oa-health-row" key={label}><span className="oa-status-dot"><CircleHelp size={10}/></span><span>{label}</span><strong>{value}</strong></div>)}
                  <div className="oa-health-row"><span className="oa-status-dot"><Clock3 size={10}/></span><span>Last health check</span><strong>Not recorded</strong></div>
                </div>
                <p className="oa-health-foot">Publishing configuration is not evidence that a message was published. Channel access remains unverified unless checked separately.</p>
              </div>
            </section>

            <section className="oa-section">
              <div className="oa-section-head">
                <div className="oa-section-title"><span className="oa-section-icon"><Radio size={15}/></span><div><div className="oa-eyebrow">BOT RECORDS</div><h2>Configured sources</h2><p>Separate instance boundaries; no shared status inference.</p></div></div>
                <span className="oa-section-state">2 SOURCES</span>
              </div>
              <div className="oa-source-list">
                {sources.map((source) => <article className={`oa-source ${source.style}`} key={source.name}>
                  <span className="oa-source-mark">{source.style === 'production' ? <Building2 size={15}/> : <Bot size={15}/>}</span>
                  <div className="oa-source-main"><strong>{source.name}</strong><span>{source.note}</span><span className="oa-source-pill">{source.badge}</span></div>
                  <div className="oa-source-values">{source.values.map(([label, value]) => <span key={label}><small>{label}</small><b>{value}</b></span>)}</div>
                </article>)}
              </div>
            </section>

            <section className="oa-section">
              <div className="oa-section-head">
                <div className="oa-section-title"><span className="oa-section-icon"><Activity size={15}/></span><div><div className="oa-eyebrow">RECORD AVAILABILITY</div><h2>Operational records</h2><p>Absence of records does not confirm that an operation is healthy.</p></div></div>
                <span className="oa-section-state">NOT RECORDED</span>
              </div>
              <div className="oa-records">
                <article className="oa-record"><div className="oa-record-top"><span>Destination activity</span><Radio size={13}/></div><strong>No channel records</strong><small>Latest activity not recorded</small></article>
                <article className="oa-record"><div className="oa-record-top"><span>Publishing operations</span><ArrowUpRight size={13}/></div><strong>No operation records</strong><small>Telegram acceptance not recorded</small></article>
                <article className="oa-record"><div className="oa-record-top"><span>Error summaries</span><ArrowDownRight size={13}/></div><strong>No summaries recorded</strong><small>Not a confirmation of zero errors</small></article>
              </div>
            </section>

            <footer className="oa-foot">
              <span className="oa-foot-icon"><Check size={12}/></span>
              <p><strong>Interpret with care.</strong> This visual prototype does not connect to live systems. Stored Development test data only; Production is disconnected. A Telegram message accepted is not proof of a broker order, execution, or profit.</p>
              <span>PRIVATE OWNER WORKSPACE · PROTOTYPE</span>
            </footer>
            <div className="oa-end"><span>SMART MONEY HUB / OPERATIONS</span><span>SAFE ACCESS · ACCURATE CONTEXT · READ ONLY</span></div>
          </div>
        </div>
      </div>
    </main>
  );
}
