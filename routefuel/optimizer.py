"""Minimum-cost continuous purchases with optional station visits (MILP)."""

import math
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from .domain import Candidate, Purchase, UnserviceableRoute

TANK_GALLONS = 50.0
MPG = 10.0
CENT = Decimal("0.01")


def optimize(
    candidates: tuple[Candidate, ...], route_miles: float, initial_gallons: float = 50.0
) -> tuple[Purchase, ...]:
    if not math.isfinite(route_miles) or route_miles <= 0:
        raise ValueError("Route distance must be positive")
    if not 0 <= initial_gallons <= TANK_GALLONS:
        raise ValueError("Starting fuel must be within tank capacity")
    if route_miles / MPG <= initial_gallons + 1e-9:
        return ()
    # Each candidate has x=purchased gallons, z=visit (binary), f=fuel after
    # rejoining the route. Equalities conserve fuel. Inequalities enforce fuel
    # before detouring, tank size at the pump, and sufficient fuel for return.
    n = len(candidates)
    if not n:
        raise UnserviceableRoute("No feasible fuel stop covers the route")
    count = 3 * n
    x_offset, z_offset, f_offset = 0, n, 2 * n
    positions = [c.mile for c in candidates]
    if any(
        not math.isfinite(c.mile) or not math.isfinite(c.detour_miles) or c.detour_miles < 0
        for c in candidates
    ):
        raise ValueError("Invalid station geometry")
    if positions != sorted(positions) or positions[0] <= 0 or positions[-1] >= route_miles:
        raise ValueError("Candidates must be ordered strictly within route")
    rows = lil_matrix((4 * n + 1, count), dtype=float)
    lower = np.full(4 * n + 1, -np.inf)
    upper = np.full(4 * n + 1, np.inf)
    for i, candidate in enumerate(candidates):
        delta = (candidate.mile - (positions[i - 1] if i else 0.0)) / MPG
        detour = candidate.detour_miles / MPG
        prev = initial_gallons if i == 0 else 0.0
        if i:
            rows[4 * i, f_offset + i - 1] = 1
            rows[4 * i + 1, f_offset + i - 1] = 1
            rows[4 * i + 2, f_offset + i - 1] = 1
        # f_i = prev + x_i - delta - 2 detour*z_i
        rows[4 * i, f_offset + i] = -1
        rows[4 * i, x_offset + i] = 1
        rows[4 * i, z_offset + i] = -2 * detour
        lower[4 * i] = upper[4 * i] = delta - prev
        # prev - delta - detour*z >= 0: reach the station before buying.
        rows[4 * i + 1, z_offset + i] = -detour
        lower[4 * i + 1] = delta - prev
        # prev + x - delta - detour*z <= capacity: tank at the pump.
        rows[4 * i + 2, x_offset + i] = 1
        rows[4 * i + 2, z_offset + i] = -detour
        upper[4 * i + 2] = TANK_GALLONS + delta - prev
        # Purchases require an actual visit.
        rows[4 * i + 3, x_offset + i] = 1
        rows[4 * i + 3, z_offset + i] = -TANK_GALLONS
        upper[4 * i + 3] = 0
    rows[-1, f_offset + n - 1] = 1
    lower[-1] = (route_miles - positions[-1]) / MPG
    objective = np.zeros(count)
    objective[:n] = [float(c.station.price) for c in candidates]
    objective[n : 2 * n] = 1e-7  # favor fewer visits only at equal economic cost
    bounds = Bounds(np.zeros(count), np.array([TANK_GALLONS] * n + [1.0] * n + [TANK_GALLONS] * n))
    integrality = np.array([0] * n + [1] * n + [0] * n)
    result = milp(
        objective,
        integrality=integrality,
        bounds=bounds,
        constraints=LinearConstraint(rows.tocsr(), lower, upper),
        options={"time_limit": 8.0, "mip_rel_gap": 0.0},
    )
    if result.status == 2:
        raise UnserviceableRoute("Fuel stops cannot bridge the route with a 500-mile tank")
    if result.status != 0 or result.x is None:
        raise RuntimeError("Fuel optimization did not converge")
    purchases = []
    for i, candidate in enumerate(candidates):
        if result.x[i] > 1e-6:
            gallons = Decimal(str(round(float(result.x[i]), 6)))
            purchases.append(
                Purchase(
                    candidate,
                    gallons,
                    (gallons * candidate.station.price).quantize(CENT, rounding=ROUND_HALF_UP),
                )
            )
    return tuple(purchases)
