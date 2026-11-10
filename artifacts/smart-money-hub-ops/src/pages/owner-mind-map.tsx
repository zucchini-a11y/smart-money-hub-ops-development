import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import {
  getGetPortalBotConnectionsQueryKey,
  useGetPortalBotConnections,
} from '@workspace/api-client-react';
import type { PortalBotConnection } from '@workspace/api-client-react';
import {
  ArrowUpRight, Bot, BookOpen, Boxes, ChevronRight, CircleHelp,
  Command, Database, Globe2, Layers3, Network, Pause, Play, Radio, RotateCcw, Search,
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
  { id: 'bots', label: 'Bots & assistants', color: 'mint' },
  { id: 'publishing', label: 'Publishing & schedules', color: 'amber' },
  { id: 'members', label: 'Member journeys', color: 'rose' },
  { id: 'operations', label: 'Owner operations', color: 'blue' },
] as const;

type GroupId = typeof groups[number]['id'];

const nodes: MapNode[] = [
  {
    id: 'ecosystem', title: 'Smart Money Hub', subtitle: 'Bots · members · operations',
    group: 'bots', icon: Network,
    description: 'The whole Smart Money Hub ecosystem: bot identities, publishing workflows, member experiences, support, and owner operations in one connected view.',
    connects: ['PRO Signals bot', 'Coach bot', 'Isolated Development bot', 'WhatsApp assistant', 'Signals & zones', 'PRO Signals channel', 'Market Analysis channel', 'Education & sessions', 'Member academy', 'PRO access', 'Support & handoff', 'Owner review', 'Health & recovery', 'Shared records'],
  },
  {
    id: 'pro-signals-bot', title: 'PRO Signals bot', subtitle: 'Telegram signals & access',
    group: 'bots', icon: Bot,
    description: 'The PRO Signals Telegram experience, linked to the reviewed signal workflow and the separate member eligibility/access process.',
    connects: ['Smart Money Hub', 'Signals & zones', 'PRO Signals channel', 'PRO access', 'Owner review', 'Shared records'],
  },
  {
    id: 'coach-bot', title: 'Coach bot', subtitle: 'Learning · guidance · diagrams',
    group: 'bots', icon: Sparkles,
    description: 'The separate Coach experience for educational explanations, learning conversations, and requested visual diagrams.',
    connects: ['Smart Money Hub', 'Member academy', 'Support & handoff', 'Shared records'],
  },
  {
    id: 'isolated-dev-bot', title: 'Isolated Development bot', subtitle: 'Separate test identity',
    group: 'bots', icon: ShieldCheck,
    description: 'A Development-only bot identity kept separate from live bots and live publishing. Its presence on the map does not mean its workflow is running.',
    connects: ['Smart Money Hub', 'Signals & zones', 'Owner review', 'Health & recovery'],
  },
  {
    id: 'whatsapp-assistant', title: 'WhatsApp assistant', subtitle: 'WhatsApp support surface',
    group: 'bots', icon: CircleHelp,
    description: 'The separate WhatsApp assistant application. Its workflow and service availability are not reported by this map.',
    connects: ['Smart Money Hub', 'Support & handoff', 'Shared records'],
  },
  {
    id: 'signals-zones', title: 'Signals & zones', subtitle: 'Chart review · guarded actions',
    group: 'publishing', icon: Sparkles,
    description: 'Signal and zone preparation, chart review, and guarded action controls. A draft is not a live trade instruction.',
    connects: ['Smart Money Hub', 'PRO Signals bot', 'PRO Signals channel', 'Owner review', 'Health & recovery'],
  },
  {
    id: 'pro-channel', title: 'PRO Signals channel', subtitle: 'Reviewed signal publishing',
    group: 'publishing', icon: Layers3,
    description: 'The verified PRO Signals publishing destination for eligible reviewed posts. This map does not confirm a post is queued or published.',
    connects: ['Smart Money Hub', 'PRO Signals bot', 'Signals & zones', 'PRO access', 'Owner review'],
  },
  {
    id: 'market-analysis', title: 'Market Analysis channel', subtitle: 'Editorial posts & review',
    group: 'publishing', icon: BookOpen,
    description: 'Editorial market-analysis drafts, review, scheduling, and channel delivery. The map does not claim a post is currently queued or sent.',
    connects: ['Smart Money Hub', 'Education & sessions', 'Owner review', 'Health & recovery'],
  },
  {
    id: 'education-sessions', title: 'Education & sessions', subtitle: 'Group lessons · scheduled posts',
    group: 'publishing', icon: Layers3,
    description: 'Education-group lessons and promotions alongside session-oriented posts. Missed time-sensitive posts are held rather than sent late.',
    connects: ['Smart Money Hub', 'Market Analysis channel', 'Member academy', 'Owner review'],
  },
  {
    id: 'member-academy', title: 'Member academy', subtitle: 'Lessons · progress · journal',
    group: 'members', icon: BookOpen,
    description: 'The member learning experience with sequential lessons, progress, practice, and journal workflows.',
    connects: ['Smart Money Hub', 'Coach bot', 'PRO access', 'Education & sessions'],
  },
  {
    id: 'pro-access', title: 'PRO access', subtitle: 'Telegram identity · eligibility',
    group: 'members', icon: ShieldCheck,
    description: 'Telegram identity linking and the separate PRO eligibility, review, and invite process. Identity linking alone does not grant access.',
    connects: ['Smart Money Hub', 'PRO Signals bot', 'PRO Signals channel', 'Member academy', 'Support & handoff'],
  },
  {
    id: 'support-handoff', title: 'Support & handoff', subtitle: 'Website · Telegram · staff',
    group: 'members', icon: CircleHelp,
    description: 'Member support conversations, staff follow-up, and human handoff across the website and Telegram support surfaces where connected.',
    connects: ['Smart Money Hub', 'Coach bot', 'WhatsApp assistant', 'PRO access', 'Owner review', 'Shared records'],
  },
  {
    id: 'owner-review', title: 'Owner review', subtitle: 'Approvals · scheduling · controls',
    group: 'operations', icon: Command,
    description: 'Owner-facing review and control paths for eligible signal, channel, education, and member-access workflows.',
    connects: ['Smart Money Hub', 'PRO Signals bot', 'Isolated Development bot', 'Signals & zones', 'PRO Signals channel', 'Market Analysis channel', 'Education & sessions', 'Health & recovery'],
  },
  {
    id: 'health-recovery', title: 'Health & recovery', subtitle: 'Heartbeat · errors · safe retries',
    group: 'operations', icon: Database,
    description: 'Operational health observations, polling, publishing failures, and recovery safeguards. Production runtime health is not connected to this Development map.',
    connects: ['Smart Money Hub', 'PRO Signals bot', 'Isolated Development bot', 'Signals & zones', 'Market Analysis channel', 'Owner review', 'Shared records'],
  },
  {
    id: 'shared-records', title: 'Shared records', subtitle: 'Data · history · audit trail',
    group: 'operations', icon: Database,
    description: 'The stored records and audit history used by supported portal workflows. The map does not expose private customer data.',
    connects: ['Smart Money Hub', 'PRO Signals bot', 'Coach bot', 'WhatsApp assistant', 'Support & handoff', 'Health & recovery'],
  },
];

