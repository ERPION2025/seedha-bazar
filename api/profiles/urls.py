from django.urls import path

from . import views

urlpatterns = [
    path("me", views.MeView.as_view()),
    path("me/delete", views.DeleteAccountView.as_view()),
    path("farmers/me", views.FarmerMeView.as_view()),
    path("farmers/me/join-org", views.JoinOrgView.as_view()),
    path("buyers/me", views.BuyerMeView.as_view()),
    path("orgs", views.OrgListView.as_view()),
    path("agent/farmers", views.AgentFarmersView.as_view()),
    path("agent/farmers/<int:user_id>/resend", views.AgentResendView.as_view()),
    path("agent/join-requests", views.AgentLinkRequestsView.as_view()),
    path("agent/join-requests/<int:pk>/approve", views.AgentLinkDecisionView.as_view(approve=True)),
    path("agent/join-requests/<int:pk>/reject", views.AgentLinkDecisionView.as_view(approve=False)),
]
