import asyncio
import logging
from typing import Optional
from datetime import datetime

from ..config import get_config, EXPIRY_DAYS
from ..models import BounceRecord
from .. import database
from .postal import postal_client
from .notifier import send_bounce_notification_email, send_chatwoot_note

logger = logging.getLogger(__name__)

# In-memory locks keyed by recipient to prevent concurrent processing
_recipient_locks: dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()


async def _get_recipient_lock(recipient: str) -> asyncio.Lock:
    """Get or create a per-recipient asyncio lock."""
    key = recipient.lower().strip()
    async with _locks_lock:
        if key not in _recipient_locks:
            _recipient_locks[key] = asyncio.Lock()
        return _recipient_locks[key]


def get_expiry_days(source: str, event_type: str) -> int:
    """Get expiry days based on source and event type."""
    config = get_config()
    expiry_config = config.get("expiry", EXPIRY_DAYS)

    if source == "ses":
        if event_type == "complaint":
            return expiry_config.get("ses_complaint", 180)
        elif event_type in ("hard_bounce", "permanent"):
            return expiry_config.get("ses_permanent", 365)
        else:
            return expiry_config.get("ses_transient", 30)
    elif source == "postal":
        return expiry_config.get("postal_bounce", 30)
    elif source == "postfix":
        if event_type == "hard_bounce":
            return expiry_config.get("postfix_hard", 365)
        else:
            return expiry_config.get("postfix_soft", 30)

    return 30


async def process_bounce(
    source: str,
    event_type: str,
    recipient: str,
    sender: Optional[str] = None,
    subject: Optional[str] = None,
    reason: str = "",
    account_id: Optional[str] = None,
    conv_id: Optional[str] = None,
    raw_payload: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Optional[BounceRecord]:
    """
    Process a bounce event:
    1. Check for duplicate (same recipient in last 24h)
    2. Calculate expiry
    3. Save to database
    4. Suppress in Postal
    5. Send notification email
    6. Add Chatwoot note (if conv_id present)

    Returns None if duplicate found (skipped).
    """
    lock = await _get_recipient_lock(recipient)
    async with lock:
        return await _process_bounce_locked(
            source=source, event_type=event_type, recipient=recipient,
            sender=sender, subject=subject, reason=reason,
            account_id=account_id, conv_id=conv_id,
            raw_payload=raw_payload, timestamp=timestamp,
        )


async def _process_bounce_locked(
    source: str,
    event_type: str,
    recipient: str,
    sender: Optional[str] = None,
    subject: Optional[str] = None,
    reason: str = "",
    account_id: Optional[str] = None,
    conv_id: Optional[str] = None,
    raw_payload: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Optional[BounceRecord]:
    """Inner bounce processing, called under per-recipient lock."""
    config = get_config()
    ts = timestamp or datetime.utcnow().isoformat()
    expiry_days = get_expiry_days(source, event_type)

    # Check for duplicate bounce in last 24 hours
    existing = await database.find_recent_bounce(recipient, hours=24)
    if existing:
        logger.info(f"Duplicate bounce for {recipient} (existing ID: {existing['id']}), skipping")
        return None

    # Create record
    record = BounceRecord(
        timestamp=ts,
        source=source,
        event_type=event_type,
        recipient=recipient,
        sender=sender or "",
        subject=subject or "",
        conv_id=conv_id,
        account_id=account_id,
        reason=reason,
        raw_payload=raw_payload,
        expiry_days=expiry_days,
    )

    # Save to database (INSERT OR IGNORE — returns None if dedup_key collision)
    bounce_id = await database.save_bounce(record)
    if bounce_id is None:
        logger.info(f"Duplicate bounce for {recipient} caught by DB constraint, skipping")
        return None
    record.id = bounce_id
    logger.info(f"Saved bounce {bounce_id}: {recipient} ({event_type}) from {source}")

    # Suppress in Postal
    if config.get("notifications", {}).get("enable_suppression", True):
        suppression_type = "Complaint" if event_type == "complaint" else "HardBounce"
        suppressed = await postal_client.add_suppression(
            recipient, suppression_type, f"Bounce Bridge: {source}"
        )
        if suppressed:
            record.postal_suppressed = True
            await database.update_bounce(bounce_id, postal_suppressed=True)

    # Send notification email to sender
    if sender and config.get("notifications", {}).get("enable_sender_notify", True):
        notified = await send_bounce_notification_email(
            recipient=recipient,
            sender=sender,
            subject=subject or "",
            event_type=event_type,
            source=source,
            reason=reason,
            expiry_days=expiry_days,
            timestamp=ts,
        )
        if notified:
            record.sender_notified = True
            await database.update_bounce(bounce_id, sender_notified=True)

    # Add Chatwoot note
    if account_id and conv_id:
        noted = await send_chatwoot_note(
            account_id=account_id,
            conv_id=conv_id,
            recipient=recipient,
            event_type=event_type,
            source=source,
            reason=reason,
            expiry_days=expiry_days,
            timestamp=ts,
        )
        if noted:
            record.chatwoot_notified = True
            await database.update_bounce(bounce_id, chatwoot_notified=True)

    return record
