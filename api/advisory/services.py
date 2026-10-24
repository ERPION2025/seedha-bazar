"""Find the advisories for a place, publish one from a KVK, and sort feed items into district, crop and topic."""
import re
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import Advisory

KIND_WORDS = {  # first match wins; English and Hindi
    "weather": ("rain", "thunder", "lightning", "storm", "wind", "temperature", "heat wave", "cold wave", "frost", "fog", "hail", "cyclone",
                "वर्षा", "बारिश", "आंधी", "बिजली", "तापमान", "पाला", "कोहरा", "ओला", "चक्रवात", "लू"),
    "pest": ("pest", "insect", "disease", "blight", "rust", "wilt", "fungicide", "insecticide", "weed", "कीट", "रोग", "इल्ली", "माहू", "फफूंद", "खरपतवार", "छिड़काव", "छिडकाव"),
    "livestock": ("cattle", "cow", "buffalo", "goat", "poultry", "milk", "animal", "fodder", "पशु", "गाय", "भैंस", "बकरी", "मुर्गी", "दूध", "चारा", "मवेशी"),
    "fish": ("fish", "pond", "मछली", "मत्स्य", "तालाब"),
    "horti": ("fruit", "vegetable", "mango", "guava", "tomato", "onion", "orchard", "फल", "सब्जी", "आम", "अमरूद", "अमरुद", "टमाटर", "प्याज"),
}
URGENT_WORDS = ("heavy rain", "very heavy", "cyclone", "hailstorm", "hail storm", "heat wave", "cold wave", "भारी वर्षा", "भारी बारिश", "चक्रवात", "ओलावृष्टि", "शीतलहर", "लू ")
ISSUER = re.compile(r"(?:K\.?\s?V\.?\s?K\.?|Krishi Vigyan Kendra|कृषि विज्ञान के(?:ं|न्)?द्र)[\s,:\-–]*([^\n।|]{2,70})", re.I)
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def classify(text: str) -> tuple[str, str]:
    low = text.lower()
    kind = next((k for k, words in KIND_WORDS.items() if any(w in low for w in words)), "general")
    severity = "warning" if any(w in low for w in URGENT_WORDS) else "info"
    return kind, severity


def language_of(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    return "hi" if letters and sum(1 for c in letters if DEVANAGARI.match(c)) > len(letters) / 3 else "en"


def crops_in(text: str) -> list[str]:
    """Crop keys named in the text, in English (mandi names too) or Hindi."""
    from rates.crops import CROPS, RULES
    from web.translations import TRANSLATIONS

    low = text.lower()
    found = [key for key, words in RULES if any(re.search(rf"\b{re.escape(w.strip('( '))}", low) for w in words)]
    for key, name in CROPS.items():
        hi = (TRANSLATIONS.get(name) or ("",))[0]
        if key not in found and (re.search(rf"\b{re.escape(name.lower())}\b", low) or (hi and len(hi) > 1 and hi in text)):
            found.append(key)
    return found[:6]


# --- places in Devanagari: a rough consonant skeleton is enough to tell districts apart -------------------
_DEV = {"क": "k", "ख": "k", "ग": "g", "घ": "g", "च": "c", "छ": "c", "ज": "j", "झ": "j", "ट": "t", "ठ": "t", "ड": "d", "ढ": "d", "ण": "n", "त": "t", "थ": "t",
        "द": "d", "ध": "d", "न": "n", "प": "p", "फ": "p", "ब": "b", "भ": "b", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "s", "ष": "s", "स": "s",
        "ह": "h", "ळ": "l", "ड़": "d", "ढ़": "d", "ज़": "j", "फ़": "p", "ं": "n", "ँ": "n"}


def _skeleton_dev(s: str) -> str:
    return "".join(_DEV.get(c, "") for c in s)


def _skeleton_latin(s: str) -> str:
    s = s.lower().replace("w", "v").replace("ph", "p").replace("bh", "b").replace("dh", "d").replace("th", "t").replace("kh", "k").replace("gh", "g").replace("ch", "c")
    s = s.replace("sh", "s").replace("z", "j").replace("q", "k").replace("x", "ks").replace("f", "p")
    return "".join(c for c in s if c.isalpha() and c not in "aeiou")


def _district_table():
    from extension import geo

    rows = []
    for st in geo.states():
        for d in geo.districts_of(st):
            rows.append((st, d, geo.norm(d), _skeleton_latin(d)))
    return rows


def locate(text: str) -> tuple[str, str, str]:
    """(state, district, issuer) from the KVK name in the text, e.g. 'KVK East Kameng' or 'कृषि विज्ञान केंद्र, पाहन्दा (अ), दुर्ग'."""
    from extension import geo

    m = None
    for m in ISSUER.finditer(text):
        pass  # the KVK's signature is usually at the end
    if not m:
        return "", "", ""
    tail = m.group(1).strip(" .,")
    issuer = m.group(0).strip(" .,")[:160]
    table = _district_table()
    parts = [p.strip(" ()") for p in re.split(r"[,()]", tail) if p.strip(" ()")]
    for part in reversed(parts):
        if DEVANAGARI.search(part):
            sk = _skeleton_dev(part)
            hits = [(st, d) for st, d, _, skl in table if len(sk) >= 3 and skl == sk]
        else:
            n = geo.norm(part)
            hits = [(st, d) for st, d, dn, _ in table if dn and (dn == n or n.endswith(dn) and len(dn) >= 4)]
        states = {st for st, _ in hits}
        if len(states) == 1:
            return hits[0][0], hits[0][1], issuer
    return "", "", issuer


def for_place(state: str, district: str, crops=None, days: int = 60, limit: int = 20) -> list:
    """Advisories that apply here: this district, or the whole state, or all of India; newest and most urgent first."""
    from extension.geo import same_district

    since = timezone.now() - timedelta(days=days)
    today = timezone.localdate()
    qs = (Advisory.objects.filter(published_at__gte=since).filter(Q(state__iexact=state or "-") | Q(state=""))
          .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).select_related("centre")[:400])
    rows = [a for a in qs if (not a.district or (district and same_district(a.district, district))) and (a.state or a.source != Advisory.Source.MKISAN)]
    crops = set(crops or [])
    rank = {"critical": 0, "warning": 1, "info": 2}
    rows.sort(key=lambda a: (rank[a.severity] if a.severity != "info" else 2, not (crops & set(a.crops or [])), -a.published_at.timestamp()))
    return rows[:limit]


