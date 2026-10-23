from django.contrib import admin

from .models import MarketRate, MspPrice, RateAlert, RateFetchLog


@admin.register(MarketRate)
class MarketRateAdmin(admin.ModelAdmin):
    list_display = ("date", "commodity", "market", "district", "state", "modal_price", "source")
    list_filter = ("source", "state", "crop")
    search_fields = ("commodity", "market", "district")
    date_hierarchy = "date"


@admin.register(RateFetchLog)
class RateFetchLogAdmin(admin.ModelAdmin):
    list_display = ("started_at", "source", "status", "rows_fetched", "rows_saved", "latest_date", "message")


@admin.register(MspPrice)
class MspPriceAdmin(admin.ModelAdmin):
    list_display = ("crop", "name", "season", "price_per_quintal", "announced_on")
    list_filter = ("season",)


admin.site.register(RateAlert)
