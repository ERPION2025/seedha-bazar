"""Delivery zones, the two fulfilment models, pickup, GST documents, couriers, labels and online payment."""
import hashlib
import hmac
from decimal import Decimal as D
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from shop import couriers, gst, payments, services as shop, shipping
from shop.models import Inbound, Invoice, Order, OrderLine, Product, SellerSettings, Shipment
from shop.tests.test_shop import ADDRESS, household
from web.tests.test_market_web import NOTIFY_MEM, make_farmer


def live(seller, **over):
    data = {"category": "handloom", "title": "Bagh print stole", "pack": "1 stole", "asked_price": D("1000"), "price": D("1000"), "stock": 10, "status": "live",
            "village": "Naigarhi", "district": "Rewa", "state": "Madhya Pradesh", "weight_g": 400, "reviewed_at": timezone.now()}
    data.update(over)
    return Product.objects.create(seller=seller, **data)


class ZoneTests(TestCase):
    def test_zones_and_days_from_pin_codes(self):
        for to, zone in (("482001", "local"), ("462016", "state"), ("440001", "near"), ("110001", "metro"), ("600001", "metro"), ("781001", "remote"),
                         ("695001", "national")):
            self.assertEqual(shipping.zone("482004", to), zone, to)
        self.assertEqual(shipping.quote("482004", "462016", 1200)["fee"], D("80"))  # 50 + 2 x 15
        self.assertEqual(shipping.quote("482004", "482001", 300), {"zone": "local", "days": "1-2", "fee": D("30")})
        self.assertFalse(shipping.valid_pin("012345"))


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM, SHOP_SELLER_PCT="3", SHOP_BUYER_PCT="5", SHOP_FREE_DELIVERY_ABOVE=99999, GSTIN="", GST_TCS_PCT="0.5")
class FulfilmentTests(TestCase):
    def setUp(self):
        self.maker = make_farmer()
        self.ss = SellerSettings.objects.create(user=self.maker, legal_name="Ramesh Kushwaha", address="Near the temple", village="Naigarhi", district="Rewa",
                                                state="Madhya Pradesh", pincode="486001", allow_self_pickup=True)
        self.staff = User.objects.create_superuser("9999999999", password="x")
        self.sc = Client()
        self.sc.force_login(self.staff)
        self.buyer = household()

    def test_warehouse_stock_counts_only_when_received_and_ships_from_jabalpur(self):
        mc = Client()
        mc.force_login(self.maker)
        p = live(self.maker, fulfilment="warehouse", stock=0)
        mc.post(f"/shop/manage/{p.pk}/", {"action": "stock", "change": "20"})
        p.refresh_from_db()
        self.assertEqual(p.stock, 0)  # not yet: on the way to the warehouse
        inb = Inbound.objects.get()
        self.sc.post("/console/shop/inbound/", {"inbound": inb.pk, "received": "18", "note": "2 damaged"})
        p.refresh_from_db()
        self.assertEqual(p.stock, 18)
        o = shop.place_order(self.buyer, {str(p.pk): 1}, ADDRESS)
        sh = o.shipments.get()
        self.assertEqual((sh.origin, sh.mode, sh.from_pincode, sh.zone, sh.sla_days), ("warehouse", "courier", "482004", "state", "2-3"))

    def test_pickup_from_the_seller_is_free_and_lists_the_place(self):
        p = live(self.maker)
        c = shop.cart_lines({str(p.pk): 2}, self.buyer, "462016", {f"s{self.maker.pk}": "pickup"})
        self.assertEqual((c["delivery"], c["groups"][0]["mode"], c["groups"][0]["place"]), (D("0"), "pickup", "Naigarhi, Rewa, Madhya Pradesh"))
        o = shop.place_order(self.buyer, {str(p.pk): 2}, ADDRESS, modes={f"s{self.maker.pk}": "pickup"})
        self.assertEqual((o.shipments.get().mode, o.delivery_fee), ("pickup", D("0")))
        self.ss.allow_self_pickup = False
        self.ss.save()
        self.assertEqual(shop.cart_lines({str(p.pk): 1}, self.buyer, "462016", {f"s{self.maker.pk}": "pickup"})["groups"][0]["mode"], "courier")

    def test_a_seller_without_a_pickup_address_cannot_ship_by_courier(self):
        other = make_farmer("9000000501")
        p = live(other)
        with self.assertRaises(Exception):
            shop.place_order(self.buyer, {str(p.pk): 1}, ADDRESS)

    def deliver(self, o):
        for step in ("confirmed", "packed", "dispatched"):
            shop.advance(o, step, self.staff)
        o.refresh_from_db()
        return o

    def test_unregistered_seller_gets_a_bill_of_supply(self):
        o = self.deliver(shop.place_order(self.buyer, {str(live(self.maker).pk): 1}, ADDRESS))
        kinds = sorted(o.invoices.values_list("kind", flat=True))
        self.assertEqual(kinds, ["platform", "supply"])
        inv = o.invoices.get(kind="supply")
        self.assertEqual(inv.data["totals"]["igst"], "0")
        self.assertTrue(inv.number.startswith(f"S{self.maker.pk}/"))
        bc = Client()
        bc.force_login(self.buyer)
        self.assertContains(bc.get(f"/shop/invoice/{inv.number}/"), "BILL OF SUPPLY")
        self.assertEqual(Client().get(f"/shop/invoice/{inv.number}/").status_code, 404)  # strangers: not even that it exists

    @override_settings(GSTIN="23AAAAA0000A1Z5")
    def test_registered_seller_tax_invoice_cgst_sgst_or_igst_and_tcs(self):
        self.ss.gstin = "23BBBBB1111B1Z5"
        self.ss.save()
        p = live(self.maker, category="food", gst_rate=D("5"), hsn="1904", price=D("105"), asked_price=D("105"), fssai_no="12345678901234")
        o = self.deliver(shop.place_order(self.buyer, {str(p.pk): 2}, ADDRESS))  # Rewa (MP) to Bhopal (MP): intra-state
        inv = o.invoices.get(kind="tax")
        self.assertEqual((inv.data["totals"]["taxable"], inv.data["totals"]["cgst"], inv.data["totals"]["sgst"]), ("200.00", "5.00", "5.00"))
        line = OrderLine.objects.get(order=o)
        self.assertEqual(line.tcs, D("1.00"))  # 0.5% of 200
        self.assertEqual(line.payout, line.amount - line.seller_fee - D("1"))
        plat = o.invoices.get(kind="platform")
        self.assertEqual(plat.data["lines"][0]["rate"], "18")
        o2 = self.deliver(shop.place_order(household("9844444446"), {str(p.pk): 1}, {**ADDRESS, "city": "Mumbai", "pincode": "400001"}))
        self.assertEqual(o2.invoices.get(kind="tax").data["totals"]["igst"], "5.00")  # Maharashtra: IGST
        self.assertEqual(Invoice.objects.filter(order=o).count(), 2)
        gst.issue(o)  # never twice
        self.assertEqual(Invoice.objects.filter(order=o).count(), 2)

    def test_local_courier_and_labels_per_box(self):
        o = shop.place_order(self.buyer, {str(live(self.maker).pk): 3}, ADDRESS)
        sh = o.shipments.get()
        self.sc.post(f"/console/shop/shipments/{sh.pk}/", {"action": "local", "boxes": "2", "courier_name": "DTDC", "tracking": "D111, D112"})
        sh.refresh_from_db()
        self.assertEqual((sh.status, sh.courier_name, sh.tracking_ids, sh.boxes), ("booked", "DTDC", ["D111", "D112"], 2))
        page = self.sc.get(f"/console/shop/shipments/{sh.pk}/labels/").content.decode()
        self.assertEqual(page.count('class="lab"'), 2)
        self.assertIn("Box 2 of 2", page)
        self.assertIn("COLLECT CASH", page)
        bc = Client()
        bc.force_login(self.buyer)
        self.assertContains(bc.get(f"/shop/orders/{o.number}/?lang=en"), "D111")

    @override_settings(SHIPROCKET_EMAIL="ops@example.in", SHIPROCKET_PASSWORD="x")
    def test_courier_partner_books_one_awb_and_label_per_box(self):
        o = shop.place_order(self.buyer, {str(live(self.maker).pk): 2}, ADDRESS)
        sh = o.shipments.get()
        sh.boxes = 2
        sh.save()
        replies = iter([{"token": "t"}, {"shipment_id": 11}, {"response": {"data": {"awb_code": "AWB1"}}}, {}, {"label_url": "https://l/1.pdf"},
                        {"shipment_id": 12}, {"response": {"data": {"awb_code": "AWB2"}}}, {}, {"label_url": "https://l/2.pdf"}])
        with mock.patch("shop.couriers._http", side_effect=lambda *a, **k: next(replies)):
            couriers.book(sh, "shiprocket")
        sh.refresh_from_db()
        self.assertEqual((sh.tracking_ids, sh.label_urls, sh.status), (["AWB1", "AWB2"], ["https://l/1.pdf", "https://l/2.pdf"], "booked"))
        with self.assertRaises(couriers.CourierError):
            couriers.book(sh, "delhivery")  # not connected


