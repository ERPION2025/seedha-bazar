from django.conf import settings
from django.templatetags.static import static

from .i18n import LANG_NAMES, LANGS
from .voice_strings import voice_config


def home_for(user, site: str = "main") -> str:
    """Where a person lands. Institution Connect is its own site: there, everything starts at "/"; on the main site,
    KVK and research staff are sent to it."""
    if not user or not user.is_authenticated:
        return "/login/"
    if site == "institution":
        return "/"
    if user.is_staff or user.role == "admin":
        return "/console/"
    if user.role == "agronomist":
        return settings.INSTITUTION_URL + "/"
    return {"farmer": "/farmer/", "buyer": "/buyer/", "agent": "/fpo/"}.get(user.role, "/")


FOOTER_SERVICES = [("Mandi rates", "/rates/"), ("Harvest calculator", "/calculator/"), ("Weather alerts", "/weather/"), ("Warehouse loans", "/storage/"),
                   ("Crop insurance", "/insurance/"), ("Government schemes", "/schemes/"), ("Farming news", "/news/"), ("Group farming", "/farmer/groups/")]

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

    site_name = getattr(request, "site", "main")
    nav = menu(request, {"unread": unread, "deal_unread": deal_unread, "waiting_orgs": waiting_orgs, "kvk_open": kvk_open})
    portal = "kvk" if site_name == "institution" else ""
    wx_alerts, alarm_on = [], True
    if user and user.is_authenticated and user.role == "farmer":
        from notify.models import Preference
        from weather.services import active_alerts

        wx_alerts = active_alerts(user)[:3]
        pref = Preference.objects.filter(user=user).first()
        alarm_on = pref.alarm_sound if pref else True
    inbox_unread, notify_cfg = 0, None
    if user and user.is_authenticated:
        from notify import push
        from notify.models import InboxItem, Preference

        inbox_unread = InboxItem.objects.filter(user=user, read_at__isnull=True).count()
        pref = Preference.objects.filter(user=user).first()
        notify_cfg = {"asked": bool(pref and pref.prompt_answer), "vapid": settings.VAPID_PUBLIC_KEY if push.configured() else "",
                      "last": InboxItem.objects.filter(user=user).order_by("-pk").values_list("pk", flat=True).first() or 0,
                      "tone": static("web/sounds/notify.wav"), "icon": static("web/icons/icon-192.png")}
    import json

    from .public_views import FOOTER_PRODUCE

    company = {"name": settings.COMPANY_NAME, "address": settings.COMPANY_ADDRESS, "email": settings.COMPANY_EMAIL, "phone": settings.COMPANY_PHONE}
    return {
        "company": company,
        "company_ld": json.dumps({"@context": "https://schema.org", "@type": "Organization", "name": "Seedha Bazar", "legalName": company["name"], "url": settings.SITE_URL,
                                  "email": company["email"], "telephone": "+91-" + company["phone"],
                                  "address": {"@type": "PostalAddress", "streetAddress": company["address"].rsplit(", Jabalpur", 1)[0], "addressLocality": "Jabalpur",
                                              "addressRegion": "Madhya Pradesh", "addressCountry": "IN"}}).replace("</", "<\\/"),
        "footer_produce": FOOTER_PRODUCE[:10],
        "footer_services": FOOTER_SERVICES,
        "inbox_unread": inbox_unread,
        "notify_cfg": notify_cfg,
        "wx_alerts": wx_alerts,
        "alarm_on": alarm_on,
        "nav": nav,
        "portal": portal,
        "site_name": site_name,
        "base_template": "institution/base.html" if site_name == "institution" else "web/base.html",
        "INSTITUTION_URL": settings.INSTITUTION_URL,
        "unread": unread,
        "deal_unread": deal_unread,
        "waiting_orgs": waiting_orgs,
        "voice": voice_config(lang),
        "lang": lang,
        "lang_choices": [(code, LANG_NAMES[code]) for code in LANGS],
        "home_url": home_for(user, site_name),
        "GA4_ID": settings.GA4_ID,
        "META_PIXEL_ID": settings.META_PIXEL_ID,
        "SUPPORT_WHATSAPP": settings.SUPPORT_WHATSAPP,
        "SITE_URL": settings.SITE_URL,
        "map_text": map_text(lang),
        "map_cfg": {"provider": "google" if settings.MAP_PROVIDER == "google" and settings.GOOGLE_MAPS_API_KEY else "osm",
                    "google_key": settings.GOOGLE_MAPS_API_KEY if settings.MAP_PROVIDER == "google" else "", "tiles": settings.MAP_TILE_URL,
                    "attribution": settings.MAP_TILE_ATTRIBUTION},
    }
