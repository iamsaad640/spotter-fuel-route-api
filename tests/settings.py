import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")
os.environ.pop("REDIS_URL", None)

from spotter.settings import *  # noqa: E402, F403
from spotter.settings import REST_FRAMEWORK  # noqa: E402

REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {"fuel-route": "1000/min"}}
