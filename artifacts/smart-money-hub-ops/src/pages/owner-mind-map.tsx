import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import {
  ArrowDown, ArrowUpRight, Bot, BookOpen, Boxes, ChevronRight, CircleHelp,
  Command, Database, Globe2, Layers3, Network, Search, ShieldCheck, Sparkles,
  X,
} from 'lucide-react';
import './owner-mind-map.css';

type MapNode = {
  id: string;
  title: string;
  subtitle: string;
  group: GroupId;
  description: string;
  connects: string[];
  icon: typeof Bot;
};

const groups = [
  { id: 'portal', label: 'Portal experience', color: 'mint' },
  { id: 'bots', label: 'Bot experiences', color: 'amber' },
  { id: 'intelligence', label: 'Knowledge & intelligence', color: 'rose' },
  { id: 'foundation', label: 'Platform foundation', color: 'blue' },
] as const;

type GroupId = typeof groups[number]['id'];

const nodes: MapNode[] = [
  {
    id: 'owner-portal', title: 'Owner Portal', subtitle: 'Operations & oversight',
    group: 'portal', icon: Command,
    description: 'The private owner workspace: a single place to understand the product surface, review operations, and move between the portal’s tools.',
    connects: ['Member learning', 'Signals bot', 'Coach bot', 'Shared platform'],
  },
  {
    id: 'member-learning', title: 'Member learning', subtitle: 'Courses · progress · journal',
    group: 'portal', icon: BookOpen,
    description: 'The member-facing learning journey, bringing course content, progress, calendar, journal, and coaching into one coherent experience.',
    connects: ['Owner Portal', 'Coach bot', 'Knowledge library'],
  },
  {
    id: 'signals', title: 'Signals bot', subtitle: 'Market education & support',
    group: 'bots', icon: Network,
    description: 'A Telegram-oriented learning surface for market education and member support. This map describes product relationships, not current operation.',
    connects: ['Owner Portal', 'Member learning', 'Shared knowledge'],
  },
  {
    id: 'coach', title: 'Coach bot', subtitle: 'Guided reflection & check-ins',
    group: 'bots', icon: Sparkles,
    description: 'A conversational coaching experience that can support member reflection and learning, connected conceptually to shared knowledge and progress.',
    connects: ['Owner Portal', 'Member learning', 'Knowledge library'],
  },
  {
    id: 'knowledge', title: 'Knowledge library', subtitle: 'Lessons · references · context',
    group: 'intelligence', icon: Layers3,
    description: 'Reusable learning material and product context that can inform member-facing experiences without implying a live data connection.',
    connects: ['Member learning', 'Signals bot', 'Coach bot'],
  },
  {
    id: 'shared-platform', title: 'Shared platform', subtitle: 'Identity · services · storage',
    group: 'foundation', icon: Database,
    description: 'The conceptual foundation beneath the portal and bot-related modules: identity, shared application services, and durable product data.',
    connects: ['Owner Portal', 'Signals bot', 'Coach bot'],
  },
];

const groupById = new Map(groups.map((group) => [group.id, group]));

function ParticleField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    let width = 0;
    let height = 0;
    let dpr = 1;
    let tick = 0;
    let particles: { x: number; y: number; z: number; phase: number }[] = [];

    const resize = () => {
      window.cancelAnimationFrame(frame);
      const bounds = canvas.getBoundingClientRect();
      width = bounds.width;
      height = bounds.height;
      dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      particles = Array.from({ length: Math.min(180, Math.floor((width * height) / 7200)) }, (_, index) => ({
        x: Math.random() * width,
        y: Math.random() * height,
        z: Math.random(),
        phase: index * 1.73,
      }));
      draw();
    };

    const draw = () => {
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, width, height);
      const centerX = width * 0.52;
      const centerY = height * 0.49;
      for (const point of particles) {
        const drift = reduced.matches ? 0 : Math.sin(tick * 0.006 + point.phase) * 5;
        const x = point.x + drift;
        const y = point.y + Math.cos(tick * 0.004 + point.phase) * (reduced.matches ? 0 : 3);
        const alpha = 0.12 + point.z * 0.34;
        const distance = Math.hypot((x - centerX) / width, (y - centerY) / height);
        context.fillStyle = distance < 0.34
          ? `rgba(132, 236, 209, ${alpha})`
          : `rgba(159, 178, 188, ${alpha * 0.56})`;
        context.beginPath();
        context.arc(x, y, 0.45 + point.z * 1.15, 0, Math.PI * 2);
        context.fill();
      }
      if (!reduced.matches) {
        tick += 1;
        frame = window.requestAnimationFrame(draw);
      }
    };

    const onMotionChange = () => {
      window.cancelAnimationFrame(frame);
      draw();
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    reduced.addEventListener('change', onMotionChange);
    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      reduced.removeEventListener('change', onMotionChange);
    };
  }, []);

  return <canvas className="omh-particles" ref={canvasRef} aria-hidden="true" />;
}

