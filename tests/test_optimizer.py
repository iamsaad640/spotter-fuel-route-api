from decimal import Decimal
from itertools import product

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from routefuel.domain import Candidate, FuelPlanInfeasibleError, Point, Station, Vehicle
from routefuel.optimizer import optimize


def candidate(mile, price, offset=0.0, id=1):
    return Candidate(
        Station(id, "Test", "Test", "TX", "Road", Decimal(str(price)), Point(32, -96), 2),
        mile,
        offset,
    )


def total(purchases):
    return sum(p.cost for p in purchases)


def test_full_tank_covers_a_trip_within_range():
    assert optimize((), 500, starting_gallons=50) == ()


def test_empty_tank_buys_every_gallon_at_the_origin_for_a_short_trip():
    stops = optimize((candidate(0, "3.00"),), 238, starting_gallons=0)
    assert [p.gallons for p in stops] == [Decimal("23.80")]
    assert total(stops) == Decimal("71.40")


def test_gap_just_over_range_is_infeasible():
    with pytest.raises(FuelPlanInfeasibleError):
        optimize((candidate(501, 2),), 502, starting_gallons=50)


def test_multiple_fills_and_full_trip_price():
    stops = optimize((candidate(400, 3, id=1), candidate(800, 2, id=2)), 1250, starting_gallons=50)
    assert [p.candidate.station.id for p in stops] == [1, 2]
    assert sum(p.gallons for p in stops) == Decimal("75.00")


def test_buy_extra_when_next_station_is_expensive():
    stops = optimize((candidate(400, 2, id=1), candidate(600, 10, id=2)), 900, starting_gallons=50)
    assert [p.candidate.station.id for p in stops] == [1]
    assert stops[0].gallons == Decimal("40.00")


def test_cheaper_station_ahead_only_buy_enough_to_reach_it():
    stops = optimize((candidate(400, 8, id=1), candidate(600, 2, id=2)), 900, starting_gallons=50)
    assert [p.gallons for p in stops] == [Decimal("10.00"), Decimal("30.00")]
    assert [p.fuel_on_arrival_gallons for p in stops] == [10.0, 0.0]


def test_detour_fuel_and_reachability():
    stops = optimize((candidate(480, 2, offset=12),), 510, starting_gallons=50)
    assert len(stops) == 1
    assert float(stops[0].gallons) == pytest.approx(3.4)
    with pytest.raises(FuelPlanInfeasibleError):
        optimize((candidate(499, 2, offset=2),), 510, starting_gallons=50)


def test_at_500_miles_station_is_reachable_and_can_buy_fraction():
    stops = optimize((candidate(500, "2.50"),), 501, starting_gallons=50)
    assert stops[0].gallons == Decimal("0.10")
    assert stops[0].cost == Decimal("0.25")


def test_skips_cheap_but_unreachable_detour():
    stops = optimize(
        (candidate(480, 1, offset=21, id=1), candidate(490, 4, id=2)), 600, starting_gallons=50
    )
    assert [p.candidate.station.id for p in stops] == [2]


def test_stop_penalty_trades_a_small_saving_for_one_fewer_stop():
    stations = (candidate(0, "3.00", id=1), candidate(100, "2.95", id=2))
    cheapest = optimize(stations, 300, starting_gallons=0)
    assert [p.candidate.station.id for p in cheapest] == [1, 2]
    assert total(cheapest) == Decimal("89.00")
    fewer_stops = optimize(stations, 300, starting_gallons=0, stop_penalty_usd=10)
    assert [p.candidate.station.id for p in fewer_stops] == [1]
    assert total(fewer_stops) == Decimal("90.00")


@pytest.mark.parametrize(
    "stations,route_miles",
    [((candidate(200, 2), candidate(100, 3)), 800), ((candidate(900, 2),), 800)],
)
def test_candidates_must_be_ordered_within_the_route(stations, route_miles):
    with pytest.raises(ValueError):
        optimize(stations, route_miles, starting_gallons=50)


def reference_cost(legs, prices, tank, start):
    """Exhaustive search over whole-gallon purchases; legs[i] ends at station i or the finish."""
    best = float("inf")
    for purchases in product(range(tank + 1), repeat=len(prices)):
        fuel, cost = start, 0
        for leg, bought, price in zip(legs, purchases, prices, strict=False):
            fuel -= leg
            if fuel < 0 or fuel + bought > tank:
                break
            fuel += bought
            cost += bought * price
        else:
            if fuel >= legs[-1]:
                best = min(best, cost)
    return best


@pytest.mark.parametrize("prices", product([2, 3, 7], repeat=3))
def test_matches_exhaustive_reference_on_price_permutations(prices):
    miles = (200, 400, 600)
    stations = tuple(candidate(miles[i], prices[i], id=i) for i in range(3))
    actual = optimize(stations, 900, starting_gallons=50)
    assert total(actual) == reference_cost((20, 20, 20, 30), prices, tank=50, start=50)


@settings(max_examples=150, deadline=None)
@given(
    legs=st.lists(st.integers(0, 5), min_size=2, max_size=5),
    prices=st.lists(st.sampled_from(["1", "2", "3", "5", "8"]), min_size=4, max_size=4),
    start=st.integers(0, 5),
)
def test_matches_exhaustive_reference_on_random_small_trips(legs, prices, start):
    small_truck = Vehicle(tank_gallons=5, miles_per_gallon=10)
    miles = [10 * sum(legs[: i + 1]) for i in range(len(legs) - 1)]
    stations = tuple(candidate(mile, prices[i], id=i) for i, mile in enumerate(miles))
    route_miles = 10 * sum(legs)
    assume(10 * start < route_miles and miles[-1] < route_miles)
    expected = reference_cost(legs, [int(p) for p in prices[: len(miles)]], tank=5, start=start)
    if expected == float("inf"):
        with pytest.raises(FuelPlanInfeasibleError):
            optimize(stations, route_miles, starting_gallons=start, vehicle=small_truck)
    else:
        actual = optimize(stations, route_miles, starting_gallons=start, vehicle=small_truck)
        assert total(actual) == expected
