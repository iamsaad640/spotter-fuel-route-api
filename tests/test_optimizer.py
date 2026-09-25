from decimal import Decimal
from itertools import product

import pytest

from routefuel.domain import Candidate, Point, Station, UnserviceableRoute
from routefuel.optimizer import optimize


def candidate(mile, price, detour=0, id=1):
    return Candidate(
        Station(id, "Test", "Test", "TX", "Road", Decimal(str(price)), Point(32, -96), 2),
        mile,
        detour,
    )


def test_reachable_without_purchase():
    assert optimize((), 500) == ()


def test_gap_just_over_range_is_infeasible():
    with pytest.raises(UnserviceableRoute):
        optimize((candidate(501, 2),), 502)


def test_multiple_fills_and_full_trip_price():
    stops = optimize((candidate(400, 3, id=1), candidate(800, 2, id=2)), 1250)
    assert [p.candidate.station.id for p in stops] == [1, 2]
    assert sum(p.gallons for p in stops) == Decimal("75.0")


def test_buy_extra_when_next_station_is_expensive():
    stops = optimize((candidate(400, 2, id=1), candidate(600, 10, id=2)), 900)
    assert [p.candidate.station.id for p in stops] == [1]
    assert stops[0].gallons == Decimal("40.0")


def test_cheaper_station_ahead_only_buy_enough_to_reach_it():
    stops = optimize((candidate(400, 8, id=1), candidate(600, 2, id=2)), 900)
    assert [p.gallons for p in stops] == [Decimal("10.0"), Decimal("30.0")]


def test_detour_fuel_and_reachability():
    stops = optimize((candidate(480, 2, detour=12),), 510)
    assert len(stops) == 1
    assert float(stops[0].gallons) == pytest.approx(3.4)
    with pytest.raises(UnserviceableRoute):
        optimize((candidate(499, 2, detour=2),), 510)


def reference_cost(positions, prices, total, tank=5):
    # Integer gallons, exact enumeration of all possible station purchase amounts.
    best = float("inf")
    for purchases in product(range(tank + 1), repeat=len(positions)):
        fuel = tank
        last = 0
        cost = 0
        for pos, purchase, price in zip(positions, purchases, prices, strict=False):
            fuel -= pos - last
            if fuel < 0 or fuel + purchase > tank:
                break
            fuel += purchase
            cost += purchase * price
            last = pos
        else:
            if fuel >= total - last:
                best = min(best, cost)
    return best


@pytest.mark.parametrize("prices", product([2, 3, 7], repeat=3))
def test_against_exhaustive_integer_reference(prices):
    positions = (200, 400, 600)  # 20, 40, 60 gallons
    actual = optimize(
        tuple(
            candidate(pos, price, id=i)
            for i, (pos, price) in enumerate(zip(positions, prices, strict=False))
        ),
        900,
        initial_gallons=50,
    )
    assert sum(float(p.cost) for p in actual) == reference_cost((20, 40, 60), prices, 90, tank=50)


def test_at_500_miles_station_is_reachable_and_can_buy_fraction():
    stops = optimize((candidate(500, "2.50"),), 501)
    assert stops[0].gallons == Decimal("0.1")
    assert stops[0].cost == Decimal("0.25")


def test_skips_cheap_but_unreachable_detour():
    stops = optimize((candidate(480, 1, detour=21, id=1), candidate(490, 4, id=2)), 600)
    assert [p.candidate.station.id for p in stops] == [2]


def test_out_of_order_candidates_rejected():
    with pytest.raises(ValueError):
        optimize((candidate(200, 2), candidate(100, 3)), 800)
