"""Centres: provisioning staff, publishing input offers and handling requests."""
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts import audit
from accounts.errors import ApiError
from accounts.models import Role, User, UserStatus
from notify import service as notify

from .models import Centre, CentreMember, InputOffer, InputRequest
from .scope import farmers as farmers_in


@transaction.atomic
def provision_staff(phone: str, centre: Centre, role: str = "expert", speciality: str = "", actor=None, request=None) -> User:
    user, created = User.objects.get_or_create(phone=phone, defaults={"role": Role.AGRONOMIST, "status": UserStatus.ACTIVE})
    if not created and user.role != Role.AGRONOMIST:
        raise ApiError("phone_in_use", "This number already belongs to a farmer or buyer account. Use a different number for the agent.", 409)
    CentreMember.objects.update_or_create(user=user, centre=centre, defaults={"role": role, "speciality": speciality})
    audit.log("centre_staff_added", actor=actor, target=user, request=request, centre=centre.pk)
    return user


def place_of(user) -> tuple[str, str, object]:
    """(state, district, organisation) of a farmer or an FPO agent."""
    if user.role == Role.FARMER:
        fp = user.farmer_profile
        return fp.state, fp.district, None
    if user.role == Role.AGENT:
        from profiles.models import OrgMembership
        m = OrgMembership.objects.filter(user=user).select_related("organisation").first()
        if m:
            return m.organisation.state, m.organisation.district, m.organisation
    return "", "", None


def offers_for(user):
    """Live offers whose geofence holds this person's district."""
    state, district, org = place_of(user)
    if not district:
        return []
    out = []
    for o in InputOffer.objects.filter(active=True, valid_until__gte=timezone.localdate()).select_related("centre"):
        from .geo import same_district

        ds = o.districts or o.centre.districts
        if o.centre.state.lower() != (state or "").lower() or not any(same_district(d, district) for d in ds):
            continue
        if o.audience == "farmers" and user.role != Role.FARMER or o.audience == "fpos" and user.role != Role.AGENT:
            continue
        if o.left > 0:
            out.append(o)
    return out


def publish(offer: InputOffer, notify_farmers: bool = True) -> int:
    """Tell farmers in the districts about a new offer. Farmers whose crops match go first; at most 200 messages per offer."""
    if not notify_farmers:
        return 0
    from web.i18n import tr

    ds = offer.districts or offer.centre.districts
    sent = 0
    for d in ds:
        qs = farmers_in(offer.centre, d)
        if offer.crop:
            rows = sorted(qs, key=lambda fp: offer.crop not in (fp.crops or []))
        else:
            rows = list(qs)
        for fp in rows:
            if sent >= 200:
                return sent
            if offer.audience == "fpos":
                break
            u = fp.user
            notify.send("sms", u.phone, "input_offer", u.language, user=u, related=f"offer:{offer.pk}", centre=offer.centre.name, item=offer.name, place=d,
                        link=f"{settings.SITE_URL}/inputs/")
            sent += 1
    return sent


@transaction.atomic
def request(offer: InputOffer, user, quantity, note: str = "", request=None) -> InputRequest:
    if offer not in offers_for(user):
        raise ApiError("offer_unavailable", "This offer is not open for you.", 400)
    if quantity is None or quantity <= 0:
        raise ApiError("bad_quantity", "Enter a quantity more than zero.", 400)
    if offer.per_person_limit and quantity > offer.per_person_limit:
        raise ApiError("over_limit", "That is more than one person can ask for.", 400)
    if quantity > offer.left:
        raise ApiError("over_limit", "That is more than one person can ask for.", 400)
    if InputRequest.objects.filter(offer=offer, user=user, status__in=["requested", "approved"]).exists():
        raise ApiError("already_requested", "You already have an open request for this with this seller.", 409)
    _, _, org = place_of(user)
    r = InputRequest.objects.create(offer=offer, user=user, organisation=org, quantity=quantity, note=(note or "")[:300])
    audit.log("input_requested", actor=user, target=r, request=request)
    return r


def decide(req: InputRequest, staff, status: str, note: str = "") -> InputRequest:
    if not req.offer.centre.members.filter(user=staff).exists():
        raise ApiError("not_allowed", "You cannot do this.", 403)
    if status not in ("approved", "declined", "collected"):
        raise ApiError("not_now", "This step is not open yet.", 409)
    req.status, req.centre_note, req.decided_at = status, (note or "")[:300], timezone.now()
    req.save()
    from web.i18n import tr
    u = req.user
    what = {"approved": "Your request was approved. Collect it.", "declined": "Your request was not approved.", "collected": "Marked as collected."}[status]
    notify.send("sms", u.phone, "input_update", u.language, user=u, related=f"input:{req.pk}", what=tr(u.language, what), product=req.offer.name, link=f"{settings.SITE_URL}/inputs/")
    return req
