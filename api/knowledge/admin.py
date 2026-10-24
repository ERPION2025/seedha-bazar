from django.contrib import admin

from .models import Announcement, Article, Scheme, Source, Video


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "language", "state", "trust", "active", "last_run", "last_error")
    list_filter = ("kind", "language", "active")
    list_editable = ("trust", "active")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "outlet", "language", "state", "score", "published_at", "hidden")
    list_filter = ("language", "hidden", "source")
    search_fields = ("title", "outlet")
    list_editable = ("hidden",)


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "channel", "language", "featured", "hidden", "published_at")
    list_filter = ("language", "featured", "hidden")
    list_editable = ("featured", "hidden")


@admin.register(Scheme)
class SchemeAdmin(admin.ModelAdmin):
    list_display = ("name", "level", "state", "active", "last_checked", "sort")
    list_editable = ("active", "sort")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "language", "state", "district", "pinned", "starts_at", "ends_at")
