import { useEffect, useMemo, useRef, useState, type CSSProperties, type Dispatch, type KeyboardEvent as ReactKeyboardEvent, type SetStateAction } from 'react';
import {
  getGetPortalCommandCenterQueryKey,
  getGetPortalBotConnectionsQueryKey,
  useGetPortalCommandCenter,
  useGetPortalBotConnections,
} from '@workspace/api-client-react';
import type { PortalBotConnection, PortalCommandCenter } from '@workspace/api-client-react';
import {
  ArrowUpRight, Bot, BookOpen, Boxes, ChevronRight, CircleAlert, CircleHelp,
  Command, Database, Globe2, Layers3, Move, Network, Pause, Play, Radio, RotateCcw, Search,
  Settings2, ShieldCheck, Sparkles, X,
} from 'lucide-react';
import {
  DEFAULT_MIND_MAP_SETTINGS,
  MindMapSettingsPanel,
  type MindMapPalette,
  type MindMapLayout,
  type MindMapSettings,
  type MindMapTheme,
} from './owner-mind-map-controls';
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
const mapViews = ['Brain', 'Navigator', 'Numbers', 'Timeline', 'You', 'Lab', 'Review', 'Files', 'Learn'] as const;
type MapViewId = typeof mapViews[number];

const themeColors: Record<MindMapTheme, { background: string; panel: string; line: string; glow: string; accent: string }> = {
  Original: { background: '#070c0d', panel: '#0d1516', line: 'rgba(163,193,188,.12)', glow: 'rgba(27,95,75,.15)', accent: '#83e6c9' },
  Midnight: { background: '#060814', panel: '#0b1021', line: 'rgba(157,164,235,.16)', glow: 'rgba(81,79,165,.17)', accent: '#a5a6ff' },
  Graphite: { background: '#101112', panel: '#17191a', line: 'rgba(190,200,205,.15)', glow: 'rgba(105,117,123,.13)', accent: '#c6d0d3' },
  Plum: { background: '#100a12', panel: '#1a101e', line: 'rgba(195,150,210,.16)', glow: 'rgba(118,66,137,.16)', accent: '#d3a3e6' },
  Ember: { background: '#120b09', panel: '#1b100c', line: 'rgba(220,150,110,.17)', glow: 'rgba(158,78,39,.16)', accent: '#f4a379' },
};

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
  ecosystem: [0, 0.61, 0.34],
  'pro-signals-bot': [-0.23, 0.69, 0.16],
  'coach-bot': [0.23, 0.69, 0.16],
  'isolated-dev-bot': [-0.22, 0.5, 0.16],
  'whatsapp-assistant': [0.22, 0.5, 0.16],
  'signals-zones': [-0.28, 0.72, -0.07],
  'pro-channel': [0.28, 0.72, -0.07],
  'market-analysis': [-0.27, 0.56, -0.1],
  'education-sessions': [0.27, 0.56, -0.1],
  'member-academy': [-0.2, 0.47, -0.17],
  'pro-access': [0.2, 0.47, -0.17],
  'support-handoff': [0.02, 0.47, 0.27],
  'owner-review': [0, 0.79, -0.05],
  'health-recovery': [-0.09, 0.4, -0.22],
  'shared-records': [0.09, 0.4, -0.22],
};

const layoutCenters: Record<MindMapLayout, Record<GroupId, [number, number, number]>> = {
  Spheres: {
    bots: [-0.15, 0.67, 0.02],
    publishing: [0.15, 0.67, 0.02],
    members: [-0.15, 0.45, -0.12],
    operations: [0.15, 0.45, -0.12],
  },
  'Folder tree': {
    bots: [-0.2, 0.72, 0],
    publishing: [0.2, 0.72, 0],
    members: [-0.2, 0.44, -0.12],
    operations: [0.2, 0.44, -0.12],
  },
  Cloud: {
    bots: [-0.08, 0.68, 0.02],
    publishing: [0.08, 0.64, 0.02],
    members: [-0.07, 0.52, -0.08],
    operations: [0.07, 0.48, -0.08],
  },
};

const nodeColors: Record<GroupId, string> = {
  bots: '#83e6c9',
  publishing: '#e4bd79',
  members: '#d69aa8',
  operations: '#8dbed0',
};

