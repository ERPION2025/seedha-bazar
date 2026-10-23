"""Group selling rules. A pool is one lot built from members' Farmer Book stock; shares stay reserved until it sells."""
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

import catalog
from accounts import audit
from accounts.errors import ApiError
from farmerbook.models import Sale
from farmerbook.units import KG_PER
from notify import service as notify

from . import stock
from .models import Listing, Pool, PoolShare

D = Decimal
ACTIVE = ("open", "listed")


def per_unit_kg(unit: str) -> D:
    return KG_PER.get(unit, D(100))


def confirmed_kg(pool: Pool) -> D:
    return pool.shares.filter(status="confirmed").aggregate(t=Sum("quantity_kg"))["t"] or D(0)


def reserved_kg(cycle, product: str) -> D:
    """Kg of this stock promised to open or listed pools (proposed or confirmed), so it cannot be listed twice."""
    return PoolShare.objects.filter(crop_cycle=cycle, pool__product=product, pool__status__in=ACTIVE, status__in=["proposed", "confirmed"]).aggregate(
        t=Sum("quantity_kg"))["t"] or D(0)


def _member(org, farmer) -> bool:
    fp = getattr(farmer, "farmer_profile", None)
    return bool(fp and fp.organisation_id == org.pk and fp.org_status in ("confirmed", "pending"))


def create(agent, org, data: dict) -> Pool:
    if not org.verified:
        raise ApiError("org_not_verified", "Your organisation is still being verified. You can add farmers once it is approved.", 403)
    if data["product"] not in catalog.PRODUCTS:
        raise ApiError("unknown_product", "Choose a product from the list.", 400)
    if not data.get("price") or data["price"] <= 0:
        raise ApiError("bad_price", "Enter a price more than zero.", 400)
    return Pool.objects.create(organisation=org, created_by=agent, product=data["product"], grade=data.get("grade") or "ungraded", unit=data.get("unit") or "quintal",
                               price=data["price"], target_kg=data.get("target_kg"), fee_pct=data.get("fee_pct") or 0, description=(data.get("description") or "")[:300],
                               collect_by=data.get("collect_by"))


@transaction.atomic
def add_share(pool: Pool, cycle, quantity_kg: D, by, confirm: bool = False) -> PoolShare:
    """A member offers (or the FPO proposes) part of a stock line. The FPO's proposal waits for the farmer unless the farmer is FPO-managed."""
    if pool.status not in ACTIVE:
        raise ApiError("pool_closed", "This lot is no longer taking shares.", 409)
    farmer = cycle.owner
    if not _member(pool.organisation, farmer):
        raise ApiError("not_member", "Only members of this FPO can join its lots.", 403)
    if quantity_kg is None or quantity_kg <= 0:
        raise ApiError("bad_quantity", "Enter a quantity more than zero.", 400)
    if PoolShare.objects.filter(pool=pool, crop_cycle=cycle).exclude(status="withdrawn").exists():
        raise ApiError("already_in_pool", "This stock is already in the lot.", 409)
    free = stock.free_kg(cycle, pool.product)
    if quantity_kg > free:
        raise ApiError("not_enough_stock", "That is more than the stock in your book that is not already listed.", 400, available_kg=str(free))
    fp = farmer.farmer_profile
    managed = fp.org_status == "pending" and fp.assisted_by_id is not None  # entered by the FPO and not yet on their own phone
    auto = by.pk == farmer.pk or confirm or managed
    share, _ = PoolShare.objects.update_or_create(pool=pool, crop_cycle=cycle, defaults={
        "farmer": farmer, "quantity_kg": quantity_kg, "status": "confirmed" if auto else "proposed", "proposed_by": by,
        "confirmed_at": timezone.now() if auto else None})
    if not auto:
        from web.i18n import tr
        notify.send("sms", farmer.phone, "pool_invite", farmer.language, user=farmer, related=f"pool:{pool.pk}", org=pool.organisation.name,
                    product=tr(farmer.language, catalog.name(pool.product)), qty=f"{(quantity_kg / per_unit_kg(pool.unit)).quantize(D('0.01'))} {tr(farmer.language, pool.unit)}",
                    link=f"{settings.SITE_URL}/farmer/pools/")
    sync_listing(pool)
    return share


def answer(share: PoolShare, farmer, yes: bool) -> PoolShare:
    if share.farmer_id != farmer.pk or share.status != "proposed":
        raise ApiError("not_now", "This step is not open yet.", 409)
    share.status = "confirmed" if yes else "withdrawn"
    share.confirmed_at = timezone.now() if yes else None
    share.save()
    sync_listing(share.pool)
    return share


def withdraw(share: PoolShare, user) -> PoolShare:
    if user.pk not in (share.farmer_id,) and not share.pool.organisation.memberships.filter(user=user).exists():
        raise ApiError("not_allowed", "You cannot do this.", 403)
    if share.pool.status not in ACTIVE:
        raise ApiError("pool_closed", "This lot is no longer taking shares.", 409)
    share.status = "withdrawn"
    share.save()
    sync_listing(share.pool)
    return share


