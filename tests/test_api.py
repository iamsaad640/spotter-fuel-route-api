import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.throttling import ScopedRateThrottle

from routefuel.domain import (
    FuelPlanInfeasibleError,
    Point,
    Route,
    RouteNotFoundError,
    RoutingProviderError,
    Station,
)
from routefuel.service import FuelRoutePlanner
from routefuel.stations import StationIndex

URL = "/api/v1/fuel-route"
DALLAS, LOS_ANGELES = Point(32.7767, -96.797), Point(34.0522, -118.2437)


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
    75_600,
)


@pytest.fixture(autouse=True)
def empty_cache():
    cache.clear()


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def router():
    return CountingRouter(LONG_TRIP)


@pytest.fixture
def planner(router):
    planner = FuelRoutePlanner(router, STATIONS, route_cache=cache)
    with patch("routefuel.views.default_planner", return_value=planner):
        yield planner


def post(client, payload, **headers):
    return client.post(URL, data=json.dumps(payload), content_type="application/json", **headers)


@pytest.mark.parametrize(
    "payload,field",
    [
        ({"finish": "Houston, TX"}, "start"),
        ({"start": "Springfeld, IL", "finish": "Houston, TX"}, "start"),
        ({"start": "Toronto, ON", "finish": "Houston, TX"}, "start"),
        ({"start": "Honolulu, HI", "finish": "Houston, TX"}, "start"),
        ({"start": {"latitude": 52, "longitude": -96}, "finish": "Houston, TX"}, "start"),
        ({"start": {"latitude": True, "longitude": -96}, "finish": "Houston, TX"}, "start"),
        ({"start": {"lat": 32, "lng": -96}, "finish": "Houston, TX"}, "start"),
        ({"start": 42, "finish": "Houston, TX"}, "start"),
        ({"start": "Dallas, TX", "finish": "Houston, TX", "starting_fuel_gallons": 51}, None),
        ({"start": "Dallas, TX", "finish": "Houston, TX", "starting_fuel": 10}, None),
        ({"start": "Dallas, TX", "finish": "dallas tx"}, None),
    ],
)
def test_invalid_requests_fail_before_routing(client, planner, router, payload, field):
    response = post(client, payload)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    if field:
        assert field in error["details"]
    assert router.calls == 0


def test_unknown_city_suggests_a_close_match(client, planner):
    response = post(client, {"start": "Springfeld, IL", "finish": "Houston, TX"})
    assert "Did you mean: Springfield, IL;" in response.json()["error"]["details"]["start"][0]


def test_city_names_plan_a_multi_stop_trip_with_one_routing_call(client, planner, router):
    response = post(client, {"start": "Dallas, TX", "finish": "Los Angeles, CA"})
    assert response.status_code == 200
    data = response.json()
    assert data["start"]["label"] == "Dallas, TX"
    assert data["distance_miles"] == 1450.0
    assert data["drive_time_hours"] == 21.0
    assert len(data["fuel_stops"]) >= 3
    assert data["fuel_stops"][0]["route_mile"] == 0.0
    assert Decimal(data["total_fuel_cost_usd"]) == sum(
        Decimal(s["cost_usd"]) for s in data["fuel_stops"]
    )
    assert data["route"]["type"] == "LineString"
    assert data["map_url"].startswith("http://testserver/map?start=")
    assert data["assumptions"]["range_miles"] == 500
    assert data["meta"]["routing_calls"] == 1
    assert router.calls == 1


def test_repeated_trip_is_served_from_the_route_cache(client, planner, router):
    first = post(client, {"start": "Dallas, TX", "finish": "Los Angeles, CA"})
    again = client.get(URL, {"start": "Dallas, TX", "finish": "Los Angeles, CA"})
    assert again.status_code == 200
    assert again.json()["meta"]["routing_calls"] == 0
    assert again.json()["total_fuel_cost_usd"] == first.json()["total_fuel_cost_usd"]
    assert router.calls == 1


def test_starting_fuel_reduces_the_bill(client, planner):
    empty = post(client, {"start": "Dallas, TX", "finish": "Los Angeles, CA"})
    full = post(
        client,
        {"start": "Dallas, TX", "finish": "Los Angeles, CA", "starting_fuel_gallons": 50},
    )
    assert Decimal(full.json()["total_fuel_cost_usd"]) < Decimal(
        empty.json()["total_fuel_cost_usd"]
    )
    assert "starting_fuel_gallons=50" in full.json()["map_url"]


@pytest.mark.parametrize(
    "exception,status,code,message",
    [
        (
            RoutingProviderError("upstream 503 body"),
            502,
            "routing_provider_unavailable",
            "Routing service is temporarily unavailable",
        ),
        (RouteNotFoundError("No driving route"), 422, "route_not_found", "No driving route"),
        (FuelPlanInfeasibleError("gap"), 422, "fuel_plan_infeasible", "gap"),
        (RuntimeError("bug"), 500, "internal_error", "An unexpected error occurred"),
    ],
)
def test_failures_share_one_error_envelope(client, exception, status, code, message):
    with patch("routefuel.views.default_planner") as planner:
        planner.return_value.plan.side_effect = exception
        response = post(client, {"start": "Dallas, TX", "finish": "Houston, TX"})
    assert response.status_code == status
    assert response.json()["error"] == {"code": code, "message": message}
    assert response.json()["request_id"] == response["X-Request-ID"]


@pytest.mark.parametrize(
    "request_kwargs,status,code",
    [
        ({"data": "{not json", "content_type": "application/json"}, 400, "parse_error"),
        ({"data": "start=Dallas", "content_type": "text/plain"}, 415, "unsupported_media_type"),
    ],
)
def test_malformed_bodies(client, request_kwargs, status, code):
    response = client.post(URL, **request_kwargs)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_unsupported_method(client):
    response = client.put(URL)
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_caller_request_id_is_propagated(client, planner):
    response = post(
        client,
        {"start": "Dallas, TX", "finish": "Los Angeles, CA"},
        headers={"X-Request-ID": "trace-12345678"},
    )
    assert response["X-Request-ID"] == "trace-12345678"
    assert response.json()["meta"]["request_id"] == "trace-12345678"
    assert client.get("/healthz", headers={"X-Request-ID": "bad id!"})["X-Request-ID"] != "bad id!"


def test_rate_limit_uses_the_error_envelope(client, planner, monkeypatch):
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"fuel-route": "1/min"})
    post(client, {"start": "Dallas, TX", "finish": "Los Angeles, CA"})
    response = post(client, {"start": "Dallas, TX", "finish": "Los Angeles, CA"})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "throttled"


def test_health(client, planner):
    response = client.get("/healthz")
    assert response.json() == {"status": "ok", "stations": 5}


def test_map_page_ships_a_nonce_based_content_security_policy(client):
    response = client.get("/map", {"start": "Dallas, TX", "finish": "Houston, TX"})
    assert response.status_code == 200
    policy = response["Content-Security-Policy"]
    assert "'nonce-" in policy and "unsafe-inline" not in policy
    assert "https://tile.openstreetmap.org" in policy
    nonce = policy.split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in response.content.decode()


def test_api_responses_forbid_any_active_content(client, planner):
    response = client.get("/healthz")
    assert response["Content-Security-Policy"].startswith("default-src 'none'")


def test_openapi_schema_and_docs(client):
    schema = client.get("/api/schema", HTTP_ACCEPT="application/json")
    assert schema.status_code == 200
    assert "/api/v1/fuel-route" in schema.json()["paths"]
    assert client.get("/api/docs").status_code == 200
    assert client.get("/")["Location"] == "/api/docs"
