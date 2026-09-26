import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG")
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is false")
    SECRET_KEY = "django-insecure-local-development-only"
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = ["rest_framework", "drf_spectacular", "routefuel"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "routefuel.middleware.RequestIdMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
]
ROOT_URLCONF = "spotter.urls"
WSGI_APPLICATION = "spotter.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csp",
            ]
        },
    }
]

# Stateless service: nothing is persisted, so no database is configured.
DATABASES: dict[str, dict[str, str]] = {}

REDIS_URL = os.getenv("REDIS_URL", "")
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
        if REDIS_URL
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    )
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True
DATA_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT")
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS")
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD")
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
if env_bool("DJANGO_BEHIND_TLS_PROXY"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
SECURE_CSP = {
    "default-src": [CSP.NONE],
    "base-uri": [CSP.NONE],
    "form-action": [CSP.NONE],
    "frame-ancestors": [CSP.NONE],
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"fuel-route": os.getenv("FUEL_ROUTE_RATE_LIMIT", "60/min")},
    "NUM_PROXIES": int(os.getenv("DJANGO_NUM_PROXIES", "0")),
    "EXCEPTION_HANDLER": "routefuel.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Fuel Route API",
    "DESCRIPTION": (
        "Plans a US driving route and the cheapest fuel stops for a truck with a 500-mile "
        "range at 10 miles per gallon, using one routing-provider call per new trip."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SWAGGER_UI_DIST": "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.0",
    "SWAGGER_UI_FAVICON_HREF": "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.0/favicon-32x32.png",
}

FUEL_ROUTE = {
    "ROUTING_BASE_URL": os.getenv("ROUTING_BASE_URL", "https://router.project-osrm.org"),
    "ROUTING_TIMEOUT_SECONDS": float(os.getenv("ROUTING_TIMEOUT_SECONDS", "12")),
    "ROUTE_CACHE_SECONDS": int(os.getenv("ROUTE_CACHE_SECONDS", str(24 * 60 * 60))),
    "CORRIDOR_MILES": float(os.getenv("ROUTE_CORRIDOR_MILES", "12")),
    "ORIGIN_RADIUS_MILES": float(os.getenv("ORIGIN_RADIUS_MILES", "25")),
    "STOP_PENALTY_USD": float(os.getenv("FUEL_STOP_PENALTY_USD", "10")),
    "FUEL_PRICES_CSV": Path(
        os.getenv("FUEL_PRICES_CSV", BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv")
    ),
    "STATION_LOCATIONS_CSV": Path(
        os.getenv("STATION_LOCATIONS_CSV", BASE_DIR / "data" / "station-locations.csv")
    ),
    "OVERPASS_URL": os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter"),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "routefuel.middleware.RequestIdLogFilter"}},
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"}
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_id"],
            "formatter": "plain",
        }
    },
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    "loggers": {"django": {"level": "INFO", "propagate": True}},
}
