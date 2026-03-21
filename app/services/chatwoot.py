import httpx
import logging
from typing import Optional

from ..config import get_config

logger = logging.getLogger(__name__)


class ChatwootClient:
    """Client for Chatwoot API."""

    def __init__(self):
        config = get_config()
        self.api_url = config.get("chatwoot", {}).get("api_url", "https://chatwoot.fiszu.com")
        self.api_token = config.get("chatwoot", {}).get("api_token", "")

    def _get_headers(self) -> dict:
        return {
            "api_access_token": self.api_token,
            "Content-Type": "application/json",
        }

    def is_configured(self) -> bool:
        return bool(self.api_token)

    async def get_conversation(self, account_id: str, conv_id: str) -> Optional[dict]:
        """Get conversation details including assignee."""
        if not self.is_configured():
            return None

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_url}/api/v1/accounts/{account_id}/conversations/{conv_id}",
                    headers=self._get_headers(),
                    timeout=10.0,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get conversation {account_id}:{conv_id}: {e}")

        return None

    async def get_assignee_name(self, account_id: str, conv_id: str) -> Optional[str]:
        """Get the name of the assigned agent for a conversation."""
        conv = await self.get_conversation(account_id, conv_id)
        if conv:
            assignee = conv.get("meta", {}).get("assignee")
            if assignee:
                return assignee.get("name")
        return None

    async def add_private_note(
        self,
        account_id: str,
        conv_id: str,
        content: str,
    ) -> bool:
        """Add a private note to a conversation."""
        if not self.is_configured():
            logger.warning("Chatwoot not configured, skipping private note")
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/api/v1/accounts/{account_id}/conversations/{conv_id}/messages",
                    headers=self._get_headers(),
                    json={
                        "content": content,
                        "message_type": "activity",
                        "private": True,
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                logger.info(f"Added private note to conversation {account_id}:{conv_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to add private note: {e}")

        return False


chatwoot_client = ChatwootClient()
