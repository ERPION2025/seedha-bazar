import re
from decimal import Decimal

from django import forms
from django.utils import timezone

from accounts.models import Language
from accounts.phone import InvalidPhone, normalise_phone
from farmerbook.models import Activity, CropCycle, Expense, Harvest, Sale
from farmerbook.units import UNITS
from market.models import Listing
from profiles.models import BuyerProfile, Organisation

from .i18n import tr

import catalog  # noqa: E402
from rates.crops import CROPS  # noqa: E402

UNIT_LABELS = [("quintal", "Quintal"), ("kg", "Kg"), ("tonne", "Tonne"), ("bag", "Bag")]
assert set(UNITS) == {u for u, _ in UNIT_LABELS}


def crop_label(lang: str, value: str) -> str:
    return tr(lang, catalog.name(value))


def today():
    return timezone.localdate()


class LangForm(forms.Form):
    """A form whose dropdown choices are shown in the visitor's language."""

    def __init__(self, *args, lang="hi", **kwargs):
        super().__init__(*args, **kwargs)
        self.lang = lang
        for f in self.fields.values():
            if getattr(f, "choices", None):
                f.choices = [(v, tr(lang, label)) for v, label in f.choices]


def date_field(label, required=True, initial=None):
    return forms.DateField(label=label, required=required, initial=initial, widget=forms.DateInput(attrs={"type": "date"}))


def split_crops(chosen, other: str) -> list[str]:
    out = [c for c in chosen]
    for part in (other or "").replace("،", ",").split(","):
        part = part.strip().lower()[:40]
        if part and part not in out:
            out.append(part)
    return out[:20]


class PhoneForm(LangForm):
    phone = forms.CharField(label="Mobile number", max_length=20, widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel", "placeholder": "98XXXXXXXX", "autofocus": True}))

    def clean_phone(self):
        try:
            return normalise_phone(self.cleaned_data["phone"])
        except InvalidPhone:
            raise forms.ValidationError("Enter a valid 10-digit Indian mobile number")


class CodeForm(LangForm):
    code = forms.CharField(label="6-digit code", max_length=12, widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "autofocus": True}))


class ConsentForm(LangForm):
    consent = forms.BooleanField(label="I agree to the privacy notice and allow Seedha Bazar to keep my details", error_messages={"required": "Please tick the box to continue"})


class FarmerProfileForm(LangForm):
    name = forms.CharField(label="Your name", max_length=120)
    village = forms.CharField(label="Village", max_length=120)
    block = forms.CharField(label="Block (tehsil)", max_length=80, required=False)
    district = forms.CharField(label="District", max_length=80)
    land_acres = forms.DecimalField(label="Land you farm (acres)", min_value=Decimal("0.01"), max_value=Decimal("100000"), decimal_places=2, widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}))
    crops = forms.MultipleChoiceField(label="What do you grow?", choices=list(CROPS.items()), required=False, widget=forms.CheckboxSelectMultiple(attrs={"class": "chips"}))
    other_crops = forms.CharField(label="Other crops (separate with commas)", max_length=120, required=False)
    discoverable = forms.BooleanField(label="Let verified buyers see my first name, village, crops and stock, and ask me for produce. My phone number stays hidden.", required=False, initial=True)
    share_with_extension = forms.BooleanField(label="Let my district's KVK or research centre see my profile, crops and Farmer Book, to advise me and offer seeds and inputs.", required=False)

    @classmethod
    def from_profile(cls, fp, lang):
        known = [c for c in fp.crops if c in CROPS]
        other = ", ".join(c for c in fp.crops if c not in CROPS)
        return cls(lang=lang, initial={"name": fp.name, "village": fp.village, "block": fp.block, "district": fp.district,
                                       "land_acres": fp.land_acres, "crops": known, "other_crops": other, "discoverable": fp.discoverable,
                                       "share_with_extension": bool(fp.share_with_extension)})

    def clean(self):
        data = super().clean()
        if not split_crops(data.get("crops") or [], data.get("other_crops")):
            self.add_error("crops", "Pick at least one crop")
        return data


