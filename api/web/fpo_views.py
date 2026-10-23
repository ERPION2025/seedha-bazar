from django.conf import settings
from django.contrib import messages
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from urllib.parse import quote

from accounts.errors import ApiError
from accounts.models import Role, User
from accounts.phone import InvalidPhone, normalise_phone
from profiles import services
from profiles.models import FarmerProfile, LinkStatus, OrgLinkRequest, Organisation, OrgMembership

from . import forms as f
from .helpers import error_text, ok, payload, role_required, warn
from .rates_views import rate_context

agent_only = role_required(Role.AGENT)
MAX_BULK = 50


def current_org(request):
    m = OrgMembership.objects.filter(user=request.user).select_related("organisation").order_by("pk").first()
    return m.organisation if m else None


def needs_org(view):
    """FPO pages need an organisation; a new agent is sent to register one first."""
    from functools import wraps

    @wraps(view)
    def wrapper(request, *a, **kw):
        org = current_org(request)
        if org is None:
            return redirect("/fpo/register/")
        request.org = org
        return view(request, *a, **kw)

    return wrapper


def needs_verified(view):
    from functools import wraps

    @wraps(view)
    def wrapper(request, *a, **kw):
        if not request.org.verified:
            warn(request, "Your organisation is still being verified. You can add farmers once it is approved.")
            return redirect("/fpo/")
        return view(request, *a, **kw)

    return wrapper


def share_text(request, org):
    link = f"{settings.SITE_URL}/join/{org.code}/"
    text = {
        "hi": f"{org.name} अब सीधा बाज़ार पर है। अपनी फसल का हिसाब रखें और सीधे खरीदार तक पहुँचें। जुड़ने के लिए: {link}",
        "mr": f"{org.name} आता सीधा बाज़ारवर आहे. पिकाचा हिशोब ठेवा आणि थेट खरेदीदारांपर्यंत पोहोचा. जोडण्यासाठी: {link}",
        "en": f"{org.name} is now on Seedha Bazar. Keep your crop accounts and reach buyers directly. Join here: {link}",
    }[request.lang]
    return link, text, f"https://wa.me/?text={quote(text)}"


@agent_only
def register(request):
    if current_org(request) is not None:
        return redirect("/fpo/")
    form = f.FpoRegisterForm(request.POST or None, lang=request.lang)
    if request.method == "POST" and form.is_valid():
        services.register_org(request.user, form.cleaned_data, request)
        ok(request, "Thank you. We will check your registration and approve you soon.")
        return redirect("/fpo/")
    return render(request, "web/fpo/register.html", {"form": form})


@agent_only
@needs_org
def dashboard(request):
    org = request.org
    members = FarmerProfile.objects.filter(organisation=org)
    confirmed = members.filter(org_status="confirmed")
    crops = {}
    for fp in confirmed.only("crops", "land_acres"):
        for c in fp.crops:
            crops[c] = crops.get(c, 0) + 1
    link, text, wa = share_text(request, org)
    ctx = {
        "org": org, "total": members.count(), "confirmed": confirmed.count(), "waiting": members.filter(user__status="pending").count(),
        "requests": OrgLinkRequest.objects.filter(organisation=org, status=LinkStatus.PENDING).count(),
        "acres": confirmed.aggregate(t=Sum("land_acres"))["t"] or 0,
        "top_crops": sorted(crops.items(), key=lambda kv: -kv[1])[:6],
        "share_link": link, "share_text": text, "wa_url": wa,
        **rate_context(request),
    }
    from farming.services import org_summary
    ctx["groups"] = org_summary(org)
    return render(request, "web/fpo/dashboard.html", ctx)


@agent_only
@needs_org
def farmers(request):
    org = request.org
    q = (request.GET.get("q") or "").strip()
    qs = FarmerProfile.objects.filter(organisation=org).select_related("user").order_by("-updated_at")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(village__icontains=q) | Q(user__phone__icontains=q))
    return render(request, "web/fpo/farmers.html", {"org": org, "rows": qs[:300], "q": q})


