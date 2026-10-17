from django.contrib import admin

from .models import Activity, CropCycle, Expense, Harvest, Plot, Sale

for m in (Plot, CropCycle, Activity, Expense, Harvest, Sale):
    admin.site.register(m)
