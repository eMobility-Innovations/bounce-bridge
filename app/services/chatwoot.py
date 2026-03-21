import httpx
import logging
from typing import Optional

from ..config import get_config

logger = logging.getLogger(__name__)


class ChatwootClient:
    """Client for Chatwoot API with dynamic config reload."""

    def _get_config(self) -> tuple:
        """Get current config values (reloads on each call)."""
        config = get_config()
        api_url = config.get("chatwoot", {}).get("api_url", "https://chatwoot.fiszu.com")
        api_token = config.get("chatwoot", {}).get("api_token", "")
        return api_url, api_token

    def _get_headers(self) -> dict:
        _, api_token = self._get_config()
        return {
            "api_access_token": api_token,
            "Content-Type": "application/json",
        }

    def is_configured(self) -> bool:
        _, api_token = self._get_config()
        return bool(api_token)

    async def get_conversation(self, account_id: str, conv_id: str) -> Optional[dict]:
        """Get conversation details including assignee."""
        if not self.is_configured():
            return None

        api_url, _ = self._get_config()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{api_url}/api/v1/accounts/{account_id}/conversations/{conv_id}",
                    headers=self._get_headers(),
                    timeout=10.0,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get conversation {account_id}:{conv_id}: {e}")

        return None

    async def get_assignee_mention(self, account_id: str, conv_id: str) -> Optional[str]:
        """
        Get the mention handle of the assigned agent for a conversation.
        Returns @username if available, otherwise None.
        """
        conv = await self.get_conversation(account_id, conv_id)
        if conv:
            assignee = conv.get("meta", {}).get("assignee")
            if assignee:
                # Try username/handle fields first, fall back to email prefix
                username = assignee.get("username") or assignee.get("handle")
                if username:
                    return f"@{username}"
                # If no username, try email prefix as fallback
                email = assignee.get("email", "")
                if email and "@" in email:
                    return f"@{email.split('@')[0]}"
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

        api_url, _ = self._get_config()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{api_url}/api/v1/accounts/{account_id}/conversations/{conv_id}/messages",
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
