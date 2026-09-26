import pytest

from routefuel.domain import PlaceNotFoundError
from routefuel.places import PlaceDirectory, city_key, default_directory


def record(city, state, zip_code, lat, lon, zip_type="STANDARD", country="US"):
    return {
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "lat": str(lat),
        "long": str(lon),
        "zip_code_type": zip_type,
        "country": country,
    }


@pytest.fixture(scope="module")
def directory():
    return PlaceDirectory(
        [
            record("Springfield", "IL", "62701", 39.80, -89.65),
            record("Springfield", "IL", "62702", 39.82, -89.64),
            record("Springfield", "IL", "62703", 39.90, -89.60),
            record("Saint Louis", "MO", "63101", 38.63, -90.19),
            record("De Forest", "WI", "53532", 43.24, -89.34),
            record("Fpo", "AE", "09001", 50.0, 8.0, zip_type="MILITARY"),
        ]
    )


@pytest.mark.parametrize(
    "query",
    ["Springfield, IL", "springfield, il", "Springfield IL", "Springfield, Illinois, USA"],
)
def test_city_and_state_spellings(directory, query):
    place = directory.resolve(query)
    assert place.label == "Springfield, IL"
    assert (place.point.latitude, place.point.longitude) == (39.82, -89.64)


@pytest.mark.parametrize("query", ["St. Louis, MO", "st louis mo", "Saint-Louis, Missouri"])
def test_abbreviated_city_names(directory, query):
    assert directory.resolve(query).label == "Saint Louis, MO"


def test_zip_code_and_coordinates(directory):
    assert directory.resolve("62701-1234").point.latitude == 39.80
    assert directory.resolve(" 41.8781, -87.6298 ").point.longitude == -87.6298


def test_spacing_variants_share_a_key():
    assert city_key("DeForest") == city_key("De Forest")


@pytest.mark.parametrize(
    "query,message",
    [
        ("Springfeld, IL", "Did you mean: Springfield, IL?"),
        ("99999", "Unknown ZIP code"),
        ("Springfield", "City, ST"),
        ("Paris, France", "City, ST"),
    ],
)
def test_unknown_places_explain_the_fix(directory, query, message):
    with pytest.raises(PlaceNotFoundError, match=message):
        directory.resolve(query)


def test_military_zip_codes_are_excluded(directory):
    with pytest.raises(PlaceNotFoundError):
        directory.resolve("09001")


def test_bundled_dataset_resolves_major_cities():
    directory = default_directory()
    assert directory.resolve("New York, NY").point.latitude == pytest.approx(40.75, abs=0.2)
    assert directory.resolve("Los Angeles, CA").point.longitude == pytest.approx(-118.3, abs=0.2)
    assert directory.resolve("60601").label == "Chicago, IL 60601"
