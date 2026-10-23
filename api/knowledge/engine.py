"""The research engine: reads public feeds on a schedule, keeps what is about farming, tags it, and drops the rest.

It stores a headline, a short snippet, the link, the outlet and tags (topic, crop, state). It never copies articles.
One feed failing never stops the others; every source records when it last worked and what went wrong.
"""
import hashlib
import logging
import re
import urllib.request
from datetime import datetime, timedelta, timezone as dt_tz

import feedparser
from django.conf import settings
from django.utils import timezone

from config.netutil import ssl_context

from . import classify
from .models import Article, Source, Video
from .sources import feed_url

log = logging.getLogger("seedha.knowledge")
USER_AGENT = getattr(settings, "GEOCODER_USER_AGENT", "SeedhaBazar/1.0") + " (news reader; contact via site)"
MAX_BYTES = 4_000_000
KEEP_DAYS = 60
NORMAL = re.compile(r"[^\wऀ-ॿ]+")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=25, context=ssl_context()) as r:  # noqa: S310 - fixed https feed addresses
        return r.read(MAX_BYTES)


def title_key(title: str) -> str:
    return hashlib.sha1(NORMAL.sub(" ", title.lower()).strip()[:90].encode()).hexdigest()[:20]


def _when(entry) -> datetime:
    for field in ("published_parsed", "updated_parsed"):
        t = entry.get(field)
        if t:
            return datetime(*t[:6], tzinfo=dt_tz.utc)
    return timezone.now()


def _split_outlet(title: str, entry) -> tuple[str, str]:
    """Google News writes 'Headline - Outlet'. Return (headline, outlet)."""
    outlet = (entry.get("source") or {}).get("title", "") if hasattr(entry.get("source", {}), "get") else ""
    if outlet and title.endswith(" - " + outlet):
        title = title[: -len(outlet) - 3]
    elif " - " in title and not outlet:
        head, _, tail = title.rpartition(" - ")
        if 2 < len(tail) < 40:
            title, outlet = head, tail
    return title.strip(), outlet.strip()


def ingest_articles(source: Source, parsed, now=None) -> int:
    now = now or timezone.now()
    kept = 0
    recent_keys = set(Article.objects.filter(published_at__gte=now - timedelta(days=14)).values_list("title_key", flat=True))
    for entry in parsed.entries[:120]:
        link = (entry.get("link") or "").strip()
        raw_title = classify.clean_text(entry.get("title", ""), 300)
        if not link or not raw_title:
            continue
        title, outlet = _split_outlet(raw_title, entry)
        summary = classify.clean_text(entry.get("summary", ""), 300)
        if summary.startswith(raw_title) or summary.startswith(title):  # Google News repeats the headline as the snippet
            summary = ""
        published = min(_when(entry), now)
        s, topics, crops = classify.score(title, summary, source.trust, published, now)
        if s < classify.MIN_SCORE:
            continue
        key = title_key(title)
        if key in recent_keys or Article.objects.filter(url=link).exists():
            continue
        Article.objects.create(
            source=source, outlet=outlet or source.name, title=title, summary=summary, url=link[:700], title_key=key, published_at=published, language=classify.language_of(title, source.language),
            state=classify.state_of(f"{title} {summary}", source.state), crops=crops, topics=[t for t in topics if t != "farming"] or ["farming"], score=s)
        recent_keys.add(key)
        kept += 1
    return kept


def ingest_videos(source: Source, parsed) -> int:
    kept = 0
    for entry in parsed.entries[:15]:
        vid = entry.get("yt_videoid") or ""
        if not vid:
            continue
        title = classify.clean_text(entry.get("title", ""), 300)
        text = f"{title} {classify.clean_text(entry.get('summary', ''), 400)}"
        _, created = Video.objects.get_or_create(
            platform="youtube", video_id=vid,
            defaults={"source": source, "title": title, "channel": parsed.feed.get("title", source.name)[:120], "language": source.language, "published_at": _when(entry),
                      "state": classify.state_of(text, source.state), "crops": classify.crops_of(text), "topics": [t for t in classify.topics_of(text) if t != "farming"]})
        kept += created
    return kept


def run_source(source: Source, now=None) -> int:
    now = now or timezone.now()
    source.last_run = now
    try:
        parsed = feedparser.parse(fetch(feed_url(source)))
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"unreadable feed: {parsed.bozo_exception}")
        added = ingest_videos(source, parsed) if source.kind == Source.Kind.YOUTUBE else ingest_articles(source, parsed, now)
        source.last_ok, source.last_error, source.last_count = now, "", len(parsed.entries)
        return added
    except Exception as e:  # one broken feed must not stop the rest
        source.last_error = f"{type(e).__name__}: {e}"[:300]
        log.warning("news source %s failed: %s", source.name, source.last_error)
        return 0
    finally:
        source.save(update_fields=["last_run", "last_ok", "last_error", "last_count"])


def prune(now=None) -> int:
    now = now or timezone.now()
    n, _ = Article.objects.filter(published_at__lt=now - timedelta(days=KEEP_DAYS)).delete()
    return n


def run_all(only: int | None = None) -> dict:
    qs = Source.objects.filter(active=True)
    if only:
        qs = qs.filter(pk=only)
    added = failed = 0
    for src in qs:
        before = src.last_error
        added += run_source(src)
        failed += bool(src.last_error)
    return {"sources": qs.count(), "added": added, "failed": failed, "pruned": prune()}


def due(now=None) -> bool:
    now = now or timezone.now()
    last = Source.objects.filter(active=True, last_run__isnull=False).order_by("-last_run").values_list("last_run", flat=True).first()
    return last is None or now - last >= timedelta(hours=getattr(settings, "NEWS_REFRESH_HOURS", 6))
