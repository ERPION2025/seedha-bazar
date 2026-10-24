"""The mKisan advisory feed (mkisan.gov.in/Home/Advisory): short advisories KVK scientists across India post for farmers.

The page lists the latest posts (about a thousand) with the scientist's name, role, time and text. It carries no district,
so the KVK's own signature in the text ("KVK East Kameng", "कृषि विज्ञान केंद्र, ..., दुर्ग") is used to place each post.
Posts that cannot be placed are kept for KVK staff, but not shown to farmers.
"""
import hashlib
import html
import logging
import re
import urllib.request
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from config.netutil import ssl_context

from .models import FeedRun
from .services import save_feed_item

log = logging.getLogger("seedha.advisory")
POST = re.compile(r'<div class="post">(.*?)<input', re.S)
NAME = re.compile(r'class="username">\s*<a[^>]*>(.*?)</a>\s*<span class="small">\((.*?)\)</span>', re.S)
WHEN = re.compile(r"Shared on - ([\d/]+ [\d:]+ [AP]M)")
BODY = re.compile(r"<!-- /.user-block -->\s*<p>(.*?)</p>", re.S)


def fetch() -> str:
    req = urllib.request.Request(settings.MKISAN_ADVISORY_URL, headers={"User-Agent": "SeedhaBazar/1.0 (+https://seedhabazar.in)"})
    with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as resp:
        return resp.read().decode("utf-8", "replace")


def _clean(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def parse(page: str) -> list[dict]:
    out = []
    for block in POST.findall(page):
        name, when, body = NAME.search(block), WHEN.search(block), BODY.search(block)
        text = _clean(body.group(1)) if body else ""
        if not (when and len(text) >= 20):
            continue  # posts with only a picture or a file carry nothing we can show
        try:
            at = timezone.make_aware(datetime.strptime(when.group(1), "%m/%d/%Y %I:%M:%S %p"))
        except ValueError:
            continue
        out.append({"author": _clean(name.group(1)) if name else "", "designation": _clean(name.group(2)) if name else "", "published_at": at, "text": text})
    return out


def sync(page: str | None = None) -> dict:
    run = FeedRun.objects.create(feed="mkisan")
    try:
        rows = parse(page if page is not None else fetch())
        saved = 0
        for r in rows:
            key = "mk:" + hashlib.sha1(f"{r['author']}|{r['published_at'].isoformat()}|{r['text'][:300]}".encode()).hexdigest()[:40]
            _, created = save_feed_item("mkisan", key, r["text"], r["published_at"], author=r["author"], designation=r["designation"], url=settings.MKISAN_ADVISORY_URL)
            saved += created
        from .services import place_by_author
        place_by_author("mkisan")
        run.ok, run.fetched, run.saved = True, len(rows), saved
    except Exception as e:  # the feed is a public page; it can change or go down
        log.warning("mKisan advisory feed failed: %s", e)
        run.error = f"{type(e).__name__}: {e}"[:300]
    run.finished_at = timezone.now()
    run.save()
    return {"ok": run.ok, "fetched": run.fetched, "saved": run.saved}
