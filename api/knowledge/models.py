from django.conf import settings
from django.db import models
from django.utils import timezone

AUDIENCES = [("farmer", "Farmers"), ("fpo", "FPOs and NGOs"), ("buyer", "Buyers")]


class Source(models.Model):
    """Somewhere the engine reads from: a news feed, a search feed, or a video channel. Staff can add more."""

    class Kind(models.TextChoices):
        RSS = "rss", "News feed (RSS)"
        SEARCH = "search", "News search (Google News)"
        YOUTUBE = "youtube", "YouTube channel"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.RSS)
    url = models.CharField(max_length=500, help_text="Feed address. For a search, the search words. For YouTube, the channel id (starts with UC).")
    language = models.CharField(max_length=2, default="en")
    state = models.CharField(max_length=60, blank=True, help_text="Blank for the whole country")
    trust = models.PositiveSmallIntegerField(default=3, help_text="1 to 5. Government and institute sources rank higher.")
    active = models.BooleanField(default=True)
    last_run = models.DateTimeField(null=True, blank=True)
    last_ok = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    last_count = models.PositiveIntegerField(default=0, help_text="Items read on the last run")

    class Meta:
        ordering = ["-trust", "name"]
        constraints = [models.UniqueConstraint(fields=["kind", "url", "language"], name="uniq_source")]

    def __str__(self):
        return self.name


class Article(models.Model):
    """One news item. Only the headline, a short snippet and the link are kept; the reader goes to the source for the rest."""

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="articles")
    outlet = models.CharField(max_length=120, blank=True, help_text="Who published it, when the feed says so")
    title = models.CharField(max_length=300)
    summary = models.CharField(max_length=320, blank=True)
    url = models.URLField(max_length=700, unique=True)
    title_key = models.CharField(max_length=40, db_index=True)
    published_at = models.DateTimeField(db_index=True)
    fetched_at = models.DateTimeField(default=timezone.now)
    language = models.CharField(max_length=2, default="en")
    state = models.CharField(max_length=60, blank=True, db_index=True)
    crops = models.JSONField(default=list, blank=True)
    topics = models.JSONField(default=list, blank=True)
    score = models.IntegerField(default=0, db_index=True)
    hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ["-published_at"]


class Video(models.Model):
    """A video farmers can watch inside the app. YouTube plays through the privacy-friendly embed, and only after a tap (saves data)."""

    class Platform(models.TextChoices):
        YOUTUBE = "youtube", "YouTube"
        FILE = "file", "Video file (direct link)"

    source = models.ForeignKey(Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="videos")
    title = models.CharField(max_length=300)
    platform = models.CharField(max_length=10, choices=Platform.choices, default=Platform.YOUTUBE)
    video_id = models.CharField(max_length=40, blank=True, help_text="YouTube video id")
    file_url = models.URLField(max_length=700, blank=True, help_text="Direct link to an .mp4 file")
    channel = models.CharField(max_length=120, blank=True)
    language = models.CharField(max_length=2, default="hi")
    state = models.CharField(max_length=60, blank=True)
    crops = models.JSONField(default=list, blank=True)
    topics = models.JSONField(default=list, blank=True)
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    featured = models.BooleanField(default=False)
    hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ["-featured", "-published_at"]
        constraints = [models.UniqueConstraint(fields=["platform", "video_id"], condition=~models.Q(video_id=""), name="uniq_video")]

    @property
    def watch_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}" if self.platform == "youtube" else self.file_url

    @property
    def embed_url(self) -> str:
        return f"https://www.youtube-nocookie.com/embed/{self.video_id}?autoplay=1&rel=0" if self.platform == "youtube" else ""

    @property
    def thumbnail(self) -> str:
        return f"https://i.ytimg.com/vi/{self.video_id}/hqdefault.jpg" if self.platform == "youtube" else ""


class Scheme(models.Model):
    """A government scheme, written for a farmer or an FPO. Summaries for orientation only: the official page is the rule."""

    class Level(models.TextChoices):
        CENTRAL = "central", "Central"
        STATE = "state", "State"

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=160)
    level = models.CharField(max_length=8, choices=Level.choices, default=Level.CENTRAL)
    state = models.CharField(max_length=60, blank=True, help_text="For a state scheme")
    agency = models.CharField(max_length=160, blank=True)
    audience = models.JSONField(default=list, help_text="farmer, fpo, ngo")
    topics = models.JSONField(default=list, help_text="e.g. bulk_purchase, fpo_benefit, insurance, credit, processing, storage, income, inputs, market")
    short = models.CharField(max_length=240, help_text="One line: what you get")
    benefit = models.TextField()
    eligibility = models.TextField(blank=True)
    how_to_apply = models.TextField(blank=True)
    documents = models.TextField(blank=True, help_text="One per line")
    portal_url = models.URLField(blank=True)
    helpline = models.CharField(max_length=60, blank=True)
    i18n = models.JSONField(default=dict, blank=True, help_text='{"hi": {"name": "", "short": "", "benefit": "", "eligibility": "", "how_to_apply": "", "documents": ""}, "mr": {...}}')
    last_checked = models.DateField(null=True, blank=True, help_text="When staff last compared this with the official page")
    active = models.BooleanField(default=True)
    sort = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["sort", "name"]

    def text(self, field: str, lang: str) -> str:
        return (self.i18n.get(lang) or {}).get(field) or getattr(self, field)


class Announcement(models.Model):
    """A note from Seedha Bazar staff to the people who sign in. Shows at the top of their home page and in News."""

    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    link = models.URLField(blank=True)
    audience = models.CharField(max_length=8, default="all", choices=[("all", "Everyone")] + AUDIENCES)
    language = models.CharField(max_length=2, blank=True, help_text="Blank to show in every language")
    state = models.CharField(max_length=60, blank=True)
    district = models.CharField(max_length=80, blank=True)
    pinned = models.BooleanField(default=False)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-pinned", "-starts_at"]
