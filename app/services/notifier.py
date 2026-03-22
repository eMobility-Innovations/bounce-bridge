import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from ..config import get_config
from .postal import postal_client
from .chatwoot import chatwoot_client

logger = logging.getLogger(__name__)

# Europe/Warsaw timezone (CET/CEST)
CET = timezone(timedelta(hours=1))
CEST = timezone(timedelta(hours=2))


def format_human_time(timestamp: Optional[str] = None) -> str:
    """
    Format timestamp in human-readable format with timezone.
    Example: "21 Mar 2026, 20:13 CET"
    """
    try:
        if timestamp:
            # Parse ISO format timestamp
            if "T" in timestamp:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(timestamp)
        else:
            dt = datetime.now(timezone.utc)

        # Convert to CET (simplified - not handling DST perfectly)
        # March 21 is after DST switch, so use CEST (+2)
        if dt.month >= 3 and dt.month <= 10:
            local_tz = CEST
            tz_name = "CEST"
        else:
            local_tz = CET
            tz_name = "CET"

        local_dt = dt.astimezone(local_tz)
        return local_dt.strftime(f"%d %b %Y, %H:%M {tz_name}")
    except Exception:
        # Fallback to original if parsing fails
        return timestamp or datetime.now().strftime("%d %b %Y, %H:%M")


def get_human_readable_type(event_type: str) -> str:
    """Convert event type to human readable format."""
    mapping = {
        "hard_bounce": "Hard Bounce",
        "soft_bounce": "Soft Bounce",
        "complaint": "Complaint",
        "transient": "Temporary Issue",
    }
    return mapping.get(event_type, event_type.replace("_", " ").title())


def get_human_explanation(event_type: str, reason: str) -> str:
    """Generate human readable explanation for the bounce."""
    if event_type == "complaint":
        return "The recipient marked this email as spam. Future emails to this address will be blocked."
    elif event_type == "hard_bounce":
        return "The recipient's email address does not exist or is permanently unreachable. Future emails will be blocked."
    elif event_type == "soft_bounce":
        return "Temporary delivery issue (mailbox full, server busy). The address is temporarily suppressed."
    else:
        return f"Delivery failed: {reason[:100] if reason else 'Unknown reason'}"


async def send_bounce_notification_email(
    recipient: str,
    sender: str,
    subject: str,
    event_type: str,
    source: str,
    reason: str,
    expiry_days: int,
    timestamp: Optional[str] = None,
) -> bool:
    """Send bounce notification email to original sender."""
    config = get_config()
    if not config.get("notifications", {}).get("enable_sender_notify", True):
        logger.info("Sender notification disabled, skipping")
        return False

    human_time = format_human_time(timestamp)
    human_type = get_human_readable_type(event_type)

    email_body = f"""Email Delivery Failed

Your email could not be delivered to: {recipient}

Original Subject: {subject or "(No subject)"}
Status: {human_type}
Time: {human_time}
Detection Source: {source.upper()}

Reason:
{reason or "No additional details available."}

Action Taken:
The recipient address has been added to the suppression list for {expiry_days} days.
Emails to this address will be blocked during this period to protect your sender reputation.

---
This is an automated message from Bounce Bridge.
"""

    return await postal_client.send_email(
        to=sender,
        subject=f"Delivery failed: {subject or '(No subject)'}",
        body=email_body,
    )


async def send_chatwoot_note(
    account_id: str,
    conv_id: str,
    recipient: str,
    event_type: str,
    source: str,
    reason: str,
    expiry_days: int,
    timestamp: Optional[str] = None,
) -> bool:
    """Send private note to Chatwoot conversation."""
    config = get_config()
    if not config.get("notifications", {}).get("enable_chatwoot_note", True):
        logger.info("Chatwoot notification disabled, skipping")
        return False

    if not chatwoot_client.is_configured():
        logger.warning("Chatwoot not configured, skipping note")
        return False

    # Get assigned agent mention handle
    mention = await chatwoot_client.get_assignee_mention(account_id, conv_id)
    if not mention:
        mention = "@team"

    human_time = format_human_time(timestamp)
    human_type = get_human_readable_type(event_type)
    explanation = get_human_explanation(event_type, reason)

    note_content = f"""🚨 Email Delivery Issue

Recipient: {recipient}
Status: {human_type}
Source: {source.upper()}
Time: {human_time}

Reason:
{reason or "No details available."}

Action: Address suppressed for {expiry_days} days

{mention} please review — {explanation}"""

    return await chatwoot_client.add_private_note(account_id, conv_id, note_content)


