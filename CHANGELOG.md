# Changelog

## [1.2.0] — 2026-08-14 — Curated chat workspace

### Changed
- **No more full dialog dump.** The dashboard no longer lists every Telegram
  chat/group/channel. Users see only the peers they explicitly added — an
  empty, clean workspace on first use instead of the whole account.

### Added
- `AddedChat` model + `added_chats` table: user-added peers persisted in the
  database (`peer_id`, `access_hash`, `peer_type`, `username`, `title`) with a
  per-user uniqueness constraint; cascade-deleted with the account.
- `POST /api/chats/` — resolve any @username (works for anyone) or numeric ID
  (people you've interacted with) via Telegram, then save it to the list.
- `DELETE /api/chats/{id}` — remove a chat from the list (Telegram untouched).
- `GET /api/chats/{id}/messages` — exactly the last 20 messages (by design).
- `POST /api/chats/{id}/messages` — send a text message to the added peer.
- Telethon `resolve_peer` / `fetch_messages` / `send_message` built on
  `InputPeer` reconstruction from stored access hashes (StringSession keeps no
  entity cache); blocked-user / write-forbidden errors mapped to clean 403s.
- Redesigned chat UI: sidebar with avatars and usernames, inline add form,
  message bubbles with timestamps, composer, refresh, per-chat delete,
  elegant empty states.

## [1.1.1] — 2026-08-14 — Zero-hassle session persistence

### Fixed
- A corrupted/revoked stored Telegram session could previously surface as a
  raw 500 (unparsable session string) or a dangling 401 that required manual
  DB cleanup.

### Changed
- `GET /api/chats/` now auto-clears an invalid stored session (401 from
  Telegram) and returns `{"telegram_linked": false}` so the UI instantly shows
  the link card again. Transient errors (network, flood-wait, missing API
  credentials) never touch the stored session.
- Server-side page redirects: `/` → `/login` when signed out, `/login` → `/`
  when already signed in — once linked, returning users sign in with just
  username + password and land directly on their chats.

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
