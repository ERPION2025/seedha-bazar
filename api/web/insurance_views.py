"""Crop insurance: compare options for a crop, opt in, keep the papers ready, track the application, report a loss."""
from decimal import Decimal, InvalidOperation

from django import forms
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

import catalog
from accounts.errors import ApiError
from accounts.models import Role, User
from farmerbook.models import CropCycle
from insurance import rules, services
from insurance.models import Application, Plan
from profiles.models import OrgMembership
from rates.crops import CROPS

from .forms import LangForm
from .helpers import error_text, ok, warn
from .market_views import base_for

LOSS_CAUSES = [("drought", "Drought or dry spell"), ("flood", "Flood or waterlogging"), ("hail", "Hail or storm"), ("pest", "Pests or disease"),
               ("fire", "Fire or lightning"), ("unseasonal_rain", "Unseasonal rain"), ("other", "Other")]


class CompareForm(LangForm):
    crop = forms.ChoiceField(label="Crop", choices=list(CROPS.items()))
    season = forms.ChoiceField(label="Season", choices=[("kharif", "Kharif"), ("rabi", "Rabi")], initial="kharif")
    area = forms.DecimalField(label="Area sown", min_value=Decimal("0.01"), max_value=Decimal("10000"), decimal_places=3, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    area_unit = forms.ChoiceField(label="Unit", choices=[("acre", "Acre"), ("hectare", "Hectare")], initial="acre")
    expected_quintal = forms.DecimalField(label="Harvest you expect (quintal, optional)", required=False, min_value=Decimal("0.01"), decimal_places=2, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    value = forms.DecimalField(label="Value of the crop to insure (₹, optional)", required=False, min_value=Decimal("100"), max_value=Decimal("100000000"), decimal_places=0, widget=forms.NumberInput(attrs={"inputmode": "numeric"}))
    state = forms.CharField(label="State", max_length=60)
    district = forms.CharField(label="District", max_length=80)


class ApplyForm(LangForm):
    channel = forms.ChoiceField(label="Where will you submit it?", choices=list(Application.Channel.choices), initial="bank", required=False)
    loanee = forms.BooleanField(label="I have a crop loan or Kisan Credit Card", required=False)


def _hectares(d) -> Decimal:
    return (d["area"] * (rules.HECTARE_PER_ACRE if d["area_unit"] == "acre" else 1)).quantize(Decimal("0.001"))


def _who(request):
    """(farmer, agent org) the page acts for. An FPO agent may act for a member farmer with ?for=<id>."""
    u = request.user
    if not u.is_authenticated:
        return None, None
    if u.role == Role.FARMER:
        return u, None
    if u.role == Role.AGENT and request.GET.get("for", request.POST.get("for", "")).isdigit():
        m = OrgMembership.objects.filter(user=u, organisation__verified=True).select_related("organisation").first()
        if m:
            farmer = User.objects.filter(pk=int(request.GET.get("for") or request.POST.get("for")), role=Role.FARMER, farmer_profile__organisation=m.organisation).first()
            if farmer:
                return farmer, m.organisation
    return None, None


def _can_see(user, app: Application) -> bool:
    if not user.is_authenticated:
        return False
    if app.farmer_id == user.pk or user.is_staff:
        return True
    return user.role == Role.AGENT and app.organisation_id and OrgMembership.objects.filter(user=user, organisation_id=app.organisation_id).exists()


def hub(request):
    u = request.user
    rows, cycles = [], []
    if u.is_authenticated and u.role == Role.FARMER:
        rows = Application.objects.filter(farmer=u)[:30]
        insured = set(Application.objects.filter(farmer=u).exclude(status="closed").values_list("crop_cycle_id", flat=True))
        cycles = [c for c in CropCycle.objects.filter(owner=u, deleted_at__isnull=True).exclude(status="closed") if c.pk not in insured and c.crop in CROPS]
    return render(request, "web/insurance/hub.html", {"rows": rows, "cycles": cycles, "base_tpl": base_for(u) if u.is_authenticated else "web/base.html"})


def compare(request):
    u = request.user
    farmer, org = _who(request)
    init = {"season": "kharif", "area_unit": "acre"}
    cycle = None
    if farmer is not None:
        fp = farmer.farmer_profile
        init.update(state=fp.state, district=fp.district)
        if request.GET.get("cycle"):
            import uuid
            try:
                cycle = CropCycle.objects.filter(owner=farmer, client_id=uuid.UUID(request.GET["cycle"]), deleted_at__isnull=True).select_related("plot").first()
            except ValueError:
                cycle = None
        if cycle is not None:
            init.update(crop=cycle.crop, season=cycle.season if cycle.season in ("kharif", "rabi") else "kharif", area=cycle.plot.area_acres)
    else:
        from . import location
        loc = location.current(request)
        init.update(state=loc.get("state", ""), district=loc.get("district", ""))
    if request.GET.get("crop") in CROPS:
        init["crop"] = request.GET["crop"]
    bound = "crop" in request.GET and "area" in request.GET
    form = CompareForm(request.GET if bound else None, initial=init, lang=request.lang)
    options, estimate, area_ha = [], None, None
    if bound and form.is_valid():
        d = form.cleaned_data
        area_ha = _hectares(d)
        estimate = services.crop_value(d["crop"], d["state"], d["district"], area_ha, d.get("expected_quintal"))
        value = d.get("value") or (estimate["value"] if estimate else None)
        for p in services.plans_for(d["crop"], d["state"], d["district"], d["season"]):
            q = services.quote(p, area_ha, value)
            q["days_left"] = services.days_left(p)
            options.append(q)
        options.sort(key=lambda q: (q["plan"].scheme != "pmfby", not q["plan"].notified))
    ctx = {"form": form, "options": options, "estimate": estimate, "area_ha": area_ha, "cycle": cycle, "farmer": farmer, "org": org, "apply_form": ApplyForm(lang=request.lang),
           "query": request.GET.urlencode(), "base_tpl": base_for(u) if u.is_authenticated else "web/base.html"}
    return render(request, "web/insurance/compare.html", ctx)


@require_POST
def apply(request):
    farmer, org = _who(request)
    if farmer is None:
        return redirect("/login/?as=farmer&next=/insurance/")
    from django.http import QueryDict

    q = QueryDict(request.POST.get("query", ""))
    form = CompareForm(q, lang=request.lang)
    af = ApplyForm(request.POST, lang=request.lang)
    plan = Plan.objects.filter(pk=request.POST.get("plan"), active=True).first()
    if not (form.is_valid() and af.is_valid() and plan):
        warn(request, "Something went wrong. Please try again.")
        return redirect(f"/insurance/compare/?{q.urlencode()}")
    d = form.cleaned_data
    cycle = None
    if q.get("cycle"):
        import uuid
        try:
            cycle = CropCycle.objects.filter(owner=farmer, client_id=uuid.UUID(q["cycle"])).first()
        except ValueError:
            cycle = None
    area_ha = _hectares(d)
    est = services.crop_value(d["crop"], d["state"], d["district"], area_ha, d.get("expected_quintal"))
    try:
        app = services.create_application(farmer, {
            "plan": plan, "crop": d["crop"], "area_ha": area_ha, "sum_insured": d.get("value") or (est["value"] if est else None), "state": d["state"], "district": d["district"],
            "village": farmer.farmer_profile.village, "year": timezone.localdate().year, "crop_cycle": cycle, "channel": "fpo" if org else (af.cleaned_data["channel"] or "bank"),
            "loanee": af.cleaned_data["loanee"]}, helped_by=request.user if org else None, organisation=org)
    except ApiError as e:
        warn(request, error_text(request, e))
        return redirect(f"/insurance/compare/?{q.urlencode()}")
    ok(request, "Saved. Now get the papers ready and submit it before the last date.")
    return redirect(f"/insurance/{app.pk}/")


def detail(request, pk):
    app = get_object_or_404(Application.objects.select_related("plan", "farmer__farmer_profile", "organisation"), pk=pk)
    if not _can_see(request.user, app):
        raise Http404
    ctx = {"a": app, "docs": [(k, label, app.checklist.get(k)) for k, label in services.DOCS], "causes": LOSS_CAUSES, "days_left": services.days_left(app.plan) if app.plan else None,
           "hours_left": (72 - services.hours_since(app.loss_date)) if app.loss_date and services.hours_since(app.loss_date) <= 72 else None, "base_tpl": base_for(request.user), "today": timezone.localdate()}
    return render(request, "web/insurance/detail.html", ctx)


@require_POST
def act(request, pk, action):
    app = get_object_or_404(Application, pk=pk)
    if not _can_see(request.user, app):
        raise Http404
    try:
        if action == "papers":
            services.update_checklist(app, request.POST.getlist("ready"))
        elif action == "submitted":
            if not request.POST.get("application_no", "").strip():
                raise ApiError("number_needed", "Write the application or receipt number you were given.", 400)
            services.mark_submitted(app, request.POST["application_no"])
        elif action == "enrolled":
            if not request.POST.get("policy_no", "").strip():
                raise ApiError("number_needed", "Write the application or receipt number you were given.", 400)
            services.mark_enrolled(app, request.POST["policy_no"], request.POST.get("insurer", ""))
        elif action == "loss":
            from datetime import date
            try:
                when = date.fromisoformat(request.POST.get("loss_date", ""))
            except ValueError:
                when = timezone.localdate()
            services.report_loss(app, min(when, timezone.localdate()), request.POST.get("cause", "other"), request.POST.get("note", ""))
            # The district's KVK hears about every reported loss, so experts can advise and confirm damage early.
            from issues import services as issue_services
            try:
                issue_services.raise_issue(app.farmer if request.user.role == Role.FARMER else request.user, {
                    "category": "crop_loss", "crop": app.crop, "urgent": True, "source": "insurance_loss", "related": f"insurance:{app.pk}",
                    "farmer": app.farmer if request.user.role == Role.AGENT else None,
                    "description": f"Crop loss reported for insurance: {dict(LOSS_CAUSES).get(app.loss_cause, app.loss_cause)} on {app.loss_date:%d %b %Y}. {app.loss_note}".strip()}, request)
            except ApiError:
                pass
        elif action == "close":
            app.status = Application.Status.CLOSED
            app.save()
        else:
            raise Http404
        ok(request, "Saved.")
    except ApiError as e:
        warn(request, error_text(request, e))
    return redirect(f"/insurance/{app.pk}/")


def printable(request, pk):
    app = get_object_or_404(Application.objects.select_related("plan", "farmer__farmer_profile"), pk=pk)
    if not _can_see(request.user, app):
        raise Http404
    return render(request, "web/insurance/print.html", {"a": app, "fp": app.farmer.farmer_profile, "docs": services.DOCS})


def norms(request):
    plans = Plan.objects.filter(active=True, state="").order_by("scheme", "season")
    states = Plan.objects.filter(active=True).exclude(state="").values_list("state", flat=True).distinct()
    return render(request, "web/insurance/norms.html", {"plans": plans, "states": sorted(set(states)), "risks": rules.RISKS, "docs": services.DOCS,
                                                         "base_tpl": base_for(request.user) if request.user.is_authenticated else "web/base.html"})


def fpo_overview(request):
    u = request.user
    if not u.is_authenticated or u.role != Role.AGENT:
        return redirect("/login/?as=fpo")
    m = OrgMembership.objects.filter(user=u).select_related("organisation").first()
    if m is None:
        return redirect("/fpo/register/")
    org = m.organisation
    apps = Application.objects.filter(farmer__farmer_profile__organisation=org).select_related("farmer__farmer_profile")[:200]
    covered = {a.farmer_id for a in apps if a.status != "closed"}
    members = User.objects.filter(farmer_profile__organisation=org, farmer_profile__org_status__in=["confirmed", "pending"]).select_related("farmer_profile")
    waiting = [x for x in members if x.pk not in covered]
    return render(request, "web/insurance/fpo.html", {"org": org, "apps": apps, "waiting": waiting, "base_tpl": "web/fpo/base.html"})
