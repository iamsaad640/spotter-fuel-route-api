from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float


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
class Candidate:
    station: Station
    mile: float
    detour_miles: float  # estimated one-way straight line, never road measured


@dataclass(frozen=True)
class Purchase:
    candidate: Candidate
    gallons: Decimal
    cost: Decimal


class UnserviceableRoute(Exception):
    pass


class ProviderFailure(Exception):
    pass


class InvalidRoute(Exception):
    pass
