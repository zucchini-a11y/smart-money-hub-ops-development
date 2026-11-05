import { randomUUID } from "node:crypto";
import { Router, type IRouter, type Request, type Response } from "express";
import {
  CreateMemberJournalTradeBody,
  CreateMemberJournalTradeResponse,
  DeleteMemberJournalTradeResponse,
  GetMemberCalendarResponse,
  ListMemberJournalTradesResponse,
  SendMemberCoachMessageBody,
  SendMemberCoachMessageResponse,
  UpdateMemberJournalTradeBody,
  UpdateMemberJournalTradeResponse,
} from "@workspace/api-zod";
import { pool } from "@workspace/db";
import { requireSameOrigin } from "../lib/portal-auth";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";
import { requireMemberIdentity } from "./member";
import { readMemberCalendar, refreshMemberCalendarIfStale } from "./member-calendar";

const router: IRouter = Router();
const schema = resolvePortalSupportSchema(process.env.NODE_ENV, process.env.PORTAL_SUPPORT_SCHEMA);
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TRADE_FIELDS = {
  instrument: "instrument",
  direction: "direction",
  entryPrice: "entry_price",
  stopLoss: "stop_loss",
  takeProfit: "take_profit",
  positionSize: "position_size",
  riskPercent: "risk_percent",
  entryAt: "entry_at",
  exitAt: "exit_at",
  outcome: "outcome",
  realizedPnl: "realized_pnl",
  notes: "notes",
} as const;

const COACH_DISCLAIMER =
  "Educational only—not financial advice. The Coach cannot verify live prices, news, or entry confirmations.";
const COACH_SYSTEM_INSTRUCTION = [
  "You are the Smart Money Hub educational Coach.",
  "Teach concepts clearly and briefly; explain trading acronyms when relevant.",
  "The Hub's preferred process is H1 context, a point of interest as a watch area (not an entry), then M5 confirmation such as a liquidity sweep and displacement with BOS or CHOCH; a retest is preferred when suitable but is not mandatory for every model.",
  "The plan's 2% per-trade risk, minimum planned 1:3 reward-to-risk, 3% daily loss cap, and break-even at 1:1 are preferences, not proof a setup is valid or guarantees.",
  "Use the principle: NO CONFIRMATION, NO ENTRY.",
  "Never claim to see live prices, current news, a chart, a valid setup, or confirmation. Do not invent market data or promise outcomes.",
  "For live-market questions, say you cannot verify live conditions and invite the user to check their own trusted source.",
  "Do not provide personalized financial advice or tell the user to enter a specific trade.",
].join(" ");

function developmentToolsEnabled(res: Response): boolean {
  if (process.env.NODE_ENV === "production" || schema !== "smh_test") {
    res.status(404).json({ error: "Member learning tools are not enabled in this environment." });
    return false;
  }
  return true;
}

function privateResponse(res: Response): void {
  res.setHeader("Cache-Control", "no-store, private");
  res.setHeader("Pragma", "no-cache");
}

function queryText(value: unknown): string | undefined {
  return typeof value === "string" ? value.trim() : undefined;
}

