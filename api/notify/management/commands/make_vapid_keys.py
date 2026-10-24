import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Make a key pair for phone notifications (Web Push). Put the two lines in the server's environment once; never share the private key."

    def handle(self, *args, **opts):
        key = ec.generate_private_key(ec.SECP256R1())
        raw_priv = key.private_numbers().private_value.to_bytes(32, "big")
        raw_pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
        self.stdout.write(f"VAPID_PUBLIC_KEY={b64(raw_pub)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={b64(raw_priv)}")
        self.stdout.write("VAPID_EMAIL=mailto:you@yourdomain.in")