def _suppression_explanation(supp_type: str, reason: str, keep_until_str: str) -> str:
    """Build explanation block based on suppression type."""
    if supp_type == "Complaint":
        return (
            "**Complaint:** This recipient previously marked one of our "
            "emails as spam. Sending further emails risks damaging "
            "our sender reputation."
        )
    elif supp_type == "HardBounce":
        return (
            "**Hard Bounce:** A previous email to this address was permanently "
            "rejected by their email server. The address may not exist, "
            "may be disabled, or their mail server may be blocking us.\n"
            f"Original reason: {reason or 'Unknown'}"
        )
    else:
        return (
            "**Temporary Issue:** A previous email bounced due to a "
            f"temporary problem (e.g. full mailbox). Sending is paused until {keep_until_str}."
        )


async def send_held_chatwoot_note(
    account_id: str,
    conv_id: str,
    recipient: str,
    suppression: dict,
) -> bool:
    """Send private Chatwoot note when an email is blocked due to suppression."""
    config = get_config()
    if not config.get("notifications", {}).get("enable_chatwoot_note", True):
        return False
    if not chatwoot_client.is_configured():
        return False

    from datetime import datetime as dt

    supp_type = suppression.get("type", "HardBounce")
    reason = suppression.get("reason", "")
    since_ts = suppression.get("timestamp", 0)
    until_ts = suppression.get("keep_until", 0)

    since_str = format_human_time(dt.fromtimestamp(since_ts, tz=timezone.utc).isoformat()) if since_ts else "Unknown"
    until_str = format_human_time(dt.fromtimestamp(until_ts, tz=timezone.utc).isoformat()) if until_ts else "Unknown"

    explanation = _suppression_explanation(supp_type, reason, until_str)

    mention = await chatwoot_client.get_assignee_mention(account_id, conv_id)
    if not mention:
        mention = "@team"

    note = f"""\u26d4 **Email Not Delivered — Recipient Suppressed**

This email was **NOT sent** to `{recipient}` because their address is on our suppression list.

**Status:** {supp_type}
**Suppressed since:** {since_str}
**Suppressed until:** {until_str}

{explanation}

\u26a0\ufe0f We recommend contacting this customer directly by phone instead of email.

{mention}"""

    return await chatwoot_client.add_private_note(account_id, conv_id, note)


async def send_held_sender_email(
    recipient: str,
    sender: str,
    subject: str,
    suppression: Optional[dict] = None,
) -> bool:
    """Send notification email to original sender when their email was held (suppressed)."""
    from datetime import datetime as dt

    supp_type = suppression.get("type", "Unknown") if suppression else "Unknown"
    reason = suppression.get("reason", "") if suppression else ""
    until_ts = suppression.get("keep_until", 0) if suppression else 0
    until_str = format_human_time(dt.fromtimestamp(until_ts, tz=timezone.utc).isoformat()) if until_ts else "Unknown"

    if "complaint" in reason.lower():
        explanation = "This recipient previously marked our email as spam."
    elif "bounce" in reason.lower() or "hard" in reason.lower():
        explanation = "A previous email to this address was permanently rejected. The address may not exist or may be disabled."
    else:
        explanation = "This address has been suppressed due to delivery issues."

    body = f"""Email Not Delivered — Recipient Suppressed

Your email could not be delivered to: {recipient}

Original Subject: {subject or "(No subject)"}

Reason:
{explanation}
{f"Details: {reason}" if reason else ""}

This address is suppressed until: {until_str}

We recommend contacting this customer directly by phone instead of email.

---
This is an automated message from Bounce Bridge.
"""

    return await postal_client.send_email(
        to=sender,
        subject=f"Not delivered — {recipient} is suppressed",
        body=body,
    )
