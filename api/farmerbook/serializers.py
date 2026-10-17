from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from accounts.errors import ApiError

from .models import Activity, CropCycle, Expense, Harvest, Plot, Sale
from .units import UNITS, to_kg

Q = Decimal("0.001")


def stock_kg(cycle, exclude_harvest=None, exclude_sale=None) -> Decimal:
    h = cycle.harvests.filter(deleted_at__isnull=True)
    s = cycle.sales.filter(deleted_at__isnull=True)
    if exclude_harvest is not None:
        h = h.exclude(pk=exclude_harvest.pk)
    if exclude_sale is not None:
        s = s.exclude(pk=exclude_sale.pk)
    return (h.aggregate(t=Sum("quantity_kg"))["t"] or Decimal("0")) - (s.aggregate(t=Sum("quantity_kg"))["t"] or Decimal("0"))


class RecordSerializer(serializers.ModelSerializer):
    client_id = serializers.UUIDField(required=False)
    deleted = serializers.SerializerMethodField()

    def get_deleted(self, obj):
        return obj.deleted_at is not None

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request is not None:
            for f in fields.values():
                # A farmer can only point at their own live records.
                if isinstance(f, serializers.SlugRelatedField):
                    f.queryset = f.queryset.filter(owner=request.user, deleted_at__isnull=True)
        return fields

    def validate_client_id(self, value):
        if self.instance is not None and value != self.instance.client_id:
            raise serializers.ValidationError("client_id cannot change")
        return value

    COMMON = ["client_id", "created_at", "updated_at", "deleted"]


class PlotSerializer(RecordSerializer):
    class Meta:
        model = Plot
        fields = RecordSerializer.COMMON + ["name", "area_acres", "soil", "irrigation", "location_note"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_area_acres(self, v):
        if v <= 0 or v > 100000:
            raise serializers.ValidationError("Enter a sensible area in acres")
        return v


class CropCycleSerializer(RecordSerializer):
    plot = serializers.SlugRelatedField(slug_field="client_id", queryset=Plot.objects.all())

    class Meta:
        model = CropCycle
        fields = RecordSerializer.COMMON + ["plot", "crop", "variety", "season", "sowing_date", "expected_harvest_date", "status"]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, a):
        s, e = a.get("sowing_date", getattr(self.instance, "sowing_date", None)), a.get("expected_harvest_date", getattr(self.instance, "expected_harvest_date", None))
        if s and e and e < s:
            raise serializers.ValidationError("Expected harvest cannot be before sowing")
        return a


class ActivitySerializer(RecordSerializer):
    crop_cycle = serializers.SlugRelatedField(slug_field="client_id", queryset=CropCycle.objects.all())

    class Meta:
        model = Activity
        fields = RecordSerializer.COMMON + ["crop_cycle", "kind", "date", "note", "done"]
        read_only_fields = ["created_at", "updated_at"]


class ExpenseSerializer(RecordSerializer):
    crop_cycle = serializers.SlugRelatedField(slug_field="client_id", queryset=CropCycle.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Expense
        fields = RecordSerializer.COMMON + ["crop_cycle", "category", "amount", "date", "note"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_amount(self, v):
        if v <= 0 or v > Decimal("100000000"):
            raise serializers.ValidationError("Enter a sensible amount")
        return v


class QuantityMixin:
    def _kg(self, a):
        unit = a.get("unit", getattr(self.instance, "unit", None))
        qty = a.get("quantity", getattr(self.instance, "quantity", None))
        bag = a.get("bag_weight_kg", getattr(self.instance, "bag_weight_kg", None))
        if unit not in UNITS:
            raise serializers.ValidationError({"unit": f"Unit must be one of {', '.join(UNITS)}"})
        if qty is None or qty <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be more than zero"})
        if unit == "bag" and not bag:
            raise serializers.ValidationError({"bag_weight_kg": "Tell us how many kg one bag weighs"})
        return qty, unit, bag, to_kg(qty, unit, bag)


class HarvestSerializer(QuantityMixin, RecordSerializer):
    crop_cycle = serializers.SlugRelatedField(slug_field="client_id", queryset=CropCycle.objects.all())
    quantity_kg = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)

    class Meta:
        model = Harvest
        fields = RecordSerializer.COMMON + ["crop_cycle", "date", "quantity", "unit", "bag_weight_kg", "quantity_kg", "grade", "storage_note", "shelf_life_days"]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, a):
        qty, unit, bag, kg = self._kg(a)
        a["quantity_kg"] = kg
        if self.instance is not None:
            cycle = self.instance.crop_cycle
            if stock_kg(cycle, exclude_harvest=self.instance) + kg < 0:
                raise ApiError("stock_would_go_negative", "Sales already recorded are more than this harvest quantity")
        return a


class SaleSerializer(QuantityMixin, RecordSerializer):
    crop_cycle = serializers.SlugRelatedField(slug_field="client_id", queryset=CropCycle.objects.all())
    quantity_kg = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Sale
        fields = RecordSerializer.COMMON + ["crop_cycle", "date", "quantity", "unit", "bag_weight_kg", "quantity_kg", "rate", "amount", "channel", "buyer_note"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_rate(self, v):
        if v <= 0 or v > Decimal("10000000"):
            raise serializers.ValidationError("Enter a sensible rate")
        return v

    def validate(self, a):
        qty, unit, bag, kg = self._kg(a)
        rate = a.get("rate", getattr(self.instance, "rate", None))
        cycle = a.get("crop_cycle", getattr(self.instance, "crop_cycle", None))
        available = stock_kg(cycle, exclude_sale=self.instance)
        if kg > available:
            raise ApiError("insufficient_stock", f"Only {available.quantize(Q)} kg is in stock for this crop. Record the harvest first.", available_kg=str(available.quantize(Q)))
        a["quantity_kg"] = kg
        a["amount"] = (qty * rate).quantize(Decimal("0.01"))
        return a
