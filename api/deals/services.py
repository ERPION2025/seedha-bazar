"""Rules for made-to-order deals. Views call these; nothing here knows about HTML.

Who acts when:
  buyer   sends the request; either side counters; the side that did NOT make the newest offer accepts it.
  both    sign the agreement with a one-time code on their own phone (method "otp"); contacts unlock once both have signed.
  buyer   pays the advance outside the app (UPI/bank) and records it; the seller confirms receiving it.
  seller  posts progress, then dispatches; the buyer confirms delivery and pays the balance; the seller confirms; done.
Payment moves outside the app until a payment connector is set up, so every payment needs both sides to agree it happened.
"""
import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import catalog
from accounts import audit, otp
from accounts.errors import ApiError
from accounts.models import Role
from catalog import services as cat
from farmerbook.units import to_kg
from market.services import mask_contacts
from notify import service as notify
from profiles.models import OrgMembership

from .models import Agreement, Deal, DealEvent, Offer, Payment

D = Decimal
UNITS = ("kg", "quintal", "tonne")
MAX_ADVANCE = 90


def link(deal) -> str:
    return f"{settings.SITE_URL}/deals/{deal.pk}/"


def side_of(deal: Deal, user) -> str:
    """'buyer', 'seller' or '' for someone with no part in it. Any agent of the selling FPO acts for the seller."""
    if not user or not user.is_authenticated:
        return ""
    if user.pk == deal.buyer_id:
        return "buyer"
    if user.pk == deal.seller_id:
        return "seller"
    if deal.organisation_id and user.role == Role.AGENT and OrgMembership.objects.filter(user=user, organisation_id=deal.organisation_id).exists():
        return "seller"
    return ""


def _require(deal, user, side=None) -> str:
    s = side_of(deal, user)
    if not s or (side and s != side):
        raise ApiError("not_your_deal", "Only the buyer or the seller can do this.", 403)
    return s


def _tell(deal: Deal, to_side: str, what: str):
    """Text the other side about a step, in their language."""
    from web.i18n import tr

    person = deal.buyer if to_side == "buyer" else deal.seller
    notify.send("sms", person.phone, "deal_update", person.language, user=person, related=f"deal:{deal.pk}",
                what=tr(person.language, what), product=tr(person.language, catalog.name(deal.product)), link=link(deal))


def _event(deal, user, kind, text, mask=False):
    masked = False
    if mask and not (hasattr(deal, "agreement") and deal.agreement.fully_signed):
        text, masked = mask_contacts(text)
    return DealEvent.objects.create(deal=deal, by=user, kind=kind, text=text[:500], masked=masked)


def _check_terms(quantity, price, advance_pct, delivery_by):
    if quantity is None or quantity <= 0:
        raise ApiError("bad_quantity", "Enter a quantity more than zero.", 400)
    if price is None or price <= 0:
        raise ApiError("bad_price", "Enter a price more than zero.", 400)
    if advance_pct is None or not 0 <= advance_pct <= MAX_ADVANCE:
        raise ApiError("bad_advance", "The advance must be between 0% and 90%.", 400)
    if delivery_by is None or delivery_by <= timezone.localdate():
        raise ApiError("bad_date", "Choose a delivery date after today.", 400)


def seller_for_org(org):
    m = OrgMembership.objects.filter(organisation=org).select_related("user").order_by("pk").first()
    return m.user if m else None


