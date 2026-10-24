"""What Institution Connect does: add farmers and FPOs/NGOs in its districts, send notices, and see loans against stored crops."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from accounts import audit, otp
from accounts.errors import ApiError
from accounts.models import Role, User, UserStatus
from extension import scope
from extension.geo import same_district
from profiles.models import OrgMembership, Organisation, OrgStatus

from .models import Notice

MAX_NEW_FARMERS_PER_DAY = 100
NOTICE_CAP = 1000


def _in_centre(centre, district: str) -> str:
    """The centre's own spelling of the district, or an error if it is outside the centre's geofence."""
    d = next((x for x in centre.districts if same_district(x, district)), None)
    if not d:
        raise ApiError("outside_area", "This district is outside your centre's area.", 400)
    return d


@transaction.atomic
def add_farmer(centre, staff, data: dict, request=None) -> User:
    """A KVK registers a farmer it works with. The farmer confirms with a code on their own phone, as with an FPO."""
    district = _in_centre(centre, data["district"])
    if User.objects.filter(created_by=staff, date_joined__gte=timezone.now() - timedelta(hours=24)).count() >= MAX_NEW_FARMERS_PER_DAY:
        raise ApiError("agent_daily_limit", "Daily limit for adding farmers reached", 429)
    if User.objects.filter(phone=data["phone"]).exists():
        raise ApiError("already_registered", "This number already has an account.", 409)
    user = User.objects.create_user(phone=data["phone"], role=Role.FARMER, status=UserStatus.PENDING, language=data.get("language", "hi"), created_by=staff)
    fp = user.farmer_profile
    for f in ("name", "village", "block", "land_acres", "crops", "contact_is_family", "family_contact_name"):
        if f in data and data[f] not in (None, ""):
            setattr(fp, f, data[f])
    fp.state, fp.district = centre.state, district
    org = data.get("organisation")
    if org is not None:
        fp.organisation, fp.org_status = org, OrgStatus.PENDING
    fp.assisted_by, fp.assisted_at = staff, timezone.now()
    fp.save()
    audit.log("farmer_added_by_centre", actor=staff, target=user, request=request, centre=centre.pk)
    otp.request_otp(user.phone, "sms", audit.client_ip(request) if request else "", user.language)
    return user


@transaction.atomic
def add_org(centre, staff, data: dict, request=None) -> Organisation:
    """A KVK adds an FPO or NGO it knows. The KVK vouches for it, so it is live at once; the agent signs in with their own phone code."""
    from profiles import services as profile_services

    district = _in_centre(centre, data["district"])
    phone = data["agent_phone"]
    existing = User.objects.filter(phone=phone).first()
    if existing and existing.role != Role.AGENT:
        raise ApiError("phone_in_use", "This number already belongs to a farmer or buyer account. Use a different number for the agent.", 409)
    org = Organisation.objects.create(name=data["name"], kind=data["kind"], code=profile_services.make_org_code(data["name"]), state=centre.state, district=district,
                                      block=data.get("block", ""), registration_no=data.get("registration_no", ""), contact_name=data.get("contact_name", ""), verified=True)
    profile_services.provision_agent(phone, org, staff, request)
    audit.log("org_added_by_centre", actor=staff, target=org, request=request, centre=centre.pk)
    return org


def recipients(centre, audience: str, districts: list[str], crop: str = "") -> list[User]:
    people, seen = [], set()
    for d in districts:
        if audience in ("all", "farmers"):
            rows = scope.farmers(centre, d).filter(user__status=UserStatus.ACTIVE)
            for fp in rows:
                if crop and crop not in (fp.crops or []):
                    continue
                if fp.user_id not in seen:
                    seen.add(fp.user_id)
                    people.append(fp.user)
        if audience in ("all", "orgs"):
            for m in OrgMembership.objects.filter(organisation__in=scope.orgs(centre, d).filter(verified=True)).select_related("user"):
                if m.user_id not in seen:
                    seen.add(m.user_id)
                    people.append(m.user)
    return people


def send_notice(centre, staff, audience: str, districts: list[str], text: str, crop: str = "", request=None) -> Notice:
    from notify import service as notify

    text = " ".join((text or "").split())[:300]
    if len(text) < 5:
        raise ApiError("text_needed", "Write the message.", 400)
    districts = [_in_centre(centre, d) for d in districts] or list(centre.districts)
    people = recipients(centre, audience, districts, crop)[:NOTICE_CAP]
    n = Notice.objects.create(centre=centre, sent_by=staff, audience=audience, districts=districts, crop=crop, text=text)
    for u in people:
        notify.tell(u, "kvk_notice", related=f"notice:{n.pk}", title=centre.name, url="/notifications/", centre=centre.name, advice=text)
    n.sent = len(people)
    n.save(update_fields=["sent"])
    audit.log("notice_sent", actor=staff, target=n, request=request, sent=n.sent)
    return n


def loans(centre, district: str = "") -> dict:
    """Crops stored in WDRA warehouses and loans against them, for farmers in the centre's districts.

    Totals cover everyone; a farmer's name is shown only if they share their book with the centre."""
    from storage.models import Pledge, Warehouse

    fps = scope.farmers(centre, district)
    qs = Pledge.objects.filter(farmer__farmer_profile__in=fps, status__in=["stored", "loan"]).select_related("farmer__farmer_profile", "warehouse")
    today = timezone.localdate()
    rows = list(qs.order_by("due_date")[:300])
    for p in rows:
        p.share = p.farmer.farmer_profile.share_with_extension
        p.overdue = bool(p.status == "loan" and p.due_date and p.due_date < today)
        p.due_soon = bool(p.status == "loan" and p.due_date and today <= p.due_date <= today + timedelta(days=30))
    loan_rows = [p for p in rows if p.status == "loan"]
    by_bank: dict = {}
    for p in loan_rows:
        b = by_bank.setdefault(p.bank or "—", {"bank": p.bank or "—", "n": 0, "amount": Decimal(0)})
        b["n"] += 1
        b["amount"] += p.loan_amount or 0
    ds = [district] if district else centre.districts
    wq = Q()
    for d in ds:
        wq |= Q(district__iexact=d) | Q(district__istartswith=d.split("(")[0].strip())
    whs = Warehouse.objects.filter(wq, state__iexact=centre.state).exclude(wdra_status__in=["Not listed", "Cancelled", "Surrendered"])
    active = whs.filter(wdra_status__iexact="Active")
    return {"rows": rows, "loans": len(loan_rows), "amount": sum((p.loan_amount or 0 for p in loan_rows), Decimal(0)),
            "stored_kg": sum((p.quantity_kg for p in rows), Decimal(0)), "overdue": sum(p.overdue for p in rows), "due_soon": sum(p.due_soon for p in rows),
            "banks": sorted(by_bank.values(), key=lambda b: -b["amount"]), "warehouses": active.count(), "warehouse_cap": active.aggregate(c=Sum("capacity_mt"))["c"] or 0,
            "warehouse_rows": list(active.order_by("-capacity_mt")[:25]), "warehouses_other": whs.exclude(wdra_status__iexact="Active").count()}
