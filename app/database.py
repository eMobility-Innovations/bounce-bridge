import aiosqlite
import json
from datetime import datetime
from typing import List, Optional, Tuple
from .config import DB_PATH
from .models import BounceRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS bounces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    recipient TEXT NOT NULL,
    sender TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    conv_id TEXT,
    account_id TEXT,
    chatwoot_notified INTEGER DEFAULT 0,
    postal_suppressed INTEGER DEFAULT 0,
    sender_notified INTEGER DEFAULT 0,
    reason TEXT DEFAULT '',
    raw_payload TEXT,
    expiry_days INTEGER DEFAULT 30,
    dedup_key TEXT
);

CREATE INDEX IF NOT EXISTS idx_bounces_timestamp ON bounces(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_bounces_recipient ON bounces(recipient);
"""

MIGRATIONS = [
    # Add dedup_key column and unique index for race condition prevention
    (
        "ALTER TABLE bounces ADD COLUMN dedup_key TEXT",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bounces_dedup ON bounces(dedup_key)",
    ),
    # Track blocked send attempts (suppressed recipients)
    (
        "ALTER TABLE bounces ADD COLUMN blocked_attempt INTEGER DEFAULT 0",
    ),
]


def make_dedup_key(recipient: str, timestamp: str) -> str:
    """Create a dedup key from recipient + minute-precision time bucket."""
    try:
        if "T" in timestamp:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(timestamp[:19], "%Y-%m-%d %H:%M:%S")
        minute_bucket = dt.strftime("%Y%m%d%H%M")
    except (ValueError, TypeError):
        minute_bucket = datetime.utcnow().strftime("%Y%m%d%H%M")
    return f"{recipient.lower().strip()}:{minute_bucket}"


async def init_db():
    """Initialize the database and run migrations."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()

        # Run migrations for existing databases
        for migration in MIGRATIONS:
            for stmt in migration:
                try:
                    await db.execute(stmt)
                except Exception:
                    pass  # Column/index already exists
            await db.commit()


async def save_bounce(record: BounceRecord) -> Optional[int]:
    """Save a bounce record to the database.

    Uses INSERT OR IGNORE with a dedup_key (recipient + minute bucket)
    to prevent duplicates at the DB level even under concurrent writes.
    Returns the row ID on success, or None if a duplicate was ignored.
    """
    dedup_key = make_dedup_key(record.recipient, record.timestamp)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO bounces (
                timestamp, source, event_type, recipient, sender, subject,
                conv_id, account_id, chatwoot_notified, postal_suppressed,
                sender_notified, reason, raw_payload, expiry_days, dedup_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.timestamp,
                record.source,
                record.event_type,
                record.recipient,
                record.sender,
                record.subject,
                record.conv_id,
                record.account_id,
                int(record.chatwoot_notified),
                int(record.postal_suppressed),
                int(record.sender_notified),
                record.reason,
                record.raw_payload,
                record.expiry_days,
                dedup_key,
            ),
        )
        await db.commit()
        if cursor.lastrowid == 0:
            return None  # Duplicate, INSERT was ignored
        return cursor.lastrowid


async def update_bounce(
    bounce_id: int,
    chatwoot_notified: Optional[bool] = None,
    postal_suppressed: Optional[bool] = None,
    sender_notified: Optional[bool] = None,
):
    """Update a bounce record."""
    updates = []
    values = []

    if chatwoot_notified is not None:
        updates.append("chatwoot_notified = ?")
        values.append(int(chatwoot_notified))
    if postal_suppressed is not None:
        updates.append("postal_suppressed = ?")
        values.append(int(postal_suppressed))
    if sender_notified is not None:
        updates.append("sender_notified = ?")
        values.append(int(sender_notified))

    if not updates:
        return

    values.append(bounce_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE bounces SET {', '.join(updates)} WHERE id = ?",
            values,
        )
        await db.commit()


async def get_recent_bounces(limit: int = 100) -> List[dict]:
    """Get recent bounce records."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM bounces ORDER BY timestamp DESC LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_stats() -> dict:
    """Get suppression statistics."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Total count
        cursor = await db.execute("SELECT COUNT(*) FROM bounces")
        total = (await cursor.fetchone())[0]

        # By type
        cursor = await db.execute(
            "SELECT event_type, COUNT(*) FROM bounces GROUP BY event_type"
        )
        by_type = {row[0]: row[1] for row in await cursor.fetchall()}

        # By source
        cursor = await db.execute(
            "SELECT source, COUNT(*) FROM bounces GROUP BY source"
        )
        by_source = {row[0]: row[1] for row in await cursor.fetchall()}

        # Suppressed count
        cursor = await db.execute(
            "SELECT COUNT(*) FROM bounces WHERE postal_suppressed = 1"
        )
        suppressed = (await cursor.fetchone())[0]

        return {
            "total": total,
            "suppressed": suppressed,
            "by_type": by_type,
            "by_source": by_source,
        }


async def check_db() -> bool:
    """Check if database is accessible."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("SELECT 1")
            return True
    except Exception:
        return False


async def find_recent_bounce(recipient: str, hours: int = 24) -> Optional[dict]:
    """
    Find a recent bounce for the same recipient within the last N hours.
    Returns the bounce record if found, None otherwise.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM bounces
            WHERE recipient = ?
            AND datetime(timestamp) > datetime('now', ?)
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (recipient, f"-{hours} hours"),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def save_blocked_attempt(
    recipient: str,
    sender: str = "",
    subject: str = "",
    reason: str = "",
    account_id: Optional[str] = None,
    conv_id: Optional[str] = None,
    chatwoot_notified: bool = False,
    raw_payload: Optional[str] = None,
) -> Optional[int]:
    """Save a blocked send attempt (suppressed recipient) to the database."""
    ts = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO bounces (
                timestamp, source, event_type, recipient, sender, subject,
                conv_id, account_id, chatwoot_notified, postal_suppressed,
                sender_notified, reason, raw_payload, expiry_days, blocked_attempt
            ) VALUES (?, 'postal', 'blocked_attempt', ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, 0, 1)
            """,
            (
                ts, recipient, sender, subject,
                conv_id, account_id, int(chatwoot_notified),
                reason, raw_payload,
            ),
        )
        await db.commit()
        return cursor.lastrowid
