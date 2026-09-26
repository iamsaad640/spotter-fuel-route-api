from django.urls import path

from .views import FuelRouteView, RouteMapView, health

urlpatterns = [
    path("api/v1/fuel-route", FuelRouteView.as_view(), name="fuel-route"),
    path("map", RouteMapView.as_view(), name="route-map"),
    path("healthz", health, name="health"),
]
