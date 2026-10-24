"""Footer on every page, and the read-only pages visitors and search engines can open."""
from decimal import Decimal

from django.test import Client, TestCase

from market import services
from web.tests.test_market_web import SELLER, listing_data, make_farmer, stocked_cycle

COMPANY = ("Vindhyachal Farms LLP", "Plot number 39, Palak Vihar", "Maharajpur, Adhartal, Jabalpur", "pranav@erpion.in", "9770417301")


class FooterTests(TestCase):
    def test_company_details_and_links_on_every_kind_of_page(self):
        farmer = make_farmer()
        c = Client()
        c.force_login(farmer)
        for client, path in ((Client(), "/login/"), (Client(), "/for-farmers/"), (c, "/farmer/"), (Client(HTTP_HOST="connect.testserver"), "/login/")):
            page = client.get(f"{path}?lang=en").content.decode()
            for bit in COMPANY:
                self.assertIn(bit, page, (path, bit))
            for link in ("/for-farmers/", "/for-fpos/", "/for-ngos/", "/for-buyers/", "/produce/wheat/", "/produce/"):
                self.assertIn(link + '"', page, (path, link))
            self.assertIn('href="tel:+919770417301"', page)
            self.assertIn('"legalName": "Vindhyachal Farms LLP"', page)  # for search engines

    def test_services_that_need_sign_in_are_nofollow_for_visitors(self):
        page = Client().get("/login/?lang=en").content.decode()
        self.assertIn('/rates/" rel="nofollow"', page)
        self.assertNotIn('/produce/wheat/" rel="nofollow"', page)


class OpenPageTests(TestCase):
    def test_visitor_pages_open_in_every_language_without_menus(self):
        for lang in ("hi", "mr", "en"):
            for path in ("/for-farmers/", "/for-fpos/", "/for-ngos/", "/for-buyers/", "/produce/", "/produce/wheat/", "/produce/kodo/"):
                r = Client().get(f"{path}?lang={lang}")
                self.assertEqual(r.status_code, 200, (path, lang))
                self.assertNotContains(r, 'class="side"')
        self.assertContains(Client().get("/for-ngos/?lang=en"), "For NGOs working with farmers")
        self.assertEqual(Client().get("/produce/not-a-crop/").status_code, 404)

    def test_produce_page_shows_what_is_on_sale_without_the_seller(self):
        seller = make_farmer()
        services.save_listing(seller, listing_data(source_cycle=stocked_cycle(seller, quintals=100), price=Decimal("2500")))
        page = Client().get("/produce/wheat/?lang=en").content.decode()
        self.assertIn("Buy Wheat directly from farmers and FPOs", page)
        self.assertIn("Ramesh", page)  # first name and village only
        self.assertNotIn(SELLER, page)
        self.assertNotIn("Kushwaha", page)
        self.assertTrue(Client().get(page.split('class="door" href="')[1].split('"')[0])["Location"].startswith("/login/"))  # buying needs sign-in

    def test_sitemap_and_robots(self):
        sm = Client().get("/sitemap.xml").content.decode()
        self.assertIn("/produce/wheat/</loc>", sm)
        self.assertIn("/for-ngos/</loc>", sm)
        robots = Client().get("/robots.txt").content.decode()
        self.assertIn("Disallow: /console/", robots)
        self.assertIn("Sitemap: ", robots)