class FpoRegisterForm(LangForm):
    contact_name = forms.CharField(label="Your name", max_length=120)
    name = forms.CharField(label="FPO / NGO name", max_length=160)
    kind = forms.ChoiceField(label="Type", choices=[("fpo", "FPO (farmer producer company)"), ("ngo", "NGO")])
    district = forms.CharField(label="District", max_length=80)
    block = forms.CharField(label="Block (tehsil)", max_length=80, required=False)
    registration_no = forms.CharField(label="Registration number (if you have it)", max_length=60, required=False)


class AddFarmerForm(LangForm):
    phone = forms.CharField(label="Farmer's mobile number", max_length=20, widget=forms.TextInput(attrs={"inputmode": "tel", "placeholder": "98XXXXXXXX"}))
    name = forms.CharField(label="Farmer's name", max_length=120)
    village = forms.CharField(label="Village", max_length=120)
    block = forms.CharField(label="Block (tehsil)", max_length=80, required=False)
    district = forms.CharField(label="District", max_length=80)
    land_acres = forms.DecimalField(label="Land (acres)", required=False, min_value=Decimal("0.01"), max_value=Decimal("100000"), decimal_places=2, widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}))
    crops = forms.MultipleChoiceField(label="Crops", choices=list(CROPS.items()), required=False, widget=forms.CheckboxSelectMultiple(attrs={"class": "chips"}))
    other_crops = forms.CharField(label="Other crops (separate with commas)", max_length=120, required=False)
    language = forms.ChoiceField(label="Farmer's language", choices=[("hi", "Hindi"), ("mr", "Marathi"), ("en", "English")], initial="hi")
    contact_is_family = forms.BooleanField(label="This number belongs to a family member", required=False)
    family_contact_name = forms.CharField(label="Family member's name", max_length=120, required=False)

    def clean_phone(self):
        try:
            return normalise_phone(self.cleaned_data["phone"])
        except InvalidPhone:
            raise forms.ValidationError("Enter a valid 10-digit Indian mobile number")


class BulkFarmersForm(LangForm):
    lines = forms.CharField(label="One farmer per line", widget=forms.Textarea(attrs={"rows": 8, "placeholder": "98XXXXXXXX, Ramesh Kushwaha, Naigarhi, Rewa, 3.5, wheat kodo"}), max_length=8000)


class JoinCodeForm(LangForm):
    code = forms.CharField(label="FPO code", max_length=20, widget=forms.TextInput(attrs={"autocapitalize": "none", "placeholder": "naigarhi"}))


class NewCropForm(LangForm):
    crop = forms.ChoiceField(label="Crop", choices=list(CROPS.items()) + [("other", "Other")])
    crop_other = forms.CharField(label="Crop name", max_length=60, required=False)
    field_name = forms.CharField(label="Field name", max_length=80, initial="My field")
    area_acres = forms.DecimalField(label="Area (acres)", min_value=Decimal("0.01"), max_value=Decimal("100000"), decimal_places=2, widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}))
    season = forms.ChoiceField(label="Season", required=False, choices=[("", "Not sure"), ("kharif", "Kharif (monsoon)"), ("rabi", "Rabi (winter)"), ("zaid", "Zaid (summer)")])
    sowing_date = date_field("Sowing date", required=False)
    expected_harvest_date = date_field("Expected harvest date", required=False)

    def clean(self):
        d = super().clean()
        if d.get("crop") == "other" and not (d.get("crop_other") or "").strip():
            self.add_error("crop_other", "Write the crop name")
        s, e = d.get("sowing_date"), d.get("expected_harvest_date")
        if s and e and e < s:
            self.add_error("expected_harvest_date", "Expected harvest cannot be before sowing")
        return d

    def crop_name(self):
        d = self.cleaned_data
        return d["crop_other"].strip().lower() if d["crop"] == "other" else d["crop"]


class ExpenseForm(LangForm):
    category = forms.ChoiceField(label="What for?", choices=list(Expense.Category.choices))
    amount = forms.DecimalField(label="Amount (₹)", min_value=Decimal("1"), decimal_places=2, widget=forms.NumberInput(attrs={"inputmode": "decimal", "autofocus": True}))
    date = date_field("Date", initial=today)
    note = forms.CharField(label="Note (optional)", max_length=200, required=False)


