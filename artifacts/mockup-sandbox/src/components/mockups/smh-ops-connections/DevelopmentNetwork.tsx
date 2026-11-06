import "./_group.css";
import { useState } from "react";
import {
  Activity,
  ArrowDownRight,
  Bot,
  CircleHelp,
  Cloud,
  Eye,
  LockKeyhole,
  Pause,
  Play,
  Radio,
  RefreshCw,
  ShieldCheck,
  Waypoints,
} from "lucide-react";

type Environment = "development" | "production";

export function DevelopmentNetwork() {
  const [environment, setEnvironment] = useState<Environment>("development");
  const [motionPaused, setMotionPaused] = useState(false);
  const [replayKey, setReplayKey] = useState(0);
  const [previewNotice, setPreviewNotice] = useState("");

  const replay = () => {
    setReplayKey((key) => key + 1);
    setPreviewNotice("Illustrative path replayed. No live source was queried.");
  };

  return (
    <main className="smh-ops-extract smh-network min-h-[100dvh] px-4 py-5 sm:px-6 sm:py-8 lg:px-10">
      <style>{`
        .smh-network {
          --net-bg: #0b1017;
          --net-panel: #101720;
          --net-panel-raised: #141e29;
          --net-line: rgba(204, 222, 232, .09);
          --net-muted: #7c8a97;
          --net-text: #d7e0e7;
          --net-green: #56d6a0;
          --net-cyan: #53c8d5;
          --net-amber: #e7bd70;
          background:
            radial-gradient(ellipse at 51% 37%, rgba(39, 75, 75, .15), transparent 44%),
            var(--net-bg);
        }
        .smh-network .network-grid {
          background-image: radial-gradient(rgba(166, 193, 203, .16) .7px, transparent .7px);
          background-size: 21px 21px;
          mask-image: linear-gradient(to bottom, black, transparent 96%);
        }
        .smh-network .signal-dash {
          stroke-dasharray: 5 8;
          animation: smh-dash 7s linear infinite;
        }
        .smh-network .crawler {
          offset-path: path("M 194 260 C 302 260, 344 218, 445 196");
          animation: smh-crawl 8s linear infinite;
        }
        .smh-network .crawler-orbit {
          transform-origin: 555px 238px;
          animation: smh-orbit 16s linear infinite;
        }
        .smh-network.motion-paused *,
        .smh-network.motion-paused *::before,
        .smh-network.motion-paused *::after {
          animation-play-state: paused !important;
        }
        @keyframes smh-dash { to { stroke-dashoffset: -104; } }
        @keyframes smh-crawl { to { offset-distance: 100%; } }
        @keyframes smh-orbit { to { transform: rotate(360deg); } }
        @media (prefers-reduced-motion: reduce) {
          .smh-network *,
          .smh-network *::before,
          .smh-network *::after {
            animation-duration: .01ms !important;
            animation-iteration-count: 1 !important;
            scroll-behavior: auto !important;
          }
        }
      `}</style>

      <div className="mx-auto max-w-[1260px]">
        <header className="flex flex-col gap-5 border-b border-white/[.07] pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="flex items-center gap-2 font-mono text-[10px] tracking-[.18em] text-slate-500">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
              SMART MONEY HUB
              <span className="text-slate-700">/</span>
              OPERATIONS CENTER
            </div>
            <h1 className="mt-3 text-[30px] font-semibold leading-tight tracking-[-.04em] text-slate-100 sm:text-[38px]">
              Connections
            </h1>
            <p className="mt-2 max-w-2xl text-[13px] leading-6 text-slate-400">
              A bounded view of what this owner-only Development console can actually observe.
            </p>
          </div>
          <div className="flex items-center gap-2 self-start rounded-lg border border-amber-200/15 bg-amber-100/[.04] px-3 py-2 sm:self-auto">
            <LockKeyhole size={13} className="text-amber-200" />
            <span className="font-mono text-[9px] tracking-[.13em] text-amber-100/90">OWNER-ONLY · DEVELOPMENT</span>
          </div>
        </header>

        <section className="mt-5 flex flex-col gap-3 rounded-xl border border-cyan-200/[.12] bg-cyan-200/[.035] px-4 py-4 sm:flex-row sm:items-start sm:px-5">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-cyan-200/[.13] bg-cyan-200/[.06] text-cyan-100">
            <Eye size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[13px] font-semibold text-slate-100">Preview mode · sample states only</h2>
              <span className="rounded border border-cyan-100/10 px-1.5 py-0.5 font-mono text-[8px] tracking-[.12em] text-cyan-100/65">NOT LIVE</span>
            </div>
            <p className="mt-1 max-w-4xl text-[11px] leading-5 text-slate-400">
              This mockup has no backend. The labels and moving trace are illustrative, not telemetry. In the actual console, the only verified inputs are the API health endpoint and an owner-only Development snapshot of the isolated test-bot heartbeat.
            </p>
          </div>
          <div className="shrink-0 rounded-md border border-white/[.07] bg-black/10 p-1">
            {(["development", "production"] as const).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => {
                  setEnvironment(item);
                  setPreviewNotice("");
                }}
                aria-pressed={environment === item}
                className={`rounded px-3 py-1.5 font-mono text-[9px] tracking-[.1em] transition-colors ${
                  environment === item
                    ? "bg-white/[.09] text-slate-100"
                    : "text-slate-500 hover:text-slate-300"
                }`}
              >
                {item.toUpperCase()}
              </button>
            ))}
          </div>
        </section>

        {environment === "development" ? (
          <>
            <section className="mt-5 overflow-hidden rounded-xl border border-white/[.08] bg-[#101720]">
              <div className="flex flex-col gap-3 border-b border-white/[.07] px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
                <div>
                  <div className="flex items-center gap-2">
                    <Waypoints size={15} className="text-emerald-200" />
                    <h2 className="text-sm font-semibold text-slate-100">Development observation map</h2>
                  </div>
                  <p className="mt-1 pl-[23px] text-[10px] text-slate-500">Evidence paths · not a service topology or delivery trace</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={replay}
                    className="inline-flex items-center gap-1.5 rounded-md border border-white/[.09] bg-white/[.025] px-2.5 py-2 text-[10px] font-medium text-slate-300 transition hover:border-white/[.16] hover:bg-white/[.05]"
                  >
                    <RefreshCw size={12} />
                    Replay sample
                  </button>
                  <button
                    type="button"
                    onClick={() => setMotionPaused((paused) => !paused)}
                    aria-pressed={motionPaused}
                    className="inline-flex items-center gap-1.5 rounded-md border border-white/[.09] bg-white/[.025] px-2.5 py-2 text-[10px] font-medium text-slate-300 transition hover:border-white/[.16] hover:bg-white/[.05]"
                  >
                    {motionPaused ? <Play size={12} /> : <Pause size={12} />}
                    {motionPaused ? "Resume motion" : "Pause motion"}
                  </button>
                </div>
              </div>

              <div className={`smh-network relative min-h-[330px] overflow-hidden ${motionPaused ? "motion-paused" : ""}`}>
                <div className="network-grid pointer-events-none absolute inset-0 opacity-30" />
                <div className="relative mx-auto max-w-[960px] px-3 py-3 sm:px-6 sm:py-5">
                  <div className="absolute left-1/2 top-5 hidden -translate-x-1/2 rounded-full border border-white/[.08] bg-[#111922]/90 px-3 py-1 font-mono text-[8px] tracking-[.12em] text-slate-500 sm:block">
                    OWNER DEVELOPMENT CONSOLE
                  </div>
                  <svg
                    key={replayKey}
                    viewBox="0 0 900 370"
                    role="img"
                    aria-label="Illustrative observation map showing API health and isolated Development test-bot heartbeat as separate verified sources, with Telegram and Production not connected."
                    className="hidden h-auto w-full sm:block"
                  >
                    <defs>
                      <linearGradient id="signalLine" x1="0" x2="1">
                        <stop offset="0" stopColor="#53c8d5" stopOpacity=".28" />
                        <stop offset=".52" stopColor="#56d6a0" stopOpacity=".62" />
                        <stop offset="1" stopColor="#53c8d5" stopOpacity=".28" />
                      </linearGradient>
                      <filter id="softDot" x="-200%" y="-200%" width="500%" height="500%">
                        <feGaussianBlur stdDeviation="4" result="blur" />
                        <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                      </filter>
                    </defs>
                    <path d="M194 130 C300 130 334 174 445 192" fill="none" stroke="url(#signalLine)" strokeWidth="1.5" className="signal-dash" />
                    <path d="M194 260 C302 260 344 218 445 196" fill="none" stroke="url(#signalLine)" strokeWidth="1.5" className="signal-dash" />
                    <path d="M194 260 C302 260 344 218 445 196" fill="none" stroke="#6bd9ae" strokeOpacity=".12" strokeWidth="11" />
                    <circle cx="480" cy="192" r="82" fill="none" stroke="#5ed5aa" strokeOpacity=".1" strokeDasharray="2 9" className="crawler-orbit" />
                    <circle cx="480" cy="192" r="61" fill="none" stroke="#5ed5aa" strokeOpacity=".08" strokeDasharray="1 8" className="crawler-orbit" />
                    <circle className="crawler" r="3.5" fill="#a9f2d1" filter="url(#softDot)" />
                    <circle cx="170" cy="130" r="23" fill="#14303a" stroke="#53c8d5" strokeOpacity=".65" />
                    <circle cx="170" cy="130" r="4" fill="#68d7df" />
                    <circle cx="170" cy="260" r="23" fill="#18332e" stroke="#56d6a0" strokeOpacity=".55" />
                    <path d="M162 260h16M170 252v16" stroke="#80e4bb" strokeWidth="1.5" strokeLinecap="round" />
                    <circle cx="480" cy="192" r="28" fill="#14212a" stroke="#a0b2bd" strokeOpacity=".48" />
                    <path d="M472 192h16M480 184v16" stroke="#b6c8d1" strokeWidth="1.3" strokeLinecap="round" />
                    <circle cx="760" cy="130" r="23" fill="#2d271c" stroke="#e7bd70" strokeOpacity=".55" />
                    <path d="M754 130h12M760 124v12" stroke="#e7bd70" strokeOpacity=".8" strokeWidth="1.4" strokeLinecap="round" />
                    <text x="170" y="82" textAnchor="middle" fill="#9bb0bd" fontSize="10" fontFamily="DM Mono">API HEALTH</text>
                    <text x="170" y="174" textAnchor="middle" fill="#667987" fontSize="9" fontFamily="DM Mono">endpoint response</text>
                    <text x="170" y="306" textAnchor="middle" fill="#d7e0e7" fontSize="10" fontFamily="DM Mono">DEV TEST BOT</text>
                    <text x="170" y="323" textAnchor="middle" fill="#74858e" fontSize="9" fontFamily="DM Mono">heartbeat snapshot</text>
                    <text x="480" y="150" textAnchor="middle" fill="#c5d0d6" fontSize="9" fontFamily="DM Mono">OWNER VIEW</text>
                    <text x="480" y="238" textAnchor="middle" fill="#74858e" fontSize="9" fontFamily="DM Mono">source visibility</text>
                    <text x="760" y="82" textAnchor="middle" fill="#9bb0bd" fontSize="10" fontFamily="DM Mono">TELEGRAM</text>
                    <text x="760" y="174" textAnchor="middle" fill="#a58a58" fontSize="9" fontFamily="DM Mono">ACCESS UNKNOWN</text>
                    <rect x="285" y="207" width="132" height="21" rx="10" fill="#111922" stroke="#ffffff" strokeOpacity=".09" />
                    <text x="351" y="221" textAnchor="middle" fill="#9aabb4" fontSize="8" fontFamily="DM Mono">SNAPSHOT OBSERVATION</text>
                    <text x="760" y="194" textAnchor="middle" fill="#697680" fontSize="8" fontFamily="DM Mono">NOT OBSERVED HERE</text>
                  </svg>

                  <div className="grid gap-3 py-3 sm:hidden">
                    <div className="flex items-center gap-3 rounded-lg border border-cyan-200/10 bg-cyan-200/[.025] p-3">
                      <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-cyan-200/25 bg-cyan-200/[.06] text-cyan-100"><Cloud size={15} /></div>
                      <div className="min-w-0 flex-1">
                        <div className="text-[11px] font-semibold text-slate-200">API health endpoint</div>
                        <div className="mt-1 font-mono text-[9px] text-slate-500">Response scope only · sample: ok</div>
                      </div>
                      <span className="h-1.5 w-1.5 rounded-full bg-cyan-200" />
                    </div>
                    <div className="flex items-center gap-3 pl-7 text-[9px] font-mono text-emerald-100/70"><ArrowDownRight size={14} /> SOURCE VISIBLE TO THIS VIEW</div>
                    <div className="relative flex items-center gap-3 overflow-hidden rounded-lg border border-emerald-200/15 bg-emerald-200/[.035] p-3">
                      <span key={replayKey} className="pointer-events-none absolute left-0 top-0 h-full w-1/3 -translate-x-full bg-gradient-to-r from-transparent via-emerald-200/[.06] to-transparent animate-[smh-sweep_5s_linear_infinite]" />
                      <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-emerald-200/25 bg-emerald-200/[.06] text-emerald-100"><Bot size={15} /></div>
                      <div className="min-w-0 flex-1">
                        <div className="text-[11px] font-semibold text-slate-200">Isolated Development test bot</div>
                        <div className="mt-1 font-mono text-[9px] text-slate-500">Heartbeat snapshot · sample: recent</div>
                      </div>
                      <Activity size={14} className="text-emerald-200" />
                    </div>
                    <div className="pl-7 text-[9px] font-mono text-amber-100/70">NO VERIFIED CHANNEL ACCESS OR POST RESULT</div>
                    <div className="flex items-center gap-3 rounded-lg border border-amber-100/10 bg-amber-100/[.025] p-3">
                      <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-amber-100/15 bg-amber-100/[.04] text-amber-100/70"><CircleHelp size={15} /></div>
                      <div className="min-w-0 flex-1">
                        <div className="text-[11px] font-semibold text-slate-300">Telegram channel</div>
                        <div className="mt-1 font-mono text-[9px] text-amber-100/65">Access and delivery · unknown</div>
                      </div>
                    </div>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 border-t border-white/[.06] pt-3 text-[9px] text-slate-500 sm:mt-0">
                    <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-cyan-200" /> Verified source scope</span>
                    <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-amber-200" /> Unknown / not observed</span>
                    <span className="text-slate-600">Moving trace is illustrative only</span>
                  </div>
                </div>
              </div>
            </section>

            <section className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_1.15fr]">
              <article className="rounded-xl border border-white/[.08] bg-[#101720] p-4 sm:p-5">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-200"><Cloud size={15} className="text-cyan-200" /> API health</div>
                  <span className="rounded-full border border-cyan-200/15 bg-cyan-200/[.05] px-2 py-1 font-mono text-[8px] tracking-[.09em] text-cyan-100">SAMPLE · OK</span>
                </div>
                <p className="mt-4 font-mono text-[10px] text-slate-400">GET /api/healthz</p>
                <p className="mt-2 text-[10px] leading-5 text-slate-500">Endpoint response only. This does not establish bot runtime, Telegram access, or a published message.</p>
              </article>

              <article className="rounded-xl border border-white/[.08] bg-[#101720] p-4 sm:p-5">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-200"><Bot size={15} className="text-emerald-200" /> Test-bot heartbeat</div>
                  <span className="rounded-full border border-emerald-200/15 bg-emerald-200/[.05] px-2 py-1 font-mono text-[8px] tracking-[.09em] text-emerald-100">SAMPLE · RECENT</span>
                </div>
                <p className="mt-4 font-mono text-[10px] text-slate-400">Owner-only Development snapshot</p>
                <p className="mt-2 text-[10px] leading-5 text-slate-500">A recent heartbeat is not proof of Telegram channel access or a successful post.</p>
              </article>

              <article className="rounded-xl border border-amber-100/[.11] bg-[#151811] p-4 sm:p-5">
                <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-200"><ShieldCheck size={15} className="text-amber-200" /> Production boundary</div>
                <div className="mt-3 inline-flex rounded-md border border-amber-100/15 bg-amber-100/[.04] px-2.5 py-1.5 font-mono text-[9px] tracking-[.11em] text-amber-100">DELIBERATELY DISCONNECTED</div>
                <p className="mt-2 text-[10px] leading-5 text-slate-500">Production bot and channel state are not connected to this Development view.</p>
              </article>
            </section>
          </>
        ) : (
          <section className="mt-5 overflow-hidden rounded-xl border border-amber-100/[.13] bg-[#111711]">
            <div className="border-b border-white/[.06] px-5 py-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-100"><ShieldCheck size={16} className="text-amber-200" /> Production stays disconnected</div>
              <p className="mt-1 text-[11px] text-slate-500">No Production bot, channel, or delivery telemetry is connected to this mockup.</p>
            </div>
            <div className="flex flex-col items-center px-5 py-14 text-center">
              <div className="grid h-14 w-14 place-items-center rounded-full border border-amber-100/15 bg-amber-100/[.04] text-amber-100/70"><Radio size={21} /></div>
              <div className="mt-5 font-mono text-[9px] tracking-[.16em] text-amber-100/75">NO PRODUCTION SOURCES</div>
              <h2 className="mt-2 text-lg font-semibold text-slate-200">Nothing is being observed here.</h2>
              <p className="mt-2 max-w-md text-[11px] leading-5 text-slate-500">This is an intentional boundary, not a service failure. Switch back to Development to view the explicitly scoped sample states.</p>
              <button
                type="button"
                onClick={() => setEnvironment("development")}
                className="mt-5 rounded-md border border-white/[.1] bg-white/[.04] px-3 py-2 text-[10px] font-medium text-slate-300 transition hover:bg-white/[.08]"
              >
                Return to Development
              </button>
            </div>
          </section>
        )}

        {previewNotice && <p role="status" className="mt-3 text-center text-[10px] text-slate-500">{previewNotice}</p>}

        <footer className="mt-6 flex flex-col items-center justify-between gap-2 border-t border-white/[.06] pt-4 text-center sm:flex-row sm:text-left">
          <span className="font-mono text-[8px] tracking-[.15em] text-slate-600">OWNER VIEW · DEVELOPMENT ONLY</span>
          <span className="text-[9px] text-slate-600">No live telemetry queried · no channel delivery implied</span>
        </footer>
      </div>
      <style>{`
        @keyframes smh-sweep { to { transform: translateX(450%); } }
        @media (prefers-reduced-motion: reduce) {
          .smh-network [class*="animate-"] { animation: none !important; }
        }
      `}</style>
    </main>
  );
}
