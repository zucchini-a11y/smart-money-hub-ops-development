import { useEffect, useState, type ReactNode, type AnchorHTMLAttributes } from 'react';
import { Link, useLocation } from 'wouter';
import { ArrowDownRight, ArrowRight, ArrowUpRight, BookOpen, Compass, Mail, ShieldCheck, X } from 'lucide-react';
import { isConfiguredPublicUrl, publicSiteLinks } from './config';
import './public-site.css';

const pages = [
  { href: '/', label: 'Home' },
  { href: '/about', label: 'About' },
  { href: '/education', label: 'Education' },
  { href: '/market-analysis', label: 'Market Analysis' },
  { href: '/philosophy', label: 'Philosophy' },
  { href: '/community', label: 'Community' },
  { href: '/contact', label: 'Contact' },
];
const assetBase = import.meta.env.BASE_URL.endsWith('/')
  ? import.meta.env.BASE_URL
  : `${import.meta.env.BASE_URL}/`;
const logoSrc = `${assetBase}vayda-logo.png`;

const pageMetadata: Record<string, { title: string; description: string }> = {
  '/': {
    title: 'VAYDA Smart Money Hub | Trading Education & Analysis',
    description: 'Learn price action, confirmation, and disciplined trading with VAYDA Smart Money Hub. Build knowledge and execute with confidence.',
  },
  '/about': {
    title: 'About VAYDA | Smart Money Hub Trading Education',
    description: 'Learn about VAYDA Smart Money Hub and its education-first approach to price action, confirmation, and independent trading decisions.',
  },
  '/education': {
    title: 'Free Trading Education | VAYDA Smart Money Hub',
    description: 'Explore practical trading education on market context, price action, confirmation, and disciplined execution from VAYDA Smart Money Hub.',
  },
  '/market-analysis': {
    title: 'Market Analysis | VAYDA Smart Money Hub',
    description: 'Learn to read market analysis through context, confirmation, and uncertainty. VAYDA content is educational, not live trade advice.',
  },
  '/philosophy': {
    title: 'No Confirmation, No Entry | VAYDA Philosophy',
    description: 'Discover the VAYDA trading philosophy: observe price action, wait for confirmation, and make deliberate decisions in uncertain markets.',
  },
  '/community': {
    title: 'VAYDA Trading Community | Smart Money Hub',
    description: 'Find the verified VAYDA Smart Money Hub community entry point and learn how to participate with an education-first mindset.',
  },
  '/contact': {
    title: 'Contact VAYDA | Smart Money Hub',
    description: 'Find verified ways to connect with VAYDA Smart Money Hub. Official contact details will appear here when confirmed.',
  },
};

function updateMeta(attribute: 'name' | 'property', key: string, content: string) {
  let element = document.head.querySelector<HTMLMetaElement>(`meta[${attribute}="${key}"]`);
  if (!element) {
    element = document.createElement('meta');
    element.setAttribute(attribute, key);
    document.head.appendChild(element);
  }
  element.content = content;
}

function usePageMetadata(path: string) {
  useEffect(() => {
    const metadata = pageMetadata[path] ?? pageMetadata['/'];
    const canonicalUrl = `https://smartmoneyhub.tech${path === '/' ? '/' : path}`;
    document.title = metadata.title;
    updateMeta('name', 'description', metadata.description);
    updateMeta('property', 'og:title', metadata.title);
    updateMeta('property', 'og:description', metadata.description);
    updateMeta('property', 'og:url', canonicalUrl);
    updateMeta('name', 'twitter:title', metadata.title);
    updateMeta('name', 'twitter:description', metadata.description);

    let canonical = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if (!canonical) {
      canonical = document.createElement('link');
      canonical.rel = 'canonical';
      document.head.appendChild(canonical);
    }
    canonical.href = canonicalUrl;
  }, [path]);
}

