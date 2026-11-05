export type TradeAction =
  | "entry_bundle" | "sl_tp" | "sl" | "tp" | "hit" | "partial" | "be"
  | "trail" | "close" | "cancel" | "invalidate" | "custom" | "edit";

export type TradeActionValues = Record<string, string | boolean | undefined>;
export type TradeQuery = (sql: string, values?: unknown[]) => Promise<{ rows: Record<string, unknown>[] }>;

const openStates = new Set(["ACTIVE", "CONFIRMED_BUY", "CONFIRMED_SELL"]);
const allowedFields: Record<TradeAction, string[]> = {
  entry_bundle: ["entry", "stopLoss", "targetNumber", "targetPrice"],
  sl_tp: ["stopLoss", "targetNumber", "targetPrice"],
  sl: ["stopLoss"],
  tp: ["targetNumber", "targetPrice"],
  hit: ["targetNumber", "targetStatus"],
  partial: ["percentage", "targetPrice", "remaining"],
  be: ["stopMoved"],
  trail: ["stopLoss"],
  close: ["outcome", "outcomeConfirmed", "exitPrice", "note"],
  cancel: ["reason"],
  invalidate: ["reason"],
  custom: ["text"],
  edit: ["text"],
};

const requiredFields: Partial<Record<TradeAction, string[]>> = {
  entry_bundle: ["entry", "stopLoss", "targetNumber", "targetPrice"],
  sl_tp: ["stopLoss", "targetNumber", "targetPrice"],
  sl: ["stopLoss"],
  tp: ["targetNumber", "targetPrice"],
  hit: ["targetNumber", "targetStatus"],
  partial: ["percentage", "targetPrice"],
  trail: ["stopLoss"],
  cancel: ["reason"],
  invalidate: ["reason"],
  custom: ["text"],
  edit: ["text"],
  close: ["outcome", "outcomeConfirmed"],
};

const credentialLike = /\b(password|passcode|otp|one[- ]time code|recovery code|api key|secret key)\s*[:=]/i;

export function isTradeManagementAvailable(nodeEnvironment: string | undefined, schema: string): boolean {
  return (nodeEnvironment === "development" && schema === "smh_test")
    || (nodeEnvironment === "production" && schema === "smh");
}

