"""What a seller really has to sell: the Farmer Book's stock, less what is already on offer.

A listing must come out of a stock line, so the marketplace can never promise produce the book does not show.
A line is one product in one crop cycle: the crop itself, or something made from it (dried, flour, oil...).
"""
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.db.models import Q
from django.utils import timezone

from farmerbook.models import CropCycle
from farmerbook.serializers import processed_stock, product_stock_kg, stock_kg
from farmerbook.units import KG_PER

from .models import Listing

THOUSANDTH = Decimal("0.001")


def book_kg(cycle, product: str = "") -> Decimal:
    """Kg in the book for the crop itself (product blank or the cycle's own crop) or for a processed product."""
    return product_stock_kg(cycle, product) if product and product != cycle.crop else stock_kg(cycle)


def listed_kg(cycle, product: str = "", exclude_listing=None) -> Decimal:
    """Kg of this stock already offered: live listings and paused ones (an expired offer frees its stock)."""
    product = product or cycle.crop
    qs = Listing.objects.filter(source_cycle=cycle, crop=product).filter(
        Q(status=Listing.Status.PAUSED) | Q(status=Listing.Status.ACTIVE, expires_at__gt=timezone.now()))
    if exclude_listing is not None:
        qs = qs.exclude(pk=exclude_listing.pk)
    return sum((q for q in qs.values_list("quantity_kg", flat=True)), Decimal(0))


def free_kg(cycle, product: str = "", exclude_listing=None) -> Decimal:
    """Book stock less what is listed, promised to an FPO lot, or pledged in a warehouse."""
    from .pools import reserved_kg

    product = product or cycle.crop
    return max(Decimal(0), book_kg(cycle, product) - listed_kg(cycle, product, exclude_listing) - reserved_kg(cycle, product) - pledged_kg(cycle, product))


def pledged_kg(cycle, product: str) -> Decimal:
    try:
        from storage.services import pledged_kg as pk
    except ImportError:  # the storage app is optional
        return Decimal(0)
    return pk(cycle, product)


def in_unit(kg: Decimal, unit: str, bag_weight_kg=None) -> Decimal:
    """Kg -> the unit the seller picked, rounded DOWN so the figure never exceeds the stock."""
    per = Decimal(bag_weight_kg) if unit == "bag" and bag_weight_kg else KG_PER.get(unit)
    if not per:
        return Decimal(0)
    return (kg / per).quantize(THOUSANDTH, rounding=ROUND_DOWN)


def lines(owners, crop: str = "") -> list[dict]:
    """Stock lines with something left to list, biggest first. `owners` is one user or several (an FPO's farmers).

    `crop` narrows to one product (the crop itself or a processed product).
    """
    owners = owners if isinstance(owners, (list, tuple, set)) else [owners]
    out = []
    cycles = CropCycle.objects.filter(owner__in=owners, deleted_at__isnull=True).select_related("plot", "owner__farmer_profile")
    for c in cycles:
        fp = getattr(c.owner, "farmer_profile", None)
        base = {"cycle": c, "owner_name": fp.name if fp else "", "owner_village": fp.village if fp else "",
                "season": c.get_season_display() if c.season else "", "plot": c.plot.name}
        candidates = [(c.crop, stock_kg(c))] + list(processed_stock(c).items())
        for product, book in candidates:
            if book <= 0 or (crop and crop != product):
                continue
            listed = listed_kg(c, product)
            free = free_kg(c, product)
            out.append({**base, "crop": c.crop, "product": product, "processed": product != c.crop, "in_book_kg": book, "listed_kg": listed,
                        "free_kg": free, "free_quintal": in_unit(free, "quintal")})
    out.sort(key=lambda x: -x["free_kg"])
    return out


def shelf_end(cycle, product: str = ""):
    """Earliest date the book says this stock stops being sellable, or None."""
    end = None
    if product and product != cycle.crop:
        for m in cycle.processings.filter(deleted_at__isnull=True, product=product, shelf_life_days__isnull=False):
            d = m.date + timedelta(days=m.shelf_life_days)
            end = d if end is None or d < end else end
        return end
    for h in cycle.harvests.filter(deleted_at__isnull=True, shelf_life_days__isnull=False):
        d = h.date + timedelta(days=h.shelf_life_days)
        end = d if end is None or d < end else end
    return end
