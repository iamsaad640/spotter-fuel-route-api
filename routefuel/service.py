import logging
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from .corridor import find_candidates
from .domain import Candidate, FuelPlan, FuelPlanInfeasibleError, Point, Route, Vehicle
from .optimizer import optimize
from .routing import OSRMRouter
from .stations import StationIndex, default_station_index

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

    def plan(self, start: Point, finish: Point, starting_gallons: float = 0.0) -> FuelPlan:
        route = self.router.route(start, finish)
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
            "fuel_plan_ms=%.1f route_miles=%.1f candidates=%s stops=%s",
            1000 * (time.perf_counter() - started),
            route.miles,
            len(candidates),
            len(purchases),
        )
        return FuelPlan(route, purchases, starting_gallons)

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
    return FuelRoutePlanner(
        router=OSRMRouter(
            os.getenv("ROUTING_BASE_URL", "https://router.project-osrm.org"),
            float(os.getenv("ROUTING_TIMEOUT_SECONDS", "12")),
        ),
        stations=default_station_index(),
        corridor_miles=float(os.getenv("ROUTE_CORRIDOR_MILES", "12")),
        stop_penalty_usd=float(os.getenv("FUEL_STOP_PENALTY_USD", "10")),
    )
