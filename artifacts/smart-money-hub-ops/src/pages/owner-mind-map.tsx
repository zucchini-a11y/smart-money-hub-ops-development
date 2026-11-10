import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import {
  ArrowUpRight, Bot, BookOpen, Boxes, ChevronRight, CircleHelp,
  Command, Database, Globe2, Layers3, Network, Pause, Play, RotateCcw, Search,
  ShieldCheck, Sparkles, X,
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
  { id: 'orchestration', label: 'Intake & review', color: 'mint' },
  { id: 'publishing', label: 'Content & delivery', color: 'amber' },
  { id: 'access', label: 'Member & PRO flows', color: 'rose' },
  { id: 'operations', label: 'Health & recovery', color: 'blue' },
] as const;

type GroupId = typeof groups[number]['id'];

const nodes: MapNode[] = [
  {
    id: 'signal-core', title: 'Signals Bot', subtitle: 'One bot · internal workflows',
    group: 'orchestration', icon: Bot,
    description: 'The central Smart Money Hub Signal Bot. Every branch represents an internal workflow of this bot; separate bot identities are not shown.',
    connects: ['Telegram intake', 'Review controls', 'Signals & zones', 'PRO Signals delivery', 'Market Analysis delivery', 'Education & sessions', 'Member & PRO access', 'Telegram support', 'Health & recovery'],
  },
  {
    id: 'telegram-intake', title: 'Telegram intake', subtitle: 'Updates · commands · polling',
    group: 'orchestration', icon: Network,
    description: 'Incoming Telegram updates and command routing. The actual polling process is separate from this animated view and is not started or measured here.',
    connects: ['Signals Bot', 'Review controls', 'Telegram support', 'Health & recovery'],
  },
  {
    id: 'review-controls', title: 'Review controls', subtitle: 'Draft · confirm · cancel',
    group: 'orchestration', icon: Command,
    description: 'Owner review controls for eligible signal and post actions. The diagram represents the product flow, not a live queue or a publication confirmation.',
    connects: ['Signals Bot', 'Signals & zones', 'PRO Signals delivery', 'Market Analysis delivery', 'Education & sessions'],
  },
  {
    id: 'signal-zones', title: 'Signals & zones', subtitle: 'Chart review · setup controls',
    group: 'publishing', icon: Sparkles,
    description: 'Development signal and zone preparation, chart review, and guarded action controls. A draft is not a live trade instruction.',
    connects: ['Signals Bot', 'Review controls', 'PRO Signals delivery', 'Health & recovery'],
  },
  {
    id: 'pro-publishing', title: 'PRO Signals delivery', subtitle: 'Verified PRO channel',
    group: 'publishing', icon: ArrowUpRight,
    description: 'Prepared and reviewed signal posts for the verified PRO Signals destination, with publication outcomes recorded where the deployment provides them.',
    connects: ['Signals Bot', 'Review controls', 'Member & PRO access', 'Health & recovery'],
  },
  {
    id: 'analysis-publishing', title: 'Market Analysis delivery', subtitle: 'Editorial channel posts',
    group: 'publishing', icon: BookOpen,
    description: 'Editorial market-analysis drafts, review, scheduling, and delivery to the Market Analysis channel. The map does not claim a post is currently queued or sent.',
    connects: ['Signals Bot', 'Review controls', 'Education & sessions', 'Health & recovery'],
  },
  {
    id: 'education-schedule', title: 'Education & sessions', subtitle: 'Group lessons · calendar posts',
    group: 'publishing', icon: Layers3,
    description: 'Education-group lessons and promotions, plus session-oriented content. Scheduled posts are held rather than sent late when their valid window has passed.',
    connects: ['Signals Bot', 'Review controls', 'Market Analysis delivery', 'Member & PRO access'],
  },
  {
    id: 'member-access', title: 'Member & PRO access', subtitle: 'Identity · eligibility · invites',
    group: 'access', icon: ShieldCheck,
    description: 'Telegram identity linking and the separate PRO eligibility and access-review flow. Linking an identity alone does not grant PRO access.',
    connects: ['Signals Bot', 'PRO Signals delivery', 'Education & sessions', 'Telegram support'],
  },
  {
    id: 'telegram-support', title: 'Telegram support', subtitle: 'Cases · replies · handoff',
    group: 'access', icon: CircleHelp,
    description: 'Telegram-origin support cases, staff follow-up, and handoff where the relevant support service is connected.',
    connects: ['Signals Bot', 'Telegram intake', 'Member & PRO access', 'Health & recovery'],
  },
  {
    id: 'health-recovery', title: 'Health & recovery', subtitle: 'Heartbeat · errors · safe retries',
    group: 'operations', icon: Database,
    description: 'Operational health signals, publishing failures, and recovery safeguards. Live production health is not connected to this Development mind map.',
    connects: ['Signals Bot', 'Telegram intake', 'Signals & zones', 'PRO Signals delivery', 'Market Analysis delivery', 'Telegram support'],
  },
];

