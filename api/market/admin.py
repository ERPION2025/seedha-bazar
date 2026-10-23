from django.contrib import admin

from .models import Enquiry, EnquiryMessage, Listing


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("crop", "quantity", "unit", "price", "district", "status", "seller", "created_at")
    list_filter = ("status", "state", "crop")
    search_fields = ("crop", "district", "seller__phone")


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ("listing", "buyer", "status", "created_at", "unlocked_at")
    list_filter = ("status",)


admin.site.register(EnquiryMessage)
