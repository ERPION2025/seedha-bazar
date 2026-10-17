from django.contrib import admin

from .models import AuditEvent, Device, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("phone", "role", "status", "language", "date_joined")
    list_filter = ("role", "status", "language")
    search_fields = ("phone",)
    exclude = ("password", "pin_hash")


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "created_at", "last_used_at", "revoked_at")
    exclude = ("refresh_hash", "prev_refresh_hash")


@admin.register(AuditEvent)
class AuditAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "target_type", "target_id", "ip")
    list_filter = ("action",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


