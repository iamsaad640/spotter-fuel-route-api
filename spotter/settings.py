import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-development-only-secret-key")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
ROOT_URLCONF = "spotter.urls"
INSTALLED_APPS: list[str] = []
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "false").lower() == "true"
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
if not DEBUG:
    if SECRET_KEY == "local-development-only-secret-key":
        raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG=false")
    if ALLOWED_HOSTS == ["localhost", "127.0.0.1", "testserver"]:
        raise RuntimeError("Set DJANGO_ALLOWED_HOSTS for production")
