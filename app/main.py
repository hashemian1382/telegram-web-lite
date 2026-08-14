"""Telegram Web Lite — application entry point."""
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.config import settings
from app.core.database import Base, engine
from app.core.telegram import TelegramAPIError, telegram_manager
from app.routers import auth, chats, views

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    settings.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    await telegram_manager.start()  # idle-connection reaper
    if settings.SECRET_KEY == "change-me-in-production":
        logger.warning("SECRET_KEY is the built-in default — set it in .env before deploying!")
    logger.info("Telegram Web Lite v%s started (debug=%s)", __version__, settings.DEBUG)
    yield
    # Shutdown — close pooled Telegram connections and return engine
    # connections to the pool automatically.
    await telegram_manager.close()


app = FastAPI(
    title="Telegram Web Lite",
    description="A fast, minimal, and lightweight Telegram web client.",
    version=__version__,
    lifespan=lifespan,
)

# Signed, HttpOnly session cookie for the web account login.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie="twl_session",
    same_site="lax",
    https_only=False,  # set True behind TLS in production
)

app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


@app.exception_handler(TelegramAPIError)
async def telegram_error_handler(request: Request, exc: TelegramAPIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


app.include_router(views.router)
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(chats.router, prefix="/api/chats", tags=["Chats"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
