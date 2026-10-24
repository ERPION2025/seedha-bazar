from django.contrib import admin

from .models import Application, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("scheme", "state", "season", "group", "crop", "farmer_share_pct", "sum_insured_per_ha", "cutoff_date", "insurer", "notified", "active")
    list_filter = ("scheme", "state", "season", "notified", "active")
    search_fields = ("crop", "insurer", "state")


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("farmer", "crop", "season", "year", "district", "sum_insured", "farmer_premium", "status", "application_no", "policy_no", "updated_at")
    list_filter = ("status", "season", "state", "channel")
    search_fields = ("farmer__phone", "application_no", "policy_no", "district")
