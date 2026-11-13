"""The Seedha Bazar shop: ready-to-sell products made by farmers, FPOs, NGOs and their groups (packed food, handloom,
handicrafts, clothing, décor...), sold to households and businesses with Seedha Bazar in the middle.

- Producers list a product with their price and stock. Seedha Bazar reviews it (and may change the price) before it goes live.
- Buyers pay the reviewed price plus Seedha Bazar's buyer fee; producers receive the price less a small seller fee.
- Buyers and producers never see each other's phone numbers; Seedha Bazar runs confirmation, delivery and payment.
- Every unit sold, added or corrected is a stock movement, so the producer's inventory is always explained.
"""
from decimal import Decimal
from decimal import Decimal as D

from django.conf import settings
from django.db import models
from django.utils import timezone

CATEGORIES = [
    ("food", "Ready-to-eat and packed food", "🍯"), ("staples", "Grains, pulses, flour and spices", "🌾"), ("fresh", "Fresh produce", "🥬"),
    ("dairy", "Dairy, eggs, honey", "🥛"), ("handloom", "Handloom and textiles", "🧵"), ("handicraft", "Handicrafts", "🏺"),
    ("clothing", "Clothing", "👗"), ("decor", "Home décor", "🪔"), ("wellness", "Herbal and wellness", "🌿"), ("other", "Other", "🛍️"),
]
CATEGORY_CHOICES = [(k, label) for k, label, _ in CATEGORIES]
FOOD_CATEGORIES = {"food", "staples", "fresh", "dairy", "wellness"}


GST_RATES = [(D("0"), "0% (exempt or nil)"), (D("5"), "5%"), (D("12"), "12%"), (D("18"), "18%")]


class SellerSettings(models.Model):
    """What Seedha Bazar needs from a seller for pickups, courier bookings, GST invoices and payouts."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shop_seller")
    legal_name = models.CharField(max_length=160, blank=True, help_text="Name on invoices: the farmer, FPO or NGO")
    gstin = models.CharField(max_length=15, blank=True, help_text="Only if GST-registered; then invoices are tax invoices")
    address = models.CharField(max_length=300, blank=True, help_text="Pickup address")
    village = models.CharField(max_length=120, blank=True)
    district = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=60, blank=True)
    pincode = models.CharField(max_length=6, blank=True)
    pickup_phone = models.CharField(max_length=20, blank=True, help_text="For the courier; never shown to buyers")
    allow_self_pickup = models.BooleanField(default=False, help_text="Buyers may collect from this address after Seedha Bazar confirms")
    payout_upi = models.CharField(max_length=80, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def ready_to_ship(self) -> bool:
        return bool(self.address and self.pincode and self.district and self.state)


class FeeRule(models.Model):
    """Seedha Bazar's commission, per category: a small share from the producer and a platform fee from the buyer."""

    category = models.CharField(max_length=12, choices=CATEGORY_CHOICES, unique=True)
    seller_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("3"), help_text="Taken from the producer's price")
    buyer_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5"), help_text="Added to the price the buyer pays")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category"]


