# Running production settings locally

This document describes how to run the Civil Defence app with **`config.settings.production`** on your own machine: local Postgres and Redis, **local disk** for static and media (no AWS S3), **WhiteNoise** for collected static files, **Brevo** (via django-anymail) for email, **Gunicorn** as the WSGI server, and **Cloudflare Tunnel** as a **named tunnel / service** exposing the site at **`https://wbcivildefence.org`** (and optionally **`https://www.wbcivildefence.org`** if you use that DNS record).

All commands assume your working directory is the Django project root (the folder that contains `manage.py`):

```bash
cd civil_defence_app
```

---

## 1. Prerequisites

- **Python 3.13** and **uv** (see `pyproject.toml`).
- **PostgreSQL** reachable with a URL you can put in `DATABASE_URL` (default in base settings is `postgres:///civil_defence_app` if that matches your local setup).
- **Redis** for Django’s production cache (`django-redis`). Default URL is `redis://127.0.0.1:6379/0`.
- **Cloudflare Tunnel** (named tunnel, run as a service): install [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/) and route **`wbcivildefence.org`** (and **`www`** if needed) to your local Gunicorn origin.
- A **Brevo** account and API key if you want real outbound email.

---

## 2. Install dependencies

```bash
uv sync
```

WhiteNoise is included as a normal dependency; when `DJANGO_USE_AWS_STORAGE=False`, production settings enable **WhiteNoise** so `/static/` is served from `STATIC_ROOT` after `collectstatic`.

---

## 3. Environment variables

### Where to edit: `.envs/.production/` vs `.envs/.local/`

The **`.envs/`** tree is **gitignored** (secrets); it is not in the GitHub repo. Create it locally (or copy from a private template / teammate).

- **`.envs/.production/`** — Use this for **`config.settings.production`** (real email, Redis cache, optional S3, etc.). Keep `.envs/.production/.django` and `.envs/.production/.postgres` on your machine only.
- **`.envs/.local/`** — Use this for the **Docker** local stack (`POSTGRES_HOST=postgres`, `REDIS_URL=redis://redis:6379/0`). It is not the right fit for production settings on your laptop unless you align those hostnames yourself.

### Building root `.env` and the `DJANGO_READ_DOT_ENV_FILE` caveat

`config.settings.base` only reads **`civil_defence_app/.env`** when **`DJANGO_READ_DOT_ENV_FILE`** is already **true in the OS environment** (shell export, IDE run configuration, systemd, Docker `environment`, etc.). That flag is checked **before** `.env` is loaded, so it **cannot** be the *only* place you set it—export it once per session or in your process manager.

To populate `.env` from the production templates:

```bash
cd civil_defence_app
uv run python merge_production_dotenvs_in_dotenv.py
export DJANGO_READ_DOT_ENV_FILE=True
```

Values in `.env` are overridden by any variable already set in the OS.

### Required for production settings

| Variable | Purpose |
|----------|---------|
| `DJANGO_SETTINGS_MODULE` | Must be `config.settings.production`. |
| `DJANGO_SECRET_KEY` | Long, random string (50+ characters recommended). |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames (no spaces), e.g. `127.0.0.1,localhost,wbcivildefence.org,www.wbcivildefence.org`. |
| `DJANGO_ADMIN_URL` | Path segment for `urls.path()` (no `^` / `$`), e.g. `super-secret-admin/` — used as the admin URL prefix. |
| `BREVO_API_KEY` | Brevo API key (SMTP & API → API keys in Brevo). |

### Local disk + tunnel (typical for this guide)

| Variable | Purpose |
|----------|---------|
| `DJANGO_USE_AWS_STORAGE` | Set to `False` to use filesystem media/static and WhiteNoise (no `DJANGO_AWS_*` needed). |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated **full URLs** including scheme, e.g. `https://wbcivildefence.org,https://www.wbcivildefence.org`. Required for HTTPS login/forms behind Cloudflare. |
| `DJANGO_PUBLIC_BASE_URL` | Public site URL without trailing slash (e.g. `https://wbcivildefence.org`); used for API schema “Servers” in Spectacular. |
| `DJANGO_READ_DOT_ENV_FILE` | Must be **`True` in the OS environment** (see above) so root `.env` is loaded. |

