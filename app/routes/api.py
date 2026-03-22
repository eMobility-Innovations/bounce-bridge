import json
import logging
import httpx
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from ..models import PostfixBounce, HealthResponse
from ..services.suppression import process_bounce
from ..services.postal import postal_client
from ..services.chatwoot import chatwoot_client
from ..utils.conv_id import extract_conv_id
from .. import database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["api"])

import re

def _extract_email(value: str) -> str:
    """Extract bare email from 'Name <email>' or plain email string."""
    if not value:
        return ""
    match = re.search(r'<([^>]+)>', value)
    if match:
        return match.group(1).strip()
    return value.strip()


def _is_return_path_token(email: str) -> bool:
    """Check if an email is a Postal return path token, not a human address.
    Matches patterns like fvkuyb@psrp.escooterclinic.co.uk"""
    if not email:
        return True
    return bool(re.match(r'^[a-z0-9]{5,10}@psrp\.', email, re.IGNORECASE))


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    db_ok = await database.check_db()

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version="1.0.0",
        postal_configured=postal_client.is_configured(),
        chatwoot_configured=chatwoot_client.is_configured(),
        database_ok=db_ok,
    )


@router.post("/ses-bounce")
async def ses_bounce(request: Request):
    """
    Receive SES bounce/complaint notification from n8n or direct SNS.

    Expected payload: Full SES SNS JSON as forwarded by n8n.
    Also handles SNS SubscriptionConfirmation requests.
    """
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    # Handle SNS SubscriptionConfirmation
    if payload.get("Type") == "SubscriptionConfirmation":
        subscribe_url = payload.get("SubscribeURL")
        if subscribe_url:
            logger.info(f"Confirming SNS subscription: {subscribe_url}")
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(subscribe_url, timeout=10.0)
                    if response.status_code == 200:
                        logger.info("SNS subscription confirmed successfully")
                        return {"status": "ok", "message": "Subscription confirmed"}
                    else:
                        logger.error(f"SNS confirmation failed: {response.status_code}")
            except Exception as e:
                logger.error(f"SNS confirmation error: {e}")
        return {"status": "ok", "message": "SubscriptionConfirmation handled"}

    logger.info(f"Received SES bounce notification")

    # Parse SES notification
    # SNS wraps the message, n8n may unwrap it
    message = payload
    if isinstance(payload.get("Message"), str):
        message = json.loads(payload["Message"])

    notification_type = message.get("notificationType", message.get("eventType", ""))

    # Early loop detection — skip bounce notifications for our own emails
    mail_data_check = message.get("mail", {})
    source_addr = mail_data_check.get("source", "")
    common_subj = mail_data_check.get("commonHeaders", {}).get("subject", "")
    if source_addr.lower() in ("bounce-bridge@fiszu.com", "noreply-bouncebridge@fiszu.com"):
        logger.info(f"Skipped SES bounce — our own notification email bounced: {source_addr}")
        return {"status": "skipped", "message": "Bounce of own notification email"}
    if common_subj.lower().startswith("delivery failed:"):
        logger.info(f"Skipped SES bounce — bounce notification bounce: {common_subj[:60]}")
        return {"status": "skipped", "message": "Bounce of bounce notification"}

    if notification_type == "Bounce":
        bounce_data = message.get("bounce", {})
        bounce_type = bounce_data.get("bounceType", "Permanent")
        event_type = "hard_bounce" if bounce_type == "Permanent" else "soft_bounce"

        recipients = bounce_data.get("bouncedRecipients", [])
        mail_data = message.get("mail", {})

        # Extract common headers
        headers = {}
        for h in mail_data.get("headers", []):
            headers[h.get("name", "")] = h.get("value", "")

        # Human sender: prefer commonHeaders.from (display name + email),
        # then From header, last resort envelope source (may be return path token)
        common_from = mail_data.get("commonHeaders", {}).get("from", [])
        sender = _extract_email(common_from[0]) if common_from else ""
        if not sender or _is_return_path_token(sender):
            sender = _extract_email(headers.get("From", ""))
        if not sender or _is_return_path_token(sender):
            sender = mail_data.get("source", "")
        subject = headers.get("Subject", "")

        # Extract conversation ID
        conv_info = extract_conv_id(headers=headers)
        account_id = conv_info[0] if conv_info else None
        conv_id = conv_info[1] if conv_info else None

        for recipient in recipients:
            email = recipient.get("emailAddress", "")
            reason = recipient.get("diagnosticCode", bounce_data.get("bounceSubType", ""))

            await process_bounce(
                source="ses",
                event_type=event_type,
                recipient=email,
                sender=sender,
                subject=subject,
                reason=reason,
                account_id=account_id,
                conv_id=conv_id,
                raw_payload=json.dumps(payload),
            )

    elif notification_type == "Complaint":
        complaint_data = message.get("complaint", {})
        recipients = complaint_data.get("complainedRecipients", [])
        mail_data = message.get("mail", {})

        headers = {}
        for h in mail_data.get("headers", []):
            headers[h.get("name", "")] = h.get("value", "")

        # Human sender (same logic as bounce)
        common_from = mail_data.get("commonHeaders", {}).get("from", [])
        sender = _extract_email(common_from[0]) if common_from else ""
        if not sender or _is_return_path_token(sender):
            sender = _extract_email(headers.get("From", ""))
        if not sender or _is_return_path_token(sender):
            sender = mail_data.get("source", "")
        subject = headers.get("Subject", "")

        conv_info = extract_conv_id(headers=headers)
        account_id = conv_info[0] if conv_info else None
        conv_id = conv_info[1] if conv_info else None

        for recipient in recipients:
            email = recipient.get("emailAddress", "")
            reason = complaint_data.get("complaintFeedbackType", "abuse")

            await process_bounce(
                source="ses",
                event_type="complaint",
                recipient=email,
                sender=sender,
                subject=subject,
                reason=f"Complaint: {reason}",
                account_id=account_id,
                conv_id=conv_id,
                raw_payload=json.dumps(payload),
            )

    return {"status": "ok", "message": f"Processed {notification_type}"}


