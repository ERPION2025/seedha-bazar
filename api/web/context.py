from django.conf import settings

from .i18n import LANG_NAMES, LANGS
from .voice_strings import voice_config


def home_for(user) -> str:
    if not user or not user.is_authenticated:
        return "/login/"
    if user.is_staff or user.role == "admin":
        return "/console/"
    return {"farmer": "/farmer/", "buyer": "/buyer/", "agent": "/fpo/", "agronomist": "/kvk/"}.get(user.role, "/")


MAP_TEXT = {"boundaries": "Boundaries: geoBoundaries (ODbL), LGD", "directions": "Directions", "farmers": "Farmers", "fpos": "FPOs", "ngos": "NGOs", "stock": "Stock",
            "issues": "Open problems", "listings": "Listings", "open": "Open", "finding": "Finding you...", "you": "You are here", "none": "No centre on the map yet.",
            "nearest": "Nearest", "blocked": "Location is blocked. Choose your place from the list."}


def map_text(lang):
    from .i18n import tr

    return {k: tr(lang, v) for k, v in MAP_TEXT.items()}


def site(request):
    lang = getattr(request, "lang", "hi")
    user = getattr(request, "user", None)
    unread = deal_unread = 0
    if user and user.is_authenticated and user.role in ("farmer", "agent", "buyer"):
        from market.services import unread_for

        unread = unread_for(user)
        from deals.services import unread_for as deal_unread_for

        deal_unread = deal_unread_for(user)
    waiting_orgs = 0
    if user and user.is_authenticated and (user.is_staff or user.role == "admin"):
        from profiles.models import Organisation

        waiting_orgs = Organisation.objects.filter(verified=False).count()
    kvk_open = 0
    if user and user.is_authenticated and user.role == "agronomist":
        from issues.models import Issue

        kvk_open = Issue.objects.filter(centre__members__user=user, status="open").distinct().count()
    from .menus import menu

    nav = menu(request, {"unread": unread, "deal_unread": deal_unread, "waiting_orgs": waiting_orgs, "kvk_open": kvk_open})
    return {
        "nav": nav,
        "unread": unread,
        "deal_unread": deal_unread,
        "waiting_orgs": waiting_orgs,
        "voice": voice_config(lang),
        "lang": lang,
        "lang_choices": [(code, LANG_NAMES[code]) for code in LANGS],
        "home_url": home_for(user),
        "GA4_ID": settings.GA4_ID,
        "META_PIXEL_ID": settings.META_PIXEL_ID,
        "SUPPORT_WHATSAPP": settings.SUPPORT_WHATSAPP,
        "SITE_URL": settings.SITE_URL,
        "map_text": map_text(lang),
    }