const groupById = new Map(groups.map((group) => [group.id, group]));

const nodePositions: Record<string, [number, number, number]> = {
  ecosystem: [0, 0.12, 0.48],
  'pro-signals-bot': [-0.46, 0.3, 0.15],
  'coach-bot': [0.46, 0.3, 0.15],
  'isolated-dev-bot': [-0.44, -0.19, 0.13],
  'whatsapp-assistant': [0.44, -0.19, 0.13],
  'signals-zones': [-0.58, 0.33, -0.18],
  'pro-channel': [0.58, 0.33, -0.18],
  'market-analysis': [-0.58, -0.06, -0.18],
  'education-sessions': [0.58, -0.06, -0.18],
  'member-academy': [-0.43, -0.43, -0.1],
  'pro-access': [0.43, -0.43, -0.1],
  'support-handoff': [0, -0.42, 0.28],
  'owner-review': [0, 0.58, -0.3],
  'health-recovery': [-0.2, -0.63, 0.08],
  'shared-records': [0.2, -0.63, 0.08],
};

const nodeColors: Record<GroupId, string> = {
  bots: '#83e6c9',
  publishing: '#e4bd79',
  members: '#d69aa8',
  operations: '#8dbed0',
};

const nodeLabelOffsets: Record<string, { x: number; y: number; align: CanvasTextAlign }> = {
  ecosystem: { x: 0, y: 17, align: 'center' },
  'pro-signals-bot': { x: -10, y: -8, align: 'right' },
  'coach-bot': { x: 10, y: -8, align: 'left' },
  'isolated-dev-bot': { x: -10, y: 8, align: 'right' },
  'whatsapp-assistant': { x: 10, y: 8, align: 'left' },
  'signals-zones': { x: -10, y: -7, align: 'right' },
  'pro-channel': { x: 10, y: -7, align: 'left' },
  'market-analysis': { x: -10, y: -6, align: 'right' },
  'education-sessions': { x: 10, y: -6, align: 'left' },
  'member-academy': { x: -10, y: 8, align: 'right' },
  'pro-access': { x: 10, y: 8, align: 'left' },
  'support-handoff': { x: 0, y: 17, align: 'center' },
  'owner-review': { x: 0, y: -14, align: 'center' },
  'health-recovery': { x: -10, y: 12, align: 'right' },
  'shared-records': { x: 10, y: 12, align: 'left' },
};