@router.post("/postal-bounce")
async def postal_bounce(request: Request):
    """
    Receive Postal webhook events: MessageBounced, MessageDeliveryFailed, MessageHeld.

    MessageHeld with "suppression" in details triggers a Chatwoot notification
    explaining the recipient is suppressed and the email was NOT sent.
    """
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    event = payload.get("event", "")
    message_data = payload.get("payload", payload)

    logger.info(f"Received Postal webhook: {event}")

    # ── MessageHeld — suppressed recipient notification ──
    if event == "MessageHeld":
        return await _handle_message_held(message_data, payload)

    # ── MessageBounced / MessageDeliveryFailed — bounce processing ──
    if event not in ("MessageBounced", "MessageDeliveryFailed"):
        return {"status": "ignored", "message": f"Event {event} not handled"}

    recipient = message_data.get("rcpt_to", message_data.get("to", ""))
    sender = message_data.get("mail_from", message_data.get("from", ""))
    subject = message_data.get("subject", "")
    message_id = message_data.get("id", message_data.get("message_id"))
    reason = message_data.get("details", message_data.get("output", ""))

    account_id = None
    conv_id = None

    if message_id:
        msg_details = await postal_client.get_message(message_id)
        if msg_details:
            headers = msg_details.get("headers", {})
            html_body = msg_details.get("html_body", "")
            conv_info = extract_conv_id(headers=headers, html_body=html_body)
            if conv_info:
                account_id, conv_id = conv_info
            # Use From header as human sender instead of envelope mail_from
            from_header = _extract_email(headers.get("From", ""))
            if from_header and not _is_return_path_token(from_header):
                sender = from_header

    await process_bounce(
        source="postal",
        event_type="hard_bounce",
        recipient=recipient,
        sender=sender,
        subject=subject,
        reason=reason,
        account_id=account_id,
        conv_id=conv_id,
        raw_payload=json.dumps(payload),
    )

    return {"status": "ok", "message": "Postal bounce processed"}


