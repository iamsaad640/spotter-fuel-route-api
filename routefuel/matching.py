"""Project city centroids onto a densified polyline without per-station API calls."""

import math

import numpy as np
from scipy.spatial import cKDTree

from .domain import Candidate, Point, Station
from .routing import Route

EARTH_MILES = 3958.7613


def great_circle(a: Point, b: Point) -> float:
    p, q = math.radians(a.latitude), math.radians(b.latitude)
    dp, dl = q - p, math.radians(b.longitude - a.longitude)
    h = math.sin(dp / 2) ** 2 + math.cos(p) * math.cos(q) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MILES * math.asin(min(1.0, math.sqrt(h)))


def match_stations(
    route: Route, stations: tuple[Station, ...], corridor_miles: float = 12
) -> tuple[Candidate, ...]:
    if corridor_miles <= 0 or not math.isfinite(corridor_miles):
        raise ValueError("Route corridor must be positive")
    # Densify to at most two miles per segment so a distant endpoint cannot hide
    # a nearby point in the middle of a long straight geometry segment.
    points: list[Point] = [route.points[0]]
    for a, b in zip(route.points, route.points[1:], strict=False):
        count = max(1, math.ceil(great_circle(a, b) / 2))
        for j in range(1, count + 1):
            t = j / count
            points.append(
                Point(
                    a.latitude + t * (b.latitude - a.latitude),
                    a.longitude + t * (b.longitude - a.longitude),
                )
            )
    cumulative = [0.0]
    for a, b in zip(points, points[1:], strict=False):
        cumulative.append(cumulative[-1] + great_circle(a, b))
    if cumulative[-1] <= 0:
        return ()
    # Equirectangular projection for nearest-neighbor discovery; final distance is
    # evaluated in station-local coordinates on adjacent route segments.
    latitude = math.radians(sum(p.latitude for p in points) / len(points))
    scale = 69.0 * math.cos(latitude)
    coords = np.array([(p.longitude * scale, p.latitude * 69.0) for p in points])
    tree = cKDTree(coords)
    candidates = []
    for station in stations:
        target = np.array([station.point.longitude * scale, station.point.latitude * 69.0])
        _, indices = tree.query(target, k=min(8, len(points)))
        best = (float("inf"), 0.0)
        for index in np.atleast_1d(indices):
            for j in (int(index) - 1, int(index)):
                if not 0 <= j < len(points) - 1:
                    continue
                a, b = points[j], points[j + 1]
                local_scale = 69.0 * math.cos(math.radians(station.point.latitude))
                ax = (a.longitude - station.point.longitude) * local_scale
                ay = (a.latitude - station.point.latitude) * 69.0
                bx = (b.longitude - station.point.longitude) * local_scale
                by = (b.latitude - station.point.latitude) * 69.0
                length2 = (bx - ax) ** 2 + (by - ay) ** 2
                t = (
                    max(0.0, min(1.0, -(ax * (bx - ax) + ay * (by - ay)) / length2))
                    if length2
                    else 0.0
                )
                distance = math.hypot(ax + t * (bx - ax), ay + t * (by - ay))
                mile = (
                    (cumulative[j] + t * (cumulative[j + 1] - cumulative[j]))
                    * route.miles
                    / cumulative[-1]
                )
                best = min(best, (distance, mile))
        if best[0] <= corridor_miles and 0 < best[1] < route.miles:
            candidates.append(Candidate(station, best[1], best[0]))
    return tuple(sorted(candidates, key=lambda c: (c.mile, c.station.id)))
