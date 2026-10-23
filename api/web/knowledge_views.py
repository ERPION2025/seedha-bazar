"""News, schemes and videos. Public pages that also sit inside each person's own area."""
from django.http import Http404
from django.shortcuts import get_object_or_404, render

import catalog
from knowledge import classify, services
from knowledge.models import Scheme

from .market_views import base_for

PAGE = 20
TOPIC_TABS = [("", "All"), ("scheme", "Schemes"), ("price", "Prices and MSP"), ("insurance", "Insurance"), ("fpo", "FPO and NGO"), ("weather", "Weather"),
              ("advisory", "Advisories"), ("processing", "Processing and storage"), ("credit", "Credit"), ("technology", "New methods")]
SCHEME_TOPICS = [("", "All"), ("bulk_purchase", "Bulk purchase"), ("fpo_benefit", "For FPOs"), ("insurance", "Insurance"), ("credit", "Credit"), ("processing", "Processing"),
                 ("storage", "Storage"), ("market", "Selling"), ("income", "Income support"), ("inputs", "Inputs and equipment")]


def _base(request):
    return base_for(request.user) if request.user.is_authenticated else "web/base.html"


def news(request):
    topic = request.GET.get("topic", "")
    crop = request.GET.get("crop", "")
    language = request.GET.get("language", "")
    if topic not in {t for t, _ in TOPIC_TABS}:
        topic = ""
    if language not in ("hi", "mr", "en", ""):
        language = ""
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    rows, total = services.ranked_articles(request.user, request.lang, topic=topic, crop=crop if crop in catalog.PRODUCTS else "", language=language, limit=PAGE, offset=(page - 1) * PAGE)
    ctx = {"rows": rows, "topic": topic, "crop": crop, "language": language, "page": page, "has_next": total > page * PAGE, "topic_tabs": TOPIC_TABS, "base_tpl": _base(request),
           "announcements": services.announcements_for(request.user, request.lang, 5) if page == 1 else [],
           "videos": services.videos_for(request.lang, topic=topic, crop=crop)[:3] if page == 1 and not language else []}
    return render(request, "web/knowledge/news.html", ctx)


def schemes(request):
    topic = request.GET.get("topic", "")
    if topic not in {t for t, _ in SCHEME_TOPICS}:
        topic = ""
    u = request.user
    from knowledge.services import profile_of

    state = profile_of(u)["state"]
    rows = services.schemes_for(getattr(u, "role", "") if u.is_authenticated else "", topic, state)
    for s in rows:
        s.t_name, s.t_short = s.text("name", request.lang), s.text("short", request.lang)
    return render(request, "web/knowledge/schemes.html", {"rows": rows, "topic": topic, "topic_tabs": SCHEME_TOPICS, "base_tpl": _base(request)})


def scheme_detail(request, slug):
    s = get_object_or_404(Scheme, slug=slug, active=True)
    lang = request.lang
    fields = {k: s.text(k, lang) for k in ("name", "short", "benefit", "eligibility", "how_to_apply", "documents")}
    fields["documents"] = [d for d in fields["documents"].splitlines() if d.strip()]
    related, _ = services.ranked_articles(request.user, lang, topic=(s.topics or [""])[0] if s.topics and s.topics[0] in {t for t, _ in TOPIC_TABS} else "", limit=4)
    return render(request, "web/knowledge/scheme.html", {"s": s, "f": fields, "related": related, "base_tpl": _base(request)})


def videos(request):
    topic = request.GET.get("topic", "")
    crop = request.GET.get("crop", "")
    rows = services.videos_for(request.lang, topic=topic if topic in {t for t, _ in TOPIC_TABS} else "", crop=crop if crop in catalog.PRODUCTS else "", limit=30)
    return render(request, "web/knowledge/videos.html", {"rows": rows, "topic": topic, "crop": crop, "topic_tabs": TOPIC_TABS, "base_tpl": _base(request)})
