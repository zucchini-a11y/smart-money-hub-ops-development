type QueryResult = { rows: Record<string, unknown>[] };
type ReadQuery = (sql: string, values?: unknown[]) => Promise<QueryResult>;

export async function readDevelopmentCommandCenter(
  query: ReadQuery,
  refreshedAt = new Date().toISOString(),
) {
  // This schema is fixed and is queried only after the route verifies Development + smh_test.
  const schema = "smh_test";
  const [
    overviewResult,
    lastUpdateResult,
    healthResult,
    operationResult,
    publishingAlertResult,
    errorResult,
  ] = await Promise.all([
    query(
      `SELECT
         (SELECT count(*)::int FROM ${schema}.assistant_escalations
           WHERE status IN ('open','reply_sending')) AS open_support_cases,
         (SELECT count(*)::int FROM ${schema}.assistant_escalations
           WHERE status='reply_uncertain') AS uncertain_support_cases,
         (SELECT count(*)::int FROM ${schema}.staff_tasks
           WHERE due_at IS NOT NULL AND due_at::timestamptz < $1::timestamptz
             AND status NOT IN ('approved','cancelled')) AS overdue_tasks,
         (SELECT count(*)::int FROM ${schema}.trades) AS recorded_trades,
         (SELECT count(*)::int FROM ${schema}.events) AS recorded_trade_events,
         (SELECT count(*)::int FROM ${schema}.operations
            WHERE status IN ('uncertain','failed','sending','retryable')) AS unresolved_operations,
          (SELECT count(*)::int FROM ${schema}.member_requests
            WHERE destination='pro'
              AND status IN ('pending_review','legacy_review')
              AND registration_status='verified' AND funding_status='verified') AS pro_pending_review,
          (SELECT count(*)::int FROM ${schema}.member_requests
            WHERE destination='pro' AND funding_status='evidence_requested') AS pro_evidence_requested,
          (SELECT count(*)::int FROM ${schema}.member_requests
            WHERE destination='pro' AND status IN ('pending_review','legacy_review')
              AND updated::timestamptz < $1::timestamptz - interval '7 days') AS stale_pro_applications`,
      [refreshedAt],
    ),
    query(`SELECT value FROM ${schema}.kv WHERE key='last_update' LIMIT 1`),
    query(`SELECT value FROM ${schema}.kv WHERE key='command_center_health' LIMIT 1`),
    query(
      `SELECT kind,status,created,updated
         FROM ${schema}.operations
        WHERE kind IN ('signal','setup','update','analysis','edit')
        ORDER BY updated DESC
        LIMIT 12`,
    ),
    query(
      `SELECT kind,status,count(*)::int AS count,max(updated) AS latest_at
         FROM ${schema}.operations
        WHERE kind IN ('signal','setup','update','analysis','edit')
          AND status IN ('failed','uncertain','sending','retryable')
        GROUP BY kind,status
        ORDER BY max(updated) DESC
        LIMIT 24`,
    ),
    query(
      `SELECT category,count(*)::int AS count,max(created) AS latest_at
         FROM ${schema}.errors
        GROUP BY category
        ORDER BY max(created) DESC
        LIMIT 8`,
    ),
  ]);

  const latestActivity = new Map<string, string>();
  const recentOperations = operationResult.rows.flatMap((row) => {
    const destination = row.kind === "analysis" ? "Market Analysis" : "PRO Signals";
    const parsedRecordedAt = Date.parse(String(row.updated ?? row.created ?? ""));
    if (!Number.isFinite(parsedRecordedAt)) return [];
    const recordedAt = new Date(parsedRecordedAt).toISOString();
    const current = latestActivity.get(destination);
    if (!current || recordedAt > current) latestActivity.set(destination, recordedAt);
    return [{
      sourceBot: "isolated_test" as const,
      destination,
      operationType: String(row.kind),
      status: String(row.status),
      recordedAt,
      telegramAccepted: row.status === "done",
    }];
  });
  const overview = overviewResult.rows[0] ?? {};
  const staleProApplications = Number(overview.stale_pro_applications ?? 0);
  let rawLastTelegramUpdate = lastUpdateResult.rows[0]?.value == null
    ? null
    : String(lastUpdateResult.rows[0].value);
  if (rawLastTelegramUpdate !== null) {
    try {
      const decoded = JSON.parse(rawLastTelegramUpdate) as unknown;
      rawLastTelegramUpdate = typeof decoded === "string" ? decoded : null;
    } catch {
      // Accept a plain stored timestamp as well as the JSON-encoded value used by the bot.
    }
  }
  const parsedLastTelegramUpdate = rawLastTelegramUpdate
    ? Date.parse(rawLastTelegramUpdate)
    : Number.NaN;
  const lastTelegramUpdate = Number.isFinite(parsedLastTelegramUpdate)
    ? new Date(parsedLastTelegramUpdate).toISOString()
    : null;
  const unknownHealth = "unknown" as const;
  let healthSnapshot: Record<string, unknown> | null = null;
  const rawHealth = healthResult.rows[0]?.value;
  if (rawHealth != null) {
    try {
      const parsed = typeof rawHealth === "string" ? JSON.parse(rawHealth) : rawHealth;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        healthSnapshot = parsed as Record<string, unknown>;
      }
    } catch {
      // Invalid or legacy values remain unknown; no raw database content is returned.
    }
  }
  const healthCheckedAtRaw = typeof healthSnapshot?.checked_at === "string"
    ? healthSnapshot.checked_at
    : null;
  const healthCheckedAtMs = healthCheckedAtRaw ? Date.parse(healthCheckedAtRaw) : Number.NaN;
  const snapshotTimeMs = Date.parse(refreshedAt);
  const heartbeatAgeMs = snapshotTimeMs - healthCheckedAtMs;
  const heartbeatFresh = Number.isFinite(heartbeatAgeMs) &&
    heartbeatAgeMs >= -30_000 && heartbeatAgeMs <= 150_000;
  const healthCheckedAt = heartbeatFresh
    ? new Date(healthCheckedAtMs).toISOString()
    : null;
  const isolatedHealthStatus = heartbeatFresh
    ? healthSnapshot?.status === "healthy" ? "healthy"
      : healthSnapshot?.status === "degraded" || healthSnapshot?.status === "unavailable"
        ? "unhealthy" : unknownHealth
    : unknownHealth;
  const telegramStatus = heartbeatFresh
    ? healthSnapshot?.telegram === "reachable" ? "healthy"
      : healthSnapshot?.telegram === "unreachable" ? "offline" : unknownHealth
    : unknownHealth;
  const databaseStatus = heartbeatFresh
    ? healthSnapshot?.database === "ok" ? "healthy"
      : healthSnapshot?.database === "unavailable" ? "offline" : unknownHealth
    : unknownHealth;
  const secondsSincePoll = typeof healthSnapshot?.seconds_since_poll === "number" &&
    Number.isFinite(healthSnapshot.seconds_since_poll)
    ? healthSnapshot.seconds_since_poll
    : null;
  const pollingStatus = !heartbeatFresh || secondsSincePoll === null
    ? unknownHealth
    : secondsSincePoll <= 120 ? "healthy"
      : secondsSincePoll <= 240 ? "degraded" : "offline";
  const testPublishingStatus = heartbeatFresh && typeof healthSnapshot?.publishing_requested === "boolean"
    ? healthSnapshot.publishing_requested ? "enabled" : "disabled"
    : unknownHealth;
  const alerts = new Map<string, {
    category: string;
    severity: "warning" | "critical";
    sourceBot: "isolated_test";
    destination: "PRO Signals" | "Market Analysis" | "System";
    title: string;
    count: number;
    latestAt: string | null;
  }>();
  const addAlert = (alert: {
    category: string;
    severity: "warning" | "critical";
    sourceBot: "isolated_test";
    destination: "PRO Signals" | "Market Analysis" | "System";
    title: string;
    count: number;
    latestAt: string | null;
  }) => {
    const key = `${alert.category}:${alert.destination}`;
    const existing = alerts.get(key);
    if (!existing) {
      alerts.set(key, alert);
      return;
    }
    existing.count += alert.count;
    if (alert.latestAt && (!existing.latestAt || alert.latestAt > existing.latestAt)) {
      existing.latestAt = alert.latestAt;
    }
  };

  if (!heartbeatFresh) {
    const hasStoredHeartbeat = rawHealth != null;
    addAlert({
      category: hasStoredHeartbeat ? "stale_heartbeat" : "missing_heartbeat",
      severity: "warning",
      sourceBot: "isolated_test",
      destination: "System",
      title: hasStoredHeartbeat
        ? "Private test bot heartbeat is stale"
        : "No private test bot heartbeat has been recorded",
      count: 1,
      latestAt: healthCheckedAtRaw && Number.isFinite(healthCheckedAtMs)
        ? new Date(healthCheckedAtMs).toISOString()
        : null,
    });
  } else if (isolatedHealthStatus === "unhealthy") {
    addAlert({
      category: "bot_health_failure",
      severity: healthSnapshot?.status === "unavailable" ? "critical" : "warning",
      sourceBot: "isolated_test",
      destination: "System",
      title: healthSnapshot?.status === "unavailable"
        ? "Private test bot reported an unavailable service"
        : "Private test bot reported degraded health",
      count: 1,
      latestAt: healthCheckedAt,
    });
  }

  const publishingStatusCopy: Record<string, { category: string; title: string; severity: "warning" | "critical" }> = {
    failed: { category: "publishing_failure", title: "A private test publishing operation failed", severity: "critical" },
    uncertain: { category: "publishing_uncertain", title: "A private test publishing outcome needs review", severity: "warning" },
    sending: { category: "publishing_pending", title: "A private test publishing operation is still marked sending", severity: "warning" },
    retryable: { category: "publishing_pending", title: "A private test publishing operation is marked retryable", severity: "warning" },
  };
  for (const row of publishingAlertResult.rows) {
    const status = String(row.status);
    const kind = String(row.kind);
    const definition = publishingStatusCopy[status];
    if (!definition || !["signal", "setup", "update", "analysis", "edit"].includes(kind)) continue;
    const destination = kind === "analysis" ? "Market Analysis" : "PRO Signals";
    const parsedLatest = Date.parse(String(row.latest_at ?? ""));
    addAlert({
      ...definition,
      sourceBot: "isolated_test",
      destination,
      count: Math.max(1, Number(row.count) || 1),
      latestAt: Number.isFinite(parsedLatest) ? new Date(parsedLatest).toISOString() : null,
    });
  }
  if (staleProApplications > 0) {
    addAlert({
      category: "pro_stale_applications",
      severity: "warning",
      sourceBot: "isolated_test",
      destination: "System",
      title: "PRO applications have waited more than seven days",
      count: staleProApplications,
      latestAt: null,
    });
  }

  return {
    scope: "development_isolated_test" as const,
    readOnly: true as const,
    refreshedAt,
    lastTelegramUpdate,
    alerts: [...alerts.values()].sort((a, b) =>
      (b.latestAt ?? "").localeCompare(a.latestAt ?? "")),
    overview: {
      openSupportCases: Number(overview.open_support_cases ?? 0),
      uncertainSupportCases: Number(overview.uncertain_support_cases ?? 0),
      overdueTasks: Number(overview.overdue_tasks ?? 0),
      recordedTrades: Number(overview.recorded_trades ?? 0),
      recordedTradeEvents: Number(overview.recorded_trade_events ?? 0),
      unresolvedPublishingOperations: Number(overview.unresolved_operations ?? 0),
      proPendingReview: Number(overview.pro_pending_review ?? 0),
      proEvidenceRequested: Number(overview.pro_evidence_requested ?? 0),
      staleProApplications,
    },
    bots: [
      {
        id: "production" as const,
        label: "Production bot",
        healthStatus: unknownHealth,
        workflowStatus: "not_connected" as const,
        publishingStatus: "unknown" as const,
        lastTelegramUpdate: null,
        processStatus: "not_connected" as const,
        healthCheckedAt: null,
        telegramStatus: unknownHealth,
        databaseStatus: unknownHealth,
        pollingStatus: unknownHealth,
        note: "Production data is deliberately not connected to this Development dashboard.",
      },
      {
        id: "isolated_test" as const,
        label: "Private test bot",
        healthStatus: isolatedHealthStatus,
        workflowStatus: "unknown" as const,
        publishingStatus: testPublishingStatus,
        lastTelegramUpdate,
        processStatus: heartbeatFresh ? "running" as const : unknownHealth,
        healthCheckedAt,
        telegramStatus,
        databaseStatus,
        pollingStatus,
        note: heartbeatFresh
          ? "Status comes from the isolated test bot heartbeat. Replit workflow-control status and channel access are not connected."
          : "No recent isolated test bot heartbeat is available. Replit workflow-control status and channel access are not connected.",
      },
    ],
    channels: [
      ...["PRO Signals", "Market Analysis", "Educational Group"].map((name) => ({
        sourceBot: "isolated_test" as const,
        name,
        status: unknownHealth,
        latestRecordedActivity: latestActivity.get(name) ?? null,
        note: name === "Educational Group"
          ? "The stored invite records do not provide a safe, reliable channel activity mapping."
          : "Recorded activity does not confirm current Telegram reachability or show all channel messages.",
      })),
      ...["PRO Signals", "Market Analysis", "Educational Group"].map((name) => ({
        sourceBot: "production" as const,
        name,
        status: "not_connected" as const,
        latestRecordedActivity: null,
        note: "Production channel data is deliberately not connected to this Development dashboard.",
      })),
    ],
    recentOperations,
    recentErrors: errorResult.rows.map((row) => ({
      category: String(row.category),
      count: Number(row.count),
      latestAt: String(row.latest_at),
    })),
  };
}
