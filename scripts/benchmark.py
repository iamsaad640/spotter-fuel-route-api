"""Offline representative route benchmark; external provider latency is separate."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from routefuel.domain import Point
from routefuel.matching import match_stations
from routefuel.optimizer import optimize
from routefuel.routing import Route
from routefuel.stations import default_stations, load_stations


def measured(task):
    start = time.perf_counter()
    value = task()
    return value, round(1000 * (time.perf_counter() - start), 1)


def main():
    stations, ingestion_ms = measured(
        lambda: load_stations(Path("data/fuel-prices-for-be-assessment.csv"))
    )
    route = Route(
        (
            Point(32.77, -96.80),
            Point(32.26, -99.72),
            Point(35.22, -101.83),
            Point(35.08, -106.65),
            Point(34.87, -111.46),
            Point(33.45, -112.07),
            Point(34.05, -118.24),
        ),
        1450,
    )
    candidates, matching_ms = measured(lambda: match_stations(route, stations))
    purchases, optimizer_ms = measured(lambda: optimize(candidates, route.miles))
    # Include a complete Django request with a counting provider stub; no demo-server
    # traffic or timing variance is hidden inside the offline benchmark.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "spotter.settings")
    import django

    django.setup()
    from django.test import Client

    from routefuel.service import FuelRouteService

    class CountingRouter:
        calls = 0

        def route(self, start, finish):
            self.calls += 1
            return route

    default_stations()  # service cache is warm for the complete-request measurement
    router = CountingRouter()
    payload = {
        "start": {"latitude": 32.77, "longitude": -96.80},
        "finish": {"latitude": 34.05, "longitude": -118.24},
    }
    with patch("routefuel.api.default_service", return_value=FuelRouteService(router)):
        response, request_ms = measured(
            lambda: Client().post(
                "/api/v1/fuel-route", data=json.dumps(payload), content_type="application/json"
            )
        )
    print(
        json.dumps(
            {
                "stations": len(stations),
                "candidates": len(candidates),
                "stops": len(purchases),
                "ingestion_ms": ingestion_ms,
                "matching_ms": matching_ms,
                "optimizer_ms": optimizer_ms,
                "offline_total_ms": ingestion_ms + matching_ms + optimizer_ms,
                "external_routing_calls": 0,
                "simulated_provider_calls": router.calls,
                "complete_request_ms": request_ms,
                "api_status": response.status_code,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
