from django.conf import settings

from .i18n import LANG_NAMES, LANGS


def home_for(user) -> str:
    if not user or not user.is_authenticated:
        return "/login/"
    if user.is_staff or user.role == "admin":
        return "/console/"
    return {"farmer": "/farmer/", "buyer": "/buyer/", "agent": "/fpo/"}.get(user.role, "/")


def site(request):
    lang = getattr(request, "lang", "hi")
    user = getattr(request, "user", None)
    unread = 0
    if user and user.is_authenticated and user.role in ("farmer", "agent", "buyer"):
        from market.services import unread_for

        unread = unread_for(user)
    return {
        "unread": unread,
        "lang": lang,
        "lang_choices": [(code, LANG_NAMES[code]) for code in LANGS],
        "home_url": home_for(user),
        "GA4_ID": settings.GA4_ID,
        "META_PIXEL_ID": settings.META_PIXEL_ID,
        "SUPPORT_WHATSAPP": settings.SUPPORT_WHATSAPP,
        "SITE_URL": settings.SITE_URL,
    }
