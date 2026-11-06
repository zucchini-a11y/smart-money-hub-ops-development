import "./_group.css";
import { Bot, Link2, RefreshCw, Signal } from "lucide-react";

export function Current() {
  return (
    <div className="smh-ops-extract min-h-screen p-6 md:p-9">
      <div className="mx-auto max-w-6xl">
        <div className="mb-7">
          <p className="font-mono text-[10px] tracking-[.18em] text-slate-500">SYSTEM / INFRASTRUCTURE</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-100">Connections</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
            Service edges and connection states will be rendered only from verified telemetry.
          </p>
        </div>

        <div className="mb-5 flex gap-3 rounded-xl border border-cyan-300/10 bg-cyan-300/[.035] p-4 md:p-5">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-cyan-300/15 bg-cyan-300/[.07] text-cyan-200">
            <Link2 size={16} />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-200">Connection visibility is not live yet</h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500">
              Only the API health endpoint is currently connected. A health response does not indicate Telegram availability or prove the bot process is running.
            </p>
          </div>
        </div>

        <section className="overflow-hidden rounded-xl border border-white/[.07] bg-[#101720]">
          <div className="grid grid-cols-3 gap-3 border-b border-white/[.07] bg-white/[.02] px-5 py-3 font-mono text-[9px] tracking-[.14em] text-slate-500">
            <span>SOURCE</span><span>DESTINATION</span><span>STATE</span>
          </div>
          <div className="p-8 text-center">
            <Link2 className="mx-auto text-slate-500" size={20} />
            <p className="mt-3 font-mono text-[9px] tracking-[.15em] text-amber-200">CONNECTION TELEMETRY UNAVAILABLE</p>
            <h2 className="mt-2 text-base font-semibold text-slate-200">No connection edges observed</h2>
            <p className="mx-auto mt-2 max-w-lg text-xs leading-5 text-slate-500">
              Bot, Telegram, and service connection data are not connected. No connection states are simulated.
            </p>
          </div>
        </section>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <section className="rounded-xl border border-white/[.07] bg-[#101720] p-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200"><Signal size={15} className="text-emerald-300" /> API health endpoint</div>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <span className="inline-flex items-center gap-2 rounded-full border border-emerald-300/20 bg-emerald-300/[.07] px-3 py-1.5 text-[11px] font-semibold text-emerald-200">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" /> API RESPONDING
              </span>
              <span className="font-mono text-[10px] text-slate-500">response · ok</span>
              <button className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-[11px] text-slate-400"><RefreshCw size={12} /> Refresh</button>
            </div>
            <p className="mt-3 text-[10px] leading-5 text-slate-500">Live source · GET /api/healthz · refreshed every 15 seconds. Scope is limited to the API endpoint.</p>
          </section>
          <section className="rounded-xl border border-white/[.07] bg-[#101720] p-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200"><Bot size={15} className="text-amber-200" /> Bot and Telegram</div>
            <span className="mt-4 inline-flex rounded-md border border-amber-200/15 bg-amber-100/[.04] px-2.5 py-1.5 font-mono text-[9px] tracking-[.12em] text-amber-200">NOT CONNECTED</span>
            <p className="mt-3 text-[10px] leading-5 text-slate-500">No bot runtime or Telegram connection telemetry is available to this console.</p>
          </section>
        </div>
        <p className="mt-6 text-center font-mono text-[9px] tracking-[.15em] text-slate-600">CURRENT REFERENCE · STATIC MOCKUP, NOT LIVE STATUS</p>
      </div>
    </div>
  );
}
