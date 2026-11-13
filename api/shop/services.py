"""Shop rules: fees, the cart, placing an order, the order's steps, price review, stock and payouts."""
import secrets
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from accounts import audit
from accounts.errors import ApiError
from accounts.models import Role

from . import gst, shipping
from .models import FeeRule, Order, OrderLine, Product, SellerSettings, Shipment, StockMove

D = Decimal
ONE = D("1")
STEPS = ["placed", "confirmed", "packed", "dispatched", "delivered"]


def _r(x) -> Decimal:
    return D(x).quantize(ONE, rounding=ROUND_HALF_UP)


def fees(category: str) -> tuple[Decimal, Decimal]:
    """(seller %, buyer %) for a category."""
    rule = FeeRule.objects.filter(category=category).first()
    if rule:
        return rule.seller_pct, rule.buyer_pct
    return D(settings.SHOP_SELLER_PCT), D(settings.SHOP_BUYER_PCT)


def is_business(user) -> bool:
    bp = getattr(user, "buyer_profile", None) if user and user.is_authenticated and user.role == Role.BUYER else None
    return bool(bp and bp.business_type and bp.business_type != "individual")


def unit_price(product: Product, qty: int, business: bool) -> tuple[Decimal, bool]:
    """The reviewed price, or the business price for a large enough business order. Returns (price, is_b2b)."""
    if business and product.b2b_price and product.b2b_min and qty >= product.b2b_min:
        return product.b2b_price, True
    return product.price, False


def buyer_price(product: Product, price: Decimal | None = None) -> Decimal:
    """What the buyer sees and pays for one unit: the reviewed price plus Seedha Bazar's buyer fee, in whole rupees."""
    _, bp = fees(product.category)
    return _r((price if price is not None else product.price) * (1 + bp / 100))


def payout_per_unit(product: Product, price: Decimal) -> Decimal:
    sp, _ = fees(product.category)
    return price - _r(price * sp / 100)


# ---------- cart (kept in the session: {product id: quantity}) ----------
def origin_of(p: Product) -> dict:
    """Where a product ships from: the Seedha Bazar warehouse, or the seller's own place."""
    if p.fulfilment == Product.Fulfilment.WAREHOUSE:
        w = settings.SHOP_WAREHOUSE
        return {"key": "w", "kind": "warehouse", "pin": w["pincode"], "place": f"{w['district']}, {w['state']}", "pickup": w["pickup_allowed"], "seller": None}
    ss = SellerSettings.objects.filter(user_id=p.seller_id).first()
    return {"key": f"s{p.seller_id}", "kind": "seller", "pin": ss.pincode if ss else "", "place": ", ".join(x for x in (p.village, p.district, p.state) if x) or p.origin,
            "pickup": bool(ss and ss.allow_self_pickup and ss.address), "seller": p.seller_id}


def cart_lines(cart: dict, user=None, pin: str = "", modes: dict | None = None) -> dict:
    """The cart, grouped by where each part ships from, with delivery options and charges for the buyer's PIN code."""
    business = is_business(user)
    modes = modes or {}
    rows, goods, fee = [], D(0), D(0)
    groups: dict = {}
    for pid, qty in cart.items():
        p = Product.objects.filter(pk=int(pid), status=Product.Status.LIVE).first() if str(pid).isdigit() else None
        if p is None or qty <= 0:
            continue
        qty = min(qty, p.max_per_order, p.stock) if p.stock else 0
        price, b2b = unit_price(p, qty, business)
        each = buyer_price(p, price)
        amount = price * qty
        org = origin_of(p)
        row = {"product": p, "qty": qty, "price": price, "each": each, "line": each * qty, "b2b": b2b, "out": qty == 0, "group": org["key"]}
        rows.append(row)
        g = groups.setdefault(org["key"], {**org, "rows": [], "weight": 0})
        g["rows"].append(row)
        g["weight"] += p.weight_g * qty
        goods += amount
        fee += each * qty - amount
    delivery = D(0)
    for g in groups.values():
        g["courier"] = shipping.quote(g["pin"], pin, g["weight"]) if pin else None
        g["mode"] = modes.get(g["key"]) if modes.get(g["key"]) in ("pickup", "courier") else "courier"
        if g["mode"] == "pickup" and not g["pickup"]:
            g["mode"] = "courier"
        g["fee"] = D(0) if g["mode"] == "pickup" or not g["courier"] else g["courier"]["fee"]
        delivery += g["fee"]
    free = bool(rows) and goods + fee >= settings.SHOP_FREE_DELIVERY_ABOVE
    if free:
        delivery = D(0)
    return {"rows": rows, "groups": list(groups.values()), "goods": goods, "fee": fee, "delivery": delivery, "free_delivery": free,
            "total": goods + fee + delivery, "count": sum(r["qty"] for r in rows), "pin": pin}


def cart_add(session, product: Product, qty: int) -> None:
    cart = dict(session.get("cart") or {})
    key = str(product.pk)
    cart[key] = max(0, min(int(cart.get(key, 0)) + qty, product.max_per_order, product.stock))
    if not cart[key]:
        cart.pop(key)
    session["cart"] = cart


