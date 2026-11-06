import { useRef, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  useHealthCheck,
  getHealthCheckQueryKey,
  useGetPortalCommandCenter,
  getGetPortalCommandCenterQueryKey,
} from '@workspace/api-client-react';
import { Link, Route, Switch, useLocation, Router as WouterRouter } from 'wouter';
import {
  Activity, AlertCircle, Bot, BrainCircuit, CalendarClock, Check, ChevronRight, MessageCircle,
  CircleHelp, Clock3, Command, Database, FileClock, FileText, Gauge,
  LayoutDashboard, Link2, Menu, RefreshCw, RotateCcw, RotateCw, Send, Server, ShieldCheck, Signal, X,
} from 'lucide-react';
import SupportPage from './SupportPage';

const queryClient = new QueryClient();
type ViewPath = '/operations' | '/activity' | '/content' | '/connections' | '/support';

const navigation: { href: ViewPath; label: string; icon: typeof LayoutDashboard; index: string }[] = [
  { href: '/operations', label: 'Overview', icon: LayoutDashboard, index: '01' },
  { href: '/activity', label: 'Activity stream', icon: Activity, index: '02' },
  { href: '/content', label: 'Content operations', icon: FileText, index: '03' },
  { href: '/connections', label: 'Connections', icon: Link2, index: '04' },
  { href: '/support', label: 'Support cases', icon: MessageCircle, index: '05' },
];

