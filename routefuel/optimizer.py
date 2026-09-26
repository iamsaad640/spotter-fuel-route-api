"""Cheapest fuel stops along a fixed route.

Stops are chosen by dynamic programming over (station, tank level when leaving it), with
tank levels in FUEL_STEP increments. Pump-to-pump consumption includes the detour off and
back onto the route and is rounded up to a whole step, so every accepted plan is feasible.
Purchases for the chosen stops are then computed exactly with the classic fixed-sequence
rule: buy just enough to reach the next cheaper stop, otherwise fill the tank.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from .domain import Candidate, FuelPlanInfeasibleError, Purchase, Vehicle

FUEL_STEP = 0.1
DEFAULT_VEHICLE = Vehicle()
CENT = Decimal("0.01")
TIE_BREAK_PER_STOP = 1e-6
TOLERANCE = 1e-9


def optimize(
    candidates: tuple[Candidate, ...],
    route_miles: float,
    *,
    starting_gallons: float,
    vehicle: Vehicle = DEFAULT_VEHICLE,
    stop_penalty_usd: float = 0.0,
) -> tuple[Purchase, ...]:
    if not math.isfinite(route_miles) or route_miles <= 0:
        raise ValueError("Route distance must be positive")
    if not 0 <= starting_gallons <= vehicle.tank_gallons:
        raise ValueError("Starting fuel must be within tank capacity")
    if stop_penalty_usd < 0:
        raise ValueError("Stop penalty cannot be negative")
    if any(not math.isfinite(c.offset_miles) or c.offset_miles < 0 for c in candidates):
        raise ValueError("Invalid station offset")
    miles = [c.route_mile for c in candidates]
    if miles != sorted(miles) or (miles and (miles[0] < 0 or miles[-1] >= route_miles)):
        raise ValueError("Candidates must be ordered within the route")
    if route_miles / vehicle.miles_per_gallon <= starting_gallons + TOLERANCE:
        return ()
    if not candidates:
        raise FuelPlanInfeasibleError("No fuel station lies along this route")
    stops = _choose_stops(
        candidates, route_miles, starting_gallons, vehicle, stop_penalty_usd or TIE_BREAK_PER_STOP
    )
    return _purchases(stops, route_miles, starting_gallons, vehicle)


def _choose_stops(
    candidates: tuple[Candidate, ...],
    route_miles: float,
    starting_gallons: float,
    vehicle: Vehicle,
    stop_penalty: float,
) -> list[Candidate]:
    # Node 0 is the trip start; node j >= 1 is candidates[j - 1].
    count = len(candidates) + 1
    levels = round(vehicle.tank_gallons / FUEL_STEP) + 1
    level = np.arange(levels)
    miles = np.array([0.0, *(c.route_mile for c in candidates)])
    offsets = np.array([0.0, *(c.offset_miles for c in candidates)])
    step_prices = np.array([0.0, *(float(c.station.price) for c in candidates)]) * FUEL_STEP

    def steps_to(origins: np.ndarray, mile: float, offset: float) -> np.ndarray:
        gallons = (offsets[origins] + mile - miles[origins] + offset) / vehicle.miles_per_gallon
        return np.ceil(gallons / FUEL_STEP - TOLERANCE).astype(np.int64)

    # cost[j, f]: cheapest spend to leave node j with f steps of fuel. The right half is
    # padding so reads past a full tank resolve to infinity instead of wrapping.
    cost = np.full((count, 2 * levels), np.inf)
    cost[0, math.floor(starting_gallons / FUEL_STEP + TOLERANCE)] = 0.0
    previous_node = np.zeros((count, levels), dtype=np.int64)
    arrival_level = np.zeros((count, levels), dtype=np.int64)
    first = 1
    for j in range(1, count):
        while miles[j] - miles[first] > vehicle.range_miles:
            first += 1
        origins = np.concatenate(([0], np.arange(first, j)))
        steps = steps_to(origins, miles[j], offsets[j])
        reachable = steps < levels
        origins, steps = origins[reachable], steps[reachable]
        if not len(origins):
            continue
        arriving = cost[origins[:, None], level[None, :] + steps[:, None]]
        best_origin = np.argmin(arriving, axis=0)
        arrival_cost = arriving[best_origin, level]
        # Leaving with f after arriving with a <= f costs arrival_cost[a] + price * (f - a).
        relative = arrival_cost - step_prices[j] * level
        cheapest = np.minimum.accumulate(relative)
        cheapest_arrival = np.maximum.accumulate(np.where(relative == cheapest, level, 0))
        cost[j, :levels] = cheapest + step_prices[j] * level + stop_penalty
        arrival_level[j] = cheapest_arrival
        previous_node[j] = origins[best_origin[cheapest_arrival]]

    finish_steps = steps_to(np.arange(count), route_miles, 0.0)
    cheapest_at_least = np.minimum.accumulate(cost[:, :levels][:, ::-1], axis=1)[:, ::-1]
    finish_cost = np.where(
        finish_steps < levels,
        cheapest_at_least[np.arange(count), np.minimum(finish_steps, levels - 1)],
        np.inf,
    )
    node = int(np.argmin(finish_cost))
    if not np.isfinite(finish_cost[node]):
        raise FuelPlanInfeasibleError(
            f"Stations along this route are more than {vehicle.range_miles:.0f} miles apart"
        )
    fuel_level = finish_steps[node] + int(np.argmin(cost[node, finish_steps[node] : levels]))
    stops = []
    while node:
        stops.append(candidates[node - 1])
        origin = int(previous_node[node, fuel_level])
        steps = steps_to(np.array([origin]), miles[node], offsets[node])[0]
        fuel_level = int(arrival_level[node, fuel_level] + steps)
        node = origin
    return stops[::-1]


def _purchases(
    stops: list[Candidate], route_miles: float, starting_gallons: float, vehicle: Vehicle
) -> tuple[Purchase, ...]:
    mpg, tank = vehicle.miles_per_gallon, vehicle.tank_gallons
    # legs[k]: gallons from node k to node k + 1, where node 0 is the start and the last
    # node is the finish; both sit on the route.
    marks = [(0.0, 0.0), *((s.route_mile, s.offset_miles) for s in stops), (route_miles, 0.0)]
    legs = [
        (offset_a + mile_b - mile_a + offset_b) / mpg
        for (mile_a, offset_a), (mile_b, offset_b) in zip(marks, marks[1:], strict=False)
    ]
    fuel = starting_gallons
    purchases = []
    for k, stop in enumerate(stops, start=1):
        fuel -= legs[k - 1]
        arrival = fuel
        target = None
        needed = 0.0
        for later in range(k, len(legs)):
            needed += legs[later]
            if needed > tank + TOLERANCE:
                break
            is_finish = later + 1 == len(legs)
            if is_finish or stops[later].station.price < stop.station.price:
                target = needed
                break
        buy = tank - fuel if target is None else max(0.0, target - fuel)
        fuel += buy
        gallons = Decimal(str(buy)).quantize(CENT, rounding=ROUND_HALF_UP)
        if gallons > 0:
            purchases.append(
                Purchase(
                    stop,
                    gallons,
                    (gallons * stop.station.price).quantize(CENT, rounding=ROUND_HALF_UP),
                    round(max(0.0, arrival), 2),
                )
            )
    return tuple(purchases)