async def _handle_message_held(message_data: dict, raw_payload: dict):
    """Handle MessageHeld event — notify sender and Chatwoot when recipient is suppressed."""
    from ..services.notifier import send_held_chatwoot_note, send_held_sender_email
    from ..config import get_config

    details = message_data.get("details", message_data.get("output", ""))

    # Only handle suppression holds
    if "suppression" not in details.lower():
        logger.info(f"MessageHeld ignored — not suppression-related: {details[:100]}")
        return {"status": "ignored", "message": "Not suppression-related hold"}

    # MessageHeld payload nests message fields under "message" key
    msg = message_data.get("message", message_data)
    recipient = msg.get("to", msg.get("rcpt_to", ""))
    sender = msg.get("from", msg.get("mail_from", ""))
    subject = msg.get("subject", "")
    message_id = msg.get("id", msg.get("message_id"))

    logger.info(f"MessageHeld — suppressed recipient: {recipient}")

    # Look up suppression record from Postal DB
    suppression = await postal_client.lookup_suppression(recipient)

    # Try to get conv_id from message headers
    account_id = None
    conv_id = None

    if message_id:
        msg_details = await postal_client.get_message(message_id)
        if msg_details:
            headers = msg_details.get("headers", {})
            html_body = msg_details.get("html_body", "")
            conv_info = extract_conv_id(headers=headers, html_body=html_body)
            if conv_info:
                account_id, conv_id = conv_info
            # Use From header for human sender
            from_header = _extract_email(headers.get("From", ""))
            if from_header and not _is_return_path_token(from_header):
                sender = from_header

    supp_type = suppression.get("type", "Unknown") if suppression else "Unknown"
    supp_reason = suppression.get("reason", "") if suppression else ""

    chatwoot_notified = False
    sender_notified = False

    # Send Chatwoot note if we have conv_id
    if account_id and conv_id and suppression:
        chatwoot_notified = await send_held_chatwoot_note(
            account_id=account_id,
            conv_id=conv_id,
            recipient=recipient,
            suppression=suppression,
        )

    # Send notification email to original sender
    config = get_config()
    if sender and not _is_return_path_token(sender) and config.get("notifications", {}).get("enable_sender_notify", True):
        sender_notified = await send_held_sender_email(
            recipient=recipient,
            sender=sender,
            subject=subject,
            suppression=suppression,
        )

    # Save blocked attempt record
    await database.save_blocked_attempt(
        recipient=recipient,
        sender=sender,
        subject=subject,
        reason=f"{supp_type}: {supp_reason}",
        account_id=account_id,
        conv_id=conv_id,
        chatwoot_notified=chatwoot_notified,
        raw_payload=json.dumps(raw_payload),
    )

    return {"status": "ok", "message": f"Held notification processed for {recipient}"}


@router.post("/postfix-bounce")
async def postfix_bounce(request: Request):
    """
    Receive Postfix DSN bounce notification.

    Payload:
    {
        "from": "sender@example.com",
        "to": "recipient@example.com",
        "subject": "...",
        "dsn": "5.1.1",
        "status": "bounced",
        "reason": "full bounce reason text",
        "relay": "mail.example.com",
        "timestamp": "2026-03-21T10:00:00Z"
    }
    """
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    logger.info(f"Received Postfix bounce notification")

    # Parse the bounce
    bounce = PostfixBounce(**payload)

    # Determine event type from DSN code
    dsn = bounce.dsn or ""
    if dsn.startswith("5"):
        event_type = "hard_bounce"
    elif dsn.startswith("4"):
        event_type = "soft_bounce"
    else:
        event_type = "hard_bounce"  # Default to hard

    await process_bounce(
        source="postfix",
        event_type=event_type,
        recipient=bounce.to,
        sender=bounce.from_addr,
        subject=bounce.subject,
        reason=bounce.reason,
        raw_payload=json.dumps(payload),
        timestamp=bounce.timestamp,
    )

    return {"status": "ok", "message": "Postfix bounce processed"}
