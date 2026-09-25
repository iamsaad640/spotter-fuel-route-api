from django.test import Client


def test_application_starts():
    assert Client().get("/missing").status_code == 404
