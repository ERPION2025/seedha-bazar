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