function HealthQuery() {
  const query = useHealthCheck({
    query: { queryKey: getHealthCheckQueryKey(), refetchInterval: 15000 },
  });
  const [retrying, setRetrying] = useState(false);
  const refresh = async () => {
    setRetrying(true);
    await query.refetch();
    setRetrying(false);
  };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2" data-testid="health-api-state">
      <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-semibold tracking-wide ${query.isError ? 'border-rose-300/20 bg-rose-300/[.07] text-rose-200' : query.data ? 'border-emerald-300/20 bg-emerald-300/[.07] text-emerald-200' : 'border-white/10 bg-white/[.035] text-slate-300'}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${query.isError ? 'bg-rose-300' : query.data ? 'pulse-dot bg-emerald-300' : 'bg-slate-500'}`} />
        {query.isLoading ? 'CHECKING API' : query.isError ? 'API UNAVAILABLE' : query.data ? 'API RESPONDING' : 'API STATUS UNKNOWN'}
      </span>
      {query.data && <span className="mono text-[10px] text-slate-500" data-testid="text-health-response">response · {query.data.status}</span>}
      {query.isError && <span className="text-[11px] text-slate-400" role="status">Health endpoint did not respond.</span>}
      <button type="button" onClick={refresh} disabled={retrying || query.isFetching} className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-[11px] text-slate-400 transition hover:text-emerald-200 disabled:opacity-50" aria-label="Refresh API health" data-testid="button-refresh-health">
        <RefreshCw size={12} className={retrying || query.isFetching ? 'animate-spin' : ''} /> Refresh
      </button>
    </div>
  );
}

function Sidebar({ mobileOpen, close }: { mobileOpen: boolean; close: () => void }) {
  const [location] = useLocation();
  return (
    <>
      {mobileOpen && <button aria-label="Close navigation overlay" onClick={close} className="fixed inset-0 z-30 bg-black/60 md:hidden" />}
      <aside className={`fixed inset-y-0 left-0 z-40 flex w-[258px] flex-col border-r border-white/[.075] bg-[#0b1017] px-5 py-6 transition-transform md:sticky md:top-0 md:h-screen md:translate-x-0 ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="mb-11 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="relative grid h-10 w-10 place-items-center rounded-xl border border-emerald-300/25 bg-emerald-300/[.08] text-emerald-200">
              <Command size={19} strokeWidth={1.7} />
              <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-[#0b1017] bg-cyan-300" />
            </div>
            <div>
              <div className="display text-[14px] font-bold tracking-tight text-slate-100">SMART MONEY</div>
              <div className="mono mt-0.5 text-[9px] tracking-[.2em] text-slate-500">HUB / OPERATIONS</div>
            </div>
          </div>
          <button onClick={close} className="rounded-md p-2 text-slate-500 hover:text-white md:hidden" aria-label="Close navigation"><X size={17} /></button>
        </div>

        <div className="mono mb-3 px-3 text-[9px] tracking-[.2em] text-slate-600">CONTROL SURFACE</div>
        <nav aria-label="Primary navigation" className="space-y-1">
          {navigation.map(({ href, label, icon: Icon, index }) => {
            const active = location === href;
            return <Link key={href} href={href} onClick={close} className={`group flex items-center gap-3 rounded-lg px-3 py-3 text-[12px] transition-colors ${active ? 'border border-emerald-300/[.12] bg-emerald-300/[.075] text-emerald-100' : 'border border-transparent text-slate-400 hover:bg-white/[.035] hover:text-slate-100'}`} aria-current={active ? 'page' : undefined} data-testid={`link-nav-${href === '/operations' ? 'overview' : href.slice(1)}`}>
              <Icon size={16} strokeWidth={1.7} className={active ? 'text-emerald-300' : 'text-slate-500 group-hover:text-slate-300'} />
              <span className="flex-1">{label}</span><span className="mono text-[9px] text-slate-600">{index}</span>
            </Link>;
          })}
        </nav>
        <div className="mt-auto">
          <div className="mb-4 h-px bg-white/[.07]" />
          <div className="rounded-xl border border-white/[.07] bg-white/[.025] p-3.5">
            <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold text-slate-300"><ShieldCheck size={14} className="text-cyan-300" /> Safe operations</div>
            <p className="text-[10px] leading-[1.6] text-slate-500">Sensitive member data is intentionally excluded from this console.</p>
          </div>
          <div className="mono mt-5 flex items-center justify-between text-[9px] tracking-[.14em] text-slate-600"><span>OPS CONSOLE</span><span>V 0.1</span></div>
        </div>
      </aside>
    </>
  );
}

function Topbar({ onMenu }: { onMenu: () => void }) {
  return <header className="sticky top-0 z-20 flex h-[68px] items-center justify-between border-b border-white/[.07] bg-[#0d1119]/90 px-4 backdrop-blur-xl md:px-8">
    <div className="flex items-center gap-3">
      <button onClick={onMenu} className="rounded-md p-2 text-slate-400 hover:bg-white/[.05] md:hidden" aria-label="Open navigation"><Menu size={19} /></button>
      <div className="hidden items-center gap-2 text-[10px] text-slate-500 sm:flex"><span className="h-1 w-1 rounded-full bg-slate-700" /> OPERATIONS CENTER <ChevronRight size={12} /><span className="text-slate-300">SERVICE STATUS</span></div>
      <span className="mono text-[9px] tracking-[.16em] text-slate-500 sm:hidden">SMH / OPS</span>
    </div>
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-2 rounded-full border border-amber-300/15 bg-amber-200/[.04] px-3 py-1.5 text-[9px] font-bold tracking-[.1em] text-amber-200"><span className="h-1.5 w-1.5 rounded-full bg-amber-300" /> DEVELOPMENT PREVIEW</div>
    </div>
  </header>;
}

function SectionHeading({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children?: React.ReactNode }) {
  return <div className="mb-7 flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
    <div><div className="mono mb-2 text-[9px] tracking-[.24em] text-emerald-300/80">{eyebrow}</div><h1 className="display text-[28px] font-semibold tracking-[-.045em] text-slate-100 sm:text-[34px]">{title}</h1><p className="mt-2 max-w-xl text-[12px] leading-5 text-slate-400">{description}</p></div>
    {children}
  </div>;
}

function DisabledAction({ children }: { children: React.ReactNode }) {
  return <div className="flex items-start gap-2 rounded-lg border border-white/[.07] bg-white/[.025] px-3 py-2.5 text-[10px] leading-4 text-slate-500">
    <CircleHelp size={13} className="mt-0.5 shrink-0 text-slate-500" /><span>{children}</span>
  </div>;
}

function MetricCard({ label, value, detail, icon: Icon, accent }: { label: string; value: string; detail: string; icon: typeof Gauge; accent: 'green' | 'cyan' | 'gold' }) {
  const accents = { green: 'text-emerald-300 bg-emerald-300/[.08]', cyan: 'text-cyan-300 bg-cyan-300/[.08]', gold: 'text-amber-200 bg-amber-200/[.08]' };
  return <div className="panel rounded-xl p-4 sm:p-5">
    <div className="flex items-start justify-between"><span className="mono text-[9px] tracking-[.15em] text-slate-500">{label}</span><span className={`grid h-8 w-8 place-items-center rounded-lg ${accents[accent]}`}><Icon size={15} /></span></div>
    <div className="mt-4 display text-[24px] font-semibold tracking-[-.04em] text-slate-100">{value}</div><div className="mt-1 text-[10px] text-slate-500">{detail}</div>
  </div>;
}

function EmptyState({ icon: Icon, title, description, tag }: { icon: typeof Activity; title: string; description: string; tag: string }) {
  return <div className="flex min-h-[210px] flex-col items-center justify-center px-5 py-9 text-center">
    <div className="mb-4 grid h-11 w-11 place-items-center rounded-xl border border-white/[.08] bg-white/[.025] text-slate-500"><Icon size={19} strokeWidth={1.5} /></div>
    <div className="mono mb-2 text-[9px] tracking-[.18em] text-slate-500">{tag}</div><h3 className="text-[13px] font-semibold text-slate-200">{title}</h3><p className="mt-2 max-w-[350px] text-[11px] leading-5 text-slate-500">{description}</p>
  </div>;
}

type ArchitectureNode = {
  id: string;
  name: string;
  summary: string;
  files: string[];
  icon: typeof Bot;
  x: number;
  y: number;
  tint: string;
};

const architectureNodes: ArchitectureNode[] = [
  { id: 'main', name: 'Python Main Bot', summary: 'Bot runtime entry and update handling', files: ['smart_money_hub_bot/main.py', 'smart_money_hub_bot/bot.py'], icon: Bot, x: 500, y: 290, tint: '#65e0aa' },
  { id: 'coach', name: 'Coach', summary: 'Coach orchestration and reply service', files: ['smart_money_hub_bot/coach.py', 'smart_money_hub_bot/message_router.py'], icon: BrainCircuit, x: 220, y: 170, tint: '#64d5df' },
  { id: 'weekend', name: 'Weekend Content', summary: 'Weekend content generation and posting modules', files: ['smart_money_hub_bot/channel_content.py', 'smart_money_hub_bot/channel_posting.py'], icon: FileText, x: 220, y: 410, tint: '#e0c46d' },
  { id: 'api', name: 'API server', summary: 'Health endpoint route and server app', files: ['artifacts/api-server/src/app.ts', 'artifacts/api-server/src/routes/health.ts'], icon: Server, x: 500, y: 100, tint: '#65d6e0' },
  { id: 'sqlite', name: 'SQLite storage', summary: 'Python repository backed by SQLite', files: ['smart_money_hub_bot/storage.py'], icon: Database, x: 780, y: 170, tint: '#b3a2f5' },
  { id: 'gemini', name: 'Gemini', summary: 'Optional configured Coach / content provider', files: ['smart_money_hub_bot/gemini_coach.py', 'smart_money_hub_bot/channel_gemini.py'], icon: BrainCircuit, x: 780, y: 410, tint: '#65d6e0' },
  { id: 'scheduler', name: 'Scheduler', summary: 'Scheduled work handled by existing bot modules', files: ['smart_money_hub_bot/channel_posting.py', 'smart_money_hub_bot/education_morning.py'], icon: CalendarClock, x: 500, y: 520, tint: '#e0c46d' },
  { id: 'telegram', name: 'Telegram API', summary: 'Existing Telegram transport client', files: ['smart_money_hub_bot/telegram_api.py'], icon: Send, x: 780, y: 290, tint: '#65d6e0' },
];

const architectureEdges: [string, string][] = [
  ['main', 'coach'], ['main', 'weekend'], ['main', 'scheduler'],
  ['main', 'telegram'], ['main', 'sqlite'], ['coach', 'gemini'], ['weekend', 'gemini'],
];

function ArchitectureMap({ apiStatus }: { apiStatus: string }) {
  const [selectedId, setSelectedId] = useState('main');
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ pointerId: number; x: number; y: number; originX: number; originY: number } | null>(null);
  const selectedNode = architectureNodes.find((node) => node.id === selectedId) ?? architectureNodes[0];
  const byId = (id: string) => architectureNodes.find((node) => node.id === id)!;
  const point = (node: ArchitectureNode) => ({ x: node.x, y: node.y });
  const changeZoom = (next: number) => setZoom(Math.max(.72, Math.min(1.42, next)));

  return <div className="panel overflow-hidden rounded-xl">
    <div className="flex flex-col gap-3 border-b border-white/[.07] px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <div><div className="mono text-[9px] tracking-[.17em] text-slate-500">ARCHITECTURE / SOURCE MAP</div><h2 className="mt-1 text-[13px] font-semibold text-slate-200">Code architecture map</h2></div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-2 rounded border border-amber-200/15 bg-amber-100/[.04] px-2.5 py-1.5 mono text-[9px] font-semibold tracking-[.12em] text-amber-200"><span className="h-1.5 w-1.5 rounded-full bg-amber-300" /> NO LIVE TELEMETRY</span>
        <span className="rounded border border-white/[.08] px-2.5 py-1.5 mono text-[9px] tracking-[.09em] text-slate-500">STATIC CODE MAP · NOT LIVE CONNECTIONS</span>
      </div>
    </div>
    <div className="grid xl:grid-cols-[minmax(0,1fr)_260px]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[.06] px-4 py-3 sm:px-5">
          <div className="flex items-center gap-2 text-[10px] text-slate-500"><span className="h-1.5 w-1.5 rounded-full bg-cyan-300" />Code presence verified · runtime state unknown</div>
          <div className="flex items-center gap-1.5">
            <button type="button" className="map-control" aria-label="Zoom out architecture map" onClick={() => changeZoom(zoom - .12)} data-testid="button-map-zoom-out">−</button>
            <span className="mono min-w-[40px] text-center text-[9px] text-slate-400" aria-live="polite">{Math.round(zoom * 100)}%</span>
            <button type="button" className="map-control" aria-label="Zoom in architecture map" onClick={() => changeZoom(zoom + .12)} data-testid="button-map-zoom-in">+</button>
            <button type="button" className="map-control ml-1" aria-label="Rotate map left" onClick={() => setRotation(Math.max(-12, rotation - 4))} data-testid="button-map-rotate-left"><RotateCcw size={12} /></button>
            <span className="mono min-w-[34px] text-center text-[8px] text-slate-500" aria-live="polite">{rotation}°</span>
            <button type="button" className="map-control" aria-label="Rotate map right" onClick={() => setRotation(Math.min(12, rotation + 4))} data-testid="button-map-rotate-right"><RotateCw size={12} /></button>
            <button type="button" className="map-control ml-1 px-2 text-[9px]" aria-label="Reset architecture map position, zoom, and rotation" onClick={() => { setZoom(1); setRotation(0); setOffset({ x: 0, y: 0 }); }} data-testid="button-map-reset">RESET</button>
          </div>
        </div>
        <div className="grid-bg relative h-[390px] overflow-auto sm:h-[460px]" aria-label="Scrollable architecture map. Drag the diagram to pan, use zoom controls to change scale.">
          <svg
            viewBox="0 0 1000 620"
            className="h-full min-h-[390px] w-full min-w-[720px] cursor-grab touch-none select-none active:cursor-grabbing sm:min-h-[460px]"
            style={{ transform: `perspective(1400px) rotateX(4deg) rotateY(${rotation}deg)`, transformOrigin: '50% 50%', transformStyle: 'preserve-3d', transition: 'transform 240ms ease-out' }}
            role="group"
            aria-label="Static code architecture graph. No live connections or runtime status are represented."
            onPointerDown={(event) => {
              if (event.target instanceof Element && event.target.closest('[data-architecture-node]')) return;
              drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, originX: offset.x, originY: offset.y };
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={(event) => {
              if (!drag.current || drag.current.pointerId !== event.pointerId) return;
              const bounds = event.currentTarget.getBoundingClientRect();
              const ratioX = 1000 / bounds.width;
              const ratioY = 620 / bounds.height;
              setOffset({ x: drag.current.originX + (event.clientX - drag.current.x) * ratioX, y: drag.current.originY + (event.clientY - drag.current.y) * ratioY });
            }}
            onPointerUp={(event) => {
              if (drag.current?.pointerId === event.pointerId) drag.current = null;
            }}
            onPointerCancel={() => { drag.current = null; }}
            onWheel={(event) => { event.preventDefault(); changeZoom(zoom + (event.deltaY < 0 ? .06 : -.06)); }}
          >
            <defs>
              <pattern id="map-dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="rgba(150,175,190,.16)" /></pattern>
              <filter id="node-shadow" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="8" stdDeviation="8" floodColor="#000" floodOpacity=".28" /></filter>
            </defs>
            <rect width="1000" height="620" fill="url(#map-dots)" />
            <g transform={`translate(${offset.x} ${offset.y}) translate(500 310) scale(${zoom}) translate(-500 -310)`}>
              {architectureEdges.map(([from, to]) => {
                const start = point(byId(from));
                const end = point(byId(to));
                return <line key={`${from}-${to}`} x1={start.x} y1={start.y} x2={end.x} y2={end.y} stroke="rgba(119,160,164,.34)" strokeWidth="1.25" strokeDasharray="5 7" />;
              })}
              <text x="500" y="42" textAnchor="middle" fill="rgba(156,178,187,.48)" fontSize="9" letterSpacing="2" fontFamily="DM Mono, monospace">SOURCE-LEVEL REFERENCES · NOT CONNECTIVITY</text>
              {architectureNodes.map((node) => {
                const Icon = node.icon;
                const chosen = selectedId === node.id;
                return <g
                  key={node.id}
                  data-architecture-node={node.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`${node.name}. Code present. Runtime state unknown, telemetry not connected. Select for source details.`}
                  aria-pressed={chosen}
                  onClick={() => setSelectedId(node.id)}
                  onPointerDown={(event) => event.stopPropagation()}
                  onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedId(node.id); } }}
                  className="cursor-pointer outline-none"
                >
                  <title>{`${node.name} — code present; runtime state unknown`}</title>
                  <rect x={node.x - 96} y={node.y - 39} width="192" height="78" rx="11" fill={chosen ? '#18252d' : '#141c25'} stroke={chosen ? node.tint : 'rgba(154,179,193,.24)'} strokeWidth={chosen ? '1.5' : '1'} filter="url(#node-shadow)" />
                  <rect x={node.x - 96} y={node.y - 39} width="3" height="78" rx="1.5" fill={node.tint} opacity={chosen ? '1' : '.7'} />
                  <circle cx={node.x - 71} cy={node.y - 12} r="12" fill={node.tint} fillOpacity=".11" stroke={node.tint} strokeOpacity=".34" />
                  <foreignObject x={node.x - 79} y={node.y - 20} width="16" height="16"><div className="grid h-4 w-4 place-items-center"><Icon size={12} color={node.tint} /></div></foreignObject>
                  <text x={node.x - 52} y={node.y - 14} fill="#e2e8ec" fontSize="11" fontWeight="600" fontFamily="Manrope, sans-serif">{node.name}</text>
                  <text x={node.x - 52} y={node.y + 2} fill="#83919a" fontSize="8" fontFamily="DM Mono, monospace">CODE PRESENT</text>
                  <circle cx={node.x - 85} cy={node.y + 22} r="2.5" fill="#d6b968" />
                  <text x={node.x - 77} y={node.y + 25} fill="#aa9e78" fontSize="7.6" letterSpacing=".45" fontFamily="DM Mono, monospace">UNKNOWN · NO TELEMETRY</text>
                </g>;
              })}
            </g>
          </svg>
          <div className="pointer-events-none absolute bottom-3 left-3 rounded border border-white/[.07] bg-[#0d1119]/85 px-2 py-1.5 mono text-[8px] tracking-[.1em] text-slate-500">DRAG TO PAN · WHEEL / BUTTONS TO ZOOM · ROTATE ABOVE</div>
        </div>
      </div>
      <aside className="border-t border-white/[.07] bg-black/[.08] p-4 sm:p-5 xl:border-l xl:border-t-0" aria-live="polite" aria-label="Selected architecture module details">
        <div className="mono mb-3 text-[9px] tracking-[.16em] text-slate-500">SELECTED MODULE</div>
        <div className="mb-4 flex items-start gap-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/[.09] bg-white/[.035]" style={{ color: selectedNode.tint }}><selectedNode.icon size={17} /></div>
          <div><h3 className="text-[12px] font-semibold text-slate-100">{selectedNode.name}</h3><p className="mt-1 text-[10px] leading-4 text-slate-500">{selectedNode.summary}</p></div>
        </div>
        <div className="mb-4 rounded-lg border border-amber-200/10 bg-amber-100/[.035] px-3 py-2.5">
          <div className="mono text-[8px] tracking-[.11em] text-amber-200">RUNTIME STATE</div>
          <div className="mt-1 text-[10px] font-semibold text-slate-300">Unknown</div>
          <div className="mt-0.5 text-[9px] text-slate-500">Telemetry not connected</div>
        </div>
        {selectedNode.id === 'api' && <div className="mb-4 rounded-lg border border-emerald-200/10 bg-emerald-100/[.035] px-3 py-2.5">
          <div className="mono text-[8px] tracking-[.11em] text-emerald-200">ONLY LIVE SIGNAL · API HEALTH</div>
          <div className="mt-1 text-[10px] text-slate-300">{apiStatus}</div>
          <div className="mt-1 text-[9px] leading-4 text-slate-500">Health endpoint response only; not a bot or Telegram status.</div>
        </div>}
        <div className="mono mb-2 text-[8px] tracking-[.14em] text-slate-500">VERIFIED SOURCE FILES</div>
        <ul className="space-y-1.5">
          {selectedNode.files.map((file) => <li key={file} className="break-all rounded border border-white/[.05] bg-white/[.02] px-2 py-1.5 mono text-[8px] leading-4 text-slate-400">{file}</li>)}
        </ul>
      </aside>
    </div>
    <div className="border-t border-white/[.07] px-4 py-4 sm:px-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div><div className="mono text-[9px] tracking-[.17em] text-slate-500">VIRTUAL WORKSPACES</div><p className="mt-1 text-[10px] text-slate-500">Code modules only · all runtime state unknown</p></div>
        <span className="mono text-[8px] tracking-[.1em] text-amber-200/80">NO LIVE TELEMETRY</span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {architectureNodes.map((node) => {
          const Icon = node.icon;
          const selected = selectedId === node.id;
          return <button key={node.id} type="button" onClick={() => setSelectedId(node.id)} aria-pressed={selected} className={`workspace-card text-left ${selected ? 'workspace-card-selected' : ''}`} data-testid={`workspace-${node.id}`}>
            <div className="flex items-start justify-between gap-2"><div className="flex items-center gap-2"><Icon size={13} style={{ color: node.tint }} /><span className="text-[10px] font-semibold text-slate-200">{node.name}</span></div><span className="h-1.5 w-1.5 rounded-full bg-amber-300/80" aria-label="Runtime unknown" /></div>
            <div className="mono mt-2 text-[8px] tracking-[.05em] text-slate-500">CODE PRESENT <span className="px-1 text-slate-700">/</span> UNKNOWN</div>
          </button>;
        })}
      </div>
    </div>
  </div>;
}

