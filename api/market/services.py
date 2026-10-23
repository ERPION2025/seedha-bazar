"""Marketplace rules. Views call these; nothing here knows about HTML."""
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from accounts import audit
from accounts.errors import ApiError
from accounts.models import Role
from farmerbook.serializers import stock_kg
from farmerbook.units import to_kg
from notify import service as notify
from rates import services as rate_services
from rates.crops import CROPS

from .models import LISTING_DAYS, Enquiry, EnquiryMessage, Listing

MAX_MESSAGES_PER_ENQUIRY_PER_HOUR = 30
NOTIFY_QUIET = timedelta(minutes=30)


def crop_key(name: str) -> str:
    n = (name or "").strip().lower()
    return n if n in CROPS else n[:60]


def per_quintal(price: Decimal, quantity: Decimal, quantity_kg: Decimal) -> Decimal:
    """Price per unit -> price per quintal, whatever the unit (a 50 kg bag at 1,200 is 2,400 a quintal)."""
    return (price * quantity * 100 / quantity_kg).quantize(Decimal("0.01"))


@transaction.atomic
def save_listing(seller, data: dict, org=None, instance: Listing | None = None, request=None) -> Listing:
    """Create or update a listing. `data` has crop, quantity, unit, bag_weight_kg, price, grade, state, district, village, variety, description, available_from."""
    try:
        kg = to_kg(data["quantity"], data["unit"], data.get("bag_weight_kg"))
    except ValueError:
        raise ApiError("bag_weight_required", "Tell us how many kg one bag weighs", 400)
    cycle = data.get("source_cycle")
    if cycle is not None:
        free = stock_kg(cycle)
        already = sum(Listing.objects.filter(source_cycle=cycle, status__in=["active", "paused"]).exclude(pk=getattr(instance, "pk", None)).values_list("quantity_kg", flat=True))
        if kg > free - already:
            raise ApiError("not_enough_stock", "That is more than the stock in your book that is not already listed.", 400, available_kg=str(max(Decimal(0), free - already)))
    li = instance or Listing(seller=seller, organisation=org, source_cycle=cycle)
    for f in ("grade", "state", "district", "village", "variety", "description", "unit"):
        if f in data:
            setattr(li, f, data[f] if data[f] is not None else "")
    li.bag_weight_kg = data.get("bag_weight_kg") if data["unit"] == "bag" else None
    if data.get("available_from"):
        li.available_from = data["available_from"]
    li.crop = crop_key(data["crop"])
    li.quantity, li.quantity_kg, li.price = data["quantity"], kg, data["price"]
    li.price_per_quintal = per_quintal(li.price, li.quantity, kg)
    if instance is None:
        li.expires_at = timezone.now() + timedelta(days=LISTING_DAYS)
    li.save()
    audit.log("listing_saved", actor=seller, target=li, request=request, created=instance is None)
    return li


def mandi_reference(listing: Listing, memo: dict | None = None) -> dict | None:
    """How the asking price compares with today's mandi price for the same place. None when we have no rate for it."""
    if listing.crop not in CROPS:
        return None
    key = (listing.crop, listing.state, listing.district)
    if memo is not None and key in memo:
        ref = memo[key]
    else:
        ref = rate_services.typical_price(*key)
        if memo is not None:
            memo[key] = ref
    if ref is None:
        return None
    diff = ((listing.price_per_quintal - ref["typical"]) / ref["typical"] * 100).quantize(Decimal("0.1"))
    return {**ref, "diff_pct": diff}


PHONE = re.compile(r"(?<!\w)\+?[0-9०-९](?:[\s\-.]?[0-9०-९]){7,}")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
URL = re.compile(r"(?:https?://|www\.)\S+", re.I)


def mask_contacts(text: str) -> tuple[str, bool]:
    """Hide phone numbers, emails and links. Used until the seller accepts, so deals are not taken off the platform early."""
    out = text
    for rx in (URL, EMAIL, PHONE):
        out = rx.sub("•••", out)
    return out, out != text


def _link(enquiry: Enquiry) -> str:
    return f"{settings.SITE_URL}/enquiry/{enquiry.pk}/"


def crop_name(lang: str, crop: str) -> str:
    from web.i18n import tr  # lazy: the website's wording lives in web/

    return tr(lang, CROPS.get(crop, crop.title()))


def qty_text(lang: str, listing: Listing, quantity) -> str:
    from web.i18n import tr

    return f"{Decimal(quantity).normalize():f} {tr(lang, listing.unit)}"


@transaction.atomic
def start_enquiry(buyer, listing: Listing, quantity: Decimal, offered_price, message: str, request=None) -> Enquiry:
    if buyer.role != Role.BUYER:
        raise ApiError("buyers_only", "Only buyers can send enquiries.", 403)
    level = getattr(getattr(buyer, "buyer_profile", None), "level", 0)
    if level < 1:
        raise ApiError("profile_incomplete", "Fill in your business details first.", 403)
    if not listing.is_live:
        raise ApiError("listing_closed", "This listing is no longer available.", 409)
    if listing.seller_id == buyer.pk:
        raise ApiError("own_listing", "This is your own listing.", 400)
    if quantity <= 0 or quantity > listing.quantity:
        raise ApiError("bad_quantity", "Ask for a quantity up to what is listed.", 400)
    enquiry, created = Enquiry.objects.get_or_create(listing=listing, buyer=buyer, defaults={"quantity": quantity, "offered_price": offered_price, "message": ""})
    if not created:
        return enquiry
    if message.strip():
        post_message(enquiry, buyer, message, request=request, notify_other=False)
    audit.log("enquiry_started", actor=buyer, target=enquiry, request=request, listing=listing.pk)
    seller = listing.seller
    notify.send("sms", seller.phone, "enquiry_received", seller.language, user=seller, related=f"enquiry:{enquiry.pk}",
                crop=crop_name(seller.language, listing.crop), qty=qty_text(seller.language, listing, quantity), link=_link(enquiry))
    return enquiry


