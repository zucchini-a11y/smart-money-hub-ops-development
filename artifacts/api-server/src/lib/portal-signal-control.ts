export type SignalAction =
  | "create_zone_draft"
  | "publish_zone"
  | "record_confirmation"
  | "cancel_setup"
  | "expire_setup"
  | "publish_signal"
  | "publish_analysis";

export type SignalQuery = (
  sql: string,
  values?: unknown[],
) => Promise<{ rows: Record<string, unknown>[] }>;

const credentialLike = /\b(password|passcode|otp|one[- ]time code|recovery code|api key|secret key)\s*[:=]/i;
const decimal = /^(?:0|[1-9]\d{0,11})(?:\.\d{1,8})?$/;

export function isPortalSignalControlAvailable(
  nodeEnvironment: string | undefined,
  schema: string,
): boolean {
  // This feature is intentionally isolated to the Development test bot.
  return nodeEnvironment === "development" && schema === "smh_test";
}

function clean(value: unknown, label: string, limit: number, optional = false): string {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text && optional) return "";
  if (!text || text.length > limit || /[\u0000-\u001f\u007f]/.test(text)) {
    throw new Error(`Enter a valid ${label}.`);
  }
  if (credentialLike.test(text)) {
    throw new Error("Do not enter passwords, OTPs, recovery codes, or account credentials.");
  }
  return text;
}

function compareDecimals(left: string, right: string): number {
  const [leftWhole, leftFraction = ""] = left.split(".");
  const [rightWhole, rightFraction = ""] = right.split(".");
  const scale = Math.max(leftFraction.length, rightFraction.length);
  const a = BigInt(leftWhole + leftFraction.padEnd(scale, "0"));
  const b = BigInt(rightWhole + rightFraction.padEnd(scale, "0"));
  return a < b ? -1 : a > b ? 1 : 0;
}

export function normalizePortalSignalInput(
  action: SignalAction,
  input: Record<string, unknown>,
): Record<string, unknown> {
  const allowed: Record<SignalAction, string[]> = {
    create_zone_draft: ["market", "low", "high", "timeframe", "condition", "minutes"],
    publish_zone: ["draftRevision"],
    record_confirmation: ["setupId", "confirmation"],
    cancel_setup: ["setupId"],
    expire_setup: ["setupId"],
    publish_signal: ["setupId", "direction", "entryRange", "stopLoss", "takeProfits"],
    publish_analysis: ["text"],
  };
  const keys = new Set(allowed[action] ?? []);
  if (!keys.size || Object.keys(input).some((key) => !keys.has(key))) {
    throw new Error("This signal action contains unsupported fields.");
  }

  if (action === "create_zone_draft") {
    const market = clean(input.market, "market", 80);
    if (market.includes("|")) throw new Error("Remove the | character from the market name.");
    const low = clean(input.low, "lower zone price", 24);
    const high = clean(input.high, "upper zone price", 24);
    if (!decimal.test(low) || !decimal.test(high)) {
      throw new Error("Enter prices using digits and an optional decimal point.");
    }
    if (compareDecimals(low, high) >= 0) {
      throw new Error("The upper zone price must be greater than the lower price.");
    }
    const timeframe = clean(input.timeframe, "timeframe", 30, true);
    if (timeframe.includes("|")) throw new Error("Remove the | character from the timeframe.");
    const condition = clean(input.condition, "confirmation", 300, true);
    if (condition.includes("|")) throw new Error("Remove the | character from the confirmation.");
    if (input.minutes !== undefined) {
      const legacyMinutes = Number(input.minutes);
      if (!Number.isInteger(legacyMinutes) || legacyMinutes < 1 || legacyMinutes > 1440) {
        throw new Error("Choose a validity period from 1 to 1440 minutes.");
      }
    }
    return { market, low, high, timeframe, condition };
  }

  if (action === "publish_zone") {
    const draftRevision = clean(input.draftRevision, "zone draft", 120, true);
    return draftRevision ? { draft_revision: draftRevision } : {};
  }

  if (action === "record_confirmation") {
    return {
      setup_id: clean(input.setupId, "active setup", 120),
      confirmation: clean(input.confirmation, "observed confirmation", 300),
    };
  }

  if (action === "cancel_setup") {
    return { setup_id: clean(input.setupId, "active setup", 120) };
  }

  if (action === "expire_setup") {
    return { setup_id: clean(input.setupId, "active setup", 120) };
  }

  if (action === "publish_signal") {
    const direction = clean(input.direction, "signal direction", 4).toUpperCase();
    if (!["BUY", "SELL"].includes(direction)) throw new Error("Choose BUY or SELL.");
    return {
      setup_id: clean(input.setupId, "active setup", 120),
      direction,
      entry_range: clean(input.entryRange, "entry range", 60),
      stop_loss: clean(input.stopLoss, "Stop Loss", 24),
      take_profits: clean(input.takeProfits, "Take Profit", 300),
    };
  }

  return { text: clean(input.text, "analysis draft", 3000) };
}