function Overview() {
  const health = useHealthCheck({ query: { queryKey: getHealthCheckQueryKey(), refetchInterval: 15000 } });
  const endpoint = health.isLoading ? 'Checking' : health.isError ? 'Unavailable' : health.data ? health.data.status : 'Unknown';
  return <main className="fade-up mx-auto max-w-[1440px] px-4 py-7 md:px-8 md:py-9">
    <SectionHeading eyebrow="SYSTEM / OVERVIEW" title="Operations overview" description="Development preview. Only the API health check is live; admin authentication, bot telemetry, content records, and operations controls are not connected. No private data is exposed.">
      <div className="mono flex items-center gap-2 self-start rounded-md border border-white/[.08] bg-white/[.025] px-3 py-2 text-[9px] tracking-[.13em] text-slate-500 sm:self-auto"><span className="h-1.5 w-1.5 rounded-full bg-cyan-300" /> LIVE API CHECK · 15S</div>
    </SectionHeading>

    <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="API HEALTH ENDPOINT" value={String(endpoint)} detail="GET /api/healthz · only connected live source" icon={Signal} accent={health.isError ? 'gold' : 'green'} />
      <MetricCard label="BOT TELEMETRY" value="Not connected" detail="No bot runtime signal available" icon={Bot} accent="cyan" />
      <MetricCard label="EVENT INGESTION" value="Unavailable" detail="No event source connected" icon={Activity} accent="gold" />
      <MetricCard label="CONTENT QUEUE" value="Unavailable" detail="Queue and publishing history offline" icon={FileClock} accent="cyan" />
    </div>

    <div className="grid gap-5">
      <ArchitectureMap apiStatus={health.isError ? 'Unavailable' : health.data ? health.data.status : health.isLoading ? 'Checking' : 'Unknown'} />
      <section className="panel rounded-xl" aria-labelledby="api-health-title">
        <div className="border-b border-white/[.07] px-5 py-4">
          <div className="mono text-[9px] tracking-[.17em] text-slate-500">SOURCE 001 / HEALTH</div><h2 id="api-health-title" className="mt-1 text-[13px] font-semibold text-slate-200">API health endpoint</h2>
        </div>
        <div className="space-y-4 p-5">
          <HealthQuery />
          <div className="rounded-lg border border-white/[.07] bg-black/10 p-3.5">
            <div className="mono mb-2 text-[9px] tracking-[.14em] text-slate-500">SCOPE NOTE</div>
            <p className="text-[11px] leading-[1.7] text-slate-400">A responding health endpoint confirms only that this API endpoint answered. It does not establish that the Python bot, Telegram, or downstream services are online.</p>
          </div>
          <div className="flex items-center justify-between border-t border-white/[.06] pt-3 text-[10px]"><span className="text-slate-500">Polling interval</span><span className="mono text-slate-300">15 seconds</span></div>
        </div>
      </section>
    </div>

    <div className="mt-5 grid gap-5 lg:grid-cols-2">
      <section className="panel rounded-xl">
        <div className="flex items-center justify-between border-b border-white/[.07] px-5 py-4"><div><div className="mono text-[9px] tracking-[.17em] text-slate-500">RECENT SIGNALS</div><h2 className="mt-1 text-[13px] font-semibold text-slate-200">Sanitized activity</h2></div><Link href="/activity" className="flex items-center gap-1 text-[10px] text-cyan-200 hover:text-cyan-100">Open stream <ChevronRight size={13} /></Link></div>
        <EmptyState icon={Activity} tag="EVENT STREAM NOT CONNECTED" title="Waiting for an event source" description="No events are fabricated or displayed until a sanitized event feed is available." />
      </section>
      <section className="panel rounded-xl">
        <div className="flex items-center justify-between border-b border-white/[.07] px-5 py-4"><div><div className="mono text-[9px] tracking-[.17em] text-slate-500">PUBLISHING PIPELINE</div><h2 className="mt-1 text-[13px] font-semibold text-slate-200">Content operations</h2></div><Link href="/content" className="flex items-center gap-1 text-[10px] text-cyan-200 hover:text-cyan-100">View queue <ChevronRight size={13} /></Link></div>
        <EmptyState icon={FileText} tag="QUEUE NOT CONNECTED" title="No publishing data available" description="Drafts, scheduled items, and publishing history will appear when a source is connected." />
      </section>
    </div>
  </main>;
}