@transaction.atomic
def request(buyer, data: dict, request=None) -> Deal:
    """`data`: seller (user) and/or organisation, product, source_crop, quantity, unit, quality, packaging, pack_size_g, price, advance_pct, delivery_by, delivery_place, message."""
    if buyer.role != Role.BUYER:
        raise ApiError("buyers_only", "Only buyers can send enquiries.", 403)
    if getattr(getattr(buyer, "buyer_profile", None), "level", 0) < 1:
        raise ApiError("profile_incomplete", "Fill in your business details first.", 403)
    org = data.get("organisation")
    seller = data.get("seller") or (seller_for_org(org) if org else None)
    if seller is None or (org is None and seller.role != Role.FARMER) or (org is not None and not org.verified):
        raise ApiError("seller_unavailable", "This seller cannot take requests right now.", 400)
    if org is None and not seller.farmer_profile.discoverable:
        raise ApiError("seller_unavailable", "This seller cannot take requests right now.", 400)
    product = data["product"]
    if product not in catalog.PRODUCTS:
        raise ApiError("unknown_product", "Choose a product from the list.", 400)
    if data["unit"] not in UNITS:
        raise ApiError("bad_unit", "Choose kg, quintal or tonne.", 400)
    _check_terms(data["quantity"], data["price"], data["advance_pct"], data["delivery_by"])
    if Deal.objects.filter(buyer=buyer, seller=seller, product=product, status__in=["requested", "negotiating"]).exists():
        raise ApiError("already_requested", "You already have an open request for this with this seller.", 409)
    deal = Deal.objects.create(
        buyer=buyer, seller=seller, organisation=org, product=product, source_crop=data.get("source_crop", "") if catalog.kind(product) == catalog.SEMI else "",
        quantity=data["quantity"], unit=data["unit"], quality=(data.get("quality") or "")[:300], packaging=data.get("packaging") or "bulk",
        pack_size_g=data.get("pack_size_g"), price=data["price"], advance_pct=data["advance_pct"], delivery_by=data["delivery_by"],
        delivery_place=(data.get("delivery_place") or "")[:200], buyer_seen_at=timezone.now())
    Offer.objects.create(deal=deal, by=buyer, side="buyer", quantity=deal.quantity, price=deal.price, advance_pct=deal.advance_pct, delivery_by=deal.delivery_by,
                         note=mask_contacts((data.get("message") or "")[:300])[0])  # terms are agreed before signing, so contacts stay hidden
    if data.get("message"):
        _event(deal, buyer, DealEvent.Kind.MESSAGE, data["message"], mask=True)
    audit.log("deal_requested", actor=buyer, target=deal, request=request)
    person = deal.seller
    from web.i18n import tr
    notify.send("sms", person.phone, "deal_request", person.language, user=person, related=f"deal:{deal.pk}",
                product=tr(person.language, catalog.name(product)), qty=f"{deal.quantity.normalize():f} {tr(person.language, deal.unit)}", link=link(deal))
    return deal


def latest_offer(deal: Deal) -> Offer | None:
    return deal.offers.order_by("-created_at", "-pk").first()


@transaction.atomic
def counter(deal: Deal, user, terms: dict, request=None) -> Offer:
    side = _require(deal, user)
    if deal.status not in ("requested", "negotiating"):
        raise ApiError("deal_locked", "The terms can no longer be changed.", 409)
    _check_terms(terms["quantity"], terms["price"], terms["advance_pct"], terms["delivery_by"])
    o = Offer.objects.create(deal=deal, by=user, side=side, quantity=terms["quantity"], price=terms["price"], advance_pct=terms["advance_pct"],
                             delivery_by=terms["delivery_by"], note=mask_contacts((terms.get("note") or "")[:300])[0])
    deal.status = Deal.Status.NEGOTIATING
    deal.save()
    _event(deal, user, DealEvent.Kind.SYSTEM, "New terms offered")
    _tell(deal, "seller" if side == "buyer" else "buyer", "New terms offered")
    return o


def agreement_text(deal: Deal, terms: dict) -> str:
    lines = [
        "SUPPLY AGREEMENT made on Seedha Bazar",
        f"Agreement no: SB-{deal.pk:06d}    Date: {terms['date']}",
        f"Buyer: {terms['buyer']['business']} ({terms['buyer']['name']}), {terms['buyer']['city']}",
        f"Seller: {terms['seller']['name']}, {terms['seller']['place']}",
        "",
        f"1. Goods: {terms['product']}" + (f", made from {terms['source_crop']}" if terms["source_crop"] else ""),
        f"2. Quantity: {terms['quantity']} {terms['unit']}. Quality: {terms['quality'] or 'fair average quality'}." + (f" Packed in {terms['pack_size_g']} g packs." if terms["packaging"] == "packed" and terms["pack_size_g"] else ""),
        f"3. Price: Rs {terms['price']} per {terms['unit']}. Total: Rs {terms['total']}.",
        f"4. Advance: {terms['advance_pct']}% (Rs {terms['advance']}) paid by the buyer after both sign. The seller starts work once the advance is received.",
        f"5. Delivery: by {terms['delivery_by']} at {terms['delivery_place'] or 'a place both agree in writing'}.",
        "6. Balance: paid by the buyer within 7 days of delivery, for the quantity received.",
        "7. Quality check: the buyer checks the goods on delivery and records any shortfall or quality problem on Seedha Bazar within 2 days.",
        "8. If the seller cannot deliver, the advance is returned in full within 7 days. If the buyer cancels after work has started, the advance is kept to cover the seller's costs.",
        "9. Disputes are first raised on Seedha Bazar for mediation. This agreement is governed by the laws of India.",
        "",
        "Both parties confirmed this agreement with a one-time code sent to their registered mobile number.",
    ]
    return "\n".join(lines)