@override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET="secret", NOTIFY_BACKENDS=NOTIFY_MEM)
class PaymentTests(TestCase):
    def test_online_payment_is_checked_on_the_server(self):
        maker = make_farmer()
        SellerSettings.objects.create(user=maker, address="x", village="v", district="Rewa", state="Madhya Pradesh", pincode="486001")
        buyer = household()
        o = shop.place_order(buyer, {str(live(maker).pk): 1}, ADDRESS, payment="online")
        self.assertEqual((o.payment, o.paid), ("online", False))
        bc = Client()
        bc.force_login(buyer)
        with mock.patch("shop.payments.create_order", return_value="order_ABC"):
            self.assertContains(bc.get(f"/shop/orders/{o.number}/pay/"), "checkout.razorpay.com")
        bc.post(f"/shop/orders/{o.number}/pay/", {"razorpay_order_id": "order_ABC", "razorpay_payment_id": "pay_1", "razorpay_signature": "forged"})
        o.refresh_from_db()
        self.assertFalse(o.paid)
        sig = hmac.new(b"secret", b"order_ABC|pay_1", hashlib.sha256).hexdigest()
        bc.post(f"/shop/orders/{o.number}/pay/", {"razorpay_order_id": "order_ABC", "razorpay_payment_id": "pay_1", "razorpay_signature": sig})
        o.refresh_from_db()
        self.assertTrue(o.paid)

    def test_unpaid_online_orders_are_cancelled_and_stock_returns(self):
        maker = make_farmer()
        SellerSettings.objects.create(user=maker, address="x", village="v", district="Rewa", state="Madhya Pradesh", pincode="486001")
        p = live(maker)
        o = shop.place_order(household(), {str(p.pk): 2}, ADDRESS, payment="online")
        Order.objects.filter(pk=o.pk).update(created_at=timezone.now() - timezone.timedelta(hours=1))
        self.assertEqual(payments.cancel_unpaid(), 1)
        p.refresh_from_db()
        self.assertEqual(p.stock, 10)


class JourneyTests(TestCase):
    def test_visitors_and_buyers_find_the_shop_and_the_cart(self):
        page = Client().get("/login/?lang=en").content.decode()
        self.assertIn("Just browsing? Visit the shop", page)
        store = Client().get("/shop/?lang=en").content.decode()
        for bit in ('href="/shop/cart/"', 'href="/login/?as=buyer"'):
            self.assertIn(bit, store)
        bc = Client()
        bc.force_login(household())
        self.assertContains(bc.get("/buyer/?lang=en"), 'href="/shop/"')
