from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.errors import ApiError
from accounts.models import Role
from farmerbook.models import CropCycle
from farmerbook.serializers import stock_kg
from market import services
from market.models import Enquiry, Listing
from notify import service as notify
from profiles.models import OrgMembership
from rates import services as rate_services
from rates.crops import CROPS, EMOJI

from . import forms as f
from . import location
from .context import home_for
from .helpers import error_text, ok, role_required, warn

PAGE = 20
MARKET_UNITS = ("quintal", "kg", "tonne", "bag")


def base_for(user) -> str:
    return {"farmer": "web/farmer/base.html", "agent": "web/fpo/base.html", "buyer": "web/buyer/base.html"}.get(user.role, "web/base.html")


def prefix_for(user) -> str:
    return "/fpo" if user.role == Role.AGENT else "/farmer"


def seller_required(view):
    """Farmers with a filled-in profile, and agents of a verified FPO. Everyone else goes to their own page."""

    @wraps(view)
    def wrapper(request, *a, **kw):
        u = request.user
        if not u.is_authenticated:
            return redirect("/login/")
        if u.role == Role.FARMER:
            if u.farmer_profile.level < 1:
                warn(request, "Complete your profile before you list produce.")
                return redirect("/farmer/profile/")
            request.org = None
        elif u.role == Role.AGENT:
            m = OrgMembership.objects.filter(user=u).select_related("organisation").order_by("pk").first()
            if m is None:
                return redirect("/fpo/register/")
            if not m.organisation.verified:
                warn(request, "Your organisation is still being verified. You can add farmers once it is approved.")
                return redirect("/fpo/")
            request.org = m.organisation
        else:
            return redirect(home_for(u))
        return view(request, *a, **kw)

    return wrapper


def card(listing, memo):
    """Adds what a listing card needs: the mandi comparison, an emoji and who is selling (never a phone number)."""
    listing.ref = services.mandi_reference(listing, memo)
    listing.emoji = EMOJI.get(listing.crop, "🌾")
    if listing.organisation_id:
        listing.seller_label, listing.seller_verified, listing.seller_org = listing.organisation.name, listing.organisation.verified, True
    else:
        fp = getattr(listing.seller, "farmer_profile", None)
        first = (fp.name.split() or [""])[0] if fp else ""
        listing.seller_label = " · ".join(x for x in (first, listing.village or (fp.village if fp else "")) if x)
        listing.seller_verified, listing.seller_org = bool(fp and fp.level >= 2), False
    return listing


# ---------- public browse ----------
def browse(request):
    qs = Listing.live().select_related("organisation", "seller__farmer_profile")
    crop = request.GET.get("crop", "")
    district = (request.GET.get("district") or "").strip()
    sort = request.GET.get("sort", "new")
    if crop:
        qs = qs.filter(crop=crop)
    if district:
        qs = qs.filter(district__icontains=district)
    qs = qs.order_by("price_per_quintal" if sort == "cheap" else "-created_at")
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    rows = list(qs[(page - 1) * PAGE:page * PAGE + 1])
    memo: dict = {}
    crops_live = sorted(set(Listing.live().values_list("crop", flat=True)))
    ctx = {"rows": [card(li, memo) for li in rows[:PAGE]], "has_next": len(rows) > PAGE, "page": page, "crop": crop, "district": district, "sort": sort,
           "crop_chips": [{"crop": c, "emoji": EMOJI.get(c, "🌾")} for c in crops_live]}
    return render(request, "web/market/browse.html", ctx)


