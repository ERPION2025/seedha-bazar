"""The shop: a public storefront for products made by farmers, FPOs, NGOs and their groups; a cart and checkout for
households and businesses; "My shop" for producers (products, stock, orders to confirm); and the Seedha Bazar desk in
the console (review and pricing, orders, fees and revenue). Seedha Bazar sits in the middle: buyers and producers never
see each other's phone numbers."""
from decimal import Decimal, InvalidOperation

from django import forms
from django.conf import settings
from django.db.models import Avg, Count, IntegerField, Q, Sum, Value
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.errors import ApiError
from accounts.models import Role
from profiles.models import OrgMembership
from shop import services as shop
from shop import couriers, payments, shipping
from shop.models import CATEGORIES, CATEGORY_CHOICES, GST_RATES, FeeRule, Inbound, Invoice, Order, OrderLine, Product, SellerSettings, Shipment

from .forms import LangForm
from .helpers import error_text, ok, role_required, warn
from .i18n import tr
from .market_views import base_for

maker_only = role_required(Role.FARMER, Role.AGENT)
buyer_only = role_required(Role.BUYER)
staff_only = role_required(staff=True)
CAT = {k: (label, emoji) for k, label, emoji in CATEGORIES}
PAGE = 24


def _maker_label(p: Product) -> str:
    if p.organisation_id:
        return p.organisation.name
    fp = getattr(p.seller, "farmer_profile", None)
    return " · ".join(x for x in ((fp.name.split() or [""])[0] if fp else "", fp.village if fp else "") if x)


def _decorate(rows):
    for p in rows:
        p.show_price = shop.buyer_price(p)
        p.maker = _maker_label(p)
        p.place = ", ".join(x for x in (p.village, p.district, p.state) if x) or p.origin
        p.from_warehouse = p.fulfilment == "warehouse"
        p.cat_label, p.cat_emoji = CAT.get(p.category, ("", "🛍️"))
    return rows


def _base(request):
    return base_for(request.user) if request.user.is_authenticated else "web/base.html"


# ---------- storefront (open to everyone) ----------
def _pin(request) -> str:
    pin = (request.GET.get("pin") or "").strip()
    if shipping.valid_pin(pin):
        request.session["pin"] = pin
    return request.session.get("pin", "")


