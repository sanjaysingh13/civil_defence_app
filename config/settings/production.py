# ruff: noqa: E501
from .base import *  # noqa: F403
from .base import CSRF_TRUSTED_ORIGINS
from .base import DATABASES
from .base import INSTALLED_APPS
from .base import MIDDLEWARE
from .base import REDIS_URL
from .base import SPECTACULAR_SETTINGS
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env("DJANGO_SECRET_KEY")
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["example.com"])

# DATABASES
# ------------------------------------------------------------------------------
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)

# CACHES
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            # Mimicking memcache behavior.
            # https://github.com/jazzband/django-redis#memcached-exceptions-behavior
            "IGNORE_EXCEPTIONS": True,
        },
    },
}

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-proxy-ssl-header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-ssl-redirect
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-secure
# ``__Secure-*`` cookie names require the Secure flag; browsers ignore them on http://.
# Default True when localhost is in ALLOWED_HOSTS so http://127.0.0.1:8000 POSTs work.
# Set DJANGO_INSECURE_LOCAL_COOKIES=False if you only serve HTTPS and want __Secure-*.
_allowed_hosts_lower = {h.lower() for h in ALLOWED_HOSTS}
_insecure_cookies_default = bool(
    _allowed_hosts_lower & {"127.0.0.1", "localhost"},
)
DJANGO_INSECURE_LOCAL_COOKIES = env.bool(
    "DJANGO_INSECURE_LOCAL_COOKIES",
    default=_insecure_cookies_default,
)
if DJANGO_INSECURE_LOCAL_COOKIES:
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_NAME = "sessionid"
    CSRF_COOKIE_NAME = "csrftoken"
else:
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_NAME = "__Secure-sessionid"
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_NAME = "__Secure-csrftoken"
# https://docs.djangoproject.com/en/dev/topics/security/#ssl-https
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-seconds
# TODO: set this to 60 seconds first and then to 518400 once you prove the former works
SECURE_HSTS_SECONDS = 60
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-include-subdomains
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=True,
)
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-preload
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=True)
# https://docs.djangoproject.com/en/dev/ref/middleware/#x-content-type-options-nosniff
SECURE_CONTENT_TYPE_NOSNIFF = env.bool(
    "DJANGO_SECURE_CONTENT_TYPE_NOSNIFF",
    default=True,
)

# When False, static and media use local disk (STATIC_ROOT / MEDIA_ROOT from base).
# Set True for real AWS S3 deploys; requires all DJANGO_AWS_* variables below.
DJANGO_USE_AWS_STORAGE = env.bool("DJANGO_USE_AWS_STORAGE", default=True)

if DJANGO_USE_AWS_STORAGE:
    # https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
    AWS_ACCESS_KEY_ID = env("DJANGO_AWS_ACCESS_KEY_ID")
    # https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
    AWS_SECRET_ACCESS_KEY = env("DJANGO_AWS_SECRET_ACCESS_KEY")
    # https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
    AWS_STORAGE_BUCKET_NAME = env("DJANGO_AWS_STORAGE_BUCKET_NAME")
    # https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
    AWS_QUERYSTRING_AUTH = False
    # DO NOT change these unless you know what you're doing.
    _AWS_EXPIRY = 60 * 60 * 24 * 7
    # https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": f"max-age={_AWS_EXPIRY}, s-maxage={_AWS_EXPIRY}, must-revalidate",
    }
    # https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
    AWS_S3_MAX_MEMORY_SIZE = env.int(
        "DJANGO_AWS_S3_MAX_MEMORY_SIZE",
        default=100_000_000,  # 100MB
    )
    # https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
    AWS_S3_REGION_NAME = env("DJANGO_AWS_S3_REGION_NAME", default=None)
    # https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#cloudfront
    AWS_S3_CUSTOM_DOMAIN = env("DJANGO_AWS_S3_CUSTOM_DOMAIN", default=None)
    aws_s3_domain = AWS_S3_CUSTOM_DOMAIN or f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
    # STATIC & MEDIA
    # ------------------------
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "location": "media",
                "file_overwrite": False,
            },
        },
        "staticfiles": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "location": "static",
                "default_acl": "public-read",
            },
        },
    }
    MEDIA_URL = f"https://{aws_s3_domain}/media/"
    STATIC_URL = f"https://{aws_s3_domain}/static/"
    COLLECTFASTA_STRATEGY = "collectfasta.strategies.boto3.Boto3Strategy"