function usePublicPageMotion(path: string) {
  useEffect(() => {
    const root = document.querySelector<HTMLElement>('.vayda-site');
    if (!root) return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });

    let observer: IntersectionObserver | undefined;
    const revealTargets = root.querySelectorAll<HTMLElement>('[data-reveal]');
    if (!reduceMotion && 'IntersectionObserver' in window) {
      root.classList.add('vs-motion-ready');
      observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer?.unobserve(entry.target);
          }
        });
      }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
      revealTargets.forEach((target) => observer?.observe(target));
    } else {
      revealTargets.forEach((target) => target.classList.add('is-visible'));
    }

    const chartStage = root.querySelector<HTMLElement>('.vs-chart-stage');
    const chartFrame = root.querySelector<HTMLElement>('.vs-chart-frame');
    let animationFrame = 0;
    const updateMotion = () => {
      animationFrame = 0;
      revealTargets.forEach((target) => {
        if (!target.classList.contains('is-visible') && target.getBoundingClientRect().top <= window.innerHeight * 0.92) {
          target.classList.add('is-visible');
          observer?.unobserve(target);
        }
      });
      if (chartStage && chartFrame) {
        if (window.innerWidth <= 760) {
          chartFrame.style.setProperty('--vs-parallax-y', '0px');
          return;
        }
        const rect = chartStage.getBoundingClientRect();
        const distanceFromCenter = (rect.top + rect.height / 2 - window.innerHeight / 2) / window.innerHeight;
        const offset = Math.max(-12, Math.min(12, distanceFromCenter * -12));
        chartFrame.style.setProperty('--vs-parallax-y', `${offset.toFixed(1)}px`);
      }
    };
    const requestMotionUpdate = () => {
      if (!animationFrame) animationFrame = window.requestAnimationFrame(updateMotion);
    };
    if (!reduceMotion) {
      window.addEventListener('scroll', requestMotionUpdate, { passive: true });
      window.addEventListener('resize', requestMotionUpdate);
      requestMotionUpdate();
    }

    return () => {
      observer?.disconnect();
      window.removeEventListener('scroll', requestMotionUpdate);
      window.removeEventListener('resize', requestMotionUpdate);
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
    };
  }, [path]);
}

function ExternalLink({ href, children, className = '', ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; children: ReactNode }) {
  return <a href={href} target="_blank" rel="noopener noreferrer" className={className} {...props}>{children}</a>;
}

function Header({ location }: { location: string }) {
  const [open, setOpen] = useState(false);
  return <header className="vs-header">
    <div className="vs-header-inner">
      <Link href="/" className="vs-brand" aria-label="VAYDA Smart Money Hub home" onClick={() => setOpen(false)} data-testid="link-public-home-brand">
        <img src={logoSrc} alt="VAYDA Smart Money Hub logo" width="48" height="48" />
        <span><span className="vs-brand-word">VAYDA</span><span className="vs-brand-sub">SMART MONEY HUB</span></span>
      </Link>
      <button className="vs-menu-toggle" type="button" aria-label={open ? 'Close navigation menu' : 'Open navigation menu'} aria-expanded={open} aria-controls="vayda-public-nav" onClick={() => setOpen(!open)} data-testid="button-public-menu">
        {open ? <X size={18} /> : <><span /><span /></>}
      </button>
      <nav id="vayda-public-nav" className={`vs-nav ${open ? 'is-open' : ''}`} aria-label="Public navigation">
        {pages.slice(1).map((page) => <Link key={page.href} href={page.href} aria-current={location === page.href ? 'page' : undefined} onClick={() => setOpen(false)} data-testid={`link-public-${page.href.slice(1) || 'home'}`}>{page.label}</Link>)}
        {isConfiguredPublicUrl(publicSiteLinks.primaryCommunity) && <ExternalLink href={publicSiteLinks.primaryCommunity} className="vs-nav-cta" data-testid="link-public-community-entry">Enter community <ArrowUpRight size={13} /></ExternalLink>}
        <Link href="/sign-up" className="vs-create-account" onClick={() => setOpen(false)} data-testid="link-public-create-account">Create account <ArrowUpRight size={13} /></Link>
        <Link href="/login" className="vs-staff-link" onClick={() => setOpen(false)} data-testid="link-public-login">Sign in</Link>
      </nav>
    </div>
  </header>;
}

