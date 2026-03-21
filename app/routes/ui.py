import logging
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import get_config, save_config, load_config, BASE_DIR
from ..models import SettingsUpdate
from .. import database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def check_access(request: Request) -> bool:
    """Check if user has access based on SSO headers."""
    config = get_config()
    allowed_users = config.get("access", {}).get("allowed_users", ["sysadmin", "Dev"])

    # Get user from ForwardAuth headers
    user = request.headers.get("X-Forwarded-User", "")
    groups = request.headers.get("X-Forwarded-Groups", "")

    if not user:
        # No auth header = probably direct access, allow for dev
        return True

    # Check if user or any group is allowed
    user_groups = [g.strip() for g in groups.split(",") if g.strip()]

    for allowed in allowed_users:
        if user == allowed or allowed in user_groups:
            return True

    return False


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard showing recent bounces."""
    if not check_access(request):
        raise HTTPException(status_code=403, detail="Access denied")

    bounces = await database.get_recent_bounces(100)
    stats = await database.get_stats()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "bounces": bounces,
            "stats": stats,
            "user": request.headers.get("X-Forwarded-User", ""),
        },
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page."""
    if not check_access(request):
        raise HTTPException(status_code=403, detail="Access denied")

    config = get_config()

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "config": config,
            "user": request.headers.get("X-Forwarded-User", ""),
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
    if not check_access(request):
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
