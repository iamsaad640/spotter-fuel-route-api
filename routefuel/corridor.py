"""Stations near the route, positioned by the mile at which the truck passes them."""

import numpy as np
from scipy.spatial import KDTree

from .domain import Candidate, Route
from .geo import EARTH_RADIUS_MILES, densify, haversine_miles, unit_vectors
from .stations import StationIndex

MAX_SEGMENT_MILES = 2.0
NEAREST_VERTICES = 4


def find_candidates(
    route: Route, stations: StationIndex, corridor_miles: float
) -> tuple[Candidate, ...]:
    if not np.isfinite(corridor_miles) or corridor_miles <= 0:
        raise ValueError("Route corridor must be positive")
    lat, lon = densify(
        np.array([p.latitude for p in route.points]),
        np.array([p.longitude for p in route.points]),
        MAX_SEGMENT_MILES,
    )
    segment_miles = haversine_miles(lat[:-1], lon[:-1], lat[1:], lon[1:])
    cumulative = np.concatenate(([0.0], np.cumsum(segment_miles)))
    if cumulative[-1] <= 0:
        return ()
    vertices = unit_vectors(lat, lon)
    tree = KDTree(vertices)

    # Densified vertices are at most MAX_SEGMENT_MILES apart, so a station inside the
    # corridor always has a vertex within this bound; everything else is discarded cheaply.
    bound = (corridor_miles + MAX_SEGMENT_MILES) / EARTH_RADIUS_MILES
    nearest, _ = tree.query(stations.unit_vectors, distance_upper_bound=bound)
    nearby = np.flatnonzero(np.isfinite(nearest))
    if not len(nearby):
        return ()

    k = min(NEAREST_VERTICES, len(vertices))
    _, vertex_ids = tree.query(stations.unit_vectors[nearby], k=k)
    vertex_ids = np.asarray(vertex_ids).reshape(len(nearby), k)
    starts = np.clip(np.hstack((vertex_ids - 1, vertex_ids)), 0, len(vertices) - 2)
    a, b = vertices[starts], vertices[starts + 1]
    p = stations.unit_vectors[nearby][:, None, :]
    ab = b - a
    length2 = np.einsum("ijk,ijk->ij", ab, ab)
    t = np.clip(np.einsum("ijk,ijk->ij", p - a, ab) / np.where(length2 > 0, length2, 1), 0, 1)
    distance = np.linalg.norm(p - (a + t[..., None] * ab), axis=2) * EARTH_RADIUS_MILES

    best = np.argmin(distance, axis=1)
    rows = np.arange(len(nearby))
    segment = starts[rows, best]
    offset = distance[rows, best]
    # Scale geometric length to the provider's road distance so miles match the route.
    mile = (cumulative[segment] + t[rows, best] * segment_miles[segment]) * (
        route.miles / cumulative[-1]
    )
    inside = (offset <= corridor_miles) & (mile > 0) & (mile < route.miles)
    candidates = [
        Candidate(stations.stations[i], float(m), float(d))
        for i, m, d in zip(nearby[inside], mile[inside], offset[inside], strict=True)
    ]
    return tuple(sorted(candidates, key=lambda c: (c.route_mile, c.station.id)))
