from django.conf import settings
from django.db import models
from django.utils import timezone


class GamePlay(models.Model):
    """One finished game. Points are the score capped per game, so no single game can dominate the leaderboard."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="game_plays")
    game = models.CharField(max_length=20, db_index=True)
    score = models.PositiveIntegerField()
    points = models.PositiveIntegerField()
    used_voice = models.BooleanField(default=False)
    district = models.CharField(max_length=80, blank=True, db_index=True)
    state = models.CharField(max_length=60, blank=True)
    played_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-played_at"]


def share_path(instance, filename):
    return f"public/share/{instance.code}.png"


class ShareCard(models.Model):
    """A free self-ad: a branded picture and a link a farmer, FPO or buyer posts on WhatsApp, Facebook or Instagram.

    The picture is drawn on the phone (so Hindi and Marathi text is shaped correctly) and uploaded, so link previews show it too.
    """

    class Kind(models.TextChoices):
        LISTING = "listing", "Produce for sale"
        LOT = "lot", "FPO group lot"
        STOCK = "stock", "My stock"
        SCORE = "score", "Game score"
        ACHIEVEMENT = "achievement", "Achievement"

    code = models.CharField(max_length=12, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="share_cards")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    ref = models.CharField(max_length=40, blank=True)
    title = models.CharField(max_length=160)
    lines = models.JSONField(default=list)
    target = models.CharField(max_length=300, help_text="Where the link leads after the landing page")
    image = models.FileField(upload_to=share_path, blank=True)
    language = models.CharField(max_length=2, default="hi")
    views = models.PositiveIntegerField(default=0)
    signups = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]


def voice_path(instance, filename):
    import uuid
    return f"private/voice/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.webm"


class VoiceNote(models.Model):
    """Something a person said to Seedha Bazar: the text (made on the phone, or on the server with Bhashini), the language,
    the topics and crops found in it, and (only if they agreed) the recording. Recordings are deleted after 180 days."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="voice_notes")
    language = models.CharField(max_length=8, help_text="BCP-47 tag, e.g. hi-IN, ta-IN")
    text = models.TextField(max_length=4000, blank=True)
    text_en = models.TextField(max_length=4000, blank=True, help_text="English translation, when Bhashini is set up (used to find topics)")
    audio = models.FileField(upload_to=voice_path, blank=True)
    topics = models.JSONField(default=list, blank=True)
    crops = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=10, default="phone", help_text="phone (browser speech) or bhashini (server)")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)


class VoiceConsent(models.Model):
    """The person's yes to using the microphone, and whether recordings may be kept. Asked once; can be withdrawn."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="voice_consent")
    keep_audio = models.BooleanField(default=False)
    given_at = models.DateTimeField(default=timezone.now)
    version = models.CharField(max_length=20, default="2026-10-v1")