def post_message(enquiry: Enquiry, sender, text: str, request=None, notify_other: bool = True) -> EnquiryMessage:
    text = (text or "").strip()[:500]
    if not text:
        raise ApiError("empty_message", "Write a message first.", 400)
    if sender.pk not in (enquiry.buyer_id, enquiry.listing.seller_id):
        raise ApiError("not_found", "Not found.", 404)
    if enquiry.status in (Enquiry.Status.DECLINED, Enquiry.Status.CLOSED):
        raise ApiError("enquiry_closed", "This conversation is closed.", 409)
    if EnquiryMessage.objects.filter(enquiry=enquiry, sender=sender, created_at__gte=timezone.now() - timedelta(hours=1)).count() >= MAX_MESSAGES_PER_ENQUIRY_PER_HOUR:
        raise ApiError("too_many_messages", "Too many messages. Try again later.", 429)
    masked = False
    if not enquiry.unlocked:
        text, masked = mask_contacts(text)
    msg = EnquiryMessage.objects.create(enquiry=enquiry, sender=sender, text=text, masked=masked)
    if masked:
        audit.log("contact_masked", actor=sender, target=enquiry, request=request)
    other = enquiry.buyer if sender.pk == enquiry.listing.seller_id else enquiry.listing.seller
    now = timezone.now()
    if notify_other and (enquiry.last_notified_at is None or now - enquiry.last_notified_at > NOTIFY_QUIET):
        notify.send("sms", other.phone, "enquiry_message", other.language, user=other, related=f"enquiry:{enquiry.pk}", crop=crop_name(other.language, enquiry.listing.crop), link=_link(enquiry))
        enquiry.last_notified_at = now
        enquiry.save(update_fields=["last_notified_at"])
    return msg


@transaction.atomic
def decide(enquiry: Enquiry, seller, accept: bool, request=None) -> Enquiry:
    if seller.pk != enquiry.listing.seller_id:
        raise ApiError("not_found", "Not found.", 404)
    if enquiry.status != Enquiry.Status.NEW:
        raise ApiError("already_decided", "This enquiry was already decided.", 409)
    now = timezone.now()
    enquiry.status = Enquiry.Status.ACCEPTED if accept else Enquiry.Status.DECLINED
    enquiry.decided_at = now
    if accept:
        enquiry.unlocked_at = now  # the pilot unlocks free of charge; unlock_fee_paise is where billing will plug in
    enquiry.save()
    audit.log("enquiry_accepted" if accept else "enquiry_declined", actor=seller, target=enquiry, request=request)
    buyer = enquiry.buyer
    notify.send("sms", buyer.phone, "enquiry_accepted" if accept else "enquiry_declined", buyer.language, user=buyer, related=f"enquiry:{enquiry.pk}",
                crop=crop_name(buyer.language, enquiry.listing.crop), link=_link(enquiry) if accept else f"{settings.SITE_URL}/market/")
    return enquiry


def close(enquiry: Enquiry, user, sold: bool = False, request=None) -> Enquiry:
    if user.pk not in (enquiry.buyer_id, enquiry.listing.seller_id):
        raise ApiError("not_found", "Not found.", 404)
    enquiry.status = Enquiry.Status.CLOSED
    enquiry.save(update_fields=["status"])
    audit.log("enquiry_closed", actor=user, target=enquiry, request=request, sold=sold)
    return enquiry


def contact_of(user, organisation=None) -> dict:
    """What the other side sees after unlock."""
    if user.role == Role.BUYER:
        bp = user.buyer_profile
        return {"name": bp.contact_name or bp.business_name, "business": bp.business_name, "phone": user.phone, "city": bp.city}
    if organisation is not None:
        return {"name": organisation.contact_name or organisation.name, "business": organisation.name, "phone": user.phone, "city": organisation.district}
    fp = getattr(user, "farmer_profile", None)
    return {"name": fp.name if fp else "", "business": "", "phone": user.phone, "city": fp.village if fp else ""}


def unread_for(user) -> int:
    """Enquiries with something new for this person (a buyer's enquiry the seller has not opened, or any reply since they last looked)."""
    seller_side = Enquiry.objects.filter(listing__seller=user).filter(Q(seller_seen_at__isnull=True) | Q(messages__created_at__gt=F("seller_seen_at"), messages__sender=F("buyer")))
    buyer_side = Enquiry.objects.filter(buyer=user).filter(Q(buyer_seen_at__isnull=True, status__in=["accepted", "declined"]) | Q(messages__created_at__gt=F("buyer_seen_at"), messages__sender=F("listing__seller")))
    return seller_side.distinct().count() + buyer_side.distinct().count()

