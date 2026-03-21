import httpx
import logging
from typing import Optional
from datetime import datetime, timedelta

from ..config import get_config

logger = logging.getLogger(__name__)


class PostalClient:
    """Client for Postal API."""

    def __init__(self):
        config = get_config()
        self.api_url = config.get("postal", {}).get("api_url", "https://postal.voltnation.pl")
        self.api_key = config.get("postal", {}).get("api_key", "")

    def _get_headers(self) -> dict:
        return {
            "X-Server-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Host": self.api_url.replace("https://", "").replace("http://", ""),
        }

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def add_suppression(
        self,
        address: str,
        suppression_type: str = "HardBounce",
        reason: str = "Bounce Bridge",
    ) -> bool:
        """
        Add an address to the Postal suppression list.

        Note: Postal's API doesn't have a direct suppression endpoint,
        so we insert directly into the database via the webhook or
        let Postal handle it naturally. This method is for documentation.

        For now, we'll use the internal database approach.
        """
        if not self.is_configured():
            logger.warning("Postal not configured, skipping suppression")
            return False

        # Postal doesn't have a public suppression API endpoint
        # Suppressions are managed internally when bounces occur
        # We track this in our own database
        logger.info(f"Suppression tracked for {address} ({suppression_type})")
        return True

    async def get_message(self, message_id: int) -> Optional[dict]:
        """Get message details from Postal API."""
        if not self.is_configured():
            return None

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/api/v1/messages/message",
                    headers=self._get_headers(),
                    json={"id": message_id},
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("status") == "success":
                    return data.get("data", {})
        except Exception as e:
            logger.error(f"Failed to get message {message_id}: {e}")

        return None

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        from_addr: Optional[str] = None,
    ) -> bool:
        """Send an email via Postal API."""
        if not self.is_configured():
            logger.warning("Postal not configured, skipping email send")
            return False

        config = get_config()
        sender = from_addr or config.get("notifications", {}).get(
            "sender_email", "bounce-bridge@fiszu.com"
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/api/v1/send/message",
                    headers=self._get_headers(),
                    json={
                        "to": [to],
                        "from": sender,
                        "subject": subject,
                        "plain_body": body,
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("status") == "success":
                    logger.info(f"Sent notification email to {to}")
                    return True
                else:
                    logger.error(f"Failed to send email: {data}")
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")

        return False


postal_client = PostalClient()