const brainPaletteColors: Record<MindMapPalette, Record<GroupId, string>> = {
  Natural: { bots: '#c7b3a5', publishing: '#d3c1b5', members: '#d9cbbb', operations: '#cdb9ad' },
  Default: nodeColors,
  Lava: { bots: '#e99a59', publishing: '#dc7253', members: '#c85159', operations: '#f0bd64' },
  Ocean: { bots: '#83cbd4', publishing: '#72b5d2', members: '#8794d7', operations: '#9bd8c8' },
  Forest: { bots: '#9fbe77', publishing: '#6fae86', members: '#b1b77b', operations: '#5caa94' },
  Aurora: { bots: '#80d5b6', publishing: '#73c8d5', members: '#ad98df', operations: '#cf8dc8' },
  Mono: { bots: '#c6c6c6', publishing: '#999999', members: '#dedede', operations: '#777777' },
  Sunset: { bots: '#f19b69', publishing: '#e4747e', members: '#ce769d', operations: '#d3a05b' },
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

type DiagramIssueItem = {
  key: string;
  title: string;
  severity: 'warning' | 'critical';
  count: number;
  latestAt: string | null;
};

type DiagramIssueMarker = {
  severity: 'warning' | 'critical';
  count: number;
  items: DiagramIssueItem[];
};

type MapTimelineEntry = {
  key: string;
  kind: 'Alert' | 'Error';
  title: string;
  count: number;
  latestAt: string | null;
  severity: 'warning' | 'critical';
};

function buildIssueMarkers(data: PortalCommandCenter | undefined) {
  const collected = new Map<string, Map<string, DiagramIssueItem>>();
  if (!data || data.scope !== 'development_isolated_test') return new Map<string, DiagramIssueMarker>();

  const addIssue = (nodeId: string, issue: DiagramIssueItem) => {
    const items = collected.get(nodeId) ?? new Map<string, DiagramIssueItem>();
    const existing = items.get(issue.key);
    if (existing) {
      existing.count += issue.count;
      if (issue.latestAt && (!existing.latestAt || issue.latestAt > existing.latestAt)) existing.latestAt = issue.latestAt;
    } else {
      items.set(issue.key, { ...issue });
    }
    collected.set(nodeId, items);
  };

  data.alerts.forEach((alert) => {
    const targets = new Set<string>(['ecosystem']);
    if (alert.category === 'pro_stale_applications') {
      targets.add('pro-access');
      targets.add('support-handoff');
    } else if (alert.destination === 'PRO Signals') {
      targets.add('isolated-dev-bot');
      targets.add('signals-zones');
      targets.add('pro-channel');
    } else if (alert.destination === 'Market Analysis') {
      targets.add('isolated-dev-bot');
      targets.add('market-analysis');
    } else {
      targets.add('isolated-dev-bot');
      targets.add('health-recovery');
    }
    const issue: DiagramIssueItem = {
      key: `alert:${alert.category}:${alert.destination}`,
      title: alert.title,
      severity: alert.severity,
      count: alert.count,
      latestAt: alert.latestAt,
    };
    targets.forEach((nodeId) => addIssue(nodeId, issue));
  });

  const oneDayAgo = Date.now() - 24 * 60 * 60 * 1000;
  data.recentErrors.forEach((error) => {
    const errorAt = Date.parse(error.latestAt);
    if (!Number.isFinite(errorAt) || errorAt < oneDayAgo) return;
    const issue: DiagramIssueItem = {
      key: `error:${error.category}`,
      title: `Recorded ${error.category.replaceAll('_', ' ')} error`,
      severity: 'warning',
      count: error.count,
      latestAt: error.latestAt,
    };
    ['ecosystem', 'isolated-dev-bot', 'health-recovery'].forEach((nodeId) => addIssue(nodeId, issue));
  });

  return new Map([...collected.entries()].map(([nodeId, itemMap]) => {
    const items = [...itemMap.values()].sort((a, b) => {
      if (a.severity !== b.severity) return a.severity === 'critical' ? -1 : 1;
      return (b.latestAt ?? '').localeCompare(a.latestAt ?? '');
    });
    return [nodeId, {
      severity: items.some((item) => item.severity === 'critical') ? 'critical' as const : 'warning' as const,
      count: items.reduce((total, item) => total + item.count, 0),
      items,
    }];
  }));
}

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
  issuesByNode,
  settings,
  setSettings,
  activeGroups,
  onToggleGroup,
  onWalkthrough,
  onReset,
  onSelect,
}: {
  selectedId: string;
  visibleIds: Set<string>;
  labelIds: Set<string>;
  runtimeByNode: Map<string, RuntimeIndicator>;
  issuesByNode: Map<string, DiagramIssueMarker>;
  settings: MindMapSettings;
  setSettings: Dispatch<SetStateAction<MindMapSettings>>;
  activeGroups: Set<string>;
  onToggleGroup: (id: string) => void;
  onWalkthrough: () => void;
  onReset: () => void;
  onSelect: (id: string) => void;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [dragMode, setDragMode] = useState<'move' | 'rotate'>('move');
  const dragModeRef = useRef<'move' | 'rotate'>('move');
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const currentRef = useRef({ selectedId, visibleIds, labelIds, runtimeByNode, issuesByNode, settings, setSettings, onSelect });
  const resetViewRef = useRef<() => void>(() => {});
  const focusViewRef = useRef<() => void>(() => {});
  const redrawRef = useRef<() => void>(() => {});
  currentRef.current = { selectedId, visibleIds, labelIds, runtimeByNode, issuesByNode, settings, setSettings, onSelect };

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
    let panX = 0;
    let panY = 0;
    let tick = 0;
    let pointerDown = false;
    let pointerMoved = false;
    let lastX = 0;
    let lastY = 0;
    let pointerStartX = 0;
    let pointerStartY = 0;
    let projectedNodes: { id: string; x: number; y: number; depth: number }[] = [];
    let pinchDistance = 0;
    let pinchCenter: { x: number; y: number } | null = null;
    const pointers = new Map<number, { x: number; y: number }>();

    type CloudPoint = {
      x: number;
      y: number;
      z: number;
      nodeId: string;
      groupId: GroupId;
      size: number;
      phase: number;
      opacity: number;
      body: boolean;
      layoutTargets?: Record<MindMapLayout, [number, number, number]>;
      shade?: number;
      nx?: number;
      ny?: number;
      nz?: number;
      hub?: boolean;
    };
    type BrainFiber = { nodeId: string; points: { x: number; y: number; z: number }[] };
    type BrainLink = { from: CloudPoint; to: CloudPoint; groupId: GroupId };
    let seed = 934761;
    const random = () => {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    const randomNormal = () => {
      let uniform = 0;
      while (!uniform) uniform = random();
      return Math.sqrt(-2 * Math.log(uniform)) * Math.cos(2 * Math.PI * random());
    };
    const unitVector = (): [number, number, number] => {
      const x = randomNormal();
      const y = randomNormal();
      const z = randomNormal();
      const magnitude = Math.hypot(x, y, z) || 1;
      return [x / magnitude, y / magnitude, z / magnitude];
    };
    const groupDirections = groups.map((_, index) => {
      const angle = index * 2.4;
      const y = 1 - ((index + 0.5) / groups.length) * 2;
      const radius = Math.sqrt(1 - y * y);
      return [Math.cos(angle) * radius, y, Math.sin(angle) * radius] as const;
    });
    const nearestGroupId = (direction: [number, number, number]): GroupId => {
      let nearestIndex = 0;
      let nearestDistance = Number.POSITIVE_INFINITY;
      groupDirections.forEach((candidate, index) => {
        const distance = (candidate[0] - direction[0]) ** 2
          + (candidate[1] - direction[1]) ** 2
          + (candidate[2] - direction[2]) ** 2;
        if (distance < nearestDistance) {
          nearestIndex = index;
          nearestDistance = distance;
        }
      });
      return groups[nearestIndex].id;
    };
    const nearestNodeId = (point: { x: number; y: number; z: number }, groupId: GroupId) => {
      const candidates = nodes.filter((node) => node.group === groupId);
      return candidates.reduce((nearest, node) => {
        const [x, y, z] = nodePositions[node.id];
        const distance = (point.x - x) ** 2 + (point.y - y) ** 2 * 1.2 + (point.z - z) ** 2;
        return distance < nearest.distance ? { id: node.id, distance } : nearest;
      }, { id: candidates[0].id, distance: Number.POSITIVE_INFINITY }).id;
    };
    const cloudPoints: CloudPoint[] = [];
    const neuralStrands: BrainFiber[] = [];
    const brainLinks: BrainLink[] = [];
    const surfaceWave = (x: number, y: number, z: number) => {
      const waves = [
        [19, 5, 3, 0.3],
        [-7, 17, 9, 1.7],
        [6, -9, 21, 2.6],
        [15, 13, -12, 4.1],
        [-12, 6, 16, 5.3],
      ];
      return waves.reduce((value, [a, b, c, offset]) => value
        + Math.sin(a * x + b * y + c * z + offset + 1.6 * Math.sin(0.8 * (c * x - a * z) + offset)), 0) / waves.length;
    };
    const lightMagnitude = Math.hypot(-0.4, 0.7, 0.6);
    const lightDirection: [number, number, number] = [-0.4 / lightMagnitude, 0.7 / lightMagnitude, 0.6 / lightMagnitude];
    const brainPoint = (
      x: number,
      y: number,
      z: number,
      nx: number,
      ny: number,
      nz: number,
      groupId: GroupId,
    ) => {
      const normalLength = Math.hypot(nx, ny, nz) || 1;
      const normalX = nx / normalLength;
      const normalY = ny / normalLength;
      const normalZ = nz / normalLength;
      const scaledX = x / 0.3;
      const scaledY = (y - 0.6) / 0.2;
      const scaledZ = z / 0.36;
      let foldStrength = Math.min(1, Math.abs(surfaceWave(scaledX * 1.3, scaledY * 1.3, scaledZ * 1.3)) / 0.1);
      if (Math.abs(x) < 0.014 && scaledY > -0.5) foldStrength = 0;
      if (Math.abs(scaledY + 0.03 - 0.5 * scaledZ) < 0.07 && Math.abs(scaledX) > 0.55) foldStrength = Math.min(foldStrength, 0.05);
      if (scaledY > 0.1 && Math.abs(scaledZ - (0.12 - 0.3 * Math.abs(scaledX))) < 0.04) foldStrength = Math.min(foldStrength, 0.05);
      if (random() > 0.18 + 0.82 * foldStrength) return false;
      const light = Math.max(0, normalX * lightDirection[0] + normalY * lightDirection[1] + normalZ * lightDirection[2]);
      const shade = (0.22 + 0.78 * light) * (0.15 + 0.85 * Math.pow(foldStrength, 0.7));
      const compression = 1 - 0.1 * (1 - foldStrength);
      const point = {
        x: x * compression,
        y: 0.6 + (y - 0.6) * compression,
        z: z * compression,
      };
      cloudPoints.push({
        ...point,
        nodeId: nearestNodeId(point, groupId),
        groupId,
        size: 0.86 + random() * 0.28,
        phase: random() * Math.PI * 2,
        opacity: 0.78 + random() * 0.22,
        body: false,
        shade,
        nx: normalX,
        ny: normalY,
        nz: normalZ,
      });
      return true;
    };
    const temporalRegion = (x: number, y: number, z: number) => ((Math.abs(x) - 0.18) / 0.1) ** 2
      + ((y - 0.5) / 0.09) ** 2 + ((z - 0.04) / 0.21) ** 2;
    const cerebrumInterior = (x: number, y: number, z: number) => (x / 0.29) ** 2
      + ((y - 0.62) / 0.2) ** 2 + (z / 0.36) ** 2;

    let accepted = 0;
    for (let attempts = 0; accepted < 16_000 && attempts < 110_000; attempts += 1) {
      const [a, rawB, c] = unitVector();
      const b = rawB < 0 ? rawB * 0.75 : rawB;
      const x = a * 0.29 * (1 - 0.2 * Math.max(0, c));
      const y = 0.62 + b * 0.2;
      const z = c * 0.36;
      if (temporalRegion(x, y, z) < 1) continue;
      const groupId = nearestGroupId([a + randomNormal() * 0.2, b + randomNormal() * 0.2, c + randomNormal() * 0.2]);
      if (brainPoint(x, y, z, a / 0.29, b / 0.2, c / 0.36, groupId)) accepted += 1;
    }

    accepted = 0;
    for (let attempts = 0; accepted < 3_600 && attempts < 30_000; attempts += 1) {
      const [a, b, c] = unitVector();
      const side = random() < 0.5 ? -1 : 1;
      const x = side * (0.18 + a * 0.1);
      const y = 0.5 + b * 0.09;
      const z = 0.04 + c * 0.21;
      if (cerebrumInterior(x, y, z) < 1) continue;
      const groupId = nearestGroupId([side * 0.5 + randomNormal() * 0.2, -0.6, 0.3]);
      if (brainPoint(x, y, z, side * a / 0.1, b / 0.09, c / 0.21, groupId)) accepted += 1;
    }

    for (let index = 0; index < 1_600; index += 1) {
      const [a, b, c] = unitVector();
      const folia = 0.5 + 0.5 * Math.sin(b * 80 + a * 2);
      const normalLength = Math.hypot(a / 0.19, b / 0.085, c / 0.13) || 1;
      const light = Math.max(0, (a / 0.19 * lightDirection[0] + b / 0.085 * lightDirection[1] + c / 0.13 * lightDirection[2]) / normalLength);
      const groupId = groups[Math.floor(random() * groups.length)].id;
      const point = { x: a * 0.19, y: 0.41 + b * 0.085, z: -0.21 + c * 0.13 };
      cloudPoints.push({
        ...point,
        nodeId: nearestNodeId(point, groupId),
        groupId,
        size: 0.86 + random() * 0.28,
        phase: random() * Math.PI * 2,
        opacity: 0.78 + random() * 0.22,
        body: false,
        shade: (0.22 + 0.78 * light) * (0.2 + 0.8 * folia),
        nx: a,
        ny: b,
        nz: c,
      });
    }

    const brainstemCenter = (y: number): [number, number, number] => [
      0.015 * (0.04 - y) * 3,
      y,
      -0.09 + 0.03 * (y - 0.04) / 0.36,
    ];
    const brainstemRadius = (y: number) => 0.036 + 0.035 * Math.exp(-(((y - 0.22) / 0.07) ** 2));
    for (let index = 0; index < 350; index += 1) {
      const y = 0.17 + random() * 0.23;
      const angle = random() * Math.PI * 2;
      const radius = brainstemRadius(y) * Math.sqrt(random());
      const [centerX, centerY, centerZ] = brainstemCenter(y);
      cloudPoints.push({
        x: centerX + Math.cos(angle) * radius,
        y: centerY,
        z: centerZ + Math.sin(angle) * radius,
        nodeId: 'health-recovery',
        groupId: 'operations',
        size: 0.86 + random() * 0.28,
        phase: random() * Math.PI * 2,
        opacity: 0.78 + random() * 0.22,
        body: true,
      });
    }

    const catmullRom = (controlPoints: [number, number, number][], progress: number): [number, number, number] => {
      const lastSegment = controlPoints.length - 1;
      const scaledProgress = progress * lastSegment;
      const segment = Math.min(lastSegment - 1, Math.floor(scaledProgress));
      const fraction = scaledProgress - segment;
      const p0 = controlPoints[Math.max(0, segment - 1)];
      const p1 = controlPoints[segment];
      const p2 = controlPoints[segment + 1];
      const p3 = controlPoints[Math.min(lastSegment, segment + 2)];
      return [0, 1, 2].map((axis) => 0.5 * (
        2 * p1[axis]
        + (p2[axis] - p0[axis]) * fraction
        + (2 * p0[axis] - 5 * p1[axis] + 4 * p2[axis] - p3[axis]) * fraction ** 2
        + (3 * p1[axis] - p0[axis] - 3 * p2[axis] + p3[axis]) * fraction ** 3
      )) as [number, number, number];
    };
    for (let strandIndex = 0; strandIndex < 6; strandIndex += 1) {
      const angle = strandIndex * 1.05;
      const controlPoints: [number, number, number][] = [];
      for (let pointIndex = 0; pointIndex <= 3; pointIndex += 1) {
        const y = 0.4 - pointIndex * 0.08;
        const [centerX, , centerZ] = brainstemCenter(y);
        const radius = brainstemRadius(y) * 0.8;
        controlPoints.push([centerX + Math.cos(angle) * radius, y, centerZ + Math.sin(angle) * radius]);
      }
      const points = Array.from({ length: 23 }, (_, pointIndex) => {
        const [x, y, z] = catmullRom(controlPoints, pointIndex / 22);
        return { x, y, z };
      });
      neuralStrands.push({ nodeId: 'health-recovery', points });
    }

    const volumeOffset = (radius: number): [number, number, number] => {
      const [x, y, z] = unitVector();
      const distance = Math.cbrt(random()) * radius;
      return [x * distance, y * distance, z * distance];
    };
    cloudPoints.forEach((point) => {
      const sphereOffset = volumeOffset(point.body ? 0.035 : 0.085);
      const folderOffset = volumeOffset(point.body ? 0.028 : 0.065);
      const cloudOffset = volumeOffset(point.body ? 0.08 : 0.34);
      const sphereCenter = layoutCenters.Spheres[point.groupId];
      const folderCenter = layoutCenters['Folder tree'][point.groupId];
      const cloudCenter = layoutCenters.Cloud[point.groupId];
      point.layoutTargets = {
        Spheres: [sphereCenter[0] + sphereOffset[0], sphereCenter[1] + sphereOffset[1], sphereCenter[2] + sphereOffset[2]],
        'Folder tree': [folderCenter[0] + folderOffset[0], folderCenter[1] + folderOffset[1], folderCenter[2] + folderOffset[2]],
        Cloud: [cloudCenter[0] + cloudOffset[0], cloudCenter[1] + cloudOffset[1], cloudCenter[2] + cloudOffset[2]],
      };
    });

    const pointsByGroup = new Map<GroupId, CloudPoint[]>(
      groups.map((group) => [group.id, cloudPoints.filter((point) => !point.body && point.groupId === group.id)]),
    );
    for (let hubIndex = 0; hubIndex < 16; hubIndex += 1) {
      const groupId = groups[hubIndex % groups.length].id;
      const sameGroupPoints = pointsByGroup.get(groupId) ?? [];
      const hub = sameGroupPoints[Math.floor(random() * sameGroupPoints.length)];
      if (!hub) continue;
      hub.hub = true;
      let linked = 0;
      for (let attempt = 0; attempt < 900 && linked < 22; attempt += 1) {
        const point = sameGroupPoints[Math.floor(random() * sameGroupPoints.length)];
        if (!point || point === hub) continue;
        const distance = Math.hypot(point.x - hub.x, point.y - hub.y, point.z - hub.z);
        if (distance < 0.3) {
          brainLinks.push({ from: hub, to: point, groupId });
          linked += 1;
        }
      }
    }
    const toRgba = (hex: string, alpha: number) => {
      const value = Number.parseInt(hex.slice(1), 16);
      return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
    };
    const nodeGroupById = new Map(nodes.map((node) => [node.id, node.group]));
    const brainSpritesByPalette = new Map<MindMapPalette, Map<GroupId, HTMLCanvasElement>>();
    (Object.keys(brainPaletteColors) as MindMapPalette[]).forEach((palette) => {
      const sprites = new Map<GroupId, HTMLCanvasElement>();
      groups.forEach((group) => {
        const sprite = document.createElement('canvas');
        sprite.width = sprite.height = 32;
        const spriteContext = sprite.getContext('2d');
        if (!spriteContext) return;
        const color = brainPaletteColors[palette][group.id];
        const gradient = spriteContext.createRadialGradient(16, 16, 0, 16, 16, 16);
        gradient.addColorStop(0, '#fff');
        gradient.addColorStop(0.18, color);
        gradient.addColorStop(0.5, toRgba(color, 0.25));
        gradient.addColorStop(1, toRgba(color, 0));
        spriteContext.fillStyle = gradient;
        spriteContext.fillRect(0, 0, 32, 32);
        sprites.set(group.id, sprite);
      });
      brainSpritesByPalette.set(palette, sprites);
    });

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
      const centerY = height / 2;
      const baseScale = Math.min(width * 1.5, height * 0.7);
      const scale = baseScale * zoom;
      const settings = currentRef.current.settings;
      const pointScale = (baseScale / 330) * Math.sqrt(zoom) * (settings.pointSize / 100);
      const cosYaw = Math.cos(yaw);
      const sinYaw = Math.sin(yaw);
      const cosPitch = Math.cos(pitch);
      const sinPitch = Math.sin(pitch);
      const projected = nodes.map((node) => {
        const [brainX, brainY, brainZ] = nodePositions[node.id];
        const sameGroup = nodes.filter((candidate) => candidate.group === node.group);
        const groupIndex = sameGroup.findIndex((candidate) => candidate.id === node.id);
        const angle = (groupIndex / Math.max(1, sameGroup.length)) * Math.PI * 2;
        const center = layoutCenters[settings.layout][node.group];
        const offsetRadius = settings.layout === 'Cloud' ? 0.055 : 0.035;
        const targetX = center[0] + Math.cos(angle) * offsetRadius;
        const targetY = center[1] + Math.sin(angle) * offsetRadius;
        const targetZ = center[2] + Math.sin(angle * 1.7) * offsetRadius;
        const anatomy = settings.anatomy / 100;
        const x = targetX + (brainX - targetX) * anatomy;
        const y = targetY + (brainY - targetY) * anatomy;
        const z = targetZ + (brainZ - targetZ) * anatomy;
        const rotatedX = x * cosYaw + z * sinYaw;
        const rotatedZ = -x * sinYaw + z * cosYaw;
        const centeredY = y - 0.58;
        const rotatedY = centeredY * cosPitch - rotatedZ * sinPitch;
        const depth = centeredY * sinPitch + rotatedZ * cosPitch;
        const perspective = 3.4 / (3.4 + depth);
        return {
          node,
          x: centerX + panX + rotatedX * scale * perspective,
          y: centerY + panY - rotatedY * scale * perspective,
          depth,
          perspective,
        };
      });
      projectedNodes = projected.map(({ node, x, y, depth }) => ({ id: node.id, x, y, depth }));

      const displayCloudPoint = (point: CloudPoint) => {
        const target = point.layoutTargets?.[settings.layout] ?? [point.x, point.y, point.z];
        const anatomy = settings.anatomy / 100;
        return {
          x: target[0] + (point.x - target[0]) * anatomy,
          y: target[1] + (point.y - target[1]) * anatomy,
          z: target[2] + (point.z - target[2]) * anatomy,
        };
      };
      const projectCloudPoint = (point: { x: number; y: number; z: number }) => {
        const rotatedX = point.x * cosYaw + point.z * sinYaw;
        const rotatedZ = -point.x * sinYaw + point.z * cosYaw;
        const centeredY = point.y - 0.58;
        const rotatedY = centeredY * cosPitch - rotatedZ * sinPitch;
        const depth = centeredY * sinPitch + rotatedZ * cosPitch;
        const perspective = 3.4 / (3.4 + depth);
        return {
          x: centerX + panX + rotatedX * scale * perspective,
          y: centerY + panY - rotatedY * scale * perspective,
          depth,
          perspective,
        };
      };

      const backdrop = context.createRadialGradient(centerX, centerY - scale * 0.08, scale * 0.04, centerX, centerY, scale * 1.2);
      backdrop.addColorStop(0, toRgba(themeColors[settings.theme].accent, 0.11));
      backdrop.addColorStop(0.55, toRgba(themeColors[settings.theme].accent, 0.045));
      backdrop.addColorStop(1, 'rgba(3,8,8,0)');
      context.fillStyle = backdrop;
      context.fillRect(0, 0, width, height);

      context.globalCompositeOperation = 'lighter';
      if (settings.showLinks && settings.showBrainstem) neuralStrands.forEach(({ nodeId, points }) => {
        const color = brainPaletteColors[settings.palette][nodeGroupById.get(nodeId) ?? 'operations'];
        const active = currentRef.current.visibleIds.has(nodeId);
        context.beginPath();
        points.forEach((point, index) => {
          const center = layoutCenters[settings.layout].operations;
          const anatomy = settings.anatomy / 100;
          const projectedPoint = projectCloudPoint({
            x: center[0] + (point.x - center[0]) * anatomy,
            y: center[1] + (point.y - center[1]) * anatomy,
            z: center[2] + (point.z - center[2]) * anatomy,
          });
          if (index === 0) context.moveTo(projectedPoint.x, projectedPoint.y);
          else context.lineTo(projectedPoint.x, projectedPoint.y);
        });
        context.strokeStyle = toRgba(color, active ? 0.17 : 0.012);
        context.lineWidth = 0.6;
        context.stroke();
      });

      if (settings.showLinks) brainLinks.forEach(({ from, to, groupId }) => {
        if (!currentRef.current.visibleIds.has(from.nodeId) || !currentRef.current.visibleIds.has(to.nodeId)) return;
        const start = projectCloudPoint(displayCloudPoint(from));
        const end = projectCloudPoint(displayCloudPoint(to));
        context.strokeStyle = toRgba(brainPaletteColors[settings.palette][groupId], 0.13);
        context.lineWidth = 0.7;
        context.beginPath();
        context.moveTo(start.x, start.y);
        context.lineTo(end.x, end.y);
        context.stroke();
      });

      cloudPoints.forEach((particle) => {
        if (particle.body && !settings.showBrainstem) return;
        const point = projectCloudPoint(displayCloudPoint(particle));
        const active = currentRef.current.visibleIds.has(particle.nodeId);
        const groupId = particle.groupId;
        const sprite = brainSpritesByPalette.get(settings.palette)?.get(groupId);
        if (!sprite) return;
        let faceAlpha = 1;
        if (particle.nx !== undefined && particle.ny !== undefined && particle.nz !== undefined) {
          const normalDepth = sinPitch * particle.ny
            + cosPitch * (-particle.nx * sinYaw + particle.nz * cosYaw);
          faceAlpha = normalDepth > 0.12 ? 0 : normalDepth > -0.05 ? 0.5 : 1;
          if (!faceAlpha) return;
        }
        const depthAlpha = Math.max(0.24, 0.92 - point.depth * 0.38);
        const foldLight = particle.shade === undefined ? 1 : Math.min(1.4, particle.shade * 2.4);
        const hubScale = (particle.hub ? 2.2 : 1) * (particle.body ? 0.55 : 0.6);
        const spriteSize = (2.4 + 4 * point.perspective) * pointScale * particle.size * hubScale;
        context.globalAlpha = Math.min(
          1,
          foldLight * particle.opacity * depthAlpha * faceAlpha * (active ? 1 : 0.05) * (particle.hub ? 1.6 : 0.9),
        );
        context.drawImage(sprite, point.x - spriteSize / 2, point.y - spriteSize / 2, spriteSize, spriteSize);
      });
      context.globalAlpha = 1;
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
      if (settings.showLinks) Array.from(connectionSet).forEach((key, index) => {
        const [fromId, toId] = key.split('|');
        const fromIndex = nodes.findIndex(({ id }) => id === fromId);
        const toIndex = nodes.findIndex(({ id }) => id === toId);
        const from = projected[fromIndex];
        const to = projected[toIndex];
        if (!from || !to) return;
        const shown = currentRef.current.visibleIds.has(fromId) && currentRef.current.visibleIds.has(toId);
        const nearer = Math.max(0, 1 - Math.max(from.depth, to.depth) / 3);
        context.strokeStyle = toRgba(themeColors[settings.theme].accent, (shown ? 0.22 : 0.045) * (0.45 + nearer * 0.55));
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
          context.fillStyle = toRgba(themeColors[settings.theme].accent, 0.82);
          context.shadowColor = themeColors[settings.theme].accent;
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
          const radius = (selected ? 4.5 : 3.6) * Math.max(0.72, perspective);
          const alpha = active ? Math.max(0.48, 0.92 - depth * 0.14) : 0.15;

          context.globalAlpha = alpha;
          const glow = context.createRadialGradient(x, y, 0, x, y, radius * 2.4);
          glow.addColorStop(0, `${color}70`);
          glow.addColorStop(1, `${color}00`);
          context.fillStyle = glow;
          context.beginPath();
          context.arc(x, y, radius * 2.4, 0, Math.PI * 2);
          context.fill();

          context.fillStyle = '#091110';
          context.strokeStyle = color;
          context.lineWidth = selected ? 1.5 : 1.1;
          context.beginPath();
          context.arc(x, y, radius, 0, Math.PI * 2);
          context.fill();
          context.stroke();

          if (selected) {
            context.strokeStyle = `${color}80`;
            context.lineWidth = 1;
            context.beginPath();
            context.arc(x, y, radius + 4, 0, Math.PI * 2);
            context.stroke();
          }

          const issueMarker = currentRef.current.issuesByNode.get(node.id);
          if (issueMarker) {
            const issueColor = issueMarker.severity === 'critical' ? '#ff7770' : '#e2bc76';
            const pulse = reducedMotion.matches ? 0 : Math.sin(tick * 0.08) * 0.8;
            context.globalAlpha = active ? 0.94 : 0.3;
            context.strokeStyle = issueColor;
            context.lineWidth = 1.5;
            context.beginPath();
            context.arc(x, y, radius + 3 + pulse, 0, Math.PI * 2);
            context.stroke();
            context.fillStyle = issueColor;
            context.beginPath();
            context.arc(x - radius * 1.45, y - radius * 1.45, 2, 0, Math.PI * 2);
            context.fill();
          }

          const runtime = currentRef.current.runtimeByNode.get(node.id);
          if (runtime) {
            const statusColor = runtime.tone === 'good' ? '#80e2b8' : runtime.tone === 'caution' ? '#e2bc76' : '#84958e';
            context.globalAlpha = active ? 1 : 0.28;
            context.fillStyle = '#07100e';
            context.beginPath();
            context.arc(x + radius * 1.45, y - radius * 1.45, 3.2, 0, Math.PI * 2);
            context.fill();
            context.fillStyle = statusColor;
            context.beginPath();
            context.arc(x + radius * 1.45, y - radius * 1.45, 2, 0, Math.PI * 2);
            context.fill();
          }

          const showLabel = currentRef.current.settings.showLabels || currentRef.current.labelIds.has(node.id);
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
        if (settings.turning && !pointerDown) {
          if (settings.limitRotation) yaw = -0.28 + Math.sin(tick * (0.0012 + settings.speed * 0.0001)) * 0.9;
          else yaw += 0.0012 + (settings.speed / 100) * 0.01;
        }
        tick += 1;
        frame = window.requestAnimationFrame(draw);
      }
    };

    resetViewRef.current = () => {
      yaw = -0.28;
      pitch = 0.12;
      zoom = 1;
      panX = 0;
      panY = 0;
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
        pinchCenter = { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 };
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
        const center = { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 };
        if (pinchDistance > 0) zoom = Math.max(0.4, Math.min(4.5, zoom * distance / pinchDistance));
        if (pinchCenter) {
          panX += center.x - pinchCenter.x;
          panY += center.y - pinchCenter.y;
        }
        pinchDistance = distance;
        pinchCenter = center;
        if (reducedMotion.matches) draw();
        return;
      }
      if (!pointerDown) return;
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      if (Math.hypot(event.clientX - pointerStartX, event.clientY - pointerStartY) > 5) pointerMoved = true;
      if (pointerMoved) {
        if (dragModeRef.current === 'move') {
          panX += dx;
          panY += dy;
        } else {
          yaw += dx * 0.008;
          pitch = Math.max(-0.8, Math.min(0.8, pitch + dy * 0.006));
        }
        if (reducedMotion.matches) draw();
      }
      lastX = event.clientX;
      lastY = event.clientY;
    };
    const pointerEnd = (event: PointerEvent) => {
      const wasTap = pointerDown && !pointerMoved && pointers.size === 1;
      pointerDown = false;
      pointers.delete(event.pointerId);
      if (pointers.size < 2) {
        pinchDistance = 0;
        pinchCenter = null;
      }
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
      zoom = Math.max(0.4, Math.min(4.5, zoom * Math.exp(-event.deltaY * 0.001)));
      if (reducedMotion.matches) draw();
    };
    focusViewRef.current = () => {
      zoom = zoom > 1.45 ? 1 : 1.55;
      panX = 0;
      panY = 0;
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
      focusViewRef.current = () => {};
      redrawRef.current = () => {};
    };
  }, []);

  useEffect(() => {
    redrawRef.current();
  }, [selectedId, visibleIds, labelIds, runtimeByNode, issuesByNode, settings]);

  return (
    <>
      <canvas
        ref={canvasRef}
        className="omh-system-canvas"
        role="img"
        aria-label="Animated three-dimensional neural cloud map of Smart Money Hub bots and workflows. Drag to move, switch to rotate mode to turn it, pinch or scroll to zoom, and tap a glowing node to select it."
        data-testid="canvas-owner-system-map-3d"
      />
      <div className="omh-3d-controls" aria-label="3D map controls">
        <button type="button" onClick={() => setSettings((current) => ({ ...current, turning: !current.turning }))} aria-pressed={settings.turning} aria-label={settings.turning ? 'Pause automatic rotation' : 'Resume automatic rotation'} title={settings.turning ? 'Pause rotation' : 'Resume rotation'}>
          {settings.turning ? <Pause size={12} /> : <Play size={12} />}
          <span>{settings.turning ? 'PAUSE' : 'AUTO'}</span>
        </button>
        <button
          type="button"
          onClick={() => {
            const nextMode = dragModeRef.current === 'move' ? 'rotate' : 'move';
            dragModeRef.current = nextMode;
            setDragMode(nextMode);
          }}
          aria-pressed={dragMode === 'move'}
          aria-label={dragMode === 'move' ? 'Drag mode: move map. Switch to rotate' : 'Drag mode: rotate map. Switch to move'}
          title={dragMode === 'move' ? 'Drag to move · tap to switch to rotate' : 'Drag to rotate · tap to switch to move'}
        >
          {dragMode === 'move' ? <Move size={12} /> : <RotateCcw size={12} />}
          <span>{dragMode === 'move' ? 'MOVE' : 'ROTATE'}</span>
        </button>
        <button type="button" onClick={() => setSettingsOpen((open) => !open)} aria-expanded={settingsOpen} aria-controls="omh-map-settings" aria-label="Open mind map settings" title="Settings"><Settings2 size={12} /></button>
        <button type="button" onClick={() => resetViewRef.current()} aria-label="Reset 3D map view" title="Reset view"><RotateCcw size={12} /></button>
      </div>
      <MindMapSettingsPanel
        open={settingsOpen}
        settings={settings}
        setSettings={setSettings}
        groups={groups}
        activeGroups={activeGroups}
        onToggleGroup={onToggleGroup}
        onClose={() => setSettingsOpen(false)}
        onWalkthrough={onWalkthrough}
        onRestoreBrain={() => {
          setSettings((current) => ({ ...current, layout: 'Spheres', anatomy: 100, palette: 'Natural' }));
          resetViewRef.current();
        }}
        onFocusBrain={() => focusViewRef.current()}
        onReset={() => { onReset(); resetViewRef.current(); setSettingsOpen(false); }}
      />
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
  const [settings, setSettings] = useState<MindMapSettings>(DEFAULT_MIND_MAP_SETTINGS);
  const [walkthroughStep, setWalkthroughStep] = useState<number | null>(null);
  const [activeView, setActiveView] = useState<MapViewId>('Brain');
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
  const issueQuery = useGetPortalCommandCenter({
    query: {
      enabled: import.meta.env.DEV,
      queryKey: getGetPortalCommandCenterQueryKey(),
      staleTime: 15_000,
      refetchOnMount: 'always',
      refetchInterval: import.meta.env.DEV ? 30_000 : false,
      refetchIntervalInBackground: false,
    },
  });
  const normalizedQuery = query.trim().toLowerCase();
  const visibleNodes = useMemo(() => nodes.filter((node) => {
    const matchesGroup = activeGroups.has(node.group);
    const matchesSearch = !normalizedQuery
      || `${node.title} ${node.subtitle} ${node.description} ${node.connects.join(' ')}`.toLowerCase().includes(normalizedQuery);
    const runtime = runtimeIndicatorFor(
      node.id,
      runtimeQuery.data?.connections,
      runtimeQuery.isLoading,
      runtimeQuery.isError,
    );
    const hasRuntimeEvidence = runtime?.label === 'RUNNING' || runtime?.label === 'STALE';
    const matchesEvidence = !settings.hideUnverified || hasRuntimeEvidence;
    return matchesGroup && matchesSearch && matchesEvidence;
  }), [activeGroups, normalizedQuery, runtimeQuery.data?.connections, runtimeQuery.isLoading, runtimeQuery.isError, settings.hideUnverified]);
  const visibleIds = new Set(visibleNodes.map(({ id }) => id));
  const selectedNode = visibleNodes.find((node) => node.id === selectedId) ?? visibleNodes[0] ?? nodes[0];
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
  const issuesByNode = useMemo(() => buildIssueMarkers(issueQuery.data), [issueQuery.data]);
  const displayGroups = useMemo(() => {
    if (settings.groupBy === 'Function') {
      return groups.map((group) => ({
        ...group,
        nodes: visibleNodes.filter((node) => node.group === group.id),
      })).filter((group) => group.nodes.length > 0);
    }
    if (settings.groupBy === 'Recorded issues') {
      return [
        { id: 'recorded-issues', label: 'Recorded issues', color: 'rose' as const, nodes: visibleNodes.filter((node) => issuesByNode.has(node.id)) },
        { id: 'no-recorded-issues', label: 'No recorded issues', color: 'mint' as const, nodes: visibleNodes.filter((node) => !issuesByNode.has(node.id)) },
      ].filter((group) => group.nodes.length > 0);
    }
    const statusFor = (node: MapNode) => {
      const indicator = runtimeIndicatorFor(
        node.id,
        runtimeQuery.data?.connections,
        runtimeQuery.isLoading,
        runtimeQuery.isError,
      );
      if (indicator?.label === 'RUNNING') return 'Recent heartbeat';
      if (indicator?.label === 'STALE') return 'Stale heartbeat';
      if (indicator?.label === 'UNKNOWN' || indicator?.label === 'NO HEARTBEAT SOURCE') return 'Unknown / no source';
      return 'Workflow not monitored';
    };
    return [
      { id: 'recent', label: 'Recent heartbeat', color: 'mint' as const },
      { id: 'stale', label: 'Stale heartbeat', color: 'amber' as const },
      { id: 'unknown', label: 'Unknown / no source', color: 'rose' as const },
      { id: 'unmonitored', label: 'Workflow not monitored', color: 'blue' as const },
    ].map((group) => ({
      ...group,
      nodes: visibleNodes.filter((node) => statusFor(node) === group.label),
    })).filter((group) => group.nodes.length > 0);
  }, [settings.groupBy, visibleNodes, issuesByNode, runtimeQuery.data?.connections, runtimeQuery.isLoading, runtimeQuery.isError]);
  const selectedIssues = issuesByNode.get(selectedNode.id);
  const issueFeedText = !import.meta.env.DEV
    ? 'Development issue feed only'
    : issueQuery.isLoading
      ? 'Checking Development issue feed'
      : issueQuery.isError
        ? 'Issue feed unavailable · health cannot be confirmed'
        : `${issuesByNode.get('ecosystem')?.count ?? 0} recorded Development issues · not a Production health check`;
  const timelineItems = useMemo(() => {
    if (!import.meta.env.DEV || issueQuery.data?.scope !== 'development_isolated_test') return [];
    const entries: MapTimelineEntry[] = [
      ...issueQuery.data.alerts.map((alert) => ({
        key: `alert:${alert.category}:${alert.destination}`,
        kind: 'Alert' as const,
        title: alert.title,
        count: alert.count,
        latestAt: alert.latestAt,
        severity: alert.severity,
      })),
      ...issueQuery.data.recentErrors.map((error) => ({
        key: `error:${error.category}`,
        kind: 'Error' as const,
        title: `Recorded ${error.category.replaceAll('_', ' ')} error`,
        count: error.count,
        latestAt: error.latestAt,
        severity: 'warning' as const,
      })),
    ];
    return entries.sort((a, b) => (b.latestAt ?? '').localeCompare(a.latestAt ?? '')).slice(0, 20);
  }, [issueQuery.data]);
  const runtimeCounts = useMemo(() => {
    const connections = import.meta.env.DEV ? runtimeQuery.data?.connections ?? [] : [];
    return {
      running: connections.filter((connection) => connection.runtimeStatus === 'running').length,
      stale: connections.filter((connection) => connection.runtimeStatus === 'stale').length,
      unknown: connections.filter((connection) => connection.runtimeStatus === 'unknown').length,
    };
  }, [runtimeQuery.data?.connections]);

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

  const resetAllSettings = () => {
    setSettings(DEFAULT_MIND_MAP_SETTINGS);
    setActiveGroups(new Set(groups.map(({ id }) => id)));
    setQuery('');
    setRevealedId(null);
    setSelectedId('ecosystem');
    setMobileDetailOpen(false);
    setActiveView('Brain');
    setWalkthroughStep(null);
  };

  const selectFromKeyboard = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const nextIndex = (index + (event.key === 'ArrowDown' ? 1 : visibleNodes.length - 1)) % visibleNodes.length;
    document.getElementById(`omh-node-${visibleNodes[nextIndex]?.id}`)?.focus();
  };

  const renderViewPanel = () => {
    if (activeView === 'Brain') return null;
    if (activeView === 'Navigator') {
      return (
        <section className="omh-view-panel" aria-label="System navigator">
          <div className="omh-view-heading"><span>NAVIGATOR</span><strong>Jump to a system</strong><small>{visibleNodes.length} systems match your current filters.</small></div>
          <div className="omh-view-node-links">{visibleNodes.map((node) => (
            <button type="button" key={node.id} onClick={() => selectNode(node.id)} className={`tone-${groupById.get(node.group)?.color ?? 'mint'}`}>
              <span>{node.title}</span><small>{node.subtitle}</small><ArrowUpRight size={13} />
            </button>
          ))}</div>
        </section>
      );
    }
    if (activeView === 'Numbers') {
      const totalIssues = timelineItems.reduce((sum, item) => sum + item.count, 0);
      return (
        <section className="omh-view-panel" aria-label="Map counts">
          <div className="omh-view-heading"><span>NUMBERS</span><strong>What is in this map</strong><small>Counts describe the map and connected Development records, not live Production health.</small></div>
          <div className="omh-metric-grid">
            <article><span>Mapped systems</span><strong>{nodes.length}</strong></article>
            <article><span>Functions</span><strong>{groups.length}</strong></article>
            <article><span>Development heartbeats</span><strong>{runtimeCounts.running}</strong></article>
            <article><span>Development issue entries</span><strong>{totalIssues}</strong></article>
          </div>
          <div className="omh-count-bars" aria-label="Mapped systems by function">
            {groups.map((group) => {
              const count = nodes.filter((node) => node.group === group.id).length;
              return <div key={group.id} className={`tone-${group.color}`}><span>{group.label}</span><i><b style={{ width: `${(count / Math.max(...groups.map((item) => nodes.filter((node) => node.group === item.id).length))) * 100}%` }} /></i><strong>{count}</strong></div>;
            })}
          </div>
        </section>
      );
    }
    if (activeView === 'Timeline' || activeView === 'Review') {
      const entries = activeView === 'Review'
        ? [...timelineItems].sort((a, b) => (a.severity === 'critical' ? -1 : 1) - (b.severity === 'critical' ? -1 : 1))
        : timelineItems;
      return (
        <section className="omh-view-panel" aria-label={activeView === 'Review' ? 'Issue review' : 'Recorded issue timeline'}>
          <div className="omh-view-heading"><span>{activeView === 'Review' ? 'REVIEW' : 'TIMELINE'}</span><strong>{activeView === 'Review' ? 'Recorded issues to review' : 'Recent recorded events'}</strong><small>{import.meta.env.DEV ? 'Read-only Development feed. A stored alert may no longer be active.' : 'The Development timeline is not available in this view.'}</small></div>
          {!import.meta.env.DEV && <div className="omh-view-empty">The Development issue timeline is not available in this build.</div>}
          {import.meta.env.DEV && issueQuery.isLoading && <div className="omh-view-empty">Checking the Development issue feed…</div>}
          {import.meta.env.DEV && issueQuery.isError && <div className="omh-view-empty is-warning">Development issue feed unavailable. Current health cannot be confirmed.</div>}
          {import.meta.env.DEV && !issueQuery.isLoading && !issueQuery.isError && !timelineItems.length && <div className="omh-view-empty">No recorded Development alerts or recent errors are available.</div>}
          <div className="omh-timeline-list">
            {entries.map((item) => <article key={item.key} className={`severity-${item.severity}`}>
              <span className="omh-timeline-kind">{item.kind}</span>
              <div><strong>{item.title}</strong><small>{item.count} recorded{item.latestAt ? ` · ${formatHeartbeat(item.latestAt)}` : ''}</small></div>
              <span className="omh-timeline-severity">{item.severity}</span>
            </article>)}
          </div>
        </section>
      );
    }
    if (activeView === 'You') {
      return <section className="omh-view-panel" aria-label="Owner view"><div className="omh-view-heading"><span>OWNER VIEW</span><strong>Your private system map</strong><small>This page is owner-only. It shows system relationships and operational summaries without exposing visitor conversation contents.</small></div><div className="omh-view-note">Selected system: <strong>{selectedNode.title}</strong>. Use search, the node list, or the 3D markers to move between systems.</div></section>;
    }
    if (activeView === 'Lab') {
      return <section className="omh-view-panel" aria-label="Visual map lab"><div className="omh-view-heading"><span>VISUAL LAB</span><strong>Try the reference controls</strong><small>These controls change only this diagram. They do not start, stop, or reconfigure any bot.</small></div><div className="omh-view-actions"><button type="button" onClick={() => setSettings((current) => ({ ...current, layout: 'Spheres', anatomy: 100, palette: 'Natural' }))}>Restore reference brain</button><button type="button" onClick={() => setSettings((current) => ({ ...current, layout: 'Cloud', anatomy: 0 }))}>Preview cloud layout</button><button type="button" onClick={() => setSettings((current) => ({ ...current, layout: 'Folder tree', anatomy: 0 }))}>Preview folder layout</button></div></section>;
    }
    if (activeView === 'Files') {
      return <section className="omh-view-panel" aria-label="Map files"><div className="omh-view-heading"><span>FILES</span><strong>Linked files</strong><small>Only files connected to this application would appear here.</small></div><div className="omh-view-empty">No application file records are linked to this map. The reference HTML is used for design guidance, not treated as an uploaded production file.</div></section>;
    }
    return <section className="omh-view-panel" aria-label="Map guide"><div className="omh-view-heading"><span>LEARN</span><strong>How to use the map</strong><small>Use search or tap a node to reveal its label and workflow details.</small></div><div className="omh-guide-grid"><article><b>Move and rotate</b><span>Drag in Move mode to reposition the map. Switch to Rotate in the map controls to turn it. The motion control pauses automatic rotation.</span></article><article><b>Zoom</b><span>Pinch on touchscreens or use the scroll wheel. Two-finger movement also pans.</span></article><article><b>Filter</b><span>Choose system groups in Settings to focus the map.</span></article><article><b>Check status</b><span>Heartbeat dots and issue rings use Development-only evidence; unknown does not mean stopped.</span></article></div></section>;
  };

  const walkthroughCopy = [
    { title: 'The full ecosystem', body: 'The brain represents Smart Money Hub systems and workflows. Its links show the map’s conceptual relationships, not live service connections.' },
    { title: 'Find a system', body: 'Search by bot, channel, member journey, or operation. Search results reveal matching labels on the brain.' },
    { title: 'Inspect health', body: 'Select a node for its details. Only verified Development heartbeats show as running; stored alerts are not proof that a fault is still active.' },
    { title: 'Tune the view', body: 'Open Settings to change themes, colors, layout, anatomy, labels, motion, and point size. These are visual-only controls.' },
  ];

  return (
    <main
      className="owner-map-page"
      data-theme={settings.theme.toLowerCase()}
      style={{
        '--omh-bg': themeColors[settings.theme].background,
        '--omh-panel-color': themeColors[settings.theme].panel,
        '--omh-line-color': themeColors[settings.theme].line,
        '--omh-glow': themeColors[settings.theme].glow,
        '--omh-mint': themeColors[settings.theme].accent,
      } as CSSProperties}
    >
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

        <nav className="omh-map-tabs" aria-label="Mind map views">
          {mapViews.map((view) => <button key={view} type="button" onClick={() => setActiveView(view)} aria-current={activeView === view ? 'page' : undefined}>{view}</button>)}
        </nav>

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

        {renderViewPanel()}

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
              <SystemMap3D
                selectedId={selectedNode.id}
                visibleIds={visibleIds}
                labelIds={labelIds}
                runtimeByNode={runtimeByNode}
                issuesByNode={issuesByNode}
                settings={settings}
                setSettings={setSettings}
                activeGroups={activeGroups}
                onToggleGroup={toggleGroup}
                onWalkthrough={() => setWalkthroughStep(0)}
                onReset={resetAllSettings}
                onSelect={selectNode}
              />
              <div className="omh-3d-caption">
                <span>SMART MONEY HUB · 3D ECOSYSTEM</span>
                <span>SEARCH OR TAP TO REVEAL · DRAG · PINCH</span>
              </div>
              <div className="omh-stage-foot"><span>ALL BOTS &amp; WORKFLOWS</span><span>DEV ALERTS + HEARTBEATS</span><span>OWNER ONLY</span></div>
            </div>

            <div className="omh-runtime-legend" aria-label="Runtime status legend">
              <span><i className="tone-good" />Recent heartbeat</span>
              <span><i className="tone-caution" />Stale heartbeat</span>
              <span><i className="tone-neutral" />Unknown / no source</span>
              <span><i className="omh-issue-legend-dot" />Recorded issue</span>
            </div>
            <div className={`omh-issue-feed-state ${issueQuery.isError ? 'is-unavailable' : ''}`} role="status" data-testid="mindmap-issue-feed-state">
              <CircleAlert size={13} />
              <span>{issueFeedText}</span>
            </div>

            <div className="omh-node-grid" aria-label="Smart Money Hub systems and workflows">
              {displayGroups.map((group, groupIndex) => {
                const groupNodes = group.nodes;
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
                        const issues = issuesByNode.get(node.id);
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
                              {issues && <span className={`omh-issue-status severity-${issues.severity}`} data-testid={`issue-status-${node.id}`}><CircleAlert size={10} />{issues.count} recorded</span>}
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
            {selectedIssues && <section className={`omh-issue-detail severity-${selectedIssues.severity}`} aria-label={`${selectedNode.title} recorded issues`} data-testid={`issue-detail-${selectedNode.id}`}>
              <div className="omh-issue-detail-heading"><CircleAlert size={14} /><strong>{selectedIssues.count} RECORDED DEVELOPMENT ISSUE{selectedIssues.count === 1 ? '' : 'S'}</strong></div>
              <ul>{selectedIssues.items.slice(0, 4).map((issue) => <li key={issue.key}>
                <span>{issue.title}</span>
                <small>{issue.count} recorded{issue.latestAt ? ` · ${formatHeartbeat(issue.latestAt)}` : ''}</small>
              </li>)}</ul>
              <small>Stored alert summary; it does not prove the issue is still active.</small>
            </section>}
            {import.meta.env.DEV && issueQuery.isError && <div className="omh-issue-feed-unavailable" role="alert"><CircleAlert size={13} />Issue feed unavailable. The map cannot confirm current health.</div>}
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
        {walkthroughStep !== null && <div className="omh-walkthrough-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setWalkthroughStep(null); }}>
          <section className="omh-walkthrough" role="dialog" aria-modal="true" aria-labelledby="omh-walkthrough-title">
            <div className="omh-walkthrough-top"><span>MAP WALKTHROUGH · {walkthroughStep + 1}/4</span><button type="button" onClick={() => setWalkthroughStep(null)} aria-label="Close walkthrough"><X size={16} /></button></div>
            <h3 id="omh-walkthrough-title">{walkthroughCopy[walkthroughStep].title}</h3>
            <p>{walkthroughCopy[walkthroughStep].body}</p>
            <div><button type="button" onClick={() => setWalkthroughStep((step) => Math.max(0, (step ?? 0) - 1))} disabled={walkthroughStep === 0}>Back</button><button type="button" onClick={() => setWalkthroughStep((step) => step !== null && step < walkthroughCopy.length - 1 ? step + 1 : null)}>{walkthroughStep === walkthroughCopy.length - 1 ? 'Finish' : 'Next'}</button></div>
          </section>
        </div>}
      </div>
    </main>
  );
}
