import secrets
from datetime import timedelta

from django.db import transaction
from django.utils.text import slugify
from django.utils import timezone
from rest_framework import status

from accounts import audit, otp
from accounts.errors import ApiError
from accounts.models import Role, User, UserStatus

from .models import FarmerProfile, LinkStatus, OrgLinkRequest, Organisation, OrgMembership, OrgStatus

MAX_NEW_FARMERS_PER_AGENT_PER_DAY = 100


def agent_orgs(user):
    """Organisations an agent may act for. An FPO that staff have not verified yet cannot add or approve members."""
    return Organisation.objects.filter(memberships__user=user, verified=True)


def on_owner_confirmed(user: User) -> None:
    """A farmer entered by an agent has now confirmed on their own phone."""
    fp = getattr(user, "farmer_profile", None)
    if fp and fp.organisation_id and fp.org_status == OrgStatus.PENDING and fp.assisted_by_id:
        fp.org_status = OrgStatus.CONFIRMED
        fp.save()


@transaction.atomic
def create_assisted_farmer(agent: User, data: dict, request=None, org: Organisation | None = None) -> User:
    """`org` is passed only by staff acting for an organisation; agents are limited to their own verified ones."""
    if org is None:
        orgs = agent_orgs(agent)
        code = data.get("org_code")
        if code:
            org = orgs.filter(code=code).first()
        elif orgs.count() == 1:
            org = orgs.first()
        if org is None:
            if OrgMembership.objects.filter(user=agent).exists() and not orgs.exists():
                raise ApiError("org_not_verified", "Your organisation is still being verified. You can add farmers once it is approved.", 403)
            raise ApiError("org_required", "Choose which organisation you are adding this farmer for", 400)

    today = timezone.now() - timedelta(hours=24)
    if User.objects.filter(created_by=agent, date_joined__gte=today).count() >= MAX_NEW_FARMERS_PER_AGENT_PER_DAY:
        raise ApiError("agent_daily_limit", "Daily limit for adding farmers reached", status.HTTP_429_TOO_MANY_REQUESTS)

    if User.objects.filter(phone=data["phone"]).exists():
        raise ApiError("already_registered", "This number already has an account. Ask the farmer to join your organisation from the app with your join code.", 409)

    user = User.objects.create_user(
        phone=data["phone"], role=Role.FARMER, status=UserStatus.PENDING,
        language=data.get("language", "hi"), created_by=agent,
    )
    fp = user.farmer_profile  # created by signal
    for f in ("name", "village", "block", "district", "land_acres", "crops", "contact_is_family", "family_contact_name"):
        if f in data:
            setattr(fp, f, data[f])
    fp.organisation = org
    fp.org_status = OrgStatus.PENDING
    fp.assisted_by = agent
    fp.assisted_at = timezone.now()
    fp.save()
    audit.log("assisted_farmer_created", actor=agent, target=user, request=request, organisation=org.pk)
    # The farmer confirms with a code sent to their own phone.
    otp.request_otp(user.phone, data.get("channel", "sms"), audit.client_ip(request), user.language)
    return user


def resend_confirmation(agent: User, farmer_user: User, channel: str, request=None) -> dict:
    if farmer_user.status != UserStatus.PENDING or farmer_user.created_by_id != agent.pk:
        raise ApiError("not_found", "Farmer not found", 404)
    return otp.request_otp(farmer_user.phone, channel, audit.client_ip(request), farmer_user.language)


