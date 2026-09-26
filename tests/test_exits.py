import csv
import io
from unittest.mock import patch

import httpx
import pytest
from django.core.management import call_command
from django.test import override_settings

from routefuel.domain import Point
from routefuel.exits import ExitIndex, Junction, exit_number
from routefuel.stations import COLUMNS, load_exit_locations, load_stations

BIG_CABIN = Point(36.5428, -95.2208)


@pytest.mark.parametrize(
    "address,expected",
    [
        ("I-44, EXIT 283 & US-69", "283"),
        ("I-8, EXIT 119 & SR-85", "119"),
        ("US-41/US-141, EXIT 176 & CR-B", "176"),
        ("I-35, Exit 12a", "12A"),
        ("US-40 & SR-13", None),
        ("34 MILE WEST OF EXIT 11/146", None),
    ],
)
def test_exit_number(address, expected):
    assert exit_number(address) == expected


def test_nearest_exit_prefers_the_closest_matching_ref_within_range():
    index = ExitIndex(
        [
            Junction(1, "283", Point(36.568, -95.213)),
            Junction(2, "283", Point(34.0, -97.0)),
            Junction(3, "284A;284B", Point(36.58, -95.20)),
        ]
    )
    assert index.nearest("283", BIG_CABIN, 15).osm_id == 1
    assert index.nearest("284", BIG_CABIN, 15).osm_id == 3
    assert index.nearest("283", Point(40.0, -100.0), 15) is None
    assert index.nearest("999", BIG_CABIN, 15) is None


def write_prices(path, rows):
    with path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(COLUMNS)
        writer.writerows(rows)


def test_stations_use_exit_locations_when_available(tmp_path):
    prices = tmp_path / "prices.csv"
    write_prices(
        prices,
        [
            [7, "WOODSHED", "I-44, EXIT 283 & US-69", "Big Cabin", "OK", 307, "3.00"],
            [8, "TOWN STOP", "US-69", "Big Cabin", "OK", 307, "3.10"],
        ],
    )
    locations = tmp_path / "locations.csv"
    locations.write_text("opis_id,latitude,longitude,osm_node_id\n7,36.5612,-95.2179,602949924\n")
    stations = {
        s.id: s for s in load_stations(prices, exit_locations=load_exit_locations(locations))
    }
    assert stations[7].point == Point(36.5612, -95.2179)
    assert stations[7].location_source == "osm_exit"
    assert stations[8].location_source == "city_centroid"


def test_locate_stations_command_writes_matched_exits(tmp_path):
    prices = tmp_path / "prices.csv"
    write_prices(
        prices,
        [
            [7, "WOODSHED", "I-44, EXIT 283 & US-69", "Big Cabin", "OK", 307, "3.00"],
            [9, "FAR AWAY", "I-40, EXIT 1", "Big Cabin", "OK", 307, "3.00"],
        ],
    )
    output = tmp_path / "locations.csv"
    replies = iter(
        [
            httpx.Response(504),
            httpx.Response(
                200,
                json={
                    "elements": [
                        {"id": 602949924, "lat": 36.5612, "lon": -95.2179, "tags": {"ref": "283"}},
                        {"id": 5, "lat": 35.2, "lon": -99.9, "tags": {"ref": "1"}},
                    ]
                },
            ),
        ]
    )
    client = httpx.Client(transport=httpx.MockTransport(lambda _: next(replies)))
    config = {
        "FUEL_PRICES_CSV": prices,
        "STATION_LOCATIONS_CSV": output,
        "OVERPASS_URL": "https://x",
    }
    with (
        override_settings(FUEL_ROUTE=config),
        patch("routefuel.management.commands.locate_stations.httpx.Client", return_value=client),
        patch("routefuel.management.commands.locate_stations.time.sleep"),
    ):
        call_command("locate_stations", "--states", "OK", stdout=io.StringIO())
    assert load_exit_locations(output) == {7: Point(36.5612, -95.2179)}
