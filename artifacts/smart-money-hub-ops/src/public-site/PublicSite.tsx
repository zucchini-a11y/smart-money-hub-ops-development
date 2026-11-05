import { useEffect, useState, type ReactNode, type AnchorHTMLAttributes } from 'react';
import { Link, useLocation } from 'wouter';
import { ArrowDownRight, ArrowRight, ArrowUpRight, BookOpen, Compass, Mail, X } from 'lucide-react';
import { isConfiguredPublicUrl, publicSiteLinks } from './config';
import { PublicSupportWidget } from '../WebsiteSupport';
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

type PublicGsapRuntime = { gsap: any; ScrollTrigger: any };
let publicGsapRuntimePromise: Promise<PublicGsapRuntime> | null = null;

function loadPublicGsapRuntime(): Promise<PublicGsapRuntime> {
  const browser = window as typeof window & { gsap?: any; ScrollTrigger?: any };
  if (browser.gsap && browser.ScrollTrigger) {
    return Promise.resolve({ gsap: browser.gsap, ScrollTrigger: browser.ScrollTrigger });
  }
  if (!publicGsapRuntimePromise) {
    const loadScript = (src: string) => new Promise<void>((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => {
        script.remove();
        reject(new Error('Animation library unavailable'));
      };
      document.head.appendChild(script);
    });
    publicGsapRuntimePromise = loadScript('https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js')
      .then(() => loadScript('https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js'))
      .then(() => {
        const runtime = window as typeof window & { gsap?: any; ScrollTrigger?: any };
        if (!runtime.gsap || !runtime.ScrollTrigger) throw new Error('Animation library unavailable');
        return { gsap: runtime.gsap, ScrollTrigger: runtime.ScrollTrigger };
      })
      .catch((error: unknown) => {
        publicGsapRuntimePromise = null;
        throw error;
      });
  }
  return publicGsapRuntimePromise;
}

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

    const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const reduceMotion = motionPreference.matches;
    let hashScrollFrame = 0;
    const scrollToCurrentHash = () => {
      const anchorId = decodeURIComponent(window.location.hash.slice(1));
      const anchorTarget = anchorId ? document.getElementById(anchorId) : null;
      if (!anchorTarget) return;
      if (hashScrollFrame) window.cancelAnimationFrame(hashScrollFrame);
      hashScrollFrame = window.requestAnimationFrame(() => {
        anchorTarget.scrollIntoView({ behavior: 'auto', block: 'start' });
      });
    };
    if (window.location.hash) {
      scrollToCurrentHash();
    } else {
      window.scrollTo({ top: 0, behavior: 'auto' });
    }
    window.addEventListener('hashchange', scrollToCurrentHash);

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

    const header = root.querySelector<HTMLElement>('.vs-header');
    let animationFrame = 0;
    const updateMotion = () => {
      animationFrame = 0;
      const scrollY = window.scrollY || window.pageYOffset;
      const shouldBlurHeader = scrollY > 12;
      if (header?.classList.contains('is-scrolled') !== shouldBlurHeader) {
        header?.classList.toggle('is-scrolled', shouldBlurHeader);
      }
    };
    const requestMotionUpdate = () => {
      if (!animationFrame) animationFrame = window.requestAnimationFrame(updateMotion);
    };
    window.addEventListener('scroll', requestMotionUpdate, { passive: true });
    requestMotionUpdate();

    let cancelled = false;
    let gsapContext: { revert: () => void } | undefined;
    if (path === '/' && !reduceMotion) {
      void (async () => {
        try {
          const { gsap: engine, ScrollTrigger } = await loadPublicGsapRuntime();
          if (cancelled) return;
          if (!engine?.registerPlugin || !engine?.context || !ScrollTrigger) return;
          engine.registerPlugin(ScrollTrigger);
          gsapContext = engine.context(() => {
            const marquee = root.querySelector<HTMLElement>('.vs-marquee-track');
            const marqueeTrigger = root.querySelector<HTMLElement>('.vs-marquee');
            if (marquee && marqueeTrigger) {
              engine.to(marquee, {
                xPercent: -22,
                ease: 'none',
                scrollTrigger: { trigger: marqueeTrigger, start: 'top bottom', end: 'bottom top', scrub: 0.8 },
              });
            }
            const statementWords = root.querySelectorAll<HTMLElement>('.vs-statement-word');
            const statementTrigger = root.querySelector<HTMLElement>('.vs-statement');
            if (statementWords.length && statementTrigger) {
              engine.fromTo(statementWords, { opacity: 0.22, y: 14 }, {
                opacity: 1, y: 0, stagger: 0.09, ease: 'power2.out',
                scrollTrigger: { trigger: statementTrigger, start: 'top 76%', end: 'bottom 52%', scrub: 0.7 },
              });
            }
            const media = engine.matchMedia();
            media.add('(min-width: 761px)', () => {
              const stage = root.querySelector<HTMLElement>('.vs-approach-stage');
              const steps = root.querySelectorAll<HTMLElement>('.vs-learning-step');
              if (!stage || !steps.length) return;
              const timeline = engine.timeline({
                scrollTrigger: {
                  trigger: stage,
                  start: 'top top+=78',
                  end: `+=${steps.length * 72}%`,
                  pin: true,
                  scrub: 0.7,
                  anticipatePin: 1,
                },
              });
              steps.forEach((step: HTMLElement, index: number) => {
                timeline.fromTo(step, { opacity: 0.35, y: 12 }, { opacity: 1, y: 0, duration: 0.7 }, index);
              });
              return () => timeline.scrollTrigger?.kill();
            });
            return () => media.revert();
          }, root);
        } catch {
          gsapContext?.revert();
          root.querySelectorAll<HTMLElement>('.vs-statement-word, .vs-learning-step, .vs-marquee-track').forEach((element) => {
            element.style.removeProperty('opacity');
            element.style.removeProperty('transform');
          });
          // Content remains fully visible and the page remains usable without GSAP.
        }
      })();
    }

    return () => {
      cancelled = true;
      gsapContext?.revert();
      observer?.disconnect();
      window.removeEventListener('scroll', requestMotionUpdate);
      window.removeEventListener('hashchange', scrollToCurrentHash);
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      if (hashScrollFrame) window.cancelAnimationFrame(hashScrollFrame);
      header?.classList.remove('is-scrolled');
      root.classList.remove('vs-motion-ready');
    };
  }, [path]);
}