def detail(request, pk):
    li = get_object_or_404(Listing.objects.select_related("organisation", "seller__farmer_profile"), pk=pk)
    u = request.user
    mine = u.is_authenticated and li.seller_id == u.pk
    if li.status == Listing.Status.HIDDEN and not (mine or (u.is_authenticated and u.is_staff)):
        raise Http404
    enquiry = Enquiry.objects.filter(listing=li, buyer=u).first() if u.is_authenticated and u.role == Role.BUYER else None
    buyer_ready = u.is_authenticated and u.role == Role.BUYER and u.buyer_profile.level >= 1
    quote = rate_services.quote(li.crop, li.state, li.district) if li.crop in CROPS else None
    form = f.EnquiryForm(lang=request.lang, initial={"quantity": li.quantity})
    ctx = {"li": card(li, {}), "mine": mine, "enquiry": enquiry, "buyer_ready": buyer_ready, "form": form, "quote": quote,
           "ref": services.mandi_reference(li), "base_tpl": base_for(u) if u.is_authenticated else "web/base.html"}
    return render(request, "web/market/detail.html", ctx)


@role_required(Role.BUYER)
@require_POST
def enquire(request, pk):
    li = get_object_or_404(Listing, pk=pk)
    form = f.EnquiryForm(request.POST, lang=request.lang)
    if form.is_valid():
        d = form.cleaned_data
        try:
            e = services.start_enquiry(request.user, li, d["quantity"], d["offered_price"], d["message"], request)
        except ApiError as err:
            if err.code == "profile_incomplete":
                warn(request, "Fill in your business details first.")
                return redirect("/buyer/profile/")
            form.add_error(None, error_text(request, err))
        else:
            ok(request, "Your enquiry was sent. The seller will reply here.")
            return redirect(f"/enquiry/{e.pk}/")
    return render(request, "web/market/detail.html", {"li": card(li, {}), "mine": False, "enquiry": None, "buyer_ready": True, "form": form,
                                                       "quote": rate_services.quote(li.crop, li.state, li.district) if li.crop in CROPS else None,
                                                       "ref": services.mandi_reference(li), "base_tpl": base_for(request.user)})


# ---------- sellers: farmers and verified FPOs ----------
def _own_cycle(user, raw):
    """The farmer's crop for a ?cycle= value, or None. A garbled value is ignored rather than breaking the page."""
    import uuid

    try:
        cid = uuid.UUID(str(raw))
    except ValueError:
        return None
    return CropCycle.objects.filter(owner=user, client_id=cid, deleted_at__isnull=True).first() if user.role == Role.FARMER else None


def _initial_for_new(request):
    u = request.user
    g = request.GET
    loc = location.current(request)
    if u.role == Role.FARMER:
        fp = u.farmer_profile
        state, district, village = fp.state, fp.district, fp.village
    else:
        state, district, village = request.org.state, request.org.district, ""
    init = {"state": state or loc.get("state", ""), "district": district or loc.get("district", ""), "village": village, "unit": "quintal"}
    cycle = _own_cycle(u, g.get("cycle")) if g.get("cycle") else None
    if cycle is not None:
        init.update(crop=cycle.crop if cycle.crop in CROPS else "other", crop_other="" if cycle.crop in CROPS else cycle.crop,
                    quantity=max(Decimal(0), (stock_kg(cycle) / 100).quantize(Decimal("0.01"))), unit="quintal")
    elif g.get("crop"):
        init.update(crop=g["crop"] if g["crop"] in CROPS else "other", crop_other="" if g["crop"] in CROPS else g["crop"])
        if g.get("qty"):
            init["quantity"] = g["qty"]
        if g.get("unit") in MARKET_UNITS:
            init["unit"] = g["unit"]
        if g.get("price"):
            init["price"] = g["price"]
    if init.get("crop") in CROPS and not init.get("price"):
        ref = rate_services.typical_price(init["crop"], init["state"], init["district"])
        if ref and init.get("unit") in (None, "quintal"):
            init["price"] = ref["typical"]
    return init, cycle


@seller_required
def my_listings(request):
    u = request.user
    qs = Listing.objects.filter(seller=u).order_by("-created_at")
    rows = list(qs[:100])
    for li in rows:
        li.emoji = EMOJI.get(li.crop, "🌾")
        li.new_enquiries = li.enquiries.filter(status="new").count()
        li.total_enquiries = li.enquiries.count()
    return render(request, "web/market/my_listings.html", {"rows": rows, "base_tpl": base_for(u), "px": prefix_for(u)})


