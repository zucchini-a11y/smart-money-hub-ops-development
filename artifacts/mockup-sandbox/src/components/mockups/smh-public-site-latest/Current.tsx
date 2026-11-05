import { useEffect, useState } from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight, BookOpen, Compass, ShieldCheck, X } from "lucide-react";
import "./_group.css";

const pages = [
  { href: "/", label: "Home" },
  { href: "/about", label: "About" },
  { href: "/education", label: "Education" },
  { href: "/market-analysis", label: "Market Analysis" },
  { href: "/philosophy", label: "Philosophy" },
  { href: "/community", label: "Community" },
  { href: "/contact", label: "Contact" },
];

const primaryCommunity = "https://t.me/SmartMoneyHubSignalsBot";
const isConfiguredPublicUrl = (value: string) => {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
};
const logoSrc = "/__mockup/images/vayda-logo.png";

function usePublicPageMotion() {
  useEffect(() => {
    const root = document.querySelector<HTMLElement>(".vayda-site");
    if (!root) return;

    const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const reduceMotion = motionPreference.matches;
    window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });

    let observer: IntersectionObserver | undefined;
    const revealTargets = root.querySelectorAll<HTMLElement>("[data-reveal]");
    if (!reduceMotion && "IntersectionObserver" in window) {
      root.classList.add("vs-motion-ready");
      observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer?.unobserve(entry.target);
          }
        });
      }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
      revealTargets.forEach((target) => observer?.observe(target));
    } else {
      revealTargets.forEach((target) => target.classList.add("is-visible"));
    }

    const hero = root.querySelector<HTMLElement>(".vs-home-hero");
    const header = root.querySelector<HTMLElement>(".vs-header");
    let heroScrollDistance = hero ? Math.max(hero.offsetHeight, window.innerHeight * 0.8) : 1;
    const chartFrame = root.querySelector<HTMLElement>(".vs-chart-frame");
    let animationFrame = 0;
    const updateMotion = () => {
      animationFrame = 0;
      const scrollY = window.scrollY || window.pageYOffset;
      if (!reduceMotion) {
        const heroProgress = Math.min(1, Math.max(0, scrollY / heroScrollDistance));
        chartFrame?.style.setProperty("--vs-hero-progress", heroProgress.toFixed(4));
        chartFrame?.style.setProperty("--vs-scan-x", `${(heroProgress * 400).toFixed(1)}px`);
      }
      const shouldBlurHeader = scrollY > 12;
      if (header?.classList.contains("is-scrolled") !== shouldBlurHeader) {
        header?.classList.toggle("is-scrolled", shouldBlurHeader);
      }
    };
    const requestMotionUpdate = () => {
      if (!animationFrame) animationFrame = window.requestAnimationFrame(updateMotion);
    };
    const handleResize = () => {
      heroScrollDistance = hero ? Math.max(hero.offsetHeight, window.innerHeight * 0.8) : 1;
      requestMotionUpdate();
    };
    window.addEventListener("scroll", requestMotionUpdate, { passive: true });
    window.addEventListener("resize", handleResize);
    requestMotionUpdate();

    return () => {
      observer?.disconnect();
      window.removeEventListener("scroll", requestMotionUpdate);
      window.removeEventListener("resize", handleResize);
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      chartFrame?.style.removeProperty("--vs-hero-progress");
      chartFrame?.style.removeProperty("--vs-scan-x");
      header?.classList.remove("is-scrolled");
    };
  }, []);
}

