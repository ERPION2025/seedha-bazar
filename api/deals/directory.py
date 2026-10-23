"""What buyers can see of producers: what they grow, what they have, what they make. Never a phone number or surname."""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q

import catalog
from accounts.models import UserStatus
from farmerbook.models import CropCycle, Processing
from market import stock
from profiles.models import FarmerProfile, Organisation, OrgStatus


def _first(name: str) -> str:
    return (name or "").split()[0] if name else ""


def farmer_card(fp: FarmerProfile, with_stock: bool = True) -> dict:
    u = fp.user
    cycles = list(CropCycle.objects.filter(owner=u, deleted_at__isnull=True).exclude(status="closed").select_related("plot"))
    grows = list(dict.fromkeys(list(fp.crops or []) + [c.crop for c in cycles]))
    makes = sorted(set(Processing.objects.filter(owner=u, deleted_at__isnull=True).values_list("product", flat=True)))
    lines = stock.lines(u) if with_stock else []
    have = defaultdict(Decimal)
    for ln in lines:
        have[ln["product"]] += ln["free_kg"]
    growing = [{"crop": c.crop, "area": c.plot.area_acres, "harvest": c.expected_harvest_date} for c in cycles if c.status == "active"]
    return {"kind": "farmer", "id": u.pk, "name": _first(fp.name), "village": fp.village, "district": fp.district, "state": fp.state, "grows": grows,
            "makes": makes, "stock": dict(have), "growing": growing, "verified": fp.level >= 2, "level": fp.level, "land": fp.land_acres,
            "org": fp.organisation.name if fp.organisation_id and fp.org_status == OrgStatus.CONFIRMED else "", "groups": _farmer_groups(u)}


def fpo_card(org: Organisation, with_stock: bool = True) -> dict:
    members = FarmerProfile.objects.filter(organisation=org, org_status__in=[OrgStatus.CONFIRMED, OrgStatus.PENDING]).select_related("user")
    users = [m.user for m in members]
    grows: dict = defaultdict(int)
    for m in members:
        for c in m.crops or []:
            grows[c] += 1
    have = defaultdict(Decimal)
    if with_stock and users:
        for ln in stock.lines(users):
            have[ln["product"]] += ln["free_kg"]
    makes = sorted(set(Processing.objects.filter(owner__in=users, deleted_at__isnull=True).values_list("product", flat=True)))
    return {"kind": "fpo", "id": org.pk, "name": org.name, "village": org.block, "district": org.district, "state": org.state, "members": len(users),
            "grows": [c for c, _ in sorted(grows.items(), key=lambda kv: -kv[1])], "makes": makes, "stock": dict(have), "verified": org.verified,
            "org_kind": org.get_kind_display(), "groups": _org_groups(org)}


def _farmer_groups(user) -> list:
    from farming.services import farmer_summary
    return farmer_summary(user)


def _org_groups(org) -> dict:
    from farming.services import org_summary
    return org_summary(org)


def search(crop: str = "", district: str = "", kind: str = "", state: str = "", limit: int = 40) -> list[dict]:
    out = []
    if kind in ("", "fpo"):
        orgs = Organisation.objects.filter(verified=True)
        if district:
            orgs = orgs.filter(district__icontains=district)
        if state:
            orgs = orgs.filter(state__iexact=state)
        for org in orgs[:limit]:
            card = fpo_card(org, with_stock=True)
            if not crop or crop in card["grows"] or crop in card["stock"] or crop in card["makes"]:
                out.append(card)
    if kind in ("", "farmer"):
        fps = FarmerProfile.objects.filter(discoverable=True, level__gte=1, user__status=UserStatus.ACTIVE).select_related("user", "organisation")
        if district:
            fps = fps.filter(district__icontains=district)
        if state:
            fps = fps.filter(state__iexact=state)
        for fp in fps[: limit * 3]:
            card = farmer_card(fp)
            if not crop or crop in card["grows"] or crop in card["stock"] or crop in card["makes"]:
                out.append(card)
    out.sort(key=lambda c: (-sum(c["stock"].values()), not c["verified"], c["name"]))
    return out[:limit]


def can_make(card: dict) -> list[str]:
    """Processed products a producer could make from what they grow: the menu of conversion requests a buyer can send."""
    from catalog import services as cat

    out = []
    for crop in card["grows"]:
        for conv in cat.conversions_from(crop):
            if conv[1] not in out:
                out.append(conv[1])
    return out