def cart_set(session, product_id: str, qty: int) -> None:
    cart = dict(session.get("cart") or {})
    if qty <= 0:
        cart.pop(str(product_id), None)
    else:
        cart[str(product_id)] = qty
    session["cart"] = cart


# ---------- orders ----------
def serviceable(city: str) -> str | None:
    """The city's own spelling if Seedha Bazar delivers there."""
    c = (city or "").strip().lower()
    return next((x for x in settings.SHOP_CITIES if x.lower() == c), None)


@transaction.atomic
def place_order(buyer, cart: dict, address: dict, payment: str = "cod", request=None, modes: dict | None = None) -> Order:
    """Take the stock, then create the order with one shipment per place it ships from (or a pickup), GST details per line."""
    if buyer.role != Role.BUYER:
        raise ApiError("not_allowed", "You cannot do this.", 403)
    pin = (address.get("pincode") or "").strip()
    if not shipping.valid_pin(pin):
        raise ApiError("bad_pincode", "Enter the 6-digit PIN code.", 400)
    c = cart_lines(cart, buyer, pin, modes)
    if not c["rows"] or any(r["out"] for r in c["rows"]):
        raise ApiError("out_of_stock", "Some items are no longer in stock. Check your cart.", 409)
    if any(g["mode"] == "courier" and g["kind"] == "seller" and not g["pin"] for g in c["groups"]):
        raise ApiError("seller_not_ready", "One seller has not set a pickup address yet. Choose pickup or remove the item.", 409)
    city = serviceable(address.get("city", "")) or (address.get("city") or "").strip().title()
    if any(g["mode"] == "courier" for g in c["groups"]) and not city:
        raise ApiError("not_serviceable", "We do not deliver to this city yet.", 400)
    if payment == "online" and not __import__("shop.payments", fromlist=["configured"]).configured():
        payment = "cod"
    order = Order.objects.create(number="SB" + secrets.token_hex(4).upper(), buyer=buyer, channel="b2b" if any(r["b2b"] for r in c["rows"]) else "b2c",
                                 name=address["name"][:120], phone=address["phone"][:20], address=address["address"][:300], city=city[:60], pincode=pin,
                                 state=shipping.state_of(pin) or (address.get("state") or ""), gstin=(address.get("gstin") or "").upper()[:15],
                                 payment=payment if payment in Order.Payment.values else "cod", goods=c["goods"], buyer_fee=c["fee"], delivery_fee=c["delivery"],
                                 total=c["total"], note=(address.get("note") or "")[:300])
    for g in c["groups"]:
        sh = Shipment.objects.create(order=order, seller_id=g["seller"], origin=g["kind"], mode=g["mode"], from_pincode=g["pin"], weight_g=g["weight"],
                                     zone=g["courier"]["zone"] if g["courier"] else "", sla_days=g["courier"]["days"] if g["courier"] and g["mode"] == "courier" else "",
                                     fee=D(0) if c["free_delivery"] else g["fee"], boxes=max(1, -(-g["weight"] // 10000)))  # about 10 kg a box to start
        for r in g["rows"]:
            p = r["product"]
            # take the stock now, so two buyers cannot buy the same last piece
            if Product.objects.filter(pk=p.pk, stock__gte=r["qty"]).update(stock=F("stock") - r["qty"]) != 1:
                raise ApiError("out_of_stock", "Some items are no longer in stock. Check your cart.", 409)
            sp, _ = fees(p.category)
            amount = r["price"] * r["qty"]
            ss = SellerSettings.objects.filter(user_id=p.seller_id).first()
            OrderLine.objects.create(order=order, product=p, seller=p.seller, title=p.title, pack=p.pack, quantity=r["qty"], unit_price=r["price"], amount=amount,
                                     seller_fee=_r(amount * sp / 100), buyer_fee=r["line"] - amount, shipment=sh, hsn=p.hsn, gst_rate=p.gst_rate,
                                     tcs=gst.tcs_for(amount, p.gst_rate, ss.gstin if ss else ""))
            StockMove.objects.create(product=p, change=-r["qty"], reason="sold", order=order, by=buyer)
    audit.log("shop_order_placed", actor=buyer, target=order, request=request, total=str(order.total))
    _tell_sellers(order)
    return order


def _tell_sellers(order: Order) -> None:
    from notify import service as notify

    for line in order.lines.select_related("seller"):
        notify.tell(line.seller, "shop_order", related=f"shoporder:{order.pk}:{line.pk}", url="/shop/manage/orders/", item=line.title, qty=str(line.quantity),
                    link=f"{settings.SITE_URL}/shop/manage/orders/")


def _tell_buyer(order: Order) -> None:
    from notify import service as notify
    from web.i18n import tr

    u = order.buyer
    notify.tell(u, "shop_update", related=f"shop:{order.pk}:{order.status}", url=f"/shop/orders/{order.number}/", product=order.number,
                what=tr(u.language, order.get_status_display()), link=f"{settings.SITE_URL}/shop/orders/{order.number}/")


def seller_confirm(line: OrderLine, seller) -> None:
    if line.seller_id != seller.pk or line.order.status != "placed":
        raise ApiError("not_now", "This step is not open yet.", 409)
    line.seller_confirmed_at = timezone.now()
    line.save(update_fields=["seller_confirmed_at"])
    order = line.order
    if not order.lines.filter(seller_confirmed_at__isnull=True).exists():
        advance(order, "confirmed", seller)


def advance(order: Order, status: str, actor, note: str = "") -> Order:
    """Seedha Bazar moves an order forward one step at a time (or cancels it before delivery)."""
    if status == "cancelled":
        return cancel(order, actor, note)
    if status not in STEPS or STEPS.index(status) != STEPS.index(order.status) + 1:
        raise ApiError("not_now", "This step is not open yet.", 409)
    order.status = status
    if status == "delivered" and order.payment == "cod":
        order.paid = True
    if note:
        order.ops_note = note[:300]
    order.save()
    if status == "dispatched":  # couriers on their way; pickups ready to collect
        order.shipments.filter(mode="courier").exclude(status="delivered").update(status="transit")
        order.shipments.filter(mode="pickup").update(status="ready")
    if status == "delivered":
        order.shipments.update(status="delivered")
    if status in ("dispatched", "delivered"):
        gst.issue(order)  # GST documents when the goods leave or are handed over
    audit.log("shop_order_" + status, actor=actor, target=order)
    _tell_buyer(order)
    return order


@transaction.atomic
def cancel(order: Order, actor, note: str = "") -> Order:
    """Before it is on the way, an order can be cancelled; its stock goes back to the makers."""
    staff = actor is None or getattr(actor, "is_staff", False)  # None: the system (an unpaid online order)
    if order.status in ("dispatched", "delivered", "cancelled") and not (staff and order.status == "dispatched"):
        raise ApiError("not_now", "This step is not open yet.", 409)
    if not staff and actor.pk != order.buyer_id:
        raise ApiError("not_allowed", "You cannot do this.", 403)
    for line in order.lines.all():
        Product.objects.filter(pk=line.product_id).update(stock=F("stock") + line.quantity)
        StockMove.objects.create(product_id=line.product_id, change=line.quantity, reason="returned", order=order, by=actor)
    order.status = "cancelled"
    order.ops_note = (note or order.ops_note)[:300]
    order.save()
    order.shipments.update(status="cancelled")
    audit.log("shop_order_cancelled", actor=actor, target=order)
    _tell_buyer(order)
    return order


# ---------- producers' products ----------
def submit(product: Product, changed_price_or_text: bool) -> None:
    """A new product, or a change to its price or description, waits for review again; a stock change does not."""
    if changed_price_or_text or product.status in ("draft", "rejected"):
        product.status = Product.Status.PENDING
        product.save(update_fields=["status"])


def send_to_warehouse(product: Product, quantity: int, note: str = ""):
    """A seller sends stock to the Seedha Bazar warehouse; it becomes sellable when the warehouse receives it."""
    from .models import Inbound
    if product.fulfilment != Product.Fulfilment.WAREHOUSE or quantity <= 0:
        raise ApiError("bad_quantity", "Enter a quantity more than zero.", 400)
    return Inbound.objects.create(product=product, quantity=quantity, note=note[:200])


def receive(inbound, staff, received: int, note: str = "") -> None:
    if inbound.status != "sent":
        raise ApiError("not_now", "This step is not open yet.", 409)
    inbound.received, inbound.status, inbound.received_at = received, "received" if received > 0 else "rejected", timezone.now()
    inbound.note = (note or inbound.note)[:200]
    inbound.save()
    if received > 0:
        add_stock(inbound.product, received, staff, "added", f"Received at the warehouse ({inbound.pk})")


def add_stock(product: Product, change: int, by, reason: str = "added", note: str = "") -> None:
    if product.stock + change < 0:
        raise ApiError("bad_quantity", "Enter a quantity more than zero.", 400)
    Product.objects.filter(pk=product.pk).update(stock=F("stock") + change)
    StockMove.objects.create(product=product, change=change, reason=reason, by=by, note=note[:120])
    product.refresh_from_db(fields=["stock"])


def review(product: Product, staff, decision: str, price=None, note: str = "") -> Product:
    """Seedha Bazar approves (at the producer's price or a changed one) or turns down a product, with a note to the producer."""
    from notify import service as notify
    from web.i18n import tr

    if decision == "approve":
        product.price = D(price) if price not in (None, "") else product.asked_price
        product.status = Product.Status.LIVE
    elif decision == "reject":
        product.status = Product.Status.REJECTED
    else:
        raise ApiError("not_now", "This step is not open yet.", 409)
    product.review_note, product.reviewed_by, product.reviewed_at = note[:300], staff, timezone.now()
    product.save()
    audit.log("shop_product_" + decision, actor=staff, target=product, price=str(product.price))
    u = product.seller
    what = tr(u.language, "On sale") if decision == "approve" else tr(u.language, "Not approved")
    notify.tell(u, "shop_review", related=f"shopreview:{product.pk}:{product.reviewed_at:%s}", url="/shop/manage/", item=product.title, what=what,
                link=f"{settings.SITE_URL}/shop/manage/")
    return product
