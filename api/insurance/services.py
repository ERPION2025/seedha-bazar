"""Which insurance fits a crop, what it costs, what it could pay, and the steps to opt in."""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from accounts.errors import ApiError
from rates import services as rate_services

from . import connectors, rules
from .models import Application, Plan

D = Decimal
DOCS = [("aadhaar", "Aadhaar card"), ("land", "Land record (khasra / 7-12) or tenancy proof"), ("bank", "Bank passbook (account linked to Aadhaar)"),
        ("sowing", "Sowing certificate or declaration (crop and area sown)"), ("photo", "Passport photo")]


def plans_for(crop: str, state: str, district: str, season: str) -> list[Plan]:
    """The options for this crop and place: the state's notified plans first, then the national rule as a fallback."""
    season = rules.season_for(crop, season)
    qs = Plan.objects.filter(active=True, season=season)
    notified = [p for p in qs.filter(state__iexact=state, crop=crop) if not p.districts or district.lower() in [d.lower() for d in p.districts]]
    if notified:
        return notified
    return list(qs.filter(state="", group=rules.group_of(crop)))


def crop_value(crop: str, state: str, district: str, area_ha: Decimal, expected_quintal: Decimal | None) -> dict | None:
    """What the crop is worth if all goes well: expected harvest at today's typical price. Used to suggest a sum insured when the state's figure is not loaded."""
    ref = rate_services.typical_price(crop, state, district)
    if not ref or not expected_quintal:
        return None
    return {"value": (expected_quintal * ref["typical"]).quantize(D("1")), "rate": ref["typical"], "as_of": ref["as_of"]}


def quote(plan: Plan, area_ha: Decimal, sum_insured: Decimal | None = None) -> dict:
    """Cost and cover for one plan. `sum_insured` is used when the plan has no per-hectare figure."""
    if plan.sum_insured_per_ha:
        si = (plan.sum_insured_per_ha * area_ha).quantize(D("1"))
        basis = "notified"
    elif sum_insured:
        si = D(sum_insured).quantize(D("1"))
        basis = "estimate"
    else:
        return {"plan": plan, "sum_insured": None, "premium": None, "basis": "unknown"}
    premium = (si * plan.farmer_share_pct / 100).quantize(D("1"), rounding=ROUND_HALF_UP)
    return {"plan": plan, "sum_insured": si, "premium": premium, "basis": basis, "times": (si / premium).quantize(D("1")) if premium else None,
            "half_loss": (si / 2).quantize(D("1")), "per_acre": (premium * rules.HECTARE_PER_ACRE / area_ha).quantize(D("1")) if area_ha else None}


def days_left(plan: Plan):
    if not plan.cutoff_date:
        return None
    return (plan.cutoff_date - timezone.localdate()).days


def create_application(farmer, data: dict, helped_by=None, organisation=None) -> Application:
    plan = data["plan"]
    if plan.cutoff_date and plan.cutoff_date < timezone.localdate():
        raise ApiError("insurance_closed", "The last day to enrol for this season has passed.", 400)
    q = quote(plan, data["area_ha"], data.get("sum_insured"))
    if q["sum_insured"] is None:
        raise ApiError("sum_insured_needed", "Tell us the value of the crop to insure.", 400)
    open_ = Application.objects.filter(farmer=farmer, crop=data["crop"], season=plan.season, year=data["year"]).exclude(status__in=["closed"])
    if data.get("crop_cycle") is not None:
        open_ = open_.filter(crop_cycle=data["crop_cycle"])
    if open_.exists():
        raise ApiError("already_applied", "This crop is already being insured for this season.", 409)
    app = Application.objects.create(
        farmer=farmer, helped_by=helped_by, organisation=organisation, crop_cycle=data.get("crop_cycle"), plan=plan, crop=data["crop"], season=plan.season,
        year=data["year"], state=data["state"], district=data["district"], village=data.get("village", ""), area_ha=data["area_ha"], sum_insured=q["sum_insured"],
        farmer_premium=q["premium"], channel=data.get("channel", "bank"), loanee=data.get("loanee", False), insurer=plan.insurer, connector=connectors.get().name)
    return app


def update_checklist(app: Application, ready: list[str]) -> Application:
    app.checklist = {k: k in ready for k, _ in DOCS}
    if app.status == Application.Status.DRAFT and all(app.checklist.get(k) for k in ("aadhaar", "land", "bank", "sowing")):
        app.status = Application.Status.READY
    app.save()
    return app


def mark_submitted(app: Application, application_no: str) -> Application:
    if app.status not in (Application.Status.DRAFT, Application.Status.READY, Application.Status.SUBMITTED):
        raise ApiError("bad_status", "This application has already moved on.", 409)
    app.application_no = application_no.strip()[:60]
    app.status = Application.Status.SUBMITTED
    app.save()
    return app


def mark_enrolled(app: Application, policy_no: str, insurer: str = "") -> Application:
    app.policy_no = policy_no.strip()[:60]
    if insurer:
        app.insurer = insurer[:160]
    app.status = Application.Status.ENROLLED
    app.save()
    return app


def report_loss(app: Application, when, cause: str, note: str) -> Application:
    if app.status not in (Application.Status.SUBMITTED, Application.Status.ENROLLED, Application.Status.LOSS):
        raise ApiError("not_insured", "Report a loss once the crop is insured.", 409)
    app.loss_date, app.loss_cause, app.loss_note = when, cause[:40], note[:500]
    app.status = Application.Status.LOSS
    app.save()
    return app


def hours_since(d) -> int:
    from datetime import datetime, time

    start = timezone.make_aware(datetime.combine(d, time(0, 0)))
    return int((timezone.now() - start).total_seconds() // 3600)