def _party_terms(deal: Deal) -> dict:
    bp = deal.buyer.buyer_profile
    if deal.organisation_id:
        org = deal.organisation
        seller = {"name": org.name, "place": f"{org.district}, {org.state}", "kind": "fpo"}
    else:
        fp = deal.seller.farmer_profile
        seller = {"name": fp.name, "place": f"{fp.village}, {fp.district}, {fp.state}", "kind": "farmer"}
    return {"buyer": {"name": bp.contact_name, "business": bp.business_name, "city": bp.city}, "seller": seller}


@transaction.atomic
def accept(deal: Deal, user, request=None) -> Agreement:
    side = _require(deal, user)
    if deal.status not in ("requested", "negotiating"):
        raise ApiError("deal_locked", "The terms can no longer be changed.", 409)
    o = latest_offer(deal)
    if o is None or o.side == side:
        raise ApiError("wait_for_other_side", "Wait for the other side to answer your offer.", 409)
    deal.quantity, deal.price, deal.advance_pct, deal.delivery_by = o.quantity, o.price, o.advance_pct, o.delivery_by
    deal.status, deal.agreed_at = Deal.Status.AGREED, timezone.now()
    deal.save()
    terms = {**_party_terms(deal), "date": timezone.localdate().isoformat(), "product": catalog.name(deal.product), "source_crop": catalog.name(deal.source_crop) if deal.source_crop else "",
             "quantity": f"{deal.quantity.normalize():f}", "unit": deal.unit, "quality": deal.quality, "packaging": deal.packaging, "pack_size_g": deal.pack_size_g,
             "price": f"{deal.price.normalize():f}", "total": str(deal.total), "advance_pct": deal.advance_pct, "advance": str(deal.advance_amount),
             "delivery_by": deal.delivery_by.isoformat(), "delivery_place": deal.delivery_place}
    text = agreement_text(deal, terms)
    ag = Agreement.objects.create(deal=deal, terms=terms, text=text, doc_hash=hashlib.sha256(json.dumps(terms, sort_keys=True).encode() + text.encode()).hexdigest())
    _event(deal, user, DealEvent.Kind.SYSTEM, "Terms agreed. Both sides now sign the agreement.")
    _tell(deal, "seller" if side == "buyer" else "buyer", "Terms agreed. Please sign the agreement.")
    audit.log("deal_agreed", actor=user, target=deal, request=request)
    return ag


def send_sign_code(deal: Deal, user, ip=None):
    _require(deal, user)
    if deal.status != Deal.Status.AGREED:
        raise ApiError("deal_locked", "The terms can no longer be changed.", 409)
    return otp.request_otp(user.phone, "sms", ip, user.language)


@transaction.atomic
def sign(deal: Deal, user, code: str, ip=None, agent="", request=None) -> Agreement:
    side = _require(deal, user)
    if deal.status != Deal.Status.AGREED:
        raise ApiError("deal_locked", "The terms can no longer be changed.", 409)
    ag = deal.agreement
    if (side == "buyer" and ag.buyer_signed_at) or (side == "seller" and ag.seller_signed_at):
        raise ApiError("already_signed", "You have already signed.", 409)
    otp.verify_code(user.phone, code)
    now = timezone.now()
    if side == "buyer":
        ag.buyer_signed_at, ag.buyer_sign_ip, ag.buyer_sign_agent = now, ip, agent[:200]
    else:
        ag.seller_signed_at, ag.seller_signer, ag.seller_sign_ip, ag.seller_sign_agent = now, user, ip, agent[:200]
    ag.save()
    audit.log("deal_signed", actor=user, target=deal, request=request, side=side, doc_hash=ag.doc_hash)
    if ag.fully_signed:
        deal.status = Deal.Status.SIGNED if deal.advance_pct else Deal.Status.IN_PROGRESS
        deal.save()
        _event(deal, None, DealEvent.Kind.SYSTEM, "Agreement signed by both. Contacts are now visible." + (" Waiting for the advance." if deal.advance_pct else ""))
        _tell(deal, "buyer", "Agreement signed by both")
        _tell(deal, "seller", "Agreement signed by both")
    else:
        _tell(deal, "seller" if side == "buyer" else "buyer", "The other side signed. Please sign too.")
    return ag


