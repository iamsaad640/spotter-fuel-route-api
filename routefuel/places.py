"""US place lookup backed by the bundled ZIP dataset, so no geocoding API is called."""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from difflib import get_close_matches
from functools import lru_cache
from statistics import median
from typing import Any

import zipcodes

from .domain import Place, PlaceNotFoundError, Point

STATE_CODES_BY_NAME = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}
US_STATE_CODES = frozenset(STATE_CODES_BY_NAME.values())
FORMAT_HINT = "Use 'City, ST', a 5-digit ZIP code, or 'latitude,longitude'"

_COORDINATES = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*,\s*([-+]?\d+(?:\.\d+)?)\s*$")
_ZIP_CODE = re.compile(r"^\s*(\d{5})(?:-\d{4})?\s*$")
_COUNTRY_SUFFIX = re.compile(r",?\s*(usa|us|united states(?: of america)?)\.?\s*$", re.IGNORECASE)
_TRAILING_ZIP = re.compile(r"\s+\d{5}(?:-\d{4})?$")
_CITY_ABBREVIATIONS = (
    (re.compile(r"\bst\.?\s"), "saint "),
    (re.compile(r"\bste\.?\s"), "sainte "),
    (re.compile(r"\bft\.?\s"), "fort "),
    (re.compile(r"\bmt\.?\s"), "mount "),
)


def city_key(city: str) -> str:
    """Canonical city name: 'St. Louis', 'saint louis' and 'SAINT-LOUIS' share one key."""
    ascii_name = unicodedata.normalize("NFKD", city).encode("ascii", "ignore").decode()
    key = f"{ascii_name.casefold().strip()} "
    for pattern, replacement in _CITY_ABBREVIATIONS:
        key = pattern.sub(replacement, key)
    return re.sub(r"[^a-z]", "", key)


def state_code(text: str) -> str | None:
    text = " ".join(text.replace(".", "").split())
    if text.upper() in US_STATE_CODES:
        return text.upper()
    return STATE_CODES_BY_NAME.get(text.casefold())


class PlaceDirectory:
    def __init__(self, records: Iterable[Mapping[str, Any]]):
        points_by_city: dict[tuple[str, str], list[Point]] = defaultdict(list)
        display_names: dict[tuple[str, str], str] = {}
        self._zip_codes: dict[str, Place] = {}
        for record in records:
            state = record["state"]
            if (
                record["country"] != "US"
                or state not in US_STATE_CODES
                or record["zip_code_type"] == "MILITARY"
                or not record["lat"]
            ):
                continue
            point = Point(float(record["lat"]), float(record["long"]))
            self._zip_codes[record["zip_code"]] = Place(
                f"{record['city']}, {state} {record['zip_code']}", point
            )
            key = (city_key(record["city"]), state)
            points_by_city[key].append(point)
            display_names.setdefault(key, record["city"])
        # A city spans many ZIP codes; the median is robust to outlying PO-box centroids.
        self._cities = {
            key: Place(
                f"{display_names[key]}, {key[1]}",
                Point(
                    round(median(p.latitude for p in points), 6),
                    round(median(p.longitude for p in points), 6),
                ),
            )
            for key, points in points_by_city.items()
        }
        self._city_keys_by_state: dict[str, list[str]] = defaultdict(list)
        for city, state in self._cities:
            self._city_keys_by_state[state].append(city)

    def city(self, name: str, state: str) -> Place | None:
        return self._cities.get((city_key(name), state))

    def resolve(self, query: str) -> Place:
        if match := _COORDINATES.match(query):
            return Place(query.strip(), Point(float(match[1]), float(match[2])))
        if match := _ZIP_CODE.match(query):
            if place := self._zip_codes.get(match[1]):
                return place
            raise PlaceNotFoundError(f"Unknown ZIP code '{match[1]}'")
        city, state = self._split_city_state(query)
        if place := self.city(city, state):
            return place
        suggestions = [
            self._cities[(key, state)].label
            for key in get_close_matches(city_key(city), self._city_keys_by_state[state], n=3)
        ]
        hint = f". Did you mean: {'; '.join(suggestions)}?" if suggestions else ""
        raise PlaceNotFoundError(f"Unknown city '{city.strip()}, {state}'{hint}")

    @staticmethod
    def _split_city_state(query: str) -> tuple[str, str]:
        text = _TRAILING_ZIP.sub("", _COUNTRY_SUFFIX.sub("", query.strip())).strip()
        if "," in text:
            city, state_text = text.rsplit(",", 1)
            if city.strip() and (state := state_code(state_text)):
                return city, state
        else:
            words = text.split()
            for size in (3, 2, 1):
                if len(words) > size and (state := state_code(" ".join(words[-size:]))):
                    return " ".join(words[:-size]), state
        raise PlaceNotFoundError(
            f"Could not read '{query.strip()}' as a US location. {FORMAT_HINT}"
        )


@lru_cache(maxsize=1)
def default_directory() -> PlaceDirectory:
    return PlaceDirectory(zipcodes.list_all())