const connectionIdByNode: Partial<Record<string, PortalBotConnection['id']>> = {
  'pro-signals-bot': 'pro_signals',
  'coach-bot': 'coach',
  'isolated-dev-bot': 'test',
};

type RuntimeIndicator = {
  label: string;
  tone: 'good' | 'caution' | 'neutral';
  detail: string;
  lastHeartbeat: string | null;
  identityStatus?: PortalBotConnection['identityStatus'];
};

function runtimeIndicatorFor(
  nodeId: string,
  connections: PortalBotConnection[] | undefined,
  loading: boolean,
  unavailable: boolean,
): RuntimeIndicator | null {
  if (nodeId === 'whatsapp-assistant') {
    return { label: 'NO HEARTBEAT SOURCE', tone: 'neutral', detail: 'This assistant does not report process health to the Development Portal.', lastHeartbeat: null };
  }
  const connectionId = connectionIdByNode[nodeId];
  if (!connectionId) return null;
  if (!import.meta.env.DEV) {
    return { label: 'DEV FEED ONLY', tone: 'neutral', detail: 'Bot runtime monitoring is limited to the isolated Development deployment.', lastHeartbeat: null };
  }
  if (loading) {
    return { label: 'CHECKING', tone: 'neutral', detail: 'Reading the isolated Development heartbeat feed.', lastHeartbeat: null };
  }
  if (unavailable || !connections) {
    return { label: 'STATUS UNAVAILABLE', tone: 'caution', detail: 'The Development heartbeat endpoint did not return status.', lastHeartbeat: null };
  }
  const connection = connections.find((item) => item.id === connectionId);
  if (!connection) {
    return { label: 'NO HEARTBEAT SOURCE', tone: 'neutral', detail: 'No process heartbeat is registered for this bot.', lastHeartbeat: null };
  }
  if (connection.runtimeStatus === 'running') {
    return {
      label: 'RUNNING',
      tone: 'good',
      detail: 'A recent process heartbeat was received. Telegram identity verification is a separate check.',
      lastHeartbeat: connection.lastHeartbeat,
      identityStatus: connection.identityStatus,
    };
  }
  if (connection.runtimeStatus === 'stale') {
    return {
      label: 'STALE',
      tone: 'caution',
      detail: 'The last process heartbeat is older than the freshness window. This does not confirm whether the process is stopped.',
      lastHeartbeat: connection.lastHeartbeat,
      identityStatus: connection.identityStatus,
    };
  }
  return {
    label: 'UNKNOWN',
    tone: 'neutral',
    detail: 'No recent process heartbeat is available. A verified Telegram identity alone does not prove the bot is running.',
    lastHeartbeat: null,
    identityStatus: connection.identityStatus,
  };
}

function formatHeartbeat(value: string | null) {
  if (!value) return 'No recent heartbeat';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Heartbeat time unavailable';
  return `Last heartbeat · ${new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)}`;
}

