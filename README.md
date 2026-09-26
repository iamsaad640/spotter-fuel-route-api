# Fuel Route API

A Django 6.1 API that obtains one driving route and computes the cheapest feasible fuel purchases along it. The provided Spotter CSV has no coordinates; station locations are **city-level estimates**, so the result optimizes over an approximate candidate set, not verified pump entrances.

## Run

With Docker (API on http://localhost:8000, Redis for the shared cache):

```bash
docker compose up --build
```

Without Docker, using [uv](https://docs.astral.sh/uv/):

```bash
make install   # uv sync --locked
make run       # development server on :8000
```

`requirements.txt` is exported from `uv.lock` for plain `pip install -r requirements.txt` setups. See `.env.example` for configuration.

## Request

Coordinate-only input uses **one external routing call**. The response geometry is GeoJSON `LineString`, suitable for rendering on a map. Text addresses are deliberately unsupported: they would need a geocoding provider and two additional calls.

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/fuel-route \
  -H 'Content-Type: application/json' \
  -d '{"start":{"latitude":32.7767,"longitude":-96.7970},"finish":{"latitude":34.0522,"longitude":-118.2437}}'
```

```json
{
  "route": {"type": "LineString", "coordinates": [[-96.797, 32.7767], [-118.2437, 34.0522]]},
  "route_miles": 1440.0,
  "fuel_stops": [{"opis_id": 123, "name": "Example", "address": "I-40", "city": "Example", "state": "NM", "location": [-106.6, 35.1], "mile_marker": 650.0, "estimated_one_way_detour_miles": 2.0, "price_per_gallon_usd": "3.10", "gallons": "40.0", "cost_usd": "124.00"}],
  "total_fuel_cost_usd": "124.00",
  "assumptions": {"starting_fuel_gallons": 50, "max_range_miles": 500, "mpg": 10, "station_locations": "city ZIP centroid approximation", "detours": "estimated straight-line round trip, not road-routed"},
  "request_id": "..."
}
```

Import `postman/spotter-fuel-route.postman_collection.json` for a success request and a validation failure.

The JSON above illustrates the **schema**, not an actual computed Dallas–Los Angeles response. Prices are static assessment data, not live pump quotes. Cost is purchases **during** the trip; the initial full 50-gallon tank is treated as already owned. A trip of at most 500 miles costs $0 under that assumption. Money is rounded half up to cents per purchase after optimizing at source precision. A 422 means no drivable route or no feasible fuel coverage; upstream failures return 502 and solver timeouts 503.

## Decisions

- **Routing:** OSRM demo endpoint, `https://router.project-osrm.org`, has a public non-commercial fair-use policy. `ROUTING_BASE_URL` can point to a dedicated OSRM-compatible deployment. One HTTP client is reused, with a 12-second timeout and no blind retry. Upstream errors are sanitized. See the [OSRM usage policy](https://github.com/Project-OSRM/osrm-backend/wiki/Api-usage-policy).
- **Data:** Original `data/fuel-prices-for-be-assessment.csv` is preserved unchanged (8,151 rows; columns: OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, Retail Price). There are repeated IDs and conflicting prices, stray whitespace, and Canadian provinces. Parsing filters non-US rows and invalid/non-positive/nonfinite prices, rejects IDs that refer to more than one city/address, then takes the **highest** observed price for repeated snapshots because there are no timestamps. Source line is retained. Unresolved locations are excluded and counted in load logs. City/state positions come from the offline `zipcodes` package, whose coordinates originate from [GeoNames](https://www.geonames.org/export/) (CC BY); attribution and terms belong to GeoNames. ZIP locations for each city are combined by median coordinate. This is a reproducible proxy, not address geocoding.
- **Candidates:** Densify provider geometry to at most two miles per segment. A KD-tree finds nearby segments; local projections produce an estimated perpendicular distance and monotonic route mile. Default corridor is 12 straight-line miles (`ROUTE_CORRIDOR_MILES`). No station routing calls.
- **Optimizer:** A mixed integer linear program has a binary visit variable, continuous purchased gallons, and continuous remaining fuel after every candidate. Conservation constraints include along-route mileage and an estimated round-trip detour. It enforces fuel to reach each candidate, a 50-gallon tank at the pump, and fuel for the destination. It minimizes price × gallons, preferring fewer stops on exact ties. This models partial fills, carrying cheap fuel past expensive stations, and skipped stops. The HiGHS solver has an 8-second cap and requires an optimal result; it never returns an unverified partial solution. Candidate matching is approximately O(S log V + V) for S stations and V densified vertices; optimization complexity is exponential in the worst case due to station-visit decisions.
- **Limits:** The original CSV lacks pump coordinates; ZIP centroid displacement and straight-line detours can change feasibility and the optimal answer. No separate route is computed for a detour. The endpoint checks a contiguous-US bounding envelope but cannot prove the point is inside the country boundary. A real service would obtain licensed pump coordinates and road-network detour costs, then use a spatial index and a routed final shortlist. No Redis, PostGIS, or workers are justified for this assessment size.

## Verify

```bash
make check   # ruff, mypy, pytest with coverage
make bench   # stage timings on a recorded cross-country route
```

The optimizer tests include an exhaustive bounded reference solver across price permutations, full/empty boundaries, sparse gaps, detours, and price inversions. Provider tests assert exactly one HTTP call and cover malformed JSON, invalid geometry, timeout, and no route. Benchmarks use a deterministic synthetic route, excluding external network latency. On the assessment runner (Python 3.12, cold process, synthetic 1,450-mile route), 6,622 US stations loaded in 1,293 ms, 146 candidates matched in 223 ms, and three stops optimized in 88 ms. Warm requests reuse the parsed station index. A complete warm Django request with a counting fake router took 298 ms and invoked that router once; the fake excludes network latency. This excludes live provider latency; outbound access to the demo service was unavailable in the assessment runtime. Exact timings vary by machine; run the script locally for yours. The GitHub workflow runs all quality checks on each PR.