function ActivityPage() {
  return <main className="fade-up mx-auto max-w-[1440px] px-4 py-7 md:px-8 md:py-9">
    <SectionHeading eyebrow="SYSTEM / OBSERVABILITY" title="Activity stream" description="Sanitized operational events only. Message content, personal chat data, usernames, tokens, and secrets are never shown." />
    <div className="mb-5 flex flex-wrap items-center gap-2">
      <span className="rounded-md border border-white/[.08] bg-white/[.025] px-3 py-2 mono text-[9px] tracking-[.12em] text-slate-400">ALL COMPONENTS</span>
      <span className="rounded-md border border-amber-200/15 bg-amber-100/[.04] px-3 py-2 mono text-[9px] tracking-[.12em] text-amber-200">SOURCE UNAVAILABLE</span>
    </div>
    <section className="panel overflow-hidden rounded-xl">
      <div className="grid grid-cols-[1.2fr_1fr_1fr_1fr] gap-3 border-b border-white/[.07] bg-white/[.02] px-5 py-3 mono text-[9px] tracking-[.14em] text-slate-500 max-sm:hidden"><span>COMPONENT</span><span>EVENT TYPE</span><span>STATUS</span><span>TIMESTAMP / UTC</span></div>
      <EmptyState icon={Activity} tag="EVENT INGESTION OFFLINE" title="No events to display" description="The sanitized event stream is not connected yet. This panel will remain empty rather than imply activity that has not been observed." />
    </section>
    <div className="mt-4 flex items-start gap-2 text-[10px] leading-5 text-slate-500"><ShieldCheck size={13} className="mt-1 shrink-0 text-cyan-300" />Privacy boundary: event fields will be limited to component, event type, status, UTC timestamp, and safe error category.</div>
  </main>;
}

