from django.contrib import admin

from .models import CropGroup, CropGroupMember


class MemberInline(admin.TabularInline):
    model = CropGroupMember
    extra = 0
    raw_id_fields = ("farmer", "crop_cycle")


@admin.register(CropGroup)
class CropGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "crop", "season", "year", "district", "state", "status", "organisation", "centre")
    list_filter = ("status", "season", "state")
    search_fields = ("name", "district", "village")
    inlines = [MemberInline]
