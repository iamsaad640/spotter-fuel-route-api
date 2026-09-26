import gzip
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from routefuel.domain import FuelPlanInfeasibleError, Point, Route, Station
from routefuel.routing import OSRMRouter
from routefuel.service import FuelRoutePlanner
from routefuel.stations import StationIndex, default_station_index

FIXTURE = Path(__file__).parent / "fixtures/osrm_new_york_los_angeles.json.gz"
NEW_YORK, LOS_ANGELES = Point(40.7128, -74.0060), Point(34.0522, -118.2437)


class FixedRouter:
    def __init__(self, route):
        self._route = route

    def route(self, start, finish):
        return self._route


@pytest.fixture(scope="module")
def cross_country_plan():
    recorded = gzip.decompress(FIXTURE.read_bytes())
    router = OSRMRouter(
        "https://router.example",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=recorded))
        ),
    )
    return FuelRoutePlanner(router, default_station_index()).plan(NEW_YORK, LOS_ANGELES)


def test_recorded_cross_country_plan_respects_range_and_buys_the_whole_trip(cross_country_plan):
    plan = cross_country_plan
    stops = [p.candidate for p in plan.purchases]
    marks = [0.0, *(s.route_mile for s in stops), plan.route.miles]
    assert stops[0].route_mile == 0.0
    assert max(b - a for a, b in zip(marks, marks[1:], strict=False)) <= 500
    detour_gallons = sum(2 * s.offset_miles for s in stops) / 10
    assert float(plan.gallons_purchased) == pytest.approx(
        plan.route.miles / 10 + detour_gallons, abs=0.1
    )
    assert all(p.fuel_on_arrival_gallons >= 0 for p in plan.purchases)
    assert all(p.gallons >= 10 for p in plan.purchases[1:])


def test_origin_station_is_the_cheapest_nearby_and_not_repeated():
    near_cheap = Station(1, "Near", "C", "TX", "A", Decimal("2.50"), Point(35.0, -100.1), 1)
    near_dear = Station(2, "Dear", "C", "TX", "A", Decimal("3.50"), Point(35.0, -100.01), 2)
    route = Route((Point(35, -100), Point(35, -98)), 113)
    plan = FuelRoutePlanner(FixedRouter(route), StationIndex((near_cheap, near_dear))).plan(
        route.points[0], route.points[-1]
    )
    assert [p.candidate.station.id for p in plan.purchases] == [1]
    assert plan.purchases[0].candidate.route_mile == 0.0
    assert plan.total_cost == Decimal("28.25")


def test_empty_tank_without_a_nearby_station_explains_the_fix():
    far = Station(1, "Far", "C", "TX", "A", Decimal("3"), Point(36.0, -100), 1)
    route = Route((Point(35, -100), Point(35, -98)), 113)
    planner = FuelRoutePlanner(FixedRouter(route), StationIndex((far,)))
    with pytest.raises(FuelPlanInfeasibleError, match="starting_fuel_gallons"):
        planner.plan(route.points[0], route.points[-1])
    assert planner.plan(route.points[0], route.points[-1], starting_gallons=50).purchases == ()
