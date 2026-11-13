"""Online payment through Razorpay (cards, UPI, net banking). Switched on by RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.

The order is created with Razorpay for the order total; the buyer pays in Razorpay's own window; the result is checked
on our server with the signature Razorpay sends (HMAC-SHA256 of "order_id|payment_id" with the secret) before the order
is marked paid. Unpaid online orders are cancelled after SHOP_UNPAID_MINUTES, and their stock returns.
"""
import base64
import hashlib
import hmac
import json
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from config.netutil import ssl_context


def configured() -> bool:
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def create_order(order) -> str:
    """Razorpay's order id for this order (amount in paise)."""
    body = json.dumps({"amount": int(order.total * 100), "currency": "INR", "receipt": order.number}).encode()
    auth = base64.b64encode(f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode()).decode()
    req = urllib.request.Request("https://api.razorpay.com/v1/orders", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:
        return json.loads(r.read())["id"]


def verify(razorpay_order_id: str, payment_id: str, signature: str) -> bool:
    expected = hmac.new(settings.RAZORPAY_KEY_SECRET.encode(), f"{razorpay_order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature)


def cancel_unpaid(now=None) -> int:
    """Online orders left unpaid too long are cancelled, so their stock goes back on sale."""
    from .models import Order
    from .services import cancel

    now = now or timezone.now()
    n = 0
    for o in Order.objects.filter(payment="online", paid=False, status="placed", created_at__lt=now - timedelta(minutes=settings.SHOP_UNPAID_MINUTES)):
        cancel(o, None, "Payment not completed")
        n += 1
    return n
