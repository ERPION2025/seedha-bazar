"""Start, find and join crop groups; and the numbers that make a group worth trusting."""
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts import audit
from accounts.errors import ApiError
from accounts.models import Role

from .models import PRACTICES, CropGroup, CropGroupMember

D = Decimal
PRACTICE_KEYS = {k for k, _ in PRACTICES}
MAX_ACRES = D("500")


def season_now(today=None) -> tuple[str, int]:
    """The season a farmer would plan for now: kharif sown June-July, rabi October-November, zaid March-April."""
    today = today or timezone.localdate()
    m = today.month
    if m in (6, 7, 8, 9):
        return "kharif", today.year
    if m in (10, 11, 12):
        return "rabi", today.year
    if m in (1, 2):
        return "rabi", today.year - 1
    return "zaid", today.year


def active_members(group):
    return group.members.filter(status=CropGroupMember.Status.ACTIVE).select_related("farmer__farmer_profile")


def stats(group: CropGroup) -> dict:
    """Members, acres, expected harvest, and a trust score that says how it was worked out."""
    from extension.scope import yields
    from farmerbook.models import CropCycle

    members = list(active_members(group))
    n = len(members)
    acres = sum((m.area_acres for m in members), D(0))
    verified = sum(1 for m in members if getattr(getattr(m.farmer, "farmer_profile", None), "level", 0) >= 2)
    keep_book = sum(1 for m in members if CropCycle.objects.filter(owner=m.farmer, crop=group.crop, deleted_at__isnull=True).exists())
    y = next((r for r in yields(group.state, [group.district], group.crop) if r["enough"]), None)
    expected_q = (acres * y["median"] / 100).quantize(D("1")) if y and acres else None
    parts = [
        ("Members whose profile is checked", round(30 * verified / n) if n else 0, 30),
        ("Members who keep the Farmer Book for this crop", round(30 * keep_book / n) if n else 0, 30),
        ("Run with a verified FPO or NGO", 15 if group.organisation_id and group.organisation.verified else 0, 15),
        ("Guided by a KVK", 15 if group.centre_id else 0, 15),
        ("Practices agreed", min(len(group.practices or []), 5) * 2, 10),
    ]
    return {"members": n, "acres": acres, "verified": verified, "keep_book": keep_book, "expected_q": expected_q,
            "trust": sum(p[1] for p in parts), "parts": [{"label": l, "got": g, "of": o} for l, g, o in parts]}


def price_signal(group: CropGroup) -> dict | None:
    """What pooled lots of this crop actually fetched against the mandi, from this group's FPO (or its district). Real sales only."""
    from market.models import Pool
    from rates import services as rate_services

    pools = Pool.objects.filter(product=group.crop, status__in=["sold", "settled"], sold_price__isnull=False)
    pools = pools.filter(organisation=group.organisation) if group.organisation_id else pools.filter(organisation__district__iexact=group.district)
    pools = [p for p in pools[:20] if p.unit in ("quintal", "kg")]
    ref = rate_services.typical_price(group.crop, group.state, group.district) if group.crop in rate_services.CROPS else None
    if not pools or not ref:
        return None
    per_q = [p.sold_price if p.unit == "quintal" else p.sold_price * 100 for p in pools]
    avg = sum(per_q) / len(per_q)
    return {"lots": len(pools), "avg": avg.quantize(D("1")), "mandi": ref["typical"], "pct": int(round(avg * 100 / ref["typical"]))}


def card(group: CropGroup) -> dict:
    s = stats(group)
    return {"id": group.pk, "name": group.name, "crop": group.crop, "season": group.get_season_display(), "year": group.year, "district": group.district,
            "village": group.village, "members": s["members"], "acres": s["acres"], "trust": s["trust"], "status": group.status,
            "org": group.organisation.name if group.organisation_id else "", "kvk": group.centre.name if group.centre_id else "", "expected_q": s["expected_q"]}


def groups_of(user):
    return CropGroup.objects.filter(members__farmer=user, members__status=CropGroupMember.Status.ACTIVE).exclude(status=CropGroup.Status.CLOSED).distinct()


def near(user, limit: int = 12) -> list:
    """Open groups in the farmer's district, for the crops they grow first."""
    from extension.geo import same_district

    fp = getattr(user, "farmer_profile", None)
    if not fp or not fp.district:
        return []
    mine = set(groups_of(user).values_list("pk", flat=True))
    rows = [g for g in CropGroup.objects.filter(state__iexact=fp.state or "", status__in=["forming", "active"]).select_related("organisation", "centre")
            if same_district(g.district, fp.district) and g.pk not in mine]
    crops = set(fp.crops or [])
    rows.sort(key=lambda g: (g.crop not in crops, -g.created_at.timestamp()))
    return rows[:limit]


def _clean_practices(values) -> list[str]:
    return [v for v in (values or []) if v in PRACTICE_KEYS]