def save_feed_item(source: str, external_id: str, text: str, published_at, author: str = "", designation: str = "", state: str = "", district: str = "",
                   issuer: str = "", severity: str = "", kind: str = "", url: str = "", valid_until=None, title: str = "") -> tuple[Advisory, bool]:
    k, sev = classify(text)
    if not (state or district):
        state, district, found = locate(text)
        issuer = issuer or found
    if not district and author:  # a scientist posts from one KVK: place them by their signed posts
        prev = Advisory.objects.filter(source=source, author=author).exclude(district="").first()
        if prev:
            state, district, issuer = prev.state, prev.district, issuer or prev.issuer
    from extension.scope import centre_for_place

    centre = centre_for_place(state, district) if district else None
    return Advisory.objects.get_or_create(external_id=external_id[:80], defaults={
        "source": source, "text": text[:4000], "published_at": published_at, "author": author[:120], "designation": designation[:120], "state": state, "district": district,
        "issuer": issuer[:160], "kind": kind or k, "severity": severity or sev, "crops": crops_in(text), "language": language_of(text), "url": url, "valid_until": valid_until,
        "title": title[:160], "centre": centre})


def place_by_author(source: str = "mkisan") -> int:
    """Give unplaced posts the district of the same scientist's signed posts."""
    n = 0
    for a in Advisory.objects.filter(source=source, district="").exclude(author=""):
        prev = Advisory.objects.filter(source=source, author=a.author).exclude(district="").first()
        if prev:
            Advisory.objects.filter(pk=a.pk).update(state=prev.state, district=prev.district, issuer=a.issuer or prev.issuer, centre=prev.centre)
            n += 1
    return n


def notify_district(a: Advisory, cap: int = 500) -> int:
    """Tell farmers (growers of the named crops first) and FPO/NGO staff in the advisory's district."""
    from extension.models import Centre
    from extension.scope import farmers as farmers_in, orgs as orgs_in
    from notify import service as notify
    from profiles.models import OrgMembership

    if not a.district:
        return 0
    centre = a.centre or Centre(state=a.state, districts=[a.district])
    rows = list(farmers_in(centre, a.district).select_related("user"))
    want = set(a.crops or [])
    rows.sort(key=lambda fp: not (want & set(fp.crops or [])))
    people = [fp.user for fp in rows]
    people += [m.user for m in OrgMembership.objects.filter(organisation__in=orgs_in(centre, a.district)).select_related("user")]
    seen, sent = set(), 0
    for u in people:
        if sent >= cap or u.pk in seen:
            continue
        seen.add(u.pk)
        notify.tell(u, "advisory", related=f"advisory:{a.pk}", title=a.issuer or "Seedha Bazar", url="/weather/", critical=a.severity == "critical",
                    centre=a.issuer or a.get_source_display(), place=a.district, advice=_short(a.title or a.text, 140), link=f"{settings.SITE_URL}/weather/")
        sent += 1
    Advisory.objects.filter(pk=a.pk).update(notified=a.notified + sent)
    return sent


def publish(centre, user, districts: list[str], text: str, title: str = "", kind: str = "", severity: str = "info", crops=None, valid_until=None, tell: bool = True) -> tuple[list, int]:
    """A KVK writes one advisory for one or more of its districts. Farmers there hear at once."""
    from accounts import audit

    k, _ = classify(text)
    out, sent = [], 0
    for d in districts:
        a = Advisory.objects.create(source=Advisory.Source.KVK, centre=centre, author=user.get_full_name() if hasattr(user, "get_full_name") else "", issuer=centre.name,
                                    state=centre.state, district=d, text=text, title=title, kind=kind or k, severity=severity, crops=list(crops or crops_in(text)),
                                    language=language_of(text), valid_until=valid_until, created_by=user)
        audit.log("advisory_published", actor=user, target=a)
        if tell:
            sent += notify_district(a)
        out.append(a)
    return out, sent


def _short(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def due(feed: str, hours: float, now=None) -> bool:
    from .models import FeedRun

    now = now or timezone.now()
    last = FeedRun.objects.filter(feed=feed).first()
    if last is None:
        return True
    if last.ok:
        return now - last.started_at >= timedelta(hours=hours) - timedelta(minutes=10)
    return now - last.started_at >= timedelta(hours=1)


def tick(now=None) -> dict:
    """Read the outside feeds that are due. Called by the worker."""
    from . import imd, mkisan

    out = {}
    if settings.MKISAN_ENABLED and due("mkisan", settings.ADVISORY_REFRESH_HOURS, now):
        out["mkisan"] = mkisan.sync()
    if settings.IMD_API_ENABLED and due("imd", 3, now):
        out["imd"] = imd.sync()
    return out