export default function OwnerMindMap() {
  const [query, setQuery] = useState('');
  const [activeGroups, setActiveGroups] = useState<Set<string>>(() => new Set(groups.map(({ id }) => id)));
  const [selectedId, setSelectedId] = useState('owner-portal');
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const selectedNode = nodes.find((node) => node.id === selectedId) ?? nodes[0];
  const normalizedQuery = query.trim().toLowerCase();
  const visibleNodes = useMemo(() => nodes.filter((node) => {
    const matchesGroup = activeGroups.has(node.group);
    const matchesSearch = !normalizedQuery
      || `${node.title} ${node.subtitle} ${node.description} ${node.connects.join(' ')}`.toLowerCase().includes(normalizedQuery);
    return matchesGroup && matchesSearch;
  }), [activeGroups, normalizedQuery]);
  const visibleIds = new Set(visibleNodes.map(({ id }) => id));

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        searchRef.current?.focus();
      }
      if (event.key === 'Escape') {
        setQuery('');
        searchRef.current?.blur();
        setMobileDetailOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const toggleGroup = (id: string) => {
    setActiveGroups((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectNode = (id: string) => {
    setSelectedId(id);
    setMobileDetailOpen(true);
  };

  const selectFromKeyboard = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const nextIndex = (index + (event.key === 'ArrowDown' ? 1 : visibleNodes.length - 1)) % visibleNodes.length;
    document.getElementById(`omh-node-${visibleNodes[nextIndex]?.id}`)?.focus();
  };

  return (
    <main className="owner-map-page">
      <ParticleField />
      <div className="omh-shell">
        <header className="omh-header">
          <div className="omh-brand">
            <div className="omh-brand-mark" aria-hidden="true"><Network size={18} strokeWidth={1.5} /></div>
            <div>
              <p className="omh-overline">SMART MONEY HUB <span>/</span> OWNER SPACE</p>
              <h1>System mind map</h1>
            </div>
          </div>
          <div className="omh-private"><ShieldCheck size={14} /> PRIVATE OWNER VIEW</div>
        </header>

        <section className="omh-intro" aria-labelledby="omh-page-title">
          <div>
            <p className="omh-kicker">THE PRODUCT, AT A GLANCE</p>
            <h2 id="omh-page-title">One ecosystem.<br /><em>Connected by design.</em></h2>
            <p className="omh-intro-copy">A conceptual map of how the Portal and bot-related modules fit together.</p>
          </div>
          <div className="omh-map-stamp">
            <span className="omh-stamp-dot" />
            <span>CONCEPTUAL TOPOLOGY</span>
            <small>Static view · not live telemetry</small>
          </div>
        </section>

        <section className="omh-workspace" aria-label="Smart Money Hub system map">
          <div className="omh-map-column">
            <div className="omh-toolbar">
              <label className="omh-search">
                <Search size={16} aria-hidden="true" />
                <span className="omh-sr-only">Search map nodes</span>
                <input
                  ref={searchRef}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Find a module or capability"
                  type="search"
                  data-testid="input-mindmap-search"
                />
                {query ? <button type="button" className="omh-clear-search" aria-label="Clear search" onClick={() => setQuery('')}><X size={14} /></button> : <kbd>⌘ K</kbd>}
              </label>
              <span className="omh-count">{visibleNodes.length.toString().padStart(2, '0')} <span>MODULES IN VIEW</span></span>
            </div>

            <div className="omh-map-stage">
              <div className="omh-stage-grid" aria-hidden="true" />
              <div className="omh-orbit omh-orbit-one" aria-hidden="true" />
              <div className="omh-orbit omh-orbit-two" aria-hidden="true" />
              <svg className="omh-connectors" viewBox="0 0 900 460" preserveAspectRatio="none" aria-hidden="true">
                <path d="M450 95 C450 155 190 130 190 216 M450 95 C450 155 710 130 710 216 M450 95 C450 180 190 280 190 342 M450 95 C450 180 710 280 710 342" />
                <path className="omh-connectors-fine" d="M190 216 C300 267 350 300 450 342 M710 216 C600 267 550 300 450 342" />
                <circle cx="450" cy="95" r="3" /><circle cx="190" cy="216" r="2" /><circle cx="710" cy="216" r="2" />
                <circle cx="190" cy="342" r="2" /><circle cx="710" cy="342" r="2" />
              </svg>

              <button
                className={`omh-core ${selectedId === 'owner-portal' ? 'is-selected' : ''} ${visibleIds.has('owner-portal') ? '' : 'is-dimmed'}`}
                onClick={() => selectNode('owner-portal')}
                disabled={!visibleIds.has('owner-portal')}
                aria-pressed={selectedId === 'owner-portal'}
                data-testid="button-node-owner-portal"
              >
                <span className="omh-core-halo" />
                <span className="omh-core-icon"><Command size={20} /></span>
                <span className="omh-core-copy"><small>PRIVATE CONTROL ROOM</small><strong>Smart Money Hub<br />Portal</strong></span>
                <ArrowDown className="omh-core-down" size={14} />
              </button>

              <div className="omh-node-grid">
                {groups.map((group, groupIndex) => {
                  const groupNodes = nodes.filter((node) => node.group === group.id && node.id !== 'owner-portal');
                  return (
                    <section key={group.id} className={`omh-branch omh-branch-${groupIndex + 1}`} aria-label={group.label}>
                      <div className={`omh-branch-heading tone-${group.color}`}>
                        <span className="omh-branch-dot" />
                        <span>{group.label}</span>
                      </div>
                      <div className="omh-branch-nodes">
                        {groupNodes.map((node, nodeIndex) => {
                          const Icon = node.icon;
                          const active = selectedId === node.id;
                          return (
                            <button
                              id={`omh-node-${node.id}`}
                              key={node.id}
                              className={`omh-node tone-${group.color} ${active ? 'is-selected' : ''} ${visibleIds.has(node.id) ? '' : 'is-dimmed'}`}
                              onClick={() => selectNode(node.id)}
                              onKeyDown={(event) => selectFromKeyboard(event, nodes.filter((item) => visibleIds.has(item.id)).findIndex((item) => item.id === node.id))}
                              disabled={!visibleIds.has(node.id)}
                              aria-pressed={active}
                              data-testid={`button-node-${node.id}`}
                            >
                              <span className="omh-node-icon"><Icon size={15} /></span>
                              <span className="omh-node-label"><strong>{node.title}</strong><small>{node.subtitle}</small></span>
                              <ChevronRight size={14} className="omh-node-chevron" />
                              {nodeIndex === 0 && <span className="omh-node-index">0{groupIndex + 1}</span>}
                            </button>
                          );
                        })}
                      </div>
                    </section>
                  );
                })}
              </div>
              <div className="omh-stage-foot"><span>STRUCTURE / 01</span><span>SELECT A NODE TO EXPLORE</span><span>OWNER MAP</span></div>
            </div>

            <div className="omh-legend" aria-label="Filter map by category">
              <span className="omh-legend-label">SHOW</span>
              {groups.map((group) => (
                <button
                  key={group.id}
                  type="button"
                  className={`omh-legend-chip tone-${group.color} ${activeGroups.has(group.id) ? 'is-on' : ''}`}
                  aria-pressed={activeGroups.has(group.id)}
                  onClick={() => toggleGroup(group.id)}
                  data-testid={`button-filter-${group.id}`}
                >
                  <i />{group.label}
                </button>
              ))}
              <button type="button" className="omh-reset" onClick={() => { setActiveGroups(new Set(groups.map(({ id }) => id))); setQuery(''); }}>Reset view</button>
            </div>
          </div>

          <aside className={`omh-detail ${mobileDetailOpen ? 'is-mobile-open' : ''}`} aria-live="polite">
            <div className="omh-detail-top">
              <span className="omh-detail-tag"><span /> NODE PROFILE</span>
              <button className="omh-detail-close" type="button" onClick={() => setMobileDetailOpen(false)} aria-label="Close node details"><X size={16} /></button>
            </div>
            <div className={`omh-detail-icon tone-${groupById.get(selectedNode.group)?.color ?? 'mint'}`}>
              {(() => { const Icon = selectedNode.icon; return <Icon size={20} />; })()}
            </div>
            <p className="omh-detail-category">{groupById.get(selectedNode.group)?.label}</p>
            <h3>{selectedNode.title}</h3>
            <p className="omh-detail-subtitle">{selectedNode.subtitle}</p>
            <p className="omh-detail-description">{selectedNode.description}</p>
            <div className="omh-detail-rule" />
            <p className="omh-detail-section-title">CONNECTED CONCEPTS <span>{String(selectedNode.connects.length).padStart(2, '0')}</span></p>
            <div className="omh-connected-list">
              {selectedNode.connects.map((connected, index) => {
                const target = nodes.find((node) => node.title === connected);
                return <button
                  type="button"
                  key={connected}
                  onClick={() => target && selectNode(target.id)}
                  disabled={!target}
                  className="omh-connected"
                  data-testid={`button-connected-${selectedNode.id}-${index}`}
                >
                  <span className="omh-connected-number">0{index + 1}</span><span>{connected}</span><ArrowUpRight size={13} />
                </button>;
              })}
            </div>
            <div className="omh-detail-note"><CircleHelp size={14} /><span>Relationships shown are conceptual, not a live connection or service health signal.</span></div>
          </aside>
        </section>

        <footer className="omh-footer">
          <div className="omh-footer-left"><span className="omh-footer-mark"><Boxes size={14} /></span><span>SMART MONEY HUB <b>·</b> INTERNAL SYSTEMS MAP</span></div>
          <div className="omh-footer-note">A working model of the product ecosystem</div>
          <button className="omh-help" type="button" onClick={() => selectNode('shared-platform')} aria-label="View platform foundation"><Globe2 size={15} /></button>
        </footer>
      </div>
    </main>
  );
}
