from django.contrib import admin

from .models import FeeRule, Inbound, Invoice, Order, OrderLine, Product, ProductPhoto, Review, SellerSettings, Shipment, StockMove


class LineInline(admin.TabularInline):
    model = OrderLine
    extra = 0
    raw_id_fields = ("product", "seller")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "created_at", "buyer", "city", "status", "payment", "paid", "total")
    list_filter = ("status", "payment", "paid", "channel")
    search_fields = ("number", "phone", "city")
    inlines = [LineInline]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "seller", "asked_price", "price", "stock", "status")
    list_filter = ("status", "category")
    search_fields = ("title", "origin")


admin.site.register(FeeRule)
admin.site.register(StockMove)

admin.site.register(SellerSettings)
admin.site.register(Inbound)
admin.site.register(Shipment)
admin.site.register(Invoice)
admin.site.register(ProductPhoto)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("created_at", "product", "stars", "title", "hidden")
    list_filter = ("stars", "hidden")
    search_fields = ("title", "text")
