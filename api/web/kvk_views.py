"""Control centre for KVKs and research centres: the whole picture of their districts, the issue desk, input offers, farmers and FPOs."""
from decimal import Decimal
from functools import wraps

from django import forms
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

import catalog
from accounts.errors import ApiError
from accounts.models import Role, User
from deals import directory
from extension import geo, scope
from extension import services as ext
from extension.models import Centre, InputOffer, InputRequest
from issues import services as issue_services
from issues.models import Issue, Reply
from profiles.models import FarmerProfile, Organisation
from rates.crops import CROPS

from .forms import LangForm, date_field
from .helpers import error_text, ok, warn


def kvk_only(view):
    @wraps(view)
    def wrapper(request, *a, **kw):
        u = request.user
        if not u.is_authenticated:
            return redirect("/login/?as=kvk")
        centres = list(scope.centres_of(u)) if u.role == Role.AGRONOMIST else (list(Centre.objects.all()) if u.is_staff else [])
        if not centres:
            if u.role == Role.AGRONOMIST:
                return render(request, "web/kvk/no_centre.html")
            from .context import home_for
            return redirect(home_for(u))
        cid = request.session.get("kvk_centre")
        request.centre = next((c for c in centres if c.pk == cid), centres[0])
        request.centres = centres
        d = request.session.get("kvk_district", "")
        request.district = d if d in request.centre.districts else ""
        return view(request, *a, **kw)

    return wrapper


def _ctx(request, **kw):
    return {"centre": request.centre, "centres": request.centres, "district": request.district, **kw}


@kvk_only
def dashboard(request):
    pic = scope.district_picture(request.centre, request.district)
    return render(request, "web/kvk/dashboard.html", _ctx(request, p=pic))


@kvk_only
@require_POST
def choose(request):
    cid = request.POST.get("centre")
    if cid and cid.isdigit() and any(c.pk == int(cid) for c in request.centres):
        request.session["kvk_centre"] = int(cid)
        request.session["kvk_district"] = ""
    d = request.POST.get("district")
    if d is not None:
        request.session["kvk_district"] = d if d in request.centre.districts else ""
    return redirect(request.POST.get("back") if (request.POST.get("back") or "").startswith("/kvk/") else "/kvk/")


# ---------- issues ----------
@kvk_only
def issues(request):
    status = request.GET.get("status", "waiting")
    qs = Issue.objects.filter(centre=request.centre).select_related("farmer__farmer_profile", "organisation")
    if request.district:
        qs = qs.filter(district__iexact=request.district)
    if status == "waiting":
        qs = qs.filter(status__in=["open", "acknowledged"])
    elif status in Issue.Status.values:
        qs = qs.filter(status=status)
    cat_ = request.GET.get("category", "")
    if cat_ in Issue.Category.values:
        qs = qs.filter(category=cat_)
    rows = list(qs.order_by("-urgent", "created_at" if status == "waiting" else "-created_at")[:200])
    now = timezone.now()
    for i in rows:
        i.age_h = int((now - i.created_at).total_seconds() // 3600)
    return render(request, "web/kvk/issues.html", _ctx(request, rows=rows, status=status, category=cat_, categories=Issue.Category.choices, statuses=Issue.Status.choices))


@kvk_only
def issue_detail(request, pk):
    i = get_object_or_404(Issue.objects.select_related("farmer__farmer_profile", "organisation", "raised_by"), pk=pk, centre=request.centre)
    fp = i.farmer.farmer_profile if i.farmer_id else None
    card = directory.farmer_card(fp) if fp and fp.share_with_extension else None
    return render(request, "web/kvk/issue.html", _ctx(request, i=i, replies=i.replies.select_related("by"), fp=fp, card=card, kinds=Reply.Kind.choices,
                                                     same=Issue.objects.filter(centre=request.centre, category=i.category, district__iexact=i.district).exclude(pk=i.pk).count()))


# ---------- input offers ----------
class OfferForm(LangForm):
    kind = forms.ChoiceField(label="What are you offering?", choices=list(InputOffer.Kind.choices))
    name = forms.CharField(label="Name and variety", max_length=160, widget=forms.TextInput(attrs={"placeholder": "Wheat seed HI-1544"}))
    crop = forms.ChoiceField(label="For which crop (optional)", choices=[("", "-")] + list(CROPS.items()), required=False)
    quantity = forms.DecimalField(label="Total available", min_value=Decimal("0.01"), decimal_places=2)
    unit = forms.CharField(label="Unit", max_length=20, initial="kg")
    per_person_limit = forms.DecimalField(label="Most one person can ask for (optional)", required=False, min_value=Decimal("0.01"), decimal_places=2)
    price = forms.DecimalField(label="Price per unit (₹, 0 for free)", min_value=Decimal("0"), decimal_places=2, initial=0)
    audience = forms.ChoiceField(label="Who can ask", choices=list(InputOffer.Audience.choices), initial="all")
    valid_until = date_field("Open until")
    pickup = forms.CharField(label="Where to collect", max_length=200, required=False)
    note = forms.CharField(label="Who qualifies, what to bring (optional)", max_length=400, required=False, widget=forms.Textarea(attrs={"rows": 2}))
    notify = forms.BooleanField(label="Send an SMS to farmers in the district (crop growers first, up to 200)", required=False, initial=True)


@kvk_only
def offers(request):
    from datetime import timedelta
    form = OfferForm(request.POST or None, lang=request.lang, initial={"valid_until": timezone.localdate() + timedelta(days=30)})
    if request.method == "POST" and form.is_valid():
        d = dict(form.cleaned_data)
        send = d.pop("notify")
        if d["valid_until"] < timezone.localdate():
            form.add_error("valid_until", "Choose a delivery date after today.")
        else:
            o = InputOffer.objects.create(centre=request.centre, created_by=request.user, districts=[request.district] if request.district else [], **d)
            n = ext.publish(o, send)
            ok(request, "Offer published. {n} farmers told by SMS.", n=n)
            return redirect("/kvk/offers/")
    rows = InputOffer.objects.filter(centre=request.centre).prefetch_related("requests")
    return render(request, "web/kvk/offers.html", _ctx(request, rows=rows, form=form))


@kvk_only
def offer_detail(request, pk):
    o = get_object_or_404(InputOffer, pk=pk, centre=request.centre)
    return render(request, "web/kvk/offer.html", _ctx(request, o=o, reqs=o.requests.select_related("user__farmer_profile", "organisation")))


@kvk_only
@require_POST
def offer_act(request, pk):
    o = get_object_or_404(InputOffer, pk=pk, centre=request.centre)
    if request.POST.get("action") == "toggle":
        o.active = not o.active
        o.save(update_fields=["active"])
    else:
        r = get_object_or_404(InputRequest, pk=request.POST.get("request"), offer=o)
        try:
            ext.decide(r, request.user, request.POST.get("action", ""), request.POST.get("note", ""))
        except ApiError as e:
            warn(request, error_text(request, e))
    ok(request, "Saved.")
    return redirect(f"/kvk/offers/{o.pk}/")


# ---------- farmers, FPOs and NGOs ----------
@kvk_only
def farmers(request):
    qs = scope.farmers(request.centre, request.district)
    crop = request.GET.get("crop", "")
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(village__icontains=q))
    rows = [fp for fp in qs.order_by("-level", "name")[:400] if not crop or crop in (fp.crops or [])]
    return render(request, "web/kvk/farmers.html", _ctx(request, rows=rows[:200], crop=crop, q=q, crops=sorted({c for fp in qs[:2000] for c in (fp.crops or []) if c in CROPS}),
                                                       sharing=sum(1 for fp in rows if fp.share_with_extension)))


