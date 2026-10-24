"""Share cards: one tap makes a branded picture and a link to post on WhatsApp, Facebook or Instagram. The link opens a page
that invites the viewer to become a buyer (or join as a farmer), and counts how many came from each post."""
import secrets
from decimal import Decimal

from django.conf import settings
from django.db.models import F
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

import catalog
from accounts.models import Role
from engagement.models import GamePlay, ShareCard
from market.models import Listing, Pool

from .i18n import tr
from .market_views import base_for

MAX_PNG = 1_500_000


def _card_for(request, kind: str, ref: str) -> dict | None:
    """Title, lines and target for what is being shared. Only the owner can share their own listing, lot or stock."""
    u, lang = request.user, request.lang
    T = lambda s, **kw: tr(lang, s, **kw)
    if kind == "listing":
        li = Listing.objects.filter(pk=ref, seller=u).first() if ref.isdigit() else None
        if li is None:
            return None
        name = tr(lang, catalog.name(li.crop))
        unit = tr(lang, li.unit)
        return {"title": name, "emoji": catalog.emoji(li.crop), "lines": [f"{li.quantity.normalize():f} {unit} · ₹{li.price:,.0f} / {unit}", f"📍 {li.district}, {li.state}",
                T("Direct from the farmer, no middlemen")], "target": f"/market/{li.pk}/"}
    if kind == "lot":
        pool = Pool.objects.filter(pk=ref, organisation__memberships__user=u).select_related("organisation").first() if ref.isdigit() else None
        if pool is None or pool.listing_id is None:
            return None
        n = pool.shares.filter(status="confirmed").count()
        name = tr(lang, catalog.name(pool.product))
        return {"title": name, "emoji": catalog.emoji(pool.product), "lines": [f"{pool.listing.quantity.normalize():f} {tr(lang, pool.unit)} · ₹{pool.price:,.0f}",
                T("Pooled from {n} farmers", n=n), f"🏢 {pool.organisation.name}, {pool.organisation.district}"], "target": f"/market/{pool.listing_id}/"}
    if kind == "stock" and u.role == Role.FARMER:
        from market import stock
        rows = [ln for ln in stock.lines(u) if ln["free_kg"] > 0][:3]
        if not rows:
            return None
        fp = u.farmer_profile
        lines = [f"{catalog.emoji(r['product'])} {tr(lang, catalog.name(r['product']))}: {(r['free_kg'] / 100).quantize(Decimal('0.1'))} {tr(lang, 'quintal')}" for r in rows]
        return {"title": T("Fresh from my farm"), "emoji": "🧑‍🌾", "lines": lines + [f"📍 {fp.village}, {fp.district}"], "target": f"/producers/farmer/{u.pk}/"}
    if kind == "score":
        gp = GamePlay.objects.filter(pk=ref, user=u).first() if ref.isdigit() else None
        if gp is None:
            return None
        from engagement.games import GAMES
        title = next((g[2] for g in GAMES if g[0] == gp.game), gp.game)
        return {"title": T("I scored {n} points!", n=gp.score), "emoji": "🏆", "lines": [tr(lang, title), T("Play free farming games on Seedha Bazar")], "target": "/games/"}
    if kind == "achievement" and u.role == Role.FARMER:
        from engagement import scores
        a, p = scores.activity(u)["score"], scores.performance(u)["score"]
        return {"title": T("My farm scores"), "emoji": "🏅", "lines": [f"⚡ {T('Activity')}: {a}/100", f"🏅 {T('Performance')}: {p}/100", T("Growing better with Seedha Bazar")],
                "target": "/for-farmers/"}
    return None


@require_POST
def new(request):
    """Make a card. The phone draws the picture next and uploads it."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "sign_in"}, status=401)
    kind, ref = request.POST.get("kind", ""), request.POST.get("ref", "")
    card = _card_for(request, kind, ref)
    if card is None:
        return JsonResponse({"error": "not_found"}, status=404)
    s = ShareCard.objects.create(code=secrets.token_urlsafe(6)[:8].replace("-", "x").replace("_", "y"), user=request.user, kind=kind, ref=ref[:40],
                                 title=card["title"][:160], lines=card["lines"], target=card["target"], language=request.lang)
    url = f"{settings.SITE_URL}/s/{s.code}/"
    buyer = tr(request.lang, "Become a buyer and get this offer first") if kind in ("listing", "lot", "stock") else tr(request.lang, "Join Seedha Bazar")
    return JsonResponse({"code": s.code, "url": url, "title": card["title"], "emoji": card["emoji"], "lines": card["lines"], "cta": buyer,
                         "brand": tr(request.lang, "Seedha Bazar"), "tagline": tr(request.lang, "Direct market, fair price, your farmer brother"),
                         "share_text": f"{card['emoji']} {card['title']} — {' · '.join(card['lines'][:2])}\n{buyer}: {url}"})


@require_POST
def upload(request, code):
    s = get_object_or_404(ShareCard, code=code, user=request.user) if request.user.is_authenticated else None
    if s is None:
        raise Http404
    f = request.FILES.get("image")
    if not f or f.size > MAX_PNG or f.read(8) != b"\x89PNG\r\n\x1a\n":
        return JsonResponse({"error": "bad_image"}, status=400)
    f.seek(0)
    from PIL import Image
    try:
        im = Image.open(f)
        im.verify()
        if im.size[0] > 2000 or im.size[1] > 2000:
            raise ValueError
    except Exception:
        return JsonResponse({"error": "bad_image"}, status=400)
    f.seek(0)
    s.image.save(f"{s.code}.png", f, save=True)
    return JsonResponse({"ok": True, "image": f"{settings.SITE_URL}/s/{s.code}.png"})


def image(request, code):
    s = get_object_or_404(ShareCard, code=code)
    if not s.image:
        raise Http404
    resp = FileResponse(s.image.open("rb"), content_type="image/png")
    resp["Cache-Control"] = "public, max-age=86400"
    return resp


def landing(request, code):
    """Public page behind every shared link: the offer, and a big button to become a buyer (or join as a farmer)."""
    s = get_object_or_404(ShareCard.objects.select_related("user__farmer_profile"), code=code)
    ShareCard.objects.filter(pk=s.pk).update(views=s.views + 1)
    request.session["share_ref"] = s.code
    attr = request.session.get("attribution") or {}
    attr.setdefault("utm_source", "share")
    attr.setdefault("utm_campaign", s.kind)
    attr["share"] = s.code
    request.session["attribution"] = attr
    buyer = s.kind in ("listing", "lot", "stock")
    join_url = f"/login/?as=buyer&next={s.target}" if buyer else "/login/?as=farmer"
    return render(request, "web/share/landing.html", {"s": s, "buyer": buyer, "join_url": join_url, "og_image": f"{settings.SITE_URL}/s/{s.code}.png" if s.image else "",
                                                      "og_url": f"{settings.SITE_URL}/s/{s.code}/", "base_tpl": "web/base.html"})


def mine(request):
    if not request.user.is_authenticated:
        return redirect("/login/")
    return render(request, "web/share/mine.html", {"rows": ShareCard.objects.filter(user=request.user)[:50], "base_tpl": base_for(request.user)})


def credit_signup(request, user):
    """Called after a first sign-in: if the person came from a shared post, count it for the post's owner."""
    code = request.session.pop("share_ref", None)
    if code:
        ShareCard.objects.filter(code=code).exclude(user=user).update(signups=F("signups") + 1)