@transaction.atomic
def request_join(farmer: FarmerProfile, org_code: str, request=None) -> OrgLinkRequest:
    org = Organisation.objects.filter(code=(org_code or "").strip().lower()).first()
    if org is None:
        raise ApiError("org_not_found", "No organisation found for this code", 404)
    if farmer.organisation_id == org.pk and farmer.org_status == OrgStatus.CONFIRMED:
        raise ApiError("already_member", "You are already a member of this organisation", 409)
    link, created = OrgLinkRequest.objects.get_or_create(farmer=farmer, organisation=org, status=LinkStatus.PENDING)
    if created:
        audit.log("org_join_requested", actor=farmer.user, target=link, request=request, organisation=org.pk)
        if org.verified and org.auto_approve_members:
            link.status = LinkStatus.APPROVED
            link.decided_at = timezone.now()
            link.save()
            farmer.organisation = org
            farmer.org_status = OrgStatus.CONFIRMED
            farmer.save()
            audit.log("org_join_auto_approved", actor=farmer.user, target=link, request=request, organisation=org.pk)
    return link


@transaction.atomic
def decide_join(agent: User, link: OrgLinkRequest, approve: bool, request=None) -> OrgLinkRequest:
    if not link.organisation.verified or not OrgMembership.objects.filter(user=agent, organisation=link.organisation).exists():
        raise ApiError("not_found", "Request not found", 404)
    if link.status != LinkStatus.PENDING:
        raise ApiError("already_decided", "This request was already decided", 409)
    link.status = LinkStatus.APPROVED if approve else LinkStatus.REJECTED
    link.decided_by = agent
    link.decided_at = timezone.now()
    link.save()
    if approve:
        fp = link.farmer
        fp.organisation = link.organisation
        fp.org_status = OrgStatus.CONFIRMED
        fp.save()
    audit.log("org_join_approved" if approve else "org_join_rejected", actor=agent, target=link, request=request)
    return link


@transaction.atomic
def delete_account(user: User, request=None) -> None:
    """Remove personal data. Audit events stay; invoices (later) are kept for tax rules."""
    audit.log("account_deleted", actor=user, target=user, request=request)
    user.devices.update(revoked_at=timezone.now())
    fp = getattr(user, "farmer_profile", None)
    if fp:
        fp.name = fp.village = fp.block = fp.district = fp.family_contact_name = ""
        fp.land_acres = None
        fp.crops = []
        fp.organisation = None
        fp.org_status = OrgStatus.NONE
        fp.assisted_by = None
        fp.save()
    bp = getattr(user, "buyer_profile", None)
    if bp:
        bp.contact_name = bp.business_name = bp.city = bp.gstin = bp.fssai = ""
        bp.business_type = ""
        bp.save()
    user.phone = f"deleted-{user.pk}-{secrets.token_hex(4)}"
    user.status = UserStatus.DELETED
    user.pin_hash = ""
    user.set_unusable_password()
    user.save()


def make_org_code(name: str) -> str:
    base = slugify(name)[:12].strip("-_") or "fpo"
    code = base
    while Organisation.objects.filter(code=code).exists():
        code = f"{base}{secrets.randbelow(900) + 100}"
    return code


@transaction.atomic
def register_org(user: User, data: dict, request=None) -> Organisation:
    """An FPO/NGO signs up by itself. It stays unverified (no powers) until Seedha Bazar staff check it."""
    org = Organisation.objects.create(
        name=data["name"], kind=data["kind"], code=make_org_code(data["name"]), district=data.get("district", ""),
        block=data.get("block", ""), registration_no=data.get("registration_no", ""), contact_name=data.get("contact_name", ""),
    )
    OrgMembership.objects.create(user=user, organisation=org, role=OrgMembership.Role.ADMIN)
    audit.log("org_registered", actor=user, target=org, request=request)
    return org


@transaction.atomic
def provision_agent(phone: str, org: Organisation, actor: User | None = None, request=None) -> User:
    """Staff attach an agent to an organisation. The agent still signs in with their own phone code."""
    user, created = User.objects.get_or_create(phone=phone, defaults={"role": Role.AGENT, "status": UserStatus.ACTIVE})
    if not created and user.role != Role.AGENT:
        raise ApiError("phone_in_use", "This number already belongs to a farmer or buyer account. Use a different number for the agent.", 409)
    OrgMembership.objects.get_or_create(user=user, organisation=org)
    audit.log("agent_provisioned", actor=actor, target=user, request=request, organisation=org.pk)
    return user