function Header() {
  const [open, setOpen] = useState(false);
  return <header className="vs-header">
    <div className="vs-header-inner">
      <a href="/" className="vs-brand" aria-label="VAYDA Smart Money Hub home" onClick={() => setOpen(false)} data-testid="link-public-home-brand">
        <img src={logoSrc} alt="VAYDA Smart Money Hub logo" width="48" height="48" />
        <span><span className="vs-brand-word">VAYDA</span><span className="vs-brand-sub">SMART MONEY HUB</span></span>
      </a>
      <button className="vs-menu-toggle" type="button" aria-label={open ? "Close navigation menu" : "Open navigation menu"} aria-expanded={open} aria-controls="vayda-public-nav" onClick={() => setOpen(!open)} data-testid="button-public-menu">
        {open ? <X size={18} /> : <><span /><span /></>}
      </button>
      <nav id="vayda-public-nav" className={`vs-nav ${open ? "is-open" : ""}`} aria-label="Public navigation">
        {pages.slice(1).map((page) => <a key={page.href} href={page.href} aria-current={page.href === "/" ? "page" : undefined} onClick={() => setOpen(false)} data-testid={`link-public-${page.href.slice(1) || "home"}`}>{page.label}</a>)}
        {isConfiguredPublicUrl(primaryCommunity) && <a href={primaryCommunity} target="_blank" rel="noopener noreferrer" className="vs-nav-cta" data-testid="link-public-community-entry">Enter community <ArrowUpRight size={13} /></a>}
        <a href="/sign-up" className="vs-create-account" onClick={() => setOpen(false)} data-testid="link-public-create-account">Create account <ArrowUpRight size={13} /></a>
        <a href="/login" className="vs-staff-link" onClick={() => setOpen(false)} data-testid="link-public-login">Sign in</a>
      </nav>
    </div>
  </header>;
}

function Footer() {
  return <footer className="vs-footer">
    <div className="vs-shell vs-footer-top">
      <div className="vs-footer-brand">
        <a href="/" className="vs-brand" aria-label="VAYDA home" data-testid="link-public-footer-home">
          <img src={logoSrc} alt="" width="48" height="48" />
          <span><span className="vs-brand-word">VAYDA</span><span className="vs-brand-sub">SMART MONEY HUB</span></span>
        </a>
        <p>Market education built around observation, confirmation, and deliberate execution.</p>
      </div>
      <div className="vs-footer-col"><h2>Explore</h2><div className="vs-footer-links">{pages.slice(1).map((page) => <a key={page.href} href={page.href} data-testid={`link-footer-${page.href.slice(1)}`}>{page.label}</a>)}</div></div>
      <div className="vs-footer-col"><h2>Start here</h2><div className="vs-footer-links">
        <a href="/philosophy" data-testid="link-footer-philosophy">Our philosophy</a>
        <a href="/community" data-testid="link-footer-community">Community access</a>
        <a href="/education" data-testid="link-footer-education">Learning approach</a>
        <a href="/login" data-testid="link-footer-login">Sign in</a>
      </div></div>
    </div>
    <div className="vs-shell vs-footer-bottom"><span>VAYDA SMART MONEY HUB · EDUCATION FIRST</span><span><strong>Trading involves risk.</strong> Education is not financial advice.</span></div>
  </footer>;
}

