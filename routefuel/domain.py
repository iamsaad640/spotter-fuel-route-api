from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Place:
    label: str
    point: Point


@dataclass(frozen=True)
class Station:
    id: int
    name: str
    city: str
    state: str
    address: str
    price: Decimal
    point: Point
    source_row: int


@dataclass(frozen=True)
class Vehicle:
    tank_gallons: float = 50.0
    miles_per_gallon: float = 10.0

    @property
    def range_miles(self) -> float:
        return self.tank_gallons * self.miles_per_gallon


@dataclass(frozen=True)
class Route:
    points: tuple[Point, ...]
    miles: float
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class Candidate:
    station: Station
    route_mile: float
    offset_miles: float  # straight-line distance to the route, never road measured


@dataclass(frozen=True)
class Purchase:
    candidate: Candidate
    gallons: Decimal
    cost: Decimal
    fuel_on_arrival_gallons: float


@dataclass(frozen=True)
class FuelPlan:
    route: Route
    purchases: tuple[Purchase, ...]
    starting_gallons: float

    @property
    def total_cost(self) -> Decimal:
        return sum((p.cost for p in self.purchases), Decimal("0.00"))

    @property
    def gallons_purchased(self) -> Decimal:
        return sum((p.gallons for p in self.purchases), Decimal("0.00"))


class PlaceNotFoundError(ValueError):
    pass


class RouteNotFoundError(Exception):
    pass


class RoutingProviderError(Exception):
    pass


class FuelPlanInfeasibleError(Exception):
    pass


class OptimizationError(Exception):
    pass
