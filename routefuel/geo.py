"""Vectorized spherical geometry on arrays of latitude/longitude degrees."""

import numpy as np
from numpy.typing import ArrayLike, NDArray

EARTH_RADIUS_MILES = 3958.7613

FloatArray = NDArray[np.float64]


def haversine_miles(
    lat1: ArrayLike, lon1: ArrayLike, lat2: ArrayLike, lon2: ArrayLike
) -> FloatArray:
    phi1, lam1, phi2, lam2 = (
        np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2)
    )
    h = (
        np.sin((phi2 - phi1) / 2) ** 2
        + np.cos(phi1) * np.cos(phi2) * np.sin((lam2 - lam1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))


def unit_vectors(lat: ArrayLike, lon: ArrayLike) -> FloatArray:
    """Points on the unit sphere; chord length times Earth radius approximates short arcs."""
    phi, lam = np.radians(np.asarray(lat, dtype=float)), np.radians(np.asarray(lon, dtype=float))
    return np.column_stack((np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)))


def densify(
    lat: FloatArray, lon: FloatArray, max_step_miles: float
) -> tuple[FloatArray, FloatArray]:
    """Insert interpolated vertices so no segment is longer than ``max_step_miles``."""
    steps = np.maximum(
        1, np.ceil(haversine_miles(lat[:-1], lon[:-1], lat[1:], lon[1:]) / max_step_miles)
    )
    steps = steps.astype(np.int64)
    segment = np.repeat(np.arange(len(steps)), steps)
    step_in_segment = np.arange(steps.sum()) - np.repeat(np.cumsum(steps) - steps, steps) + 1
    fraction = step_in_segment / steps[segment]
    dense_lat = lat[segment] + fraction * (lat[segment + 1] - lat[segment])
    dense_lon = lon[segment] + fraction * (lon[segment + 1] - lon[segment])
    return np.concatenate(([lat[0]], dense_lat)), np.concatenate(([lon[0]], dense_lon))


def simplify(xy: FloatArray, tolerance: float) -> NDArray[np.intp]:
    """Indices kept by Ramer-Douglas-Peucker, using distance to the segment, not the line."""
    keep = np.zeros(len(xy), dtype=bool)
    keep[[0, -1]] = True
    pending = [(0, len(xy) - 1)]
    while pending:
        start, end = pending.pop()
        if end - start < 2:
            continue
        a, b = xy[start], xy[end]
        inner = xy[start + 1 : end]
        ab = b - a
        length2 = float(ab @ ab)
        t = np.clip((inner - a) @ ab / length2, 0.0, 1.0) if length2 else np.zeros(len(inner))
        distance = np.linalg.norm(inner - (a + t[:, None] * ab), axis=1)
        farthest = int(np.argmax(distance))
        if distance[farthest] > tolerance:
            split = start + 1 + farthest
            keep[split] = True
            pending += [(start, split), (split, end)]
    return np.flatnonzero(keep)