function ChartIllustration() {
  const candles = [
    [42, 183, 25, 45, "down"], [75, 167, 34, 54, "up"], [108, 177, 28, 44, "down"],
    [141, 144, 38, 62, "up"], [174, 151, 28, 48, "down"], [207, 121, 37, 64, "up"],
    [240, 135, 25, 44, "down"], [273, 110, 40, 67, "up"], [306, 117, 26, 46, "down"],
    [339, 86, 39, 69, "up"], [372, 98, 27, 47, "down"], [405, 66, 37, 64, "up"],
  ] as const;
  return <div className="vs-chart-stage" aria-label="Illustrative price-action diagram, not live market data">
    <div className="vs-chart-orbit" aria-hidden="true" />
    <figure className="vs-chart-frame">
      <div className="vs-chart-head"><div><div className="vs-chart-title">Structure before signal</div><div className="vs-chart-caption">CONCEPTUAL PRICE-ACTION STUDY</div></div><span className="vs-chart-tag">ILLUSTRATIVE</span></div>
      <svg className="vs-chart-svg" viewBox="0 0 460 260" role="img" aria-labelledby="vayda-chart-title vayda-chart-desc">
        <title id="vayda-chart-title">Illustrative price action diagram</title>
        <desc id="vayda-chart-desc">A schematic sequence of candles, a marked area, and a confirmation path. This is not live market data.</desc>
        <defs>
          <pattern id="vs-grid" width="46" height="43" patternUnits="userSpaceOnUse"><path d="M 46 0 L 0 0 0 43" fill="none" stroke="rgba(205,214,198,.1)" strokeWidth="1" /></pattern>
          <linearGradient id="vs-area" x1="0" x2="1"><stop offset="0" stopColor="#d7bd7b" stopOpacity=".09"/><stop offset="1" stopColor="#d7bd7b" stopOpacity=".01"/></linearGradient>
        </defs>
        <rect x="0" y="0" width="460" height="230" fill="url(#vs-grid)" />
        <rect x="240" y="104" width="149" height="43" fill="url(#vs-area)" stroke="rgba(215,189,123,.34)" strokeDasharray="4 5" />
        <text x="247" y="99" fill="#c8b576" fontSize="8" letterSpacing="1.2" fontFamily="DM Mono, monospace">AREA OF INTEREST</text>
        <line className="vs-chart-scanline" x1="20" y1="20" x2="20" y2="222" stroke="#58e6d0" strokeOpacity=".68" strokeWidth="1" />
        <path className="vs-chart-trend" d="M20 210 C65 191 73 178 110 184 S151 154 179 164 S210 133 239 142 S267 112 300 120 S336 85 363 91 S397 53 433 41" fill="none" stroke="rgba(139,185,154,.56)" strokeWidth="1.3" strokeDasharray="4 6" />
        {candles.map(([x, y, h, wick, type], index) => <g key={index} className="vs-chart-candle" style={{ animationDelay: `${index * 55}ms` }}>
          <line x1={x + 7} y1={y - wick / 2} x2={x + 7} y2={y + wick / 2} stroke={type === "up" ? "#8bb99a" : "#bb9d62"} strokeOpacity=".85" />
          <rect x={x} y={y} width="14" height={h} fill={type === "up" ? "#8bb99a" : "#bb9d62"} fillOpacity={type === "up" ? ".78" : ".6"} />
        </g>)}
        <path className="vs-chart-confirmation" d="M270 162 L289 150 L307 156 L325 133 L343 137 L359 110 L377 115 L394 89" fill="none" stroke="#e1c77f" strokeWidth="2" />
        <circle className="vs-chart-confirmation-dot" cx="394" cy="89" r="4" fill="#e1c77f" />
        <path d="M20 230H440" stroke="rgba(235,220,181,.15)" />
        <text x="20" y="248" fill="#77817a" fontSize="8" letterSpacing="1" fontFamily="DM Mono, monospace">OBSERVE</text>
        <text x="190" y="248" fill="#77817a" fontSize="8" letterSpacing="1" fontFamily="DM Mono, monospace">WAIT FOR CONFIRMATION</text>
        <text x="385" y="248" fill="#77817a" fontSize="8" letterSpacing="1" fontFamily="DM Mono, monospace">DECIDE</text>
      </svg>
      <figcaption className="vs-chart-foot"><span><strong>SCHEMATIC</strong> · FOR EDUCATION ONLY</span><span>NOT LIVE MARKET DATA</span></figcaption>
    </figure>
  </div>;
}

