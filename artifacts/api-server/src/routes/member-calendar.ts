import { createHash } from "node:crypto";
import type { PortalSupportSchema } from "../lib/portal-support-schema";

type DatabasePool = typeof import("@workspace/db").pool;
const HORIZON_DAYS = 120;
const STALE_AFTER_MS = 24 * 60 * 60 * 1000;
const MAX_BODY_BYTES = 4_000_000;
const WAT = "Africa/Lagos";

type CalendarEvent = {
  id: string;
  sourceKey: string;
  sourceName: string;
  title: string;
  eventDate: string;
  eventAt: string | null;
  timeLabel: string;
  timezoneStatus: string;
  sourceUrl: string;
  verificationStatus: string;
};

type SourceConfig = {
  id: string;
  sourceName: string;
  url: string;
  kind: "bea" | "bls" | "census" | "fed";
};

const SOURCES: SourceConfig[] = [
  {
    id: "bea_release_dates",
    sourceName: "U.S. Bureau of Economic Analysis",
    url: "https://apps.bea.gov/API/signup/release_dates.json",
    kind: "bea",
  },
  {
    id: "bls_ics",
    sourceName: "U.S. Bureau of Labor Statistics",
    url: "https://www.bls.gov/schedule/news_release/bls.ics",
    kind: "bls",
  },
  {
    id: "census_calendar",
    sourceName: "U.S. Census Bureau",
    url: "https://www.census.gov/economic-indicators/calendar-listview.html",
    kind: "census",
  },
  {
    id: "fomc_calendar",
    sourceName: "Federal Reserve",
    url: "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    kind: "fed",
  },
];

const DOL_SOURCE = {
  id: "dol_claims",
  sourceName: "U.S. Department of Labor",
};

let refreshInFlight: Promise<void> | null = null;

function dayString(value: Date, timeZone = WAT): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function formatWatTime(value: Date): string {
  return `${new Intl.DateTimeFormat("en-NG", {
    timeZone: WAT,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(value)} WAT`;
}

function cleanIcsText(value: string): string {
  return value.replace(/\\n/gi, " ").replace(/\\([,;\\])/g, "$1").trim();
}