function ExternalLink({ href, children, className = '', ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; children: ReactNode }) {
  return <a href={href} target="_blank" rel="noopener noreferrer" className={className} {...props}>{children}</a>;
}

function Header({ location }: { location: string }) {
  const [open, setOpen] = useState(false);
  const isHome = location === '/';
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
        {isHome ? <>
          <a href="#approach" onClick={() => setOpen(false)} data-testid="link-public-approach">Approach</a>
          <a href="#curriculum" onClick={() => setOpen(false)} data-testid="link-public-curriculum">Curriculum</a>
          <a href="#principles" onClick={() => setOpen(false)} data-testid="link-public-principles">Principles</a>
        </> : pages.slice(1).map((page) => <Link key={page.href} href={page.href} aria-current={location === page.href ? 'page' : undefined} onClick={() => setOpen(false)} data-testid={`link-public-${page.href.slice(1) || 'home'}`}>{page.label}</Link>)}
        {isConfiguredPublicUrl(publicSiteLinks.primaryCommunity) && <ExternalLink href={publicSiteLinks.primaryCommunity} className="vs-nav-cta" data-testid="link-public-community-entry">{isHome ? 'Join' : 'Enter community'} <ArrowUpRight size={13} /></ExternalLink>}
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
        </defs>
        <rect x="0" y="0" width="460" height="230" fill="url(#vs-grid)" />
        <rect x="240" y="104" width="149" height="43" fill="none" stroke="rgba(215,189,123,.34)" strokeDasharray="4 5" />
        <text x="247" y="99" fill="#c8b576" fontSize="8" letterSpacing="1.2" fontFamily="DM Mono, monospace">AREA OF INTEREST</text>
        <line className="vs-chart-scanline" x1="20" y1="20" x2="20" y2="222" stroke="#58e6d0" strokeOpacity=".68" strokeWidth="1" />
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
      <figcaption className="vs-chart-foot"><span>Illustrative example · not market data.</span><span>FOR EDUCATION ONLY</span></figcaption>
    </figure>
  </div>;
}

