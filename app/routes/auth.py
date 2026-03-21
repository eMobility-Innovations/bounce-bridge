"""Authentication routes for Keycloak OIDC."""
import logging
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from ..auth import oauth, is_authenticated, get_current_user, is_user_allowed, KEYCLOAK_CLIENT_SECRET
from ..config import BASE_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/login")
async def login(request: Request):
    """Redirect to Keycloak login."""
    if not KEYCLOAK_CLIENT_SECRET:
        return RedirectResponse(url="/")

    redirect_uri = str(request.url_for("auth_callback"))
    return await oauth.keycloak.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def auth_callback(request: Request):
    """Handle Keycloak callback."""
    if not KEYCLOAK_CLIENT_SECRET:
        return RedirectResponse(url="/")

    try:
        token = await oauth.keycloak.authorize_access_token(request)
        user_info = token.get("userinfo", {})

        # Store user in session
        request.session["user"] = {
            "sub": user_info.get("sub"),
            "preferred_username": user_info.get("preferred_username"),
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            "groups": user_info.get("groups", []),
        }

        logger.info(f"User logged in: {user_info.get('preferred_username')}")

        # Check if user is allowed
        if not is_user_allowed(request):
            return RedirectResponse(url="/auth/forbidden")

        return RedirectResponse(url="/")
    except Exception as e:
        logger.error(f"Auth callback error: {e}")
        return RedirectResponse(url="/auth/error")


@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to Keycloak logout."""
    request.session.clear()

    if not KEYCLOAK_CLIENT_SECRET:
        return RedirectResponse(url="/")

    # Redirect to Keycloak logout
    from ..auth import KEYCLOAK_URL, KEYCLOAK_REALM
    logout_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/logout"
    return RedirectResponse(url=logout_url)


@router.get("/forbidden", response_class=HTMLResponse)
async def forbidden(request: Request):
    """Show 403 forbidden page."""
    user = get_current_user(request)
    return templates.TemplateResponse(
        "403.html",
        {
            "request": request,
            "user": user,
        },
        status_code=403,
    )


@router.get("/error", response_class=HTMLResponse)
async def auth_error(request: Request):
    """Show auth error page."""
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "message": "Authentication failed. Please try again.",
        },
    )