function Home() {
  return <main>
    <section className="vs-home-hero">
      <div className="vs-hero-layout">
        <div className="vs-hero-copy">
          <div className="vs-hero-mark">A more deliberate way to learn the market</div>
          <h1>TRADE WITH <span>KNOWLEDGE.</span> EXECUTE WITH CONFIDENCE.</h1>
          <p>Learn the markets. Understand price action. Master confirmation. Build the discipline to trade independently.</p>
          <div className="vs-hero-actions">
            {isConfiguredPublicUrl(primaryCommunity) && <a href={primaryCommunity} target="_blank" rel="noopener noreferrer" className="vs-button" data-testid="link-home-community">Join Our Community <ArrowRight /></a>}
            <a href="/philosophy" className="vs-button vs-button-quiet" data-testid="link-home-philosophy">Our philosophy <ArrowDownRight /></a>
          </div>
          <div className="vs-hero-footnote">NO PROMISES. NO SHORTCUTS. JUST A PROCESS.</div>
        </div>
        <ChartIllustration />
      </div>
    </section>
    <div className="vs-shell vs-ticker" data-reveal><span>STRUCTURE</span><b>PRICE ACTION · CONFIRMATION · DISCIPLINE</b><span>INDEPENDENCE</span></div>

    <section className="vs-section">
      <div className="vs-shell">
        <div className="vs-section-heading" data-reveal><div><div className="vs-eyebrow">THE VAYDA APPROACH</div><h2>Clarity is built, not called.</h2></div><p>Markets are uncertain. Your process does not have to be. VAYDA brings practical concepts into focus so traders can make considered decisions for themselves.</p></div>
        <div className="vs-pillars vs-stagger" data-reveal>
          <article className="vs-pillar"><span className="vs-index">01 / READ</span><h3>Understand structure</h3><p>Learn to observe price behavior, identify meaningful context, and separate a useful idea from market noise.</p><span className="vs-pillar-sign" aria-hidden="true">↗</span></article>
          <article className="vs-pillar"><span className="vs-index">02 / WAIT</span><h3>Require confirmation</h3><p>Patience is part of the setup. Build a habit of waiting for your conditions instead of anticipating them.</p><span className="vs-pillar-sign" aria-hidden="true">⌁</span></article>
          <article className="vs-pillar"><span className="vs-index">03 / OWN</span><h3>Execute with discipline</h3><p>Use a repeatable framework, manage uncertainty, and take responsibility for each decision you make.</p><span className="vs-pillar-sign" aria-hidden="true">◌</span></article>
        </div>
      </div>
    </section>

    <section className="vs-quote-band" data-reveal><div className="vs-eyebrow">THE RULE THAT KEEPS US GROUNDED</div><blockquote>NO CONFIRMATION,<br />NO ENTRY.</blockquote><p>Process over prediction. Every time.</p></section>

    <section className="vs-section vs-section-tight">
      <div className="vs-shell">
        <div className="vs-section-heading" data-reveal><div><div className="vs-eyebrow">FIND YOUR NEXT STEP</div><h2>Learn first. Participate with purpose.</h2></div><p>Start with the principles. Then choose the community entry point that fits what you want to explore.</p></div>
        <div className="vs-pathways vs-stagger" data-reveal>
          <a href="/education" className="vs-path-card" data-testid="link-home-education"><div className="vs-path-top"><span>01 / LEARN</span><BookOpen size={17} /></div><h3>Build your understanding</h3><p>Explore the learning approach behind VAYDA. Educational channel details will be added when confirmed.</p><span className="vs-path-action">Explore Free Education <ArrowRight /></span></a>
          <a href="/market-analysis" className="vs-path-card secondary" data-testid="link-home-market-analysis"><div className="vs-path-top"><span>02 / OBSERVE</span><Compass size={17} /></div><h3>Put context first</h3><p>Learn how to read analysis with care, identify confirmation, and leave room for uncertainty.</p><span className="vs-path-action">Access Market Analysis <ArrowRight /></span></a>
          <a href="/community" className="vs-path-card" data-testid="link-home-community-guide"><div className="vs-path-top"><span>03 / CONNECT</span><Compass size={17} /></div><h3>Find your people</h3><p>See how community access works and find the verified starting point.</p><span className="vs-path-action">Community guide <ArrowRight /></span></a>
        </div>
      </div>
    </section>
    <div className="vs-shell vs-disclaimer" role="note" data-reveal><ShieldCheck size={15} style={{ verticalAlign: "middle", marginRight: 8 }} />VAYDA provides educational content, not personalized financial advice. Trading carries risk, including the possible loss of capital.</div>
  </main>;
}

export function Current() {
  usePublicPageMotion();
  return <div className="vayda-site is-home"><Header /><div className="vs-page-transition"><Home /></div><Footer /></div>;
}
