"""Games, scores and district insights."""
import json
from datetime import timedelta

from django.db.models import Max, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Role
from engagement import games as G
from engagement import scores
from engagement.models import GamePlay

from . import location
from .i18n import tr
from .market_views import base_for
from .voice_strings import LANG_TAG

MAX_PLAYS_PER_DAY = 60


def _place(request):
    u = request.user
    if u.is_authenticated:
        from extension.services import place_of
        s, d, _ = place_of(u)
        if d:
            return s, d
    loc = location.current(request)
    return loc.get("state", ""), loc.get("district", "")


def leaderboard(state: str, district: str, days: int = 7, limit: int = 10):
    since = timezone.now() - timedelta(days=days)
    rows = (GamePlay.objects.filter(played_at__gte=since, district__iexact=district, state__iexact=state).values("user").annotate(pts=Sum("points")).order_by("-pts")[:limit])
    from accounts.models import User
    users = {u.pk: u for u in User.objects.filter(pk__in=[r["user"] for r in rows]).select_related("farmer_profile")}
    out = []
    for r in rows:
        u = users.get(r["user"])
        fp = getattr(u, "farmer_profile", None)
        out.append({"name": (fp.name.split()[0] if fp and fp.name else "—"), "village": fp.village if fp else "", "points": r["pts"], "me": False, "uid": r["user"]})
    return out


def hub(request):
    state, district = _place(request)
    best = {}
    if request.user.is_authenticated:
        best = dict(GamePlay.objects.filter(user=request.user).values("game").annotate(b=Max("score")).values_list("game", "b"))
    board = leaderboard(state, district) if district else []
    for r in board:
        r["me"] = request.user.is_authenticated and r["uid"] == request.user.pk
    return render(request, "web/games/hub.html", {"games": [{"slug": g[0], "emoji": g[1], "title": g[2], "line": g[3], "voice": g[5], "best": best.get(g[0])} for g in G.GAMES],
                                                  "board": board, "district": district, "base_tpl": base_for(request.user) if request.user.is_authenticated else "web/base.html"})


def play(request, slug):
    meta = next((g for g in G.GAMES if g[0] == slug), None)
    if meta is None:
        raise Http404
    state, district = _place(request)
    cfg = {"slug": slug, "lang": request.lang, "speech": LANG_TAG.get(request.lang, "hi-IN"), "signed_in": request.user.is_authenticated,
           "t": {s: tr(request.lang, s) for s in G.UI}, "data": G.data_for(slug, request.lang, state, district)}
    return render(request, "web/games/play.html", {"g": {"slug": slug, "emoji": meta[1], "title": meta[2], "line": meta[3], "voice": meta[5]}, "cfg": cfg,
                                                   "base_tpl": base_for(request.user) if request.user.is_authenticated else "web/base.html"})


@require_POST
def score(request, slug):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "sign_in"}, status=401)
    if slug not in G.SLUGS:
        raise Http404
    try:
        body = json.loads(request.body or b"{}")
        value = int(body.get("score", 0))
    except (ValueError, TypeError):
        return JsonResponse({"error": "bad_score"}, status=400)
    if GamePlay.objects.filter(user=request.user, played_at__gte=timezone.now() - timedelta(days=1)).count() >= MAX_PLAYS_PER_DAY:
        return JsonResponse({"points": 0, "note": "daily_limit"})
    value = max(0, min(value, 10000))
    state, district = _place(request)
    p = GamePlay.objects.create(user=request.user, game=slug, score=value, points=min(value, G.CAP[slug]), used_voice=bool(body.get("voice")), state=state, district=district)
    return JsonResponse({"points": p.points, "id": p.pk})


def insights(request):
    state, district = _place(request)
    u = request.user
    ctx = {"state": state, "district": district, "base_tpl": base_for(u) if u.is_authenticated else "web/base.html"}
    if district:
        ctx["d"] = scores.district_insights(state, district)
        from catalog.services import odop_for
        ctx["odop"] = odop_for(state, district)
    if u.is_authenticated and u.role == Role.FARMER:
        ctx["activity"], ctx["performance"] = scores.activity(u), scores.performance(u)
        from extension.scope import percentile, yields
        from farmerbook.models import CropCycle
        from farmerbook.views import cycle_summary
        from decimal import Decimal
        mine = []
        ys = {y["crop"]: y for y in ctx.get("d", {}).get("yields", [])}
        for c in CropCycle.objects.filter(owner=u, deleted_at__isnull=True).select_related("plot"):
            s = cycle_summary(c)
            y = ys.get(c.crop)
            if y and c.plot.area_acres and Decimal(s["harvested_kg"]) > 0:
                per = Decimal(s["harvested_kg"]) / c.plot.area_acres
                mine.append({"crop": c.crop, "per_acre": per, "avg": y["average"], "pct": percentile(per, [v for v, _ in y["values"]])})
        ctx["mine"] = mine
    return render(request, "web/insights.html", ctx)