function ContentPage() {
  return <main className="fade-up mx-auto max-w-[1440px] px-4 py-7 md:px-8 md:py-9">
    <SectionHeading eyebrow="SYSTEM / PUBLISHING" title="Content operations" description="Review publishing state without exposing message text or member data." >
      <button type="button" disabled aria-disabled="true" title="Publishing controls are unavailable until a content API is connected." className="cursor-not-allowed rounded-lg border border-white/[.08] bg-white/[.03] px-4 py-2.5 text-[11px] font-semibold text-slate-500">Create draft</button>
    </SectionHeading>
    <div className="mb-5 grid gap-3 sm:grid-cols-3">
      <MetricCard label="DRAFTS" value="Unavailable" detail="Draft source not connected" icon={FileText} accent="cyan" />
      <MetricCard label="SCHEDULED" value="Unavailable" detail="Schedule source not connected" icon={Clock3} accent="gold" />
      <MetricCard label="PUBLISHED" value="Unavailable" detail="Publishing history not connected" icon={Check} accent="green" />
    </div>
    <section className="panel rounded-xl">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[.07] px-5 py-4"><div><div className="mono text-[9px] tracking-[.17em] text-slate-500">QUEUE / HISTORY</div><h2 className="mt-1 text-[13px] font-semibold text-slate-200">Publishing records</h2></div><span className="rounded border border-amber-200/15 bg-amber-100/[.04] px-2 py-1 mono text-[9px] tracking-[.12em] text-amber-200">NOT CONNECTED</span></div>
      <EmptyState icon={FileClock} tag="CONTENT SOURCE UNAVAILABLE" title="No content records available" description="Drafts and publishing history are not connected to a data source. No draft or delivery status is assumed." />
    </section>
    <div className="mt-4 max-w-xl"><DisabledAction>Publishing controls are disabled because no content API is connected. This console cannot create, edit, schedule, or publish content in this pass.</DisabledAction></div>
  </main>;
}

