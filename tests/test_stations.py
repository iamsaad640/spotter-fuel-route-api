import csv
from pathlib import Path

from routefuel.stations import COLUMNS, load_stations


def test_csv_conflicts_duplicates_invalid_and_non_us(tmp_path: Path):
    path = tmp_path / "fuel.csv"
    with path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(COLUMNS)
        writer.writerow([1, "A", "Main", "Dallas", "TX", 1, "3.12"])
        writer.writerow([1, "A", "Main", "Dallas", "TX", 1, "3.58"])
        writer.writerow([2, "B", "A", "Dallas", "TX", 1, "2.50"])
        writer.writerow([2, "B", "Other", "Austin", "TX", 1, "2.50"])
        writer.writerow([3, "C", "A", "Toronto", "ON", 1, "1.00"])
        writer.writerow([4, "D", "A", "Dallas", "TX", 1, "nan"])
        writer.writerow([5, "E", "A", "Dallas", "TX", 1, "-1"])
    stations = load_stations(path)
    assert len(stations) == 1
    assert stations[0].id == 1
    assert str(stations[0].price) == "3.58"
    assert stations[0].source_row == 3


def test_real_csv_loads_us_only():
    stations = load_stations(Path(__file__).parents[1] / "data/fuel-prices-for-be-assessment.csv")
    assert len(stations) > 5000
    assert all(s.state not in {"ON", "AB", "BC"} for s in stations)