function Footer() {
  return <footer className="vs-footer">
    <div className="vs-shell vs-footer-top">
      <div className="vs-footer-brand">
        <Link href="/" className="vs-brand" aria-label="VAYDA home" data-testid="link-public-footer-home">
          <img src={logoSrc} alt="" width="48" height="48" />
          <span><span className="vs-brand-word">VAYDA</span><span className="vs-brand-sub">SMART MONEY HUB</span></span>
        </Link>
        <p>Market education built around observation, confirmation, and deliberate execution.</p>
      </div>
      <div className="vs-footer-col"><h2>Explore</h2><div className="vs-footer-links">{pages.slice(1).map((page) => <Link key={page.href} href={page.href} data-testid={`link-footer-${page.href.slice(1)}`}>{page.label}</Link>)}</div></div>
      <div className="vs-footer-col"><h2>Start here</h2><div className="vs-footer-links">
        <Link href="/philosophy" data-testid="link-footer-philosophy">Our philosophy</Link>
        <Link href="/community" data-testid="link-footer-community">Community access</Link>
        <Link href="/education" data-testid="link-footer-education">Learning approach</Link>
        <Link href="/login" data-testid="link-footer-login">Sign in</Link>
      </div></div>
    </div>
    <div className="vs-shell vs-footer-bottom"><span>VAYDA SMART MONEY HUB · EDUCATION FIRST</span><span><strong>Trading involves risk.</strong> Education is not financial advice.</span></div>
  </footer>;
}