@seller_required
def listing_form(request, pk=None):
    u = request.user
    instance = get_object_or_404(Listing, pk=pk, seller=u) if pk else None
    cycle = None
    if instance is not None:
        init = {k: getattr(instance, k) for k in ("grade", "quantity", "unit", "bag_weight_kg", "price", "state", "district", "village", "variety", "description", "available_from")}
        init.update(crop=instance.crop if instance.crop in CROPS else "other", crop_other="" if instance.crop in CROPS else instance.crop)
        cycle = instance.source_cycle
    else:
        init, cycle = _initial_for_new(request)
    form = f.ListingForm(request.POST or None, initial=init, lang=request.lang)
    if request.method == "POST" and form.is_valid():
        d = dict(form.cleaned_data)
        d["crop"] = form.crop_name()
        d["grade"] = d.get("grade") or "ungraded"
        if cycle is None and request.POST.get("cycle"):
            cycle = _own_cycle(u, request.POST["cycle"])
        d["source_cycle"] = cycle if instance is None else None
        try:
            li = services.save_listing(u, d, org=request.org, instance=instance, request=request)
        except ApiError as e:
            form.add_error(None, error_text(request, e))
        else:
            ok(request, "Listing saved. Buyers can see it now.")
            return redirect(f"{prefix_for(u)}/sell/{li.pk}/")
    ref = None
    crop = (form.data.get("crop") if form.is_bound else init.get("crop")) or ""
    if crop in CROPS:
        ref = rate_services.typical_price(crop, (form.data.get("state") if form.is_bound else init.get("state")) or "", (form.data.get("district") if form.is_bound else init.get("district")) or "")
    return render(request, "web/market/listing_form.html", {"form": form, "instance": instance, "cycle": cycle or (request.GET.get("cycle") or request.POST.get("cycle")),
                                                              "ref": ref, "base_tpl": base_for(u), "px": prefix_for(u)})


@seller_required
def manage_listing(request, pk):
    u = request.user
    li = get_object_or_404(Listing.objects.select_related("organisation"), pk=pk, seller=u)
    enquiries = li.enquiries.select_related("buyer__buyer_profile").order_by("-created_at")
    for e in enquiries:
        e.unseen = e.seller_seen_at is None
    return render(request, "web/market/manage.html", {"li": card(li, {}), "enquiries": enquiries, "base_tpl": base_for(u), "px": prefix_for(u), "ref": services.mandi_reference(li)})


@seller_required
@require_POST
def listing_action(request, pk):
    li = get_object_or_404(Listing, pk=pk, seller=request.user)
    act = request.POST.get("action")
    px = prefix_for(request.user)
    if act == "pause" and li.status == Listing.Status.ACTIVE:
        li.status = Listing.Status.PAUSED
    elif act == "resume" and li.status in (Listing.Status.PAUSED, Listing.Status.ACTIVE):
        li.status = Listing.Status.ACTIVE
        if li.expires_at < timezone.now():
            from market.models import default_expiry
            li.expires_at = default_expiry()
    elif act == "sold":
        li.status = Listing.Status.SOLD
    elif act == "delete":
        if li.enquiries.exists():
            warn(request, "This listing has enquiries, so it cannot be deleted. Mark it sold or pause it.")
            return redirect(f"{px}/sell/{li.pk}/")
        li.delete()
        ok(request, "Removed.")
        return redirect(f"{px}/sell/")
    else:
        return redirect(f"{px}/sell/{li.pk}/")
    li.save()
    ok(request, "Saved.")
    return redirect(f"{px}/sell/{li.pk}/")


