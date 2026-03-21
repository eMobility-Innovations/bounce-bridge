import logging
from fastapi import APIRouter, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import get_config, save_config, load_config, BASE_DIR
from ..models import SettingsUpdate
from .. import database
from ..auth import require_auth, get_current_user, is_authenticated, is_user_allowed, KEYCLOAK_CLIENT_SECRET

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard showing recent bounces."""
    # Check auth if SSO is enabled
    if KEYCLOAK_CLIENT_SECRET:
        if not is_authenticated(request):
            return RedirectResponse(url="/auth/login")
        if not is_user_allowed(request):
            return RedirectResponse(url="/auth/forbidden")

    bounces = await database.get_recent_bounces(100)
    stats = await database.get_stats()
    user = get_current_user(request)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "bounces": bounces,
            "stats": stats,
            "user": user.get("preferred_username", "") if user else "",
        },
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page."""
    if KEYCLOAK_CLIENT_SECRET:
        if not is_authenticated(request):
            return RedirectResponse(url="/auth/login")
        if not is_user_allowed(request):
            return RedirectResponse(url="/auth/forbidden")

    config = get_config()
    user = get_current_user(request)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "config": config,
            "user": user.get("preferred_username", "") if user else "",
        },
    )


@router.post("/settings")
async def save_settings(
    request: Request,
    allowed_users: str = Form(""),
    postal_api_key: str = Form(""),
    chatwoot_api_token: str = Form(""),
    sender_email: str = Form(""),
    enable_suppression: bool = Form(False),
    enable_sender_notify: bool = Form(False),
    enable_chatwoot_note: bool = Form(False),
):
    """Save settings from form."""
    if KEYCLOAK_CLIENT_SECRET:
        if not is_authenticated(request):
            return RedirectResponse(url="/auth/login")
        if not is_user_allowed(request):
            raise HTTPException(status_code=403, detail="Access denied")

    config = load_config()

    # Update config
    config.setdefault("access", {})["allowed_users"] = [
        u.strip() for u in allowed_users.split(",") if u.strip()
    ]

    if postal_api_key:
        config.setdefault("postal", {})["api_key"] = postal_api_key

    if chatwoot_api_token:
        config.setdefault("chatwoot", {})["api_token"] = chatwoot_api_token

    config.setdefault("notifications", {})["sender_email"] = sender_email or "bounce-bridge@fiszu.com"
    config["notifications"]["enable_suppression"] = enable_suppression
    config["notifications"]["enable_sender_notify"] = enable_sender_notify
    config["notifications"]["enable_chatwoot_note"] = enable_chatwoot_note

    save_config(config)
    logger.info("Settings saved")

    return RedirectResponse(url="/settings?saved=1", status_code=303)
