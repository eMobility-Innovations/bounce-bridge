import os
import secrets
import logging
from typing import Optional
from functools import wraps

from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware

from .config import get_config

logger = logging.getLogger(__name__)

# OAuth client
oauth = OAuth()

# Keycloak configuration
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://auth.fiszu.com")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "fiszu")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "bounce-bridge")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32))

# OIDC endpoints
OIDC_BASE = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"
OIDC_CONFIG = {
    "client_id": KEYCLOAK_CLIENT_ID,
    "client_secret": KEYCLOAK_CLIENT_SECRET,
    "server_metadata_url": f"{OIDC_BASE}/.well-known/openid-configuration",
    "client_kwargs": {"scope": "openid email profile"},
}


def setup_oauth(app):
    """Setup OAuth and session middleware."""
    # Add session middleware
    app.add_middleware(
        SessionMiddleware,
        secret_key=SESSION_SECRET,
        session_cookie="bounce_bridge_session",
        max_age=86400,  # 24 hours
        same_site="lax",
        https_only=True,
    )

    # Register Keycloak OAuth
    if KEYCLOAK_CLIENT_SECRET:
        oauth.register(name="keycloak", **OIDC_CONFIG)
        logger.info("Keycloak OIDC configured")
    else:
        logger.warning("Keycloak client secret not configured, SSO disabled")


def is_authenticated(request: Request) -> bool:
    """Check if user is authenticated."""
    return "user" in request.session


def get_current_user(request: Request) -> Optional[dict]:
    """Get current user from session."""
    return request.session.get("user")


def is_user_allowed(request: Request) -> bool:
    """Check if authenticated user is in allowed list."""
    user = get_current_user(request)
    if not user:
        return False

    config = get_config()
    allowed_users = config.get("access", {}).get("allowed_users", ["sysadmin", "Dev"])

    username = user.get("preferred_username", "")
    groups = user.get("groups", [])

    # Check username
    if username in allowed_users:
        return True

    # Check groups
    for group in groups:
        # Groups might come as /groupname or groupname
        group_name = group.lstrip("/")
        if group_name in allowed_users:
            return True

    return False


async def require_auth(request: Request):
    """
    Dependency to require authentication.
    Returns user if authenticated and allowed, otherwise raises exception.
    """
    if not KEYCLOAK_CLIENT_SECRET:
        # SSO not configured, allow access
        return None

    if not is_authenticated(request):
        # Redirect to login
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})

    if not is_user_allowed(request):
        # User authenticated but not allowed
        raise HTTPException(status_code=403, detail="Access denied")

    return get_current_user(request)