### Database and cache

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres URL (see [django-environ](https://django-environ.readthedocs.io/) `DATABASE_URL` format). |
| `REDIS_URL` | Redis URL, default `redis://127.0.0.1:6379/0` if unset. |

### Email (Brevo / Anymail)

| Variable | Purpose |
|----------|---------|
| `DJANGO_DEFAULT_FROM_EMAIL` | Visible “From” address; must use a **verified sender or domain** in Brevo. |
| `DJANGO_SERVER_EMAIL` | Optional; defaults to `DEFAULT_FROM_EMAIL`. |
| `BREVO_API_URL` | Optional; default `https://api.brevo.com/v3/`. |

### Optional tuning

| Variable | Purpose |
|----------|---------|
| `CONN_MAX_AGE` | DB connection max age in seconds (default `60` in production). |
| `DJANGO_SECURE_SSL_REDIRECT` | Default `True`; safe behind Cloudflare if `X-Forwarded-Proto: https` is set. |
| `DJANGO_EMAIL_SUBJECT_PREFIX` | Prefix for email subjects. |

### Example merged `.env` content (adjust values)

Prefer editing **`.envs/.production/*.django` / `.postgres`**, then run **`merge_production_dotenvs_in_dotenv.py`**. The snippet below is what ends up in `.env` (do not put `DJANGO_READ_DOT_ENV_FILE` here alone—export it in the shell):

```env
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SECRET_KEY=change-me-to-a-long-random-string-at-least-fifty-chars
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,wbcivildefence.org,www.wbcivildefence.org
DJANGO_CSRF_TRUSTED_ORIGINS=https://wbcivildefence.org,https://www.wbcivildefence.org
DJANGO_PUBLIC_BASE_URL=https://wbcivildefence.org
DJANGO_USE_AWS_STORAGE=False
DJANGO_ADMIN_URL=your-secret-admin-prefix/
DATABASE_URL=postgres://USER:PASSWORD@127.0.0.1:5432/civil_defence_app
REDIS_URL=redis://127.0.0.1:6379/0
BREVO_API_KEY=xkeysib-xxxxxxxx
DJANGO_DEFAULT_FROM_EMAIL=Civil Defence <noreply@wbcivildefence.org>
```

Then: `export DJANGO_READ_DOT_ENV_FILE=True` before `manage.py` or Gunicorn.

Align **`DJANGO_ALLOWED_HOSTS`** and **`DJANGO_CSRF_TRUSTED_ORIGINS`** with the hostnames Cloudflare actually sends (apex, `www`, or both). Remove `www` entries if you do not publish that record.

Keep **`.envs/.production/.django`** in sync with the above, then run **`merge_production_dotenvs_in_dotenv.py`**.

---

## 4. Brevo setup

1. In Brevo, create an **API key** with permission to send transactional email.
2. **Verify** **`wbcivildefence.org`** (or the exact address) in Brevo for `DJANGO_DEFAULT_FROM_EMAIL`.
3. Set `BREVO_API_KEY` and matching `DJANGO_DEFAULT_FROM_EMAIL` in your environment.

Production uses **`django-anymail`** with **`EMAIL_BACKEND = "anymail.backends.brevo.EmailBackend"`** (see `config/settings/production.py`).

django-allauth uses **`ACCOUNT_EMAIL_VERIFICATION = "mandatory"`** in base settings, so sign-up flows expect working email delivery.

---

## 5. Database and static files

```bash
uv run python manage.py migrate
uv run python manage.py collectstatic --noinput
```

- **`collectstatic`** copies static assets into **`STATIC_ROOT`** (`staticfiles/` at project root). WhiteNoise serves them when `DJANGO_USE_AWS_STORAGE=False`.
- User uploads use **`MEDIA_ROOT`** (`civil_defence_app/media/`); URLs are `/media/…` as wired in `config/urls.py`.

If **`collectstatic`** fails on manifest issues, production sets **`WHITENOISE_MANIFEST_STRICT = False`** for the local-storage path so minor third-party static references are less likely to abort the build. Fix underlying missing assets if you see broken styles in the browser.

---

## 6. Gunicorn

### Linux-style server (`config/gunicorn/prod.py`)

Uses `/var/log/gunicorn/`, `/var/run/gunicorn/`, **`daemon = True`**. On macOS you usually need **`sudo`** to create those paths, or you change the paths.

```bash
uv run gunicorn -c config/gunicorn/prod.py
```

### Local machine / macOS (`config/gunicorn/prod_local.py`)

Binds **`127.0.0.1:8000`**, logs to **stdout/stderr**, **foreground**, PID under **`run/gunicorn.pid`** (directory is created automatically; `run/` is gitignored). This config **sets `DJANGO_SETTINGS_MODULE` to `config.settings.production`** so you still get production behavior (e.g. **Brevo**) even if your shell exports **`config.settings.local`** for `manage.py`. It also **`setdefault`s `DJANGO_INSECURE_LOCAL_COOKIES=True`** so **CSRF cookies work on plain `http://127.0.0.1:8000`** (browsers reject `__Secure-csrftoken` there). Export **`DJANGO_INSECURE_LOCAL_COOKIES=False`** before starting Gunicorn if you only use **HTTPS** via the tunnel and want stricter cookies.

```bash
uv run gunicorn -c config/gunicorn/prod_local.py
```

Point your **named tunnel** ingress at **`http://127.0.0.1:8000`** (or whatever port Gunicorn uses).

---

## 7. Cloudflare Tunnel (named tunnel → wbcivildefence.org)

This setup assumes a **persistent tunnel** (e.g. `cloudflared` installed as a **service** on the machine that runs Gunicorn), not a one-off “quick tunnel.”

1. In the [Cloudflare Zero Trust / Tunnels](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/) dashboard, create or select a tunnel and attach a **public hostname**:
   - **`wbcivildefence.org`** → `http://127.0.0.1:8000` (or your bind address/port).
   - Optionally **`www.wbcivildefence.org`** → the same origin, or use a single **CNAME** redirect rule if you only want one canonical host.
2. Ensure **DNS** for the zone points at the tunnel as Cloudflare instructs (proxied records).
3. Match Django env to the hostnames users hit:
   - **`DJANGO_ALLOWED_HOSTS`** — include `wbcivildefence.org` and `www.wbcivildefence.org` if both are valid **Host** headers.
   - **`DJANGO_CSRF_TRUSTED_ORIGINS`** — `https://wbcivildefence.org` and, if used, `https://www.wbcivildefence.org`.
   - **`DJANGO_PUBLIC_BASE_URL`** — usually `https://wbcivildefence.org` (your canonical URL for API docs).

Full tunnel and ingress configuration is in [Cloudflare Tunnel documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/). The important part for Django is that the browser’s **Host** header and **origin** match your settings.

Production sets **`SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`** so Django treats requests as HTTPS when Cloudflare sets **`X-Forwarded-Proto: https`**.

**Quick tunnel** (temporary URL, for ad-hoc tests only): `cloudflared tunnel --url http://127.0.0.1:8000` prints a **`*.trycloudflare.com`** host—use that host in `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` only for that experiment; it does not apply to **`wbcivildefence.org`**.

---

## 8. Celery (optional)

Production settings expect **Redis** for caching; Celery also uses **`REDIS_URL`** from base settings. If you use background tasks in production-like runs:

```bash
uv run celery -A config.celery_app worker -l info
```

For periodic tasks, run **celery beat** in a separate process (see `README.md`).

---

## 9. Verification checklist

1. **`uv run python manage.py check --deploy`** with production env (may report warnings; fix `SECRET_KEY`, `ALLOWED_HOSTS`, etc. as needed).
2. Open **`https://wbcivildefence.org`** (and **`https://www.wbcivildefence.org`** if configured) in a browser; confirm **static** (CSS/JS) and **admin** load.
3. Trigger a **password reset** or sign-up and confirm mail in Brevo (or inbox).

---

## 10. Troubleshooting

| Symptom | What to check |
|--------|----------------|
| **DisallowedHost** | Add the hostname Cloudflare sends (e.g. `wbcivildefence.org` or `www.wbcivildefence.org`) to `DJANGO_ALLOWED_HOSTS`. |
| **403 CSRF** on POST/login | Add full `https://…` origin to `DJANGO_CSRF_TRUSTED_ORIGINS`. If you use **`http://127.0.0.1:8000`** with production settings, **`__Secure-csrftoken`** cookies are never stored (Secure-only). Set **`DJANGO_INSECURE_LOCAL_COOKIES=True`** and usually **`DJANGO_SECURE_SSL_REDIRECT=False`** for that case only, or test via **`https://wbcivildefence.org`** instead. |
| **404 on /static/** | Run `collectstatic`; ensure `DJANGO_USE_AWS_STORAGE=False` so WhiteNoise is enabled. |
| **Email not sent** | `BREVO_API_KEY`, verified sender, Brevo quotas/suppression lists. |
| **Cannot write PID/logs** | Use `config/gunicorn/prod_local.py` or adjust paths in `prod.py`. |

---

## 11. When you switch to AWS S3

Set **`DJANGO_USE_AWS_STORAGE=True`** and provide all **`DJANGO_AWS_*`** variables as in `config/settings/production.py`. In that mode, **WhiteNoise middleware is not inserted** and static URLs point at S3 (or your custom domain).

---

## Reference: settings and packages

- Production settings: `config/settings/production.py`
- WhiteNoise (Django): [WhiteNoise Django integration](https://whitenoise.readthedocs.io/en/stable/django.html)
- Anymail + Brevo: [Anymail Brevo](https://anymail.readthedocs.io/en/stable/esps/brevo/)