# ---------- conversations ----------
def inbox(request):
    u = request.user
    if not u.is_authenticated or u.role not in (Role.FARMER, Role.AGENT, Role.BUYER):
        return redirect("/login/")
    qs = Enquiry.objects.select_related("listing", "buyer__buyer_profile", "listing__seller")
    qs = qs.filter(buyer=u) if u.role == Role.BUYER else qs.filter(listing__seller=u)
    rows = list(qs.order_by("-created_at")[:100])
    for e in rows:
        e.emoji = EMOJI.get(e.listing.crop, "🌾")
        e.last = e.messages.last()
        seen = e.buyer_seen_at if u.role == Role.BUYER else e.seller_seen_at
        e.unseen = seen is None or (e.last is not None and e.last.sender_id != u.pk and e.last.created_at > seen)
    return render(request, "web/market/inbox.html", {"rows": rows, "base_tpl": base_for(u), "is_buyer": u.role == Role.BUYER})


def _party(request, pk):
    u = request.user
    if not u.is_authenticated:
        raise Http404
    e = get_object_or_404(Enquiry.objects.select_related("listing__organisation", "listing__seller__farmer_profile", "buyer__buyer_profile"), pk=pk)
    if u.pk not in (e.buyer_id, e.listing.seller_id):
        raise Http404
    return e, u.pk == e.listing.seller_id


def thread(request, pk):
    if not request.user.is_authenticated:
        return redirect("/login/")
    e, is_seller = _party(request, pk)
    u = request.user
    form = f.ChatForm(lang=request.lang)
    now = timezone.now()
    if is_seller:
        e.seller_seen_at = now
    else:
        e.buyer_seen_at = now
    e.save(update_fields=["seller_seen_at" if is_seller else "buyer_seen_at"])
    li = e.listing
    contact = None
    if e.unlocked:
        contact = services.contact_of(e.buyer) if is_seller else services.contact_of(li.seller, li.organisation)
        contact["wa"] = notify.wa_link("", contact["phone"])
    sale_url = ""
    if is_seller and e.status == Enquiry.Status.ACCEPTED and li.source_cycle_id and u.role == Role.FARMER:
        buyer_name = e.buyer.buyer_profile.business_name or e.buyer.buyer_profile.contact_name
        sale_url = (f"/farmer/book/{li.source_cycle.client_id}/add/sale/?quantity={e.quantity.normalize():f}&unit={li.unit}"
                    f"&rate={(e.offered_price or li.price).normalize():f}&channel=direct_buyer&buyer_note={buyer_name[:80]}")
    return render(request, "web/market/thread.html", {"e": e, "li": card(li, {}), "is_seller": is_seller, "messages_": e.messages.select_related("sender"), "form": form,
                                                       "contact": contact, "sale_url": sale_url, "base_tpl": base_for(u), "closed": e.status in ("declined", "closed")})


@require_POST
def thread_message(request, pk):
    e, _ = _party(request, pk)
    form = f.ChatForm(request.POST, lang=request.lang)
    if form.is_valid():
        try:
            services.post_message(e, request.user, form.cleaned_data["text"], request)
        except ApiError as err:
            messages.error(request, error_text(request, err))
    return redirect(f"/enquiry/{e.pk}/")


@require_POST
def thread_decide(request, pk, accept):
    e, is_seller = _party(request, pk)
    if not is_seller:
        raise Http404
    try:
        services.decide(e, request.user, accept, request)
        ok(request, "Accepted. You can now see each other's contact." if accept else "Declined.")
    except ApiError as err:
        messages.error(request, error_text(request, err))
    return redirect(f"/enquiry/{e.pk}/")


@require_POST
def thread_close(request, pk):
    e, is_seller = _party(request, pk)
    sold = is_seller and request.POST.get("sold") == "1"
    services.close(e, request.user, sold, request)
    if sold:
        li = e.listing
        li.status = Listing.Status.SOLD
        li.save()
    ok(request, "Closed.")
    return redirect(f"/enquiry/{e.pk}/")