function Home() {
  return <>
    <main>
      <section className="vs-home-hero">
        <div className="vs-hero-layout">
          <div className="vs-hero-copy">
          <div className="vs-hero-mark">[ Trading education ]</div>
            <h1>Learn how<br />price really <span>moves.</span></h1>
            <p>Market education for people who would rather understand the conditions than chase the call.</p>
            <div className="vs-hero-actions">
              {isConfiguredPublicUrl(publicSiteLinks.primaryCommunity) && <ExternalLink href={publicSiteLinks.primaryCommunity} className="vs-button" data-testid="link-home-community">Join the community <ArrowRight /></ExternalLink>}
              <a href="#approach" className="vs-button vs-button-quiet" data-testid="link-home-approach">Explore the approach <ArrowDownRight /></a>
            </div>
            <div className="vs-hero-footnote">NO CONFIRMATION, NO ENTRY</div>
          </div>
          <div className="vs-hero-index" aria-hidden="true"><span>READ THE MARKET</span><span>OBSERVE / CONFIRM / DECIDE</span></div>
        </div>
      </section>
      <section className="vs-marquee" aria-label="Learning themes">
        <div className="vs-marquee-track"><span>STRUCTURE</span><i>·</i><span>LIQUIDITY</span><i>·</i><span>RISK</span><i>·</i><span>PROCESS</span><i>·</i><span>STRUCTURE</span><i>·</i><span>LIQUIDITY</span><i>·</i><span>RISK</span><i>·</i><span>PROCESS</span><i>·</i></div>
      </section>

      <section className="vs-approach vs-section" id="approach">
        <div className="vs-shell">
          <div className="vs-section-heading" data-reveal><div><div className="vs-eyebrow">01 / APPROACH</div><h2>Read the conditions.<br />Then make a decision.</h2></div><p>There is no shortcut around uncertainty. A useful framework helps you see what is happening, define what matters, and choose whether to act.</p></div>
          <div className="vs-approach-stage">
            <div className="vs-learning-steps">
              <article className="vs-learning-step"><span className="vs-index">01 / STRUCTURE</span><h3>Start with structure</h3><p>Place price in context. Notice the shape of the move before deciding what it might mean.</p></article>
              <article className="vs-learning-step"><span className="vs-index">02 / LIQUIDITY</span><h3>Let liquidity inform the picture</h3><p>Study where attention gathers and what price does around those areas. A level is context, not a promise.</p></article>
              <article className="vs-learning-step"><span className="vs-index">03 / RISK</span><h3>Put risk before entry</h3><p>Consider exposure and sizing before acting. Require confirmation, define what you are willing to risk, and stay willing to stand aside.</p></article>
            </div>
            <div className="vs-approach-visual"><ChartIllustration /></div>
          </div>
        </div>
      </section>

      <section className="vs-statement" data-reveal>
        <div className="vs-statement-inner"><div className="vs-eyebrow">A DIFFERENT KIND OF EDGE</div><p>{'The point is not to predict every move. It is to know what you are waiting for.'.split(' ').map((word, index) => <span className="vs-statement-word" key={`${word}-${index}`}>{word} </span>)}</p><span className="vs-statement-note">OBSERVE / CONFIRM / DECIDE</span></div>
      </section>

      <section className="vs-section vs-curriculum" id="curriculum">
        <div className="vs-shell">
          <div className="vs-section-heading" data-reveal><div><div className="vs-eyebrow">02 / CURRICULUM</div><h2>Four ideas.<br />One considered practice.</h2></div><p>Build a working vocabulary for reading price and making deliberate choices. Each topic is a lens; none removes uncertainty.</p></div>
          <div className="vs-curriculum-grid" data-reveal>
            <article className="vs-curriculum-item"><span className="vs-index">01 / MAP</span><h3>Market structure</h3><p>Read swings, shifts, and context to understand where price sits in the larger picture.</p><span className="vs-curriculum-mark">01</span></article>
            <article className="vs-curriculum-item"><span className="vs-index">02 / NOTICE</span><h3>Liquidity</h3><p>Explore how resting orders and areas of interest can shape the way price behaves.</p><span className="vs-curriculum-mark">02</span></article>
            <article className="vs-curriculum-item"><span className="vs-index">03 / DEFINE</span><h3>Risk and sizing</h3><p>Think about exposure before an idea becomes a position. Risk belongs in the plan from the start.</p><span className="vs-curriculum-mark">03</span></article>
            <article className="vs-curriculum-item"><span className="vs-index">04 / REPEAT</span><h3>Process and psychology</h3><p>Practice patience, review decisions honestly, and make room for a clear head.</p><span className="vs-curriculum-mark">04</span></article>
          </div>
        </div>
      </section>

      <section className="vs-principles vs-section" id="principles">
        <div className="vs-shell">
          <div className="vs-section-heading" data-reveal><div><div className="vs-eyebrow">03 / PRINCIPLES</div><h2>What we will not trade away.</h2></div><p>The method matters most when the outcome is uncertain. These are the standards that keep learning grounded.</p></div>
          <div className="vs-principles-list" data-reveal>
            <article><span className="vs-index">01</span><h3>Process over outcome</h3><p>A sound decision is not defined by one result. Work the plan; review the reasoning.</p></article>
            <article><span className="vs-index">02</span><h3>Risk before reward</h3><p>Capital is exposed to loss. Consider what is at stake before considering what might be gained.</p></article>
            <article><span className="vs-index">03</span><h3>Honest expectations</h3><p>Education can build understanding. It cannot promise a return or remove market risk.</p></article>
          </div>
        </div>
      </section>

      <section className="vs-home-cta" data-reveal>
        <div className="vs-home-cta-inner"><div><div className="vs-eyebrow">KEEP LEARNING, AT YOUR PACE</div><h2>Build a process<br />you can explain.</h2><p>Start with the principles. Stay curious. Decide for yourself.</p></div>
          {isConfiguredPublicUrl(publicSiteLinks.primaryCommunity) && <ExternalLink href={publicSiteLinks.primaryCommunity} className="vs-button" data-testid="link-home-cta-community">Join the Smart Money Hub <ArrowUpRight /></ExternalLink>}
        </div>
      </section>
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
      {publicSiteLinks.contactEmail && <div className="vs-community-option"><div><h2>Email VAYDA</h2><p>Open your email app to contact the team.</p></div><a className="vs-button" href={`mailto:${encodeURIComponent(publicSiteLinks.contactEmail)}`} data-testid="link-contact-email">Compose email <Mail /></a></div>}
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
  return <div className={`vayda-site${path === '/' ? ' is-home' : ' is-public'}`}><Header location={path} /><div className="vs-page-transition" key={path}>{page}</div><Footer /><PublicSupportWidget /></div>;
}
