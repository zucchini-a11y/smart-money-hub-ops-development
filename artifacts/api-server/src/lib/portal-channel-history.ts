export type ChannelHistoryDestination = "all" | "signals" | "analysis" | "education";
export type ChannelHistoryBot = "main" | "test";

type QueryResult = { rows: Record<string, unknown>[] };
type ReadQuery = (sql: string, values: unknown[]) => Promise<QueryResult>;

const HISTORY_SQL = (schema: "smh" | "smh_test") => `
  SELECT source, destination, event_type, status, recorded_at, message_text, attachment_label
    FROM (
      SELECT
        'bot'::text AS source,
        CASE WHEN payload::jsonb->>'destination'='analysis'
             THEN 'Market Analysis' ELSE 'PRO Signals' END AS destination,
        kind::text AS event_type,
        status::text AS status,
        COALESCE(updated, created)::timestamptz AS recorded_at,
        COALESCE(payload::jsonb->>'text', '') AS message_text,
        CASE WHEN COALESCE(payload::jsonb->>'image', '') <> ''
             THEN 'Chart image attached' ELSE 'No attachment' END AS attachment_label
      FROM ${schema}.operations
      WHERE kind IN ('setup','signal','update','analysis','edit')
        AND message_id IS NOT NULL
        AND (
          (kind='analysis' AND payload::jsonb->>'destination'='analysis')
          OR
          (kind<>'analysis' AND payload::jsonb->>'destination'='signals')
        )
        AND status<>'abandoned'
        AND NOT EXISTS (
          SELECT 1
            FROM ${schema}.channel_history captured
           WHERE captured.message_id=operations.message_id
             AND captured.chat_id=(payload::jsonb->>'channel')::bigint
             AND captured.destination=CASE WHEN payload::jsonb->>'destination'='analysis'
                                           THEN 'Market Analysis' ELSE 'PRO Signals' END
        )
      UNION ALL
      SELECT
        'telegram_manual'::text AS source,
        destination,
        event_type,
        'received'::text AS status,
        recorded_at::timestamptz AS recorded_at,
        message_text,
        attachment_label
      FROM ${schema}.channel_history
      WHERE NOT EXISTS (
        SELECT 1
          FROM ${schema}.operations operation
         WHERE operation.message_id=channel_history.message_id
           AND operation.payload::jsonb->>'channel'=channel_history.chat_id::text
           AND operation.status<>'abandoned'
           AND (
             (operation.kind='analysis' AND channel_history.destination='Market Analysis'
              AND operation.payload::jsonb->>'destination'='analysis')
             OR
             (operation.kind<>'analysis' AND channel_history.destination='PRO Signals'
              AND operation.payload::jsonb->>'destination'='signals')
           )
      )
      UNION ALL
      SELECT
        'bot'::text AS source,
        'Educational Group · Video tutorials'::text AS destination,
        'education_video'::text AS event_type,
        status::text AS status,
        COALESCE(published_at, updated, created)::timestamptz AS recorded_at,
        concat_ws(E'\\n\\n', NULLIF(title, ''), NULLIF(caption, '')) AS message_text,
        'Video attached'::text AS attachment_label
      FROM ${schema}.education_video_posts
      WHERE status IN ('queued','sending','published','uncertain','failed','blocked')
        AND target_chat_id IS NOT NULL AND target_thread_id IS NOT NULL
    ) AS history
   WHERE ($1='all'
       OR ($1='signals' AND destination='PRO Signals')
       OR ($1='analysis' AND destination='Market Analysis')
       OR ($1='education' AND destination='Educational Group · Video tutorials'))
   ORDER BY recorded_at DESC
   LIMIT $2 OFFSET $3
`;

function publicText(value: unknown): string {
  return String(value ?? "")
    .replace(/<\s*br\s*\/?\s*>/gi, "\n")
    .replace(/<\/\s*(p|div|li|h[1-6])\s*>/gi, "\n")
    .replace(/<[^>]{0,500}>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

function publicDate(value: unknown): string {
  const date = new Date(String(value ?? ""));
  return Number.isNaN(date.getTime()) ? String(value ?? "") : date.toISOString();
}

export async function readDevelopmentChannelHistory(
  query: ReadQuery,
  {
    page,
    limit,
    destination,
    bot,
  }: {
    page: number;
    limit: number;
    destination: ChannelHistoryDestination;
    bot: ChannelHistoryBot;
  },
) {
  const schema = bot === "main" ? "smh" : "smh_test";
  const result = await query(HISTORY_SQL(schema), [destination, limit + 1, page * limit]);
  const hasMore = result.rows.length > limit;
  return {
    scope: bot === "main" ? "development_main_bot" as const : "development_isolated_test" as const,
    productionConnected: false as const,
    page,
    limit,
    hasMore,
    items: result.rows.slice(0, limit).map((row) => ({
      source: row.source === "telegram_manual" ? "telegram_manual" as const : "bot" as const,
      destination: String(row.destination) as
        | "PRO Signals"
        | "Market Analysis"
        | "Educational Group · Video tutorials",
      eventType: String(row.event_type ?? "unknown"),
      status: String(row.status ?? "unknown"),
      recordedAt: publicDate(row.recorded_at),
      messageText: publicText(row.message_text),
      attachmentLabel: String(row.attachment_label ?? "No attachment"),
    })),
  };
}
