# Changelog

## [1.1.0] — 2026-08-14 — Refactor & dependency refresh

### Fixed
- **HTTP 500 on all HTML pages**: `TemplateResponse(name, context)` used the
  legacy Starlette signature which was removed in Starlette 1.x; switched to
  `TemplateResponse(request, name)` (compatible with all supported versions).
- `datetime.utcnow()` (deprecated since Python 3.12) → timezone-aware
  `datetime.now(timezone.utc)`.
- `sqlalchemy.ext.declarative.declarative_base` (legacy) → SQLAlchemy 2.0
  `DeclarativeBase` with fully typed `Mapped`/`mapped_column` models.
- Deprecated pydantic `class Config` → `SettingsConfigDict`.
- Unused imports (`os`, dangling `Depends`/`get_db` in routers) and the unused
  `templates` instance in `main.py` removed; paths are now absolute
  (`Path`-based) so the app runs from any working directory.
- Stale-connection failures on serverless Postgres (e.g. Neon) via
  `pool_pre_ping=True`.

### Changed
- **Dependencies updated to the August 2026 release set** (FastAPI 0.141,
  Starlette 1.6, Telethon 1.44, SQLAlchemy 2.0.52, Pydantic 2.13,
  python-multipart 0.0.32 — includes security fixes).
- **passlib → pwdlib**: passlib is unmaintained since 2020 and breaks with
  modern bcrypt; passwords now hashed with Argon2id (bcrypt fallback) with
  transparent re-hash on login.
- Settings parsed once via `lru_cache`; unused `SECRET_KEY` default triggers a
  startup warning.

### Added
- Working account system: register / login / logout / me with signed HttpOnly
  session cookies (Starlette `SessionMiddleware`).
- Real Telegram linking flow: `send-code` → `verify-code` (incl. 2FA password
  step) using Telethon `StringSession` stored per user in the database.
- `/api/chats/` returns the user's real dialogs once Telegram is linked.
- Proper request validation (username/phone/code patterns, password length)
  and consistent HTTP error responses (`TelegramAPIError` → JSON `detail`).
- `/healthz` liveness endpoint; structured logging.
- Functional frontend: login/register tabs, Telegram link card (phone → code →
  2FA), chat list rendering, busy states and alert messages — all vanilla JS.
- Application `lifespan` handler (replaces import-time side effects).
