"""Courier partners: book a forward shipment and get a label for every box.

Each partner switches on when its keys are set (Console > Shop > Couriers shows which). A local courier needs no
connection: staff type its name and the tracking id. Seedha Bazar's own printable labels (one per box) work with all.

Shiprocket (apiv2.shiprocket.in): log in, create an order, assign an AWB, ask for pickup, generate the label.
Delhivery (track.delhivery.com): create one package per box against a registered pickup location; labels from the packing slip.
Calls are made only when staff press "Book"; nothing here runs in the background.
"""
import json
import urllib.parse
import urllib.request

from django.conf import settings
from django.utils import timezone

from config.netutil import ssl_context


class CourierError(Exception):
    pass


def _http(url, data=None, headers=None, method=None, form=False):
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    h = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json", "Accept": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=h, method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=40, context=ssl_context()) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise CourierError(f"{e.code}: {e.read()[:200]!r}")


def _parcel(shipment):
    """Who it goes to, from where, and what is inside, in the shape couriers want."""
    o = shipment.order
    lines = list(shipment.lines.all())
    cod = o.payment == "cod" and not o.paid
    value = sum((l.amount + l.buyer_fee for l in lines), 0) + shipment.fee
    if shipment.origin == "warehouse":
        w = settings.SHOP_WAREHOUSE
        pickup = {"name": w["name"], "address": w["address"], "pincode": w["pincode"], "district": w["district"], "state": w["state"], "phone": settings.COMPANY_PHONE}
    else:
        s = shipment.seller.shop_seller
        pickup = {"name": s.legal_name or "Seller", "address": s.address, "pincode": s.pincode, "district": s.district, "state": s.state,
                  "phone": s.pickup_phone or shipment.seller.phone}
    return {"order": o, "lines": lines, "cod": cod, "value": value, "pickup": pickup, "weight_kg": max(0.1, shipment.weight_g / 1000)}


class Shiprocket:
    code, label = "shiprocket", "Shiprocket"
    BASE = "https://apiv2.shiprocket.in/v1/external"

    @staticmethod
    def configured() -> bool:
        return bool(settings.SHIPROCKET_EMAIL and settings.SHIPROCKET_PASSWORD)

    def book(self, shipment) -> dict:
        p = _parcel(shipment)
        o = p["order"]
        token = _http(f"{self.BASE}/auth/login", {"email": settings.SHIPROCKET_EMAIL, "password": settings.SHIPROCKET_PASSWORD}).get("token")
        if not token:
            raise CourierError("Shiprocket login failed")
        auth = {"Authorization": f"Bearer {token}"}
        awbs, labels = [], []
        per_box = round(p["weight_kg"] / shipment.boxes, 3)
        for box in range(1, shipment.boxes + 1):
            made = _http(f"{self.BASE}/orders/create/adhoc", {
                "order_id": f"{o.number}-{shipment.pk}-{box}", "order_date": timezone.localtime(o.created_at).strftime("%Y-%m-%d %H:%M"),
                "pickup_location": settings.SHIPROCKET_PICKUP_LOCATION, "billing_customer_name": o.name, "billing_last_name": "", "billing_address": o.address,
                "billing_city": o.city, "billing_pincode": o.pincode, "billing_state": o.state or o.city, "billing_country": "India", "billing_phone": o.phone,
                "shipping_is_billing": True, "payment_method": "COD" if p["cod"] else "Prepaid",
                "order_items": [{"name": l.title[:60], "sku": f"SB{l.product_id}", "units": l.quantity, "selling_price": float(l.unit_price)} for l in p["lines"]] if box == 1
                else [{"name": f"{o.number} box {box}", "sku": f"SB{o.pk}-B{box}", "units": 1, "selling_price": 1}],
                "sub_total": float(p["value"]) if box == 1 else 1, "length": 30, "breadth": 25, "height": 15, "weight": per_box}, auth)
            sid = made.get("shipment_id")
            if not sid:
                raise CourierError(f"Shiprocket did not create the shipment: {made}")
            awb = _http(f"{self.BASE}/courier/assign/awb", {"shipment_id": sid}, auth).get("response", {}).get("data", {}).get("awb_code", "")
            _http(f"{self.BASE}/courier/generate/pickup", {"shipment_id": [sid]}, auth)
            lab = _http(f"{self.BASE}/courier/generate/label", {"shipment_id": [sid]}, auth).get("label_url", "")
            awbs.append(awb)
            labels.append(lab)
        return {"tracking_ids": awbs, "label_urls": [x for x in labels if x], "tracking_url": f"https://shiprocket.co/tracking/{awbs[0]}" if awbs and awbs[0] else ""}