def farmer_data(d: dict, lang_default="hi") -> dict:
    data = payload({k: v for k, v in d.items() if k not in ("crops", "other_crops", "land_acres")})
    if d.get("land_acres") is not None:
        data["land_acres"] = d["land_acres"]
    data["crops"] = f.split_crops(d.get("crops") or [], d.get("other_crops"))
    return data


@agent_only
@needs_org
@needs_verified
def add_farmer(request):
    form = f.AddFarmerForm(request.POST or None, lang=request.lang)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_assisted_farmer(request.user, farmer_data(form.cleaned_data), request, org=request.org)
        except ApiError as e:
            form.add_error("phone" if e.code == "already_registered" else None, error_text(request, e))
        else:
            ok(request, "Added. A code was sent to the farmer's phone. The farmer confirms it to activate the account.")
            return redirect("/fpo/farmers/")
    return render(request, "web/fpo/add_farmer.html", {"form": form, "org": request.org})


@agent_only
@needs_org
@needs_verified
def bulk_add(request):
    form = f.BulkFarmersForm(request.POST or None, lang=request.lang)
    results = None
    if request.method == "POST" and form.is_valid():
        results = []
        lines = [ln.strip() for ln in form.cleaned_data["lines"].splitlines() if ln.strip()]
        if len(lines) > MAX_BULK:
            form.add_error("lines", "Add up to 50 farmers at a time")
            results = None
        else:
            for ln in lines:
                results.append(_bulk_line(request, ln))
    return render(request, "web/fpo/bulk_add.html", {"form": form, "org": request.org, "results": results})


def _bulk_line(request, line):
    """phone, name, village, district, acres, crops (space separated). Returns a row for the result table."""
    parts = [p.strip() for p in line.split(",")]
    row = {"line": line, "ok": False, "error": ""}
    try:
        if len(parts) < 4:
            raise ValueError("Each line needs: phone, name, village, district")
        phone = normalise_phone(parts[0])
        acres = None
        if len(parts) > 4 and parts[4]:
            acres = parts[4]
        crops = [c for c in (parts[5].lower().split() if len(parts) > 5 else [])]
        data = {"phone": phone, "name": parts[1], "village": parts[2], "district": parts[3], "language": request.lang, "crops": crops}
        if acres:
            data["land_acres"] = acres
        services.create_assisted_farmer(request.user, data, request, org=request.org)
        row["ok"] = True
    except InvalidPhone:
        row["error"] = "Enter a valid 10-digit Indian mobile number"
    except ApiError as e:
        row["error"] = error_text(request, e)
    except ValueError as e:
        row["error"] = str(e)
    except Exception:
        row["error"] = "Could not read this line"
    return row


@agent_only
@needs_org
@needs_verified
@require_POST
def resend(request, user_id):
    farmer = get_object_or_404(User, pk=user_id, farmer_profile__organisation=request.org)
    try:
        services.resend_confirmation(request.user, farmer, "sms", request)
        ok(request, "A new code was sent.")
    except ApiError as e:
        messages.error(request, error_text(request, e))
    return redirect("/fpo/farmers/")


@agent_only
@needs_org
def requests_list(request):
    pending = OrgLinkRequest.objects.filter(organisation=request.org, status=LinkStatus.PENDING).select_related("farmer__user").order_by("created_at")
    return render(request, "web/fpo/requests.html", {"org": request.org, "pending": pending})


@agent_only
@needs_org
@needs_verified
@require_POST
def decide(request, pk, approve):
    link = get_object_or_404(OrgLinkRequest.objects.select_related("farmer__user", "organisation"), pk=pk, organisation=request.org)
    try:
        services.decide_join(request.user, link, approve, request)
        ok(request, "Approved." if approve else "Declined.")
    except ApiError as e:
        messages.error(request, error_text(request, e))
    return redirect("/fpo/requests/")


@agent_only
@needs_org
@require_POST
def toggle_auto(request):
    org = request.org
    org.auto_approve_members = not org.auto_approve_members
    org.save(update_fields=["auto_approve_members"])
    ok(request, "Farmers who use your link are now confirmed automatically." if org.auto_approve_members else "You will approve each farmer yourself.")
    return redirect("/fpo/")