@kvk_only
def farmer_detail(request, pk):
    fp = get_object_or_404(FarmerProfile.objects.select_related("user", "organisation"), user_id=pk)
    if not request.centre.covers(fp.state, fp.district):
        raise Http404
    if not fp.share_with_extension:
        return render(request, "web/kvk/farmer_private.html", _ctx(request, fp=fp))
    from farmerbook.models import CropCycle
    from farmerbook.views import cycle_summary
    from insurance.models import Application
    cycles = [cycle_summary(c) | {"obj": c} for c in CropCycle.objects.filter(owner=fp.user, deleted_at__isnull=True).select_related("plot").order_by("-created_at")[:20]]
    ys = {y["crop"]: y for y in scope.yields(request.centre.state, [fp.district])}
    for c in cycles:
        y = ys.get(c["crop"])
        area = c["obj"].plot.area_acres
        if y and area and Decimal(c["harvested_kg"]) > 0:
            mine = Decimal(c["harvested_kg"]) / area
            c["per_acre"], c["pct"] = mine.quantize(Decimal("1")), scope.percentile(mine, [v for v, _ in y["values"]])
    return render(request, "web/kvk/farmer.html", _ctx(request, fp=fp, card=directory.farmer_card(fp), cycles=cycles, issues=Issue.objects.filter(farmer=fp.user)[:10],
                                                       insurance=Application.objects.filter(farmer=fp.user)[:10]))


@kvk_only
def orgs(request):
    rows = [directory.fpo_card(o) | {"obj": o} for o in scope.orgs(request.centre, request.district).filter(verified=True)[:100]]
    return render(request, "web/kvk/orgs.html", _ctx(request, rows=rows))


@kvk_only
def org_detail(request, pk):
    o = get_object_or_404(Organisation, pk=pk, verified=True)
    if not request.centre.covers(o.state, o.district):
        raise Http404
    from deals.models import Deal
    from market.models import Listing
    members = FarmerProfile.objects.filter(organisation=o).select_related("user")
    return render(request, "web/kvk/org.html", _ctx(request, o=o, c=directory.fpo_card(o), members=members, listings=Listing.live().filter(organisation=o).count(),
                                                    deals=Deal.objects.filter(organisation=o).count(), issues=Issue.objects.filter(organisation=o).count()))


# ---------- map ----------
@kvk_only
def map_page(request):
    return render(request, "web/kvk/map.html", _ctx(request, state_file=geo.state_file(request.centre.state),
                                                   names=[geo.official_name(request.centre.state, d) for d in request.centre.districts]))


@kvk_only
def map_data(request):
    c = request.centre
    out = {"centre": {"name": c.name, "lat": c.lat, "lon": c.lon}, "districts": {}, "fpos": [], "issues": []}
    for d in c.districts:
        p = scope.district_picture(c, d)
        out["districts"][geo.official_name(c.state, d)] = {"name": d, "farmers": p["farmers"], "fpos": p["fpos"], "ngos": p["ngos"], "stock_q": float(p["stock_total"] / 100),
                                                           "issues": p["issues_open"], "listings": p["listings"]}
    for o in scope.orgs(c).filter(verified=True, lat__isnull=False):
        out["fpos"].append({"id": o.pk, "name": o.name, "lat": o.lat, "lon": o.lon, "kind": o.kind, "district": o.district, "url": f"/kvk/orgs/{o.pk}/"})
    for i in Issue.objects.filter(centre=c, lat__isnull=False, status__in=["open", "acknowledged", "advised"])[:300]:
        out["issues"].append({"id": i.pk, "lat": i.lat, "lon": i.lon, "label": i.get_category_display(), "urgent": i.urgent, "url": f"/kvk/issues/{i.pk}/"})
    return JsonResponse(out)
