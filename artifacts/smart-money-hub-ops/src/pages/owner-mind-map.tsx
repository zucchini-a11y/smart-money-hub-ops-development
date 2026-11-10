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

const nodePositions: Record<string, [number, number, number]> = {
  'owner-portal': [0, 0, 0],
  'member-learning': [0.92, 0.08, 0.28],
  signals: [-0.92, 0.06, 0.28],
  coach: [0.12, 0.86, -0.43],
  knowledge: [-0.62, -0.72, -0.28],
  'shared-platform': [0.66, -0.7, -0.28],
};

const nodeColors: Record<GroupId, string> = {
  portal: '#83e6c9',
  bots: '#e4bd79',
  intelligence: '#d69aa8',
  foundation: '#8dbed0',
};

function SystemMap3D({
  selectedId,
  visibleIds,
  onSelect,
}: {
  selectedId: string;
  visibleIds: Set<string>;
  onSelect: (id: string) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const currentRef = useRef({ selectedId, visibleIds, onSelect });
  currentRef.current = { selectedId, visibleIds, onSelect };

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    let width = 0;
    let height = 0;
    let dpr = 1;
    let yaw = -0.28;
    let pitch = 0.12;
    let zoom = 1;
    let tick = 0;
    let pointerDown = false;
    let pointerMoved = false;
    let lastX = 0;
    let lastY = 0;
    let pointerStartX = 0;
    let pointerStartY = 0;
    let projectedNodes: { id: string; x: number; y: number; depth: number }[] = [];

    const resize = () => {
      window.cancelAnimationFrame(frame);
      const bounds = canvas.getBoundingClientRect();
      width = bounds.width;
      height = bounds.height;
      dpr = Math.min(window.devicePixelRatio || 1, 1.75);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      draw();
    };

    const draw = () => {
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, width, height);
      if (!width || !height) return;

      const centerX = width / 2;
      const centerY = height / 2 - 8;
      const scale = Math.min(width * 0.34, height * 0.37) * zoom;
      const cosYaw = Math.cos(yaw);
      const sinYaw = Math.sin(yaw);
      const cosPitch = Math.cos(pitch);
      const sinPitch = Math.sin(pitch);
      const projected = nodes.map((node) => {
        const [x, y, z] = nodePositions[node.id];
        const rotatedX = x * cosYaw + z * sinYaw;
        const rotatedZ = -x * sinYaw + z * cosYaw;
        const rotatedY = y * cosPitch - rotatedZ * sinPitch;
        const depth = y * sinPitch + rotatedZ * cosPitch;
        const perspective = 3.7 / (3.7 + depth);
        return {
          node,
          x: centerX + rotatedX * scale * perspective,
          y: centerY - rotatedY * scale * perspective,
          depth,
          perspective,
        };
      });
      projectedNodes = projected.map(({ node, x, y, depth }) => ({ id: node.id, x, y, depth }));

      // Subtle projected orbital rings give the map depth without implying live telemetry.
      context.save();
      context.translate(centerX, centerY);
      context.strokeStyle = 'rgba(131,230,201,.075)';
      context.lineWidth = 1;
      context.beginPath();
      context.ellipse(0, 0, scale * 0.97, scale * 0.31, -0.12, 0, Math.PI * 2);
      context.stroke();
      context.strokeStyle = 'rgba(141,190,208,.055)';
      context.beginPath();
      context.ellipse(0, 0, scale * 0.68, scale * 0.96, 0.2, 0, Math.PI * 2);
      context.stroke();
      context.restore();

      const connectionSet = new Set<string>();
      nodes.forEach((node) => {
        node.connects.forEach((title) => {
          const target = nodes.find((item) => item.title === title);
          if (!target) return;
          connectionSet.add([node.id, target.id].sort().join('|'));
        });
      });

      context.lineWidth = 1;
      Array.from(connectionSet).forEach((key, index) => {
        const [fromId, toId] = key.split('|');
        const fromIndex = nodes.findIndex(({ id }) => id === fromId);
        const toIndex = nodes.findIndex(({ id }) => id === toId);
        const from = projected[fromIndex];
        const to = projected[toIndex];
        if (!from || !to) return;
        const shown = currentRef.current.visibleIds.has(fromId) && currentRef.current.visibleIds.has(toId);
        const nearer = Math.max(0, 1 - Math.max(from.depth, to.depth) / 3);
        context.strokeStyle = `rgba(131,230,201,${(shown ? 0.22 : 0.045) * (0.45 + nearer * 0.55)})`;
        context.setLineDash([3, 6]);
        context.beginPath();
        context.moveTo(from.x, from.y);
        context.lineTo(to.x, to.y);
        context.stroke();
        context.setLineDash([]);

        if (shown && !reducedMotion.matches) {
          const pulse = (tick * 0.007 + index * 0.19) % 1;
          const px = from.x + (to.x - from.x) * pulse;
          const py = from.y + (to.y - from.y) * pulse;
          context.fillStyle = 'rgba(161,255,240,.82)';
          context.shadowColor = '#83e6c9';
          context.shadowBlur = 9;
          context.beginPath();
          context.arc(px, py, 2, 0, Math.PI * 2);
          context.fill();
          context.shadowBlur = 0;
        }
      });

      projected
        .slice()
        .sort((a, b) => b.depth - a.depth)
        .forEach(({ node, x, y, depth, perspective }) => {
          const active = currentRef.current.visibleIds.has(node.id);
          const selected = currentRef.current.selectedId === node.id;
          const color = nodeColors[node.group];
          const radius = (node.id === 'owner-portal' ? 12 : 8) * Math.max(0.72, perspective);
          const alpha = active ? Math.max(0.48, 0.92 - depth * 0.14) : 0.15;

          context.globalAlpha = alpha;
          const glow = context.createRadialGradient(x, y, 0, x, y, radius * 3.1);
          glow.addColorStop(0, `${color}70`);
          glow.addColorStop(1, `${color}00`);
          context.fillStyle = glow;
          context.beginPath();
          context.arc(x, y, radius * 3.1, 0, Math.PI * 2);
          context.fill();

          context.fillStyle = '#091110';
          context.strokeStyle = color;
          context.lineWidth = selected ? 2 : 1.35;
          context.beginPath();
          context.arc(x, y, radius, 0, Math.PI * 2);
          context.fill();
          context.stroke();

          if (selected) {
            context.strokeStyle = `${color}80`;
            context.lineWidth = 1;
            context.beginPath();
            context.arc(x, y, radius + 6, 0, Math.PI * 2);
            context.stroke();
          }

          context.globalAlpha = active ? 0.96 : 0.34;
          context.textAlign = 'center';
          context.textBaseline = 'top';
          context.fillStyle = '#e4efea';
          context.font = `600 ${Math.max(10, Math.min(13, width / 66))}px system-ui, sans-serif`;
          context.fillText(node.title, x, y + radius + 9);
          context.globalAlpha = 1;
        });

      context.globalAlpha = 1;
      if (!reducedMotion.matches) {
        yaw += 0.0016;
        tick += 1;
        frame = window.requestAnimationFrame(draw);
      }
    };

    const pointerStart = (event: PointerEvent) => {
      pointerDown = true;
      pointerMoved = false;
      lastX = pointerStartX = event.clientX;
      lastY = pointerStartY = event.clientY;
      canvas.setPointerCapture(event.pointerId);
    };
    const pointerMove = (event: PointerEvent) => {
      if (!pointerDown) return;
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      if (Math.hypot(event.clientX - pointerStartX, event.clientY - pointerStartY) > 5) pointerMoved = true;
      if (pointerMoved) {
        yaw += dx * 0.008;
        pitch = Math.max(-0.8, Math.min(0.8, pitch + dy * 0.006));
        if (reducedMotion.matches) draw();
      }
      lastX = event.clientX;
      lastY = event.clientY;
    };
    const pointerEnd = (event: PointerEvent) => {
      if (!pointerDown) return;
      pointerDown = false;
      if (!pointerMoved) {
        const bounds = canvas.getBoundingClientRect();
        const x = event.clientX - bounds.left;
        const y = event.clientY - bounds.top;
        const nearest = projectedNodes
          .map((point) => ({ ...point, distance: Math.hypot(point.x - x, point.y - y) }))
          .filter((point) => point.distance <= 30)
          .sort((a, b) => a.distance - b.distance)[0];
        if (nearest) currentRef.current.onSelect(nearest.id);
      }
    };
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      zoom = Math.max(0.72, Math.min(1.55, zoom * Math.exp(-event.deltaY * 0.001)));
      if (reducedMotion.matches) draw();
    };
    const motionChange = () => {
      window.cancelAnimationFrame(frame);
      draw();
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    canvas.addEventListener('pointerdown', pointerStart);
    canvas.addEventListener('pointermove', pointerMove);
    canvas.addEventListener('pointerup', pointerEnd);
    canvas.addEventListener('pointercancel', pointerEnd);
    canvas.addEventListener('wheel', wheel, { passive: false });
    reducedMotion.addEventListener('change', motionChange);
    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      canvas.removeEventListener('pointerdown', pointerStart);
      canvas.removeEventListener('pointermove', pointerMove);
      canvas.removeEventListener('pointerup', pointerEnd);
      canvas.removeEventListener('pointercancel', pointerEnd);
      canvas.removeEventListener('wheel', wheel);
      reducedMotion.removeEventListener('change', motionChange);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="omh-system-canvas"
      role="img"
      aria-label="Animated three-dimensional conceptual map connecting the Owner Portal, member learning, the Signals bot, Coach bot, knowledge library, and shared platform. Drag to rotate, scroll to zoom, or select nodes below."
      data-testid="canvas-owner-system-map-3d"
    />
  );
}

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
            <small>Animated 3D · not live telemetry</small>
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
              <SystemMap3D selectedId={selectedId} visibleIds={visibleIds} onSelect={selectNode} />
              <div className="omh-3d-caption">
                <span>3D SYSTEM MAP</span>
                <span>DRAG TO ROTATE · SCROLL TO ZOOM · SELECT A NODE BELOW</span>
              </div>
              <div className="omh-stage-foot"><span>PRODUCT CONCEPT</span><span>ANIMATED VIEW</span><span>OWNER ONLY</span></div>
            </div>

            <div className="omh-node-grid" aria-label="System map nodes">
              {groups.map((group, groupIndex) => {
                const groupNodes = nodes.filter((node) => node.group === group.id);
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