def paid_confirmed(deal: Deal, kind: str) -> D:
    return sum((p.amount for p in deal.payments.filter(kind=kind, confirmed_at__isnull=False, disputed=False)), D(0))


@transaction.atomic
def record_payment(deal: Deal, user, kind: str, amount, method: str, reference: str, request=None) -> Payment:
    _require(deal, user, "buyer")
    if kind == "advance" and deal.status != Deal.Status.SIGNED:
        raise ApiError("not_now", "This step is not open yet.", 409)
    if kind == "balance" and deal.status != Deal.Status.DELIVERED:
        raise ApiError("not_now", "This step is not open yet.", 409)
    if amount is None or amount <= 0:
        raise ApiError("bad_amount", "Enter the amount paid.", 400)
    p = Payment.objects.create(deal=deal, kind=kind, amount=amount, method=method if method in Payment.Method.values else "upi", reference=(reference or "")[:80])
    if kind == "advance":
        deal.status = Deal.Status.ADVANCE_PAID
        deal.save()
    _event(deal, user, DealEvent.Kind.SYSTEM, f"{'Advance' if kind == 'advance' else 'Final payment'} of Rs {amount} marked as paid. Seller to confirm.")
    _tell(deal, "seller", "Payment marked as paid. Please confirm you received it.")
    audit.log("deal_payment_marked", actor=user, target=deal, request=request, kind=kind, amount=str(amount))
    return p


def balance_due(deal: Deal) -> D:
    qty = deal.received_quantity if deal.received_quantity is not None else deal.quantity
    return max(D(0), (qty * deal.price).quantize(D("1")) - paid_confirmed(deal, "advance") - paid_confirmed(deal, "balance"))


@transaction.atomic
def confirm_payment(deal: Deal, user, payment: Payment, received: bool, request=None) -> Payment:
    _require(deal, user, "seller")
    if payment.deal_id != deal.pk or payment.confirmed_at or payment.disputed:
        raise ApiError("not_now", "This step is not open yet.", 409)
    if not received:
        payment.disputed = True
        payment.save()
        if payment.kind == "advance":
            deal.status = Deal.Status.SIGNED
            deal.save()
        _event(deal, user, DealEvent.Kind.ISSUE, "Seller has not received the payment.")
        _tell(deal, "buyer", "The seller has not received your payment. Please check.")
        return payment
    payment.confirmed_at = timezone.now()
    payment.save()
    if payment.kind == "advance":
        deal.status = Deal.Status.IN_PROGRESS
        _event(deal, user, DealEvent.Kind.SYSTEM, "Advance received. Work has started.")
        _tell(deal, "buyer", "Advance received. Work has started.")
    elif balance_due(deal) <= 0:
        deal.status, deal.completed_at = Deal.Status.COMPLETED, timezone.now()
        _event(deal, user, DealEvent.Kind.SYSTEM, "Paid in full. Order completed.")
        _tell(deal, "buyer", "Order completed")
    deal.save()
    audit.log("deal_payment_confirmed", actor=user, target=deal, request=request, kind=payment.kind)
    return payment


def post(deal: Deal, user, text: str, kind: str = "message") -> DealEvent:
    side = _require(deal, user)
    text = (text or "").strip()
    if not text:
        raise ApiError("empty_message", "Write a message first.", 400)
    if kind == "progress" and (side != "seller" or deal.status != Deal.Status.IN_PROGRESS):
        raise ApiError("not_now", "This step is not open yet.", 409)
    e = _event(deal, user, kind if kind in ("message", "progress", "issue") else "message", text, mask=True)
    _tell(deal, "buyer" if side == "seller" else "seller", "New message" if kind == "message" else "Update on your order" if kind == "progress" else "A problem was reported")
    return e