class QuantityForm(LangForm):
    quantity = forms.DecimalField(label="Quantity", min_value=Decimal("0.001"), decimal_places=3, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal", "autofocus": True}))
    unit = forms.ChoiceField(label="Unit", choices=UNIT_LABELS, initial="quintal")
    bag_weight_kg = forms.DecimalField(label="Weight of one bag (kg)", required=False, min_value=Decimal("0.1"), decimal_places=2, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    date = date_field("Date", initial=today)

    def clean(self):
        d = super().clean()
        if d.get("unit") == "bag" and not d.get("bag_weight_kg"):
            self.add_error("bag_weight_kg", "Tell us how many kg one bag weighs")
        return d


class HarvestForm(QuantityForm):
    grade = forms.ChoiceField(label="Quality", choices=list(Harvest.Grade.choices), initial="ungraded", required=False)
    shelf_life_days = forms.IntegerField(label="How many days can it be stored? (optional)", required=False, min_value=1, max_value=3650)
    storage_note = forms.CharField(label="Where is it stored? (optional)", max_length=160, required=False)


class SaleForm(QuantityForm):
    product = forms.ChoiceField(label="What did you sell?", choices=[], required=False)
    rate = forms.DecimalField(label="Rate (₹ per unit chosen above)", min_value=Decimal("0.01"), decimal_places=2, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    channel = forms.ChoiceField(label="Sold to", choices=list(Sale.Channel.choices), initial="other", required=False)
    buyer_note = forms.CharField(label="Buyer name or note (optional)", max_length=160, required=False)

    def __init__(self, *args, products=(), **kwargs):
        """`products`: (key, English name) of what is in stock besides the crop itself. With none, the question is not asked."""
        super().__init__(*args, **kwargs)
        if products:
            self.fields["product"].choices = [("", tr(self.lang, "The crop itself"))] + [(k, tr(self.lang, n)) for k, n in products]
        else:
            del self.fields["product"]


class ProcessForm(QuantityForm):
    """Making something from stock: how much went in, what came out, what it cost."""

    product = forms.ChoiceField(label="What did you make?", choices=[])
    input_quantity = forms.DecimalField(label="How much did you put in?", min_value=Decimal("0.001"), decimal_places=3, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal", "autofocus": True}))
    input_unit = forms.ChoiceField(label="Unit of what went in", choices=[("quintal", "Quintal"), ("kg", "Kg"), ("tonne", "Tonne")], initial="quintal")
    cost = forms.DecimalField(label="What did the work cost in total? (₹)", required=False, min_value=Decimal("0"), max_value=Decimal("100000000"), decimal_places=2, initial=0, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    packaging = forms.ChoiceField(label="How will it be sold?", choices=[("bulk", "Loose, in bulk"), ("packed", "Packed for retail")], initial="bulk", required=False)
    pack_size_g = forms.IntegerField(label="Grams (or ml) in one pack", required=False, min_value=1, max_value=100000)
    shelf_life_days = forms.IntegerField(label="How many days can it be stored? (optional)", required=False, min_value=1, max_value=3650)
    note = forms.CharField(label="Note (optional)", max_length=200, required=False)

    def __init__(self, *args, crop="", **kwargs):
        super().__init__(*args, **kwargs)
        from catalog import services as cat

        options = [c[1] for c in cat.conversions_from(crop)]
        seen = []
        self.fields["product"].choices = [(k, tr(self.lang, catalog.name(k))) for k in options if k not in seen and not seen.append(k)]
        self.fields["quantity"].label = "How much did you get out?"
        self.order_fields(["product", "date", "input_quantity", "input_unit", "quantity", "unit", "bag_weight_kg", "cost", "packaging", "pack_size_g", "shelf_life_days", "note"])


class TaskForm(LangForm):
    kind = forms.ChoiceField(label="What work?", choices=list(Activity.Kind.choices))
    date = date_field("Date", initial=today)
    note = forms.CharField(label="Note (optional)", max_length=200, required=False)
    planned = forms.BooleanField(label="Remind me later (not done yet)", required=False)


class BuyerProfileForm(LangForm):
    contact_name = forms.CharField(label="Your name", max_length=120)
    business_name = forms.CharField(label="Business name", max_length=160)
    business_type = forms.ChoiceField(label="Type of business", choices=list(BuyerProfile.BusinessType.choices))
    city = forms.CharField(label="City", max_length=80)
    gstin = forms.CharField(label="GSTIN (optional)", max_length=15, required=False)
    fssai = forms.CharField(label="FSSAI number (optional)", max_length=14, required=False)

    def clean_gstin(self):
        v = self.cleaned_data["gstin"].strip().upper()
        if v and len(v) != 15:
            raise forms.ValidationError("GSTIN has 15 characters")
        return v

    def clean_fssai(self):
        v = self.cleaned_data["fssai"].strip()
        if v and (len(v) != 14 or not v.isdigit()):
            raise forms.ValidationError("FSSAI number has 14 digits")
        return v


class LeadForm(LangForm):
    name = forms.CharField(label="Your name", max_length=120)
    phone = forms.CharField(label="Mobile number", max_length=20, widget=forms.TextInput(attrs={"inputmode": "tel"}))
    city = forms.CharField(label="City or district", max_length=80, required=False)
    message = forms.CharField(label="What do you need? (optional)", max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    consent = forms.BooleanField(label="You may contact me about Seedha Bazar on this number", error_messages={"required": "Please tick the box to continue"})
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))  # honeypot: people leave it empty, bots fill it

    def clean_phone(self):
        try:
            return normalise_phone(self.cleaned_data["phone"])
        except InvalidPhone:
            raise forms.ValidationError("Enter a valid 10-digit Indian mobile number")


class ConsoleOrgForm(FpoRegisterForm):
    agent_phone = forms.CharField(label="Agent's mobile number", max_length=20)
    verified = forms.BooleanField(label="Mark as verified now", required=False, initial=True)

    def clean_agent_phone(self):
        try:
            return normalise_phone(self.cleaned_data["agent_phone"])
        except InvalidPhone:
            raise forms.ValidationError("Enter a valid 10-digit Indian mobile number")


class ConsoleAddFarmerForm(AddFarmerForm):
    organisation = forms.ChoiceField(label="Organisation", choices=[])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organisation"].choices = [(str(o.pk), o.name) for o in Organisation.objects.order_by("name")]


class ListingForm(LangForm):
    variety = forms.CharField(label="Variety (optional)", max_length=60, required=False)
    grade = forms.ChoiceField(label="Quality", choices=list(Listing.Grade.choices), initial="ungraded", required=False)
    quantity = forms.DecimalField(label="How much is for sale?", min_value=Decimal("0.001"), decimal_places=3, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    unit = forms.ChoiceField(label="Unit", choices=UNIT_LABELS, initial="quintal")
    bag_weight_kg = forms.DecimalField(label="Weight of one bag (kg)", required=False, min_value=Decimal("0.1"), decimal_places=2, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    price = forms.DecimalField(label="Your price (₹ per unit chosen above)", min_value=Decimal("0.01"), max_value=Decimal("10000000"), decimal_places=2, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    state = forms.CharField(label="State", max_length=60)
    district = forms.CharField(label="District", max_length=80)
    village = forms.CharField(label="Village (optional)", max_length=120, required=False)
    available_from = date_field("Available from", initial=today)
    packaging = forms.ChoiceField(label="How is it sold?", choices=[("bulk", "Loose, in bulk"), ("packed", "Packed for retail")], initial="bulk", required=False)
    pack_size_g = forms.IntegerField(label="Grams (or ml) in one pack", required=False, min_value=1, max_value=100000, widget=forms.NumberInput(attrs={"inputmode": "numeric"}))
    brand = forms.CharField(label="Brand name (optional)", max_length=80, required=False)
    fssai_no = forms.CharField(label="FSSAI licence or registration number (14 digits)", max_length=20, required=False, widget=forms.TextInput(attrs={"inputmode": "numeric"}))
    shelf_life_days = forms.IntegerField(label="Stays good for (days)", required=False, min_value=1, max_value=3650, widget=forms.NumberInput(attrs={"inputmode": "numeric"}))
    description = forms.CharField(label="Anything buyers should know? (optional)", max_length=300, required=False, widget=forms.Textarea(attrs={"rows": 3}))

    SEMI_ONLY = ("packaging", "pack_size_g", "brand", "fssai_no")

    def __init__(self, *args, processed=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.processed = processed
        if not processed:
            for name in self.SEMI_ONLY:
                del self.fields[name]
            self.fields["shelf_life_days"].label = "Stays good for (days, optional)"

    def clean(self):
        d = super().clean()
        if self.processed and d.get("packaging") == "packed":
            if len(re.sub(r"\D", "", d.get("fssai_no") or "")) != 14:
                self.add_error("fssai_no", "Packed food needs a 14-digit FSSAI licence or registration number.")
            if not d.get("pack_size_g"):
                self.add_error("pack_size_g", "Tell us the size of one pack")
        if d.get("unit") == "bag" and not d.get("bag_weight_kg"):
            self.add_error("bag_weight_kg", "Tell us how many kg one bag weighs")
        return d


class EnquiryForm(LangForm):
    quantity = forms.DecimalField(label="How much do you want?", min_value=Decimal("0.001"), decimal_places=3, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    offered_price = forms.DecimalField(label="Your offered price per unit (optional)", required=False, min_value=Decimal("0.01"), decimal_places=2, widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}))
    message = forms.CharField(label="Message (optional)", max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 3}))


class ChatForm(LangForm):
    text = forms.CharField(label="Write a message", max_length=500, widget=forms.Textarea(attrs={"rows": 2}))


class AnnouncementForm(LangForm):
    title = forms.CharField(label="Title", max_length=160)
    body = forms.CharField(label="Message (optional)", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    link = forms.URLField(label="Link (optional)", required=False)
    audience = forms.ChoiceField(label="Who sees it", choices=[("all", "Everyone"), ("farmer", "Farmers"), ("fpo", "FPOs and NGOs"), ("buyer", "Buyers")], initial="all")
    language = forms.ChoiceField(label="Language", choices=[("", "Every language"), ("hi", "Hindi"), ("mr", "Marathi"), ("en", "English")], required=False)
    state = forms.CharField(label="Only this state (optional)", max_length=60, required=False)
    district = forms.CharField(label="Only this district (optional)", max_length=80, required=False)
    pinned = forms.BooleanField(label="Pin to the top", required=False)


class CentreForm(LangForm):
    name = forms.CharField(label="Centre name", max_length=200)
    kind = forms.ChoiceField(label="Type", choices=[("kvk", "Krishi Vigyan Kendra (KVK)"), ("research", "Research centre / ICAR institute"), ("university", "Agricultural university"), ("department", "Agriculture department office")])
    state = forms.CharField(label="State", max_length=60, initial="Madhya Pradesh")
    districts = forms.CharField(label="Districts it looks after (separate with commas)", max_length=600)
    host = forms.CharField(label="Host institution (optional)", max_length=200, required=False)
    address = forms.CharField(label="Address (optional)", max_length=300, required=False)
    lat = forms.FloatField(label="Latitude (optional)", required=False, min_value=6, max_value=38)
    lon = forms.FloatField(label="Longitude (optional)", required=False, min_value=68, max_value=98)
    phone = forms.CharField(label="Phone (optional)", max_length=40, required=False)
    email = forms.EmailField(label="Email (optional)", required=False)
    website = forms.URLField(label="Website (optional)", required=False)


class CentreStaffForm(LangForm):
    phone = forms.CharField(label="Mobile number", max_length=20, widget=forms.TextInput(attrs={"inputmode": "tel"}))
    role = forms.ChoiceField(label="Role", choices=[("head", "Head / Senior scientist"), ("expert", "Subject matter specialist"), ("staff", "Staff")], initial="expert")
    speciality = forms.CharField(label="Speciality (optional)", max_length=80, required=False)

    def clean_phone(self):
        from accounts.phone import InvalidPhone, normalise_phone
        try:
            return normalise_phone(self.cleaned_data["phone"])
        except InvalidPhone:
            raise forms.ValidationError("Enter a valid 10-digit mobile number")
