"""Buyers find producers and order produce or processed goods to measure; both sides agree, sign, pay and deliver here."""
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

import catalog
from accounts import audit
from accounts.errors import ApiError
from accounts.models import Role, User
from catalog import services as cat
from deals import directory, services
from deals.models import Deal, Payment
from market.models import Listing
from market.services import contact_of
from notify import service as notify
from profiles.models import Organisation
from rates import services as rate_services
from rates.crops import CROPS

from .forms import LangForm, date_field
from .helpers import error_text, ok, warn
from .i18n import tr
from .market_views import base_for, card

UNITS = [("kg", "Kg"), ("quintal", "Quintal"), ("tonne", "Tonne")]


class TermsForm(LangForm):
    quantity = forms.DecimalField(label="Quantity", min_value=Decimal("0.001"), decimal_places=3, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    unit = forms.ChoiceField(label="Unit", choices=UNITS, initial="kg")
    price = forms.DecimalField(label="Price (₹ per unit chosen above)", min_value=Decimal("0.01"), decimal_places=2, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    advance_pct = forms.IntegerField(label="Advance paid after signing (%)", min_value=0, max_value=90, initial=20, widget=forms.NumberInput(attrs={"inputmode": "numeric"}))
    delivery_by = date_field("Deliver by")
    note = forms.CharField(label="Note (optional)", max_length=300, required=False)


class RequestForm(TermsForm):
    product = forms.ChoiceField(label="What do you need?", choices=[])
    quality = forms.CharField(label="Quality you need (optional)", max_length=300, required=False, widget=forms.TextInput(attrs={"placeholder": "e.g. moisture below 10%, cleaned, no stones"}))
    packaging = forms.ChoiceField(label="Packing", choices=[("bulk", "Loose, in bulk"), ("packed", "Packed for retail")], initial="bulk", required=False)
    pack_size_g = forms.IntegerField(label="Grams (or ml) in one pack", required=False, min_value=1, max_value=100000)
    delivery_place = forms.CharField(label="Deliver to", max_length=200, required=False)

    def __init__(self, *args, products=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].choices = [(k, tr(self.lang, catalog.name(k))) for k in products]
        self.fields["note"].label = tr(self.lang, "Message to the seller (optional)")
        self.fields["quality"].widget.attrs["placeholder"] = tr(self.lang, "e.g. moisture below 10%, cleaned, no stones")
        self.order_fields(["product", "quantity", "unit", "quality", "packaging", "pack_size_g", "price", "advance_pct", "delivery_by", "delivery_place", "note"])


def _buyer_ready(request):
    u = request.user
    if not u.is_authenticated:
        return redirect(f"/login/?as=buyer&next={request.path}")
    if u.role != Role.BUYER:
        raise Http404
    if u.buyer_profile.level < 1:
        warn(request, "Fill in your business details first.")
        return redirect("/buyer/profile/")
    return None


def producers(request):
    stop = _buyer_ready(request)
    if stop:
        return stop
    crop = request.GET.get("crop", "")
    district = (request.GET.get("district") or "").strip()
    kind = request.GET.get("kind", "")
    rows = directory.search(crop=crop if crop in catalog.PRODUCTS else "", district=district, kind=kind if kind in ("farmer", "fpo") else "")
    from catalog.services import featured_districts
    return render(request, "web/deals/producers.html", {"rows": rows, "crop": crop, "district": district, "kind": kind,
                                                        "crops": [(k, catalog.emoji(k)) for k in CROPS], "spotlight": featured_districts("", 10) if not (crop or district) else []})


def _producer(kind, pk):
    if kind == "farmer":
        u = get_object_or_404(User, pk=pk, role=Role.FARMER, farmer_profile__discoverable=True, farmer_profile__level__gte=1)
        return directory.farmer_card(u.farmer_profile), u, None
    if kind == "fpo":
        org = get_object_or_404(Organisation, pk=pk, verified=True)
        return directory.fpo_card(org), services.seller_for_org(org), org
    raise Http404


def producer(request, kind, pk):
    stop = _buyer_ready(request)
    if stop:
        return stop
    c, seller, org = _producer(kind, pk)
    listings = Listing.live().filter(organisation=org) if org else Listing.live().filter(seller=seller, organisation__isnull=True)
    odop = cat.odop_for(c["state"], c["district"])
    return render(request, "web/deals/producer.html", {"c": c, "can_make": directory.can_make(c), "listings": [card(li, {}) for li in listings[:6]], "odop": odop,
                                                       "past": Deal.objects.filter(seller=seller, status="completed").count() if seller else 0})


def _price_hint(product, state, district):
    if catalog.kind(product) == catalog.SEMI:
        rp = cat.reference_price(product, state)
        return {"per": "kg", "typical": rp["typical"], "low": rp["low"], "high": rp["high"], "source": rp["source"]} if rp else None
    ref = rate_services.typical_price(product, state, district) if product in CROPS else None
    return {"per": "quintal", "typical": ref["typical"], "source": "mandi", "as_of": ref["as_of"]} if ref else None


def new(request):
    stop = _buyer_ready(request)
    if stop:
        return stop
    kind = "fpo" if request.GET.get("fpo") or request.POST.get("fpo") else "farmer"
    pk = request.GET.get(kind) or request.POST.get(kind)
    if not (pk or "").isdigit():
        return redirect("/buyer/producers/")
    c, seller, org = _producer(kind, int(pk))
    products = list(dict.fromkeys(list(c["stock"]) + c["grows"] + directory.can_make(c)))
    products = [p for p in products if p in catalog.PRODUCTS]
    want = request.GET.get("product") if request.GET.get("product") in products else (products[0] if products else "")
    init = {"product": want, "unit": "kg" if catalog.kind(want) == catalog.SEMI else "quintal", "advance_pct": 20,
            "delivery_by": timezone.localdate() + timedelta(days=21), "delivery_place": request.user.buyer_profile.city}
    hint = _price_hint(want, c["state"], c["district"]) if want else None
    if hint:
        init["price"] = hint["typical"]
    form = RequestForm(request.POST or None, initial=init, lang=request.lang, products=products)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        src = ""
        if catalog.kind(d["product"]) == catalog.SEMI:
            src = next((cv[0] for cv in cat.conversions_to(d["product"]) if cv[0] in c["grows"]), "")
        try:
            deal = services.request(request.user, {**d, "seller": seller if org is None else None, "organisation": org, "source_crop": src, "message": d.get("note", "")}, request)
        except ApiError as e:
            form.add_error(None, error_text(request, e))
        else:
            ok(request, "Request sent. The seller will reply here.")
            return redirect(f"/deals/{deal.pk}/")
    return render(request, "web/deals/new.html", {"c": c, "form": form, "hint": hint, "want": want, "kind": kind, "pk": pk})


def my_deals(request):
    u = request.user
    if not u.is_authenticated or u.role not in (Role.BUYER, Role.FARMER, Role.AGENT):
        return redirect("/login/")
    if u.role == Role.BUYER:
        qs = Deal.objects.filter(buyer=u)
    elif u.role == Role.AGENT:
        from django.db.models import Q
        qs = Deal.objects.filter(Q(seller=u) | Q(organisation__memberships__user=u)).distinct()
    else:
        qs = Deal.objects.filter(seller=u)
    rows = list(qs.select_related("buyer__buyer_profile", "seller__farmer_profile", "organisation")[:100])
    for d in rows:
        seen = d.buyer_seen_at if u.role == Role.BUYER else d.seller_seen_at
        d.unseen = d.is_open and (seen is None or d.updated_at > seen)
        d.emoji = catalog.emoji(d.product)
    return render(request, "web/deals/list.html", {"rows": rows, "base_tpl": base_for(u), "is_buyer": u.role == Role.BUYER})


def _deal(request, pk):
    if not request.user.is_authenticated:
        raise Http404
    d = get_object_or_404(Deal.objects.select_related("buyer__buyer_profile", "seller__farmer_profile", "organisation"), pk=pk)
    side = services.side_of(d, request.user)
    if not side:
        raise Http404
    return d, side


def detail(request, pk):
    d, side = _deal(request, pk)
    now = timezone.now()
    if side == "buyer":
        d.buyer_seen_at = now
    else:
        d.seller_seen_at = now
    Deal.objects.filter(pk=d.pk).update(**({"buyer_seen_at": now} if side == "buyer" else {"seller_seen_at": now}))
    offer = services.latest_offer(d)
    ag = getattr(d, "agreement", None)
    contact = None
    if services.contacts_visible(d):
        contact = contact_of(d.buyer) if side == "seller" else contact_of(d.seller, d.organisation)
        contact["wa"] = notify.wa_link("", contact["phone"])
    need = services.raw_needed(d)
    if need and side == "seller":
        from market import stock
        owners = [d.seller] if not d.organisation_id else list(User.objects.filter(farmer_profile__organisation=d.organisation))
        need["have"] = sum((ln["free_kg"] for ln in stock.lines(owners, crop=need["crop"])), Decimal(0))
    pending_payment = d.payments.filter(confirmed_at__isnull=True, disputed=False).last()
    sale_url = ""
    if side == "seller" and d.status == "completed" and d.seller.role == Role.FARMER and not d.organisation_id:
        from farmerbook.models import CropCycle
        cyc = CropCycle.objects.filter(owner=d.seller, crop__in=[d.product, d.source_crop], deleted_at__isnull=True).order_by("-created_at").first()
        if cyc:
            qty = d.received_quantity if d.received_quantity is not None else d.quantity
            sale_url = (f"/farmer/book/{cyc.client_id}/add/sale/?quantity={qty.normalize():f}&unit={d.unit}&rate={d.price.normalize():f}&channel=direct_buyer"
                        + (f"&product={d.product}" if d.product != cyc.crop else "") + f"&buyer_note={d.buyer.buyer_profile.business_name[:80]}")
    ctx = {"d": d, "side": side, "offer": offer, "offers": d.offers.select_related("by"), "ag": ag, "contact": contact, "need": need,
           "events": d.events.select_related("by"), "payments": d.payments.all(), "pending_payment": pending_payment, "balance": services.balance_due(d),
           "advance_confirmed": services.paid_confirmed(d, "advance"), "terms_form": TermsForm(lang=request.lang, initial={"quantity": offer.quantity if offer else d.quantity, "unit": d.unit,
           "price": offer.price if offer else d.price, "advance_pct": offer.advance_pct if offer else d.advance_pct, "delivery_by": offer.delivery_by if offer else d.delivery_by}),
           "my_turn": offer is not None and offer.side != side and d.status in ("requested", "negotiating"), "sale_url": sale_url, "methods": Payment.Method.choices,
           "i_signed": ag and ((side == "buyer" and ag.buyer_signed_at) or (side == "seller" and ag.seller_signed_at)), "base_tpl": base_for(request.user)}
    return render(request, "web/deals/detail.html", ctx)


@require_POST
def act(request, pk, action):
    d, side = _deal(request, pk)
    u = request.user
    P = request.POST
    try:
        if action == "counter":
            f = TermsForm(P, lang=request.lang)
            if not f.is_valid():
                raise ApiError("bad_terms", "Check the terms and try again.", 400)
            t = f.cleaned_data
            if t["unit"] != d.unit:
                from farmerbook.units import to_kg
                t["quantity"] = (to_kg(t["quantity"], t["unit"]) / to_kg(Decimal(1), d.unit)).quantize(Decimal("0.001"))
                t["price"] = (t["price"] * to_kg(Decimal(1), d.unit) / to_kg(Decimal(1), t["unit"])).quantize(Decimal("0.01"))
            services.counter(d, u, t, request)
            ok(request, "Your offer was sent.")
        elif action == "accept":
            services.accept(d, u, request)
            ok(request, "Terms agreed. Now sign the agreement.")
        elif action == "decline":
            services.decline(d, u, request)
            ok(request, "Closed.")
        elif action == "code":
            from accounts.audit import client_ip
            services.send_sign_code(d, u, client_ip(request))
            from accounts.otp import static_code_for
            trial = static_code_for(u.phone)
            if trial:
                ok(request, "Trial period: SMS is not switched on yet. Use the code {code}.", code=trial)
            else:
                ok(request, "A code was sent to your phone. Enter it to sign.")
            request.session[f"sign_{d.pk}"] = True
        elif action == "sign":
            from accounts.audit import client_ip
            services.sign(d, u, P.get("code", ""), client_ip(request), request.META.get("HTTP_USER_AGENT", ""), request)
            ok(request, "Signed.")
        elif action == "pay":
            try:
                amount = Decimal(P.get("amount", "0"))
            except Exception:
                amount = None
            services.record_payment(d, u, P.get("kind", "advance"), amount, P.get("method", "upi"), P.get("reference", ""), request)
            ok(request, "Saved. The seller will confirm.")
        elif action in ("received", "not_received"):
            p = get_object_or_404(Payment, pk=P.get("payment"), deal=d)
            services.confirm_payment(d, u, p, action == "received", request)
            ok(request, "Saved.")
        elif action in ("message", "progress", "issue"):
            services.post(d, u, P.get("text", ""), action)
        elif action == "dispatch":
            services.dispatch(d, u, P.get("note", ""))
            ok(request, "Saved.")
        elif action == "deliver":
            try:
                qty = Decimal(P.get("received", ""))
            except Exception:
                qty = None
            services.deliver(d, u, qty, P.get("ok") == "1", P.get("note", ""))
            ok(request, "Saved.")
        elif action == "rate":
            services.rate(d, u, int(P.get("stars", "0") or 0))
            ok(request, "Thank you.")
        else:
            raise Http404
    except ApiError as e:
        warn(request, error_text(request, e))
    return redirect(f"/deals/{d.pk}/")


def agreement(request, pk):
    d, side = _deal(request, pk)
    ag = getattr(d, "agreement", None)
    if ag is None:
        raise Http404
    return render(request, "web/deals/agreement.html", {"d": d, "ag": ag})
