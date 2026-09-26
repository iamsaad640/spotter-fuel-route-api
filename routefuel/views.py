import time
from typing import Any
from urllib.parse import urlencode

from django.http import HttpRequest, JsonResponse
from django.urls import reverse
from django.utils.csp import CSP
from django.utils.decorators import method_decorator
from django.views.decorators.csp import csp_override
from django.views.generic import TemplateView
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .domain import Place
from .middleware import current_request_id
from .serializers import FuelRouteRequestSerializer, FuelRouteResponseSerializer
from .service import default_planner

LEAFLET_CDN = "https://cdnjs.cloudflare.com"
MAP_TILES = "https://tile.openstreetmap.org"
ERROR_RESPONSES = {
    400: {"description": "Invalid or unknown location"},
    422: {"description": "No driving route, or stations too far apart for a 500-mile range"},
    429: {"description": "Rate limit exceeded"},
    502: {"description": "Routing provider unavailable"},
}


def query_value(place: Place) -> str:
    return f"{place.point.latitude},{place.point.longitude}"


class FuelRouteView(APIView):
    throttle_scope = "fuel-route"

    @extend_schema(
        summary="Plan a route with the cheapest fuel stops",
        request=FuelRouteRequestSerializer,
        responses={200: FuelRouteResponseSerializer, **ERROR_RESPONSES},
        examples=[
            OpenApiExample(
                "City names", value={"start": "New York, NY", "finish": "Los Angeles, CA"}
            ),
            OpenApiExample("ZIP codes", value={"start": "60601", "finish": "77002"}),
            OpenApiExample(
                "Coordinates",
                value={
                    "start": {"latitude": 32.7767, "longitude": -96.797},
                    "finish": {"latitude": 34.0522, "longitude": -118.2437},
                },
            ),
            OpenApiExample(
                "Truck starts full",
                value={"start": "Dallas, TX", "finish": "Houston, TX", "starting_fuel_gallons": 50},
            ),
        ],
    )
    def post(self, request: Request) -> Response:
        return self._plan(request, request.data)

    @extend_schema(
        summary="Plan a route with the cheapest fuel stops (query string)",
        parameters=[
            OpenApiParameter(
                "start", str, required=True, examples=[OpenApiExample("City", "Chicago, IL")]
            ),
            OpenApiParameter(
                "finish", str, required=True, examples=[OpenApiExample("City", "Houston, TX")]
            ),
            OpenApiParameter("starting_fuel_gallons", float, required=False),
        ],
        responses={200: FuelRouteResponseSerializer, **ERROR_RESPONSES},
    )
    def get(self, request: Request) -> Response:
        return self._plan(request, request.query_params)

    def _plan(self, request: Request, data: Any) -> Response:
        started = time.perf_counter()
        params = FuelRouteRequestSerializer(data=data)
        params.is_valid(raise_exception=True)
        start, finish = params.validated_data["start"], params.validated_data["finish"]
        starting_gallons = params.validated_data["starting_fuel_gallons"]
        planner = default_planner()
        plan = planner.plan(start.point, finish.point, starting_gallons)

        map_query = {"start": query_value(start), "finish": query_value(finish)}
        if starting_gallons:
            map_query["starting_fuel_gallons"] = str(starting_gallons)
        result = {
            "start": start,
            "finish": finish,
            "plan": plan,
            "map_url": request.build_absolute_uri(f"{reverse('route-map')}?{urlencode(map_query)}"),
            "assumptions": {
                "tank_gallons": planner.vehicle.tank_gallons,
                "miles_per_gallon": planner.vehicle.miles_per_gallon,
                "range_miles": planner.vehicle.range_miles,
                "starting_fuel_gallons": starting_gallons,
                "stop_penalty_usd": planner.stop_penalty_usd,
                "station_corridor_miles": planner.corridor_miles,
                "station_locations": (
                    "OpenStreetMap exit node where the address names an exit, "
                    "otherwise the city centroid; the CSV has no coordinates"
                ),
            },
            "meta": {
                "request_id": current_request_id(),
                "routing_calls": plan.routing_calls,
                "elapsed_ms": round(1000 * (time.perf_counter() - started)),
            },
        }
        return Response(FuelRouteResponseSerializer(result).data)


@method_decorator(
    csp_override(
        {
            "default-src": [CSP.NONE],
            "script-src": [CSP.NONCE, LEAFLET_CDN],
            "style-src": [CSP.NONCE, LEAFLET_CDN],
            "img-src": [MAP_TILES, "data:"],
            "connect-src": [CSP.SELF],
            "base-uri": [CSP.NONE],
            "form-action": [CSP.SELF],
            "frame-ancestors": [CSP.NONE],
        }
    ),
    name="dispatch",
)
class RouteMapView(TemplateView):
    template_name = "routefuel/route_map.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return {**super().get_context_data(**kwargs), "api_url": reverse("fuel-route")}


def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "stations": len(default_planner().stations)})
