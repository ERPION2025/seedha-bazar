from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from accounts.errors import ApiError

from .models import Activity, CropCycle, Expense, Harvest, Plot, Processing, Sale
from .units import UNITS, to_kg

Q = Decimal("0.001")


def stock_kg(cycle, exclude_harvest=None, exclude_sale=None, exclude_processing=None) -> Decimal:
    """Kg of the crop itself in stock: harvested, less sold as the crop, less what went into processing."""
    h = cycle.harvests.filter(deleted_at__isnull=True)
    s = cycle.sales.filter(deleted_at__isnull=True, product="")
    p = cycle.processings.filter(deleted_at__isnull=True)
    if exclude_harvest is not None:
        h = h.exclude(pk=exclude_harvest.pk)
    if exclude_sale is not None:
        s = s.exclude(pk=exclude_sale.pk)
    if exclude_processing is not None:
        p = p.exclude(pk=exclude_processing.pk)
    zero = Decimal("0")
    return (h.aggregate(t=Sum("quantity_kg"))["t"] or zero) - (s.aggregate(t=Sum("quantity_kg"))["t"] or zero) - (p.aggregate(t=Sum("input_kg"))["t"] or zero)


def product_stock_kg(cycle, product: str, exclude_sale=None, exclude_processing=None) -> Decimal:
    """Kg of a processed product in stock: made in this cycle, less sold."""
    made = cycle.processings.filter(deleted_at__isnull=True, product=product)
    sold = cycle.sales.filter(deleted_at__isnull=True, product=product)
    if exclude_sale is not None:
        sold = sold.exclude(pk=exclude_sale.pk)
    if exclude_processing is not None:
        made = made.exclude(pk=exclude_processing.pk)
    zero = Decimal("0")
    return (made.aggregate(t=Sum("quantity_kg"))["t"] or zero) - (sold.aggregate(t=Sum("quantity_kg"))["t"] or zero)


def processed_stock(cycle) -> dict:
    """{product: kg left} for everything made in this cycle that is still in stock."""
    keys = set(cycle.processings.filter(deleted_at__isnull=True).values_list("product", flat=True))
    out = {k: product_stock_kg(cycle, k) for k in keys}
    return {k: v for k, v in out.items() if v > 0}


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
        fields = RecordSerializer.COMMON + ["crop_cycle", "product", "date", "quantity", "unit", "bag_weight_kg", "quantity_kg", "rate", "amount", "channel", "buyer_note"]
        read_only_fields = ["created_at", "updated_at"]
        extra_kwargs = {"product": {"required": False, "allow_blank": True}}

    def validate_rate(self, v):
        if v <= 0 or v > Decimal("10000000"):
            raise serializers.ValidationError("Enter a sensible rate")
        return v

    def validate(self, a):
        qty, unit, bag, kg = self._kg(a)
        rate = a.get("rate", getattr(self.instance, "rate", None))
        cycle = a.get("crop_cycle", getattr(self.instance, "crop_cycle", None))
        product = a.get("product", getattr(self.instance, "product", "")) or ""
        a["product"] = product
        available = product_stock_kg(cycle, product, exclude_sale=self.instance) if product else stock_kg(cycle, exclude_sale=self.instance)
        if kg > available:
            raise ApiError("insufficient_stock", f"Only {available.quantize(Q)} kg is in stock for this crop. Record the harvest first.", available_kg=str(available.quantize(Q)))
        a["quantity_kg"] = kg
        a["amount"] = (qty * rate).quantize(Decimal("0.01"))
        return a


class ProcessingSerializer(QuantityMixin, RecordSerializer):
    crop_cycle = serializers.SlugRelatedField(slug_field="client_id", queryset=CropCycle.objects.all())
    quantity_kg = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)

    class Meta:
        model = Processing
        fields = RecordSerializer.COMMON + ["crop_cycle", "date", "product", "input_kg", "quantity", "unit", "bag_weight_kg", "quantity_kg", "cost",
                                            "packaging", "pack_size_g", "shelf_life_days", "note"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_product(self, v):
        from catalog import PRODUCTS
        if v not in PRODUCTS:
            raise serializers.ValidationError("Choose something from the list")
        return v

    def validate_input_kg(self, v):
        if v <= 0:
            raise serializers.ValidationError("Enter how much you are processing")
        return v

    def validate_cost(self, v):
        if v < 0 or v > Decimal("100000000"):
            raise serializers.ValidationError("Enter a sensible amount")
        return v

    def validate(self, a):
        qty, unit, bag, kg = self._kg(a)
        cycle = a.get("crop_cycle", getattr(self.instance, "crop_cycle", None))
        input_kg = a.get("input_kg", getattr(self.instance, "input_kg", None))
        available = stock_kg(cycle, exclude_processing=self.instance)
        if input_kg > available:
            raise ApiError("insufficient_stock", f"Only {available.quantize(Q)} kg is in stock for this crop. Record the harvest first.", available_kg=str(available.quantize(Q)))
        if kg > input_kg * Decimal("1.6"):
            raise serializers.ValidationError({"quantity": "The product is more than the crop you put in. Check the quantity and unit."})
        a["quantity_kg"] = kg
        return a
