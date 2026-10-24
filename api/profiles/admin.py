from django.contrib import admin

from .models import BuyerProfile, FarmerProfile, OrgLinkRequest, Organisation, OrgMembership


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "district", "block", "verified", "code")
    list_filter = ("kind", "verified", "district")
    search_fields = ("name", "code")


@admin.register(OrgMembership)
class OrgMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organisation", "role")


@admin.register(FarmerProfile)
class FarmerProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "village", "district", "organisation", "org_status", "level")
    list_filter = ("district", "org_status", "level", "land_record_verified", "documents_verified")
    search_fields = ("name", "user__phone", "village")
    readonly_fields = ("level",)


@admin.register(BuyerProfile)
class BuyerProfileAdmin(admin.ModelAdmin):
    list_display = ("business_name", "business_type", "city", "user", "level")
    list_filter = ("business_type", "level", "documents_verified")
    readonly_fields = ("level",)


admin.site.register(OrgLinkRequest)