class Delhivery:
    code, label = "delhivery", "Delhivery"

    @staticmethod
    def configured() -> bool:
        return bool(settings.DELHIVERY_TOKEN and settings.DELHIVERY_PICKUP_NAME)

    def book(self, shipment) -> dict:
        p = _parcel(shipment)
        o = p["order"]
        per_box = round(shipment.weight_g / shipment.boxes)
        packages = [{"name": o.name, "add": o.address, "pin": o.pincode, "city": o.city, "state": o.state, "country": "India", "phone": o.phone,
                     "order": f"{o.number}-{shipment.pk}-{box}", "payment_mode": "COD" if p["cod"] and box == 1 else "Prepaid",
                     "cod_amount": float(p["value"]) if p["cod"] and box == 1 else 0, "total_amount": float(p["value"]) if box == 1 else 0,
                     "products_desc": ", ".join(l.title for l in p["lines"])[:200], "quantity": sum(l.quantity for l in p["lines"]) if box == 1 else 1,
                     "weight": per_box, "shipment_width": 25, "shipment_height": 15, "shipment_length": 30}
                    for box in range(1, shipment.boxes + 1)]
        data = {"format": "json", "data": json.dumps({"shipments": packages, "pickup_location": {"name": settings.DELHIVERY_PICKUP_NAME}})}
        res = _http(f"{settings.DELHIVERY_BASE}/api/cmu/create.json", data, {"Authorization": f"Token {settings.DELHIVERY_TOKEN}"}, form=True)
        awbs = [pk.get("waybill", "") for pk in res.get("packages", [])]
        if not any(awbs):
            raise CourierError(f"Delhivery did not create the shipment: {str(res)[:200]}")
        labels = [f"{settings.DELHIVERY_BASE}/api/p/packing_slip?wbns={a}&pdf=true" for a in awbs if a]
        return {"tracking_ids": awbs, "label_urls": labels, "tracking_url": f"https://www.delhivery.com/track/package/{awbs[0]}"}


PARTNERS = {c.code: c for c in (Shiprocket, Delhivery)}


def available() -> list:
    return [c for c in PARTNERS.values() if c.configured()]


def book(shipment, code: str) -> None:
    """Book with a partner; on failure the shipment keeps its state and shows the error."""
    cls = PARTNERS.get(code)
    if cls is None or not cls.configured():
        raise CourierError("This courier is not connected.")
    out = cls().book(shipment)
    shipment.courier, shipment.courier_name = code, cls.label
    shipment.tracking_ids, shipment.label_urls, shipment.tracking_url = out["tracking_ids"], out["label_urls"], out.get("tracking_url", "")
    shipment.status, shipment.booked_at, shipment.error = "booked", timezone.now(), ""
    shipment.save()


def book_local(shipment, name: str, tracking: str, url: str = "") -> None:
    """A local courier or transporter: staff give its name and tracking id(s), one per box, separated by commas."""
    ids = [t.strip() for t in tracking.split(",") if t.strip()]
    if not name.strip() or not ids:
        raise CourierError("Write the courier's name and the tracking id.")
    shipment.courier, shipment.courier_name, shipment.tracking_ids = "local", name.strip()[:60], ids
    shipment.tracking_url = url if url.startswith("https://") else ""
    shipment.status, shipment.booked_at, shipment.error = "booked", timezone.now(), ""
    shipment.save()
