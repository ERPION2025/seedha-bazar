"""Raising, routing and answering issues. Routing is by district: the centre whose geofence covers the farmer's district gets it."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts import audit
from accounts.errors import ApiError
from accounts.models import Role
from notify import service as notify

from .models import Issue, Reply

AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/aac", "audio/x-m4a", "audio/wav", "video/webm"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
MAX_AUDIO = 3 * 1024 * 1024
MAX_IMAGE = 6 * 1024 * 1024
RESPONSE_HOURS = 48
KEEP_MEDIA_DAYS = 180


def check_upload(f, kinds, limit):
    if not f:
        return None
    ctype = (getattr(f, "content_type", "") or "").split(";")[0].strip().lower()
    if ctype not in kinds:
        raise ApiError("bad_file", "This file type is not allowed.", 400)
    if f.size > limit:
        raise ApiError("file_too_big", "The file is too big.", 400)
    return f


def link(issue) -> str:
    return f"{settings.SITE_URL}/help/{issue.pk}/"


def staff_link(issue) -> str:
    return f"{settings.SITE_URL}/kvk/issues/{issue.pk}/"


def _alert_centre(issue: Issue, what: str):
    if issue.centre_id is None:
        return
    from web.i18n import tr

    for m in issue.centre.members.select_related("user"):
        u = m.user
        notify.send("sms", u.phone, "issue_alert", u.language, user=u, related=f"issue:{issue.pk}", what=tr(u.language, what),
                    place=issue.district, link=staff_link(issue))


@transaction.atomic
def raise_issue(user, data: dict, request=None) -> Issue:
    """`data`: description, category, crop, urgent, via_voice, voice_note, photo, lat, lon, farmer (for an FPO agent), source, related."""
    from extension.scope import centre_for_place
    from profiles.models import OrgMembership

    text = (data.get("description") or "").strip()
    if len(text) < 3 and not data.get("voice_note"):
        raise ApiError("describe_issue", "Tell us the problem: type it, speak it, or record a voice note.", 400)
    farmer, org = None, None
    if user.role == Role.FARMER:
        farmer = user
        fp = user.farmer_profile
        state, district, village = fp.state, fp.district, fp.village
        org = fp.organisation if fp.org_status == "confirmed" else None
    elif user.role == Role.AGENT:
        m = OrgMembership.objects.filter(user=user).select_related("organisation").first()
        if m is None:
            raise ApiError("not_allowed", "You cannot do this.", 403)
        org = m.organisation
        farmer = data.get("farmer")
        if farmer is not None and getattr(farmer.farmer_profile, "organisation_id", None) != org.pk:
            raise ApiError("not_allowed", "You cannot do this.", 403)
        src = farmer.farmer_profile if farmer else org
        state, district, village = src.state, src.district, getattr(src, "village", "")
    else:
        raise ApiError("not_allowed", "You cannot do this.", 403)
    if not district:
        raise ApiError("district_needed", "Add your district to your profile first.", 400)
    issue = Issue.objects.create(
        raised_by=user, farmer=farmer, organisation=org, centre=centre_for_place(state, district), state=state, district=district, village=village,
        category=data.get("category") or "other", crop=data.get("crop") or "", description=text[:2000] or "(voice note)", via_voice=bool(data.get("via_voice")),
        voice_note=check_upload(data.get("voice_note"), AUDIO_TYPES, MAX_AUDIO) or "", photo=check_upload(data.get("photo"), IMAGE_TYPES, MAX_IMAGE) or "",
        lat=data.get("lat"), lon=data.get("lon"), urgent=bool(data.get("urgent")), source=data.get("source", "app"), related=data.get("related", ""))
    audit.log("issue_raised", actor=user, target=issue, request=request, centre=issue.centre_id)
    _alert_centre(issue, "Urgent problem raised" if issue.urgent else "New problem raised")
    return issue


def can_see(user, issue: Issue) -> str:
    """'owner' (raised it, or it is about them, or their FPO), 'centre' (staff of the routed centre), or ''."""
    if not user.is_authenticated:
        return ""
    if user.pk in (issue.raised_by_id, issue.farmer_id):
        return "owner"
    if user.role == Role.AGENT and issue.organisation_id:
        from profiles.models import OrgMembership
        if OrgMembership.objects.filter(user=user, organisation_id=issue.organisation_id).exists():
            return "owner"
    if issue.centre_id and issue.centre.members.filter(user=user).exists():
        return "centre"
    if user.is_staff:
        return "centre"
    return ""


@transaction.atomic
def reply(issue: Issue, user, text: str, kind: str = "reply", via_voice=False, voice_note=None, status: str = "", request=None) -> Reply:
    side = can_see(user, issue)
    if not side:
        raise ApiError("not_allowed", "You cannot do this.", 403)
    text = (text or "").strip()
    if not text and not voice_note:
        raise ApiError("empty_message", "Write a message first.", 400)
    if side != "centre":
        kind = "reply"
    r = Reply.objects.create(issue=issue, by=user, kind=kind if kind in Reply.Kind.values else "reply", text=text[:2000] or "(voice note)", via_voice=bool(via_voice),
                             voice_note=check_upload(voice_note, AUDIO_TYPES, MAX_AUDIO) or "")
    now = timezone.now()
    if side == "centre":
        if issue.first_response_at is None and kind != "note":
            issue.first_response_at = now
        if issue.assigned_to_id is None:
            issue.assigned_to = user
        if status in ("acknowledged", "advised", "resolved", "closed"):
            issue.status = status
        elif kind in ("advice", "visit") and issue.status in ("open", "acknowledged"):
            issue.status = "advised"
        elif issue.status == "open" and kind != "note":
            issue.status = "acknowledged"
        issue.save()
        if kind != "note":
            from web.i18n import tr
            who = issue.farmer or issue.raised_by
            notify.send("sms", who.phone, "issue_reply", who.language, user=who, related=f"issue:{issue.pk}", link=link(issue))
    else:
        if status in ("resolved", "closed"):
            issue.status = status
        elif issue.status in ("advised", "resolved"):
            issue.status = "acknowledged"  # the farmer wrote again: back to the centre
        issue.save()
        _alert_centre(issue, "The farmer replied")
    audit.log("issue_reply", actor=user, target=issue, request=request, kind=kind)
    return r


def overdue(now=None):
    now = now or timezone.now()
    return Issue.objects.filter(status="open", first_response_at__isnull=True, created_at__lt=now - timedelta(hours=24), reminded_at__isnull=True, centre__isnull=False)


def remind_overdue(now=None) -> int:
    """Once per issue: tell the centre an issue has waited a day with no answer."""
    n = 0
    for issue in overdue(now):
        _alert_centre(issue, "A problem has waited a day for an answer")
        issue.reminded_at = timezone.now()
        issue.save(update_fields=["reminded_at"])
        n += 1
    return n


def purge_media(days: int = KEEP_MEDIA_DAYS) -> int:
    """Voice notes and photos are deleted after `days`; the text stays."""
    cutoff = timezone.now() - timedelta(days=days)
    n = 0
    for issue in Issue.objects.filter(created_at__lt=cutoff).exclude(voice_note="", photo=""):
        for f in (issue.voice_note, issue.photo):
            if f:
                f.delete(save=False)
                n += 1
        issue.voice_note, issue.photo = "", ""
        issue.save(update_fields=["voice_note", "photo"])
    for r in Reply.objects.filter(created_at__lt=cutoff).exclude(voice_note=""):
        r.voice_note.delete(save=False)
        r.voice_note = ""
        r.save(update_fields=["voice_note"])
        n += 1
    return n
