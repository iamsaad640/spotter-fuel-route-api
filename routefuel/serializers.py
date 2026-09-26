import math
from typing import Any

import numpy as np
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .domain import FuelPlan, Place, PlaceNotFoundError, Point
from .geo import simplify
from .places import FORMAT_HINT, default_directory

CONTIGUOUS_US_LATITUDE = (24.0, 50.0)
CONTIGUOUS_US_LONGITUDE = (-125.0, -66.0)
# About 50 m at US latitudes: invisible on a road map, and it cuts a cross-country
# route from ~35k to a few thousand vertices.
ROUTE_DISPLAY_TOLERANCE_DEGREES = 0.0005


@extend_schema_field(
    {
        "oneOf": [
            {"type": "string", "example": "Chicago, IL"},
            {
                "type": "object",
                "properties": {
                    "latitude": {"type": "number", "example": 41.8781},
                    "longitude": {"type": "number", "example": -87.6298},
                },
                "required": ["latitude", "longitude"],
            },
        ],
        "description": f"A place in the contiguous US. {FORMAT_HINT}, or a coordinate object.",
    }
)
class LocationField(serializers.Field):
    default_error_messages = {
        "invalid": f"Expected a place name or a coordinate object. {FORMAT_HINT}.",
        "coordinates": "Coordinates must be an object with numeric latitude and longitude only.",
        "outside_us": "Location must be in the contiguous United States.",
    }

    def to_internal_value(self, data: Any) -> Place:
        if isinstance(data, dict):
            place = self._from_coordinates(data)
        elif isinstance(data, str) and data.strip():
            try:
                place = default_directory().resolve(data)
            except PlaceNotFoundError as exc:
                raise serializers.ValidationError(str(exc)) from exc
        else:
            self.fail("invalid")
        lat, lon = place.point.latitude, place.point.longitude
        if not (
            CONTIGUOUS_US_LATITUDE[0] <= lat <= CONTIGUOUS_US_LATITUDE[1]
            and CONTIGUOUS_US_LONGITUDE[0] <= lon <= CONTIGUOUS_US_LONGITUDE[1]
        ):
            self.fail("outside_us")
        return place

    def _from_coordinates(self, data: dict[str, Any]) -> Place:
        if set(data) != {"latitude", "longitude"}:
            self.fail("coordinates")
        lat, lon = data["latitude"], data["longitude"]
        if any(isinstance(v, bool) or not isinstance(v, int | float) for v in (lat, lon)):
            self.fail("coordinates")
        if not (math.isfinite(lat) and math.isfinite(lon)):
            self.fail("coordinates")
        return Place(f"{lat:.5f},{lon:.5f}", Point(float(lat), float(lon)))

    def to_representation(self, value: Place) -> dict[str, Any]:
        return {
            "label": value.label,
            "latitude": value.point.latitude,
            "longitude": value.point.longitude,
        }


class FuelRouteRequestSerializer(serializers.Serializer):
    start = LocationField()
    finish = LocationField()
    starting_fuel_gallons = serializers.FloatField(
        min_value=0,
        max_value=50,
        default=0,
        help_text="Fuel already in the tank. The default 0 bills every gallon of the trip.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        unknown = sorted(set(self.initial_data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError({name: "Unknown field." for name in unknown})
        if attrs["start"].point == attrs["finish"].point:
            raise serializers.ValidationError("Start and finish must be different places.")
        return attrs


class RoundedFloatField(serializers.FloatField):
    def __init__(self, digits: int, **kwargs: Any):
        self.digits = digits
        super().__init__(read_only=True, **kwargs)

    def to_representation(self, value: float) -> float:
        return round(float(value), self.digits)


class PlaceSerializer(serializers.Serializer):
    label = serializers.CharField()
    latitude = serializers.FloatField(source="point.latitude")
    longitude = serializers.FloatField(source="point.longitude")


class FuelStopSerializer(serializers.Serializer):
    opis_id = serializers.IntegerField(source="candidate.station.id")
    name = serializers.CharField(source="candidate.station.name")
    address = serializers.CharField(source="candidate.station.address")
    city = serializers.CharField(source="candidate.station.city")
    state = serializers.CharField(source="candidate.station.state")
    latitude = serializers.FloatField(source="candidate.station.point.latitude")
    longitude = serializers.FloatField(source="candidate.station.point.longitude")
    route_mile = RoundedFloatField(1, source="candidate.route_mile")
    miles_off_route = RoundedFloatField(1, source="candidate.offset_miles")
    price_per_gallon_usd = serializers.CharField(source="candidate.station.price")
    gallons = serializers.DecimalField(max_digits=8, decimal_places=2)
    cost_usd = serializers.DecimalField(max_digits=10, decimal_places=2, source="cost")
    fuel_on_arrival_gallons = RoundedFloatField(2)


class AssumptionsSerializer(serializers.Serializer):
    tank_gallons = serializers.FloatField()
    miles_per_gallon = serializers.FloatField()
    range_miles = serializers.FloatField()
    starting_fuel_gallons = serializers.FloatField()
    stop_penalty_usd = serializers.FloatField()
    station_corridor_miles = serializers.FloatField()
    station_locations = serializers.CharField()


class MetaSerializer(serializers.Serializer):
    request_id = serializers.CharField()
    routing_calls = serializers.IntegerField()
    elapsed_ms = serializers.IntegerField()


class FuelRouteResponseSerializer(serializers.Serializer):
    start = PlaceSerializer()
    finish = PlaceSerializer()
    distance_miles = RoundedFloatField(1, source="plan.route.miles")
    drive_time_hours = RoundedFloatField(1, source="plan.route.duration_hours")
    total_fuel_cost_usd = serializers.DecimalField(
        max_digits=10, decimal_places=2, source="plan.total_cost"
    )
    gallons_purchased = serializers.DecimalField(
        max_digits=10, decimal_places=2, source="plan.gallons_purchased"
    )
    fuel_stops = FuelStopSerializer(source="plan.purchases", many=True)
    map_url = serializers.URLField()
    route = serializers.SerializerMethodField(
        help_text="GeoJSON LineString, simplified to about 50 m for display."
    )
    assumptions = AssumptionsSerializer()
    meta = MetaSerializer()

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_route(self, result: dict[str, Any]) -> dict[str, Any]:
        plan: FuelPlan = result["plan"]
        xy = np.array([(p.longitude, p.latitude) for p in plan.route.points])
        kept = xy[simplify(xy, ROUTE_DISPLAY_TOLERANCE_DEGREES)]
        return {"type": "LineString", "coordinates": np.round(kept, 5).tolist()}
