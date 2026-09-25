from decimal import Decimal

from routefuel.domain import Point, Station
from routefuel.matching import match_stations
from routefuel.routing import Route


def station(id, lon, lat=35):
    return Station(id, "S", "C", "TX", "A", Decimal("3"), Point(lat, lon), id)


def test_progress_and_corridor_and_order():
    route = Route((Point(35, -100), Point(35, -95), Point(35, -90)), 600)
    stations = (station(3, -91), station(1, -98), station(2, -96, 35.1), station(4, -92, 37))
    matches = match_stations(route, stations)
    assert [m.station.id for m in matches] == [1, 2, 3]
    assert [m.mile for m in matches] == sorted(m.mile for m in matches)
    assert matches[1].detour_miles > 0


def test_station_behind_start_and_away_are_excluded():
    route = Route((Point(35, -100), Point(35, -95)), 300)
    assert match_stations(route, (station(1, -101), station(2, -98, 37))) == ()
