"""What each person sees: announcements from staff, and news ranked for their place, crops and language."""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Announcement, Article, Scheme, Video

CANDIDATES = 400


def profile_of(user) -> dict:
    """{state, district, crops} for the person, from their own profile or book. Empty values when we do not know."""
    out = {"state": "", "district": "", "crops": []}
    if not user or not user.is_authenticated:
        return out
    fp = getattr(user, "farmer_profile", None) if user.role == "farmer" else None
    if fp is not None:
        from farmerbook.models import CropCycle

        crops = list(fp.crops or []) + list(CropCycle.objects.filter(owner=user, deleted_at__isnull=True).values_list("crop", flat=True))
        out.update(state=fp.state, district=fp.district, crops=list(dict.fromkeys(crops)))
    elif user.role == "agent":
        from profiles.models import OrgMembership

        m = OrgMembership.objects.filter(user=user).select_related("organisation").first()
        if m:
            org = m.organisation
            crops = [c for fp_crops in org.farmers.values_list("crops", flat=True) for c in (fp_crops or [])]
            out.update(state=org.state, district=org.district, crops=[c for c, _ in _top(crops)])
    return out


def _top(items, n=6):
    counts: dict = {}
    for i in items:
        counts[i] = counts.get(i, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:n]


def announcements_for(user, lang: str, limit: int = 3):
    now = timezone.now()
    role = getattr(user, "role", "") if user and user.is_authenticated else ""
    audience = {"farmer": "farmer", "agent": "fpo", "buyer": "buyer"}.get(role, "")
    p = profile_of(user)
    qs = Announcement.objects.filter(starts_at__lte=now).filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
    qs = qs.filter(Q(audience="all") | Q(audience=audience)).filter(Q(language="") | Q(language=lang))
    rows = []
    for a in qs.order_by("-pinned", "-starts_at")[:30]:
        if a.state and p["state"] and a.state.lower() != p["state"].lower():
            continue
        if a.district and p["district"] and a.district.lower() != p["district"].lower():
            continue
        rows.append(a)
    return rows[:limit]


def ranked_articles(user, lang: str, topic: str = "", crop: str = "", state: str = "", language: str = "", limit: int = 20, offset: int = 0, mine: bool = True):
    """Newest and most relevant first. A person's own state, crops and language lift an item; age pulls it down."""
    qs = Article.objects.filter(hidden=False)
    if state:
        qs = qs.filter(Q(state__iexact=state) | Q(state=""))
    if language:
        qs = qs.filter(language=language)
    now = timezone.now()
    p = profile_of(user) if mine else {"state": "", "district": "", "crops": []}
    rows = []
    for a in qs.filter(published_at__gte=now - timedelta(days=45)).order_by("-published_at")[:CANDIDATES * (3 if topic or crop else 1)]:
        # Tag filters run here, not in SQL: JSON "contains" is not available on every database we support.
        if (topic and topic not in a.topics) or (crop and crop not in a.crops):
            continue
        r = a.score - (now - a.published_at).total_seconds() / 86400 * 1.5
        if p["state"] and a.state.lower() == p["state"].lower():
            r += 6
        elif a.state and p["state"] and a.state.lower() != p["state"].lower():
            r -= 4
        r += 5 * min(2, len(set(a.crops) & set(p["crops"])))
        r += 4 if a.language == lang else 1 if a.language == "en" else -2
        rows.append((r, a))
    rows.sort(key=lambda x: -x[0])
    return [a for _, a in rows[offset:offset + limit]], len(rows)


def schemes_for(user_role: str = "", topic: str = "", state: str = ""):
    qs = Scheme.objects.filter(active=True)
    audience = {"farmer": "farmer", "agent": "fpo", "buyer": ""}.get(user_role, "")
    rows = [s for s in qs if not topic or topic in s.topics]
    if state:
        rows = [s for s in rows if s.level == "central" or s.state.lower() == state.lower()]
    if audience:
        rows.sort(key=lambda s: (audience not in s.audience, s.sort))
    return rows


def videos_for(lang: str, topic: str = "", crop: str = "", limit: int = 24):
    qs = Video.objects.filter(hidden=False)
    rows = [v for v in qs.order_by("-featured", "-published_at")[:400] if (not topic or topic in v.topics) and (not crop or crop in v.crops)]
    rows.sort(key=lambda v: (not v.featured, v.language != lang, -v.published_at.timestamp()))
    return rows[:limit]
