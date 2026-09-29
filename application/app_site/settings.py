"""T06a domain service settings. PostgreSQL is required, including for tests."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ.get("APPLICATION_SECRET_KEY", "test-only-key-not-for-deployment")
DEBUG = False
INSTALLED_APPS = ["django.contrib.contenttypes", "inventory"]
MIDDLEWARE = []
ROOT_URLCONF = "app_site.urls"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("PGDATABASE", "ingredient_test"),
        "USER": os.environ.get("PGUSER", "ingredient_test"),
        "PASSWORD": os.environ.get("PGPASSWORD", ""),
        "HOST": os.environ.get("PGHOST", "127.0.0.1"),
        "PORT": os.environ.get("PGPORT", "5432"),
        "TEST": {"NAME": os.environ.get("PGTESTDATABASE", "test_ingredient_test")},
    }
}
TIME_ZONE = "Asia/Hong_Kong"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
INVENTORY_TEST_HOOKS = False
SYNTHETIC_FIXTURE = REPO_ROOT / "fixtures" / "synthetic" / "stock.json"
