# ✈️ Telegram Web Lite

A fast, minimal, and lightweight Telegram web client built for speed and simplicity.

FastAPI + Telethon on the backend, server-rendered Jinja2 + Tailwind CSS + vanilla
JS on the frontend — no build step required.

## Features

- **Web accounts** — register / sign in with signed HttpOnly session cookies,
  passwords hashed with Argon2id (automatic re-hash on login)
- **Telegram linking** — full login flow: phone → confirmation code → optional
  2FA password, via Telethon
- **Portable sessions** — Telegram sessions stored as `StringSession` in the
  database; no `.session` files, survives restarts and redeploys
- **Curated chat workspace** — you only see what YOU add: drop any @username or
  numeric Telegram ID into the app and it stays in your personal list, persisted
  in the database (never the whole dialogs dump)
- **Messaging** — read the last 20 messages of an added chat and send new ones;
  incoming messages appear automatically (incremental refresh every 2 s)
- **Photos & files** — send photos/files with captions; photo previews right in
  the bubbles, full files stream to your browser straight from Telegram
  (nothing buffered on the server)
- **Flexible database** — SQLite out of the box, PostgreSQL-ready (Neon, Supabase…)
- **Clean API** — typed schemas, proper HTTP status codes, interactive docs at `/docs`

## Quickstart

```bash
git clone https://github.com/hashemian1382/telegram-web-lite
cd telegram-web-lite

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env   # then edit SECRET_KEY and Telegram credentials
python -m app.main
```

Open <http://127.0.0.1:8000> — create an account, sign in, then link your Telegram
number from the dashboard.

> Get your Telegram API credentials at <https://my.telegram.org/apps> (free).
> Each user may alternatively provide their own `api_id` / `api_hash`.

## Configuration (`.env`)

| Variable            | Default                  | Description                                   |
|---------------------|--------------------------|-----------------------------------------------|
| `SECRET_KEY`        | `change-me-in-production`| Signs session cookies — **set in production** |
| `DEBUG`             | `True`                   | Auto-reload + verbose logging                 |
| `HOST` / `PORT`     | `127.0.0.1` / `8000`     | Bind address for `python -m app.main`         |
| `DATABASE_URL`      | `sqlite:///./sqlite.db`  | e.g. `postgresql://…?sslmode=require` (Neon)  |
| `TELEGRAM_API_ID`   | `0`                      | Global fallback Telegram `api_id`             |
| `TELEGRAM_API_HASH` | `""`                     | Global fallback Telegram `api_hash`           |

## API overview

| Method | Endpoint                    | Description                              |
|--------|-----------------------------|------------------------------------------|
| POST   | `/api/auth/register`        | Create a web account                     |
| POST   | `/api/auth/login`           | Sign in (sets session cookie)            |
| POST   | `/api/auth/logout`          | Sign out                                 |
| GET    | `/api/auth/me`              | Current account info                     |
| POST   | `/api/auth/telegram/send-code`   | Request Telegram login code         |
| POST   | `/api/auth/telegram/verify-code` | Verify code / 2FA, stores session   |
| GET    | `/api/chats/`               | List MY added chats (from the database)  |
| POST   | `/api/chats/`               | Add a chat by @username / numeric ID     |
| DELETE | `/api/chats/{id}`           | Remove a chat from my list               |
| GET    | `/api/chats/{id}/messages`  | Last 20 messages (`?after_id=N` → only newer) |
| POST   | `/api/chats/{id}/messages`  | Send a message to an added chat          |
| POST   | `/api/chats/{id}/files`     | Upload a photo/file (multipart, ≤ 50 MB) |
| GET    | `/api/chats/{id}/messages/{mid}/download` | Stream/download media (`?thumb=1` preview) |
| GET    | `/healthz`                  | Liveness probe                           |

## Project structure

```
telegram-web-lite/
├── app/
│   ├── main.py             # App factory, lifespan, middleware, error handlers
│   ├── config.py           # pydantic-settings configuration (.env)
│   ├── core/
│   │   ├── database.py     # SQLAlchemy 2.0 engine/session/Base
│   │   ├── security.py     # Argon2id/bcrypt password hashing (pwdlib)
│   │   ├── telegram.py     # Telethon client manager + error mapping
│   │   └── templating.py   # Shared Jinja2 environment
│   ├── models/             # User + AddedChat ORM models (typed, SA 2.0 style)
│   ├── schemas/            # Request/response models (Pydantic v2)
│   ├── routers/            # views / auth / chats / shared dependencies
│   ├── static/             # css + vanilla js
│   └── templates/          # base / login / index (Jinja2 + Tailwind)
├── sessions/               # Reserved for runtime artefacts (git-ignored)
├── requirements.txt
├── .env.example
└── CHANGELOG.md
```

## Notes

- Requires **Python 3.11+** (tested on 3.13).
- For production: set a strong `SECRET_KEY`, set `DEBUG=False`, serve behind
  TLS (e.g. via a reverse proxy) and consider `https_only=True` on the session
  cookie in `app/main.py`.
- Database schema is created automatically on startup (`create_all`). For
  evolving schemas, adopt Alembic migrations.