type ConnectionState = 'healthy' | 'degraded' | 'offline' | 'unhealthy' | 'running' | 'not_connected' | 'unknown';

function connectionLabel(state: string | undefined) {
  switch (state) {
    case 'healthy': return 'Healthy';
    case 'running': return 'Recent heartbeat';
    case 'degraded': return 'Degraded';
    case 'offline': return 'Offline';
    case 'unhealthy': return 'Unhealthy';
    case 'not_connected': return 'Not connected';
    default: return 'Unknown';
  }
}

function connectionTone(state: ConnectionState | undefined) {
  if (state === 'healthy' || state === 'running') return 'connection-tone-good';
  if (state === 'degraded' || state === 'unhealthy' || state === 'offline') return 'connection-tone-warning';
  return 'connection-tone-unknown';
}

function ConnectionStatus({ state, label }: { state: ConnectionState | undefined; label?: string }) {
  return <span className={`connection-status ${connectionTone(state)}`}><span className="connection-status-dot" />{label ?? connectionLabel(state)}</span>;
}

function ConnectionsPage() {
  const api = useHealthCheck({
    query: { queryKey: getHealthCheckQueryKey(), refetchInterval: 15000 },
  });
  const snapshot = useGetPortalCommandCenter({
    query: {
      queryKey: getGetPortalCommandCenterQueryKey(),
      staleTime: 15000,
      refetchOnMount: 'always',
      refetchInterval: 30000,
    },
  });
  const [refreshing, setRefreshing] = useState(false);
  const privateTestBot = snapshot.data?.bots.find((bot) => bot.id === 'isolated_test');
  const productionBot = snapshot.data?.bots.find((bot) => bot.id === 'production');
  const apiState: ConnectionState = api.isError ? 'offline' : api.data ? 'healthy' : 'unknown';
  const heartbeatState: ConnectionState = privateTestBot?.processStatus === 'running'
    ? 'running'
    : privateTestBot?.healthStatus === 'unhealthy'
      ? 'unhealthy'
      : 'unknown';
  const refresh = async () => {
    setRefreshing(true);
    try {
      await Promise.all([api.refetch(), snapshot.refetch()]);
    } finally {
      setRefreshing(false);
    }
  };
  const healthTime = privateTestBot?.healthCheckedAt
    ? new Date(privateTestBot.healthCheckedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : 'No recent check';
  const telegramStatus: ConnectionState = privateTestBot?.telegramStatus ?? 'unknown';
  const databaseStatus: ConnectionState = privateTestBot?.databaseStatus ?? 'unknown';
  const pollingStatus: ConnectionState = privateTestBot?.pollingStatus ?? 'unknown';

  return <main className="fade-up mx-auto max-w-[1440px] px-4 py-7 md:px-8 md:py-9">
    <SectionHeading eyebrow="SYSTEM / DEVELOPMENT TELEMETRY" title="Connections" description="A read-only view of the API and the latest isolated Development bot heartbeat." />
    <section className="network-panel panel overflow-hidden rounded-2xl" data-testid="development-connection-map">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-white/[.07] px-5 py-5 md:px-7">
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="network-scope-tag">DEVELOPMENT ONLY</span>
            <span className="network-readonly-tag"><ShieldCheck size={11} /> READ-ONLY</span>
          </div>
          <h2 className="text-base font-semibold text-slate-100">System signal map</h2>
          <p className="mt-1 max-w-2xl text-[11px] leading-5 text-slate-500">Motion appears only while this dashboard checks a real endpoint. The bot node is a stored heartbeat snapshot, not a direct Telegram delivery monitor.</p>
        </div>
        <button type="button" onClick={refresh} disabled={refreshing || api.isFetching || snapshot.isFetching} className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-white/10 bg-white/[.035] px-3 text-[11px] font-medium text-slate-300 transition hover:border-emerald-300/25 hover:text-emerald-100 disabled:opacity-50" aria-label="Refresh connection status" data-testid="button-refresh-connections">
          <RefreshCw size={13} className={refreshing || api.isFetching || snapshot.isFetching ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="network-map-stage">
        <div className="network-map-web" aria-hidden="true" />
        <svg className="network-map-lines" viewBox="0 0 1000 360" preserveAspectRatio="none" aria-hidden="true">
          <path d="M 246 180 C 300 180 333 180 385 180" className={`network-link ${apiState === 'healthy' ? 'network-link-observed' : ''}`} />
          <path d="M 615 180 C 666 180 699 180 754 180" className={`network-link ${snapshot.data && !snapshot.isError ? 'network-link-observed' : ''}`} />
          {apiState === 'healthy' && <circle r="5" className={`network-packet ${api.isFetching ? 'network-packet-active' : ''}`}><animateMotion dur="1.8s" repeatCount="indefinite" path="M 246 180 C 300 180 333 180 385 180" /></circle>}
          {snapshot.data && !snapshot.isError && <circle r="4.5" className={`network-packet network-packet-cyan ${snapshot.isFetching ? 'network-packet-active' : ''}`}><animateMotion dur="2.3s" repeatCount="indefinite" path="M 615 180 C 666 180 699 180 754 180" /></circle>}
        </svg>
        <div className="network-map-nodes">
          <article className="network-node network-node-dashboard">
            <span className="network-node-icon"><Command size={16} /></span>
            <div className="network-node-copy"><span className="network-node-kicker">MONITORING SURFACE</span><strong>Operations Center</strong><small>Owner-only Development view</small></div>
            <span className="network-node-presence" aria-label="Current page" />
          </article>
          <article className="network-node network-node-api">
            <span className="network-node-icon network-node-icon-api"><Signal size={16} /></span>
            <div className="network-node-copy"><span className="network-node-kicker">LIVE CHECK · EVERY 15S</span><strong>API health endpoint</strong><small>GET /api/healthz · {api.data?.status ?? (api.isError ? 'no response' : 'checking')}</small></div>
            <ConnectionStatus state={apiState} />
          </article>
          <article className="network-node network-node-heartbeat">
            <span className="network-node-icon network-node-icon-bot"><Bot size={16} /></span>
            <div className="network-node-copy"><span className="network-node-kicker">ISOLATED TEST BOT</span><strong>Heartbeat snapshot</strong><small>Last check · {healthTime}</small></div>
            <ConnectionStatus state={heartbeatState} label={heartbeatState === 'running' ? 'Recent' : connectionLabel(heartbeatState)} />
          </article>
        </div>
        <div className="network-map-captions" aria-hidden="true">
          <span>HEALTH PROBE</span><span>READ-ONLY SNAPSHOT QUERY</span>
        </div>
      </div>

      <div className="grid gap-0 border-t border-white/[.07] md:grid-cols-[1.15fr_1fr]">
        <div className="border-b border-white/[.07] p-5 md:border-b-0 md:border-r md:px-7 md:py-6">
          <div className="flex items-center justify-between gap-3">
            <div><p className="mono text-[9px] tracking-[.16em] text-slate-500">PRIVATE TEST BOT · DEVELOPMENT</p><h3 className="mt-1 text-[13px] font-semibold text-slate-200">Latest reported signals</h3></div>
            <ConnectionStatus state={heartbeatState} label={heartbeatState === 'running' ? 'Heartbeat recent' : 'Heartbeat unknown'} />
          </div>
          <p className="mt-3 text-[10px] leading-5 text-slate-500">
            {privateTestBot?.processStatus === 'running'
              ? 'A recent isolated-test heartbeat is available. This does not confirm that a Telegram channel accepted a post.'
              : snapshot.isError
                ? 'The Development command-center snapshot could not be checked. Bot and Telegram status are left unknown.'
                : 'No fresh isolated-test heartbeat is available. Bot and Telegram status remain unknown.'}
          </p>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {[
              ['Bot health', privateTestBot?.healthStatus],
              ['Telegram reachability', privateTestBot?.telegramStatus],
              ['Database', privateTestBot?.databaseStatus],
              ['Polling', privateTestBot?.pollingStatus],
              ['Workflow control', privateTestBot?.workflowStatus],
              ['Channel delivery', 'unknown'],
            ].map(([label, value]) => <div className="network-signal" key={label}>
              <span>{label}</span>
              <ConnectionStatus state={value as ConnectionState | undefined} />
            </div>)}
          </div>
        </div>
        <div className="p-5 md:px-7 md:py-6">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-200"><Server size={14} className="text-amber-200" /> Production services</div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/[.07] bg-white/[.02] px-4 py-3">
            <div><strong className="block text-[11px] text-slate-300">Production bot</strong><span className="mt-1 block text-[10px] text-slate-500">Not connected to this Development monitor</span></div>
            <ConnectionStatus state={productionBot?.processStatus ?? 'not_connected'} label="Not connected" />
          </div>
          <p className="mt-3 text-[10px] leading-5 text-slate-500">No Production bot, channel, VPS service, or message-delivery telemetry is read or controlled here. This page cannot restart services or publish posts.</p>
        </div>
      </div>
    </section>
    <p className="mt-4 flex items-start gap-2 text-[10px] leading-5 text-slate-500"><CircleHelp size={13} className="mt-0.5 shrink-0 text-cyan-200" /> A green heartbeat means the isolated test bot reported recently. It is not proof of channel access or successful delivery.</p>
  </main>;
}

function NotFound() {
  return <main className="mx-auto max-w-4xl px-5 py-20 text-center"><AlertCircle className="mx-auto text-amber-200" /><h1 className="display mt-4 text-3xl text-slate-100">Route not found</h1><Link href="/operations" className="mt-5 inline-block text-sm text-cyan-200">Return to overview</Link></main>;
}

function Shell() {
  const [mobileOpen, setMobileOpen] = useState(false);
  return <div className="shell grain flex min-h-[100dvh] text-slate-200">
    <Sidebar mobileOpen={mobileOpen} close={() => setMobileOpen(false)} />
    <div className="min-w-0 flex-1"><Topbar onMenu={() => setMobileOpen(true)} />
      <Switch>
        <Route path="/operations" component={Overview} />
        <Route path="/activity" component={ActivityPage} />
        <Route path="/content" component={ContentPage} />
        <Route path="/connections" component={ConnectionsPage} />
        <Route component={NotFound} />
      </Switch>
      <footer className="mx-auto flex max-w-[1440px] flex-col gap-1 border-t border-white/[.06] px-4 py-5 text-[9px] text-slate-600 sm:flex-row sm:items-center sm:justify-between md:px-8"><span>SMART MONEY HUB OPERATIONS CENTER</span><span>DEVELOPMENT PREVIEW · AUTH NOT CONFIGURED · PRIVATE DATA HIDDEN</span></footer>
    </div>
  </div>;
}

function AppRoutes() {
  return <Switch>
    <Route path="/" component={SupportPage} />
    <Route path="/support" component={SupportPage} />
    <Route component={Shell} />
  </Switch>;
}

function App({ routeBase }: { routeBase?: string } = {}) {
  const base = routeBase ?? import.meta.env.BASE_URL.replace(/\/$/, '');
  return <QueryClientProvider client={queryClient}><WouterRouter base={base}><AppRoutes /></WouterRouter></QueryClientProvider>;
}

export default App;