@transaction.atomic
def dispatch(deal: Deal, user, note: str = "") -> Deal:
    _require(deal, user, "seller")
    if deal.status != Deal.Status.IN_PROGRESS:
        raise ApiError("not_now", "This step is not open yet.", 409)
    deal.status = Deal.Status.DISPATCHED
    deal.save()
    _event(deal, user, DealEvent.Kind.DISPATCH, note or "Goods sent")
    _tell(deal, "buyer", "Your order has been sent")
    return deal


@transaction.atomic
def deliver(deal: Deal, user, received_quantity, ok: bool, note: str = "") -> Deal:
    _require(deal, user, "buyer")
    if deal.status != Deal.Status.DISPATCHED:
        raise ApiError("not_now", "This step is not open yet.", 409)
    if received_quantity is None or received_quantity < 0 or received_quantity > deal.quantity * D("1.1"):
        raise ApiError("bad_quantity", "Enter a quantity more than zero.", 400)
    deal.received_quantity = received_quantity
    deal.status = Deal.Status.DELIVERED
    deal.save()
    _event(deal, user, DealEvent.Kind.DELIVERY if ok else DealEvent.Kind.ISSUE,
           (f"Received {received_quantity.normalize():f} {deal.unit}." + (f" {note}" if note else "")) if ok else f"Received {received_quantity.normalize():f} {deal.unit} with a problem: {note}")
    if balance_due(deal) <= 0:
        deal.status, deal.completed_at = Deal.Status.COMPLETED, timezone.now()
        deal.save()
    _tell(deal, "seller", "The buyer confirmed delivery" if ok else "The buyer reported a problem with the delivery")
    return deal


def decline(deal: Deal, user, request=None) -> Deal:
    side = _require(deal, user)
    if deal.status not in ("requested", "negotiating", "agreed"):
        raise ApiError("deal_locked", "The terms can no longer be changed.", 409)
    deal.status = Deal.Status.DECLINED if side == "seller" else Deal.Status.CANCELLED
    deal.save()
    _event(deal, user, DealEvent.Kind.SYSTEM, "Declined by the seller." if side == "seller" else "Cancelled by the buyer.")
    _tell(deal, "buyer" if side == "seller" else "seller", "The request was closed")
    audit.log("deal_closed", actor=user, target=deal, request=request)
    return deal


def rate(deal: Deal, user, stars: int) -> Deal:
    side = _require(deal, user)
    if deal.status != Deal.Status.COMPLETED or not 1 <= stars <= 5:
        raise ApiError("not_now", "This step is not open yet.", 409)
    if side == "buyer":
        deal.buyer_rating = stars
    else:
        deal.seller_rating = stars
    deal.save()
    return deal


def contacts_visible(deal: Deal) -> bool:
    return hasattr(deal, "agreement") and deal.agreement.fully_signed


def raw_needed(deal: Deal) -> dict | None:
    """For a processed product: about how much of the crop the seller needs, against what their book shows."""
    if catalog.kind(deal.product) != catalog.SEMI:
        return None
    convs = [c for c in cat.conversions_to(deal.product) if not deal.source_crop or c[0] == deal.source_crop]
    if not convs:
        return None
    frm, _, yld, *_ = convs[0]
    out_kg = to_kg(deal.quantity, deal.unit)
    need = (out_kg * 100 / ((D(yld[0]) + D(yld[1])) / 2)).quantize(D("1"))
    return {"crop": frm, "kg": need, "yield_low": yld[0], "yield_high": yld[1]}


def unread_for(user) -> int:
    from django.db.models import F, Q

    if user.role == Role.BUYER:
        return Deal.objects.filter(buyer=user).filter(Q(buyer_seen_at__isnull=True) | Q(updated_at__gt=F("buyer_seen_at"))).filter(status__in=Deal.OPEN).count()
    qs = Deal.objects.filter(Q(seller=user) | Q(organisation__memberships__user=user)) if user.role == Role.AGENT else Deal.objects.filter(seller=user)
    return qs.filter(Q(seller_seen_at__isnull=True) | Q(updated_at__gt=F("seller_seen_at"))).filter(status__in=Deal.OPEN).distinct().count()