function validIsoDate(value: string | undefined): boolean {
  if (value === undefined) return true;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function riskRewardRatio(trade: {
  direction: "long" | "short";
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
}): number | null {
  const risk = trade.direction === "long"
    ? trade.entryPrice - trade.stopLoss
    : trade.stopLoss - trade.entryPrice;
  const reward = trade.direction === "long"
    ? trade.takeProfit - trade.entryPrice
    : trade.entryPrice - trade.takeProfit;
  if (!(risk > 0) || !(reward > 0)) return null;
  return Math.round((reward / risk) * 100) / 100;
}

function mapTrade(row: Record<string, unknown>) {
  const trade = {
    id: String(row.id),
    instrument: String(row.instrument),
    direction: String(row.direction) as "long" | "short",
    entryPrice: Number(row.entry_price),
    stopLoss: Number(row.stop_loss),
    takeProfit: Number(row.take_profit),
    positionSize: Number(row.position_size),
    riskPercent: row.risk_percent == null ? null : Number(row.risk_percent),
    entryAt: new Date(row.entry_at as string | Date).toISOString(),
    exitAt: row.exit_at == null ? null : new Date(row.exit_at as string | Date).toISOString(),
    outcome: String(row.outcome) as "open" | "win" | "loss" | "breakeven",
    realizedPnl: row.realized_pnl == null ? null : Number(row.realized_pnl),
    notes: String(row.notes ?? ""),
    createdAt: new Date(row.created_at as string | Date).toISOString(),
    updatedAt: new Date(row.updated_at as string | Date).toISOString(),
  };
  return { ...trade, riskRewardRatio: riskRewardRatio(trade) };
}

function validateTrade(
  trade: {
    instrument: string;
    direction: "long" | "short";
    entryPrice: number;
    stopLoss: number;
    takeProfit: number;
    positionSize: number;
    entryAt: string | Date;
    exitAt?: string | Date | null;
    outcome: "open" | "win" | "loss" | "breakeven";
  },
): string | null {
  const validDirection = trade.direction === "long"
    ? trade.stopLoss < trade.entryPrice && trade.takeProfit > trade.entryPrice
    : trade.stopLoss > trade.entryPrice && trade.takeProfit < trade.entryPrice;
  if (!validDirection) return "For a long trade, stop loss must be below entry and take profit above it; reverse those levels for a short trade.";
  if (trade.outcome === "open" && trade.exitAt) return "Open trades cannot have an exit date.";
  if (trade.outcome !== "open" && !trade.exitAt) return "Add an exit date before recording a closed trade.";
  if (trade.exitAt && new Date(trade.exitAt).getTime() < new Date(trade.entryAt).getTime()) return "The exit date cannot be before the entry date.";
  return null;
}

function parseTradeRow(body: unknown, update = false) {
  return update
    ? UpdateMemberJournalTradeBody.safeParse(body)
    : CreateMemberJournalTradeBody.safeParse(body);
}

router.get("/member/calendar", async (req: Request, res: Response): Promise<void> => {
  privateResponse(res);
  if (!developmentToolsEnabled(res)) return;
  const identity = await requireMemberIdentity(req, res);
  if (!identity) return;

  const from = queryText(req.query.from);
  const to = queryText(req.query.to);
  const impact = queryText(req.query.impact);
  const currency = queryText(req.query.currency);
  if (!validIsoDate(from) || !validIsoDate(to) || (from && to && from > to)) {
    res.status(400).json({ error: "Choose a valid calendar date range." });
    return;
  }
  if (currency && currency !== "USD") {
    res.status(400).json({ error: "Only the USD calendar is currently available." });
    return;
  }
  if (impact && !["high", "medium", "low", "unavailable"].includes(impact)) {
    res.status(400).json({ error: "Choose a valid impact filter." });
    return;
  }

  await refreshMemberCalendarIfStale(pool, schema);
  const result = await readMemberCalendar(pool, schema, { from, to, impact });
  res.json(GetMemberCalendarResponse.parse(result));
});

router.get("/member/journal", async (req: Request, res: Response): Promise<void> => {
  privateResponse(res);
  if (!developmentToolsEnabled(res)) return;
  const identity = await requireMemberIdentity(req, res);
  if (!identity) return;

  const instrument = queryText(req.query.instrument);
  const outcome = queryText(req.query.outcome);
  if (instrument && (instrument.length < 2 || instrument.length > 24)) {
    res.status(400).json({ error: "Instrument must be 2 to 24 characters." });
    return;
  }
  if (outcome && !["open", "win", "loss", "breakeven"].includes(outcome)) {
    res.status(400).json({ error: "Choose a valid trade outcome." });
    return;
  }

  const values: unknown[] = [identity.clerkUserId];
  const conditions = ["clerk_user_id=$1"];
  if (instrument) {
    values.push(instrument);
    conditions.push(`position(lower($${values.length}) in lower(instrument)) > 0`);
  }
  if (outcome) {
    values.push(outcome);
    conditions.push(`outcome=$${values.length}`);
  }
  const where = conditions.join(" AND ");
  const [tradesResult, summaryResult] = await Promise.all([
    pool.query(
      `SELECT id,instrument,direction,entry_price,stop_loss,take_profit,position_size,
              risk_percent,entry_at,exit_at,outcome,realized_pnl,notes,created_at,updated_at
         FROM ${schema}.member_journal_trades
        WHERE ${where}
        ORDER BY entry_at DESC
        LIMIT 500`,
      values,
    ),
    pool.query(
      `SELECT COUNT(*)::int AS total_trades,
              COUNT(*) FILTER (WHERE outcome='open')::int AS open_trades,
              COUNT(*) FILTER (WHERE outcome='win')::int AS wins,
              COUNT(*) FILTER (WHERE outcome='loss')::int AS losses,
              COUNT(*) FILTER (WHERE outcome='breakeven')::int AS breakeven,
              CASE WHEN COUNT(*) FILTER (WHERE outcome IN ('win','loss')) > 0
                   THEN (COUNT(*) FILTER (WHERE outcome='win')::numeric * 100
                         / COUNT(*) FILTER (WHERE outcome IN ('win','loss')))::numeric
                   ELSE NULL END AS win_rate,
              COALESCE(SUM(realized_pnl),0)::numeric AS total_recorded_pnl,
              AVG(CASE WHEN direction='long'
                       THEN (take_profit-entry_price)/NULLIF(entry_price-stop_loss,0)
                       ELSE (entry_price-take_profit)/NULLIF(stop_loss-entry_price,0)
                  END)::numeric AS average_planned_risk_reward
         FROM ${schema}.member_journal_trades
        WHERE ${where}`,
      values,
    ),
  ]);
  const summaryRow = summaryResult.rows[0] ?? {};
  res.json(ListMemberJournalTradesResponse.parse({
    trades: tradesResult.rows.map((row) => mapTrade(row)),
    summary: {
      totalTrades: Number(summaryRow.total_trades ?? 0),
      openTrades: Number(summaryRow.open_trades ?? 0),
      wins: Number(summaryRow.wins ?? 0),
      losses: Number(summaryRow.losses ?? 0),
      breakeven: Number(summaryRow.breakeven ?? 0),
      winRate: summaryRow.win_rate == null ? null : Number(summaryRow.win_rate),
      totalRecordedPnl: Number(summaryRow.total_recorded_pnl ?? 0),
      averagePlannedRiskReward: summaryRow.average_planned_risk_reward == null
        ? null
        : Number(summaryRow.average_planned_risk_reward),
    },
  }));
});

router.post("/member/journal", requireSameOrigin, async (req: Request, res: Response): Promise<void> => {
  privateResponse(res);
  if (!developmentToolsEnabled(res)) return;
  const identity = await requireMemberIdentity(req, res);
  if (!identity) return;
  const parsed = parseTradeRow(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Check the trade details and try again." });
    return;
  }
  const data = parsed.data as {
    instrument: string;
    direction: "long" | "short";
    entryPrice: number;
    stopLoss: number;
    takeProfit: number;
    positionSize: number;
    riskPercent?: number | null;
    entryAt: string | Date;
    exitAt?: string | Date | null;
    outcome: "open" | "win" | "loss" | "breakeven";
    realizedPnl?: number | null;
    notes?: string;
  };
  if (
    !data.instrument || !data.direction || data.entryPrice === undefined ||
    data.stopLoss === undefined || data.takeProfit === undefined ||
    data.positionSize === undefined || !data.entryAt || !data.outcome
  ) {
    res.status(400).json({ error: "Complete all required trade fields." });
    return;
  }
  const validationError = validateTrade(data);
  if (validationError) {
    res.status(400).json({ error: validationError });
    return;
  }
  const inserted = await pool.query(
    `INSERT INTO ${schema}.member_journal_trades
     (id,clerk_user_id,instrument,direction,entry_price,stop_loss,take_profit,position_size,
      risk_percent,entry_at,exit_at,outcome,realized_pnl,notes)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
     RETURNING id,instrument,direction,entry_price,stop_loss,take_profit,position_size,
               risk_percent,entry_at,exit_at,outcome,realized_pnl,notes,created_at,updated_at`,
    [
      randomUUID(), identity.clerkUserId, data.instrument.trim(), data.direction,
      data.entryPrice, data.stopLoss, data.takeProfit, data.positionSize,
      data.riskPercent ?? null, data.entryAt, data.exitAt ?? null, data.outcome,
      data.realizedPnl ?? null, data.notes?.trim() ?? "",
    ],
  );
  res.status(201).json(CreateMemberJournalTradeResponse.parse(mapTrade(inserted.rows[0])));
});

router.patch("/member/journal/:tradeId", requireSameOrigin, async (req: Request, res: Response): Promise<void> => {
  privateResponse(res);
  if (!developmentToolsEnabled(res)) return;
  const identity = await requireMemberIdentity(req, res);
  if (!identity) return;
  const tradeId = Array.isArray(req.params.tradeId) ? req.params.tradeId[0] : req.params.tradeId;
  if (!UUID_RE.test(tradeId)) {
    res.status(404).json({ error: "Trade not found." });
    return;
  }
  const parsed = parseTradeRow(req.body, true);
  if (!parsed.success || Object.keys(parsed.data ?? {}).length === 0) {
    res.status(400).json({ error: "Provide at least one valid trade field to update." });
    return;
  }
  const existing = await pool.query(
    `SELECT id,instrument,direction,entry_price,stop_loss,take_profit,position_size,
            risk_percent,entry_at,exit_at,outcome,realized_pnl,notes,created_at,updated_at
       FROM ${schema}.member_journal_trades
      WHERE id=$1 AND clerk_user_id=$2 LIMIT 1`,
    [tradeId, identity.clerkUserId],
  );
  if (!existing.rows[0]) {
    res.status(404).json({ error: "Trade not found." });
    return;
  }
  const current = mapTrade(existing.rows[0]);
  const merged = {
    instrument: current.instrument,
    direction: current.direction,
    entryPrice: current.entryPrice,
    stopLoss: current.stopLoss,
    takeProfit: current.takeProfit,
    positionSize: current.positionSize,
    riskPercent: current.riskPercent,
    entryAt: current.entryAt,
    exitAt: current.exitAt,
    outcome: current.outcome,
    realizedPnl: current.realizedPnl,
    notes: current.notes,
    ...parsed.data,
  };
  const complete = CreateMemberJournalTradeBody.safeParse(merged);
  if (!complete.success) {
    res.status(400).json({ error: "The updated trade is incomplete or invalid." });
    return;
  }
  const validationError = validateTrade(complete.data);
  if (validationError) {
    res.status(400).json({ error: validationError });
    return;
  }

  const fields = Object.entries(parsed.data).filter(([key]) => key in TRADE_FIELDS);
  const values: unknown[] = fields.map(([key, value]) => {
    if (key === "instrument" && typeof value === "string") return value.trim();
    if (key === "notes" && typeof value === "string") return value.trim();
    return value;
  });
  const assignments = fields.map(([key], index) => `${TRADE_FIELDS[key as keyof typeof TRADE_FIELDS]}=$${index + 1}`);
  values.push(tradeId, identity.clerkUserId);
  const updated = await pool.query(
    `UPDATE ${schema}.member_journal_trades
        SET ${assignments.join(",")},updated_at=NOW()
      WHERE id=$${values.length - 1} AND clerk_user_id=$${values.length}
      RETURNING id,instrument,direction,entry_price,stop_loss,take_profit,position_size,
                risk_percent,entry_at,exit_at,outcome,realized_pnl,notes,created_at,updated_at`,
    values,
  );
  if (!updated.rows[0]) {
    res.status(404).json({ error: "Trade not found." });
    return;
  }
  res.json(UpdateMemberJournalTradeResponse.parse(mapTrade(updated.rows[0])));
});

router.delete("/member/journal/:tradeId", requireSameOrigin, async (req: Request, res: Response): Promise<void> => {
  privateResponse(res);
  if (!developmentToolsEnabled(res)) return;
  const identity = await requireMemberIdentity(req, res);
  if (!identity) return;
  const tradeId = Array.isArray(req.params.tradeId) ? req.params.tradeId[0] : req.params.tradeId;
  if (!UUID_RE.test(tradeId)) {
    res.status(404).json({ error: "Trade not found." });
    return;
  }
  const deleted = await pool.query(
    `DELETE FROM ${schema}.member_journal_trades WHERE id=$1 AND clerk_user_id=$2 RETURNING id`,
    [tradeId, identity.clerkUserId],
  );
  if (!deleted.rowCount) {
    res.status(404).json({ error: "Trade not found." });
    return;
  }
  res.json(DeleteMemberJournalTradeResponse.parse({ deleted: true }));
});

async function consumeCoachRateLimit(clerkUserId: string): Promise<boolean> {
  const bucketStart = new Date(Math.floor(Date.now() / 600_000) * 600_000);
  const result = await pool.query(
    `WITH expired AS (
       DELETE FROM ${schema}.member_coach_rate_limits
        WHERE bucket_start < NOW() - INTERVAL '2 days'
     )
     INSERT INTO ${schema}.member_coach_rate_limits(clerk_user_id,bucket_start,request_count)
     VALUES($1,$2,1)
     ON CONFLICT(clerk_user_id,bucket_start)
     DO UPDATE SET request_count=${schema}.member_coach_rate_limits.request_count + 1
     RETURNING request_count`,
    [clerkUserId, bucketStart],
  );
  return Number(result.rows[0]?.request_count ?? 0) <= 12;
}

function localCoachReply(message: string): { reply: string; topic: string } {
  if (/\b(trading plan|our plan|risk plan)\b/i.test(message)) {
    return {
      topic: "Trading Plan",
      reply: "Use the process in order: H1 for context; mark a POI as a watch area, not an entry; wait for planned M5 confirmation such as a liquidity sweep and valid BOS or CHOCH. The plan's risk limits are preferences, not proof a setup is valid. NO CONFIRMATION, NO ENTRY.",
    };
  }
  return {
    topic: "Learning guidance",
    reply: "I can help with trading concepts, but cannot verify live prices, current news, or entry confirmation. Compare the idea with your written plan and be willing to stand aside when confirmation is missing.",
  };
}

async function generateCoachReply(
  message: string,
  history: Array<{ role: "user" | "assistant"; content: string }>,
): Promise<{ reply: string; topic: string }> {
  const apiKey = process.env.GEMINI_API_KEY?.trim();
  if (!apiKey) return localCoachReply(message);
  const contents = [
    ...history.slice(-6).map((item) => ({
      role: item.role === "assistant" ? "model" : "user",
      parts: [{ text: item.content.slice(0, 1200) }],
    })),
    { role: "user", parts: [{ text: message.slice(0, 1200) }] },
  ];
  try {
    const response = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key=${encodeURIComponent(apiKey)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          systemInstruction: { parts: [{ text: COACH_SYSTEM_INSTRUCTION }] },
          contents,
          generationConfig: { temperature: 0.35, maxOutputTokens: 900 },
        }),
        signal: AbortSignal.timeout(10_000),
      },
    );
    if (!response.ok) return localCoachReply(message);
    const payload = await response.json() as {
      candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
    };
    const reply = payload.candidates?.[0]?.content?.parts
      ?.map((part) => part.text ?? "")
      .join("\n")
      .trim();
    if (!reply) return localCoachReply(message);
    return { reply: reply.slice(0, 3500), topic: "Smart Money Hub Coach" };
  } catch {
    return localCoachReply(message);
  }
}

router.post("/member/coach/chat", requireSameOrigin, async (req: Request, res: Response): Promise<void> => {
  privateResponse(res);
  if (!developmentToolsEnabled(res)) return;
  const identity = await requireMemberIdentity(req, res);
  if (!identity) return;
  const parsed = SendMemberCoachMessageBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Enter a question of up to 1,200 characters." });
    return;
  }
  if (!(await consumeCoachRateLimit(identity.clerkUserId))) {
    res.status(429).json({ error: "The Coach is receiving too many requests from this account. Try again in a few minutes." });
    return;
  }
  const history = (parsed.data.history ?? [])
    .slice(-6)
    .map((item) => ({ role: item.role, content: item.content.trim().slice(0, 1200) }));
  const generated = await generateCoachReply(parsed.data.message.trim(), history);
  res.json(SendMemberCoachMessageResponse.parse({
    ...generated,
    disclaimer: COACH_DISCLAIMER,
  }));
});

export default router;
