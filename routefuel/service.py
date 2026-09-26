import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from django.conf import settings
from django.core.cache import cache
from django.core.cache.backends.base import BaseCache

from .corridor import find_candidates
from .domain import Candidate, FuelPlan, FuelPlanInfeasibleError, Point, Route, Vehicle
from .optimizer import optimize
from .routing import OSRMRouter
from .stations import StationIndex, load_stations

logger = logging.getLogger(__name__)


class Router(Protocol):
    def route(self, start: Point, finish: Point) -> Route: ...


@dataclass
class FuelRoutePlanner:
    router: Router
    stations: StationIndex
    vehicle: Vehicle = field(default_factory=Vehicle)
    corridor_miles: float = 12.0
    origin_radius_miles: float = 25.0
    stop_penalty_usd: float = 10.0
    route_cache: BaseCache | None = None
    route_cache_seconds: int = 24 * 60 * 60

    def plan(self, start: Point, finish: Point, starting_gallons: float = 0.0) -> FuelPlan:
        route, routing_calls = self._route(start, finish)
        started = time.perf_counter()
        candidates = self._candidates(route, starting_gallons)
        purchases = optimize(
            candidates,
            route.miles,
            starting_gallons=starting_gallons,
            vehicle=self.vehicle,
            stop_penalty_usd=self.stop_penalty_usd,
        )
        logger.info(
            "fuel_plan_ms=%.1f route_miles=%.1f candidates=%s stops=%s routing_calls=%s",
            1000 * (time.perf_counter() - started),
            route.miles,
            len(candidates),
            len(purchases),
            routing_calls,
        )
        return FuelPlan(route, purchases, starting_gallons, routing_calls)

    def _route(self, start: Point, finish: Point) -> tuple[Route, int]:
        if self.route_cache is None:
            return self.router.route(start, finish), 1
        key = (
            f"route:v1:{start.latitude:.5f},{start.longitude:.5f}:"
            f"{finish.latitude:.5f},{finish.longitude:.5f}"
        )
        # The cache only saves provider calls; an unavailable cache must not fail a request.
        try:
            cached = self.route_cache.get(key)
        except Exception:
            logger.warning("route_cache_read_failed", exc_info=True)
            cached = None
        if isinstance(cached, Route):
            return cached, 0
        route = self.router.route(start, finish)
        try:
            self.route_cache.set(key, route, self.route_cache_seconds)
        except Exception:
            logger.warning("route_cache_write_failed", exc_info=True)
        return route, 1

    def _candidates(self, route: Route, starting_gallons: float) -> tuple[Candidate, ...]:
        along_route = find_candidates(route, self.stations, self.corridor_miles)
        # The trip begins with a fill-up at the cheapest station near the origin; an
        # empty tank could not reach any other station.
        origin = self.stations.cheapest_near(route.points[0], self.origin_radius_miles)
        if origin is None:
            if starting_gallons == 0:
                raise FuelPlanInfeasibleError(
                    f"No fuel station within {self.origin_radius_miles:.0f} miles of the start; "
                    "set starting_fuel_gallons to plan from a fuelled truck"
                )
            return along_route
        station, _ = origin
        return (
            Candidate(station, 0.0, 0.0),
            *(c for c in along_route if c.station.id != station.id),
        )


@lru_cache(maxsize=1)
def default_planner() -> FuelRoutePlanner:
    config = settings.FUEL_ROUTE
    return FuelRoutePlanner(
        router=OSRMRouter(config["ROUTING_BASE_URL"], config["ROUTING_TIMEOUT_SECONDS"]),
        stations=StationIndex(load_stations(config["FUEL_PRICES_CSV"])),
        corridor_miles=config["CORRIDOR_MILES"],
        origin_radius_miles=config["ORIGIN_RADIUS_MILES"],
        stop_penalty_usd=config["STOP_PENALTY_USD"],
        route_cache=cache,
        route_cache_seconds=config["ROUTE_CACHE_SECONDS"],
    )
