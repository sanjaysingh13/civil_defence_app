"""Gunicorn config for production settings on a local machine.

Foreground process, logs to stdout/stderr, no /var log or PID paths.
Use instead of prod.py on macOS or when tunneling (e.g. Cloudflare).
"""

import multiprocessing
import os
from pathlib import Path

# Gunicorn loads this file before the WSGI app. ``config.wsgi`` only does
# ``setdefault(..., "config.settings.production")``, so a shell or IDE that
# exports ``DJANGO_SETTINGS_MODULE=config.settings.local`` (matching
# ``manage.py``) would otherwise keep local settings — e.g. console email
# instead of Brevo. This config is explicitly for production settings.
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.production"

# Loopback HTTP cannot use ``__Secure-*`` CSRF cookies. Default on so POSTs work at
# http://127.0.0.1:8000. To force ``__Secure-*`` cookies, export
# ``DJANGO_INSECURE_LOCAL_COOKIES=False`` in the shell before starting Gunicorn; then
# use only https://your-domain in the browser.
os.environ.setdefault("DJANGO_INSECURE_LOCAL_COOKIES", "True")

# With production settings, DEBUG is False so Django does not mount /media/; this
# makes Gunicorn serve volunteer uploads from MEDIA_ROOT (filesystem storage only).
os.environ.setdefault("DJANGO_SERVE_LOCAL_MEDIA", "True")

# Project root is the parent of the config/ package (directory that contains manage.py).
_root = Path(__file__).resolve().parent.parent.parent
_run_dir = _root / "run"
_run_dir.mkdir(parents=True, exist_ok=True)

wsgi_app = "config.wsgi:application"
workers = multiprocessing.cpu_count() * 2 + 1
bind = "127.0.0.1:8000"
accesslog = "-"
errorlog = "-"
capture_output = False
daemon = False
pidfile = str(_run_dir / "gunicorn.pid")
