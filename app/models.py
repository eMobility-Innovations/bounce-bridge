from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class PostfixBounce(BaseModel):
    """Postfix DSN bounce notification."""
    from_addr: str
    to: str
    subject: Optional[str] = ""
    dsn: str
    status: str
    reason: str
    relay: Optional[str] = ""
    timestamp: Optional[str] = None

    class Config:
        populate_by_name = True

    def __init__(self, **data):
        # Handle 'from' field mapping to 'from_addr'
        if 'from' in data:
            data['from_addr'] = data.pop('from')
        super().__init__(**data)


class BounceRecord(BaseModel):
    """Database record for a bounce event."""
    id: Optional[int] = None
    timestamp: str
    source: str  # ses, postal, postfix
    event_type: str  # hard_bounce, soft_bounce, complaint
    recipient: str
    sender: Optional[str] = ""
    subject: Optional[str] = ""
    conv_id: Optional[str] = None
    account_id: Optional[str] = None
    chatwoot_notified: bool = False
    postal_suppressed: bool = False
    sender_notified: bool = False
    reason: str = ""
    raw_payload: Optional[str] = None
    expiry_days: int = 30


class SettingsUpdate(BaseModel):
    """Settings update from UI."""
    allowed_users: str = ""
    postal_api_key: str = ""
    chatwoot_api_token: str = ""
    sender_email: str = ""
    enable_suppression: bool = True
    enable_sender_notify: bool = True
    enable_chatwoot_note: bool = True


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    postal_configured: bool
    chatwoot_configured: bool
    database_ok: bool
