"""The owner console: password sign-in, institutions and their people, admins, all records; institution email codes;
the warehouse list; map tiles."""
import re

from django.contrib import admin
from django.core import mail
from django.test import Client, TestCase, override_settings

from accounts.models import Role, User, UserStatus
from extension.models import Centre, CentreMember
from storage.models import Warehouse
from web.tests.test_market_web import make_farmer

PASSWORD = "a-long-test-password"


def owner():
    u = User.objects.create_superuser("9999999999", password=PASSWORD, email="owner@example.in")
    return u


class ConsoleLoginTests(TestCase):
    def test_console_asks_for_a_password_and_accepts_phone_or_email(self):
        owner()
        c = Client()
        self.assertRedirects(c.get("/console/"), "/console/login/", fetch_redirect_response=False)
        r = c.post("/console/login/?lang=en", {"login": "owner@example.in", "password": "wrong-password"})
        self.assertContains(r, "is wrong")
        self.assertRedirects(c.post("/console/login/", {"login": "OWNER@example.in", "password": PASSWORD}), "/console/", fetch_redirect_response=False)
        c2 = Client()
        self.assertRedirects(c2.post("/console/login/", {"login": "99999 99999", "password": PASSWORD}), "/console/", fetch_redirect_response=False)

    def test_farmers_cannot_use_the_console_login(self):
        f = make_farmer()
        f.set_password(PASSWORD)
        f.save()
        r = Client().post("/console/login/?lang=en", {"login": f.phone, "password": PASSWORD})
        self.assertContains(r, "is wrong")

    def test_create_owner_command(self):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("create_owner", phone="9888888888", email="boss@example.in", stdout=out)
        u = User.objects.get(phone="9888888888")
        self.assertTrue(u.is_superuser and u.is_staff)
        password = re.search(r"Password .*: (\S+)", out.getvalue()).group(1)
        self.assertTrue(u.check_password(password))


class InstitutionAdminTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.c.force_login(owner())

    def add(self):
        r = self.c.post("/console/institutions/new/", {"action": "save", "name": "KVK Satna", "kind": "kvk", "state": "Madhya Pradesh", "districts": ["Satna"],
                                                        "verified": "on"})
        centre = Centre.objects.get(name="KVK Satna")
        self.assertRedirects(r, f"/console/institutions/{centre.pk}/", fetch_redirect_response=False)
        return centre

    def test_add_change_people_and_remove(self):
        centre = self.add()
        self.assertEqual(centre.districts, ["Satna"])
        self.c.post(f"/console/institutions/{centre.pk}/", {"action": "staff_add", "new-name": "Dr Sharma", "new-phone": "9811100002",
                                                            "new-email": "sharma@kvk.in", "new-role": "head"})
        m = CentreMember.objects.get(centre=centre)
        self.assertEqual((m.name, m.user.email, m.user.role), ("Dr Sharma", "sharma@kvk.in", Role.AGRONOMIST))
        self.c.post(f"/console/institutions/{centre.pk}/", {"action": "staff_update", "member": m.pk, "name": "Dr R Sharma", "role": "expert", "email": "rs@kvk.in"})
        m.refresh_from_db()
        self.assertEqual((m.name, m.role, m.user.email), ("Dr R Sharma", "expert", "rs@kvk.in"))
        self.c.post(f"/console/institutions/{centre.pk}/", {"action": "save", "name": "KVK Satna", "kind": "kvk", "state": "Madhya Pradesh",
                                                            "districts": ["Satna", "Rewa"]})
        centre.refresh_from_db()
        self.assertEqual(sorted(centre.districts), ["Rewa", "Satna"])
        self.c.post(f"/console/institutions/{centre.pk}/", {"action": "staff_remove", "member": m.pk})
        self.assertEqual(User.objects.get(phone="9811100002").status, UserStatus.DISABLED)  # their sign-in stops

    def test_remove_needs_the_name_typed(self):
        centre = self.add()
        self.c.post(f"/console/institutions/{centre.pk}/", {"action": "delete", "confirm": "nope"})
        self.assertTrue(Centre.objects.filter(pk=centre.pk).exists())
        self.c.post(f"/console/institutions/{centre.pk}/", {"action": "delete", "confirm": "KVK Satna"})
        self.assertFalse(Centre.objects.filter(pk=centre.pk).exists())

    def test_changing_state_reloads_its_districts_without_saving(self):
        r = self.c.post("/console/institutions/new/?lang=en", {"action": "reload", "name": "X", "state": "Maharashtra"})
        self.assertContains(r, 'value="Pune"')
        self.assertFalse(Centre.objects.exists())

    def test_pages_render(self):
        centre = self.add()
        for lang in ("hi", "mr", "en"):
            for path in ("/console/institutions/", f"/console/institutions/{centre.pk}/", "/console/institutions/new/", "/console/admins/"):
                self.assertEqual(self.c.get(f"{path}?lang={lang}").status_code, 200, path)