def storefront(request, category="", seller=None):
    """The listing: search, filters with counts, sorting, and product cards with everything a buyer compares on."""
    from shop import catalogue

    if category and category not in CAT:
        raise Http404
    params = {k: request.GET.get(k, "") for k in ("q", "from", "state", "price", "rating", "sort")}
    params["cat"] = category or request.GET.get("cat", "")
    if seller:
        params["seller"] = str(seller)
    try:
        page = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page = 1
    qs = catalogue.filtered(params)
    total = qs.count()
    pin = _pin(request)
    rows = catalogue.decorate(qs[(page - 1) * PAGE: page * PAGE], pin, request.user)
    band = params["price"]
    if "-" in band:  # exact, on the price the buyer pays
        lo, _, hi = band.partition("-")
        rows = [r for r in rows if r.show_price >= Decimal(lo or 0) and (not hi or r.show_price <= Decimal(hi))]
    keep = {k: v for k, v in params.items() if v and k not in ("cat", "seller")}
    from urllib.parse import urlencode
    return render(request, "web/shop/storefront.html", {
        "rows": rows, "total": total, "page": page, "pages": max(1, -(-total // PAGE)), "params": params, "qs": urlencode(keep),
        "qs_nosort": urlencode({k: v for k, v in keep.items() if k != "sort"}), "category": params["cat"], "cat": CAT.get(params["cat"]),
        "f": catalogue.facets(params), "sorts": catalogue.SORTS, "pin": pin, "store": seller and _store_info(seller), "base_tpl": _base(request)})


def _store_info(seller_id):
    from django.contrib.auth import get_user_model
    from django.db.models import Avg
    u = get_user_model().objects.filter(pk=seller_id).select_related("farmer_profile").first()
    if u is None:
        raise Http404
    org = _org(u)
    ss = SellerSettings.objects.filter(user=u).first()
    fp = getattr(u, "farmer_profile", None)
    from shop.models import Review
    r = Review.objects.filter(product__seller=u, hidden=False).aggregate(a=Avg("stars"), n=Count("id"))
    return {"name": (org.name if org else "") or (ss.legal_name if ss else "") or (fp.name if fp else ""), "place": ", ".join(x for x in (
        (ss.village if ss else "") or getattr(fp, "village", ""), (ss.district if ss else "") or getattr(fp, "district", ""), (ss.state if ss else "") or getattr(fp, "state", "")) if x),
            "since": u.date_joined, "rating": round(r["a"], 1) if r["a"] else None, "ratings_n": r["n"], "org": bool(org), "verified": bool(org and org.verified)}


def store(request, seller_id):
    return storefront(request, seller=seller_id)


def product_page(request, pk):
    """A product page with a gallery, the buy box (price, MRP, delivery date, stock, pickup), highlights, specifications,
    ratings and reviews, the maker, and similar products."""
    from shop import catalogue

    p = catalogue.base_qs().filter(pk=pk).first() or get_object_or_404(Product.objects.select_related("organisation", "seller__farmer_profile")
                                                                       .annotate(rating=Avg("reviews__stars"), ratings_n=Count("reviews"), sold_30=Value(0, output_field=IntegerField())), pk=pk)
    mine = request.user.is_authenticated and p.seller_id == request.user.pk
    if p.status != Product.Status.LIVE and not mine and not request.user.is_staff:
        raise Http404
    pin = _pin(request)
    catalogue.decorate([p], pin, request.user)
    b2b_each = shop.buyer_price(p, p.b2b_price) if p.b2b_price else None
    org = shop.origin_of(p)
    est = shipping.quote(org["pin"], pin, p.weight_g) if shipping.valid_pin(pin) and org["pin"] else None
    similar = catalogue.decorate(catalogue.base_qs().filter(category=p.category).exclude(pk=p.pk).order_by("-sold_30", "-reviewed_at")[:8], pin)
    from_maker = catalogue.decorate(catalogue.base_qs().filter(seller_id=p.seller_id).exclude(pk=p.pk)[:4], pin)
    photos = ([f"/shop/img/{p.pk}/"] if p.photo else []) + [f"/shop/img/{p.pk}/{ph.pk}/" for ph in p.photos.all()]
    reviews = list(p.reviews.filter(hidden=False).select_related("buyer")[:20])
    for r in reviews:  # first name only
        bp = getattr(r.buyer, "buyer_profile", None)
        r.who = ((bp.contact_name if bp else "") or "").split(" ")[0] or tr(request.lang, "Seedha Bazar buyer")
    return render(request, "web/shop/product.html", {
        "p": p, "b2b_each": b2b_each, "similar": similar, "from_maker": from_maker, "mine": mine, "pin": pin, "est": est, "org": org, "photos": photos,
        "highlights": catalogue.lines_of(p.highlights), "specs": catalogue.specs(p), "rs": catalogue.rating_summary(p), "store": _store_info(p.seller_id),
        "reviews": reviews, "warehouse": settings.SHOP_WAREHOUSE,
        "qty_range": range(1, min(p.max_per_order, p.stock, 10) + 1), "base_tpl": _base(request)})


def photo_extra(request, pk, n):
    from shop.models import ProductPhoto
    ph = get_object_or_404(ProductPhoto.objects.select_related("product"), pk=n, product_id=pk)
    if ph.product.status != "live" and not (request.user.is_authenticated and (request.user.pk == ph.product.seller_id or request.user.is_staff)):
        raise Http404
    resp = FileResponse(ph.image.open("rb"), content_type="image/jpeg")
    resp["Cache-Control"] = "public, max-age=86400"
    return resp


@buyer_only
@require_POST
def review(request, line_id):
    """A rating from the buyer, once the order is delivered: one per product bought."""
    from shop.models import Review
    line = get_object_or_404(OrderLine.objects.select_related("order"), pk=line_id, order__buyer=request.user)
    try:
        stars = int(request.POST.get("stars", "0"))
    except ValueError:
        stars = 0
    if line.order.status != "delivered" or not 1 <= stars <= 5:
        warn(request, "Choose 1 to 5 stars.")
    else:
        from market.services import mask_contacts
        Review.objects.update_or_create(line=line, defaults={"product_id": line.product_id, "buyer": request.user, "stars": stars,
                                                             "title": mask_contacts(request.POST.get("title", ""))[0][:100],
                                                             "text": mask_contacts(request.POST.get("text", ""))[0][:1000]})
        ok(request, "Thank you for rating it.")
    return redirect(f"/shop/orders/{line.order.number}/")


def photo(request, pk):
    p = get_object_or_404(Product, pk=pk)
    if not p.photo or (p.status != "live" and not (request.user.is_authenticated and (request.user.pk == p.seller_id or request.user.is_staff))):
        raise Http404
    resp = FileResponse(p.photo.open("rb"), content_type="image/jpeg")
    resp["Cache-Control"] = "public, max-age=86400"
    return resp


def _cart(request):
    return shop.cart_lines(request.session.get("cart") or {}, request.user, request.session.get("pin", ""), request.session.get("modes") or {})


def cart(request):
    if request.method == "POST":  # the buyer's PIN code, and pickup or courier for each part
        pin = (request.POST.get("pin") or "").strip()
        if pin:
            if shipping.valid_pin(pin):
                request.session["pin"] = pin
            else:
                warn(request, "Enter the 6-digit PIN code.")
        modes = dict(request.session.get("modes") or {})
        for k, v in request.POST.items():
            if k.startswith("mode_") and v in ("pickup", "courier"):
                modes[k[5:]] = v
        request.session["modes"] = modes
        return redirect("/shop/cart/")
    return render(request, "web/shop/cart.html", {"c": _cart(request), "free_above": settings.SHOP_FREE_DELIVERY_ABOVE, "warehouse": settings.SHOP_WAREHOUSE,
                                                  "base_tpl": _base(request)})


@require_POST
def cart_change(request):
    pid, qty = request.POST.get("product", ""), request.POST.get("qty", "1")
    p = Product.objects.filter(pk=pid, status="live").first() if pid.isdigit() else None
    if p is None:
        return redirect("/shop/cart/")
    try:
        n = int(qty)
    except ValueError:
        n = 1
    if request.POST.get("set") == "1":
        shop.cart_set(request.session, pid, min(max(n, 0), p.max_per_order, p.stock))
    else:
        shop.cart_add(request.session, p, max(n, 1))
        if request.POST.get("buy") == "1":  # Buy now: straight on to delivery and checkout
            return redirect("/shop/checkout/" if request.session.get("pin") else "/shop/cart/")
        ok(request, "Added to your cart.")
    return redirect(request.POST.get("back") if (request.POST.get("back") or "").startswith("/shop/") else "/shop/cart/")


class CheckoutForm(LangForm):
    name = forms.CharField(label="Name", max_length=120)
    phone = forms.CharField(label="Mobile number", max_length=20, widget=forms.TextInput(attrs={"inputmode": "tel"}))
    address = forms.CharField(label="Delivery address", max_length=300, widget=forms.Textarea(attrs={"rows": 2}))
    city = forms.ChoiceField(label="City", choices=[])
    pincode = forms.RegexField(label="PIN code", regex=r"^[1-9]\d{5}$", max_length=6, error_messages={"invalid": "Enter the 6-digit PIN code."})
    gstin = forms.CharField(label="GSTIN for a business invoice (optional)", max_length=15, required=False)
    payment = forms.ChoiceField(label="How you will pay", choices=list(Order.Payment.choices), initial="cod", widget=forms.RadioSelect(attrs={"class": "chips"}))
    note = forms.CharField(label="Note for delivery (optional)", max_length=300, required=False)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["city"].choices = [(c, c) for c in settings.SHOP_CITIES]
        self.fields["payment"].choices = [(v, l) for v, l in Order.Payment.choices
                                          if v == "cod" or (v == "upi" and settings.SHOP_UPI_ID) or (v == "online" and payments.configured())]

    def clean_gstin(self):
        v = (self.cleaned_data.get("gstin") or "").strip().upper()
        if v and len(v) != 15:
            raise forms.ValidationError("GSTIN has 15 characters")
        return v


def checkout(request):
    u = request.user
    if not u.is_authenticated:
        return redirect("/login/?as=buyer&next=/shop/checkout/")
    if u.role != Role.BUYER:
        warn(request, "Please sign in with a buyer account to place orders.")
        return redirect("/shop/cart/")
    c = _cart(request)
    if not c["rows"]:
        return redirect("/shop/")
    if not c["pin"]:
        warn(request, "Enter your PIN code to see delivery options.")
        return redirect("/shop/cart/")
    bp = getattr(u, "buyer_profile", None)
    form = CheckoutForm(request.POST or None, lang=request.lang, initial={"name": bp.contact_name if bp else "", "phone": u.phone, "pincode": c["pin"],
                                                                          "city": shop.serviceable(bp.city if bp else "") or "", "gstin": bp.gstin if bp else ""})
    if request.method == "POST" and form.is_valid():
        try:
            order = shop.place_order(u, request.session.get("cart") or {}, form.cleaned_data, form.cleaned_data["payment"], request, request.session.get("modes") or {})
        except ApiError as e:
            form.add_error(None, error_text(request, e))
        else:
            request.session["cart"] = {}
            if order.payment == "online":
                return redirect(f"/shop/orders/{order.number}/pay/")
            ok(request, "Order placed. We will confirm it with the makers and keep you posted.")
            return redirect(f"/shop/orders/{order.number}/")
    return render(request, "web/shop/checkout.html", {"form": form, "c": c, "upi": settings.SHOP_UPI_ID, "base_tpl": base_for(u)})


@buyer_only
def my_orders(request):
    return render(request, "web/shop/orders.html", {"rows": Order.objects.filter(buyer=request.user).prefetch_related("lines")[:50], "base_tpl": base_for(request.user)})


@buyer_only
def order_page(request, number):
    o = get_object_or_404(Order.objects.prefetch_related("lines"), number=number, buyer=request.user)
    if request.method == "POST" and request.POST.get("action") == "cancel":
        try:
            shop.cancel(o, request.user, "Cancelled by the buyer")
            ok(request, "Order cancelled.")
        except ApiError as e:
            warn(request, error_text(request, e))
        return redirect(f"/shop/orders/{o.number}/")
    from shop.models import Review
    rated = {r.line_id: r for r in Review.objects.filter(line__order=o)}
    for line in o.lines.all():
        line.rated = rated.get(line.pk)
    labels, at = dict(Order.Status.choices), shop.STEPS.index(o.status) if o.status in shop.STEPS else -1
    steps = [{"label": labels[s], "state": "done" if i < at else ("now" if i == at else "")} for i, s in enumerate(shop.STEPS)]
    return render(request, "web/shop/order.html", {"o": o, "steps": steps, "upi": settings.SHOP_UPI_ID, "shipments": o.shipments.prefetch_related("lines"),
                                                   "invoices": o.invoices.all(), "warehouse": settings.SHOP_WAREHOUSE, "base_tpl": base_for(request.user)})


@buyer_only
def pay(request, number):
    """Online payment in Razorpay's window; the result is checked on our server before the order counts as paid."""
    o = get_object_or_404(Order, number=number, buyer=request.user, payment="online")
    if o.paid or o.status == "cancelled":
        return redirect(f"/shop/orders/{o.number}/")
    if request.method == "POST":
        rid, pid, sig = request.POST.get("razorpay_order_id", ""), request.POST.get("razorpay_payment_id", ""), request.POST.get("razorpay_signature", "")
        if rid == o.payment_ref and payments.verify(rid, pid, sig):
            o.paid, o.payment_ref = True, f"{rid}|{pid}"[:80]
            o.save(update_fields=["paid", "payment_ref"])
            ok(request, "Payment received. Thank you.")
            return redirect(f"/shop/orders/{o.number}/")
        warn(request, "The payment could not be confirmed. If money was taken, it is refunded automatically; or try again.")
        return redirect(f"/shop/orders/{o.number}/pay/")
    if not payments.configured():
        raise Http404
    if not o.payment_ref:
        try:
            o.payment_ref = payments.create_order(o)
            o.save(update_fields=["payment_ref"])
        except Exception:
            warn(request, "Online payment is not available right now. Try again in a few minutes.")
            return redirect(f"/shop/orders/{o.number}/")
    return render(request, "web/shop/pay.html", {"o": o, "key": settings.RAZORPAY_KEY_ID, "base_tpl": base_for(request.user)})


def invoice(request, number):
    """A GST document: for the buyer of the order, the seller on it, or Seedha Bazar staff."""
    inv = get_object_or_404(Invoice.objects.select_related("order"), number=number.replace("-", "/"))
    u = request.user
    if not (u.is_authenticated and (u.is_staff or u.pk == inv.order.buyer_id or (inv.seller_id and u.pk == inv.seller_id))):
        raise Http404
    return render(request, "web/shop/invoice.html", {"inv": inv, "d": inv.data})


# ---------- My shop (farmers, FPOs, NGOs) ----------
class ProductForm(LangForm):
    category = forms.ChoiceField(label="Category", choices=CATEGORY_CHOICES)
    title = forms.CharField(label="Product name", max_length=120, widget=forms.TextInput(attrs={"placeholder": "Kodo millet cookies, Chanderi saree, bamboo lamp..."}))
    pack = forms.CharField(label="One unit is", max_length=60, widget=forms.TextInput(attrs={"placeholder": "250 g pack, 1 saree, set of 4"}))
    description = forms.CharField(label="Describe it: material, how it is made, size, care", max_length=2000, widget=forms.Textarea(attrs={"rows": 4}))
    highlights = forms.CharField(label="Key points buyers should know, one per line", max_length=1200, required=False,
                                 widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Hand-woven by women weavers of Chanderi\nPure cotton-silk, soft and light\nDry clean only"}))
    details = forms.CharField(label="Specifications, one per line as 'Name: value' (optional)", max_length=1500, required=False,
                              widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Material: Cotton\nLength: 5.5 m\nColour: Indigo"}))
    asked_price = forms.DecimalField(label="Your price for one unit (₹)", min_value=Decimal("1"), decimal_places=2)
    mrp = forms.DecimalField(label="M.R.P. or usual price (₹, optional)", min_value=Decimal("1"), decimal_places=2, required=False)
    b2b_price = forms.DecimalField(label="Price for business orders (₹ per unit, optional)", min_value=Decimal("1"), decimal_places=2, required=False)
    b2b_min = forms.IntegerField(label="Business price from how many units (optional)", min_value=2, required=False)
    max_per_order = forms.IntegerField(label="Most units in one order", min_value=1, max_value=1000, initial=20)
    returnable = forms.BooleanField(label="Buyers can return a damaged or wrong item", required=False, initial=True)
    return_days = forms.IntegerField(label="Days to return", min_value=1, max_value=30, initial=7, required=False)
    fulfilment = forms.ChoiceField(label="How it reaches buyers", choices=list(Product.Fulfilment.choices), initial="seller", widget=forms.RadioSelect)
    village = forms.CharField(label="Village", max_length=120)
    district = forms.CharField(label="District", max_length=80)
    state = forms.CharField(label="State", max_length=60)
    weight_g = forms.IntegerField(label="Packed weight of one unit (grams)", min_value=10, max_value=50000, initial=500)
    hsn = forms.CharField(label="HSN code (for GST invoices, optional)", max_length=8, required=False)
    gst_rate = forms.TypedChoiceField(label="GST included in your price", choices=[(str(v), l) for v, l in GST_RATES], coerce=Decimal, initial="0")
    fssai_no = forms.CharField(label="FSSAI number (14 digits, for packed food)", max_length=14, required=False)
    shelf_life_days = forms.IntegerField(label="Stays good for (days, food only)", min_value=1, required=False)
    photo = forms.ImageField(label="Photo (clear, on a plain background)", required=False)

    def clean(self):
        d = super().clean()
        if d.get("category") == "food" and len("".join(ch for ch in (d.get("fssai_no") or "") if ch.isdigit())) != 14:
            self.add_error("fssai_no", "Packed food needs a 14-digit FSSAI licence or registration number.")
        hsn = (d.get("hsn") or "").strip()
        if hsn and not (hsn.isdigit() and len(hsn) in (4, 6, 8)):
            self.add_error("hsn", "HSN codes have 4, 6 or 8 digits.")
        if d.get("mrp") and d.get("asked_price") and d["mrp"] < d["asked_price"]:
            self.add_error("mrp", "The M.R.P. cannot be less than your price.")
        if bool(d.get("b2b_price")) != bool(d.get("b2b_min")):
            self.add_error("b2b_min", "Give both the business price and from how many units.")
        p = d.get("photo")
        if p and p.size > 4 * 1024 * 1024:
            self.add_error("photo", "The photo is too large. Use one under 4 MB.")
        return d


def _org(user):
    m = OrgMembership.objects.filter(user=user).select_related("organisation").first() if user.role == Role.AGENT else None
    return m.organisation if m else None


def _jpeg(f):
    """A clean JPEG no wider than 1200 px (and without the phone's hidden location data)."""
    from io import BytesIO

    from django.core.files.base import ContentFile
    from PIL import Image, ImageOps

    im = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
    im.thumbnail((1200, 1200))
    buf = BytesIO()
    im.save(buf, "JPEG", quality=85)
    return ContentFile(buf.getvalue())


def _save_photo(product, f):
    product.photo.save(f"p{product.pk}.jpg", _jpeg(f), save=True)


MORE_PHOTOS = 4


def _save_more_photos(product, files) -> int:
    """Up to four more photos (sides, close-ups, in use); a new set replaces the old one."""
    from PIL import UnidentifiedImageError

    from shop.models import ProductPhoto
    good = []
    for f in files[:MORE_PHOTOS]:
        if f.size > 4 * 1024 * 1024:
            continue
        try:
            good.append(_jpeg(f))
        except (UnidentifiedImageError, OSError):
            continue
    if good:
        for old in product.photos.all():
            old.image.delete(save=False)
            old.delete()
        for i, content in enumerate(good):
            ph = ProductPhoto(product=product, position=i)
            ph.image.save(f"p{product.pk}_{i + 1}.jpg", content, save=False)
            ph.save()
    return len(good)


@maker_only
def manage(request):
    u = request.user
    rows = Product.objects.filter(seller=u)
    to_confirm = OrderLine.objects.filter(seller=u, order__status="placed", seller_confirmed_at__isnull=True).count()
    earned = OrderLine.objects.filter(seller=u, order__status="delivered").aggregate(a=Sum("amount"), f=Sum("seller_fee"))
    ss = SellerSettings.objects.filter(user=u).first()
    return render(request, "web/shop/manage.html", {"rows": rows, "to_confirm": to_confirm, "earned": (earned["a"] or 0) - (earned["f"] or 0),
                                                    "ss_ready": bool(ss and ss.ready_to_ship), "base_tpl": base_for(u)})


@maker_only
def product_form(request, pk=None):
    u = request.user
    p = get_object_or_404(Product, pk=pk, seller=u) if pk else None
    FIELDS = ("category", "title", "pack", "description", "highlights", "details", "asked_price", "mrp", "b2b_price", "b2b_min", "max_per_order", "returnable",
              "return_days", "fssai_no", "shelf_life_days", "fulfilment", "village", "district", "state", "weight_g", "hsn", "gst_rate")
    ss = SellerSettings.objects.filter(user=u).first()
    fp = getattr(u, "farmer_profile", None) if u.role == Role.FARMER else None
    org = _org(u)
    home = {"village": (ss.village if ss else "") or getattr(fp, "village", "") or getattr(org, "block", ""),
            "district": (ss.district if ss else "") or getattr(fp, "district", "") or getattr(org, "district", ""),
            "state": (ss.state if ss else "") or getattr(fp, "state", "") or getattr(org, "state", "")}
    initial = {f: getattr(p, f) for f in FIELDS} if p else home
    form = ProductForm(request.POST or None, request.FILES or None, lang=request.lang, initial=initial)
    if request.method == "POST" and request.POST.get("action") == "stock" and p is not None:
        try:
            n = int(request.POST.get("change", "0"))
            if p.fulfilment == "warehouse":  # warehouse stock counts only when the warehouse receives it
                shop.send_to_warehouse(p, n, request.POST.get("note", ""))
                ok(request, "Noted. Send the goods to the Seedha Bazar warehouse; they go on sale when received.")
            else:
                shop.add_stock(p, n, u, "added" if n > 0 else "corrected", request.POST.get("note", ""))
                ok(request, "Stock updated.")
        except (ValueError, ApiError):
            warn(request, "Enter a quantity more than zero.")
        return redirect(f"/shop/manage/{p.pk}/")
    if request.method == "POST" and request.POST.get("action") in ("pause", "resume") and p is not None:
        p.status = "paused" if request.POST["action"] == "pause" else ("live" if p.price else "pending")
        p.save(update_fields=["status"])
        return redirect(f"/shop/manage/{p.pk}/")
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        new = p is None
        p = p or Product(seller=u, organisation=_org(u))
        before = (p.asked_price, p.title, p.description, p.b2b_price, p.mrp, p.highlights) if not new else None
        for f in ("category", "title", "pack", "description", "highlights", "details", "asked_price", "mrp", "b2b_price", "b2b_min", "max_per_order",
                  "returnable", "return_days", "shelf_life_days", "fulfilment", "village", "district", "state", "weight_g", "hsn", "gst_rate"):
            setattr(p, f, d.get(f))
        p.highlights, p.details, p.return_days = p.highlights or "", p.details or "", p.return_days or 7
        p.origin = ", ".join(x for x in (p.village, p.district) if x)
        p.fssai_no = "".join(ch for ch in (d.get("fssai_no") or "") if ch.isdigit())
        p.save()
        if new:
            try:
                start = int(request.POST.get("stock", "0") or 0)
            except ValueError:
                start = 0
            if start > 0 and p.fulfilment == "warehouse":
                shop.send_to_warehouse(p, start, "Opening stock")
            elif start > 0:
                shop.add_stock(p, start, u, "added", "Opening stock")
        if d.get("photo"):
            _save_photo(p, d["photo"])
        if request.FILES.getlist("more_photos"):
            _save_more_photos(p, request.FILES.getlist("more_photos"))
        shop.submit(p, new or before != (p.asked_price, p.title, p.description, p.b2b_price, p.mrp, p.highlights))
        ok(request, "Saved. Seedha Bazar checks new products and price changes before they go on sale.")
        return redirect(f"/shop/manage/{p.pk}/")
    fee = shop.fees(p.category if p else "other")
    return render(request, "web/shop/product_form.html", {"form": form, "p": p, "moves": p.moves.all()[:20] if p else [], "seller_pct": fee[0], "buyer_pct": fee[1],
                                                          "inbounds": p.inbounds.all()[:10] if p else [], "ss": ss, "warehouse": settings.SHOP_WAREHOUSE,
                                                          "payout": shop.payout_per_unit(p, p.price) if p and p.price else None, "base_tpl": base_for(u)})


@maker_only
def manage_orders(request):
    u = request.user
    if request.method == "POST":
        line = get_object_or_404(OrderLine, pk=request.POST.get("line"), seller=u)
        try:
            shop.seller_confirm(line, u)
            ok(request, "Confirmed. Pack it; Seedha Bazar will arrange the pickup.")
        except ApiError as e:
            warn(request, error_text(request, e))
        return redirect("/shop/manage/orders/")
    rows = OrderLine.objects.filter(seller=u).select_related("order").order_by("-order__created_at")[:100]
    return render(request, "web/shop/manage_orders.html", {"rows": rows, "base_tpl": base_for(u)})


# ---------- Seedha Bazar's desk (console) ----------
@staff_only
def desk_review(request):
    if request.method == "POST":
        p = get_object_or_404(Product, pk=request.POST.get("product"))
        price = request.POST.get("price") or None
        try:
            if price is not None:
                Decimal(price)
            shop.review(p, request.user, request.POST.get("decision", ""), price, request.POST.get("note", ""))
            ok(request, "Saved.")
        except (ApiError, InvalidOperation):
            warn(request, "Enter a price in rupees.")
        return redirect("/console/shop/")
    pending = _decorate(list(Product.objects.filter(status="pending").select_related("organisation", "seller__farmer_profile")[:100]))
    for p in pending:
        p.fee = shop.fees(p.category)
    live = Product.objects.filter(status="live").count()
    return render(request, "web/console/shop_review.html", {"rows": pending, "live": live})


@staff_only
def desk_orders(request):
    if request.method == "POST":
        o = get_object_or_404(Order, pk=request.POST.get("order"))
        action = request.POST.get("action", "")
        try:
            if action == "paid":
                o.paid = True
                o.save(update_fields=["paid"])
            elif action == "payout":
                OrderLine.objects.filter(order=o, paid_out_at__isnull=True).update(paid_out_at=timezone.now())
            else:
                shop.advance(o, action, request.user, request.POST.get("note", ""))
            ok(request, "Saved.")
        except ApiError as e:
            warn(request, error_text(request, e))
        return redirect("/console/shop/orders/" + (f"?status={request.GET['status']}" if request.GET.get("status") else ""))
    status = request.GET.get("status", "open")
    qs = Order.objects.prefetch_related("lines__seller__farmer_profile").select_related("buyer")
    qs = qs.exclude(status__in=["delivered", "cancelled"]) if status == "open" else (qs.filter(status=status) if status in Order.Status.values else qs)
    rows = list(qs[:200])
    for o in rows:
        i = shop.STEPS.index(o.status) if o.status in shop.STEPS else -1
        o.next_step = shop.STEPS[i + 1] if 0 <= i < len(shop.STEPS) - 1 else ""
        o.next_label = dict(Order.Status.choices).get(o.next_step, "")
        o.unpaid_out = o.status == "delivered" and o.lines.filter(paid_out_at__isnull=True).exists()
    return render(request, "web/console/shop_orders.html", {"rows": rows, "status": status, "statuses": Order.Status.choices})


@staff_only
def desk_fees(request):
    if request.method == "POST":
        try:
            for k, _ in CATEGORY_CHOICES:
                sp, bp = Decimal(request.POST.get(f"s_{k}") or "0"), Decimal(request.POST.get(f"b_{k}") or "0")
                if not (0 <= sp <= 30 and 0 <= bp <= 30):
                    raise InvalidOperation
                FeeRule.objects.update_or_create(category=k, defaults={"seller_pct": sp, "buyer_pct": bp})
            ok(request, "Saved.")
        except InvalidOperation:
            warn(request, "Fees must be between 0 and 30 per cent.")
        return redirect("/console/shop/fees/")
    rules = []
    for k, label, emoji in CATEGORIES:
        sp, bp = shop.fees(k)
        rules.append({"key": k, "label": label, "emoji": emoji, "seller": sp, "buyer": bp})
    done = OrderLine.objects.filter(order__status="delivered")
    by_month = (done.values("order__created_at__year", "order__created_at__month").annotate(sales=Sum("amount"), sf=Sum("seller_fee"), bf=Sum("buyer_fee"),
                                                                                                 n=Count("order", distinct=True))
                .order_by("-order__created_at__year", "-order__created_at__month")[:12])
    owed = done.filter(paid_out_at__isnull=True).aggregate(a=Sum("amount"), f=Sum("seller_fee"))
    return render(request, "web/console/shop_fees.html", {"rules": rules, "months": by_month, "owed": (owed["a"] or 0) - (owed["f"] or 0),
                                                          "delivery_fee": settings.SHOP_DELIVERY_FEE, "free_above": settings.SHOP_FREE_DELIVERY_ABOVE})



# ---------- seller settings ----------
class SellerForm(LangForm):
    legal_name = forms.CharField(label="Name on invoices (farmer, FPO or NGO)", max_length=160)
    gstin = forms.CharField(label="GSTIN (only if GST-registered)", max_length=15, required=False)
    address = forms.CharField(label="Pickup address (house, street, landmark)", max_length=300)
    village = forms.CharField(label="Village", max_length=120)
    district = forms.CharField(label="District", max_length=80)
    state = forms.CharField(label="State", max_length=60)
    pincode = forms.RegexField(label="PIN code", regex=r"^[1-9]\d{5}$", max_length=6, error_messages={"invalid": "Enter the 6-digit PIN code."})
    pickup_phone = forms.CharField(label="Phone for the courier (never shown to buyers)", max_length=20, required=False)
    allow_self_pickup = forms.BooleanField(label="Buyers may collect from this address (Seedha Bazar shares it after confirming the order)", required=False)
    payout_upi = forms.CharField(label="UPI ID for your payments (optional)", max_length=80, required=False)

    def clean_gstin(self):
        v = (self.cleaned_data.get("gstin") or "").strip().upper()
        if v and len(v) != 15:
            raise forms.ValidationError("GSTIN has 15 characters")
        return v


@maker_only
def seller_settings(request):
    u = request.user
    ss, _ = SellerSettings.objects.get_or_create(user=u)
    fp = getattr(u, "farmer_profile", None) if u.role == Role.FARMER else None
    org = _org(u)
    initial = {f: getattr(ss, f) for f in ("legal_name", "gstin", "address", "village", "district", "state", "pincode", "pickup_phone", "allow_self_pickup", "payout_upi")}
    for f, alt in (("legal_name", org.name if org else getattr(fp, "name", "")), ("village", getattr(fp, "village", "") or getattr(org, "block", "")),
                   ("district", getattr(fp, "district", "") or getattr(org, "district", "")), ("state", getattr(fp, "state", "") or getattr(org, "state", "")),
                   ("pickup_phone", u.phone)):
        initial[f] = initial[f] or alt
    form = SellerForm(request.POST or None, lang=request.lang, initial=initial)
    if request.method == "POST" and form.is_valid():
        for k, v in form.cleaned_data.items():
            setattr(ss, k, v)
        ss.save()
        ok(request, "Saved.")
        return redirect("/shop/manage/")
    return render(request, "web/shop/seller_settings.html", {"form": form, "base_tpl": base_for(u)})


# ---------- Seedha Bazar desk: shipments, labels, warehouse inbound, couriers ----------
@staff_only
def desk_shipment(request, pk):
    sh = get_object_or_404(Shipment.objects.select_related("order", "seller__shop_seller"), pk=pk)
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            boxes = int(request.POST.get("boxes") or sh.boxes)
            sh.boxes = max(1, min(boxes, 50))
            sh.save(update_fields=["boxes"])
            if action == "book":
                couriers.book(sh, request.POST.get("partner", ""))
                ok(request, "Courier booked.")
            elif action == "local":
                couriers.book_local(sh, request.POST.get("courier_name", ""), request.POST.get("tracking", ""), request.POST.get("tracking_url", ""))
                ok(request, "Saved.")
            elif action == "ready":
                sh.status = "ready"
                sh.save(update_fields=["status"])
                ok(request, "Saved.")
            elif action == "boxes":
                ok(request, "Saved.")
        except (couriers.CourierError, ValueError) as e:
            sh.error = str(e)[:300]
            sh.save(update_fields=["error"])
            warn(request, str(e)[:200])
        return redirect(f"/console/shop/shipments/{sh.pk}/")
    pickup = settings.SHOP_WAREHOUSE if sh.origin == "warehouse" else (getattr(sh.seller, "shop_seller", None) if sh.seller_id else None)
    return render(request, "web/console/shop_shipment.html", {"sh": sh, "pickup": pickup, "partners": couriers.available(), "lines": sh.lines.all()})


@staff_only
def desk_labels(request, pk):
    """One printable label per box: from, to, order, box n of N, weight, tracking id, and cash to collect."""
    sh = get_object_or_404(Shipment.objects.select_related("order", "seller__shop_seller"), pk=pk)
    o = sh.order
    if sh.origin == "warehouse":
        w = settings.SHOP_WAREHOUSE
        frm = {"name": w["name"], "address": w["address"], "pincode": w["pincode"]}
    else:
        ss = getattr(sh.seller, "shop_seller", None)
        frm = {"name": "Seedha Bazar c/o " + ((ss.legal_name if ss else "") or "seller"), "address": f"{ss.address}, {ss.village}, {ss.district}, {ss.state}" if ss else "",
               "pincode": ss.pincode if ss else ""}
    cod = o.payment == "cod" and not o.paid
    collect = sum((l.amount + l.buyer_fee for l in sh.lines.all()), 0) + sh.fee if cod else 0
    boxes = [{"n": i + 1, "id": (sh.tracking_ids[i] if i < len(sh.tracking_ids) else (sh.tracking_ids[0] if sh.tracking_ids else ""))} for i in range(sh.boxes)]
    return render(request, "web/console/shop_labels.html", {"sh": sh, "o": o, "frm": frm, "boxes": boxes, "collect": collect, "per_box_g": sh.weight_g // max(1, sh.boxes)})


@staff_only
def desk_inbound(request):
    if request.method == "POST":
        inb = get_object_or_404(Inbound, pk=request.POST.get("inbound"))
        try:
            shop.receive(inb, request.user, int(request.POST.get("received") or 0), request.POST.get("note", ""))
            ok(request, "Saved.")
        except (ApiError, ValueError):
            warn(request, "Enter a quantity more than zero.")
        return redirect("/console/shop/inbound/")
    return render(request, "web/console/shop_inbound.html", {"rows": Inbound.objects.select_related("product__seller").order_by("status", "-created_at")[:100],
                                                             "warehouse": settings.SHOP_WAREHOUSE})


@staff_only
def desk_couriers(request):
    from shop.shipping import SLA
    return render(request, "web/console/shop_couriers.html", {"partners": [(c, c.configured()) for c in couriers.PARTNERS.values()], "warehouse": settings.SHOP_WAREHOUSE,
                                                              "zones": [(z, SLA[z], settings.SHOP_ZONE_FEES[z]) for z in SLA], "gstin": settings.GSTIN,
                                                              "online": payments.configured(), "upi": settings.SHOP_UPI_ID})
