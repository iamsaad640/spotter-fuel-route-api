import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "spotter.settings")

application = get_wsgi_application()

from routefuel.service import default_planner  # noqa: E402  (needs the app registry)

# Build the station and place indexes before the first request. Under gunicorn with
# preload_app, workers inherit them from the master instead of each loading the CSV.
default_planner()
