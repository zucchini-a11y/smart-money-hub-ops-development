from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from contextlib import contextmanager
from collections.abc import Iterator

APP_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(__import__("os").environ.get("WHATSAPP_DB_PATH", APP_DIR / "data" / "assistant.sqlite3"))
WAT = ZoneInfo("Africa/Lagos")

SEED_MODULES = [
    (
        "trading-fundamentals",
        "Trading Fundamentals",
        "Build a plan, understand chart context, and define risk before considering a trade.",
        "A trading plan explains what conditions must be present before you consider a setup, where the idea is invalidated, and how risk is controlled. A chart observation is not an instruction to trade. Start with context, write down the conditions you need, and be willing to stay out when they are absent.",
    ),
    (
        "smart-money-concepts",
        "Smart Money Concepts",
        "Use market structure, liquidity, and areas of interest as context—not automatic entries.",
        "Smart Money Concepts are a way some traders organize price action. Structure, liquidity, and points of interest can help frame a hypothesis, but none confirms a trade by itself. Define what evidence would support or invalidate the idea and follow a written plan.",
    ),
    (
        "market-structure",
        "Market Structure",
        "Read swing highs and lows in context and distinguish a break from a confirmed shift.",
        "Market structure describes how price forms swing highs and swing lows. A break of structure (BOS) is commonly used to describe a move beyond a relevant swing in the direction of an existing move. A change of character (CHoCH) is commonly used for an early break against that move. Definitions vary, so use consistent rules and do not treat a label as a signal.",
    ),
    (
        "liquidity",
        "Liquidity",
        "Learn how traders use equal highs, equal lows, and stop clusters as chart references.",
        "In chart analysis, traders often use liquidity to describe areas where orders may cluster, such as around visible highs or lows. A move through one of those levels can continue, reverse, or form a deeper pullback. A sweep alone does not prove direction; wait for the confirmation your own plan requires.",
    ),
    (
        "points-of-interest",
        "Points of Interest",
        "A POI identifies an area to watch; it does not tell you when to enter.",
        "A point of interest (POI) is an area a trader marks for closer observation, such as an order block or fair value gap. Price reaching that area does not validate a setup. Define confirmation and invalidation in advance and avoid entering only because price touched the zone.",
    ),
    (
        "order-blocks",
        "Order Blocks",
        "Treat order blocks as chart areas to evaluate, not guaranteed support or resistance.",
        "An order block is a chart concept used to mark a candle or area before a notable move. Traders define these zones differently. A marked block can fail, so evaluate it with broader structure, the plan's confirmation rule, and a clear invalidation point rather than assuming price must react there.",
    ),
    (
        "fair-value-gaps",
        "Fair Value Gaps",
        "Understand imbalance zones and why they still need context and confirmation.",
        "A fair value gap (FVG) is commonly marked where a three-candle sequence leaves an imbalance between the first and third candles. Traders may watch how price revisits that range, but it is not a promise that price will fill or reverse there. Use a consistent definition and combine it with a broader plan.",
    ),
    (
        "premium-discount",
        "Premium and Discount",
        "Compare price with a defined range midpoint without assuming a trade direction.",
        "Premium and discount describe whether price is above or below the midpoint of a chosen dealing range. The range must be defined consistently; changing it can change the label. These terms provide context, not an entry signal, and do not replace confirmation or risk limits.",
    ),
    (
        "gold-xauusd",
        "Gold Trading (XAUUSD)",
        "Approach gold with a plan for volatility, event risk, and position sizing.",
        "Gold (XAUUSD) can move sharply and spreads or execution conditions may change around major events. This assistant does not have verified live prices or a live calendar. Check a current, reliable source yourself, define your invalidation and risk in advance, and do not treat general education as a trade recommendation.",
    ),
    (
        "risk-management",
        "Risk Management",
        "Set risk and invalidation before entry; protect capital and accept that losses occur.",
        "Risk management starts before an order: decide what would invalidate the idea, how much you are prepared to risk under your own plan, and whether the setup fits your limits. Avoid increasing risk to recover a loss. No approach removes the possibility of losing money.",
    ),
    (
        "trading-psychology",
        "Trading Psychology",
        "Use a repeatable process, pause after emotional decisions, and review a journal.",
        "A journal helps compare decisions with the plan rather than judging only by outcome. Record the setup, the evidence, the risk decision, and any deviation. If you feel pressure to chase, revenge-trade, or abandon your rules, stepping away is a valid decision.",
    ),
    (
        "gold-and-usd",
        "Gold and the U.S. Dollar",
        "Study possible relationships without treating correlation as a reliable prediction.",
        "Gold and the U.S. dollar can respond to overlapping factors such as rates, yields, and risk sentiment, but their relationship is not fixed. This assistant does not verify live news, prices, or macro releases. Use current sources and avoid inferring a trade from a single headline or correlation.",
    ),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=10) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY,
                wa_id TEXT NOT NULL UNIQUE,
                display_name TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                last_inbound_at TEXT NOT NULL,
                unread_count INTEGER NOT NULL DEFAULT 0,
                is_enquiry INTEGER NOT NULL DEFAULT 0,
                welcome_sent INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                provider_id TEXT NOT NULL UNIQUE,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                direction TEXT NOT NULL CHECK(direction IN ('inbound', 'outbound')),
                text TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                response_state TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
                ON messages(conversation_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_messages_response_state
                ON messages(direction, response_state, created_at);
            CREATE TABLE IF NOT EXISTS education_modules (
                slug TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                published INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conversation_columns = {
            row[1] for row in db.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "welcome_sent" not in conversation_columns:
            db.execute("ALTER TABLE conversations ADD COLUMN welcome_sent INTEGER NOT NULL DEFAULT 0")
        existing = db.execute("SELECT COUNT(*) FROM education_modules").fetchone()[0]
        if existing == 0:
            db.executemany(
                """INSERT INTO education_modules
                   (slug, title, summary, content, published, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?)""",
                [(slug, title, summary, content, utc_now()) for slug, title, summary, content in SEED_MODULES],
            )
        db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('paused', '0')")
        db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('telegram_community_url', '')")


def connection() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    db = connection()
    try:
        with db:
            yield db
    finally:
        db.close()


def get_setting(key: str, default: str = "") -> str:
    with db_session() as db:
        row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def put_setting(key: str, value: str) -> None:
    with db_session() as db:
        db.execute(
            """INSERT INTO settings(key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )


def add_activity(kind: str, summary: str) -> None:
    with db_session() as db:
        db.execute(
            "INSERT INTO activity(kind, summary, created_at) VALUES (?, ?, ?)",
            (kind[:40], summary[:240], utc_now()),
        )


def record_inbound(
    provider_id: str,
    wa_id: str,
    display_name: str | None,
    text: str,
    status: str = "received",
) -> tuple[int, bool] | None:
    now = utc_now()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(timespec="seconds")
    rate_limited = False
    with db_session() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT id FROM conversations WHERE wa_id = ?", (wa_id,)).fetchone()
        is_new = row is None
        if is_new:
            cursor = db.execute(
                """INSERT INTO conversations
                   (wa_id, display_name, first_seen, last_seen, last_inbound_at, unread_count)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (wa_id, display_name, now, now, now),
            )
            conversation_id = int(cursor.lastrowid)
        else:
            conversation_id = int(row["id"])
            recent_count = db.execute(
                """SELECT COUNT(*) FROM messages
                   WHERE conversation_id = ? AND direction = 'inbound' AND created_at >= ?""",
                (conversation_id, cutoff),
            ).fetchone()[0]
            rate_limited = recent_count >= 20
            db.execute(
                """UPDATE conversations SET
                   display_name = COALESCE(?, display_name),
                   last_seen = ?, last_inbound_at = ?, unread_count = unread_count + 1
                   WHERE id = ?""",
                (display_name, now, now, conversation_id),
            )
        try:
            db.execute(
                """INSERT INTO messages
                   (provider_id, conversation_id, direction, text, status, created_at, response_state)
                   VALUES (?, ?, 'inbound', ?, ?, ?, ?)""",
                (
                    provider_id,
                    conversation_id,
                    text[:4096],
                    "rate_limited" if rate_limited else status,
                    now,
                    "blocked" if rate_limited else "pending",
                ),
            )
        except sqlite3.IntegrityError:
            db.rollback()
            return None
    add_activity(
        "attention" if rate_limited else "inbound",
        "An inbound message was held by the rate limit." if rate_limited else "New incoming message received.",
    )
    return conversation_id, is_new


def claim_next_inbound() -> sqlite3.Row | None:
    with db_session() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
        """SELECT m.id, m.conversation_id, m.text, c.wa_id, c.display_name,
                      c.first_seen, c.last_inbound_at, c.is_enquiry, c.welcome_sent
               FROM messages m JOIN conversations c ON c.id = m.conversation_id
               WHERE m.direction = 'inbound' AND m.response_state = 'pending'
               ORDER BY m.id LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        db.execute("UPDATE messages SET response_state = 'processing' WHERE id = ?", (row["id"],))
        return row


def mark_interrupted_processing() -> int:
    with db_session() as db:
        cur = db.execute(
            """UPDATE messages SET response_state = 'uncertain'
               WHERE direction = 'inbound' AND response_state = 'processing'"""
        )
    if cur.rowcount:
        add_activity("attention", "A reply was interrupted; check the conversation before retrying.")
    return cur.rowcount


def finish_inbound(message_id: int, state: str) -> None:
    with db_session() as db:
        db.execute("UPDATE messages SET response_state = ? WHERE id = ?", (state, message_id))


def mark_welcome_sent(conversation_id: int) -> None:
    with db_session() as db:
        db.execute("UPDATE conversations SET welcome_sent = 1 WHERE id = ?", (conversation_id,))


def add_outbound(conversation_id: int, provider_id: str, text: str, status: str = "sent") -> int:
    with db_session() as db:
        cursor = db.execute(
            """INSERT INTO messages
               (provider_id, conversation_id, direction, text, status, created_at)
               VALUES (?, ?, 'outbound', ?, ?, ?)""",
            (provider_id, conversation_id, text[:4096], status, utc_now()),
        )
        db.execute(
            "UPDATE conversations SET last_seen = ? WHERE id = ?",
            (utc_now(), conversation_id),
        )
        return int(cursor.lastrowid)


def mark_enquiry(conversation_id: int) -> None:
    with db_session() as db:
        db.execute("UPDATE conversations SET is_enquiry = 1 WHERE id = ?", (conversation_id,))
    add_activity("enquiry", "A conversation was flagged for admin follow-up.")


def list_conversations(
    search: str = "",
    enquiries_only: bool = False,
    test_recipients: set[str] | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT c.*, m.text AS last_message_preview
        FROM conversations c
        LEFT JOIN messages m ON m.id = (
            SELECT MAX(id) FROM messages WHERE conversation_id = c.id
        )
    """
    conditions: list[str] = []
    params: list[Any] = []
    if search:
        like = f"%{search[:80]}%"
        conditions.append("(c.wa_id LIKE ? OR COALESCE(c.display_name, '') LIKE ?)")
        params.extend((like, like))
    if enquiries_only:
        conditions.append("c.is_enquiry = 1")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY c.last_seen DESC LIMIT 100"
    now = datetime.now(timezone.utc)
    with db_session() as db:
        rows = db.execute(query, params).fetchall()
    results = []
    for row in rows:
        inbound = _parse_time(row["last_inbound_at"])
        results.append(
            {
                "id": row["id"],
                "waId": row["wa_id"],
                "displayName": row["display_name"],
                "lastMessagePreview": row["last_message_preview"] or "",
                "lastMessageAt": row["last_seen"],
                "unreadCount": row["unread_count"],
                "isEnquiry": bool(row["is_enquiry"]),
                "testRecipientAllowed": row["wa_id"] in (test_recipients or set()),
                "replyWindowOpen": bool(inbound and (now - inbound).total_seconds() < 24 * 60 * 60),
            }
        )
    return results


def get_conversation(
    conversation_id: int,
    test_recipients: set[str] | None = None,
) -> dict[str, Any] | None:
    with db_session() as db:
        conv = db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if conv is None:
            return None
        rows = db.execute(
            """SELECT id, direction, text, status, created_at
               FROM messages WHERE conversation_id = ? ORDER BY id LIMIT 500""",
            (conversation_id,),
        ).fetchall()
        db.execute("UPDATE conversations SET unread_count = 0 WHERE id = ?", (conversation_id,))
    messages = [
        {
            "id": row["id"],
            "direction": row["direction"],
            "text": row["text"],
            "status": row["status"],
            "createdAt": row["created_at"],
        }
        for row in rows
    ]
    summary = next(
        (item for item in list_conversations(test_recipients=test_recipients) if item["id"] == conversation_id),
        None,
    )
    return {"conversation": summary, "messages": messages} if summary else None


def conversation_by_id(conversation_id: int) -> sqlite3.Row | None:
    with db_session() as db:
        return db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()


def recent_messages(conversation_id: int, limit: int = 12) -> list[dict[str, str]]:
    with db_session() as db:
        rows = db.execute(
            """SELECT direction, text FROM messages
               WHERE conversation_id = ? ORDER BY id DESC LIMIT ?""",
            (conversation_id, limit),
        ).fetchall()
    return [{"role": "user" if row["direction"] == "inbound" else "assistant", "text": row["text"]} for row in reversed(rows)]


def list_modules(published_only: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM education_modules"
    if published_only:
        query += " WHERE published = 1"
    query += " ORDER BY title"
    with db_session() as db:
        rows = db.execute(query).fetchall()
    return [
        {
            "slug": row["slug"],
            "title": row["title"],
            "summary": row["summary"],
            "content": row["content"],
            "published": bool(row["published"]),
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def update_module(slug: str, summary: str, content: str, published: bool) -> dict[str, Any] | None:
    with db_session() as db:
        cur = db.execute(
            """UPDATE education_modules
               SET summary = ?, content = ?, published = ?, updated_at = ?
               WHERE slug = ?""",
            (summary[:2000], content[:50000], int(published), utc_now(), slug),
        )
    if not cur.rowcount:
        return None
    return next(module for module in list_modules() if module["slug"] == slug)


def recent_activity(limit: int = 30) -> list[dict[str, Any]]:
    with db_session() as db:
        rows = db.execute(
            "SELECT id, kind, summary, created_at FROM activity ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"id": row["id"], "kind": row["kind"], "summary": row["summary"], "createdAt": row["created_at"]}
        for row in rows
    ]


def dashboard_counts() -> dict[str, int]:
    from datetime import time as datetime_time

    day_start = datetime.combine(datetime.now(WAT).date(), datetime_time.min, tzinfo=WAT)
    day_start_utc = day_start.astimezone(timezone.utc).isoformat(timespec="seconds")
    with db_session() as db:
        conversations = db.execute(
            "SELECT COUNT(*) FROM conversations WHERE first_seen >= ?",
            (day_start_utc,),
        ).fetchone()[0]
        messages = db.execute(
            "SELECT COUNT(*) FROM messages WHERE created_at >= ?",
            (day_start_utc,),
        ).fetchone()[0]
        enquiries = db.execute("SELECT COUNT(*) FROM conversations WHERE is_enquiry = 1").fetchone()[0]
    return {"conversationsToday": conversations, "messagesToday": messages, "openEnquiries": enquiries}


def set_paused(paused: bool) -> None:
    put_setting("paused", "1" if paused else "0")
    add_activity("assistant", "AI replies paused." if paused else "AI replies resumed.")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
