from django.contrib import admin

from .models import BuyerProfile, FarmerProfile, OrgLinkRequest, Organisation, OrgMembership


admin.site.site_header = "Seedha Bazar admin"
admin.site.site_url = "/console/"  # the "View site" link opens the staff console, where FPOs are approved


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "district", "block", "verified", "code", "created_at")
    list_filter = ("verified", "kind", "district")
    list_editable = ("verified",)
    ordering = ("verified", "-created_at")  # waiting for approval first
    search_fields = ("name", "code")
    actions = ["approve", "unapprove"]

    @admin.action(description="Approve selected FPOs/NGOs")
    def approve(self, request, queryset):
        n = queryset.update(verified=True)
        self.message_user(request, f"{n} approved.")

    @admin.action(description="Remove approval from selected")
    def unapprove(self, request, queryset):
        n = queryset.update(verified=False)
        self.message_user(request, f"{n} set to not approved.")


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
