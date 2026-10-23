from django.contrib import admin

from .models import Advisory, FeedRun


@admin.register(Advisory)
class AdvisoryAdmin(admin.ModelAdmin):
    list_display = ("published_at", "source", "state", "district", "kind", "severity", "issuer", "notified")
    list_filter = ("source", "kind", "severity", "state")
    search_fields = ("text", "issuer", "author", "district")


@admin.register(FeedRun)
class FeedRunAdmin(admin.ModelAdmin):
    list_display = ("feed", "started_at", "ok", "fetched", "saved", "error")
    list_filter = ("feed", "ok")
