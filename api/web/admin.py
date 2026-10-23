from django.contrib import admin

from .models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "name", "phone", "city", "language")
    list_filter = ("kind", "language")
    search_fields = ("name", "phone", "city")


# "All records" for the owner: every model can be searched, changed or removed here, including those without their own page.
admin.site.site_header = "Seedha Bazar – All records"
admin.site.site_title = "Seedha Bazar records"
admin.site.index_title = "Every record, for the owner and admins"


def _register_the_rest():
    from django.apps import apps
    from django.db import models as m

    for model in apps.get_models():
        if admin.site.is_registered(model) or model._meta.app_label in ("contenttypes", "sessions", "admin"):
            continue
        fields = [f for f in model._meta.concrete_fields if not isinstance(f, (m.TextField, m.JSONField, m.FileField))]
        text = [f.name for f in fields if isinstance(f, (m.CharField, m.EmailField)) and not f.choices][:4]
        fks = [f.name for f in fields if isinstance(f, m.ForeignKey)]
        attrs = {"list_display": [f.name for f in fields][:7], "search_fields": text, "raw_id_fields": fks,
                 "list_filter": [f.name for f in fields if f.choices or isinstance(f, m.BooleanField)][:4]}
        admin.site.register(model, type(f"{model.__name__}Admin", (admin.ModelAdmin,), attrs))


_register_the_rest()
