from django.urls import path

from . import views

urlpatterns = [
    path("otp/request", views.OtpRequestView.as_view()),
    path("otp/verify", views.OtpVerifyView.as_view()),
    path("token/refresh", views.RefreshView.as_view()),
    path("pin", views.PinSetView.as_view()),
    path("pin/login", views.PinLoginView.as_view()),
    path("devices", views.DeviceListView.as_view()),
    path("devices/<uuid:device_pk>", views.DeviceDetailView.as_view()),
    path("logout", views.LogoutView.as_view()),
]