@transaction.atomic
def create(by, *, crop: str, season: str, year: int, district: str, state: str, village: str = "", seed_variety: str = "", practices=None, note: str = "",
           organisation=None, centre=None, name: str = "", lead_acres=None, invite: bool = True, request=None) -> CropGroup:
    from rates.crops import CROPS

    if crop not in CROPS:
        raise ApiError("bad_crop", "Choose a crop from the list.", 400)
    if not district:
        raise ApiError("bad_place", "Add your district to your profile first.", 400)
    g = CropGroup.objects.create(name=(name or f"{CROPS[crop]} · {village or district}")[:120], crop=crop, season=season, year=year, state=state, district=district,
                                 village=village[:120], seed_variety=seed_variety[:80], practices=_clean_practices(practices), note=note[:300],
                                 organisation=organisation, centre=centre, created_by=by, lead=by if by.role == Role.FARMER else None)
    audit.log("crop_group_created", actor=by, target=g, request=request)
    if by.role == Role.FARMER:
        join(g, by, lead_acres or getattr(by.farmer_profile, "land_acres", None) or D("1"), notify_others=False)
    if invite:
        invite_growers(g)
    return g


def invite_growers(g: CropGroup, cap: int = 100) -> int:
    """Tell farmers in the district who grow this crop that a group is forming."""
    from extension.models import Centre
    from extension.scope import farmers as farmers_in
    from notify import service as notify
    from rates.crops import CROPS

    centre = g.centre or Centre(state=g.state, districts=[g.district])
    in_group = set(g.members.values_list("farmer_id", flat=True))
    sent = 0
    for fp in farmers_in(centre, g.district):
        if sent >= cap:
            break
        if fp.user_id in in_group or g.crop not in (fp.crops or []):
            continue
        u = fp.user
        from web.i18n import tr
        notify.tell(u, "group_invite", related=f"group:{g.pk}", title="Seedha Bazar", url=f"/farmer/groups/{g.pk}/", crop=tr(u.language, CROPS[g.crop]),
                    place=g.village or g.district, link=f"{settings.SITE_URL}/farmer/groups/{g.pk}/")
        sent += 1
    return sent


@transaction.atomic
def join(g: CropGroup, user, area_acres, notify_others: bool = True) -> CropGroupMember:
    from extension.geo import same_district
    from farmerbook.models import CropCycle

    if user.role != Role.FARMER:
        raise ApiError("not_allowed", "You cannot do this.", 403)
    if g.status == CropGroup.Status.CLOSED:
        raise ApiError("not_now", "This step is not open yet.", 409)
    fp = user.farmer_profile
    if not (fp.district and same_district(fp.district, g.district)):
        raise ApiError("other_district", "This group is for farmers of another district.", 400)
    try:
        area = D(str(area_acres))
    except Exception:
        area = D(0)
    if not (D("0.1") <= area <= MAX_ACRES):
        raise ApiError("bad_area", "Enter the acres you will grow this crop on.", 400)
    cycle = CropCycle.objects.filter(owner=user, crop=g.crop, deleted_at__isnull=True).exclude(status="closed").order_by("-created_at").first()
    m, _ = CropGroupMember.objects.update_or_create(group=g, farmer=user, defaults={"area_acres": area, "status": CropGroupMember.Status.ACTIVE, "crop_cycle": cycle})
    audit.log("crop_group_joined", actor=user, target=g)
    if g.status == CropGroup.Status.FORMING and active_members(g).count() >= 5:
        g.status = CropGroup.Status.ACTIVE
        g.save(update_fields=["status"])
    return m


def leave(g: CropGroup, user) -> None:
    CropGroupMember.objects.filter(group=g, farmer=user).update(status=CropGroupMember.Status.LEFT)
    audit.log("crop_group_left", actor=user, target=g)


def farmer_summary(user) -> list[dict]:
    """For profile cards and the buyer's producer page: the groups this farmer farms in."""
    from rates.crops import CROPS

    out = []
    for g in groups_of(user).select_related("organisation", "centre"):
        agg = active_members(g).aggregate(a=Sum("area_acres"))
        out.append({"id": g.pk, "crop": g.crop, "crop_name": CROPS.get(g.crop, g.crop), "members": active_members(g).count(), "acres": agg["a"] or D(0),
                    "kvk": g.centre.name if g.centre_id else ""})
    return out


def org_summary(org) -> dict:
    groups = list(CropGroup.objects.filter(organisation=org).exclude(status=CropGroup.Status.CLOSED))
    members = CropGroupMember.objects.filter(group__in=groups, status=CropGroupMember.Status.ACTIVE)
    return {"groups": len(groups), "farmers": members.values("farmer").distinct().count(), "acres": members.aggregate(a=Sum("area_acres"))["a"] or D(0),
            "crops": sorted({g.crop for g in groups})}


def score_part(user) -> tuple[int, str]:
    """For the performance score (10 points): 5 for farming in an active group, up to 5 more from the group's trust score."""
    best = 0
    groups = list(groups_of(user))
    for g in groups:
        best = max(best, stats(g)["trust"])
    if not groups:
        return 0, "—"
    return 5 + round(best / 20), f"{len(groups)} · {best}/100"
