from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health),
    path("api/auth/", include("accounts.urls")),
    path("api/farmerbook/", include("farmerbook.urls")),
    path("api/rates/", include("rates.urls")),
    path("api/", include("profiles.urls")),
    path("", include("web.urls")),
]
