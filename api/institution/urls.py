"""Institution Connect: the URL map of its own site. Nothing from the farmer, FPO or buyer site is reachable here."""
from django.urls import path

from config.urls import health
from web import auth_views, help_views, notify_views

from . import views

urlpatterns = [
    path("health/", health),
    path("login/", auth_views.login_view),
    path("login/verify/", auth_views.verify_view),
    path("login/resend/", auth_views.resend_view),
    path("login/consent/", auth_views.consent_view),
    path("logout/", auth_views.logout_view),
    path("", views.dashboard),
    path("choose/", views.choose),
    path("weather/", views.weather),
    path("advisories/<int:pk>/", views.advisory_detail),
    path("farmers/", views.farmers),
    path("farmers/add/", views.farmer_add),
    path("farmers/<int:pk>/", views.farmer_detail),
    path("orgs/", views.orgs),
    path("orgs/add/", views.org_add),
    path("orgs/<int:pk>/", views.org_detail),
    path("loans/", views.loans),
    path("offers/", views.offers),
    path("offers/<int:pk>/", views.offer_detail),
    path("offers/<int:pk>/act/", views.offer_act),
    path("notices/", views.notices),
    path("issues/", views.issues),
    path("issues/<int:pk>/", views.issue_detail),
    path("help/<int:pk>/reply/", help_views.reply),
    path("help/media/<str:kind>/<int:pk>/<str:field>/", help_views.media),
    path("groups/", views.groups),
    path("groups/<int:pk>/", views.group_detail),
    path("map/", views.map_page),
    path("map/data/", views.map_data),
    path("notifications/", notify_views.page),
    path("push/subscribe/", notify_views.subscribe),
    path("push/test/", notify_views.test_push),
    path("manifest.webmanifest", notify_views.manifest),
    path("sw.js", notify_views.service_worker),
]
