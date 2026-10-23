from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.errors import ApiError
from accounts.permissions import IsFarmer

from .models import Activity, CropCycle, Expense, Harvest, Plot, Processing, Sale
from .serializers import (ActivitySerializer, CropCycleSerializer, ExpenseSerializer, HarvestSerializer,
                          PlotSerializer, ProcessingSerializer, SaleSerializer, processed_stock, stock_kg)

PAGE = 500


def _soft_delete_cycle(cycle, now):
    for rel in (cycle.activities, cycle.expenses, cycle.harvests, cycle.sales, cycle.processings):
        rel.filter(deleted_at__isnull=True).update(deleted_at=now, updated_at=now)
    cycle.deleted_at = now
    cycle.save()


class BookViewSet(viewsets.ModelViewSet):
    """Every record is private to its farmer. Built for offline apps: the app creates the id,
    retries are safe, deletes are soft, and `?since=` pulls only what changed."""

    permission_classes = [IsFarmer]
    lookup_field = "client_id"
    lookup_value_regex = "[0-9a-fA-F-]{36}"
    model = None
    serializer_class = None

    def get_queryset(self):
        qs = self.model.objects.filter(owner=self.request.user)
        if self.action == "list":
            since = self.request.query_params.get("since")
            if since:
                dt = parse_datetime(since)
                if dt is None:
                    raise ApiError("bad_since", "since must be an ISO date-time", 400)
                return qs.filter(updated_at__gt=dt).order_by("updated_at")
            return qs.filter(deleted_at__isnull=True).order_by("updated_at")
        return qs.filter(deleted_at__isnull=True)

    def list(self, request, *a, **kw):
        rows = list(self.get_queryset()[:PAGE])
        data = self.get_serializer(rows, many=True).data
        nxt = rows[-1].updated_at.isoformat() if len(rows) == PAGE else None
        return Response({"results": data, "next_since": nxt})

    def create(self, request, *a, **kw):
        cid = request.data.get("client_id")
        if cid:
            try:
                existing = self.model.objects.filter(owner=request.user, client_id=cid).first()
            except Exception:
                raise ApiError("bad_client_id", "client_id must be a UUID", 400)
            if existing is not None:
                # A retry of a create that already reached us: answer as before, change nothing.
                return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(owner=request.user)
        return Response(s.data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        self.soft_delete(instance, timezone.now())

    def soft_delete(self, instance, now):
        instance.deleted_at = now
        instance.save()


class PlotViewSet(BookViewSet):
    model, serializer_class = Plot, PlotSerializer

    def soft_delete(self, instance, now):
        for c in instance.cycles.filter(deleted_at__isnull=True):
            _soft_delete_cycle(c, now)
        instance.deleted_at = now
        instance.save()


class CropCycleViewSet(BookViewSet):
    model, serializer_class = CropCycle, CropCycleSerializer

    def soft_delete(self, instance, now):
        _soft_delete_cycle(instance, now)


class ActivityViewSet(BookViewSet):
    model, serializer_class = Activity, ActivitySerializer


class ExpenseViewSet(BookViewSet):
    model, serializer_class = Expense, ExpenseSerializer


class HarvestViewSet(BookViewSet):
    model, serializer_class = Harvest, HarvestSerializer

    def soft_delete(self, instance, now):
        if stock_kg(instance.crop_cycle, exclude_harvest=instance) < 0:
            raise ApiError("stock_would_go_negative", "Sales already recorded are more than the remaining harvest. Remove those sales first.")
        instance.deleted_at = now
        instance.save()


class SaleViewSet(BookViewSet):
    model, serializer_class = Sale, SaleSerializer


class ProcessingViewSet(BookViewSet):
    model, serializer_class = Processing, ProcessingSerializer

    def soft_delete(self, instance, now):
        from .serializers import product_stock_kg
        if product_stock_kg(instance.crop_cycle, instance.product, exclude_processing=instance) < 0:
            raise ApiError("stock_would_go_negative", "Some of this has already been sold. Remove those sales first.")
        instance.deleted_at = now
        instance.save()


def _money(x) -> str:
    return str((x or Decimal("0")).quantize(Decimal("0.01")))


def _kg(x) -> str:
    return str((x or Decimal("0")).quantize(Decimal("0.001")))


def cycle_summary(cycle: CropCycle) -> dict:
    exp = cycle.expenses.filter(deleted_at__isnull=True).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    exp += cycle.processings.filter(deleted_at__isnull=True).aggregate(t=Sum("cost"))["t"] or Decimal("0")
    harvested = cycle.harvests.filter(deleted_at__isnull=True).aggregate(t=Sum("quantity_kg"))["t"] or Decimal("0")
    sold = cycle.sales.filter(deleted_at__isnull=True, product="").aggregate(t=Sum("quantity_kg"))["t"] or Decimal("0")
    processed = cycle.processings.filter(deleted_at__isnull=True).aggregate(t=Sum("input_kg"))["t"] or Decimal("0")
    revenue = cycle.sales.filter(deleted_at__isnull=True).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    out = {
        "crop_cycle": str(cycle.client_id), "crop": cycle.crop, "plot": cycle.plot.name, "status": cycle.status,
        "expenses": _money(exp), "revenue": _money(revenue), "profit": _money(revenue - exp),
        "harvested_kg": _kg(harvested), "sold_kg": _kg(sold), "processed_kg": _kg(processed), "stock_kg": _kg(harvested - sold - processed),
        "processed_stock": {k: _kg(v) for k, v in processed_stock(cycle).items()},
        "cost_per_kg": None, "avg_sale_rate_per_quintal": None,
    }
    if harvested > 0:
        out["cost_per_kg"] = _money(exp / harvested)
    raw_revenue = cycle.sales.filter(deleted_at__isnull=True, product="").aggregate(t=Sum("amount"))["t"] or Decimal("0")
    if sold > 0:
        out["avg_sale_rate_per_quintal"] = _money(raw_revenue / sold * 100)
    return out


def ledger_for(user, cycle_id=None) -> dict:
    cycles = CropCycle.objects.filter(owner=user, deleted_at__isnull=True).select_related("plot")
    if cycle_id:
        cycles = cycles.filter(client_id=cycle_id)
    rows = [cycle_summary(c) for c in cycles.order_by("-created_at")]
    general = Expense.objects.filter(owner=user, crop_cycle__isnull=True, deleted_at__isnull=True).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    total_exp = sum((Decimal(r["expenses"]) for r in rows), Decimal("0")) + (general if not cycle_id else Decimal("0"))
    total_rev = sum((Decimal(r["revenue"]) for r in rows), Decimal("0"))
    return {
        "cycles": rows,
        "general_expenses": _money(general),
        "totals": {"expenses": _money(total_exp), "revenue": _money(total_rev), "profit": _money(total_rev - total_exp)},
    }


class LedgerView(APIView):
    """Profit and loss per crop cycle, all computed on the server from the farmer's own records."""

    permission_classes = [IsFarmer]

    def get(self, request):
        return Response(ledger_for(request.user, request.query_params.get("crop_cycle")))


def stock_for(user) -> list[dict]:
    """Stock at home: the crop itself, and anything made from it (dried, ground, pressed...), one line each."""
    today = timezone.now().date()
    out = []
    for c in CropCycle.objects.filter(owner=user, deleted_at__isnull=True).select_related("plot"):
        batches = c.harvests.filter(deleted_at__isnull=True, shelf_life_days__isnull=False).order_by("date")
        expiry = None
        for h in batches:
            end = h.date + timedelta(days=h.shelf_life_days)
            expiry = end if expiry is None or end < expiry else expiry
        left = stock_kg(c)
        if left > 0:
            out.append({"crop_cycle": str(c.client_id), "crop": c.crop, "product": "", "stock_kg": _kg(left), "stock_quintal": str((left / 100).quantize(Decimal("0.01"))),
                        "earliest_shelf_life_end": expiry.isoformat() if expiry else None, "days_left": (expiry - today).days if expiry else None})
        for product, kg in processed_stock(c).items():
            made = c.processings.filter(deleted_at__isnull=True, product=product, shelf_life_days__isnull=False).order_by("date").first()
            end = made.date + timedelta(days=made.shelf_life_days) if made else None
            out.append({"crop_cycle": str(c.client_id), "crop": c.crop, "product": product, "stock_kg": _kg(kg), "stock_quintal": str((kg / 100).quantize(Decimal("0.01"))),
                        "earliest_shelf_life_end": end.isoformat() if end else None, "days_left": (end - today).days if end else None})
    return out


class StockView(APIView):
    permission_classes = [IsFarmer]

    def get(self, request):
        return Response({"stock": stock_for(request.user)})