else:
    # WhiteNoise serves collected static from STATIC_ROOT; manifest adds hashed filenames for caching.
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
    MEDIA_URL = "/media/"
    STATIC_URL = "/static/"
    COLLECTFASTA_STRATEGY = "collectfasta.strategies.filesystem.FileSystemStrategy"

if not DJANGO_USE_AWS_STORAGE:
    # https://whitenoise.readthedocs.io/en/stable/django.html#enable-whitenoise
    _security_mw = "django.middleware.security.SecurityMiddleware"
    _insert_at = MIDDLEWARE.index(_security_mw) + 1
    MIDDLEWARE = [
        *MIDDLEWARE[:_insert_at],
        "whitenoise.middleware.WhiteNoiseMiddleware",
        *MIDDLEWARE[_insert_at:],
    ]
    # Allow collectstatic to succeed if a dependency references a missing static asset in the manifest.
    WHITENOISE_MANIFEST_STRICT = False

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#default-from-email
DEFAULT_FROM_EMAIL = env(
    "DJANGO_DEFAULT_FROM_EMAIL",
    default="Civil Defence App <noreply@civildefencewb.org>",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#server-email
SERVER_EMAIL = env("DJANGO_SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-subject-prefix
EMAIL_SUBJECT_PREFIX = env(
    "DJANGO_EMAIL_SUBJECT_PREFIX",
    default="[Civil Defence App] ",
)
ACCOUNT_EMAIL_SUBJECT_PREFIX = EMAIL_SUBJECT_PREFIX

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL regex.
ADMIN_URL = env("DJANGO_ADMIN_URL")

# Anymail
# ------------------------------------------------------------------------------
# https://anymail.readthedocs.io/en/stable/installation/#installing-anymail
INSTALLED_APPS += ["anymail"]
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
# https://anymail.readthedocs.io/en/stable/installation/#anymail-settings-reference
# https://anymail.readthedocs.io/en/stable/esps/brevo/
EMAIL_BACKEND = "anymail.backends.brevo.EmailBackend"
ANYMAIL = {
    "BREVO_API_KEY": env("BREVO_API_KEY"),
    "BREVO_API_URL": env("BREVO_API_URL", default="https://api.brevo.com/v3/"),
}

# Collectfasta
# ------------------------------------------------------------------------------
# https://github.com/jasongi/collectfasta#installation
INSTALLED_APPS = ["collectfasta", *INSTALLED_APPS]

# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
# A sample logging configuration. The only tangible logging
# performed by this configuration is to send an email to
# the site admins on every HTTP 500 error when DEBUG=False.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"require_debug_false": {"()": "django.utils.log.RequireDebugFalse"}},
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "mail_admins": {
            "level": "ERROR",
            "filters": ["require_debug_false"],
            "class": "django.utils.log.AdminEmailHandler",
        },
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "django.request": {
            "handlers": ["mail_admins"],
            "level": "ERROR",
            "propagate": True,
        },
        "django.security.DisallowedHost": {
            "level": "ERROR",
            "handlers": ["console", "mail_admins"],
            "propagate": True,
        },
    },
}

# django-rest-framework
# -------------------------------------------------------------------------------
# Tools that generate code samples can use SERVERS to point to the correct domain
_spectacular_base = env(
    "DJANGO_PUBLIC_BASE_URL",
    default="https://example.com",
).rstrip("/")
SPECTACULAR_SETTINGS["SERVERS"] = [
    {"url": _spectacular_base, "description": "Production server"},
]

# Merge extra trusted origins (e.g. tunnel URL). Plain HTTP to Gunicorn on 8000 needs
# these when DJANGO_INSECURE_LOCAL_COOKIES=True (see SECURITY block above).
_csrf_from_env = list(env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[]))
if DJANGO_INSECURE_LOCAL_COOKIES:
    _csrf_from_env.extend(
        [
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
    )
CSRF_TRUSTED_ORIGINS = list(
    dict.fromkeys(
        [
            *CSRF_TRUSTED_ORIGINS,
            *_csrf_from_env,
        ],
    ),
)

# Your stuff...
# ------------------------------------------------------------------------------
