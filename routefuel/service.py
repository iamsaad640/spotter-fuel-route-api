import logging
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from .domain import Point
from .matching import match_stations
from .optimizer import optimize
from .routing import OSRMRouter
from .stations import default_stations

logger = logging.getLogger(__name__)


@dataclass
class FuelRouteService:
    router: OSRMRouter
    corridor_miles: float = 12

    def plan(self, start: Point, finish: Point) -> dict:
        route = self.router.route(start, finish)
        start_time = time.perf_counter()
        candidates = match_stations(route, default_stations(), self.corridor_miles)
        logger.info("route_miles=%.2f candidate_count=%s", route.miles, len(candidates))
        purchases = optimize(candidates, route.miles)
        logger.info(
            "optimization_ms=%.1f fuel_stops=%s",
            1000 * (time.perf_counter() - start_time),
            len(purchases),
        )
        return {
            "route": {
                "type": "LineString",
                "coordinates": [[p.longitude, p.latitude] for p in route.points],
            },
            "route_miles": round(route.miles, 2),
            "fuel_stops": [
                {
                    "opis_id": p.candidate.station.id,
                    "name": p.candidate.station.name,
                    "address": p.candidate.station.address,
                    "city": p.candidate.station.city,
                    "state": p.candidate.station.state,
                    "location": [
                        p.candidate.station.point.longitude,
                        p.candidate.station.point.latitude,
                    ],
                    "mile_marker": round(p.candidate.mile, 2),
                    "estimated_one_way_detour_miles": round(p.candidate.detour_miles, 2),
                    "price_per_gallon_usd": str(p.candidate.station.price),
                    "gallons": str(p.gallons),
                    "cost_usd": str(p.cost),
                }
                for p in purchases
            ],
            "total_fuel_cost_usd": str(sum((p.cost for p in purchases), Decimal("0.00"))),
            "assumptions": {
                "starting_fuel_gallons": 50,
                "max_range_miles": 500,
                "mpg": 10,
                "station_locations": "city ZIP centroid approximation",
                "detours": "estimated straight-line round trip, not road-routed",
            },
        }


@lru_cache(maxsize=1)
def default_service() -> FuelRouteService:
    return FuelRouteService(
        OSRMRouter(
            os.getenv("ROUTING_BASE_URL", "https://router.project-osrm.org"),
            float(os.getenv("ROUTING_TIMEOUT_SECONDS", "12")),
        ),
        float(os.getenv("ROUTE_CORRIDOR_MILES", "12")),
    )