function SystemMap3D({
  selectedId,
  visibleIds,
  labelIds,
  runtimeByNode,
  onSelect,
}: {
  selectedId: string;
  visibleIds: Set<string>;
  labelIds: Set<string>;
  runtimeByNode: Map<string, RuntimeIndicator>;
  onSelect: (id: string) => void;
}) {
  const [autoRotate, setAutoRotate] = useState(true);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const currentRef = useRef({ selectedId, visibleIds, labelIds, runtimeByNode, onSelect, autoRotate });
  const resetViewRef = useRef<() => void>(() => {});
  const redrawRef = useRef<() => void>(() => {});
  currentRef.current = { selectedId, visibleIds, labelIds, runtimeByNode, onSelect, autoRotate };

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
      for (let strandIndex = 0; strandIndex < 18 && cloud.length > 1; strandIndex += 1) {
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

          const runtime = currentRef.current.runtimeByNode.get(node.id);
          if (runtime) {
            const statusColor = runtime.tone === 'good' ? '#80e2b8' : runtime.tone === 'caution' ? '#e2bc76' : '#84958e';
            context.globalAlpha = active ? 1 : 0.28;
            context.fillStyle = '#07100e';
            context.beginPath();
            context.arc(x + radius * 1.45, y - radius * 1.45, 4.2, 0, Math.PI * 2);
            context.fill();
            context.fillStyle = statusColor;
            context.beginPath();
            context.arc(x + radius * 1.45, y - radius * 1.45, 2.5, 0, Math.PI * 2);
            context.fill();
          }

          const showLabel = currentRef.current.labelIds.has(node.id);
          if (showLabel) {
            context.globalAlpha = active ? 0.96 : 0.34;
            const labelOffset = nodeLabelOffsets[node.id];
            context.textAlign = labelOffset.align;
            context.textBaseline = 'middle';
            context.fillStyle = '#e4efea';
            context.font = `600 ${Math.max(8, Math.min(10, width / 54))}px system-ui, sans-serif`;
            context.fillText(node.title, x + labelOffset.x, y + labelOffset.y);
          }
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
  }, [selectedId, visibleIds, labelIds, runtimeByNode, autoRotate]);

  return (
    <>
      <canvas
        ref={canvasRef}
        className="omh-system-canvas"
        role="img"
        aria-label="Animated three-dimensional neural cloud map of Smart Money Hub bots and workflows. Drag to rotate, pinch or scroll to zoom, and tap a glowing node to select it."
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
  const [selectedId, setSelectedId] = useState('ecosystem');
  const [revealedId, setRevealedId] = useState<string | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const runtimeQuery = useGetPortalBotConnections({
    query: {
      enabled: import.meta.env.DEV,
      queryKey: getGetPortalBotConnectionsQueryKey(),
      staleTime: 10_000,
      refetchOnMount: 'always',
      refetchInterval: import.meta.env.DEV ? 30_000 : false,
      refetchIntervalInBackground: false,
    },
  });
  const selectedNode = nodes.find((node) => node.id === selectedId) ?? nodes[0];
  const normalizedQuery = query.trim().toLowerCase();
  const visibleNodes = useMemo(() => nodes.filter((node) => {
    const matchesGroup = activeGroups.has(node.group);
    const matchesSearch = !normalizedQuery
      || `${node.title} ${node.subtitle} ${node.description} ${node.connects.join(' ')}`.toLowerCase().includes(normalizedQuery);
    return matchesGroup && matchesSearch;
  }), [activeGroups, normalizedQuery]);
  const visibleIds = new Set(visibleNodes.map(({ id }) => id));
  const selectedRuntime = runtimeIndicatorFor(
    selectedNode.id,
    runtimeQuery.data?.connections,
    runtimeQuery.isLoading,
    runtimeQuery.isError,
  );
  const labelIds = useMemo(() => new Set([
    ...(normalizedQuery ? visibleNodes.map(({ id }) => id) : []),
    ...(revealedId ? [revealedId] : []),
  ]), [normalizedQuery, visibleNodes, revealedId]);
  const runtimeByNode = useMemo(() => {
    const indicators = new Map<string, RuntimeIndicator>();
    nodes.forEach((node) => {
      const indicator = runtimeIndicatorFor(
        node.id,
        runtimeQuery.data?.connections,
        runtimeQuery.isLoading,
        runtimeQuery.isError,
      );
      if (indicator) indicators.set(node.id, indicator);
    });
    return indicators;
  }, [runtimeQuery.data?.connections, runtimeQuery.isLoading, runtimeQuery.isError]);

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
    setRevealedId(id);
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
              <h1>Smart Money Hub map</h1>
            </div>
          </div>
          <div className="omh-private"><ShieldCheck size={14} /> PRIVATE OWNER VIEW</div>
        </header>

        <section className="omh-intro" aria-labelledby="omh-page-title">
          <div>
            <p className="omh-kicker">ALL BOTS · ALL WORKFLOWS</p>
            <h2 id="omh-page-title">Every bot.<br /><em>Every function.</em></h2>
            <p className="omh-intro-copy">A connected view of bot identities, member journeys, publishing, support, and operations.</p>
          </div>
          <div className="omh-map-stamp">
            <span className="omh-stamp-dot" />
            <span>CONCEPTUAL TOPOLOGY</span>
            <small>Animated 3D · not live telemetry</small>
          </div>
        </section>

        <section className="omh-workspace" aria-label="Smart Money Hub bots and workflows">
          <div className="omh-map-column">
            <div className="omh-toolbar">
              <label className="omh-search">
                <Search size={16} aria-hidden="true" />
                <span className="omh-sr-only">Search bot workflows</span>
                <input
                  ref={searchRef}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Find a bot or workflow"
                  type="search"
                  data-testid="input-mindmap-search"
                />
                {query ? <button type="button" className="omh-clear-search" aria-label="Clear search" onClick={() => setQuery('')}><X size={14} /></button> : <kbd>⌘ K</kbd>}
              </label>
                <span className="omh-count">{visibleNodes.length.toString().padStart(2, '0')} <span>ITEMS IN VIEW</span></span>
            </div>

            <div className="omh-map-stage">
              <div className="omh-stage-grid" aria-hidden="true" />
              <SystemMap3D selectedId={selectedId} visibleIds={visibleIds} labelIds={labelIds} runtimeByNode={runtimeByNode} onSelect={selectNode} />
              <div className="omh-3d-caption">
                <span>SMART MONEY HUB · 3D ECOSYSTEM</span>
                <span>SEARCH OR TAP TO REVEAL · DRAG · PINCH</span>
              </div>
              <div className="omh-stage-foot"><span>ALL BOTS &amp; WORKFLOWS</span><span>DEV HEARTBEAT FEED</span><span>OWNER ONLY</span></div>
            </div>

            <div className="omh-runtime-legend" aria-label="Runtime status legend">
              <span><i className="tone-good" />Recent heartbeat</span>
              <span><i className="tone-caution" />Stale heartbeat</span>
              <span><i className="tone-neutral" />Unknown / no source</span>
            </div>

            <div className="omh-node-grid" aria-label="Smart Money Hub systems and workflows">
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
                        const runtime = runtimeIndicatorFor(
                          node.id,
                          runtimeQuery.data?.connections,
                          runtimeQuery.isLoading,
                          runtimeQuery.isError,
                        );
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
                            <span className="omh-node-label">
                              <strong>{node.title}</strong>
                              <small>{node.subtitle}</small>
                              {runtime && <span className={`omh-runtime-status tone-${runtime.tone}`} data-testid={`runtime-status-${node.id}`}><i />{runtime.label}</span>}
                            </span>
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
            {selectedRuntime && <section className={`omh-runtime-detail tone-${selectedRuntime.tone}`} aria-label={`${selectedNode.title} runtime status`} data-testid={`runtime-detail-${selectedNode.id}`}>
              <div className="omh-runtime-detail-heading"><Radio size={13} /><strong>{selectedRuntime.label === 'NO HEARTBEAT SOURCE' ? 'PROCESS STATUS · SOURCE NOT CONNECTED' : 'PROCESS STATUS · DEVELOPMENT FEED'}</strong><span className={`omh-runtime-status tone-${selectedRuntime.tone}`}><i />{selectedRuntime.label}</span></div>
              <p>{selectedRuntime.detail}</p>
              <small>{formatHeartbeat(selectedRuntime.lastHeartbeat)}</small>
              {selectedRuntime.identityStatus && <small>Telegram identity check · {selectedRuntime.identityStatus.replaceAll('_', ' ')}</small>}
            </section>}
            <div className="omh-detail-rule" />
            <p className="omh-detail-section-title">CONNECTED SYSTEMS <span>{String(selectedNode.connects.length).padStart(2, '0')}</span></p>
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
            <div className="omh-detail-note"><CircleHelp size={14} /><span>Runtime badges use the read-only Development heartbeat feed. Missing or stale heartbeats are not reported as “idle.” Other relationships are conceptual, and Production telemetry is not connected here.</span></div>
          </aside>
        </section>

        <footer className="omh-footer">
          <div className="omh-footer-left"><span className="omh-footer-mark"><Boxes size={14} /></span><span>SMART MONEY HUB <b>·</b> ALL SYSTEMS MAP</span></div>
          <div className="omh-footer-note">Animated ecosystem view · no process is started</div>
          <button className="omh-help" type="button" onClick={() => selectNode('health-recovery')} aria-label="View health and recovery workflow"><Globe2 size={15} /></button>
        </footer>
      </div>
    </main>
  );
}
