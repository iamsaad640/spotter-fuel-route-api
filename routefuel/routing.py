"""OSRM driving directions: exactly one HTTP request per route."""

import logging
import math
import time
from urllib.parse import urlparse

import httpx

from .domain import Point, Route, RouteNotFoundError, RoutingProviderError

logger = logging.getLogger(__name__)
MILES_PER_METER = 0.000621371192


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
        started = time.perf_counter()
        try:
            response = self.client.get(
                f"{self.base_url}/route/v1/driving/{coordinates}",
                params={"overview": "full", "geometries": "geojson", "steps": "false"},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") in {"NoRoute", "NoSegment"}:
                raise RouteNotFoundError("No driving route connects these locations")
            if payload.get("code") != "Ok":
                raise ValueError("Unexpected provider status")
            route = payload["routes"][0]
            miles = float(route["distance"]) * MILES_PER_METER
            duration = float(route.get("duration", 0.0))
            geometry = route["geometry"]
            if geometry["type"] != "LineString":
                raise ValueError("Unexpected route geometry")
            points = tuple(Point(float(lat), float(lon)) for lon, lat in geometry["coordinates"])
            if (
                len(points) < 2
                or not math.isfinite(miles)
                or miles <= 0
                or not math.isfinite(duration)
                or any(not (-90 <= p.latitude <= 90 and -180 <= p.longitude <= 180) for p in points)
            ):
                raise ValueError("Invalid route distance or coordinates")
            return Route(points, miles, duration)
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
        ) as exc:
            logger.warning("routing_provider_failed error=%s", type(exc).__name__)
            raise RoutingProviderError("Routing service is unavailable") from exc
        finally:
            logger.info("routing_provider_ms=%.1f", 1000 * (time.perf_counter() - started))
