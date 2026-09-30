"""T03 prototype settings.

Simulated persistence: SQLite, single process. This does NOT prove
concurrency or locking (D09, AGENTS.md). Synthetic data only.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

# Prototype only; not a production secret. Override with PROTOTYPE_SECRET_KEY.
SECRET_KEY = os.environ.get("PROTOTYPE_SECRET_KEY", "prototype-only-not-a-secret")
DEBUG = os.environ.get("PROTOTYPE_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "inventory",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "inventory.errors.ErrorLogMiddleware",
]

ROOT_URLCONF = "proto_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "proto_site.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("PROTOTYPE_DB", str(BASE_DIR / "prototype.sqlite3")),
    }
}

MESSAGE_STORAGE = "django.contrib.messages.storage.cookie.CookieStorage"

LANGUAGE_CODE = "zh-hans"
# Operation times are stored in UTC; business dates use Asia/Hong_Kong (D04).
TIME_ZONE = "Asia/Hong_Kong"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SYNTHETIC_FIXTURE = REPO_ROOT / "fixtures" / "synthetic" / "stock.json"
