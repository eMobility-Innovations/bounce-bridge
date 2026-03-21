import logging
from datetime import datetime
from typing import Optional

from ..config import get_config
from .postal import postal_client
from .chatwoot import chatwoot_client

logger = logging.getLogger(__name__)


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

    ts = timestamp or datetime.utcnow().isoformat()
    human_type = get_human_readable_type(event_type)

    email_body = f"""Email Delivery Failed

Your email could not be delivered to: {recipient}

Original Subject: {subject or "(No subject)"}
Status: {human_type}
Time: {ts}
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

    # Get assigned agent
    assignee_name = await chatwoot_client.get_assignee_name(account_id, conv_id)
    mention = f"@{assignee_name}" if assignee_name else "@team"

    ts = timestamp or datetime.utcnow().isoformat()
    human_type = get_human_readable_type(event_type)
    explanation = get_human_explanation(event_type, reason)

    note_content = f"""🚨 Email Delivery Issue

Recipient: {recipient}
Status: {human_type}
Source: {source.upper()}
Time: {ts}

Reason:
{reason or "No details available."}

Action: Address suppressed for {expiry_days} days

{mention} please review — {explanation}"""

    return await chatwoot_client.add_private_note(account_id, conv_id, note_content)
