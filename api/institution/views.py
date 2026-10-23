"""Institution Connect, the site for KVKs and research agencies: the picture of their districts, alerts and advisories, farmers
and FPOs/NGOs (and adding them), loans against stored crops, seeds and inputs, notices, the problem desk and crop groups."""
from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django import forms
from django.conf import settings
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

import catalog
from accounts.errors import ApiError
from advisory import services as advisory_services
from advisory.models import Advisory
from accounts.models import Role, User
from deals import directory
from extension import geo, scope
from extension import services as ext
from extension.models import Centre, InputOffer, InputRequest
from issues import services as issue_services
from issues.models import Issue, Reply
from profiles.models import FarmerProfile, Organisation
from rates.crops import CROPS

from web.forms import AddFarmerForm, LangForm, date_field
from web.helpers import error_text, ok, warn

from . import services as inst
from .models import Notice


def kvk_only(view):
    @wraps(view)
    def wrapper(request, *a, **kw):
        u = request.user
        if not u.is_authenticated:
            return redirect("/login/")
        if u.role != Role.AGRONOMIST and not u.is_staff:  # a farmer, FPO or buyer session has no business here
            from django.contrib.auth import logout
            logout(request)
            warn(request, "This site is for KVKs and research agencies. Farmers, FPOs and buyers use Seedha Bazar.")
            return redirect("/login/")
        centres = list(scope.centres_of(u)) if u.role == Role.AGRONOMIST else list(Centre.objects.all())
        if not centres:
            return render(request, "institution/no_centre.html")
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
    return render(request, "institution/dashboard.html", _ctx(request, p=pic))


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
    return redirect(request.POST.get("back") if (request.POST.get("back") or "").startswith("/") else "/")


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
    return render(request, "institution/issues.html", _ctx(request, rows=rows, status=status, category=cat_, categories=Issue.Category.choices, statuses=Issue.Status.choices))


