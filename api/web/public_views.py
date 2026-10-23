import json
from datetime import timedelta

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts import audit
from profiles.models import Organisation

from .forms import LeadForm
from .models import Lead

LEAD_KINDS = {"buyer": Lead.Kind.BUYER, "fpo": Lead.Kind.FPO, "farmer": Lead.Kind.FARMER, "contact": Lead.Kind.CONTACT, "calculator": Lead.Kind.CALCULATOR}
MAX_LEADS_PER_IP_PER_HOUR = 10


def home(request):
    if request.user.is_authenticated:
        from .context import home_for

        return redirect(home_for(request.user))
    from .rates_views import rate_context

    from market.models import Listing

    from .market_views import card

    memo: dict = {}
    listings = [card(li, memo) for li in Listing.live().select_related("organisation", "seller__farmer_profile").order_by("-created_at")[:2]]
    return render(request, "web/public/home.html", {**rate_context(request), "listings": listings})


def for_farmers(request):
    return render(request, "web/public/for_farmers.html")


def for_fpos(request):
    return render(request, "web/public/for_fpos.html", {"form": LeadForm(lang=request.lang), "lead_kind": "fpo"})


def for_buyers(request):
    return render(request, "web/public/for_buyers.html", {"form": LeadForm(lang=request.lang), "lead_kind": "buyer"})


def privacy(request):
    return render(request, "web/public/privacy.html")


@require_http_methods(["GET", "POST"])
def lead(request, kind):
    if kind not in LEAD_KINDS:
        return redirect("/")
    form = LeadForm(request.POST or None, lang=request.lang)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        ip = audit.client_ip(request)
        recent = Lead.objects.filter(ip=ip, created_at__gte=timezone.now() - timedelta(hours=1)).count() if ip else 0
        if not d["website"] and recent < MAX_LEADS_PER_IP_PER_HOUR:  # a filled honeypot or a flood is dropped quietly
            extra = {}
            raw = request.POST.get("payload", "")
            if kind == "calculator" and raw and len(raw) <= 2000:
                try:
                    parsed = json.loads(raw)
                    extra = parsed if isinstance(parsed, dict) else {}
                except ValueError:
                    extra = {}
            Lead.objects.create(
                kind=LEAD_KINDS[kind], name=d["name"], phone=d["phone"], city=d["city"], message=d["message"], payload=extra,
                attribution=request.session.get("attribution", {}), language=request.lang, consent=True, ip=ip,
            )
        return redirect(f"/thanks/?kind={kind}")
    return render(request, "web/public/lead.html", {"form": form, "lead_kind": kind})


def thanks(request):
    return render(request, "web/public/thanks.html", {"kind": request.GET.get("kind", "")})


def join_page(request, code):
    """A link an FPO shares with its members. After the farmer signs in, the join request is sent for them."""
    org = get_object_or_404(Organisation, code=code.lower(), verified=True)
    request.session["join_code"] = org.code
    request.session["login_as"] = "farmer"
    return render(request, "web/public/join.html", {"org": org})


def institution_moved(request, rest=""):
    from django.conf import settings

    return redirect(f"{settings.INSTITUTION_URL}/{rest}")
