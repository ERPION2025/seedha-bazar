from django.contrib import admin

from .models import Message, OptOut


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "channel", "phone", "template", "status", "provider")
    list_filter = ("channel", "status", "template")
    search_fields = ("phone", "text")
    readonly_fields = [f.name for f in Message._meta.fields]


admin.site.register(OptOut)
