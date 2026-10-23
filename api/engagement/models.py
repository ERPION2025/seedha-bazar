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
