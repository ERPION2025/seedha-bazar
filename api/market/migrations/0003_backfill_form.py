from django.db import migrations


def backfill(apps, schema_editor):
    from catalog import kind

    Listing = apps.get_model("market", "Listing")
    for li in Listing.objects.all():
        k = kind(li.crop)
        if li.form != k:
            li.form = k
            li.save(update_fields=["form"])


class Migration(migrations.Migration):
    dependencies = [("market", "0002_listing_brand_listing_form_listing_fssai_no_and_more")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
