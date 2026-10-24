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


# ---------- pages open to visitors and search engines (no menus; buying and everything else need sign-in) ----------
FOOTER_PRODUCE = ["wheat", "rice", "soybean", "gram", "milk", "eggs", "fish", "honey", "kodo", "cocoons", "mustard", "maize", "tur", "moong", "kutki", "onion",
                  "potato", "tomato", "garlic", "turmeric", "atta"]


def for_ngos(request):
    return render(request, "web/public/for_fpos.html", {"form": LeadForm(lang=request.lang), "lead_kind": "fpo", "ngo": True})


def _live_counts() -> dict:
    from django.core.cache import cache
    from django.db.models import Count

    from market.models import Listing

    out = cache.get("produce-counts")
    if out is None:
        out = dict(Listing.live().values_list("crop").annotate(n=Count("id")).values_list("crop", "n"))
        cache.set("produce-counts", out, 600)
    return out


def produce_index(request):
    """All produce on the marketplace, by kind, with how many lots are on sale now."""
    import catalog

    counts = _live_counts()
    groups = []
    for kind, label in (("raw", "Grains and pulses"), ("fresh", "Fresh produce"), ("live", "Dairy, poultry, fish, honey and silk"), ("semi", "Processed goods")):
        rows = [{"key": k, "emoji": v[3], "n": counts.get(k, 0)} for k, v in catalog.PRODUCTS.items() if v[4] == kind]
        rows.sort(key=lambda r: (-r["n"], catalog.name(r["key"])))
        groups.append({"label": label, "rows": rows})
    return render(request, "web/public/produce_index.html", {"groups": groups, "total": sum(counts.values())})


def produce(request, crop):
    """One produce: what is on sale now (seller's first name and village only), today's mandi price, and how to buy."""
    import catalog
    from django.http import Http404

    from market.models import Listing
    from rates import services as rate_services

    from .market_views import card

    if crop not in catalog.PRODUCTS:
        raise Http404
    memo: dict = {}
    qs = Listing.live().filter(crop=crop).select_related("organisation", "seller__farmer_profile").order_by("-created_at")
    rows = [card(li, memo) for li in qs[:12]]
    ref = rate_services.typical_price(crop) if crop in rate_services.CROPS else None
    districts = sorted({li.district for li in qs[:200] if li.district})[:12]
    related = [k for k in FOOTER_PRODUCE if k != crop and catalog.PRODUCTS[k][4] == catalog.PRODUCTS[crop][4]][:8]
    return render(request, "web/public/produce.html", {"crop": crop, "emoji": catalog.emoji(crop), "rows": rows, "n": qs.count(), "ref": ref,
                                                       "districts": districts, "related": related})


def sitemap(request):
    """For search engines: the pages anyone can read."""
    from django.conf import settings
    from django.http import HttpResponse

    import catalog

    paths = ["/for-farmers/", "/for-fpos/", "/for-ngos/", "/for-buyers/", "/produce/", "/privacy/", "/login/"] + [f"/produce/{k}/" for k in catalog.PRODUCTS]
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    body += "".join(f"  <url><loc>{settings.SITE_URL}{p}</loc></url>\n" for p in paths) + "</urlset>\n"
    return HttpResponse(body, content_type="application/xml")


def robots(request):
    from django.conf import settings
    from django.http import HttpResponse

    lines = ["User-agent: *", "Allow: /for-farmers/", "Allow: /for-fpos/", "Allow: /for-ngos/", "Allow: /for-buyers/", "Allow: /produce/", "Allow: /privacy/",
             "Disallow: /console/", "Disallow: /admin/", "Disallow: /api/", "Disallow: /s/", "Disallow: /verify/", f"Sitemap: {settings.SITE_URL}/sitemap.xml"]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")