function ChartIllustration() {
  const candles = [
    [42, 183, 25, 45, 'down'], [75, 167, 34, 54, 'up'], [108, 177, 28, 44, 'down'],
    [141, 144, 38, 62, 'up'], [174, 151, 28, 48, 'down'], [207, 121, 37, 64, 'up'],
    [240, 135, 25, 44, 'down'], [273, 110, 40, 67, 'up'], [306, 117, 26, 46, 'down'],
    [339, 86, 39, 69, 'up'], [372, 98, 27, 47, 'down'], [405, 66, 37, 64, 'up'],
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
        <path className="vs-chart-trend" d="M20 210 C65 191 73 178 110 184 S151 154 179 164 S210 133 239 142 S267 112 300 120 S336 85 363 91 S397 53 433 41" fill="none" stroke="rgba(139,185,154,.56)" strokeWidth="1.3" strokeDasharray="4 6" />
        {candles.map(([x, y, h, wick, type], index) => <g key={index} className="vs-chart-candle" style={{ animationDelay: `${index * 55}ms` }}>
          <line x1={x + 7} y1={y - wick / 2} x2={x + 7} y2={y + wick / 2} stroke={type === 'up' ? '#8bb99a' : '#bb9d62'} strokeOpacity=".85" />
          <rect x={x} y={y} width="14" height={h} fill={type === 'up' ? '#8bb99a' : '#bb9d62'} fillOpacity={type === 'up' ? '.78' : '.6'} />
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
  return <>
    <main>
      <section className="vs-home-hero">
        <div className="vs-hero-layout">
          <div className="vs-hero-copy">
            <div className="vs-hero-mark">A more deliberate way to learn the market</div>
            <h1>TRADE WITH <span>KNOWLEDGE.</span> EXECUTE WITH CONFIDENCE.</h1>
            <p>Learn the markets. Understand price action. Master confirmation. Build the discipline to trade independently.</p>
            <div className="vs-hero-actions">
              {isConfiguredPublicUrl(publicSiteLinks.primaryCommunity) && <ExternalLink href={publicSiteLinks.primaryCommunity} className="vs-button" data-testid="link-home-community">Join Our Community <ArrowRight /></ExternalLink>}
              <Link href="/philosophy" className="vs-button vs-button-quiet" data-testid="link-home-philosophy">Our philosophy <ArrowDownRight /></Link>
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
            <Link href="/education" className="vs-path-card" data-testid="link-home-education"><div className="vs-path-top"><span>01 / LEARN</span><BookOpen size={17} /></div><h3>Build your understanding</h3><p>Explore the learning approach behind VAYDA. Educational channel details will be added when confirmed.</p><span className="vs-path-action">Explore Free Education <ArrowRight /></span></Link>
            <Link href="/market-analysis" className="vs-path-card secondary" data-testid="link-home-market-analysis"><div className="vs-path-top"><span>02 / OBSERVE</span><Compass size={17} /></div><h3>Put context first</h3><p>Learn how to read analysis with care, identify confirmation, and leave room for uncertainty.</p><span className="vs-path-action">Access Market Analysis <ArrowRight /></span></Link>
            <Link href="/community" className="vs-path-card" data-testid="link-home-community-guide"><div className="vs-path-top"><span>03 / CONNECT</span><Compass size={17} /></div><h3>Find your people</h3><p>See how community access works and find the verified starting point.</p><span className="vs-path-action">Community guide <ArrowRight /></span></Link>
          </div>
        </div>
      </section>
      <div className="vs-shell vs-disclaimer" role="note" data-reveal><ShieldCheck size={15} style={{ verticalAlign: 'middle', marginRight: 8 }} />VAYDA provides educational content, not personalized financial advice. Trading carries risk, including the possible loss of capital.</div>
    </main>
  </>;
}

function PageHero({ eyebrow, title, summary }: { eyebrow: string; title: string; summary: string }) {
  return <section className="vs-page-hero" data-reveal><div className="vs-shell"><div className="vs-eyebrow">{eyebrow}</div><h1>{title}</h1><p>{summary}</p></div></section>;
}

function Placeholder({ title, body, icon = <BookOpen /> }: { title: string; body: string; icon?: ReactNode }) {
  return <section className="vs-placeholder" aria-label={title}><div className="vs-placeholder-mark">{icon}</div><div><h2>{title}</h2><p>{body} <em>This destination is not available yet.</em></p></div></section>;
}

function About() {
  return <main><PageHero eyebrow="ABOUT VAYDA" title="A steadier way to meet the markets." summary="VAYDA Smart Money Hub is a practical trading education brand for people who want to understand price action and make decisions with discipline." />
    <section className="vs-page-content"><div className="vs-shell vs-reading-grid" data-reveal>
      <aside className="vs-side-note">OUR POINT OF VIEW<br /><br />Better questions before bigger opinions.</aside>
      <article className="vs-reading">
        <h2>Education before expectation.</h2>
        <p>Markets do not owe anyone a result. VAYDA exists to help retail traders build a stronger grasp of how price behaves, how confirmation can shape a decision, and why a clear process matters when outcomes are uncertain.</p>
        <p>We believe useful education should make a person more capable of thinking independently—not more dependent on someone else's certainty.</p>
        <h2>Practical, not promotional.</h2>
        <p>Our focus is on concepts traders can study and apply thoughtfully: market structure, price action, confirmation, and the discipline to follow a plan. We avoid promises and present educational material as education, not as a prediction or a personal recommendation.</p>
        <ul className="vs-reading-list"><li><span className="vs-index">01</span><span>Learn to observe before acting.</span></li><li><span className="vs-index">02</span><span>Use confirmation as a condition, not a hope.</span></li><li><span className="vs-index">03</span><span>Own your process and your decisions.</span></li></ul>
        <p><strong>Our measure of progress is understanding—not a promised outcome.</strong></p>
      </article>
    </div></section>
  </main>;
}

function Education() {
  return <main><PageHero eyebrow="EDUCATION" title="Learn to read the story in price." summary="A practical learning direction centered on price action, market context, confirmation, and disciplined execution." />
    <section className="vs-page-content"><div className="vs-shell">
      <div className="vs-method-grid vs-stagger" data-reveal>
        <article className="vs-method"><span className="vs-index">01 / CONTEXT</span><h3>Read the larger picture</h3><p>Study how structure and surrounding context can shape the way a price move is understood.</p></article>
        <article className="vs-method"><span className="vs-index">02 / PRICE ACTION</span><h3>Observe behavior</h3><p>Focus on what price is doing, where it is reacting, and what conditions may still be missing.</p></article>
        <article className="vs-method"><span className="vs-index">03 / CONFIRMATION</span><h3>Wait for evidence</h3><p>Learn why an idea and a confirmed condition are not the same thing. Patience is part of the method.</p></article>
        <article className="vs-method"><span className="vs-index">04 / DISCIPLINE</span><h3>Build a repeatable practice</h3><p>Review decisions and follow a considered plan rather than letting urgency choose the next step.</p></article>
      </div>
      {isConfiguredPublicUrl(publicSiteLinks.educationChannel)
        ? <div className="vs-community-option"><div><h2>VAYDA Education</h2><p>Official education channel</p></div><ExternalLink className="vs-button" href={publicSiteLinks.educationChannel} data-testid="link-education-channel">Open education channel <ArrowUpRight /></ExternalLink></div>
        : <div style={{ marginTop: 25 }} data-reveal><Placeholder title="Education channel coming into focus" body="Lessons and channel access will appear here once the official destination is configured." /></div>}
    </div></section>
  </main>;
}

function MarketAnalysis() {
  return <main><PageHero eyebrow="MARKET ANALYSIS" title="A framework for observation, not certainty." summary="Market analysis is most useful when it explains context, conditions, and uncertainty—not when it claims to know what happens next." />
    <section className="vs-page-content"><div className="vs-shell">
      <div className="vs-reading-grid" data-reveal><aside className="vs-side-note">A GOOD ANALYSIS<br /><br />Names the condition.<br />Acknowledges uncertainty.</aside>
        <article className="vs-reading"><h2>Context, then a point of view.</h2><p>VAYDA's educational lens looks for structure, price behavior, and confirmation. Analysis should make its assumptions legible and leave room for the market to do something unexpected.</p><p>No chart can remove uncertainty. Any example should be understood as a learning aid, not a live instruction or guarantee of an outcome.</p><h2>How to read an analysis</h2><ul className="vs-reading-list"><li><span className="vs-index">A</span><span>Notice the context being discussed.</span></li><li><span className="vs-index">B</span><span>Identify what would count as confirmation.</span></li><li><span className="vs-index">C</span><span>Consider what would invalidate the idea.</span></li></ul></article>
      </div>
      {isConfiguredPublicUrl(publicSiteLinks.marketAnalysisChannel)
        ? <div style={{ marginTop: 58 }} className="vs-community-option"><div><h2>Market Analysis</h2><p>Official analysis channel</p></div><ExternalLink className="vs-button" href={publicSiteLinks.marketAnalysisChannel} data-testid="link-market-analysis-channel">Open analysis channel <ArrowUpRight /></ExternalLink></div>
         : <div style={{ marginTop: 58 }} data-reveal><Placeholder title="Market analysis updates are not connected yet" body="The official Market Analysis channel has not been supplied. We will add the verified destination when it is available." icon={<Compass />} /></div>}
    </div></section>
  </main>;
}

function Philosophy() {
  return <main><PageHero eyebrow="PHILOSOPHY" title="Process is the part you can practice." summary="A clear trading philosophy does not predict the market. It helps you decide what you will require before you act." />
    <section className="vs-quote-band" data-reveal><div className="vs-eyebrow">THE VAYDA PRINCIPLE</div><blockquote>NO CONFIRMATION,<br />NO ENTRY.</blockquote><p>A simple rule. A deliberate habit.</p></section>
    <section className="vs-page-content"><div className="vs-shell vs-reading-grid" data-reveal><aside className="vs-side-note">THE WORK IS IN THE WAIT.</aside><article className="vs-reading">
      <h2>We do not confuse a possibility with a plan.</h2><p>An idea can be interesting and still not be ready. Confirmation means waiting for the conditions you chose to appear, rather than acting because a move feels overdue.</p>
      <h2>Discipline is a practice, not a personality.</h2><p>It is built in small decisions: defining conditions, being willing to stand aside, and reviewing what happened without rewriting the plan after the fact.</p>
      <h2>Independence is the goal.</h2><p>Education should support informed judgment. VAYDA does not promise that any framework will produce a particular result. Each trader remains responsible for their own decisions, risk, and circumstances.</p>
      <div className="vs-disclaimer">Trading involves significant risk. Educational material is general in nature and is not financial advice, a trade recommendation, or a guarantee of performance.</div>
    </article></div></section>
  </main>;
}

function Community() {
  return <main><PageHero eyebrow="COMMUNITY" title="Learn alongside people who value the process." summary="Community can make learning more thoughtful when the focus stays on understanding, preparation, and disciplined decisions." />
    <section className="vs-page-content"><div className="vs-shell" data-reveal>
      <div className="vs-reading" style={{ marginBottom: 45 }}><h2>Start with the official entry point.</h2><p>Join the VAYDA community through the verified primary community link. Take time to understand the space and its educational context before deciding what is right for you.</p></div>
      {isConfiguredPublicUrl(publicSiteLinks.primaryCommunity) && <div className="vs-community-option"><div><h2>VAYDA Smart Money Hub</h2><p>Primary community entry point</p></div><ExternalLink className="vs-button" href={publicSiteLinks.primaryCommunity} data-testid="link-community-primary">Open community <ArrowUpRight /></ExternalLink></div>}
      {isConfiguredPublicUrl(publicSiteLinks.generalCommunity)
        ? <div className="vs-community-option"><div><h2>General community</h2><p>Official general community destination</p></div><ExternalLink className="vs-button" href={publicSiteLinks.generalCommunity} data-testid="link-general-community">Visit general community <ArrowUpRight /></ExternalLink></div>
        : <div style={{ marginTop: 18 }}><Placeholder title="General community details are not available yet" body="The owner has not supplied a separate general community destination. Use the primary entry point above in the meantime." icon={<Compass />} /></div>}
      {isConfiguredPublicUrl(publicSiteLinks.proSignalsAssistant) && <div className="vs-community-option"><div><h2>PRO Signals access</h2><p>For people specifically looking to access PRO Signals.</p></div><ExternalLink className="vs-button" href={publicSiteLinks.proSignalsAssistant} data-testid="link-community-pro-signals">Access PRO Signals <ArrowUpRight /></ExternalLink></div>}
      <div className="vs-disclaimer">No performance claims or trading outcomes are implied by community participation. Trading involves risk; make decisions based on your own circumstances.</div>
    </div></section>
  </main>;
}

function Contact() {
  return <main><PageHero eyebrow="CONTACT" title="A good question is a useful beginning." summary="We want to make it easy to find the right place to learn or participate. Verified contact details will be shown here when provided." />
    <section className="vs-page-content"><div className="vs-shell" data-reveal>
      <div className="vs-reading" style={{ marginBottom: 40 }}><h2>Looking for the community?</h2><p>Use the primary community entry point for general access. For direct contact, the owner has not yet supplied a verified contact destination.</p></div>
      {isConfiguredPublicUrl(publicSiteLinks.primaryCommunity) && <div className="vs-community-option"><div><h2>Community entry</h2><p>Use the verified main community link.</p></div><ExternalLink className="vs-button" href={publicSiteLinks.primaryCommunity} data-testid="link-contact-community">Open community <ArrowUpRight /></ExternalLink></div>}
      {isConfiguredPublicUrl(publicSiteLinks.contactUrl) && <div className="vs-community-option"><div><h2>Contact VAYDA</h2><p>Verified contact destination</p></div><ExternalLink className="vs-button" href={publicSiteLinks.contactUrl} data-testid="link-contact-destination">Open contact page <ArrowUpRight /></ExternalLink></div>}
      {publicSiteLinks.contactEmail && <div className="vs-community-option"><div><h2>Email VAYDA</h2><p>{publicSiteLinks.contactEmail}</p></div><a className="vs-button" href={`mailto:${encodeURIComponent(publicSiteLinks.contactEmail)}`} data-testid="link-contact-email">Compose email <Mail /></a></div>}
      {!isConfiguredPublicUrl(publicSiteLinks.contactUrl) && !publicSiteLinks.contactEmail && <div style={{ marginTop: 18 }}><Placeholder title="Direct contact details are not available yet" body="The owner has not supplied a contact URL or email address. We will add verified details when available." icon={<Mail />} /></div>}
    </div></section>
  </main>;
}

export default function PublicSite() {
  const [location] = useLocation();
  const path = location.replace(/\/+$/, '') || '/';
  usePageMetadata(path);
  usePublicPageMotion(path);
  const exactPublicPath = pages.some((page) => page.href === path);
  if (!exactPublicPath) return null;
  const page = path === '/' ? <Home /> : path === '/about' ? <About /> : path === '/education' ? <Education /> : path === '/market-analysis' ? <MarketAnalysis /> : path === '/philosophy' ? <Philosophy /> : path === '/community' ? <Community /> : <Contact />;
  return <div className="vayda-site"><Header location={path} /><div className="vs-page-transition" key={path}>{page}</div><Footer /></div>;
}
