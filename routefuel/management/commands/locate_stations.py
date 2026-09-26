import csv
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from routefuel.domain import Point, Station
from routefuel.exits import ExitIndex, Junction, exit_number
from routefuel.stations import LOCATION_COLUMNS, load_stations

USER_AGENT = "spotter-fuel-route-api/1.0 (+https://github.com/iamsaad640/spotter-fuel-route-api)"
JUNCTIONS_QUERY = """
[out:json][timeout:180];
area["ISO3166-2"="US-{state}"][admin_level=4]->.state;
node(area.state)[highway=motorway_junction][ref];
out;
"""


class Command(BaseCommand):
    help = (
        "Write data/station-locations.csv: stations whose address names a highway exit, "
        "placed at that exit's OpenStreetMap node. Run once; the API only reads the file."
    )

    def add_arguments(self, parser: Any) -> None:
        config = settings.FUEL_ROUTE
        parser.add_argument("--output", type=Path, default=config["STATION_LOCATIONS_CSV"])
        parser.add_argument("--overpass-url", default=config["OVERPASS_URL"])
        parser.add_argument(
            "--max-miles",
            type=float,
            default=15.0,
            help="Reject an exit farther than this from the station's city centre.",
        )
        parser.add_argument("--states", nargs="*", help="Limit to these state codes.")

    def handle(self, *args: Any, **options: Any) -> None:
        stations_by_state: dict[str, list[tuple[Station, str]]] = defaultdict(list)
        for station in load_stations(settings.FUEL_ROUTE["FUEL_PRICES_CSV"]):
            if ref := exit_number(station.address):
                stations_by_state[station.state].append((station, ref))
        states = sorted(options["states"] or stations_by_state)

        rows = []
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=200) as client:
            for state in states:
                index = ExitIndex(self._junctions(client, options["overpass_url"], state))
                located = 0
                for station, ref in stations_by_state[state]:
                    junction = index.nearest(ref, station.point, options["max_miles"])
                    if junction:
                        located += 1
                        rows.append(
                            (
                                station.id,
                                junction.point.latitude,
                                junction.point.longitude,
                                junction.osm_id,
                            )
                        )
                self.stdout.write(
                    f"{state}: {located}/{len(stations_by_state[state])} exits located"
                )
                time.sleep(1)  # Overpass fair use: one heavy query at a time.

        options["output"].parent.mkdir(parents=True, exist_ok=True)
        with options["output"].open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(LOCATION_COLUMNS)
            writer.writerows(sorted(rows))
        total = sum(len(stations_by_state[s]) for s in states)
        self.stdout.write(
            self.style.SUCCESS(
                f"Located {len(rows)} of {total} exit addresses -> {options['output']}"
            )
        )

    def _junctions(self, client: httpx.Client, url: str, state: str) -> list[Junction]:
        for attempt in range(4):
            response = client.post(url, data={"data": JUNCTIONS_QUERY.format(state=state)})
            if response.status_code == 200 and response.headers.get("content-type", "").startswith(
                "application/json"
            ):
                return [
                    Junction(
                        element["id"], element["tags"]["ref"], Point(element["lat"], element["lon"])
                    )
                    for element in response.json()["elements"]
                ]
            time.sleep(10 * 2**attempt)
        raise CommandError(f"Overpass did not return junctions for {state}")
