from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("plots", views.PlotViewSet, basename="plot")
router.register("cycles", views.CropCycleViewSet, basename="cycle")
router.register("activities", views.ActivityViewSet, basename="activity")
router.register("expenses", views.ExpenseViewSet, basename="expense")
router.register("harvests", views.HarvestViewSet, basename="harvest")
router.register("sales", views.SaleViewSet, basename="sale")
router.register("processings", views.ProcessingViewSet, basename="processing")

urlpatterns = [
    path("ledger", views.LedgerView.as_view()),
    path("stock", views.StockView.as_view()),
    path("", include(router.urls)),
]