function parseJson(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return {};
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function iso(value: unknown): string {
  if (value instanceof Date) return value.toISOString();
  return String(value ?? "");
}

export function publicTrade(row: Record<string, unknown>) {
  const data = parseJson(row.data);
  const targets = parseJson(data.targets);
  const targetList = Object.entries(targets)
    .sort(([left], [right]) => Number(left) - Number(right))
    .map(([number, value]) => {
      const target = value && typeof value === "object" ? value as Record<string, unknown> : {};
      return {
        number,
        price: String(target.price ?? ""),
        hit: target.hit === true,
        hitStatus: target.hit_status == null ? null : String(target.hit_status),
      };
    });
  return {
    tradeId: String(row.id),
    symbol: String(data.symbol ?? data.market ?? "Unspecified market"),
    direction: String(data.direction ?? "Unspecified"),
    state: String(row.state ?? data.state ?? "UNKNOWN"),
    entry: data.entry == null ? null : String(data.entry),
    stopLoss: data.sl == null ? null : String(data.sl),
    targets: targetList,
    version: Number(row.version ?? data.version ?? 0),
    created: iso(row.created),
    updated: iso(row.updated),
    hasLinkedPost: Boolean(data.message_id || data.setup_message_id),
    eventCount: Number(row.event_count ?? 0),
  };
}

export function workerSnapshot(value: unknown) {
  const raw = parseJson(value);
  const updated = typeof raw.updated === "string" ? Date.parse(raw.updated) : Number.NaN;
  const fresh = Number.isFinite(updated) && updated <= Date.now() + 30_000 &&
    Date.now() - updated <= 90_000;
  const status = raw.status === "migration_required" && fresh
    ? "migration_required" : raw.status === "ready" && fresh ? "ready" : "unknown";
  return {
    workerStatus: status,
    publishingEnabled: status === "ready" && raw.publishing_enabled === true,
    destinationsVerified: status === "ready" && raw.destinations_verified === true,
  };
}

export async function readPortalTrades(
  query: TradeQuery,
  schema: "smh" | "smh_test",
  nodeEnvironment: string | undefined,
) {
  if (!isTradeManagementAvailable(nodeEnvironment, schema)) {
    throw new Error("Trade management is unavailable in this environment.");
  }
  const [trades, worker] = await Promise.all([
    query(
      `SELECT t.id,t.data,t.state,t.created,t.updated,t.version,
              (SELECT COUNT(*) FROM ${schema}.events e WHERE e.trade_id=t.id) AS event_count
         FROM ${schema}.trades t
        ORDER BY t.updated DESC
        LIMIT 100`,
    ),
    query(`SELECT value FROM ${schema}.kv WHERE key=$1 LIMIT 1`, ["portal_trade_worker_status"]),
  ]);
  const status = workerSnapshot(worker.rows[0]?.value);
  return {
    environment: nodeEnvironment === "production" ? "production" as const : "development_test" as const,
    ...status,
    trades: trades.rows.map(publicTrade),
  };
}

export async function readPortalTrade(
  query: TradeQuery,
  schema: "smh" | "smh_test",
  nodeEnvironment: string | undefined,
  tradeId: string,
) {
  if (!isTradeManagementAvailable(nodeEnvironment, schema)) {
    throw new Error("Trade management is unavailable in this environment.");
  }
  const result = await query(
    `SELECT t.id,t.data,t.state,t.created,t.updated,t.version,
            (SELECT COUNT(*) FROM ${schema}.events e WHERE e.trade_id=t.id) AS event_count
       FROM ${schema}.trades t WHERE t.id=$1 LIMIT 1`,
    [tradeId],
  );
  const row = result.rows[0];
  if (!row) return null;
  const history = await query(
    `SELECT text,created FROM ${schema}.events WHERE trade_id=$1 ORDER BY id DESC LIMIT 50`,
    [tradeId],
  );
  return {
    trade: publicTrade(row),
    history: history.rows.map((event) => ({ text: String(event.text ?? ""), created: iso(event.created) })),
  };
}

export function normalizeTradeActionInput(action: TradeAction, input: TradeActionValues): Record<string, unknown> {
  const allowed = new Set(allowedFields[action]);
  if (!allowed) throw new Error("Choose a supported trade action.");
  for (const key of Object.keys(input)) {
    if (!allowed.has(key)) throw new Error("This action contains an unsupported field.");
  }
  for (const key of requiredFields[action] ?? []) {
    if (!(key in input) || input[key] === "" || input[key] === undefined || input[key] === null) {
      throw new Error(`Enter ${key.replace(/[A-Z]/g, (letter) => ` ${letter.toLowerCase()}`)}.`);
    }
  }
  const strings = Object.fromEntries(
    Object.entries(input).filter(([, value]) => typeof value === "string"),
  ) as Record<string, string>;
  for (const value of Object.values(strings)) {
    if (credentialLike.test(value)) throw new Error("Do not enter passwords, OTPs, or account credentials.");
  }
  if (action === "be" && input.stopMoved !== true) {
    throw new Error("Confirm that you actually moved the stop loss to entry.");
  }
  if (action === "close") {
    if (input.outcomeConfirmed !== true) throw new Error("Confirm the recorded outcome before continuing.");
    if (!["Win", "Breakeven", "Loss", "Unrecorded"].includes(String(input.outcome))) {
      throw new Error("Choose a valid recorded outcome.");
    }
  }
  if (action === "hit" && !["partial", "final"].includes(String(input.targetStatus))) {
    throw new Error("Choose whether the observed target was partial or final.");
  }
  if (action === "partial" && input.remaining && String(input.remaining).length > 200) {
    throw new Error("The remaining-position note is too long.");
  }

  const names: Record<string, string> = {
    stopLoss: "stop_loss",
    targetNumber: "target_number",
    targetPrice: "target_price",
    targetStatus: "target_status",
    outcomeConfirmed: "outcome_confirmed",
    exitPrice: "exit_price",
    stopMoved: "stop_moved",
  };
  const normalized = Object.fromEntries(Object.entries(input).map(([key, value]) => [names[key] ?? key, value]));
  if (action === "partial") normalized.mode = "reported";
  return normalized;
}

export function publicTradeAction(row: Record<string, unknown>) {
  const status = String(row.command_status);
  return {
    commandId: String(row.id),
    tradeId: String(row.trade_id),
    action: String(row.action),
    status,
    previewText: String(row.preview_text ?? ""),
    safeResult: String(row.safe_result ?? ""),
    created: iso(row.created),
    updated: iso(row.updated),
    canConfirm: status === "preview_ready",
    canCancel: ["queued", "preview_ready"].includes(status),
  };
}