function parseObject(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value !== "string") return {};
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function asIso(value: unknown): string {
  if (value instanceof Date) return value.toISOString();
  return String(value ?? "");
}

export function signalWorkerSnapshot(value: unknown) {
  const raw = parseObject(value);
  const parsedUpdated = typeof raw.updated === "string" ? Date.parse(raw.updated) : Number.NaN;
  const fresh = Number.isFinite(parsedUpdated)
    && parsedUpdated <= Date.now() + 30_000
    && Date.now() - parsedUpdated <= 90_000;
  const status = fresh && raw.version === "signal-controls-v1"
    && ["ready", "migration_required", "disabled"].includes(String(raw.status))
    ? String(raw.status) : "unknown";
  return {
    workerStatus: status,
    publishingEnabled: status === "ready" && raw.publishing_enabled === true,
    destinationsVerified: status === "ready" && raw.destinations_verified === true,
  };
}

export function publicSignalCommand(row: Record<string, unknown>) {
  const status = String(row.command_status ?? "unknown");
  return {
    commandId: String(row.id ?? ""),
    action: String(row.action ?? ""),
    status,
    previewText: String(row.preview_text ?? ""),
    safeResult: String(row.safe_result ?? ""),
    created: asIso(row.created),
    updated: asIso(row.updated),
    canConfirm: status === "preview_ready",
    canCancel: ["queued", "preview_ready"].includes(status),
  };
}

export async function readPortalSignalPanel(
  query: SignalQuery,
  schema: "smh" | "smh_test",
  nodeEnvironment: string | undefined,
) {
  if (!isPortalSignalControlAvailable(nodeEnvironment, schema)) {
    throw new Error("Signal controls are available only with isolated Development test data.");
  }
  const [panelRows, workerRows, commandRows] = await Promise.all([
    query(`SELECT value FROM ${schema}.kv WHERE key=$1 LIMIT 1`, ["portal_signal_panel"]),
    query(`SELECT value FROM ${schema}.kv WHERE key=$1 LIMIT 1`, ["portal_signal_worker_status"]),
    query(
      `SELECT id,action,command_status,preview_text,safe_result,created,updated
         FROM ${schema}.portal_signal_commands ORDER BY created DESC LIMIT 20`,
    ),
  ]);
  const worker = signalWorkerSnapshot(workerRows.rows[0]?.value);
  const panel = parseObject(panelRows.rows[0]?.value);
  const activeSetup = parseObject(panel.active_setup);
  const zoneDraft = parseObject(panel.zone_draft);
  const updated = typeof panel.updated === "string" ? panel.updated : "";
  return {
    environment: "development_test" as const,
    ...worker,
    panelUpdated: updated,
    activeSetup: Object.keys(activeSetup).length ? {
      setupId: String(activeSetup.setup_id ?? ""),
      market: String(activeSetup.market ?? ""),
      zone: String(activeSetup.zone ?? ""),
      timeframe: String(activeSetup.timeframe ?? ""),
      condition: String(activeSetup.condition ?? ""),
      status: String(activeSetup.status ?? "Unknown"),
      expires: activeSetup.expires == null ? null : Number(activeSetup.expires),
      hasChart: activeSetup.has_chart === true,
      hasMessage: activeSetup.has_message === true,
    } : null,
    zoneDraft: Object.keys(zoneDraft).length ? {
      revision: String(zoneDraft.revision ?? ""),
      market: String(zoneDraft.market ?? ""),
      zone: String(zoneDraft.zone ?? ""),
      timeframe: String(zoneDraft.timeframe ?? ""),
      condition: String(zoneDraft.condition ?? ""),
      step: String(zoneDraft.step ?? ""),
      hasChart: zoneDraft.has_chart === true,
      readyToPublish: zoneDraft.ready_to_publish === true,
    } : null,
    commands: commandRows.rows.map(publicSignalCommand),
  };
}
