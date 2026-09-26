import httpx
import pytest

from routefuel.domain import Point, RouteNotFoundError, RoutingProviderError
from routefuel.routing import OSRMRouter


def router(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OSRMRouter("https://router.example", client=client)


def test_one_provider_call_for_coordinates():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 1000,
                        "duration": 60,
                        "geometry": {"type": "LineString", "coordinates": [[-96, 32], [-95, 33]]},
                    }
                ],
            },
        )

    route = router(handler).route(Point(32, -96), Point(33, -95))
    assert len(calls) == 1
    assert "geometries=geojson" in str(calls[0].url)
    assert route.duration_seconds == 60
    assert route.miles == pytest.approx(0.621371192)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"routes": []},
        {
            "routes": [
                {
                    "distance": "nan",
                    "geometry": {"type": "LineString", "coordinates": [[1, 2], [3, 4]]},
                }
            ]
        },
        {"routes": [{"distance": 1000, "geometry": {"type": "Point", "coordinates": []}}]},
    ],
)
def test_malformed_response_is_upstream_failure(payload):
    with pytest.raises(RoutingProviderError):
        router(lambda _: httpx.Response(200, json=payload)).route(Point(32, -96), Point(33, -95))


def test_timeout():
    def handler(_):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(RoutingProviderError):
        router(handler).route(Point(32, -96), Point(33, -95))


def test_no_route():
    with pytest.raises(RouteNotFoundError):
        router(lambda _: httpx.Response(200, json={"code": "NoRoute"})).route(
            Point(32, -96), Point(33, -95)
        )


def test_invalid_url_configuration():
    with pytest.raises(ValueError):
        OSRMRouter("http://example.com")


def test_non_json_response():
    with pytest.raises(RoutingProviderError):
        router(lambda _: httpx.Response(200, text="not json")).route(Point(32, -96), Point(33, -95))
