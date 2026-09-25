"""Small HTTP boundary: coordinate input avoids extra provider requests."""

import json
import logging
import math
import uuid

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .domain import InvalidRoute, Point, ProviderFailure, UnserviceableRoute
from .service import default_service

logger = logging.getLogger(__name__)


def error(code: str, detail: str, status: int, request_id: str) -> JsonResponse:
    result = JsonResponse(
        {"error": {"code": code, "message": detail}, "request_id": request_id}, status=status
    )
    result["X-Request-ID"] = request_id
    return result


def parse_point(value: object) -> Point:
    if not isinstance(value, dict) or set(value) != {"latitude", "longitude"}:
        raise ValueError("Locations must contain latitude and longitude only")
    lat, lon = value["latitude"], value["longitude"]
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) for v in (lat, lon)):
        raise ValueError("Coordinates must be finite numbers")
    if not all(math.isfinite(v) for v in (lat, lon)) or not (
        24 <= lat <= 50 and -125 <= lon <= -66
    ):
        raise ValueError("Locations must be within the contiguous US coordinate envelope")
    return Point(float(lat), float(lon))


@csrf_exempt  # Stateless public API with no cookie authentication or side effects.
def plan_route(request: HttpRequest) -> JsonResponse:
    request_id = uuid.uuid4().hex
    if request.method != "POST":
        response = error("method_not_allowed", "Use POST", 405, request_id)
        response["Allow"] = "POST"
        return response
    if request.content_type != "application/json" or len(request.body) > 4096:
        return error("invalid_request", "Expected a JSON request under 4096 bytes", 400, request_id)
    try:
        body = json.loads(request.body)
        if not isinstance(body, dict) or set(body) != {"start", "finish"}:
            raise ValueError("Expected start and finish locations")
        start, finish = parse_point(body["start"]), parse_point(body["finish"])
        if start == finish:
            raise ValueError("Start and finish must differ")
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        return error("invalid_request", str(exc), 400, request_id)
    try:
        result = default_service().plan(start, finish)
    except InvalidRoute as exc:
        return error("route_unavailable", str(exc), 422, request_id)
    except UnserviceableRoute as exc:
        return error("fuel_coverage_unavailable", str(exc), 422, request_id)
    except ProviderFailure:
        return error(
            "routing_provider_unavailable",
            "Routing service is temporarily unavailable",
            502,
            request_id,
        )
    except RuntimeError:
        logger.exception("optimization_failed request_id=%s", request_id)
        return error(
            "optimization_unavailable", "Fuel optimization could not complete", 503, request_id
        )
    result["request_id"] = request_id
    response = JsonResponse(result)
    response["X-Request-ID"] = request_id
    return response
