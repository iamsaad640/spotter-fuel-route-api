import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import Client

from routefuel.domain import (
    FuelPlanInfeasibleError,
    Point,
    Route,
    RoutingProviderError,
    Station,
)
from routefuel.service import FuelRoutePlanner
from routefuel.stations import StationIndex

DALLAS, LOS_ANGELES = Point(32.77, -96.8), Point(34.05, -118.24)


class CountingRouter:
    def __init__(self, route):
        self._route = route
        self.calls = 0

    def route(self, start, finish):
        self.calls += 1
        return self._route


def station(id, lat, lon, price):
    return Station(id, f"Stop {id}", "C", "TX", "A", Decimal(price), Point(lat, lon), id)


STATIONS = StationIndex(
    (
        station(1, 32.78, -96.81, "3.10"),
        station(2, 32.26, -99.72, "2.95"),
        station(3, 35.22, -101.83, "3.05"),
        station(4, 35.08, -106.65, "2.80"),
        station(5, 33.45, -112.07, "3.20"),
    )
)
LONG_TRIP = Route(
    (
        DALLAS,
        Point(32.26, -99.72),
        Point(35.22, -101.83),
        Point(35.08, -106.65),
        Point(34.87, -111.46),
        Point(33.45, -112.07),
        LOS_ANGELES,
    ),
    1450,
)


@pytest.fixture
def client():
    return Client()


def post(client, payload):
    return client.post(
        "/api/v1/fuel-route", data=json.dumps(payload), content_type="application/json"
    )


def body(start, finish):
    return {
        "start": {"latitude": start.latitude, "longitude": start.longitude},
        "finish": {"latitude": finish.latitude, "longitude": finish.longitude},
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"start": {}, "finish": {}},
        {"start": {"latitude": 52, "longitude": -96}, "finish": {"latitude": 32, "longitude": -96}},
        {
            "start": {"latitude": True, "longitude": -96},
            "finish": {"latitude": 32, "longitude": -96},
        },
        {"start": {"latitude": 32, "longitude": -96}, "finish": {"latitude": 32, "longitude": -96}},
    ],
)
def test_rejected_inputs_do_not_call_provider(client, payload):
    with patch("routefuel.api.default_planner") as planner:
        assert post(client, payload).status_code == 400
    planner.assert_not_called()


def test_short_trip_from_an_empty_tank_is_billed(client):
    router = CountingRouter(Route((DALLAS, Point(32.5, -97.5)), 60))
    with patch("routefuel.api.default_planner", return_value=FuelRoutePlanner(router, STATIONS)):
        response = post(client, body(DALLAS, Point(32.5, -97.5)))
    assert response.status_code == 200
    assert response.json()["fuel_stops"][0]["gallons"] == "6.00"
    assert response.json()["total_fuel_cost_usd"] == "18.60"
    assert router.calls == 1


def test_long_trip_uses_multiple_stops_and_one_routing_call(client):
    router = CountingRouter(LONG_TRIP)
    with patch("routefuel.api.default_planner", return_value=FuelRoutePlanner(router, STATIONS)):
        response = post(client, body(DALLAS, LOS_ANGELES))
    assert response.status_code == 200
    assert len(response.json()["fuel_stops"]) >= 3
    assert Decimal(response.json()["total_fuel_cost_usd"]) > 0
    assert router.calls == 1


@pytest.mark.parametrize(
    "exception,status,code",
    [
        (RoutingProviderError(), 502, "routing_provider_unavailable"),
        (FuelPlanInfeasibleError("gap"), 422, "fuel_coverage_unavailable"),
    ],
)
def test_failure_mapping(client, exception, status, code):
    with patch("routefuel.api.default_planner") as planner:
        planner.return_value.plan.side_effect = exception
        response = post(client, body(DALLAS, LOS_ANGELES))
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
