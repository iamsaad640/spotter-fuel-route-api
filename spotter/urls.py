from django.urls import path

from routefuel.api import plan_route

urlpatterns = [path("api/v1/fuel-route", plan_route, name="fuel-route")]
