import json
from unittest.mock import patch

import pytest
from django.test import Client

from routefuel.domain import Point, ProviderFailure, UnserviceableRoute
from routefuel.routing import Route
from routefuel.service import FuelRouteService


@pytest.fixture
def client():
    return Client()


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
    with patch("routefuel.api.default_service") as service:
        result = client.post(
            "/api/v1/fuel-route", data=json.dumps(payload), content_type="application/json"
        )
    assert result.status_code == 400
    service.assert_not_called()


def test_complete_request_with_fake_router_and_one_call(client):
    class FakeRouter:
        calls = 0

        def route(self, start, finish):
            self.calls += 1
            return Route((start, Point(35, -98), finish), 300)

    router = FakeRouter()
    with patch("routefuel.api.default_service", return_value=FuelRouteService(router)):
        response = client.post(
            "/api/v1/fuel-route",
            data=json.dumps(
                {
                    "start": {"latitude": 35, "longitude": -100},
                    "finish": {"latitude": 35, "longitude": -95},
                }
            ),
            content_type="application/json",
        )
    assert response.status_code == 200
    assert response.json()["route"]["type"] == "LineString"
    assert response.json()["total_fuel_cost_usd"] == "0.00"
    assert router.calls == 1


@pytest.mark.parametrize(
    "exception,status,code",
    [
        (ProviderFailure(), 502, "routing_provider_unavailable"),
        (UnserviceableRoute("gap"), 422, "fuel_coverage_unavailable"),
    ],
)
def test_failure_mapping(client, exception, status, code):
    with patch("routefuel.api.default_service") as service:
        service.return_value.plan.side_effect = exception
        response = client.post(
            "/api/v1/fuel-route",
            data=json.dumps(
                {
                    "start": {"latitude": 35, "longitude": -100},
                    "finish": {"latitude": 35, "longitude": -95},
                }
            ),
            content_type="application/json",
        )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_complete_long_trip_uses_multiple_fuel_stops(client):
    class FakeRouter:
        calls = 0

        def route(self, start, finish):
            self.calls += 1
            return Route(
                (
                    start,
                    Point(32.26, -99.72),
                    Point(35.22, -101.83),
                    Point(35.08, -106.65),
                    Point(34.87, -111.46),
                    Point(33.45, -112.07),
                    finish,
                ),
                1450,
            )

    router = FakeRouter()
    body = {
        "start": {"latitude": 32.77, "longitude": -96.8},
        "finish": {"latitude": 34.05, "longitude": -118.24},
    }
    with patch("routefuel.api.default_service", return_value=FuelRouteService(router)):
        response = client.post(
            "/api/v1/fuel-route", data=json.dumps(body), content_type="application/json"
        )
    assert response.status_code == 200
    assert len(response.json()["fuel_stops"]) >= 2
    assert float(response.json()["total_fuel_cost_usd"]) > 0
    assert router.calls == 1
