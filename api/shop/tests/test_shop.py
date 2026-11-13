from decimal import Decimal as D

from django.test import Client, TestCase, override_settings

from accounts.models import Role, User, UserStatus
from notify.models import InboxItem, Preference
from shop import services as shop
from shop.models import Order, OrderLine, Product, SellerSettings, StockMove
from web.tests.test_market_web import NOTIFY_MEM, make_buyer, make_farmer


def household(phone="9844444444"):
    u = User.objects.create_user(phone, role=Role.BUYER, status=UserStatus.ACTIVE, consent_version="2026-10-v1")
    bp = u.buyer_profile
    bp.contact_name, bp.business_type, bp.city = "Asha", "individual", "Bhopal"
    bp.save()
    return u


ADDRESS = {"name": "Asha", "phone": "9844444444", "address": "12 Arera Colony", "city": "Bhopal", "pincode": "462016", "payment": "cod"}


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM, SHOP_SELLER_PCT="3", SHOP_BUYER_PCT="5", SHOP_DELIVERY_FEE=49, SHOP_FREE_DELIVERY_ABOVE=999)
class ShopTests(TestCase):
    def setUp(self):
        self.maker = make_farmer()
        SellerSettings.objects.create(user=self.maker, legal_name="Ramesh Kushwaha", address="Near the temple", village="Naigarhi", district="Rewa",
                                      state="Madhya Pradesh", pincode="486001", allow_self_pickup=True)
        self.mc = Client()
        self.mc.force_login(self.maker)
        self.staff = User.objects.create_superuser("9999999999", password="x")
        self.sc = Client()
        self.sc.force_login(self.staff)

    def add_product(self, **over):
        data = {"category": "handloom", "title": "Chanderi saree", "pack": "1 saree", "description": "Handwoven silk-cotton, 5.5 m.", "asked_price": "2400",
                "max_per_order": "5", "fulfilment": "seller", "village": "Naigarhi", "district": "Rewa", "state": "Madhya Pradesh", "weight_g": "500", "gst_rate": "0",
                "stock": "6"}
        data.update(over)
        self.mc.post("/shop/manage/new/", data)
        return Product.objects.latest("pk")

    def approve(self, p, price=""):
        self.sc.post("/console/shop/", {"product": p.pk, "decision": "approve", "price": price, "note": "Good photos"})
        p.refresh_from_db()
        return p

    def test_a_product_goes_on_sale_only_after_review_at_the_reviewed_price(self):
        p = self.add_product()
        self.assertEqual((p.status, p.stock, p.seller, p.price), ("pending", 6, self.maker, None))
        self.assertEqual(Client().get(f"/shop/p/{p.pk}/").status_code, 404)  # not public yet
        self.assertEqual(StockMove.objects.get(product=p).change, 6)
        p = self.approve(p, "2200")
        self.assertEqual((p.status, p.price), ("live", D("2200")))
        self.assertTrue(InboxItem.objects.filter(user=self.maker, template="shop_review").exists())
        page = Client().get(f"/shop/p/{p.pk}/?lang=en").content.decode()
        self.assertIn("2,310", page)  # 2200 + 5% buyer fee
        self.assertNotIn(self.maker.phone, page)
        self.assertContains(Client().get("/shop/c/handloom/?lang=en"), "Chanderi saree")
        self.mc.post(f"/shop/manage/{p.pk}/", {"action": "stock", "change": "4"})
        p.refresh_from_db()
        self.assertEqual((p.stock, p.status), (10, "live"))  # stock changes stay live
        self.mc.post(f"/shop/manage/{p.pk}/", {"category": "handloom", "title": "Chanderi saree", "pack": "1 saree", "description": "Handwoven silk-cotton, 5.5 m.",
                                               "asked_price": "2600", "max_per_order": "5", "fulfilment": "seller", "village": "Naigarhi", "district": "Rewa",
                                               "state": "Madhya Pradesh", "weight_g": "500", "gst_rate": "0"})
        p.refresh_from_db()
        self.assertEqual(p.status, "pending")  # a new price is checked again

    def test_packed_food_needs_fssai(self):
        self.mc.post("/shop/manage/new/", {"category": "food", "title": "Kodo cookies", "pack": "200 g", "description": "Millet cookies", "asked_price": "120",
                                           "max_per_order": "10", "fulfilment": "seller", "village": "Naigarhi", "district": "Rewa", "state": "Madhya Pradesh",
                                           "weight_g": "200", "gst_rate": "0"})
        self.assertFalse(Product.objects.exists())

    def test_cart_checkout_fees_stock_and_the_order_steps(self):
        p = self.approve(self.add_product(), "400")
        anon = Client()
        anon.post("/shop/cart/change/", {"product": p.pk, "qty": "2"})
        self.assertTrue(anon.get("/shop/checkout/")["Location"].startswith("/login/"))  # buying needs sign-in
        buyer = household()
        bc = Client()
        bc.force_login(buyer)
        bc.post("/shop/cart/change/", {"product": p.pk, "qty": "2"})
        bc.post("/shop/cart/", {"pin": "462016"})
        r = bc.post("/shop/checkout/", ADDRESS)
        o = Order.objects.get()
        self.assertRedirects(r, f"/shop/orders/{o.number}/", fetch_redirect_response=False)
        # Rewa to Bhopal is within the state: ₹50 for the first 500 g and ₹15 for the next 500 g
        self.assertEqual((o.goods, o.buyer_fee, o.delivery_fee, o.total, o.channel, o.state), (D("800"), D("40"), D("65"), D("905"), "b2c", "Madhya Pradesh"))
        p.refresh_from_db()
        self.assertEqual(p.stock, 4)
        line = OrderLine.objects.get()
        self.assertEqual((line.seller_fee, line.payout), (D("24"), D("776")))
        self.assertTrue(InboxItem.objects.filter(user=self.maker, template="shop_order").exists())
        self.mc.post("/shop/manage/orders/", {"line": line.pk})
        o.refresh_from_db()
        self.assertEqual(o.status, "confirmed")
        for step in ("packed", "dispatched", "delivered"):
            self.sc.post("/console/shop/orders/", {"order": o.pk, "action": step})
        o.refresh_from_db()
        self.assertEqual((o.status, o.paid), ("delivered", True))  # cash collected on delivery
        self.sc.post("/console/shop/orders/", {"order": o.pk, "action": "payout"})
        self.assertIsNotNone(OrderLine.objects.get().paid_out_at)
        self.assertContains(self.sc.get("/console/shop/fees/?lang=en"), "₹64")  # 24 from the maker + 40 from the buyer
        self.assertTrue(InboxItem.objects.filter(user=buyer, template="shop_update").exists())

    @override_settings(SHOP_DELIVERY_FEE=49)
    def test_delivery_fee_and_cities(self):
        p = self.approve(self.add_product(), "100")
        buyer = household()
        bc = Client()
        bc.force_login(buyer)
        bc.post("/shop/cart/change/", {"product": p.pk, "qty": "1"})
        self.assertEqual(shop.cart_lines(bc.session["cart"], buyer, "462016")["delivery"], D("50"))
        bc.post("/shop/cart/", {"pin": "462016"})
        bc.post("/shop/checkout/", {**ADDRESS, "city": "Atlantis"})
        self.assertFalse(Order.objects.exists())

    def test_cancelling_returns_stock_but_not_once_on_the_way(self):
        p = self.approve(self.add_product(), "400")
        buyer = household()
        o = shop.place_order(buyer, {str(p.pk): 3}, ADDRESS)
        p.refresh_from_db()
        self.assertEqual(p.stock, 3)
        bc = Client()
        bc.force_login(buyer)
        bc.post(f"/shop/orders/{o.number}/", {"action": "cancel"})
        p.refresh_from_db()
        o.refresh_from_db()
        self.assertEqual((o.status, p.stock), ("cancelled", 6))
        o2 = shop.place_order(buyer, {str(p.pk): 1}, ADDRESS)
        for step in ("confirmed", "packed", "dispatched"):
            shop.advance(o2, step, self.staff)
        bc.post(f"/shop/orders/{o2.number}/", {"action": "cancel"})
        o2.refresh_from_db()
        self.assertEqual(o2.status, "dispatched")

    def test_the_last_piece_cannot_be_sold_twice(self):
        p = self.approve(self.add_product(stock="1"), "400")
        shop.place_order(household(), {str(p.pk): 1}, ADDRESS)
        with self.assertRaises(Exception):
            shop.place_order(household("9844444445"), {str(p.pk): 1}, ADDRESS)

    def test_business_buyers_get_the_business_price(self):
        p = self.approve(self.add_product(b2b_price="350", b2b_min="3"), "400")
        biz = make_buyer()
        o = shop.place_order(biz, {str(p.pk): 4}, ADDRESS)
        self.assertEqual((o.channel, OrderLine.objects.get(order=o).unit_price), ("b2b", D("350")))
        home = shop.place_order(household(), {str(p.pk): 2}, ADDRESS)  # a household pays the normal price
        self.assertEqual(OrderLine.objects.get(order=home).unit_price, D("400"))

    def test_fees_are_set_per_category_in_the_console(self):
        data = {f"s_{k}": "3" for k, _, _ in __import__("shop.models", fromlist=["CATEGORIES"]).CATEGORIES} | {f"b_{k}": "5" for k, _, _ in __import__("shop.models", fromlist=["CATEGORIES"]).CATEGORIES}
        data.update(s_handloom="6", b_handloom="8")
        self.sc.post("/console/shop/fees/", data)
        self.assertEqual(shop.fees("handloom"), (D("6.00"), D("8.00")))

    def test_menus_and_the_open_storefront(self):
        self.assertContains(self.mc.get("/shop/manage/?lang=en"), 'href="/shop/manage/"')
        bc = Client()
        bc.force_login(household())
        page = bc.get("/shop/?lang=en").content.decode()
        self.assertIn('href="/shop/orders/"', page)
        visitor = Client().get("/shop/?lang=en")
        self.assertEqual(visitor.status_code, 200)
        self.assertNotContains(visitor, 'class="side"')
        self.assertTrue(Client().get("/shop/manage/")["Location"].startswith("/login/"))
        self.assertIn("/shop/</loc>", Client().get("/sitemap.xml").content.decode())


class SoundTests(TestCase):
    def test_every_page_carries_the_breeze_and_it_can_be_switched_off(self):
        u = make_farmer()
        c = Client()
        c.force_login(u)
        page = c.get("/farmer/?lang=en").content.decode()
        self.assertIn("sounds/breeze.wav", page)
        self.assertIn('data-sound-on="1"', page)
        self.assertIn("web/sound.js", page)
        c.post("/notifications/settings/", {"sms": "1"})  # soft_sounds not ticked
        self.assertFalse(Preference.objects.get(user=u).soft_sounds)
        self.assertIn('data-sound-on=""', c.get("/farmer/?lang=en").content.decode())
        self.assertIn('data-sound-on="1"', Client().get("/login/").content.decode())
