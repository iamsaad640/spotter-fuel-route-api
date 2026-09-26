"""Place stations whose address names a highway exit at that exit's OpenStreetMap node."""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .domain import Point
from .geo import haversine_miles

_EXIT_ADDRESS = re.compile(r",\s*EXIT\s+(\d+[A-Z]?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Junction:
    osm_id: int
    ref: str
    point: Point


def exit_number(address: str) -> str | None:
    """'I-44, EXIT 283 & US-69' -> '283'."""
    match = _EXIT_ADDRESS.search(address)
    return match[1].upper() if match else None


class ExitIndex:
    def __init__(self, junctions: Iterable[Junction]):
        self._by_ref: dict[str, list[Junction]] = defaultdict(list)
        for junction in junctions:
            for ref in junction.ref.upper().replace(" ", "").split(";"):
                self._by_ref[ref].append(junction)
                # Split exits (283A/283B) also answer to the plain number the CSV uses.
                if ref[-1:].isalpha():
                    self._by_ref[ref[:-1]].append(junction)

    def nearest(self, ref: str, near: Point, max_miles: float) -> Junction | None:
        candidates = self._by_ref.get(ref, [])
        if not candidates:
            return None
        distances = haversine_miles(
            near.latitude,
            near.longitude,
            [j.point.latitude for j in candidates],
            [j.point.longitude for j in candidates],
        )
        best = int(distances.argmin())
        return candidates[best] if distances[best] <= max_miles else None
