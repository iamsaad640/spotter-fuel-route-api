"""One error envelope for every API failure: {"error": {...}, "request_id": "..."}."""

import logging
from typing import Any

from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .domain import FuelPlanInfeasibleError, RouteNotFoundError, RoutingProviderError
from .middleware import current_request_id

logger = logging.getLogger(__name__)

DOMAIN_ERRORS: dict[type[Exception], tuple[int, str]] = {
    RouteNotFoundError: (status.HTTP_422_UNPROCESSABLE_ENTITY, "route_not_found"),
    FuelPlanInfeasibleError: (status.HTTP_422_UNPROCESSABLE_ENTITY, "fuel_plan_infeasible"),
    RoutingProviderError: (status.HTTP_502_BAD_GATEWAY, "routing_provider_unavailable"),
}


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error, "request_id": current_request_id()}


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    for error_type, (status_code, code) in DOMAIN_ERRORS.items():
        if isinstance(exc, error_type):
            # Provider errors can carry upstream detail; clients get a stable message.
            message = (
                "Routing service is temporarily unavailable"
                if isinstance(exc, RoutingProviderError)
                else str(exc)
            )
            return Response(error_body(code, message), status=status_code)

    response = exception_handler(exc, context)
    if response is None:
        logger.exception("unhandled_error", exc_info=exc)
        return Response(
            error_body("internal_error", "An unexpected error occurred"),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if isinstance(exc, ValidationError):
        response.data = error_body("invalid_request", "Request validation failed", exc.detail)
    elif isinstance(exc, APIException):
        response.data = error_body(exc.default_code, str(exc.detail))
    return response
