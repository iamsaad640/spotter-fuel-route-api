"""Immutable source CSV -> validated US stations with ZIP-derived city coordinates."""

import csv
import logging
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from statistics import median

import zipcodes

from .domain import Point, Station

logger = logging.getLogger(__name__)
US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
    "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
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


@lru_cache(maxsize=8192)
def city_point(city: str, state: str) -> Point | None:
    matches = zipcodes.filter_by(city=city, state=state)
    if not matches and city != city.title():
        matches = zipcodes.filter_by(city=city.title(), state=state)
    points = [(float(r["lat"]), float(r["long"])) for r in matches if r["lat"] and r["long"]]
    if not points:
        return None
    return Point(median(p[0] for p in points), median(p[1] for p in points))


def load_stations(path: Path) -> tuple[Station, ...]:
    by_id: dict[int, list[tuple[int, dict[str, str], Decimal]]] = defaultdict(list)
    rejected: dict[str, int] = defaultdict(int)
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != COLUMNS:
            raise ValueError("Unexpected fuel CSV schema")
        for line, row in enumerate(reader, start=2):
            state = row["State"].strip().upper()
            if state not in US_STATES:
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
        point = city_point(row["City"].strip(), row["State"].strip().upper())
        if point is None:
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
                point,
                line,
            )
        )
        rejected["duplicate_rows"] += len(records) - 1
    logger.info("station_index_loaded usable=%s rejected=%s", len(stations), dict(rejected))
    return tuple(stations)


@lru_cache(maxsize=1)
def default_stations() -> tuple[Station, ...]:
    return load_stations(
        Path(__file__).resolve().parent.parent / "data/fuel-prices-for-be-assessment.csv"
    )
