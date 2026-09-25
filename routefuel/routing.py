"""One OSRM directions call, with provider failures kept out of the HTTP boundary."""

import logging
import math
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .domain import InvalidRoute, Point, ProviderFailure

logger = logging.getLogger(__name__)
MILES_PER_METER = 0.000621371192


@dataclass(frozen=True)
class Route:
    points: tuple[Point, ...]
    miles: float


class OSRMRouter:
    def __init__(self, base_url: str, timeout: float = 12, client: httpx.Client | None = None):
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("ROUTING_BASE_URL must be an HTTPS origin without credentials")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("ROUTING_TIMEOUT_SECONDS must be positive")
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False)

    def route(self, start: Point, finish: Point) -> Route:
        coordinates = (
            f"{start.longitude:.6f},{start.latitude:.6f};"
            f"{finish.longitude:.6f},{finish.latitude:.6f}"
        )
        start_time = time.perf_counter()
        try:
            response = self.client.get(
                f"{self.base_url}/route/v1/driving/{coordinates}",
                params={"overview": "full", "geometries": "geojson", "steps": "false"},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") == "NoRoute":
                raise InvalidRoute("No driving route is available for these locations")
            if payload.get("code") != "Ok":
                raise ValueError("Unexpected provider status")
            route = payload["routes"][0]
            miles = float(route["distance"]) * MILES_PER_METER
            geometry = route["geometry"]
            if geometry["type"] != "LineString":
                raise ValueError("Unexpected route geometry")
            points = tuple(Point(float(lat), float(lon)) for lon, lat in geometry["coordinates"])
            if (
                len(points) < 2
                or not math.isfinite(miles)
                or miles <= 0
                or any(not (-90 <= p.latitude <= 90 and -180 <= p.longitude <= 180) for p in points)
            ):
                raise ValueError("Invalid route distance or coordinates")
            return Route(points, miles)
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
        ) as exc:
            logger.warning("route_provider_failed type=%s", type(exc).__name__)
            raise ProviderFailure("Routing service is unavailable") from exc
        finally:
            logger.info("route_provider_latency_ms=%.1f", 1000 * (time.perf_counter() - start_time))
