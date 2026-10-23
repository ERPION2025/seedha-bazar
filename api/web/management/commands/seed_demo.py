from datetime import date, timedelta

from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Role, User, UserStatus
from django.conf import settings
from farmerbook.models import Activity, CropCycle, Expense, Harvest, Plot, Processing, Sale
from profiles import services
from profiles.models import Organisation
from market import services as market
from market.models import Enquiry, Listing
from rates.demo import seed_demo_rates
from web.models import Lead

FPO_ADMIN, FARMER, WAITING, BUYER, KVK_STAFF = "9000000001", "9000000002", "9000000003", "9000000004", "9000000005"


class Command(BaseCommand):
    help = "Create a demo FPO, farmers and a season of Farmer Book entries so every screen has something to show. Safe to run twice."

    def handle(self, *args, **opts):
        today = timezone.localdate()
        org, _ = Organisation.objects.get_or_create(code="naigarhi", defaults={"name": "Naigarhi FPO"})
        org.district, org.block, org.verified, org.contact_name = "Rewa", "Naigarhi", True, "Mohan Tiwari"
        org.save()
        agent = services.provision_agent(FPO_ADMIN, org)

        farmer = User.objects.filter(phone=FARMER).first()
        if farmer is None:
            farmer = User.objects.create_user(FARMER, role=Role.FARMER, status=UserStatus.ACTIVE, language="hi",
                                              consented_at=timezone.now(), consent_version=settings.CONSENT_VERSION)
            fp = farmer.farmer_profile
            fp.name, fp.village, fp.block, fp.district = "Ramesh Kushwaha", "Naigarhi", "Naigarhi", "Rewa"
            fp.land_acres, fp.crops, fp.organisation, fp.org_status = 3.5, ["wheat", "kodo"], org, "confirmed"
            fp.save()
            plot = Plot.objects.create(owner=farmer, name="Home field", area_acres=2)
            c = CropCycle.objects.create(owner=farmer, plot=plot, crop="wheat", season="rabi", sowing_date=today - timedelta(days=150),
                                         expected_harvest_date=today - timedelta(days=20), status="harvested")
            for cat, amt, ago in (("seed", 3200, 150), ("fertiliser", 4100, 120), ("labour", 6500, 40), ("irrigation", 2400, 90)):
                Expense.objects.create(owner=farmer, crop_cycle=c, category=cat, amount=amt, date=today - timedelta(days=ago))
            Harvest.objects.create(owner=farmer, crop_cycle=c, date=today - timedelta(days=20), quantity=24, unit="quintal", quantity_kg=2400, grade="A", shelf_life_days=240)
            Sale.objects.create(owner=farmer, crop_cycle=c, date=today - timedelta(days=10), quantity=10, unit="quintal", quantity_kg=1000, rate=2425, amount=24250, channel="mandi")
            k = CropCycle.objects.create(owner=farmer, plot=plot, crop="kodo", season="kharif", sowing_date=today - timedelta(days=30), expected_harvest_date=today + timedelta(days=75))
            Activity.objects.create(owner=farmer, crop_cycle=k, kind="spray", date=today + timedelta(days=3), note="Neem spray", done=False)
            Activity.objects.create(owner=farmer, crop_cycle=k, kind="weeding", date=today - timedelta(days=1), done=False)

        # Stock the FPO can sell from: the member's kodo harvest, and a small batch of wheat turned into atta.
        kodo = CropCycle.objects.filter(owner=farmer, crop="kodo").first()
        if kodo and not Harvest.objects.filter(crop_cycle=kodo).exists():
            Harvest.objects.create(owner=farmer, crop_cycle=kodo, date=today - timedelta(days=5), quantity=40, unit="quintal", quantity_kg=4000, grade="B", shelf_life_days=300)
        wheat_cycle = CropCycle.objects.filter(owner=farmer, crop="wheat").first()
        if wheat_cycle and not Processing.objects.filter(crop_cycle=wheat_cycle).exists():
            Processing.objects.create(owner=farmer, crop_cycle=wheat_cycle, date=today - timedelta(days=3), product="atta", input_kg=200, quantity=160, unit="kg", quantity_kg=160,
                                      cost=500, packaging="bulk", shelf_life_days=90, note="Stone mill in Naigarhi")

        if not User.objects.filter(phone=WAITING).exists():
            services.create_assisted_farmer(agent, {"phone": WAITING, "name": "Sunita Devi", "village": "Gangeo", "district": "Rewa", "land_acres": 2, "crops": ["rice"], "language": "hi"}, org=org)
        buyer = User.objects.filter(phone=BUYER).first()
        if buyer is None:
            buyer = User.objects.create_user(BUYER, role=Role.BUYER, status=UserStatus.ACTIVE, consented_at=timezone.now(), consent_version=settings.CONSENT_VERSION)
            bp = buyer.buyer_profile
            bp.contact_name, bp.business_name, bp.business_type, bp.city = "Anita Rao", "Rao Caterers", "caterer", "Pune"
            bp.save()
        call_command("load_msp", stdout=self.stdout)
        call_command("load_odop", stdout=self.stdout)
        call_command("seed_knowledge", stdout=self.stdout)
        call_command("seed_insurance", stdout=self.stdout)
        # A demo KVK for Rewa. The map point is the town centre, not the KVK's real address: replace it with the centre's own.
        from extension.models import Centre, InputOffer
        from extension.services import provision_staff
        kvk, _ = Centre.objects.get_or_create(name="KVK Rewa (demo)", defaults={"state": "Madhya Pradesh", "districts": ["Rewa"], "lat": 24.5373, "lon": 81.3042,
                                                                               "host": "Demo data", "phone": "", "address": "Rewa (approximate demo location)"})
        provision_staff(KVK_STAFF, kvk, "head", "Agronomy")
        if not InputOffer.objects.filter(centre=kvk).exists():
            InputOffer.objects.create(centre=kvk, kind="seed", name="Wheat seed HI-1544 (demo)", crop="wheat", quantity=500, unit="kg", per_person_limit=40, price=0,
                                      valid_until=today + timedelta(days=30), pickup="KVK Rewa campus", note="For farmers with a soil health card. Bring Aadhaar.")
        Organisation.objects.filter(code="naigarhi", lat__isnull=True).update(lat=24.62, lon=81.18)
        fp_demo = farmer.farmer_profile
        if fp_demo.share_with_extension is None:
            fp_demo.share_with_extension = True
            fp_demo.save()
        self.stdout.write(f"Sample mandi rates: {seed_demo_rates()} rows (labelled as sample data).")
        if not Listing.objects.exists():
            wheat = CropCycle.objects.filter(owner=farmer, crop="wheat").first()
            fl = market.save_listing(farmer, {"crop": "wheat", "quantity": Decimal("10"), "unit": "quintal", "price": Decimal("2500"), "grade": "A", "state": "Madhya Pradesh",
                                              "district": "Rewa", "village": "Naigarhi", "description": "Sharbati, cleaned and bagged.", "source_cycle": wheat})
            kodo = CropCycle.objects.filter(owner=farmer, crop="kodo").first()
            ol = market.save_listing(agent, {"crop": "kodo", "source_cycle": kodo, "quantity": Decimal("30"), "unit": "quintal", "price": Decimal("3300"), "grade": "B", "state": "Madhya Pradesh",
                                             "district": "Rewa", "description": "Collected from 12 member farmers. Organic practices."}, org=org)
            market.start_enquiry(buyer, ol, Decimal("10"), Decimal("3200"), "We can lift this week. Can you deliver to Satna?")
            self.stdout.write(f"Sample listings: {fl.pk}, {ol.pk}")
        Lead.objects.get_or_create(kind="buyer", phone="9822000001", defaults={"name": "Vikram (Hotel Sapphire)", "city": "Nagpur", "consent": True, "language": "en", "attribution": {"utm_source": "facebook", "utm_campaign": "kodo"}})
        self.stdout.write(self.style.SUCCESS("Demo data ready. Sign in at /login/ with these numbers; the code appears in the server log:"))
        for label, phone, door in (("KVK expert (code shown on screen in development)", KVK_STAFF, "kvk"), ("FPO agent", FPO_ADMIN, "fpo"), ("Farmer", FARMER, "farmer"), ("Farmer waiting to confirm", WAITING, "farmer"), ("Buyer", BUYER, "buyer")):
            self.stdout.write(f"  {label:28} {phone}   /login/?as={door}")
