from django.urls import path

from . import views

urlpatterns = [
    path("", views.QuoteView.as_view()),
    path("places", views.PlacesView.as_view()),
    path("crops", views.CropsView.as_view()),
]
