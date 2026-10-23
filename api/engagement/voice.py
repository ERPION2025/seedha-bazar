"""What people talk about: topics and crops from their voice notes (and problems they raised), and content to match."""
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from knowledge import classify

LANGUAGES = [("hi-IN", "हिन्दी"), ("mr-IN", "मराठी"), ("en-IN", "English"), ("bn-IN", "বাংলা"), ("ta-IN", "தமிழ்"), ("te-IN", "తెలుగు"),
             ("gu-IN", "ગુજરાતી"), ("kn-IN", "ಕನ್ನಡ"), ("ml-IN", "മലയാളം"), ("pa-IN", "ਪੰਜਾਬੀ"), ("ur-IN", "اردو"), ("or-IN", "ଓଡ଼ିଆ")]
CODES = {c for c, _ in LANGUAGES}
KEEP_AUDIO_DAYS = 180


def analyse(text: str, text_en: str = "") -> tuple[list, list]:
    both = f"{text} {text_en}"
    topics = [t for t in classify.topics_of(both) if t != "farming"]
    return topics, classify.crops_of(both)


def interests(user, days: int = 90) -> dict:
    """{'topics': [(topic, n)], 'crops': [(crop, n)]} from voice notes and problems raised in the last `days`."""
    from issues.models import Issue

    from .models import VoiceNote

    since = timezone.now() - timedelta(days=days)
    t, c = Counter(), Counter()
    for v in VoiceNote.objects.filter(user=user, created_at__gte=since):
        t.update(v.topics)
        c.update(v.crops)
    for i in Issue.objects.filter(raised_by=user, created_at__gte=since):
        topics, crops = analyse(i.description)
        t.update(topics)
        c.update(crops + ([i.crop] if i.crop else []))
    return {"topics": t.most_common(5), "crops": c.most_common(5)}


def for_you(user, lang: str, limit: int = 6) -> dict:
    """News, schemes, videos and value-add pages about what the person talks about most."""
    from knowledge import services as k

    it = interests(user)
    topics = [x for x, _ in it["topics"]]
    crops = [x for x, _ in it["crops"]]
    news, seen = [], set()
    for topic in topics[:3]:
        for a in k.ranked_articles(user, lang, topic=topic, limit=4)[0]:
            if a.pk not in seen:
                seen.add(a.pk)
                news.append(a)
    for crop in crops[:2]:
        for a in k.ranked_articles(user, lang, crop=crop, limit=3)[0]:
            if a.pk not in seen:
                seen.add(a.pk)
                news.append(a)
    scheme_topics = {"insurance": "insurance", "credit": "credit", "price": "market", "processing": "processing", "fpo": "fpo_benefit", "market": "market", "inputs": "inputs"}
    schemes = []
    for topic in topics:
        for s in k.schemes_for(getattr(user, "role", ""), scheme_topics.get(topic, ""))[:2] if topic in scheme_topics else []:
            if s not in schemes:
                schemes.append(s)
    videos = []
    for topic in topics[:2]:
        videos += [v for v in k.videos_for(lang, topic=topic, limit=2) if v not in videos]
    return {"interests": it, "news": news[:limit], "schemes": schemes[:3], "videos": videos[:3], "crops": crops}


def notify_new_matches(now=None) -> int:
    """Once a day: tell people about one new headline on the topic they talk about most (if any arrived in the last day)."""
    from knowledge.models import Article
    from notify import service as notify
    from web.i18n import tr

    from .models import VoiceNote

    now = now or timezone.now()
    sent = 0
    users = {v.user for v in VoiceNote.objects.filter(created_at__gte=now - timedelta(days=90)).select_related("user")}
    for u in users:
        it = interests(u)
        if not it["topics"] and not it["crops"]:
            continue
        top_t = [t for t, _ in it["topics"][:2]]
        top_c = [c for c, _ in it["crops"][:2]]
        fresh = Article.objects.filter(hidden=False, fetched_at__gte=now - timedelta(days=1)).order_by("-score")[:200]
        hit = next((a for a in fresh if set(a.topics) & set(top_t) or set(a.crops) & set(top_c)), None)
        if hit:
            notify.tell(u, "interest_news", related=f"article:{hit.pk}", url="/voice/", title=tr(u.language, "For you"), headline=hit.title[:120],
                        link=f"{settings.SITE_URL}/voice/")
            sent += 1
    return sent


def purge_audio(days: int = KEEP_AUDIO_DAYS) -> int:
    from .models import VoiceNote

    n = 0
    for v in VoiceNote.objects.filter(created_at__lt=timezone.now() - timedelta(days=days)).exclude(audio=""):
        v.audio.delete(save=False)
        v.audio = ""
        v.save(update_fields=["audio"])
        n += 1
    return n
