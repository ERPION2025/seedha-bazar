from .i18n import DEFAULT_LANG, LANGS

ATTRIBUTION_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "gclid", "fbclid")


class LanguageMiddleware:
    """`?lang=hi|mr|en` switches language and is remembered; signed-in people keep it on their account."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        chosen = request.GET.get("lang")
        user = getattr(request, "user", None)
        signed_in = bool(user and user.is_authenticated)
        if chosen in LANGS:
            request.session["lang"] = chosen
            if signed_in and user.language != chosen:
                user.language = chosen
                user.save(update_fields=["language"])
        request.lang = request.session.get("lang") or (user.language if signed_in and user.language in LANGS else DEFAULT_LANG)
        return self.get_response(request)


class AttributionMiddleware:
    """Remember where an ad click came from (first touch only) so a later form submission carries it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "GET" and "attribution" not in request.session:
            found = {k: request.GET[k][:100] for k in ATTRIBUTION_KEYS if request.GET.get(k)}
            if found:
                found["landing"] = request.path[:100]
                ref = request.META.get("HTTP_REFERER", "")
                if ref:
                    found["referrer"] = ref[:200]
                request.session["attribution"] = found
        return self.get_response(request)


class SiteMiddleware:
    """Two sites from one codebase and one database: the main Seedha Bazar site (farmers, FPOs and NGOs, buyers, staff) and
    Institution Connect (KVKs and research agencies) on its own address, with its own URLs, sign-in and menus.
    Sessions do not cross: the browser keeps cookies per host."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        host = request.get_host().split(":")[0].lower()
        if host in settings.INSTITUTION_HOSTS:
            request.site, request.urlconf = "institution", "institution.urls"
        else:
            request.site = "main"
        return self.get_response(request)


class LoginFirstMiddleware:
    """Nothing is shown before sign-in: every page sends a visitor to the sign-in page, which then opens the menus for their role.

    Open without signing in: the sign-in steps themselves, the privacy notice, an FPO's join link, shared ad cards (so a
    link on WhatsApp or Facebook shows its picture), statement checks for banks, and machine endpoints (API, webhooks,
    static files, the app manifest and service worker)."""

    OPEN = ("/login/", "/logout/", "/auth/facebook/", "/privacy/", "/join/", "/s/", "/verify/", "/static/", "/media/", "/api/", "/admin/",
            "/hooks/", "/manifest.webmanifest", "/sw.js", "/favicon.ico", "/robots.txt", "/health/", "/kvk/",
            "/console/login/")

    def __init__(self, get_response):
        self.get_response = get_response

    OPEN_INSTITUTION = ("/login/", "/logout/", "/static/", "/manifest.webmanifest", "/sw.js", "/favicon.ico", "/robots.txt", "/health/")

    def __call__(self, request):
        user = getattr(request, "user", None)
        open_paths = self.OPEN_INSTITUTION if getattr(request, "site", "main") == "institution" else self.OPEN
        if not (user and user.is_authenticated) and not request.path.startswith(open_paths):
            from urllib.parse import quote

            from django.shortcuts import redirect

            if request.path.startswith("/console/"):  # the owner console has its own password sign-in
                return redirect("/console/login/")
            if request.path == "/" or request.method != "GET":
                return redirect("/login/")
            return redirect(f"/login/?next={quote(request.get_full_path())}")
        return self.get_response(request)
