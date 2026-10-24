from django.contrib import admin

from .models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "name", "phone", "city", "language")
    list_filter = ("kind", "language")
    search_fields = ("name", "phone", "city")
