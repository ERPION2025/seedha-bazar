from django.contrib import admin

from .models import Agreement, Deal, DealEvent, Offer, Payment


class OfferInline(admin.TabularInline):
    model = Offer
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


class EventInline(admin.TabularInline):
    model = DealEvent
    extra = 0


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ("pk", "product", "buyer", "seller", "organisation", "quantity", "unit", "price", "status", "delivery_by", "updated_at")
    list_filter = ("status", "product")
    inlines = [OfferInline, PaymentInline, EventInline]


@admin.register(Agreement)
class AgreementAdmin(admin.ModelAdmin):
    list_display = ("deal", "buyer_signed_at", "seller_signed_at", "doc_hash")
    readonly_fields = ("terms", "text", "doc_hash", "buyer_signed_at", "buyer_sign_ip", "buyer_sign_agent", "seller_signed_at", "seller_signer", "seller_sign_ip", "seller_sign_agent")
