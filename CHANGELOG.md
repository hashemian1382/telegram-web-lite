# Changelog

## [1.5.0] — 2026-08-14 — Latency, duplicate-send fixes & photo sending

### Fixed — latency (root cause)
- **Persistent connection pool** (`app/core/telegram.py`): the app no longer
  opens a brand-new Telegram connection and tears it down for every request.
  Each operation previously paid for a TCP + TLS handshake plus several RPC
  round-trips (and an extra `GetMe`), which is why a single send or fetch could
  take seconds. Connections are now reused per user, dropping the steady-state
  cost to a single RPC on an already-open socket. Idle connections are reaped
  in the background and the whole pool closes cleanly on shutdown.
- Invalid/revoked sessions now also evict their pooled connection.

### Fixed — duplicate sends & duplicate bubbles
- **Send guard**: a single `sendInFlight` flag plus disabled controls now makes
  it impossible for repeated Enter presses / button clicks to fire the same
  message or upload twice (this was the "message sent several times after a
  delay" bug — the slow network window let a second Enter slip through).
- **Optimistic rendering**: messages appear instantly as a "sending" bubble and
  are reconciled with the server reply, so there is no perceived dead time that
  tempts a re-press.
- **De-duplication**: a `knownIds` set prevents the auto-refresh poll from
  re-rendering a message that was just sent/rendered.
- **Non-overlapping polling**: auto-refresh is now self-scheduling (the next
  tick only starts after the previous finishes), pauses on hidden tabs, and
  discards results if you switched chats mid-request.

### Added — send photos as photos (and files)
- The upload endpoint now accepts an `as_photo` flag and spools the upload to a
  temp file whose name/extension lets Telethon detect the correct type. Images
  are sent as **photos** by default (they previously always went as documents
  because the temp file had no extension, and the original file name was lost).
- A **"Photo / File" segmented toggle** appears in the composer for image
  attachments, so an image can be sent either inline as a photo or as a
  document. Non-image files are unchanged (videos/audio keep their natural
  types). Original file names are now preserved via an explicit
  `DocumentAttributeFilename`.

### Changed
- Frontend `app.js` refactored: clearer module-style sections, a shared
  `appendMessage` renderer with a pending state, and explicit guards/tokens
  against stale async results.

## [1.4.0] — 2026-08-14 — Frontend redesign

Purely a presentation-layer release: **no Python, API, database, or behaviour
changes.** Every endpoint, payload, and flow is identical to 1.3.0 — only
`templates/`, `static/css/`, and `static/js/` were touched.

### Added
- **Design system** (`static/css/style.css`) — CSS custom properties for colour,
  radii, shadows, motion and layout; light + dark palettes.
- **Dark mode** — header toggle, persisted in `localStorage`, defaults to the OS
  preference, applied pre-paint via an inline script (no flash of wrong theme).
- **Inline SVG icon sprite** in `base.html` — replaces all emoji-as-icons.
- **Auth screens** — animated ambient background, sliding segmented tabs,
  floating labels, show/hide password, live password-strength meter, and
  auto-fill of the username after registering.
- **Telegram linking** — 3-step stepper (phone → code → done), phone recap with
  a "Change" action, spaced confirmation-code field, styled disclosure for
  custom `api_id` / `api_hash`.
- **Chat view** — grouped consecutive bubbles with tails, Today/Yesterday date
  dividers, read ticks, chat wallpaper pattern, and a photo lightbox (Esc/click
  to close).
- **Productivity** — chat search box, `Enter` to send / `Shift+Enter` for a
  newline, auto-growing composer textarea, drag-&-drop and paste-to-attach,
  client-side 50 MB pre-check, toast notifications, and skeleton loaders.
- **Responsive** — off-canvas sidebar drawer with backdrop on mobile.
- **Accessibility** — semantic roles/ARIA on tabs, live regions for messages and
  toasts, keyboard-navigable chat list, visible focus rings, and full
  `prefers-reduced-motion` support.

### Changed
- **Removed the `cdn.tailwindcss.com` dependency.** The CDN build is explicitly
  not intended for production and caused a flash of unstyled content. Styling is
  now a self-contained stylesheet, so the UI has **no runtime network
  dependencies** and renders offline.
- Avatar colours now use an FNV-1a hash, so sequential peer IDs get visibly
  distinct hues instead of near-identical ones.
- Message composer is a `<textarea>` (was `<input>`) to support multi-line text.
- Errors surface as non-blocking toasts on the dashboard; the auth page keeps an
  inline alert with a shake animation.

### Fixed
- Oversized download glyph in file cards squashing long filenames.
- Account avatar disappearing from the mobile header.

## [1.3.0] — 2026-08-14 — Photos, files & live refresh

### Added
- **Photo & file sending**: `POST /api/chats/{id}/files` (multipart, optional
  caption). Uploads spool to disk in 1 MB chunks (flat memory), capped at
  50 MB (413 above); Telethon streams the file to Telegram in chunks. Images
  go as Telegram photos, everything else as documents.
- **Media in messages**: bubbles carry media metadata (`media_type`,
  `media_name`, `media_size`, `mime_type`); captions shown as message text.
- **Media download**: `GET /api/chats/{id}/messages/{mid}/download` streams
  the file straight from Telegram to the browser — the client connection stays
  open for the generator's lifetime, so even large files never sit in server
  memory. Images/videos/audio/PDF render inline, other types download as
  attachments, unicode filenames via RFC 5987. `?thumb=1` returns a small
  photo preview for chat bubbles.
- **Live auto-refresh**: messages poll `GET .../messages?after_id=N`
  (Telethon `min_id`) every 2 seconds — only *new* messages transfer, they
  append in place, and the view only auto-scrolls when you're already at the
  bottom. Polling pauses on hidden tabs and stops cleanly if the Telegram
  session dies.
- Composer 📎 attach button with a pending-file chip (name + size + remove).

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