class AdminsTests(TestCase):
    def test_only_an_owner_adds_and_removes_admins(self):
        c = Client()
        c.force_login(owner())
        c.post("/console/admins/", {"action": "add", "phone": "9877777777", "email": "ops@example.in", "password": "another-long-one"})
        u = User.objects.get(phone="9877777777")
        self.assertTrue(u.is_staff and not u.is_superuser and u.check_password("another-long-one"))
        helper = Client()
        helper.force_login(u)
        helper.post("/console/admins/", {"action": "add", "phone": "9866666666", "email": "x@example.in", "password": "another-long-one"})
        self.assertFalse(User.objects.filter(phone="9866666666").exists())
        c.post("/console/admins/", {"action": "remove", "user": u.pk})
        u.refresh_from_db()
        self.assertFalse(u.is_staff)
        self.assertEqual(u.status, UserStatus.DISABLED)

    def test_every_model_is_in_all_records(self):
        from django.apps import apps
        missing = [m.__name__ for m in apps.get_models() if not admin.site.is_registered(m) and m._meta.app_label not in ("contenttypes", "sessions", "admin")]
        self.assertEqual(missing, [])
        c = Client()
        c.force_login(owner())
        self.assertEqual(c.get("/admin/extension/centre/").status_code, 200)
        self.assertEqual(c.get("/admin/storage/warehouse/").status_code, 200)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", OTP_BACKEND="accounts.messaging.MemoryBackend")
class InstitutionEmailCodeTests(TestCase):
    def setUp(self):
        from extension import services as ext
        self.centre = Centre.objects.create(name="KVK Rewa", state="Madhya Pradesh", districts=["Rewa"])
        self.staff = ext.provision_staff("9811100001", self.centre, "expert", email="expert@kvk.in", name="Dr Rao")
        self.k = Client(HTTP_HOST="connect.testserver")

    def test_sign_in_with_a_code_by_email(self):
        r = self.k.post("/login/?lang=en", {"by": "email", "email": "EXPERT@kvk.in"})
        self.assertRedirects(r, "/login/verify/", fetch_redirect_response=False)
        self.assertEqual(mail.outbox[0].to, ["expert@kvk.in"])
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        self.assertContains(self.k.get("/login/verify/?lang=en"), "ex•••@kvk.in")
        r = self.k.post("/login/verify/", {"code": code})
        if r["Location"] == "/login/consent/":
            r = self.k.post("/login/consent/", {"consent": "on"})
        self.assertEqual(r["Location"], "/")
        self.assertEqual(self.k.get("/").status_code, 200)

    def test_or_by_mobile_and_unknown_addresses_are_refused(self):
        self.assertRedirects(self.k.post("/login/", {"by": "mobile", "phone": "9811100001"}), "/login/verify/", fetch_redirect_response=False)
        self.assertContains(Client(HTTP_HOST="connect.testserver").post("/login/?lang=en", {"by": "email", "email": "nobody@kvk.in"}), "not registered")
        self.assertEqual(len(mail.outbox), 0)

    def test_removed_staff_cannot_sign_in(self):
        from extension import services as ext
        ext.remove_staff(CentreMember.objects.get(user=self.staff))
        self.k.post("/login/", {"by": "mobile", "phone": "9811100001"})
        from accounts.tests.helpers import last_code
        r = self.k.post("/login/verify/", {"code": last_code("9811100001")})
        self.assertNotEqual(r.get("Location"), "/")


class WarehouseListTests(TestCase):
    def setUp(self):
        self.f = make_farmer()
        fp = self.f.farmer_profile
        fp.village = "Gurh"
        fp.save()
        mk = lambda n, d, addr, st="Active", cap=1000: Warehouse.objects.create(name=n, state="Madhya Pradesh", district=d, address=addr, wdra_status=st, capacity_mt=cap,
                                                                                 wdra_reg_no=n, source="wdra", phone="9000000000")
        mk("BIG STORE", "Rewa", "Khasra No. 12, Vill- Raipur, Tehsil Huzur", cap=9000)
        mk("GURH WAREHOUSE", "Rewa", "Gram Gurh, Rewa", cap=500)
        mk("SHUT STORE", "Rewa", "Mauganj", st="Inactive")
        mk("SATNA STORE", "Satna", "Amarpatan")
        self.c = Client()
        self.c.force_login(self.f)

    def test_own_district_by_default_own_village_first_and_tidy_names(self):
        r = self.c.get("/storage/warehouses/?lang=en")
        names = [w.label for w in r.context["rows"]]
        self.assertEqual(names, ["Gurh Warehouse", "Big Store"])  # village first; inactive and other districts hidden
        self.assertEqual(r.context["rows"][1].place, "Raipur, Huzur")  # khasra numbers dropped
        self.assertContains(r, 'href="tel:9000000000"')

    def test_filters(self):
        self.assertEqual(len(self.c.get("/storage/warehouses/?district=Rewa&all=1").context["rows"]), 3)
        self.assertEqual([w.label for w in self.c.get("/storage/warehouses/?district=Rewa&q=raipur").context["rows"]], ["Big Store"])
        self.assertEqual([w.label for w in self.c.get("/storage/warehouses/?district=").context["rows"]][0], "Gurh Warehouse")
        self.assertEqual(len(self.c.get("/storage/warehouses/?district=Satna").context["rows"]), 1)

    def test_hub_shows_three_nearest_and_a_link(self):
        r = self.c.get("/storage/?lang=en")
        self.assertContains(r, "/storage/warehouses/")
        self.assertContains(r, "Gurh Warehouse")


class MapTileTests(TestCase):
    def test_tiles_send_our_origin_as_osm_requires(self):
        from pathlib import Path
        js = (Path(__file__).resolve().parents[1] / "static" / "web" / "map.js").read_text()
        self.assertIn('referrerPolicy: "strict-origin-when-cross-origin"', js)
