import httpx
import logging
from typing import Optional
from datetime import datetime, timedelta

from ..config import get_config

logger = logging.getLogger(__name__)


class PostalClient:
    """Client for Postal API with dynamic config reload."""

    def _get_config(self) -> tuple:
        """Get current config values (reloads on each call)."""
        config = get_config()
        api_url = config.get("postal", {}).get("api_url", "https://postal.voltnation.pl")
        api_key = config.get("postal", {}).get("api_key", "")
        return api_url, api_key

    def _get_headers(self) -> dict:
        api_url, api_key = self._get_config()
        return {
            "X-Server-API-Key": api_key,
            "Content-Type": "application/json",
            "Host": api_url.replace("https://", "").replace("http://", ""),
        }

    def is_configured(self) -> bool:
        _, api_key = self._get_config()
        return bool(api_key)

    async def add_suppression(
        self,
        address: str,
        suppression_type: str = "HardBounce",
        reason: str = "Bounce Bridge",
    ) -> bool:
        """
        Add an address to the Postal suppression list.

        Valid types: HardBounce, Complaint
        For soft bounces, use HardBounce with shorter expiry (handled by caller).
        """
        if not self.is_configured():
            logger.warning("Postal not configured, skipping suppression")
            return False

        # Normalize suppression type
        if suppression_type not in ("HardBounce", "Complaint"):
            suppression_type = "HardBounce"

        api_url, _ = self._get_config()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{api_url}/api/v1/suppressions/add",
                    headers=self._get_headers(),
                    json={
                        "address": address,
                        "type": suppression_type,
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("status") == "success":
                    logger.info(f"Added {address} to Postal suppression list ({suppression_type})")
                    return True
                else:
                    logger.error(f"Postal suppression failed: {data}")
        except Exception as e:
            logger.error(f"Failed to add suppression for {address}: {e}")

        return False

    async def get_message(self, message_id: int) -> Optional[dict]:
        """Get message details from Postal API."""
        if not self.is_configured():
            return None

        api_url, _ = self._get_config()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{api_url}/api/v1/messages/message",
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

        api_url, _ = self._get_config()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{api_url}/api/v1/send/message",
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