@kvk_only
def issue_detail(request, pk):
    i = get_object_or_404(Issue.objects.select_related("farmer__farmer_profile", "organisation", "raised_by"), pk=pk, centre=request.centre)
    fp = i.farmer.farmer_profile if i.farmer_id else None
    card = directory.farmer_card(fp) if fp and fp.share_with_extension else None
    return render(request, "institution/issue.html", _ctx(request, i=i, replies=i.replies.select_related("by"), fp=fp, card=card, kinds=Reply.Kind.choices,
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
            return redirect("/offers/")
    rows = InputOffer.objects.filter(centre=request.centre).prefetch_related("requests")
    return render(request, "institution/offers.html", _ctx(request, rows=rows, form=form))


@kvk_only
def offer_detail(request, pk):
    o = get_object_or_404(InputOffer, pk=pk, centre=request.centre)
    return render(request, "institution/offer.html", _ctx(request, o=o, reqs=o.requests.select_related("user__farmer_profile", "organisation")))


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
    return redirect(f"/offers/{o.pk}/")


# ---------- farmers, FPOs and NGOs ----------
@kvk_only
def farmers(request):
    qs = scope.farmers(request.centre, request.district)
    crop = request.GET.get("crop", "")
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(village__icontains=q))
    rows = [fp for fp in qs.order_by("-level", "name")[:400] if not crop or crop in (fp.crops or [])]
    return render(request, "institution/farmers.html", _ctx(request, rows=rows[:200], crop=crop, q=q, crops=sorted({c for fp in qs[:2000] for c in (fp.crops or []) if c in CROPS}),
                                                       sharing=sum(1 for fp in rows if fp.share_with_extension)))


@kvk_only
def farmer_detail(request, pk):
    fp = get_object_or_404(FarmerProfile.objects.select_related("user", "organisation"), user_id=pk)
    if not request.centre.covers(fp.state, fp.district):
        raise Http404
    if not fp.share_with_extension:
        return render(request, "institution/farmer_private.html", _ctx(request, fp=fp))
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
    return render(request, "institution/farmer.html", _ctx(request, fp=fp, card=directory.farmer_card(fp), cycles=cycles, issues=Issue.objects.filter(farmer=fp.user)[:10],
                                                       insurance=Application.objects.filter(farmer=fp.user)[:10]))


@kvk_only
def orgs(request):
    rows = [directory.fpo_card(o) | {"obj": o} for o in scope.orgs(request.centre, request.district).filter(verified=True)[:100]]
    return render(request, "institution/orgs.html", _ctx(request, rows=rows))


@kvk_only
def org_detail(request, pk):
    o = get_object_or_404(Organisation, pk=pk, verified=True)
    if not request.centre.covers(o.state, o.district):
        raise Http404
    from deals.models import Deal
    from market.models import Listing
    members = FarmerProfile.objects.filter(organisation=o).select_related("user")
    return render(request, "institution/org.html", _ctx(request, o=o, c=directory.fpo_card(o), members=members, listings=Listing.live().filter(organisation=o).count(),
                                                    deals=Deal.objects.filter(organisation=o).count(), issues=Issue.objects.filter(organisation=o).count()))


# ---------- map ----------
@kvk_only
def map_page(request):
    return render(request, "institution/map.html", _ctx(request, state_file=geo.state_file(request.centre.state),
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
        out["fpos"].append({"id": o.pk, "name": o.name, "lat": o.lat, "lon": o.lon, "kind": o.kind, "district": o.district, "url": f"/orgs/{o.pk}/"})
    for i in Issue.objects.filter(centre=c, lat__isnull=False, status__in=["open", "acknowledged", "advised"])[:300]:
        out["issues"].append({"id": i.pk, "lat": i.lat, "lon": i.lon, "label": i.get_category_display(), "urgent": i.urgent, "url": f"/issues/{i.pk}/"})
    return JsonResponse(out)


def _district_choices(request, blank_label="All my districts"):
    return [("", blank_label)] + [(d, d) for d in request.centre.districts]


def _chosen_districts(request, value: str) -> list[str]:
    return [value] if value else ([request.district] if request.district else list(request.centre.districts))


# ---------- alerts, weather and advisories ----------
class AdvisoryForm(LangForm):
    district = forms.ChoiceField(label="For which district", choices=[], required=False)
    title = forms.CharField(label="Headline (optional)", max_length=160, required=False)
    text = forms.CharField(label="Advice for farmers", max_length=1500, widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Spray ... within 3 days; do not irrigate before the rain"}))
    kind = forms.ChoiceField(label="Topic", choices=list(Advisory.Kind.choices), initial="general")
    severity = forms.ChoiceField(label="How urgent", choices=list(Advisory.Severity.choices), initial="info")
    crops = forms.MultipleChoiceField(label="Crops (optional)", choices=list(CROPS.items()), required=False, widget=forms.CheckboxSelectMultiple(attrs={"class": "chips"}))
    valid_until = date_field("Valid until (optional)", required=False)
    notify = forms.BooleanField(label="Tell farmers and FPOs of the district now", required=False, initial=True)


def _forecast(state, district):
    from weather import services as wx

    try:
        from datetime import date
        place = wx.place_for(state, district, lookup=False)
        days = wx.forecast(place.lat, place.lon) if place else None
        return [{**d, "date": date.fromisoformat(str(d["date"])[:10])} for d in days or []]
    except Exception:
        return None


@kvk_only
def weather(request):
    from weather.models import Alert

    c = request.centre
    form = AdvisoryForm(request.POST or None, lang=request.lang)
    form.fields["district"].choices = _district_choices(request)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        rows, sent = advisory_services.publish(c, request.user, _chosen_districts(request, d["district"]), d["text"], title=d["title"], kind=d["kind"],
                                               severity=d["severity"], crops=d["crops"], valid_until=d["valid_until"], tell=d["notify"])
        ok(request, "Advice published for {n} districts. {m} people told.", n=len(rows), m=sent)
        return redirect("/weather/")
    districts = [request.district] if request.district else c.districts
    today = timezone.localdate()
    alerts = (Alert.objects.filter(scope._district_q("", c.state, districts), day__gte=today - timedelta(days=1)).values("day", "kind", "severity", "crop", "district")
              .annotate(n=Count("farmer", distinct=True)).order_by("day", "severity", "-n")[:60])
    forecasts = [{"district": d, "days": (_forecast(c.state, d) or [])[:5]} for d in districts[:4]]
    advisories, seen = [], set()
    for d in districts:
        for a in advisory_services.for_place(c.state, d, limit=15):
            if a.pk not in seen:
                seen.add(a.pk)
                advisories.append(a)
    advisories.sort(key=lambda a: -a.published_at.timestamp())
    from advisory.models import FeedRun
    return render(request, "institution/weather.html", _ctx(request, form=form, alerts=alerts, forecasts=forecasts, advisories=advisories[:30],
                                                            mine=Advisory.objects.filter(centre=c, source="kvk")[:10],
                                                            feed=FeedRun.objects.filter(feed="mkisan").first(), imd_on=settings.IMD_API_ENABLED,
                                                            national=Advisory.objects.filter(source="mkisan", district="").order_by("-published_at")[:8]))


@kvk_only
def advisory_detail(request, pk):
    a = get_object_or_404(Advisory, pk=pk)
    return render(request, "institution/advisory.html", _ctx(request, a=a))


# ---------- add farmers and FPOs/NGOs ----------
class KvkFarmerForm(AddFarmerForm):
    organisation = forms.ChoiceField(label="FPO or NGO (optional)", choices=[], required=False)

    field_order = ["phone", "name", "village", "block", "district", "land_acres", "crops", "other_crops", "organisation", "language", "contact_is_family", "family_contact_name"]


class KvkOrgForm(LangForm):
    name = forms.CharField(label="FPO / NGO name", max_length=160)
    kind = forms.ChoiceField(label="Type", choices=[("fpo", "FPO (farmer producer company)"), ("ngo", "NGO")])
    district = forms.ChoiceField(label="District", choices=[])
    block = forms.CharField(label="Block (tehsil)", max_length=80, required=False)
    registration_no = forms.CharField(label="Registration number (if you have it)", max_length=60, required=False)
    contact_name = forms.CharField(label="Contact person", max_length=120)
    agent_phone = forms.CharField(label="Agent's mobile number", max_length=20, widget=forms.TextInput(attrs={"inputmode": "tel"}))

    def clean_agent_phone(self):
        from accounts.phone import InvalidPhone, normalise_phone
        try:
            return normalise_phone(self.cleaned_data["agent_phone"])
        except InvalidPhone:
            raise forms.ValidationError("Enter a valid 10-digit Indian mobile number")


@kvk_only
def farmer_add(request):
    from web.fpo_views import farmer_data

    form = KvkFarmerForm(request.POST or None, lang=request.lang, initial={"district": request.district})
    form.fields["district"] = forms.ChoiceField(label=form.fields["district"].label, choices=[(d, d) for d in request.centre.districts])
    orgs_here = list(scope.orgs(request.centre, request.district).filter(verified=True).order_by("name"))
    form.fields["organisation"].choices = [("", "-")] + [(str(o.pk), o.name) for o in orgs_here]
    if request.method == "POST" and form.is_valid():
        d = dict(form.cleaned_data)
        org_id = d.pop("organisation")
        data = farmer_data(d)
        data["district"] = d["district"]
        data["organisation"] = next((o for o in orgs_here if str(o.pk) == org_id), None)
        try:
            inst.add_farmer(request.centre, request.user, data, request)
        except ApiError as e:
            form.add_error("phone" if e.code == "already_registered" else None, error_text(request, e))
        else:
            ok(request, "Added. A code was sent to the farmer's phone. The farmer confirms it to activate the account.")
            return redirect("/farmers/")
    return render(request, "institution/farmer_add.html", _ctx(request, form=form))


@kvk_only
def org_add(request):
    form = KvkOrgForm(request.POST or None, lang=request.lang, initial={"district": request.district})
    form.fields["district"].choices = [(d, d) for d in request.centre.districts]
    if request.method == "POST" and form.is_valid():
        try:
            org = inst.add_org(request.centre, request.user, form.cleaned_data, request)
        except ApiError as e:
            form.add_error("agent_phone" if e.code == "phone_in_use" else None, error_text(request, e))
        else:
            ok(request, "Organisation created. Its agent signs in with their own phone code. Join code: {code}", code=org.code)
            return redirect(f"/orgs/{org.pk}/")
    return render(request, "institution/org_add.html", _ctx(request, form=form))


# ---------- active loans against stored crops ----------
@kvk_only
def loans(request):
    return render(request, "institution/loans.html", _ctx(request, L=inst.loans(request.centre, request.district)))


# ---------- notices to farmers, FPOs and NGOs ----------
class NoticeForm(LangForm):
    audience = forms.ChoiceField(label="Send to", choices=list(Notice.Audience.choices), initial="all")
    district = forms.ChoiceField(label="District", choices=[], required=False)
    crop = forms.ChoiceField(label="Only farmers who grow (optional)", choices=[("", "-")] + list(CROPS.items()), required=False)
    text = forms.CharField(label="Message", max_length=300, widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Soil testing camp at KVK on Friday, 10 am. Bring a soil sample."}))


@kvk_only
def notices(request):
    form = NoticeForm(request.POST or None, lang=request.lang, initial={"district": request.district})
    form.fields["district"].choices = _district_choices(request)
    d = form.cleaned_data if request.method == "POST" and form.is_valid() else None
    if d is not None:
        try:
            n = inst.send_notice(request.centre, request.user, d["audience"], _chosen_districts(request, d["district"]), d["text"], d["crop"], request)
        except ApiError as e:
            form.add_error(None, error_text(request, e))
        else:
            ok(request, "Sent to {n} people.", n=n.sent)
            return redirect("/notices/")
    counts = {k: len(inst.recipients(request.centre, k, _chosen_districts(request, ""))) for k in ("farmers", "orgs")}
    return render(request, "institution/notices.html", _ctx(request, form=form, rows=Notice.objects.filter(centre=request.centre)[:30], counts=counts))


# ---------- group farming ----------
@kvk_only
def groups(request):
    from farming import services as farming
    from farming.models import CropGroup

    districts = [request.district] if request.district else request.centre.districts
    rows = [g for g in CropGroup.objects.filter(state__iexact=request.centre.state).exclude(status="closed").select_related("organisation", "centre")
            if any(geo.same_district(g.district, d) for d in districts)]
    cards = [farming.card(g) for g in rows[:100]]
    return render(request, "institution/groups.html", _ctx(request, rows=cards, acres=sum(c["acres"] for c in cards), farmers=sum(c["members"] for c in cards)))


@kvk_only
def group_detail(request, pk):
    from farming import services as farming
    from farming.models import PRACTICES, CropGroup

    g = get_object_or_404(CropGroup.objects.select_related("organisation", "centre"), pk=pk)
    if not request.centre.covers(g.state, g.district):
        raise Http404
    if request.method == "POST":
        g.centre = request.centre if request.POST.get("action") == "guide" else None
        g.save(update_fields=["centre"])
        ok(request, "Saved.")
        return redirect(f"/groups/{g.pk}/")
    members = [{"fp": m.farmer.farmer_profile, "acres": m.area_acres} for m in farming.active_members(g)]
    return render(request, "institution/group.html", _ctx(request, g=g, s=farming.stats(g), signal=farming.price_signal(g), members=members,
                                                         practices=[label for k, label in PRACTICES if k in (g.practices or [])]))