def sync_listing(pool: Pool):
    """Keep the pool's single marketplace listing in step with the confirmed shares."""
    li = pool.listing
    total = confirmed_kg(pool)
    if li is None:
        return
    if total <= 0:
        li.status = Listing.Status.PAUSED
    li.quantity_kg = total
    li.quantity = (total / per_unit_kg(pool.unit)).quantize(D("0.001"), rounding=ROUND_DOWN)
    li.price, li.unit = pool.price, pool.unit
    li.price_per_quintal = (pool.price * 100 / per_unit_kg(pool.unit)).quantize(D("0.01"))
    li.save()


@transaction.atomic
def publish(pool: Pool, agent) -> Listing:
    total = confirmed_kg(pool)
    if total <= 0:
        raise ApiError("pool_empty", "No confirmed shares yet.", 409)
    org = pool.organisation
    n = pool.shares.filter(status="confirmed").count()
    li = pool.listing or Listing(seller=agent, organisation=org)
    li.crop, li.form = pool.product, catalog.kind(pool.product)
    li.grade, li.state, li.district, li.village = pool.grade, org.state, org.district, org.block
    li.description = (pool.description or f"Pooled from {n} member farmers of {org.name}.")[:300]
    li.status = Listing.Status.ACTIVE
    li.quantity_kg = total
    li.quantity = (total / per_unit_kg(pool.unit)).quantize(D("0.001"), rounding=ROUND_DOWN)
    li.price, li.unit = pool.price, pool.unit
    li.price_per_quintal = (pool.price * 100 / per_unit_kg(pool.unit)).quantize(D("0.01"))
    li.save()
    pool.listing, pool.status = li, Pool.Status.LISTED
    pool.save()
    audit.log("pool_listed", actor=agent, target=pool, kg=str(total), farmers=n)
    return li


@transaction.atomic
def settle(pool: Pool, agent, sold_kg: D, price: D, buyer_note: str = "") -> list[PoolShare]:
    """The lot is sold: each confirmed share gets its part of the sold quantity, the price less the FPO fee, and a sale in its Farmer Book."""
    if pool.status not in ACTIVE:
        raise ApiError("pool_closed", "This lot is no longer taking shares.", 409)
    shares = list(pool.shares.filter(status="confirmed").select_related("crop_cycle", "farmer"))
    total = sum((s.quantity_kg for s in shares), D(0))
    if not shares or total <= 0:
        raise ApiError("pool_empty", "No confirmed shares yet.", 409)
    if sold_kg is None or sold_kg <= 0 or sold_kg > total:
        raise ApiError("bad_quantity", "Enter a quantity more than zero.", 400)
    if price is None or price <= 0:
        raise ApiError("bad_price", "Enter a price more than zero.", 400)
    per = per_unit_kg(pool.unit)
    net_rate = (price * (1 - pool.fee_pct / 100)).quantize(D("0.01"))
    today = timezone.localdate()
    from web.i18n import tr
    for s in shares:
        kg = (sold_kg * s.quantity_kg / total).quantize(D("0.001"), rounding=ROUND_DOWN)
        qty = (kg / per).quantize(D("0.001"), rounding=ROUND_DOWN)
        s.sold_kg, s.payout = kg, (qty * net_rate).quantize(D("0.01"))
        if kg > 0:
            s.sale = Sale.objects.create(owner=s.farmer, crop_cycle=s.crop_cycle, product="" if pool.product == s.crop_cycle.crop else pool.product, date=today,
                                         quantity=qty, unit=pool.unit, quantity_kg=kg, rate=net_rate, amount=s.payout, channel=Sale.Channel.FPO,
                                         buyer_note=f"{pool.organisation.name} lot #{pool.pk}" + (f" · {buyer_note}" if buyer_note else ""))
        s.save()
        f = s.farmer
        notify.send("sms", f.phone, "pool_paid", f.language, user=f, related=f"pool:{pool.pk}", org=pool.organisation.name,
                    product=tr(f.language, catalog.name(pool.product)), amount=f"Rs {s.payout:,.0f}", link=f"{settings.SITE_URL}/farmer/pools/")
    pool.sold_kg, pool.sold_price, pool.buyer_note, pool.status = sold_kg, price, buyer_note[:160], Pool.Status.SOLD
    pool.save()
    if pool.listing:
        pool.listing.status = Listing.Status.SOLD
        pool.listing.save()
    audit.log("pool_settled", actor=agent, target=pool, kg=str(sold_kg), price=str(price))
    return shares


def mark_paid(share: PoolShare, agent) -> PoolShare:
    if not share.pool.organisation.memberships.filter(user=agent).exists() or share.payout is None:
        raise ApiError("not_now", "This step is not open yet.", 409)
    share.paid_at = timezone.now()
    share.save(update_fields=["paid_at"])
    pool = share.pool
    if not pool.shares.filter(status="confirmed", payout__isnull=False, paid_at__isnull=True).exists():
        pool.status, pool.settled_at = Pool.Status.SETTLED, timezone.now()
        pool.save()
    return share
