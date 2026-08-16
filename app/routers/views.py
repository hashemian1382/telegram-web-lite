"""HTML pages and lightweight operational endpoints."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import __version__
from app.core.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request) -> Response:
    if request.session.get("user_id"):
        return templates.TemplateResponse(request, "index.html")
    return templates.TemplateResponse(request, "landing.html")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    # Already signed in → skip the login form entirely.
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html")


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness probe for uptime checks / container orchestrators."""
    return {"status": "ok", "version": __version__}