const groupById = new Map(groups.map((group) => [group.id, group]));

const nodePositions: Record<string, [number, number, number]> = {
  'signal-core': [0, 0.12, 0.48],
  'telegram-intake': [0.02, 0.58, -0.08],
  'review-controls': [0.43, 0.3, 0.2],
  'signal-zones': [-0.46, 0.3, 0.18],
  'pro-publishing': [0.57, 0.04, 0.02],
  'analysis-publishing': [-0.57, 0.04, 0.02],
  'education-schedule': [0, -0.36, -0.22],
  'member-access': [0.42, -0.25, -0.23],
  'telegram-support': [-0.42, -0.25, -0.23],
  'health-recovery': [0, -0.61, 0.04],
};

const nodeColors: Record<GroupId, string> = {
  orchestration: '#83e6c9',
  publishing: '#e4bd79',
  access: '#d69aa8',
  operations: '#8dbed0',
};

const nodeLabelOffsets: Record<string, { x: number; y: number; align: CanvasTextAlign }> = {
  'signal-core': { x: 0, y: 17, align: 'center' },
  'telegram-intake': { x: 0, y: -14, align: 'center' },
  'review-controls': { x: 10, y: -5, align: 'left' },
  'signal-zones': { x: -10, y: -5, align: 'right' },
  'pro-publishing': { x: 10, y: -2, align: 'left' },
  'analysis-publishing': { x: -10, y: -2, align: 'right' },
  'education-schedule': { x: 0, y: 16, align: 'center' },
  'member-access': { x: 10, y: 12, align: 'left' },
  'telegram-support': { x: -10, y: 12, align: 'right' },
  'health-recovery': { x: 0, y: 18, align: 'center' },
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
  const [autoRotate, setAutoRotate] = useState(true);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const currentRef = useRef({ selectedId, visibleIds, onSelect, autoRotate });
  const resetViewRef = useRef<() => void>(() => {});
  const redrawRef = useRef<() => void>(() => {});
  currentRef.current = { selectedId, visibleIds, onSelect, autoRotate };

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
    let pinchDistance = 0;
    const pointers = new Map<number, { x: number; y: number }>();

    type CloudPoint = { x: number; y: number; z: number; nodeId: string; size: number; phase: number; opacity: number };
    let seed = 934761;
    const random = () => {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    const nearestNodeId = (point: { x: number; y: number; z: number }) => nodes.reduce((nearest, node) => {
      const [x, y, z] = nodePositions[node.id];
      const distance = (point.x - x) ** 2 + (point.y - y) ** 2 * 1.2 + (point.z - z) ** 2;
      return distance < nearest.distance ? { id: node.id, distance } : nearest;
    }, { id: nodes[0].id, distance: Number.POSITIVE_INFINITY }).id;
    const cloudPoints: CloudPoint[] = [];
    for (let index = 0; index < 1_650; index += 1) {
      const vertical = random() * 2 - 1;
      const angle = random() * Math.PI * 2;
      const ring = Math.sqrt(1 - vertical * vertical);
      const rawX = Math.cos(angle) * ring;
      const rawZ = Math.sin(angle) * ring;
      const radial = index < 1_100 ? 0.76 + random() * 0.25 : 0.24 + random() * 0.72;
      const fold = 1 + 0.045 * Math.sin(angle * 5 + vertical * 7) + 0.028 * Math.cos(angle * 9 - vertical * 4);
      const taper = 0.86 + 0.14 * Math.max(0, vertical + 0.2);
      const point = {
        x: Math.sign(rawX || 1) * (0.035 + Math.abs(rawX) * 0.66) * radial * fold * taper,
        y: 0.12 + vertical * 0.72 * radial * fold,
        z: rawZ * 0.49 * radial * fold,
      };
      cloudPoints.push({
        ...point,
        nodeId: nearestNodeId(point),
        size: 0.55 + random() * 1.45,
        phase: random() * Math.PI * 2,
        opacity: 0.28 + random() * 0.6,
      });
    }
    for (let index = 0; index < 240; index += 1) {
      const progress = random();
      const radius = 0.13 * (1 - progress) + 0.018;
      cloudPoints.push({
        x: (random() - 0.5) * radius + 0.018 * Math.sin(progress * 8),
        y: -0.5 - progress * 0.68,
        z: (random() - 0.5) * radius * 0.78,
        nodeId: 'health-recovery',
        size: 0.55 + random() * 1.25,
        phase: random() * Math.PI * 2,
        opacity: 0.24 + random() * 0.55,
      });
    }
    const pointsByNode = new Map<string, CloudPoint[]>();
    nodes.forEach(({ id }) => pointsByNode.set(id, cloudPoints.filter((point) => point.nodeId === id)));
    const neuralStrands: { nodeId: string; points: { x: number; y: number; z: number }[] }[] = [];
    nodes.forEach(({ id }) => {
      const cloud = pointsByNode.get(id) ?? [];
      for (let strandIndex = 0; strandIndex < 28 && cloud.length > 1; strandIndex += 1) {
        const start = cloud[Math.floor(random() * cloud.length)];
        let end = cloud[Math.floor(random() * cloud.length)];
        for (let attempt = 0; attempt < 8 && end === start; attempt += 1) end = cloud[Math.floor(random() * cloud.length)];
        const bend = { x: (random() - 0.5) * 0.2, y: (random() - 0.5) * 0.24, z: (random() - 0.5) * 0.2 };
        const points = Array.from({ length: 9 }, (_, pointIndex) => {
          const t = pointIndex / 8;
          const inverse = 1 - t;
          return {
            x: inverse * inverse * start.x + 2 * inverse * t * ((start.x + end.x) / 2 + bend.x) + t * t * end.x,
            y: inverse * inverse * start.y + 2 * inverse * t * ((start.y + end.y) / 2 + bend.y) + t * t * end.y,
            z: inverse * inverse * start.z + 2 * inverse * t * ((start.z + end.z) / 2 + bend.z) + t * t * end.z,
          };
        });
        neuralStrands.push({ nodeId: id, points });
      }
    });
    const nodeColorsById = new Map(nodes.map((node) => [node.id, nodeColors[node.group]]));
    const toRgba = (hex: string, alpha: number) => {
      const value = Number.parseInt(hex.slice(1), 16);
      return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
    };

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
      const centerY = height * 0.51;
      const scale = Math.min(width * 0.47, height * 0.39) * zoom;
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

      const projectCloudPoint = (point: { x: number; y: number; z: number }) => {
        const rotatedX = point.x * cosYaw + point.z * sinYaw;
        const rotatedZ = -point.x * sinYaw + point.z * cosYaw;
        const rotatedY = point.y * cosPitch - rotatedZ * sinPitch;
        const depth = point.y * sinPitch + rotatedZ * cosPitch;
        const perspective = 3.7 / (3.7 + depth);
        return {
          x: centerX + rotatedX * scale * perspective,
          y: centerY - rotatedY * scale * perspective,
          depth,
          perspective,
        };
      };

      const backdrop = context.createRadialGradient(centerX, centerY - scale * 0.08, scale * 0.04, centerX, centerY, scale * 1.2);
      backdrop.addColorStop(0, 'rgba(42,116,94,.11)');
      backdrop.addColorStop(0.55, 'rgba(14,44,38,.06)');
      backdrop.addColorStop(1, 'rgba(3,8,8,0)');
      context.fillStyle = backdrop;
      context.fillRect(0, 0, width, height);

      context.globalCompositeOperation = 'lighter';
      neuralStrands.forEach(({ nodeId, points }, strandIndex) => {
        const color = nodeColorsById.get(nodeId) ?? '#83e6c9';
        const active = currentRef.current.visibleIds.has(nodeId);
        context.beginPath();
        points.forEach((point, index) => {
          const projectedPoint = projectCloudPoint(point);
          if (index === 0) context.moveTo(projectedPoint.x, projectedPoint.y);
          else context.lineTo(projectedPoint.x, projectedPoint.y);
        });
        context.strokeStyle = toRgba(color, active ? 0.13 + 0.035 * Math.sin(tick * 0.025 + strandIndex) : 0.012);
        context.lineWidth = 0.55;
        context.stroke();
      });

      cloudPoints.forEach((particle) => {
        const point = projectCloudPoint(particle);
        const active = currentRef.current.visibleIds.has(particle.nodeId);
        const color = nodeColorsById.get(particle.nodeId) ?? '#83e6c9';
        const pulse = reducedMotion.matches ? 1 : 0.78 + Math.sin(tick * 0.025 + particle.phase) * 0.22;
        const depthAlpha = Math.max(0.24, 0.92 - point.depth * 0.38);
        context.fillStyle = toRgba(color, particle.opacity * depthAlpha * pulse * (active ? 1 : 0.07));
        context.beginPath();
        context.arc(point.x, point.y, particle.size * Math.max(0.66, point.perspective), 0, Math.PI * 2);
        context.fill();
      });
      context.globalCompositeOperation = 'source-over';

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
        context.beginPath();
        context.moveTo(from.x, from.y);
        const controlX = (from.x + to.x) / 2;
        const controlY = (from.y + to.y) / 2 - scale * 0.1;
        context.quadraticCurveTo(controlX, controlY, to.x, to.y);
        context.stroke();

        if (shown && !reducedMotion.matches) {
          const pulse = (tick * 0.007 + index * 0.19) % 1;
          const inverse = 1 - pulse;
          const px = inverse * inverse * from.x + 2 * inverse * pulse * controlX + pulse * pulse * to.x;
          const py = inverse * inverse * from.y + 2 * inverse * pulse * controlY + pulse * pulse * to.y;
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
          const radius = (selected ? 7 : 5.2) * Math.max(0.72, perspective);
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
          const labelOffset = nodeLabelOffsets[node.id];
          context.textAlign = labelOffset.align;
          context.textBaseline = 'middle';
          context.fillStyle = '#e4efea';
          context.font = `600 ${Math.max(8, Math.min(10, width / 54))}px system-ui, sans-serif`;
          context.fillText(node.title, x + labelOffset.x, y + labelOffset.y);
          context.globalAlpha = 1;
        });

      context.globalAlpha = 1;
      if (!reducedMotion.matches) {
        if (currentRef.current.autoRotate && !pointerDown) yaw += 0.00075;
        tick += 1;
        frame = window.requestAnimationFrame(draw);
      }
    };

    resetViewRef.current = () => {
      yaw = -0.28;
      pitch = 0.12;
      zoom = 1;
      if (reducedMotion.matches) draw();
    };
    redrawRef.current = () => {
      if (reducedMotion.matches) draw();
    };
    const pointerStart = (event: PointerEvent) => {
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      canvas.setPointerCapture(event.pointerId);
      if (pointers.size > 1) {
        pointerMoved = true;
        pointerDown = false;
        const [first, second] = Array.from(pointers.values());
        pinchDistance = Math.hypot(first.x - second.x, first.y - second.y);
        return;
      }
      pointerDown = true;
      pointerMoved = false;
      lastX = pointerStartX = event.clientX;
      lastY = pointerStartY = event.clientY;
    };
    const pointerMove = (event: PointerEvent) => {
      if (pointers.has(event.pointerId)) pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pointers.size > 1) {
        const [first, second] = Array.from(pointers.values());
        const distance = Math.hypot(first.x - second.x, first.y - second.y);
        if (pinchDistance > 0) zoom = Math.max(0.68, Math.min(1.8, zoom * distance / pinchDistance));
        pinchDistance = distance;
        if (reducedMotion.matches) draw();
        return;
      }
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
      const wasTap = pointerDown && !pointerMoved && pointers.size === 1;
      pointerDown = false;
      pointers.delete(event.pointerId);
      if (pointers.size < 2) pinchDistance = 0;
      if (wasTap) {
        const bounds = canvas.getBoundingClientRect();
        const x = event.clientX - bounds.left;
        const y = event.clientY - bounds.top;
        const nearest = projectedNodes
          .map((point) => ({ ...point, distance: Math.hypot(point.x - x, point.y - y) }))
          .filter((point) => point.distance <= 26)
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
      resetViewRef.current = () => {};
      redrawRef.current = () => {};
    };
  }, []);

  useEffect(() => {
    redrawRef.current();
  }, [selectedId, visibleIds, autoRotate]);

  return (
    <>
      <canvas
        ref={canvasRef}
        className="omh-system-canvas"
        role="img"
        aria-label="Animated three-dimensional neural cloud map of the Signal Bot's internal workflows. Drag to rotate, pinch or scroll to zoom, and tap a glowing node to select it."
        data-testid="canvas-owner-system-map-3d"
      />
      <div className="omh-3d-controls" aria-label="3D map controls">
        <button type="button" onClick={() => setAutoRotate((turning) => !turning)} aria-pressed={autoRotate} aria-label={autoRotate ? 'Pause automatic rotation' : 'Resume automatic rotation'} title={autoRotate ? 'Pause rotation' : 'Resume rotation'}>
          {autoRotate ? <Pause size={12} /> : <Play size={12} />}
          <span>{autoRotate ? 'PAUSE' : 'ROTATE'}</span>
        </button>
        <button type="button" onClick={() => resetViewRef.current()} aria-label="Reset 3D map view" title="Reset view"><RotateCcw size={12} /></button>
      </div>
    </>
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
  const [selectedId, setSelectedId] = useState('signal-core');
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
              <h1>Signals Bot system map</h1>
            </div>
          </div>
          <div className="omh-private"><ShieldCheck size={14} /> PRIVATE OWNER VIEW</div>
        </header>

        <section className="omh-intro" aria-labelledby="omh-page-title">
          <div>
            <p className="omh-kicker">ONE BOT · INTERNAL WORKFLOWS</p>
            <h2 id="omh-page-title">One bot.<br /><em>Every workflow.</em></h2>
            <p className="omh-intro-copy">Explore the Signal Bot’s intake, review, publishing, member-access, support, and recovery flows.</p>
          </div>
          <div className="omh-map-stamp">
            <span className="omh-stamp-dot" />
            <span>CONCEPTUAL TOPOLOGY</span>
            <small>Animated 3D · not live telemetry</small>
          </div>
        </section>

        <section className="omh-workspace" aria-label="Signals Bot internal workflow map">
          <div className="omh-map-column">
            <div className="omh-toolbar">
              <label className="omh-search">
                <Search size={16} aria-hidden="true" />
                <span className="omh-sr-only">Search bot workflows</span>
                <input
                  ref={searchRef}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Find a bot workflow"
                  type="search"
                  data-testid="input-mindmap-search"
                />
                {query ? <button type="button" className="omh-clear-search" aria-label="Clear search" onClick={() => setQuery('')}><X size={14} /></button> : <kbd>⌘ K</kbd>}
              </label>
              <span className="omh-count">{visibleNodes.length.toString().padStart(2, '0')} <span>WORKFLOWS IN VIEW</span></span>
            </div>

            <div className="omh-map-stage">
              <div className="omh-stage-grid" aria-hidden="true" />
              <SystemMap3D selectedId={selectedId} visibleIds={visibleIds} onSelect={selectNode} />
              <div className="omh-3d-caption">
                <span>SIGNALS BOT · 3D WORKFLOW MAP</span>
                <span>DRAG · PINCH TO ZOOM · TAP A WORKFLOW</span>
              </div>
              <div className="omh-stage-foot"><span>ANIMATED CONCEPT</span><span>NOT LIVE TELEMETRY</span><span>OWNER ONLY</span></div>
            </div>

            <div className="omh-node-grid" aria-label="Signal Bot workflows">
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
              <span className="omh-detail-tag"><span /> WORKFLOW PROFILE</span>
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
            <p className="omh-detail-section-title">LINKED FLOWS <span>{String(selectedNode.connects.length).padStart(2, '0')}</span></p>
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
          <div className="omh-footer-left"><span className="omh-footer-mark"><Boxes size={14} /></span><span>SMART MONEY HUB <b>·</b> SIGNAL BOT FLOWS</span></div>
          <div className="omh-footer-note">Animated workflow view · no process is started</div>
          <button className="omh-help" type="button" onClick={() => selectNode('health-recovery')} aria-label="View health and recovery workflow"><Globe2 size={15} /></button>
        </footer>
      </div>
    </main>
  );
}