function decodeHtml(value: string): string {
  return value
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&#(\d+);/g, (_match, decimal: string) => String.fromCodePoint(Number(decimal)))
    .replace(/&#x([0-9a-f]+);/gi, (_match, hex: string) => String.fromCodePoint(parseInt(hex, 16)));
}

function htmlText(value: string): string {
  return decodeHtml(value.replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();
}

export function impactFor(title: string): "high" | "medium" | "low" {
  const normalized = title.toLowerCase();
  if (/\b(fomc|consumer price index|employment situation|nonfarm payroll|gross domestic product|personal income and outlays)\b/.test(normalized)) {
    return "high";
  }
  if (/\b(producer price index|job openings|retail|international trade|claims|productivity|construction spending)\b/.test(normalized)) {
    return "medium";
  }
  return "low";
}

function eventId(sourceKey: string, title: string, identity: string): string {
  return createHash("sha256")
    .update(`${sourceKey}\n${title}\n${identity}`)
    .digest("hex");
}

function parseDate(value: string): string | null {
  const match = value.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (match) return `${match[1]}-${match[2]}-${match[3]}`;
  const monthDateYear = value.match(/^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$/);
  if (!monthDateYear) return null;
  const date = new Date(`${monthDateYear[1]} ${monthDateYear[2]}, ${monthDateYear[3]} 00:00:00 UTC`);
  return Number.isNaN(date.getTime()) ? null : dayString(date, "UTC");
}

function zonedLocalTimeToUtc(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
  second: number,
  timeZone: string,
): Date | null {
  let guess = Date.UTC(year, month - 1, day, hour, minute, second);
  try {
    const formatter = new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    const target = Date.UTC(year, month - 1, day, hour, minute, second);
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const parts = formatter.formatToParts(new Date(guess));
      const get = (type: string) => Number(parts.find((part) => part.type === type)?.value);
      const displayed = Date.UTC(
        get("year"),
        get("month") - 1,
        get("day"),
        get("hour"),
        get("minute"),
        get("second"),
      );
      const offset = target - displayed;
      if (offset === 0) break;
      guess += offset;
    }
    return new Date(guess);
  } catch {
    return null;
  }
}

function parseIcsDateTime(line: string): {
  sourceDate: string;
  eventAt: Date | null;
  timezoneStatus: string;
} | null {
  const match = line.match(/^DTSTART((?:;[^:]*)?):(.+)$/);
  if (!match) return null;
  const parameters = match[1] ?? "";
  const raw = match[2].trim();
  const dateMatch = raw.match(/^(\d{4})(\d{2})(\d{2})/);
  if (!dateMatch) return null;
  const sourceDate = `${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}`;
  if (/^\d{8}$/.test(raw)) {
    return { sourceDate, eventAt: null, timezoneStatus: "date_only_no_time" };
  }
  const timeMatch = raw.match(/^\d{8}T(\d{2})(\d{2})(\d{2})(Z?)$/);
  if (!timeMatch) return { sourceDate, eventAt: null, timezoneStatus: "unverified_invalid_source_time" };
  if (timeMatch[4] === "Z") {
    const eventAt = new Date(Date.UTC(
      Number(dateMatch[1]), Number(dateMatch[2]) - 1, Number(dateMatch[3]),
      Number(timeMatch[1]), Number(timeMatch[2]), Number(timeMatch[3]),
    ));
    return { sourceDate, eventAt, timezoneStatus: "verified_source_timezone:UTC" };
  }
  const zone = parameters.match(/(?:^|;)TZID=(?:"([^"]+)"|([^;:]+))/)?.slice(1).find(Boolean);
  if (!zone) {
    return { sourceDate, eventAt: null, timezoneStatus: "unverified_missing_source_timezone" };
  }
  const eventAt = zonedLocalTimeToUtc(
    Number(dateMatch[1]), Number(dateMatch[2]), Number(dateMatch[3]),
    Number(timeMatch[1]), Number(timeMatch[2]), Number(timeMatch[3]), zone,
  );
  return {
    sourceDate,
    eventAt,
    timezoneStatus: eventAt ? `verified_source_timezone:${zone}` : "unverified_unknown_source_timezone",
  };
}

function inHorizon(value: string, now: Date): boolean {
  const eventDate = new Date(`${value}T00:00:00Z`);
  const start = new Date(`${dayString(now, "UTC")}T00:00:00Z`);
  const end = new Date(start);
  end.setUTCDate(end.getUTCDate() + HORIZON_DAYS);
  return eventDate >= start && eventDate <= end;
}

function makeEvent(
  source: SourceConfig,
  title: string,
  identity: string,
  eventDate: string,
  eventAt: Date | null,
  timezoneStatus: string,
  sourceUrl = source.url,
  verificationStatus = "verified_schedule",
  listedTime?: string | null,
): CalendarEvent {
  let timeLabel = "Exact release time unavailable";
  if (eventAt) timeLabel = formatWatTime(eventAt);
  else if (listedTime?.trim()) timeLabel = `${listedTime.trim()} (source timezone unverified)`;
  return {
    id: eventId(source.id, title, identity),
    sourceKey: source.id,
    sourceName: source.sourceName,
    title,
    eventDate: eventAt ? dayString(eventAt) : eventDate,
    eventAt: eventAt?.toISOString() ?? null,
    timeLabel,
    timezoneStatus,
    sourceUrl,
    verificationStatus,
  };
}

export function parseBea(body: string, source: SourceConfig, now: Date): CalendarEvent[] {
  const payload = JSON.parse(body) as Record<string, { release_dates?: unknown }>;
  const allowed = ["Gross Domestic Product", "Personal Income and Outlays"];
  const events: CalendarEvent[] = [];
  for (const title of allowed) {
    const dates = payload[title]?.release_dates;
    if (!Array.isArray(dates)) continue;
    for (const value of dates) {
      if (typeof value !== "string") continue;
      if (!/T.*(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)) continue;
      const eventAt = new Date(value);
      if (Number.isNaN(eventAt.getTime())) continue;
      const eventDate = dayString(eventAt);
      if (!inHorizon(eventDate, now)) continue;
      events.push(makeEvent(
        source, title, eventDate, eventDate, eventAt,
        "verified_explicit_utc_offset",
        "https://www.bea.gov/news/schedule",
      ));
    }
  }
  return events;
}

export function parseBls(body: string, source: SourceConfig, now: Date): CalendarEvent[] {
  const unfolded = body.replace(/\r?\n[ \t]/g, "");
  const allowed: Array<[RegExp, string]> = [
    [/consumer price index/i, "Consumer Price Index (CPI)"],
    [/producer price index/i, "Producer Price Index (PPI)"],
    [/employment situation|nonfarm payroll/i, "Employment Situation"],
    [/job openings and labor turnover survey/i, "Job Openings and Labor Turnover Survey"],
    [/productivity and costs/i, "Productivity and Costs"],
  ];
  const events: CalendarEvent[] = [];
  for (const block of unfolded.matchAll(/BEGIN:VEVENT([\s\S]*?)END:VEVENT/g)) {
    const summary = cleanIcsText(block[1].match(/^SUMMARY(?:;[^:]*)?:(.*)$/m)?.[1] ?? "");
    const title = allowed.find(([pattern]) => pattern.test(summary))?.[1];
    const startLine = block[1].match(/^DTSTART(?:;[^:]*)?:.*$/m)?.[0];
    if (!title || !startLine) continue;
    const timing = parseIcsDateTime(startLine);
    if (!timing || !inHorizon(timing.sourceDate, now)) continue;
    events.push(makeEvent(
      source,
      title,
      timing.sourceDate,
      timing.sourceDate,
      timing.eventAt,
      timing.timezoneStatus,
    ));
  }
  return events;
}

export function parseCensus(body: string, source: SourceConfig, now: Date): CalendarEvent[] {
  const table = body.match(/<table\b[^>]*\bid=["']calendar["'][^>]*>([\s\S]*?)<\/table>/i)?.[1];
  if (!table) throw new Error("calendar_table_not_found");
  const allowed = new Map([
    ["advance monthly sales for retail and food services", "Advance Monthly Sales for Retail and Food Services"],
    ["construction spending (construction put in place)", "Construction Spending (Construction Put in Place)"],
    ["full report - manufacturers' shipments, inventories and orders", "Full Report - Manufacturers' Shipments, Inventories and Orders"],
    ["full report - manufacturers' shipments, inventories, and orders", "Full Report - Manufacturers' Shipments, Inventories and Orders"],
    ["u.s. international trade in goods and services", "U.S. International Trade in Goods and Services"],
  ]);
  const events: CalendarEvent[] = [];
  for (const row of table.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = Array.from(row[1].matchAll(/<td\b([^>]*)>([\s\S]*?)<\/td>/gi));
    if (cells.length < 3) continue;
    const sourceTitle = htmlText(cells[0][2]);
    const title = allowed.get(sourceTitle.toLowerCase());
    const sourceDate = htmlText(cells[1][2]);
    const date = parseDate(sourceDate);
    if (!title || !date || !inHorizon(date, now)) continue;
    const listedTime = htmlText(cells[2][2]);
    const href = cells[0][2].match(/<a\b[^>]*href=["']([^"']+)["']/i)?.[1];
    let sourceUrl = source.url;
    if (href) {
      try {
        const resolved = new URL(href, "https://www.census.gov");
        if (resolved.hostname === "www.census.gov" || resolved.hostname === "census.gov") {
          sourceUrl = resolved.toString();
        }
      } catch {
        sourceUrl = source.url;
      }
    }
    events.push(makeEvent(
      source,
      title,
      `${date}|${listedTime}`,
      date,
      null,
      "unverified_no_timezone_in_source",
      sourceUrl,
      "date_time_listed_timezone_unverified",
      listedTime,
    ));
  }
  return events;
}

export function parseFed(body: string, source: SourceConfig, now: Date): CalendarEvent[] {
  const tokens = body.matchAll(/<\/?div\b[^>]*>|<\/?h4\b[^>]*>|[^<>]+/gi);
  const stack: string[] = [];
  let inHeading = false;
  let currentYear: number | null = null;
  let row: { year: number; month: string; date: string; depth: number } | null = null;
  const events: CalendarEvent[] = [];
  const monthNames = new Set([
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ]);
  for (const tokenMatch of tokens) {
    const token = tokenMatch[0];
    if (/^<h4\b/i.test(token)) {
      inHeading = true;
      continue;
    }
    if (/^<\/h4/i.test(token)) {
      inHeading = false;
      continue;
    }
    if (/^<div\b/i.test(token)) {
      const classes = token.match(/\bclass=["']([^"']*)["']/i)?.[1] ?? "";
      const classTokens = classes.split(/\s+/);
      stack.push(classes);
      if (!row && classTokens.includes("fomc-meeting") && !classTokens.some((item) => item.startsWith("fomc-meeting__"))) {
        row = { year: currentYear ?? new Date().getUTCFullYear(), month: "", date: "", depth: stack.length };
      }
      continue;
    }
    if (/^<\/div/i.test(token)) {
      if (row && stack.length === row.depth) {
        const month = row.month.trim();
        const dateText = row.date.trim();
        const dateMatch = dateText.match(/(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s*\*?/);
        if (monthNames.has(month) && dateMatch) {
          const startDay = Number(dateMatch[1]);
          const endDay = Number(dateMatch[2] ?? dateMatch[1]);
          const start = new Date(Date.UTC(row.year, Array.from(monthNames).indexOf(month), startDay));
          if (!Number.isNaN(start.getTime())) {
            const eventDate = dayString(start, "UTC");
            if (inHorizon(eventDate, now)) {
              const range = startDay === endDay ? `${month} ${startDay}, ${row.year}` : `${month} ${startDay}–${endDay}, ${row.year}`;
              const title = `FOMC meeting window (${range})`;
              events.push(makeEvent(
                source,
                title,
                range,
                eventDate,
                null,
                "meeting_window_no_release_time",
                source.url,
                "verified_meeting_window_release_time_unavailable",
              ));
            }
          }
        }
        row = null;
      }
      stack.pop();
      continue;
    }
    if (token.startsWith("<") || !token.trim()) continue;
    const text = htmlText(token);
    if (inHeading) {
      const yearMatch = text.match(/\b(20\d{2})\s+FOMC Meetings\b/i);
      if (yearMatch) currentYear = Number(yearMatch[1]);
    }
    if (!row) continue;
    const activeClasses = [...stack].reverse().join(" ");
    if (/fomc-meeting__month/.test(activeClasses)) row.month += ` ${text}`;
    else if (/fomc-meeting__date/.test(activeClasses)) row.date += ` ${text}`;
  }
  return events;
}

async function fetchBody(url: string): Promise<string> {
  const parsed = new URL(url);
  const allowedHosts = new Set([
    "apps.bea.gov",
    "www.bls.gov",
    "www.census.gov",
    "www.federalreserve.gov",
  ]);
  if (!allowedHosts.has(parsed.hostname)) throw new Error("source_host_not_allowed");
  const response = await fetch(url, {
    headers: { "User-Agent": "SmartMoneyHubMemberCalendar/1.0" },
    signal: AbortSignal.timeout(12_000),
  });
  if (!response.ok) throw new Error(`source_http_${response.status}`);
  const declaredSize = Number(response.headers.get("content-length") ?? 0);
  if (declaredSize > MAX_BODY_BYTES) throw new Error("source_body_too_large");
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > MAX_BODY_BYTES) throw new Error("source_body_too_large");
  return new TextDecoder().decode(bytes);
}

async function persistSource(
  pool: DatabasePool,
  schema: PortalSupportSchema,
  source: SourceConfig,
  events: CalendarEvent[],
  checkedAt: Date,
): Promise<void> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(`DELETE FROM ${schema}.member_economic_calendar_events WHERE source_key=$1`, [source.id]);
    for (const event of events) {
      await client.query(
        `INSERT INTO ${schema}.member_economic_calendar_events
         (id,source_key,source_name,title,currency,event_date,event_at_utc,time_label,timezone_status,
          impact,impact_basis,source_url,verification_status,previous_value,forecast_value,actual_value,retrieved_at)
         VALUES ($1,$2,$3,$4,'USD',$5::date,$6,$7,$8,$9,'smh_estimate',$10,$11,NULL,NULL,NULL,$12)
         ON CONFLICT (id) DO UPDATE SET
           source_name=EXCLUDED.source_name,title=EXCLUDED.title,event_date=EXCLUDED.event_date,
           event_at_utc=EXCLUDED.event_at_utc,time_label=EXCLUDED.time_label,
           timezone_status=EXCLUDED.timezone_status,impact=EXCLUDED.impact,
           impact_basis=EXCLUDED.impact_basis,source_url=EXCLUDED.source_url,
           verification_status=EXCLUDED.verification_status,retrieved_at=EXCLUDED.retrieved_at`,
        [
          event.id,
          event.sourceKey,
          event.sourceName,
          event.title,
          event.eventDate,
          event.eventAt,
          event.timeLabel,
          event.timezoneStatus,
          impactFor(event.title),
          event.sourceUrl,
          event.verificationStatus,
          checkedAt,
        ],
      );
    }
    await client.query(
      `INSERT INTO ${schema}.member_economic_calendar_sources
       (source_key,source_name,status,checked_at,message)
       VALUES ($1,$2,'available',$3,$4)
       ON CONFLICT (source_key) DO UPDATE SET
         source_name=EXCLUDED.source_name,status='available',
         checked_at=EXCLUDED.checked_at,message=EXCLUDED.message`,
      [source.id, source.sourceName, checkedAt, `${events.length} official schedule entries checked.`],
    );
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

async function saveSourceFailure(
  pool: DatabasePool,
  schema: PortalSupportSchema,
  source: SourceConfig,
  checkedAt: Date,
  error: unknown,
): Promise<void> {
  const message = error instanceof Error ? error.message.slice(0, 120) : "source_unavailable";
  await pool.query(
    `INSERT INTO ${schema}.member_economic_calendar_sources
     (source_key,source_name,status,checked_at,message)
     VALUES ($1,$2,'failed',$3,$4)
     ON CONFLICT (source_key) DO UPDATE SET
       source_name=EXCLUDED.source_name,status='failed',
       checked_at=EXCLUDED.checked_at,message=EXCLUDED.message`,
    [source.id, source.sourceName, checkedAt, message],
  );
}

async function refreshSource(
  pool: DatabasePool,
  schema: PortalSupportSchema,
  source: SourceConfig,
  now: Date,
): Promise<void> {
  const checkedAt = new Date();
  try {
    const body = await fetchBody(source.url);
    let events: CalendarEvent[];
    switch (source.kind) {
      case "bea":
        events = parseBea(body, source, now);
        break;
      case "bls":
        events = parseBls(body, source, now);
        break;
      case "census":
        events = parseCensus(body, source, now);
        break;
      case "fed":
        events = parseFed(body, source, now);
        break;
    }
    await persistSource(pool, schema, source, events, checkedAt);
  } catch (error) {
    await saveSourceFailure(pool, schema, source, checkedAt, error);
  }
}

async function refreshCalendar(pool: DatabasePool, schema: PortalSupportSchema): Promise<void> {
  const now = new Date();
  await Promise.all(SOURCES.map((source) => refreshSource(pool, schema, source, now)));
  await pool.query(
    `INSERT INTO ${schema}.member_economic_calendar_sources
     (source_key,source_name,status,checked_at,message)
     VALUES ($1,$2,'unverified',NOW(),'The official claims schedule parser is not verified; no dates are listed.')
     ON CONFLICT (source_key) DO UPDATE SET
       source_name=EXCLUDED.source_name,status='unverified',
       checked_at=EXCLUDED.checked_at,message=EXCLUDED.message`,
    [DOL_SOURCE.id, DOL_SOURCE.sourceName],
  );
}

export async function refreshMemberCalendarIfStale(
  pool: DatabasePool,
  schema: PortalSupportSchema,
): Promise<void> {
  const statuses = await pool.query(
    `SELECT checked_at FROM ${schema}.member_economic_calendar_sources`,
  );
  const statusRows = statuses.rows as Array<{ checked_at: string | Date | null }>;
  const expired = statusRows.length < SOURCES.length + 1 || statusRows.some((row) => {
    const checkedAt = row.checked_at ? new Date(row.checked_at as string | Date).getTime() : 0;
    return !checkedAt || Date.now() - checkedAt > STALE_AFTER_MS;
  });
  if (!expired) return;
  if (!refreshInFlight) {
    refreshInFlight = refreshCalendar(pool, schema).finally(() => {
      refreshInFlight = null;
    });
  }
  await refreshInFlight;
}

export async function readMemberCalendar(
  pool: DatabasePool,
  schema: PortalSupportSchema,
  filters: { from?: string; to?: string; impact?: string },
) {
  const events = await pool.query(
    `SELECT id,title,currency,event_date,event_at_utc,time_label,impact,impact_basis,
            source_name,source_url,verification_status,timezone_status,
            previous_value,forecast_value,actual_value,retrieved_at
       FROM ${schema}.member_economic_calendar_events
      WHERE event_date >= COALESCE($1::date,CURRENT_DATE)
        AND event_date <= COALESCE($2::date,CURRENT_DATE + INTERVAL '120 days')
        AND ($3::text IS NULL OR impact=$3)
      ORDER BY event_date ASC, event_at_utc ASC NULLS LAST, title ASC
      LIMIT 400`,
    [filters.from ?? null, filters.to ?? null, filters.impact ?? null],
  );
  const sourceRows = await pool.query(
    `SELECT source_key,source_name,status,checked_at,message
       FROM ${schema}.member_economic_calendar_sources
      ORDER BY source_name`,
  );
  const typedSourceRows = sourceRows.rows as Array<{
    source_key: string;
    source_name: string;
    status: string;
    checked_at: string | Date | null;
    message: string | null;
  }>;
  const sources = typedSourceRows.map((row) => {
    const checkedAt = row.checked_at ? new Date(row.checked_at as string | Date) : null;
    const stale = !checkedAt || Date.now() - checkedAt.getTime() > STALE_AFTER_MS;
    const status = stale && row.status === "available" ? "stale" : String(row.status);
    return {
      id: String(row.source_key),
      sourceName: String(row.source_name),
      status,
      checkedAt: checkedAt?.toISOString() ?? null,
      message: String(row.message ?? ""),
    };
  });
  const refreshedAt = sources
    .map((source) => source.checkedAt)
    .filter((value): value is string => value !== null)
    .sort()
    .at(-1) ?? null;
  return {
    events: (events.rows as Array<Record<string, unknown>>).map((row) => ({
      id: String(row.id),
      title: String(row.title),
      currency: "USD" as const,
      eventDate: String(row.event_date).slice(0, 10),
      eventAt: row.event_at_utc ? new Date(row.event_at_utc as string | Date).toISOString() : null,
      timeLabel: String(row.time_label),
      impact: String(row.impact) as "high" | "medium" | "low" | "unavailable",
      impactBasis: String(row.impact_basis) as "smh_estimate" | "source_verified" | "unavailable",
      sourceName: String(row.source_name),
      sourceUrl: String(row.source_url),
      verificationStatus: String(row.verification_status),
      timezoneStatus: String(row.timezone_status),
      previous: row.previous_value == null ? null : String(row.previous_value),
      forecast: row.forecast_value == null ? null : String(row.forecast_value),
      actual: row.actual_value == null ? null : String(row.actual_value),
      lastRetrievedAt: new Date(row.retrieved_at as string | Date).toISOString(),
    })),
    sources,
    refreshedAt,
    stale: sources.some((source: { status: string }) => source.status === "failed" || source.status === "stale"),
  };
}