class Product(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Waiting for review"
        LIVE = "live", "On sale"
        PAUSED = "paused", "Paused"
        REJECTED = "rejected", "Not approved"

    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shop_products")
    organisation = models.ForeignKey("profiles.Organisation", null=True, blank=True, on_delete=models.SET_NULL, related_name="shop_products",
                                     help_text="When an FPO, NGO or group sells it")
    category = models.CharField(max_length=12, choices=CATEGORY_CHOICES)
    title = models.CharField(max_length=120)
    description = models.TextField(max_length=2000, blank=True)
    pack = models.CharField(max_length=60, help_text="What one unit is: 500 g pack, 1 saree, set of 4...")
    photo = models.ImageField(upload_to="shop/", blank=True)
    asked_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="The producer's price for one unit")
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Price after Seedha Bazar's review; this is what is charged")
    b2b_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Price per unit for business orders of b2b_min or more")
    b2b_min = models.PositiveIntegerField(null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    max_per_order = models.PositiveIntegerField(default=20)
    fssai_no = models.CharField(max_length=14, blank=True, help_text="Needed for packed food")
    shelf_life_days = models.PositiveIntegerField(null=True, blank=True)
    origin = models.CharField(max_length=120, blank=True, help_text="Village, district: shown to buyers")

    class Fulfilment(models.TextChoices):
        SELLER = "seller", "From the seller: buyer picks up, or the seller ships with Seedha Bazar's courier"
        WAREHOUSE = "warehouse", "From the Seedha Bazar warehouse (stock is sent there first)"

    fulfilment = models.CharField(max_length=10, choices=Fulfilment.choices, default=Fulfilment.SELLER)
    village = models.CharField(max_length=120, blank=True)
    district = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=60, blank=True)
    weight_g = models.PositiveIntegerField(default=500, help_text="Packed weight of one unit, for shipping")
    hsn = models.CharField(max_length=8, blank=True, help_text="HSN code for GST invoices")
    gst_rate = models.DecimalField(max_digits=4, decimal_places=1, default=D("0"), help_text="GST % included in the price (0 for exempt farm produce)")
    mrp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Printed or usual price; the discount is shown against it")
    highlights = models.TextField(max_length=1200, blank=True, help_text="'About this item': one point per line")
    details = models.TextField(max_length=1500, blank=True, help_text="Specifications, one per line as 'Name: value' (Material: Cotton)")
    returnable = models.BooleanField(default=True, help_text="Damaged or wrong items can be returned")
    return_days = models.PositiveSmallIntegerField(default=7)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    review_note = models.CharField(max_length=300, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title

    @property
    def is_food(self) -> bool:
        return self.category in FOOD_CATEGORIES


class Inbound(models.Model):
    """Stock a seller sends to the Seedha Bazar warehouse. It counts as stock only when the warehouse receives it."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="inbounds")
    quantity = models.PositiveIntegerField()
    received = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=9, default="sent", choices=[("sent", "On the way to the warehouse"), ("received", "Received"), ("rejected", "Not accepted")])
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class StockMove(models.Model):
    """Every change to a product's stock, so the producer's inventory is always explained."""

    class Reason(models.TextChoices):
        ADDED = "added", "Added"
        SOLD = "sold", "Sold"
        RETURNED = "returned", "Order cancelled, back in stock"
        CORRECTED = "corrected", "Corrected"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="moves")
    change = models.IntegerField()
    reason = models.CharField(max_length=10, choices=Reason.choices)
    order = models.ForeignKey("Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]


class Order(models.Model):
    class Status(models.TextChoices):
        PLACED = "placed", "Placed"
        CONFIRMED = "confirmed", "Confirmed by the makers"
        PACKED = "packed", "Packed"
        DISPATCHED = "dispatched", "On the way"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    class Payment(models.TextChoices):
        COD = "cod", "Pay on delivery"
        UPI = "upi", "UPI to Seedha Bazar"
        ONLINE = "online", "Pay online (card, UPI, net banking)"

    number = models.CharField(max_length=16, unique=True)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="shop_orders")
    channel = models.CharField(max_length=3, default="b2c", help_text="b2c for households, b2b for businesses")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLACED, db_index=True)
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    address = models.CharField(max_length=300)
    city = models.CharField(max_length=60, db_index=True)
    pincode = models.CharField(max_length=6)
    payment = models.CharField(max_length=6, choices=Payment.choices, default=Payment.COD)
    paid = models.BooleanField(default=False)
    payment_ref = models.CharField(max_length=80, blank=True, help_text="Gateway order or payment id, or UPI reference")
    state = models.CharField(max_length=60, blank=True, help_text="Delivery state: decides CGST+SGST or IGST")
    gstin = models.CharField(max_length=15, blank=True, help_text="Buyer's GSTIN for B2B invoices")
    goods = models.DecimalField(max_digits=12, decimal_places=2, help_text="Sum of reviewed prices")
    buyer_fee = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=300, blank=True)
    ops_note = models.CharField(max_length=300, blank=True, help_text="For Seedha Bazar staff only")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.number


class OrderLine(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="lines")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="shop_sales")
    title = models.CharField(max_length=120)
    pack = models.CharField(max_length=60)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    seller_fee = models.DecimalField(max_digits=10, decimal_places=2)
    buyer_fee = models.DecimalField(max_digits=10, decimal_places=2)
    seller_confirmed_at = models.DateTimeField(null=True, blank=True)
    shipment = models.ForeignKey("Shipment", null=True, blank=True, on_delete=models.SET_NULL, related_name="lines")
    hsn = models.CharField(max_length=8, blank=True)
    gst_rate = models.DecimalField(max_digits=4, decimal_places=1, default=D("0"))
    tcs = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="GST TCS kept by Seedha Bazar as e-commerce operator (registered sellers)")
    paid_out_at = models.DateTimeField(null=True, blank=True, help_text="When Seedha Bazar paid the producer")

    @property
    def payout(self) -> Decimal:
        return self.amount - self.seller_fee - self.tcs


class Shipment(models.Model):
    """One parcel journey for part of an order: from one seller (or the Seedha Bazar warehouse) to the buyer, or a pickup."""

    class Origin(models.TextChoices):
        SELLER = "seller", "Seller's place"
        WAREHOUSE = "warehouse", "Seedha Bazar warehouse"

    class Mode(models.TextChoices):
        PICKUP = "pickup", "Buyer picks up"
        COURIER = "courier", "Seedha Bazar courier"

    class Status(models.TextChoices):
        PENDING = "pending", "Being prepared"
        BOOKED = "booked", "Courier booked"
        IN_TRANSIT = "transit", "On the way"
        READY = "ready", "Ready for pickup"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="shipments")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    origin = models.CharField(max_length=10, choices=Origin.choices)
    mode = models.CharField(max_length=8, choices=Mode.choices)
    from_pincode = models.CharField(max_length=6, blank=True)
    zone = models.CharField(max_length=12, blank=True)
    sla_days = models.CharField(max_length=8, blank=True, help_text="e.g. 2-3")
    fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    weight_g = models.PositiveIntegerField(default=0)
    boxes = models.PositiveSmallIntegerField(default=1)
    courier = models.CharField(max_length=20, blank=True, help_text="shiprocket, delhivery, local...")
    courier_name = models.CharField(max_length=60, blank=True, help_text="For a local courier: its name")
    tracking_ids = models.JSONField(default=list, blank=True, help_text="One AWB / tracking id per box")
    tracking_url = models.URLField(blank=True)
    label_urls = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=300, blank=True)
    booked_at = models.DateTimeField(null=True, blank=True)


class Invoice(models.Model):
    """A GST document for one supplier on one order: a tax invoice (GST-registered seller), a bill of supply (unregistered
    or exempt), or Seedha Bazar's own invoice for its platform and delivery charges. Kept as issued; never edited."""

    class Kind(models.TextChoices):
        TAX = "tax", "Tax invoice"
        SUPPLY = "supply", "Bill of supply"
        PLATFORM = "platform", "Seedha Bazar service invoice"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="invoices")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    number = models.CharField(max_length=24, unique=True)
    issued_at = models.DateTimeField(default=timezone.now)
    data = models.JSONField(help_text="Everything printed on it, frozen at issue")

    class Meta:
        ordering = ["issued_at"]


class ProductPhoto(models.Model):
    """More photos of a product, after the main one."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="shop/")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "pk"]


class Review(models.Model):
    """A rating from a buyer who received the product: verified purchase only, one per order line."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    line = models.OneToOneField(OrderLine, on_delete=models.CASCADE, related_name="review")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    stars = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=100, blank=True)
    text = models.CharField(max_length=1000, blank=True)
    hidden = models.BooleanField(default=False, help_text="Hidden by Seedha Bazar (abuse, phone numbers...)")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
