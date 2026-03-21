import os
import time
import logging
from typing import Optional

import httpx
import pymysql

from ..config import get_config

logger = logging.getLogger(__name__)

# Postal MariaDB connection via SSH tunnel (mariadb-tunnel.service)
# Tunnel: 127.0.0.1:3307 -> CT200 127.0.0.1:3306
POSTAL_DB_HOST = os.environ.get("POSTAL_DB_HOST", "127.0.0.1")
POSTAL_DB_PORT = int(os.environ.get("POSTAL_DB_PORT", "3307"))
POSTAL_DB_USER = os.environ.get("POSTAL_DB_USER", "root")
POSTAL_DB_PASSWORD = os.environ.get("POSTAL_DB_PASSWORD", "")
POSTAL_DB_NAME = os.environ.get("POSTAL_DB_NAME", "postal-server-1")

# Suppression durations by type (days)
SUPPRESSION_DAYS = {
    "HardBounce": 365,
    "Complaint": 180,
}


def _get_postal_db():
    """Get a connection to Postal's MariaDB."""
    return pymysql.connect(
        host=POSTAL_DB_HOST,
        port=POSTAL_DB_PORT,
        user=POSTAL_DB_USER,
        password=POSTAL_DB_PASSWORD,
        database=POSTAL_DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


class PostalClient:
    """Client for Postal with direct MariaDB suppression management."""

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
        """Add an address to Postal's suppression list via direct MariaDB insert.

        Valid types: HardBounce, Complaint
        """
        if suppression_type not in ("HardBounce", "Complaint"):
            suppression_type = "HardBounce"

        now = time.time()
        days = SUPPRESSION_DAYS.get(suppression_type, 365)
        keep_until = now + (days * 86400)

        try:
            conn = _get_postal_db()
            cursor = conn.cursor()

            # Check if suppression already exists for this address + type
            cursor.execute(
                "SELECT id, keep_until FROM suppressions WHERE address = %s AND type = %s",
                (address, suppression_type),
            )
            existing = cursor.fetchone()

            if existing:
                if keep_until > float(existing["keep_until"]):
                    cursor.execute(
                        "UPDATE suppressions SET keep_until = %s, reason = %s, timestamp = %s WHERE id = %s",
                        (keep_until, reason, now, existing["id"]),
                    )
                    conn.commit()
                    logger.info(f"Updated suppression for {address} ({suppression_type}), extended to {days}d")
                else:
                    logger.info(f"Suppression already exists for {address} ({suppression_type}), no update needed")
            else:
                cursor.execute(
                    "INSERT INTO suppressions (type, address, reason, timestamp, keep_until) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (suppression_type, address, reason, now, keep_until),
                )
                conn.commit()
                logger.info(f"Added suppression for {address} ({suppression_type}) for {days} days")

            conn.close()
            return True

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
