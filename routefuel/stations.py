"""Immutable source CSV -> validated US stations with ZIP-derived city coordinates."""

import csv
import logging
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

import numpy as np

from .domain import Point, Station
from .geo import haversine_miles, unit_vectors
from .places import US_STATE_CODES, PlaceDirectory, default_directory

logger = logging.getLogger(__name__)
FUEL_PRICES_CSV = (
    Path(__file__).resolve().parent.parent / "data" / "fuel-prices-for-be-assessment.csv"
)
COLUMNS = [
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
]


def load_stations(path: Path, places: PlaceDirectory | None = None) -> tuple[Station, ...]:
    places = places or default_directory()
    by_id: dict[int, list[tuple[int, dict[str, str], Decimal]]] = defaultdict(list)
    rejected: dict[str, int] = defaultdict(int)
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != COLUMNS:
            raise ValueError("Unexpected fuel CSV schema")
        for line, row in enumerate(reader, start=2):
            state = row["State"].strip().upper()
            if state not in US_STATE_CODES:
                rejected["non_us"] += 1
                continue
            try:
                identifier = int(row["OPIS Truckstop ID"])
                price = Decimal(row["Retail Price"].strip())
                if identifier <= 0 or not price.is_finite() or price <= 0:
                    raise ValueError("Invalid ID or price")
                if not all(row[k].strip() for k in ("Truckstop Name", "City", "Address")):
                    raise ValueError("Incomplete station")
            except (ValueError, InvalidOperation):
                rejected["invalid"] += 1
                continue
            by_id[identifier].append((line, row, price))
    stations: list[Station] = []
    for identifier, records in sorted(by_id.items()):
        # Same ID at different locations is ambiguous: discard the entire ID.
        locations = {
            (
                r["City"].strip().casefold(),
                r["State"].strip().upper(),
                r["Address"].strip().casefold(),
            )
            for _, r, _ in records
        }
        if len(locations) != 1:
            rejected["conflicting_id"] += len(records)
            continue
        # Duplicate snapshots lack timestamps. The cheapest recorded price is optimistic;
        # use the highest observed price as a conservative, deterministic quote.
        line, row, price = max(records, key=lambda item: (item[2], -item[0]))
        place = places.city(row["City"], row["State"].strip().upper())
        if place is None:
            rejected["no_city_coordinate"] += len(records)
            continue
        stations.append(
            Station(
                identifier,
                row["Truckstop Name"].strip(),
                row["City"].strip(),
                row["State"].strip().upper(),
                row["Address"].strip(),
                price,
                place.point,
                line,
            )
        )
        rejected["duplicate_rows"] += len(records) - 1
    logger.info("stations_loaded usable=%s rejected=%s", len(stations), dict(rejected))
    return tuple(stations)


class StationIndex:
    def __init__(self, stations: tuple[Station, ...]):
        self.stations = stations
        self.latitudes = np.array([s.point.latitude for s in stations], dtype=float)
        self.longitudes = np.array([s.point.longitude for s in stations], dtype=float)
        self.unit_vectors = unit_vectors(self.latitudes, self.longitudes)
        self.prices = np.array([float(s.price) for s in stations], dtype=float)

    def __len__(self) -> int:
        return len(self.stations)

    def cheapest_near(self, point: Point, radius_miles: float) -> tuple[Station, float] | None:
        """Cheapest station within the radius, nearest first on equal price."""
        distances = haversine_miles(
            point.latitude, point.longitude, self.latitudes, self.longitudes
        )
        within = np.flatnonzero(distances <= radius_miles)
        if not len(within):
            return None
        best = within[np.lexsort((distances[within], self.prices[within]))[0]]
        return self.stations[best], float(distances[best])


@lru_cache(maxsize=1)
def default_station_index() -> StationIndex:
    return StationIndex(load_stations(FUEL_PRICES_CSV))
