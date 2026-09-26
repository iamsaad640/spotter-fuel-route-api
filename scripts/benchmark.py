"""Stage latencies for a recorded New York -> Los Angeles OSRM response.

The recorded response is served through the real OSRMRouter, so parsing is measured and
only network time to the routing provider is excluded.
"""

import gzip
import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from routefuel.corridor import find_candidates
from routefuel.domain import Point
from routefuel.routing import OSRMRouter
from routefuel.service import FuelRoutePlanner
from routefuel.stations import FUEL_PRICES_CSV, STATION_LOCATIONS_CSV, build_station_index

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/osrm_new_york_los_angeles.json.gz"
NEW_YORK, LOS_ANGELES = Point(40.7128, -74.0060), Point(34.0522, -118.2437)


def timed[T](task: Callable[[], T], repeat: int = 1) -> tuple[T, float]:
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        value = task()
        samples.append(1000 * (time.perf_counter() - started))
    return value, round(statistics.median(samples), 1)


def main() -> None:
    recorded = gzip.decompress(FIXTURE.read_bytes())
    router = OSRMRouter(
        "https://router.project-osrm.org",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=recorded))
        ),
    )
    stations, load_ms = timed(lambda: build_station_index(FUEL_PRICES_CSV, STATION_LOCATIONS_CSV))
    route, parse_ms = timed(lambda: router.route(NEW_YORK, LOS_ANGELES), repeat=5)
    candidates, corridor_ms = timed(lambda: find_candidates(route, stations, 12), repeat=5)
    planner = FuelRoutePlanner(router, stations)
    plan, plan_ms = timed(lambda: planner.plan(NEW_YORK, LOS_ANGELES), repeat=5)
    print(
        json.dumps(
            {
                "route_miles": round(route.miles, 1),
                "route_vertices": len(route.points),
                "stations": len(stations),
                "corridor_candidates": len(candidates),
                "fuel_stops": len(plan.purchases),
                "total_fuel_cost_usd": str(plan.total_cost),
                "station_index_load_ms": load_ms,
                "route_parse_ms": parse_ms,
                "corridor_match_ms": corridor_ms,
                "warm_plan_ms_median_of_5": plan_ms,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
